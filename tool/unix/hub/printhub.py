#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
#  PrintHub Pro v2.0.1  -  Print from any web page to any printer
#  by Bitdream IT  -  MIT licensed, 100% local & open source
#  PrintHub Pro - Version 2.0.0 - by Bitdream IT - MIT license
#  100% local - no cloud, no tracking.
# ------------------------------------------------------------
#  Chrome extension <-> this hub (localhost) -> ANY printer
#  NO print dialog. NO subscription. NO cloud. NO data collection.
#
#  * ZERO pip dependencies - pure Python 3.8+ standard library
#  * Cross-platform: Windows (SumatraPDF) / Linux & macOS (CUPS lp)
#  * Any printer: thermal, receipt, label, A4 - hub sees it, you print
#  * Print queue: priority, exponential retry, scheduled prints,
#    dead-letter list, duplicate blocking, printer groups + fallback
#  * Printer status (ready / offline / paper-out / error) - jobs wait
#    while the printer is offline and print automatically when back
#  * Raw printing: ESC/POS (cut, cash drawer, barcode, QR) + ZPL
#  * Print profiles (paper, tray, duplex, copies) + page ranges
#  * Security: random token on new install, header-only tokens,
#    origin allowlist, SSRF-guarded pdf_url, IP lockout, token rotate
#  * Audit log (who / site / document hash / printer / time), REPRINT
#    watermark, log rotation, diagnostics export, CSV export, dashboard
#  * Job history: SQLite, reprint anytime, survives restarts
#  * Token auth, CORS + Private-Network headers, localhost by default
#
#  Quick start:   python printhub.py serve
#  Health check:  http://127.0.0.1:9235/health
#  Dashboard:     http://127.0.0.1:9235/dashboard?token=...
#  Full check:    python printhub.py doctor
#  Help:          python printhub.py help
# ============================================================

import base64
import csv
import hashlib
import hmac
import html
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, parse_qsl

VERSION = "2.0.2"
BRANDING = ("PrintHub Pro - Version %s - by Bitdream IT - MIT license - "
            "100%% local - no cloud, no tracking" % VERSION)
APP_NAME = "PrintHub Pro"
VENDOR = "Bitdream IT"
GITHUB_REPO = "bitdreamit/PrintHub-Pro"
GITHUB_RELEASES = "https://github.com/%s/releases" % GITHUB_REPO
SERVICE_NAME = "PrintHub"          # optional Windows service (services.msc)
SERVICE_DISPLAYNAME = "PrintHub Pro Service"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HIDE = 0x08000000 if IS_WIN else 0          # no console window flash on Windows
MAX_BODY = 40 * 1024 * 1024                 # 40 MB hard cap on request body
MAX_PDF = 25 * 1024 * 1024                  # 25 MB cap for downloaded pdf_url
HISTORY_DEFAULT = 100                       # Ultraprint-style: last 100 jobs
LEGACY_TOKEN = "PrintHub-2024"              # pre-2.0 default (old installs)

# ------------------------------------------------------------
# Configuration:  defaults <- config.json <- environment variables
# ------------------------------------------------------------
# config.json lives in the data dir and PERSISTS settings between runs.
# New settings (allowed_origins, printer_groups, profiles, retries,
# audit, watermark, peers ...) go here and on the extension Options page.
# Defaults intentionally keep the pre-2.0 behaviour wherever possible:
#   allowed_origins []      = allow all origins (as before)
#   token_header_only False = query/body tokens still accepted (old installs)
#   reprint_reason_required False = reprint needs no reason (as before)
#   peer_forwarding False   = never forward jobs to peer hubs (as before)
CFG = {
    "host": os.environ.get("PRINTHUB_HOST", "127.0.0.1"),     # localhost by default
    "port": int(os.environ.get("PRINTHUB_PORT", "9235")),
    "token": os.environ.get("PRINTHUB_TOKEN", LEGACY_TOKEN),
    "printer": os.environ.get("PRINTHUB_PRINTER", ""),        # empty = OS default
    "data_dir": os.environ.get(
        "PRINTHUB_DATA",
        os.path.join(os.path.expanduser("~"), ".printhub")),
    # destination "file": save the rendered PDF here instead of printing
    "file_dir": os.environ.get("PRINTHUB_FILE_DIR", ""),
    "keep_files": True,   # keep printed files so /reprint works

    # ---- v2.0 settings (config.json + /config API + Options page) ----
    "token_header_only": False,       # False = accept token in query/body too
    "allowed_origins": [],            # [] = allow every origin (old behaviour)
    "pdf_url_allowed_hosts": [],      # hosts exempt from the private-IP block
    "max_auth_failures": 10,          # failed tokens before ...
    "lockout_minutes": 5,             # ... the IP is locked this many minutes
    "lockout_exempt_loopback": True,  # 127.0.0.1/::1 are NEVER locked
                                      # (every Chrome window/profile shares
                                      #  that ONE IP - v2.0.1: a stale token
                                      #  in one window must not lock out
                                      #  the dashboard, tray and extension)
    "printer_groups": {},             # {"Front Desk": ["A", "B"]} fallback order
    "profiles": {},                   # {"Invoice": {"paper": "a4", "duplex": True}}
    "max_retries": 2,                 # exponential retry (0 = off, 1.7.2 style)
    "retry_base_seconds": 30,         # backoff: 30s, 60s, 120s ...
    "dedupe_minutes": 5,              # block identical jobs inside this window
    "hold_offline": True,             # hold jobs while the printer is offline
    "audit_enabled": True,
    "reprint_watermark": False,       # stamp "REPRINT" on reprinted pages
    "reprint_reason_required": False,
    "peer_hubs": [],                  # [{"url": "http://ip:9235", "token": "..."}]
    "peer_forwarding": False,         # forward jobs to a live peer hub
    "log_max_mb": 5,                  # hub.log rotates after this size
    "log_backups": 3,                 # ... keeping this many old logs
}

# env overrides that win over config.json (back-compat for 1.x users)
for _k in ("token", "printer", "file_dir"):
    pass  # already applied above; config.json is applied in init_config()

CONFIG_KEYS = ("token", "token_header_only", "allowed_origins",
               "pdf_url_allowed_hosts", "max_auth_failures",
               "lockout_minutes", "lockout_exempt_loopback",
               "printer_groups", "profiles",
               "max_retries", "retry_base_seconds", "dedupe_minutes",
               "hold_offline", "audit_enabled", "reprint_watermark",
               "reprint_reason_required", "peer_hubs", "peer_forwarding",
               "log_max_mb", "log_backups", "printer", "file_dir")
CONFIG_TYPES = {"token_header_only": bool, "allowed_origins": list,
                "pdf_url_allowed_hosts": list, "max_auth_failures": int,
                "lockout_minutes": int, "lockout_exempt_loopback": bool,
                "printer_groups": dict,
                "profiles": dict, "max_retries": int,
                "retry_base_seconds": int, "dedupe_minutes": int,
                "hold_offline": bool, "audit_enabled": bool,
                "reprint_watermark": bool, "reprint_reason_required": bool,
                "peer_hubs": list, "peer_forwarding": bool,
                "log_max_mb": int, "log_backups": int}

DEFAULT_TOKEN_WARNING = False   # True while the legacy default token is active


def config_path():
    return os.path.join(CFG["data_dir"], "config.json")


def read_config_file():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_config_file(data):
    """Persist settings to config.json (atomic enough for a local hub)."""
    ensure_dirs()
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config_path())


def init_config():
    """Merge config.json into CFG (env vars keep winning) and bootstrap the
    v2.0 token policy:
      * brand-new install -> RANDOM token saved to config.json
        (the old shared default 'PrintHub-2024' is gone) + header-only auth
      * old install (existing history.db / explicit env token) -> keeps
        working exactly as before, but /health raises
        default_token_warning so the UI can ask the user to change it.
    Called from db_init() and every CLI command - always safe to re-run."""
    global DEFAULT_TOKEN_WARNING
    ensure_dirs()
    disk = read_config_file()
    fresh = not os.path.isfile(db_path()) and not disk
    for key in CONFIG_KEYS:
        if key in disk:
            want = CONFIG_TYPES.get(key)
            v = disk[key]
            try:
                if want is bool:
                    v = bool(v)
                elif want is int:
                    v = int(v)
                elif want is list:
                    v = list(v) if isinstance(v, list) else []
                elif want is dict:
                    v = dict(v) if isinstance(v, dict) else {}
            except (TypeError, ValueError):
                continue
            CFG[key] = v
    env_token = os.environ.get("PRINTHUB_TOKEN")
    if "token" not in disk and not env_token:
        if fresh:
            # NEW INSTALL: generate a private random token, persist it
            CFG["token"] = secrets.token_urlsafe(24)
            disk = {k: CFG[k] for k in CONFIG_KEYS}
            disk["token_header_only"] = True   # strict mode for new installs
            CFG["token_header_only"] = True
            write_config_file(disk)
            log("[TOKEN] new install - generated a private random token and"
                " saved it to %s" % config_path())
            log("[TOKEN] token: %s" % CFG["token"])
            log("[TOKEN] enter this token once in the extension Options page.")
        else:
            # OLD INSTALL (1.x): keep the legacy default so nothing breaks
            CFG["token"] = LEGACY_TOKEN
    else:
        CFG["token"] = env_token or str(CFG["token"])
    DEFAULT_TOKEN_WARNING = (CFG["token"] == LEGACY_TOKEN)
    if DEFAULT_TOKEN_WARNING:
        log("[SECURITY] the default token '%s' is still in use - please"
            " change it:  python printhub.py token-rotate" % LEGACY_TOKEN)
    return CFG

def default_file_dir():
    """Preferred save-as-PDF folder: ~/Downloads/PrintHub, with a safe
    fallback to ~/.printhub/files when Downloads is not writable."""
    if CFG.get("file_dir"):
        return CFG["file_dir"]
    dl = os.path.join(os.path.expanduser("~"), "Downloads", "PrintHub")
    try:
        os.makedirs(dl, exist_ok=True)
        return dl
    except OSError:
        return os.path.join(CFG["data_dir"], "files")
SUMATRA_HINT = "winget install SumatraPDF.SumatraPDF   (or download from kjkpub.sf.net/sumatrapdf)"

def ensure_dirs():
    os.makedirs(CFG["data_dir"], exist_ok=True)
    os.makedirs(os.path.join(CFG["data_dir"], "jobs"), exist_ok=True)
    try:
        os.makedirs(default_file_dir(), exist_ok=True)
    except OSError:
        pass

def db_path():
    return os.path.join(CFG["data_dir"], "history.db")

def rotate_log_if_needed(path):
    """v2.0 log rotation: hub.log -> hub.log.1 -> ... (CFG['log_backups'])."""
    try:
        if os.path.getsize(path) < CFG["log_max_mb"] * 1024 * 1024:
            return
        keep = max(1, int(CFG["log_backups"]))
        for i in range(keep - 1, 0, -1):
            src, dst = "%s.%d" % (path, i), "%s.%d" % (path, i + 1)
            if os.path.isfile(src):
                os.replace(src, dst)
        os.replace(path, path + ".1")
    except OSError:
        pass


def log(msg):
    """Console + file log with timestamp and automatic size rotation."""
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        ensure_dirs()
        path = os.path.join(CFG["data_dir"], "hub.log")
        rotate_log_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ------------------------------------------------------------
# Print history + queue state (SQLite) - thread-safe via one lock
# v2.0: the v1.x schema is MIGRATED in place (ALTER TABLE) so old
# databases keep working untouched - no export/import, no re-init.
# ------------------------------------------------------------
_DB_LOCK = threading.Lock()

# extra columns added on top of the v1.x jobs table (missing ones are
# appended automatically at startup; existing rows keep their values)
JOB_COLUMNS = {
    "priority":       "INTEGER DEFAULT 5",    # 1 = urgent ... 9 = low
    "attempts":       "INTEGER DEFAULT 0",    # retry counter
    "next_attempt_at": "TEXT",                # ISO - retry backoff / schedule
    "run_at":         "TEXT",                 # ISO - scheduled print time
    "dedupe_key":     "TEXT",                 # duplicate-blocking fingerprint
    "content_hash":   "TEXT",                 # sha256 of the document bytes
    "site":           "TEXT",                 # which site/origin requested it
    "reason":         "TEXT",                 # reprint reason (audit)
    "profile":        "TEXT",                 # print profile applied
    "pages":          "TEXT",                 # page range "1-3,5"
    "duplex":         "TEXT",
    "paper_size":     "TEXT",
    "tray":           "TEXT",
    "watermarked":    "INTEGER DEFAULT 0",
    "held_reason":    "TEXT",                 # why the job is on hold
    "peer":           "TEXT",                 # peer hub the job was sent to
}

AUDIT_EVENTS = ("print.submitted", "print.completed", "print.failed",
                "print.held", "print.requeued", "reprint", "job.canceled",
                "job.dead", "job.forwarded", "auth.failed", "auth.locked",
                "token.rotated", "config.changed", "queue.paused",
                "queue.resumed", "queue.cleared", "audit.purged")


def db():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    ensure_dirs()
    init_config()
    with _DB_LOCK, db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   kind       TEXT NOT NULL,            -- a4 | thermal | image | page
                   title      TEXT,
                   printer    TEXT,
                   copies     INTEGER DEFAULT 1,
                   status     TEXT NOT NULL,            -- queued|printing|printed|failed|canceled|saved
                   error      TEXT,
                   file_path  TEXT,
                   source     TEXT DEFAULT 'api',      -- extension | website | api | cli
                   origin_ip  TEXT,
                   duration_ms INTEGER DEFAULT 0
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit (
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts        TEXT NOT NULL,
                   event     TEXT NOT NULL,
                   job_id    INTEGER,
                   actor     TEXT,
                   site      TEXT,
                   ip        TEXT,
                   doc_hash  TEXT,
                   printer   TEXT,
                   reason    TEXT,
                   details   TEXT
               )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        # v1.x -> v2.0 migration: add any missing columns, never touch data
        have = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        for col, decl in JOB_COLUMNS.items():
            if col not in have:
                conn.execute("ALTER TABLE jobs ADD COLUMN %s %s" % (col, decl))
                log("[MIGRATE] jobs.%s column added (v2.0 schema)" % col)

def db_add(kind, title, printer, copies, file_path, source, origin_ip,
           status="queued", **extra):
    """Insert a job. Extra v2.0 fields ride along as kwargs (whitelisted
    against the schema so old callers stay source-compatible)."""
    allowed = {"priority", "attempts", "next_attempt_at", "run_at",
               "dedupe_key", "content_hash", "site", "reason", "profile",
               "pages", "duplex", "paper_size", "tray", "watermarked",
               "held_reason", "peer", "duration_ms", "error"}
    cols = ["created_at", "kind", "title", "printer", "copies", "status",
            "file_path", "source", "origin_ip"]
    vals = [datetime.now().isoformat(timespec="seconds"), kind, title,
            printer, copies, status, file_path, source, origin_ip]
    for k, v in (extra or {}).items():
        if k in allowed and v is not None:
            cols.append(k)
            vals.append(v)
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (%s) VALUES (%s)" % (",".join(cols),
                                                   ",".join("?" * len(cols))),
            vals)
        return cur.lastrowid

def db_update(job_id, **fields):
    sets = ", ".join("%s=?" % k for k in fields)
    with _DB_LOCK, db() as conn:
        conn.execute("UPDATE jobs SET %s WHERE id=?" % sets, (*fields.values(), job_id))

def db_get(job_id):
    with _DB_LOCK, db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

def db_list(limit=HISTORY_DEFAULT, status=None):
    with _DB_LOCK, db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, int(limit))).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

def db_next_queued():
    """Next printable job: priority first (1 = urgent), then FIFO, and
    only jobs whose retry backoff / scheduled time has come due."""
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' AND "
            "(next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY priority ASC, id ASC LIMIT 1", (now,)
        ).fetchone()
        return dict(row) if row else None

def db_promote_scheduled():
    """Move due scheduled jobs into the live queue (and clear their
    future retry timestamp so the worker picks them up). Returns count."""
    now = datetime.now().isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='queued', next_attempt_at=NULL "
            "WHERE status='scheduled' AND run_at IS NOT NULL AND run_at <= ?",
            (now,))
        return cur.rowcount or 0

def db_find_duplicate(dedupe_key, minutes):
    """Recent alive job with the same fingerprint -> duplicate blocked."""
    if not dedupe_key or minutes <= 0:
        return None
    cutoff = (datetime.now() - timedelta(minutes=minutes)) \
        .isoformat(timespec="seconds")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE dedupe_key=? AND created_at >= ? AND "
            "status NOT IN ('failed','canceled','dead') "
            "ORDER BY id DESC LIMIT 1", (dedupe_key, cutoff)).fetchone()
        return dict(row) if row else None

def db_count_pending():
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','printing')"
        ).fetchone()
        return int(row["n"])

def db_count_today():
    today = datetime.now().strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE created_at LIKE ?",
            (today + "%",)).fetchone()
        return int(row["n"])

def db_count_held():
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status='held'").fetchone()
        return int(row["n"])

def db_stats():
    """Success rate + queue size for the dashboard (last 7 days + today)."""
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        by = {}
        for r in conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status"):
            by[r["status"]] = int(r["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status='printed' AND created_at >= ?",
            (week,)).fetchone()
        ok7 = int(row["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('failed','dead') AND created_at >= ?",
            (week,)).fetchone()
        bad7 = int(row["n"])
    total7 = ok7 + bad7
    return {
        "by_status": by,
        "queue_size": db_count_pending() + db_count_held(),
        "jobs_today": db_count_today(),
        "success_rate": round(100.0 * ok7 / total7, 1) if total7 else None,
        "printed_7d": ok7,
        "failed_7d": bad7,
    }

# ------------------------------------------------------------
# Audit log (v2.0): who / which site / document hash / printer / time
# ------------------------------------------------------------
def db_audit(event, job_id=None, actor=None, site=None, ip=None,
             doc_hash=None, printer=None, reason=None, details=None):
    if not CFG.get("audit_enabled", True):
        return
    try:
        with _DB_LOCK, db() as conn:
            conn.execute(
                "INSERT INTO audit (ts, event, job_id, actor, site, ip,"
                " doc_hash, printer, reason, details)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), event,
                 job_id, actor, site, ip, doc_hash, printer, reason,
                 details))
    except Exception as e:
        log("[WARN] audit write failed: %s" % e)

def audit_list(limit=50, event=None):
    q = "SELECT * FROM audit"
    args = []
    if event:
        q += " WHERE event=?"
        args.append(event)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with _DB_LOCK, db() as conn:
        return [dict(r) for r in conn.execute(q, args)]

def audit_purge(days):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _DB_LOCK, db() as conn:
        cur = conn.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
        n = cur.rowcount or 0
    if n:
        db_audit("audit.purged", details="%d entries older than %dd removed" % (n, days))
    return n

# ------------------------------------------------------------
# Printer + browser discovery (best effort, pure stdlib)
# ------------------------------------------------------------
def find_sumatra():
    """Locate SumatraPDF.exe on common Windows paths."""
    if not IS_WIN:
        return None
    cands = [
        r"C:\Tools\SumatraPDF.exe",
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe"),
        shutil.which("SumatraPDF.exe"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None

def find_browser():
    """Locate a Chromium browser for headless HTML->PDF (Chrome, Edge, Chromium)."""
    if IS_WIN:
        cands = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
        return None
    if IS_MAC:
        cands = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for c in cands:
            if os.path.exists(c):
                return c
        return None
    for name in ("google-chrome", "google-chrome-stable", "microsoft-edge",
                 "microsoft-edge-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None

def list_printers():
    """Return list of installed printer names (best effort)."""
    try:
        if IS_WIN:
            ps = "Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name"
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            names = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
            return names
        else:
            out = subprocess.run(["lpstat", "-e"], capture_output=True,
                                 text=True, timeout=10)
            names = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
            if not names:  # older CUPS: try -p and strip state
                out = subprocess.run(["lpstat", "-p"], capture_output=True,
                                     text=True, timeout=10)
                for l in (out.stdout or "").splitlines():
                    if l.startswith("printer "):
                        names.append(l.split()[1])
            return names
    except Exception as e:
        log("[WARN] list_printers failed: %s" % e)
        return []

def default_printer():
    """Return the OS default printer name (best effort)."""
    try:
        if IS_WIN:
            ps = ("(Get-CimInstance Win32_Printer | Where-Object Default)"
                  ".Name")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            name = (out.stdout or "").strip()
            return name or None
        else:
            out = subprocess.run(["lpstat", "-d"], capture_output=True,
                                 text=True, timeout=10)
            for l in (out.stdout or "").splitlines():
                if "system default destination" in l:
                    return l.split(":")[-1].strip()
            return None
    except Exception:
        return None

# ------------------------------------------------------------
# Printer STATUS (v2.0): ready / offline / paper-out / error
# Windows: Win32_Printer via PowerShell; Unix: lpstat -p states.
# Cached 20 s so the worker loop can poll it freely.
# ------------------------------------------------------------
_PS_CACHE = {"t": 0.0, "v": {}}

def _printer_status_windows():
    ps = ("Get-CimInstance Win32_Printer | ForEach-Object {"
          "\"{0}|{1}|{2}|{3}\" -f $_.Name,$_.PrinterStatus,"
          "$_.DetectedErrorState,[int]([bool]$_.WorkOffline) }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=20,
                         creationflags=HIDE)
    res = {}
    for line in (out.stdout or "").splitlines():
        parts = (line or "").strip().split("|")
        if len(parts) != 4 or not parts[0]:
            continue
        name = parts[0]
        try:
            pstat, derr, woff = int(parts[1] or 0), int(parts[2] or 0), int(parts[3] or 0)
        except ValueError:
            pstat, derr, woff = 0, 0, 0
        if woff or pstat == 7 or derr == 8:
            st = "offline"
        elif derr in (3, 4):
            st = "paper-out"
        elif derr in (5, 6, 7, 9, 10) or pstat == 6:
            st = "error"
        elif pstat in (3, 4, 5) or derr == 2 or pstat == 0:
            st = "ready"
        else:
            st = "unknown"
        res[name] = st
    return res

def _printer_status_unix():
    out = subprocess.run(["lpstat", "-p"], capture_output=True,
                         text=True, timeout=10)
    res = {}
    for line in (out.stdout or "").splitlines():
        m = re.match(r"^printer (\S+) (.+)$", line or "")
        if not m:
            continue
        name, state = m.group(1), m.group(2)
        if "disabled" in state:
            res[name] = "offline"
        elif "printing" in state or "idle" in state or "processing" in state:
            res[name] = "ready"
        else:
            res[name] = "unknown"
    return res

def printers_status(force=False):
    """{printer_name: 'ready'|'offline'|'paper-out'|'error'|'unknown'}."""
    if not force and time.time() - _PS_CACHE["t"] < 20 and _PS_CACHE["v"]:
        return _PS_CACHE["v"]
    try:
        res = _printer_status_windows() if IS_WIN else _printer_status_unix()
    except Exception as e:
        log("[WARN] printer status check failed: %s" % e)
        res = {}
    if res:
        _PS_CACHE["t"] = time.time()
        _PS_CACHE["v"] = res
    return res

def printer_ready(name=""):
    """'ready' | 'offline' | 'paper-out' | 'error' | 'unknown'.
    Empty name = the OS default printer. Unknown printers never block."""
    st = printers_status()
    target = name or CFG["printer"] or default_printer() or ""
    if not target:
        return "unknown"
    if target in st:
        return st[target]
    # CUPS may report the class/member differently - stay permissive
    return "unknown"

def printer_group_members(name):
    """Members of a configured printer group (ordered fallback list)."""
    groups = CFG.get("printer_groups") or {}
    members = groups.get(name)
    if isinstance(members, dict):
        members = members.get("members")
    return [str(m) for m in members] if isinstance(members, list) else []

def pick_group_printer(name):
    """First group member whose status is not offline/paper-out/error.
    Falls back to the first member when nothing is confirmed ready."""
    members = printer_group_members(name)
    if not members:
        return None
    st = printers_status()
    for m in members:
        if st.get(m, "unknown") not in ("offline", "paper-out", "error"):
            return m
    return members[0]

def _glob_to_regex(pat):
    """Simple glob -> regex ('*' matches anything; used for origins/hosts)."""
    rx = "".join(".*" if c == "*" else re.escape(c) for c in (pat or ""))
    return re.compile("^" + rx + "$", re.I)

def origin_allowed(origin):
    """allowed_origins: [] = allow all (old behaviour). Patterns like
    '*.htncr.org' or 'https://intranet.example.com' otherwise."""
    rules = CFG.get("allowed_origins") or []
    if not rules:
        return True
    if not origin:
        return False
    o = str(origin).strip().lower()
    for pat in rules:
        p = str(pat).strip().lower()
        if p and _glob_to_regex(p if "://" in p else "*://" + p).match(o):
            return True
    return False

def host_allowed(host):
    """pdf_url allowlist (overrides the private-IP block)."""
    host = (host or "").lower()
    for pat in (CFG.get("pdf_url_allowed_hosts") or []):
        p = str(pat).strip().lower()
        if p and (_glob_to_regex(p).match(host) or p == host):
            return True
    return False

def pdf_url_guard(url):
    """SSRF guard for pdf_url (v2.0):
      * file://, ftp:// and every non-http(s) scheme are blocked
      * hosts resolving to private/loopback/link-local addresses are
        blocked unless listed in pdf_url_allowed_hosts (config.json)
    Raises ValueError with a friendly message; returns the url when OK."""
    try:
        p = urlparse(str(url))
    except Exception:
        raise ValueError("pdf_url is not a valid URL")
    if p.scheme not in ("http", "https"):
        raise ValueError(
            "pdf_url scheme '%s:' is blocked - only http/https URLs are"
            " allowed (file:// and ftp:// are disabled for security)" % p.scheme)
    host = p.hostname or ""
    if not host:
        raise ValueError("pdf_url has no host name")
    if host_allowed(host):
        return url
    ip_raw = host.strip("[]")
    try:
        candidates = [ipaddress.ip_address(ip_raw)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
            candidates = [ipaddress.ip_address(i[4][0]) for i in infos]
        except socket.gaierror as e:
            raise ValueError("pdf_url host '%s' cannot be resolved (%s)" % (host, e))
    for ip in candidates:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(
                "pdf_url host '%s' resolves to a private/local address"
                " (%s) - blocked. Add it to 'pdf_url_allowed_hosts' in"
                " config.json if this is intentional." % (host, ip))
    return url

# ------------------------------------------------------------
# Minimal PDF builders (pure Python): text receipts/pages + JPEG images
# ------------------------------------------------------------
def _pdf_escape(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

def jpeg_size(data):
    """Scan JPEG markers for SOF0..SO F15 to get (width, height). Pure stdlib."""
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = (data[i + 5] << 8) | data[i + 6]
            w = (data[i + 7] << 8) | data[i + 8]
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        seg_len = (data[i + 2] << 8) | data[i + 3]
        i += 2 + seg_len
    return None, None

def image_pdf_bytes(jpeg, title="screenshot", paper="a4", landscape=None):
    """
    Wrap a JPEG image into a single-page PDF (pure Python, DCTDecode).
    paper="a4" (default) or "thermal" (80mm roll, image scaled to width).
    landscape=True forces A4 landscape for wide screenshots.
    Returns (pdf_bytes, suggested_filename).
    """
    MM = 72 / 25.4
    w, h = jpeg_size(jpeg)
    if not w or not h:
        raise ValueError("not a valid JPEG image (sender must use image/jpeg)")
    landscape = bool(landscape) if landscape is not None else (w > h)
    if paper == "thermal":
        PW, PH = 80 * MM, 297 * MM
        margin = 2 * MM
    elif landscape:
        PW, PH = 297 * MM, 210 * MM
        margin = 8 * MM
    else:
        PW, PH = 210 * MM, 297 * MM
        margin = 10 * MM
    avail_w, avail_h = PW - 2 * margin, PH - 2 * margin
    scale = min(avail_w / w, avail_h / h)
    dw, dh = w * scale, h * scale
    x, y = (PW - dw) / 2.0, (PH - dh) / 2.0

    img_id, page_id, cont_id, pages_id, cat_id = 1, 2, 3, 4, 5
    content = ("q %.2f 0 0 %.2f %.2f %.2f cm /Im0 Do Q" % (dw, dh, x, y)).encode()
    objs = {
        img_id: ("<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                 "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                 "/Length %d >>\nstream\n" % (w, h, len(jpeg))).encode()
                 + jpeg + b"\nendstream",
        cont_id: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        page_id: ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.1f %.1f] "
                  "/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                  % (pages_id, PW, PH, img_id, cont_id)).encode(),
        pages_id: ("<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % page_id).encode(),
        cat_id: ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode(),
    }
    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (cat_id + 1)).encode()
    out += b"0000000000 65535 f \n"
    for idx in sorted(objs):
        out += ("%010d 00000 n \n" % offsets[idx]).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (cat_id + 1, cat_id, xref)).encode()
    fname = "%s-%s.pdf" % (title or "image", datetime.now().strftime("%Y%m%d%H%M%S"))
    return bytes(out), "".join(c for c in fname if c.isalnum() or c in "-._")

def thermal_pdf_bytes(text, title="receipt", paper="thermal"):
    """
    Build a minimal PDF from plain text (pure Python, no dependencies):
      paper="thermal" -> 80mm receipt roll, Courier 8pt
      paper="a4"      -> 210x297mm page, Courier 11pt
    Markers: #big <line> = large bold heading, |center| <line> = centered.
    Returns (bytes, filename).
    """
    MM = 72 / 25.4
    if paper == "a4":
        W = 210 * MM
        PAGE_H = 297 * MM
        font_pt, lead, max_cols = 11, 5.5 * MM, 95
        big_pt, big_lead = 18, 9 * MM
        top_mm, bottom_pad = 15, 40
    else:
        W = 80 * MM                        # 80mm paper
        PAGE_H = None                      # auto height (receipt roll)
        font_pt, lead, max_cols = 8, 3.6 * MM, 40
        big_pt, big_lead = 13, 6.5 * MM
        top_mm, bottom_pad = 8, 10
    LM = 4 * MM
    lines = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith("#big"):
            lines.append(("big", raw[4:].strip()))
        elif raw.startswith("|center|"):
            lines.append(("center", raw[8:].strip()))
        else:
            lines.append(("normal", raw))
    # paginate every N lines
    per_page = 70 if PAGE_H is None else int((PAGE_H - 2 * top_mm * MM) / lead) - 2
    pages, cur = [], []
    for ln in lines:
        cur.append(ln)
        if len(cur) >= per_page:
            pages.append(cur); cur = []
    pages.append(cur or [("normal", "")])

    out = bytearray()
    n = len(pages)
    objs = {}

    def add_obj(idx, body):
        objs[idx] = body

    # fonts: F1 Courier, F2 Courier-Bold
    add_obj(1, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    add_obj(2, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>")

    page_ids = []
    next_id = 3
    content_ids = []
    for pi, page in enumerate(pages):
        H = pages_h(page) if PAGE_H is None else PAGE_H
        stream = []
        y = H - top_mm * MM
        for style, txt in page:
            if style == "big":
                stream.append("BT /F2 %d Tf %d %.1f Td (%s) Tj ET" %
                              (big_pt, int(LM), y, _pdf_escape(txt[:max_cols])))
                y -= big_lead
            else:
                t = txt[:max_cols]
                if style == "center":
                    pad = max(0, (max_cols - len(t)) // 2)
                    t = " " * pad + t
                stream.append("BT /F1 %d Tf %d %.1f Td (%s) Tj ET" %
                              (font_pt, int(LM), y, _pdf_escape(t)))
                y -= lead
        data = ("\n".join(stream)).encode("latin-1", "replace")
        cid = next_id; next_id += 1
        content_ids.append(cid)
        add_obj(cid, b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")

    pages_id = next_id; next_id += 1
    for pi in range(n):
        pid = next_id; next_id += 1
        page_ids.append(pid)
        H = pages_h(pages[pi]) if PAGE_H is None else PAGE_H
        add_obj(pid,
                ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.1f %.1f] "
                 "/Resources << /Font << /F1 1 0 R /F2 2 0 R >> >> "
                 "/Contents %d 0 R >>" % (pages_id, W, H, content_ids[pi])
                 ).encode())
    kids = " ".join("%d 0 R" % p for p in page_ids)
    add_obj(pages_id,
            ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode())
    cat_id = next_id; next_id += 1
    add_obj(cat_id, ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode())

    # serialize
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (next_id)).encode()
    out += b"0000000000 65535 f \n"
    for idx in sorted(objs):
        out += ("%010d 00000 n \n" % offsets[idx]).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (next_id, cat_id, xref)).encode()
    fname = "%s-%s.pdf" % (title or "receipt", datetime.now().strftime("%Y%m%d%H%M%S"))
    return bytes(out), "".join(c for c in fname if c.isalnum() or c in "-._")

def pages_h(page_lines):
    MM = 72 / 25.4
    h = 10 * MM + len(page_lines) * 3.6 * MM
    return max(60 * MM, h)

# ------------------------------------------------------------
# HTML / web page -> PDF via headless Chrome or Edge (zero pip)
# ------------------------------------------------------------
def html_to_pdf_bytes(source, is_url=True, title="page"):
    """
    Render an HTML string or a URL to PDF using headless Chrome/Edge.
    Uses a throwaway profile dir so it never fights the user's browser.
    Returns (pdf_bytes, suggested_filename).
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError(
            "No Chrome/Edge found for page printing. Install Google Chrome"
            " (or print PDFs instead - SumatraPDF handles those directly).")
    out_path = os.path.join(tempfile.gettempdir(),
                            "printhub-%s.pdf" % os.getpid())
    profile = tempfile.mkdtemp(prefix="printhub-profile-")
    if is_url:
        target = source
    else:
        html_path = os.path.join(tempfile.gettempdir(),
                                 "printhub-%s.html" % os.getpid())
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(source)
        target = "file:///" + html_path.replace("\\", "/").lstrip("/")

    def attempt(headless_flag):
        cmd = [exe, headless_flag, "--disable-gpu", "--no-first-run",
               "--disable-extensions", "--user-data-dir=" + profile,
               "--no-pdf-header-footer",
               "--print-to-pdf=" + out_path, target]
        if IS_WIN:
            return subprocess.run(cmd, capture_output=True, timeout=120,
                                  creationflags=HIDE)
        return subprocess.run(cmd, capture_output=True, timeout=120)

    pdf = None
    try:
        for flag in ("--headless=new", "--headless"):
            try:
                proc = attempt(flag)
            except subprocess.TimeoutExpired:
                continue
            if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                with open(out_path, "rb") as f:
                    pdf = f.read()
                break
        if not pdf or not pdf[:5].startswith(b"%PDF"):
            raise RuntimeError(
                "headless browser did not produce a PDF (page blocked,"
                " login required, or browser too old)")
    finally:
        for p in (out_path,):
            try:
                os.unlink(p)
            except OSError:
                pass
        shutil.rmtree(profile, ignore_errors=True)
    fname = "%s-%s.pdf" % (title or "page", datetime.now().strftime("%Y%m%d%H%M%S"))
    return pdf, "".join(c for c in fname if c.isalnum() or c in "-._")

# ------------------------------------------------------------
# Silent printing back-end (cancellable: keeps a handle to the process)
# ------------------------------------------------------------
_CURRENT_LOCK = threading.Lock()
_CURRENT = {"id": None, "proc": None}

def print_file(path, kind="a4", printer="", copies=1, job_id=None,
               pages=None, duplex=None, paper_size=None, tray=None):
    """
    Print a PDF file SILENTLY (no dialog) to the given printer
    or the OS default. Raises RuntimeError with a friendly message.
    The spawned process is registered so /jobs/{id}/cancel can kill it.
    v2.0 options: pages ("1-3,5"), duplex ("simplex"|"duplex"|"long"|"short"),
    paper_size ("A4", "Letter"...), tray ("Tray2" - CUPS only; SumatraPDF
    cannot select trays, logged as a warning).
    """
    copies = max(1, min(int(copies or 1), 50))
    target = printer or CFG["printer"] or default_printer() or ""

    def register(proc):
        with _CURRENT_LOCK:
            _CURRENT["id"] = job_id
            _CURRENT["proc"] = proc
        return proc

    def duplex_flag():
        d = (duplex or "").lower()
        if d in ("long", "long-edge", "twosided-long-edge"):
            return "duplexlong"
        if d in ("short", "short-edge", "twosided-short-edge"):
            return "duplexshort"
        if d in ("1", "true", "on", "yes", "duplex"):
            return "duplex"
        if d in ("0", "false", "off", "no", "one", "simplex"):
            return "simplex"
        return None

    try:
        if IS_WIN:
            sumatra = find_sumatra()
            if not sumatra:
                raise RuntimeError(
                    "SumatraPDF not found. Install it first: %s" % SUMATRA_HINT)
            parts = []
            if pages:
                parts.append(re.sub(r"[^0-9,\-]", "", str(pages)))
            df = duplex_flag()
            if df:
                parts.append(df)
            if paper_size:
                parts.append("paper=%s" % re.sub(r"[^A-Za-z0-9]", "",
                                                 str(paper_size)) or "A4")
            if tray:
                log("[PRINT] note: SumatraPDF cannot select a paper tray"
                    " ('%s' ignored) - tray printing needs CUPS" % tray)
            parts.append("noscale" if kind in ("thermal", "image-thermal")
                         else "shrinkfit")
            if copies > 1:
                parts.append("%dx" % copies)
            cmd = [sumatra, "-silent", "-exit-when-done",
                   "-print-settings", ",".join(parts)]
            if target:
                cmd += ["-print-to", target]
            cmd.append(path)
            log("[PRINT] SumatraPDF -> %s (%s, %d copy/copies%s%s)"
                % (target or "OS default", kind, copies,
                   (", pages %s" % pages) if pages else "",
                   (", %s" % df) if df else ""))
            proc = register(subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE,
                                             creationflags=HIDE))
        else:
            if shutil.which("lp") is None:
                raise RuntimeError("CUPS 'lp' command not found."
                                   " Install cups / cups-client first.")
            cmd = ["lp"]
            if target:
                cmd += ["-d", target]
            if copies > 1:
                cmd += ["-n", str(copies)]
            if pages:
                cmd += ["-o", "page-ranges=%s" % re.sub(r"[^0-9,\-]", "",
                                                        str(pages))]
            df = duplex_flag()
            if df:
                cmd += ["-o", {"duplex": "two-sided-long-edge",
                               "duplexlong": "two-sided-long-edge",
                               "duplexshort": "two-sided-short-edge",
                               "simplex": "one-sided"}[df]]
            media = ",".join(x for x in (paper_size, tray) if x)
            if media:
                cmd += ["-o", "media=%s" % re.sub(r"[^A-Za-z0-9,]", "", media)]
            cmd += ["-o", "fit-to-page" if kind in ("a4", "image") else "noscale",
                    path]
            log("[PRINT] lp -> %s (%s, %d copy/copies%s%s%s)"
                % (target or "OS default", kind, copies,
                   (", pages %s" % pages) if pages else "",
                   (", %s" % df) if df else "",
                   (", media %s" % media) if media else ""))
            proc = register(subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE))
        try:
            out, err = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("printer did not respond within 180 s")
        if proc.returncode != 0:
            raise RuntimeError("print backend exit %d: %s"
                               % (proc.returncode,
                                  (err or b"").decode("utf-8", "ignore")[:300]))
    finally:
        with _CURRENT_LOCK:
            if _CURRENT["id"] == job_id:
                _CURRENT["id"] = None
                _CURRENT["proc"] = None
    return target or "OS default"

def cancel_current_print():
    """Kill the in-flight print process, if any. Returns job id or None."""
    with _CURRENT_LOCK:
        proc = _CURRENT["proc"]
        jid = _CURRENT["id"]
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        _CURRENT["proc"] = None
        _CURRENT["id"] = None
    return jid

# ------------------------------------------------------------
# Print queue: DB-driven worker with global pause
# v2.0: priority (urgent first), exponential retry with backoff,
# dead-letter after the final attempt, HOLD while the printer is
# offline / out of paper, scheduled prints, printer-group fallback
# and optional forwarding to a live peer hub.
# ------------------------------------------------------------
RESUME_EVENT = threading.Event()   # set = queue running, clear = paused
RESUME_EVENT.set()
_UNHOLD_TS = [0.0]                 # periodic printer re-check throttle

def _job_print_args(job):
    """(file bytes path, kind, printer) with printer-group resolution."""
    printer = job.get("printer") or ""
    if printer_group_members(printer):
        member = pick_group_printer(printer)
        if member:
            log("[GROUP] '%s' -> member '%s'" % (printer, member))
            printer = member
    return job.get("file_path"), job.get("kind", "a4"), printer

def _hold_job(job, why):
    db_update(job["id"], status="held", held_reason=why[:200], error=None)
    db_audit("print.held", job_id=job["id"], printer=job.get("printer"),
             details=why[:200])
    log("[HOLD] job #%d: %s" % (job["id"], why))

def _release_held_jobs():
    """Every ~15 s: printers that came back online release their held jobs."""
    if time.time() - _UNHOLD_TS[0] < 15:
        return
    _UNHOLD_TS[0] = time.time()
    held = db_list(limit=200, status="held")
    if not held:
        return
    st = printers_status()
    for j in held:
        target = j.get("printer") or CFG["printer"] or default_printer() or ""
        cur = st.get(target, "unknown") if target else "unknown"
        if cur not in ("offline", "paper-out", "error"):
            db_update(j["id"], status="queued", held_reason=None,
                      error=None, next_attempt_at=None)
            db_audit("print.requeued", job_id=j["id"], printer=target,
                     details="printer back %s - job released" % (cur or "ready"))
            log("[RELEASE] job #%d back in queue (%s ready)" % (j["id"], target))

def _retry_or_dead(job, err):
    """Exponential retry: requeue with backoff, or dead-letter after the
    final attempt (visible in the dead-letter list, retryable)."""
    attempts = int(job.get("attempts") or 0) + 1
    maxr = max(0, int(CFG.get("max_retries", 2)))
    if attempts <= maxr:
        delay = int(CFG.get("retry_base_seconds", 30)) * (2 ** (attempts - 1))
        nxt = (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
        db_update(job["id"], status="queued", attempts=attempts,
                  next_attempt_at=nxt,
                  error="retry %d/%d in %ds: %s" % (attempts, maxr, delay,
                                                    str(err)[:120]))
        db_audit("print.requeued", job_id=job["id"],
                 printer=job.get("printer"),
                 details="retry %d/%d in %ds - %s" % (attempts, maxr, delay,
                                                      str(err)[:120]))
        log("[RETRY] job #%d failed (%s) - attempt %d/%d in %ds"
            % (job["id"], str(err)[:80], attempts, maxr, delay))
    else:
        db_update(job["id"], status="dead", attempts=attempts,
                  error=str(err)[:500])
        db_audit("job.dead", job_id=job["id"], printer=job.get("printer"),
                 details=str(err)[:200])
        log("[DEAD] job #%d moved to the dead-letter list: %s"
            % (job["id"], str(err)[:120]))

def _try_peer_forward(job):
    """Offline/unknown printer + peer_forwarding on: send the document to
    the first ALIVE peer hub that has the printer. Dead peers are skipped.
    Returns True when the job was handed over."""
    if not CFG.get("peer_forwarding"):
        return False
    peers = CFG.get("peer_hubs") or []
    if not peers:
        return False
    try:
        with open(job["file_path"], "rb") as f:
            data = f.read()
    except OSError:
        return False
    want = job.get("printer") or ""
    for peer in peers:
        url = (peer.get("url") or "").rstrip("/")
        if not url:
            continue
        headers = {"X-PrintHub-Token": peer.get("token") or "",
                   "User-Agent": "PrintHubPro/%s" % VERSION}
        try:
            req = urllib.request.Request(url + "/health", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as r:
                if not (r.getcode() == 200):
                    continue
            if want:
                req = urllib.request.Request(url + "/printers", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as r:
                    names = [p.get("name") for p in
                             json.loads(r.read().decode("utf-8", "replace"))
                             .get("printers", [])]
                if want not in names:
                    continue     # peer alive but no such printer - next peer
            payload = json.dumps({
                "pdf_base64": base64.b64encode(data).decode("ascii"),
                "title": job.get("title") or "peer",
                "printer": want, "copies": job.get("copies") or 1,
                "kind": job.get("kind") or "a4",
                "source": "peer:%s" % CFG["port"]}).encode()
            req = urllib.request.Request(
                url + "/print", data=payload, headers=dict(
                    headers, **{"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read().decode("utf-8", "replace"))
            if resp.get("ok"):
                db_update(job["id"], status="forwarded", peer=url,
                          error=None,
                          held_reason=None,
                          duration_ms=None)
                db_audit("job.forwarded", job_id=job["id"], printer=want,
                         details="forwarded to peer %s (job %s)" %
                                 (url, resp.get("job_id")))
                log("[PEER] job #%d forwarded to %s (remote job %s)"
                    % (job["id"], url, resp.get("job_id")))
                return True
        except Exception as e:
            log("[PEER] %s skipped (%s)" % (url, str(e)[:80]))
            continue
    return False

def _execute_job(job, t0):
    """Print one job - the status-aware group pick goes first, the other
    group members follow as real fallback, then history + audit + retry."""
    path, kind, printer = _job_print_args(job)
    members = printer_group_members(job.get("printer") or "")
    if members:
        first = pick_group_printer(job.get("printer") or "") or members[0]
        candidates = [first] + [m for m in members if m != first]
    else:
        candidates = [printer] if printer else [""]
    last_err = None
    for cand in candidates:
        try:
            target = print_file(path, kind, cand, job.get("copies") or 1,
                                job_id=job["id"], pages=job.get("pages"),
                                duplex=job.get("duplex"),
                                paper_size=job.get("paper_size"),
                                tray=job.get("tray"))
            ms = int((time.time() - t0) * 1000)
            db_update(job["id"], status="printed", error=None,
                      duration_ms=ms, printer=target)
            db_audit("print.completed", job_id=job["id"], printer=target,
                     actor=job.get("source"), site=job.get("site"),
                     ip=job.get("origin_ip"), doc_hash=job.get("content_hash"),
                     details="%d ms" % ms)
            log("[OK] job #%d printed on %s in %d ms" % (job["id"], target, ms))
            return True
        except Exception as e:
            last_err = e
            log("[FAIL] job #%d on '%s': %s" % (job["id"], cand or "default", e))
    latest = db_get(job["id"]) or {}
    if latest.get("status") == "canceled":
        log("[CANCELED] job #%d killed mid-print" % job["id"])
        return False
    db_update(job["id"], status="failed", error=str(last_err)[:500])
    db_audit("print.failed", job_id=job["id"], printer=job.get("printer"),
             details=str(last_err)[:200])
    _retry_or_dead(job, last_err)
    return False

def worker():
    # recover jobs stuck in 'printing' from a previous crash/restart
    for j in db_list(limit=200, status="printing"):
        log("[RECOVER] job #%d was interrupted -> requeued" % j["id"])
        db_update(j["id"], status="queued",
                  error="requeued after hub restart")
    while True:
        RESUME_EVENT.wait()                     # pause support
        try:
            db_promote_scheduled()              # scheduled prints -> queue
            _release_held_jobs()                # offline printers -> back up
        except Exception:
            pass
        job = db_next_queued()
        if not job:
            time.sleep(0.35)
            continue
        # HOLD: printer offline / out of paper / error state (raw jobs skip
        # the status check - receipt printers rarely report usable state)
        if CFG.get("hold_offline", True) and job.get("kind") != "raw":
            pstat = printer_ready(job.get("printer") or "")
            if pstat in ("offline", "paper-out", "error"):
                _hold_job(job, "printer '%s' is %s - job held until it is"
                              " ready" % (job.get("printer") or "default",
                                          pstat))
                continue
            if pstat != "ready" and _try_peer_forward(job):
                continue
        t0 = time.time()
        db_update(job["id"], status="printing", error=None)
        if job.get("kind") == "raw":
            try:
                with open(job["file_path"], "rb") as f:
                    data = f.read()
                target = print_raw(data, job.get("printer") or "",
                                   job_id=job["id"],
                                   title=job.get("title") or "raw")
                ms = int((time.time() - t0) * 1000)
                db_update(job["id"], status="printed", error=None,
                          duration_ms=ms, printer=target)
                db_audit("print.completed", job_id=job["id"], printer=target,
                         actor=job.get("source"), site=job.get("site"),
                         ip=job.get("origin_ip"),
                         doc_hash=job.get("content_hash"))
                log("[OK] job #%d raw-printed on %s" % (job["id"], target))
            except Exception as e:
                latest = db_get(job["id"]) or {}
                if latest.get("status") == "canceled":
                    log("[CANCELED] job #%d killed mid-print" % job["id"])
                else:
                    db_update(job["id"], status="failed",
                              error=str(e)[:500])
                    db_audit("print.failed", job_id=job["id"],
                             printer=job.get("printer"),
                             details=str(e)[:200])
                    _retry_or_dead(job, e)
        else:
            _execute_job(job, t0)
        finally_guard(job)

def finally_guard(job):
    # keep the file for reprint (unless keep_files is off)
    if not CFG["keep_files"] and job.get("file_path") \
            and os.path.exists(job["file_path"]) \
            and (db_get(job["id"]) or {}).get("status") in (
                "printed", "failed", "dead", "canceled"):
        try:
            os.unlink(job["file_path"])
        except OSError:
            pass

def start_worker():
    threading.Thread(target=worker, daemon=True, name="printhub-worker").start()

def save_job_file(kind, title, data, ext="pdf"):
    """Write payload bytes into the jobs dir; returns full path."""
    ensure_dirs()
    safe = "".join(c for c in (title or "job") if c.isalnum() or c in "-_ ")[:40] or "job"
    fname = "%s-%s-%s.%s" % (safe.replace(" ", "_"),
                             datetime.now().strftime("%Y%m%d%H%M%S"),
                             os.getpid(), ext)
    path = os.path.join(CFG["data_dir"], "jobs", fname)
    with open(path, "wb") as f:
        f.write(data)
    return path

def enqueue_print(kind, title, data, printer="", copies=1,
                  source="api", origin_ip="-", queue_mode=True,
                  priority=5, run_at=None, site=None, dedupe=True,
                  content_hash=None, **extra):
    """Save file + insert DB row. Returns (job_id, duplicate_job_id_or_None).
    queue_mode=True  -> FIFO worker prints the job in order (pause respected)
    queue_mode=False -> Queue Mode OFF: job prints IMMEDIATELY in its own
                        thread, pause has no effect. Tracked like always.
    dedupe=False     -> skip duplicate blocking for this one submission."""
    ext = "prn" if kind == "raw" else "pdf"
    path = save_job_file(kind, title, data, ext=ext)
    if not content_hash:
        content_hash = hashlib.sha256(data).hexdigest()
    dedupe_key = hashlib.sha256(("%s|%s|%s|%s" % (title, printer, kind,
                                                  content_hash))
                                .encode()).hexdigest()[:32]
    dup = None
    if dedupe:
        dup = db_find_duplicate(dedupe_key,
                                int(CFG.get("dedupe_minutes", 5)))
    if dup:
        log("[DEDUPE] job identical to #%d (%s) from %s - blocked"
            % (dup["id"], dup["title"], dup["created_at"]))
        try:
            os.unlink(path)
        except OSError:
            pass
        return dup["id"], dup["id"]
    status = "queued"
    next_at = None
    if run_at:
        status = "scheduled"
        next_at = run_at
    job_id = db_add(kind, title, printer, copies, path, source, origin_ip,
                    status=status, priority=max(1, min(9, int(priority or 5))),
                    run_at=run_at, next_attempt_at=next_at, site=site,
                    dedupe_key=dedupe_key, content_hash=content_hash,
                    **extra)
    if queue_mode and status == "queued":
        log("[QUEUE] job #%d queued (p%s, %s, %s) from %s"
            % (job_id, priority, kind, title or "untitled", source))
        return job_id, None
    if status == "scheduled":
        log("[SCHEDULE] job #%d scheduled for %s" % (job_id, run_at))
        return job_id, None
    db_update(job_id, status="printing", error=None)
    threading.Thread(target=_print_now,
                     args=(job_id, path, kind, printer, copies),
                     daemon=True, name="printhub-direct-%d" % job_id).start()
    log("[DIRECT] job #%d printing immediately (queue mode OFF)"
        % job_id)
    return job_id, None


def _print_now(job_id, path, kind, printer, copies):
    """Immediate-execution thread for queue:false jobs (bypasses FIFO)."""
    t0 = time.time()
    try:
        if kind == "raw":
            with open(path, "rb") as f:
                data = f.read()
            target = print_raw(data, printer, job_id=job_id)
        else:
            target = print_file(path, kind, printer, copies, job_id=job_id)
        ms = int((time.time() - t0) * 1000)
        db_update(job_id, status="printed", error=None,
                  duration_ms=ms, printer=target)
        db_audit("print.completed", job_id=job_id, printer=target)
        log("[OK] job #%d printed on %s in %d ms (direct)"
            % (job_id, target, ms))
    except Exception as e:
        latest = db_get(job_id) or {}
        if latest.get("status") == "canceled":
            log("[CANCELED] job #%d killed mid-print" % job_id)
        else:
            db_update(job_id, status="failed", error=str(e)[:500])
            db_audit("print.failed", job_id=job_id, printer=printer,
                     details=str(e)[:200])
            _retry_or_dead(db_get(job_id) or {}, e)
    finally:
        if not CFG["keep_files"] and path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

def save_file_job(kind, title, data, source="api", origin_ip="-"):
    """Destination 'file': write the PDF into the user's file folder
    (~/Downloads/PrintHub by default) - NO paper, NO queue. The job is
    stored with status 'saved' and can be re-printed later."""
    fdir = default_file_dir()
    try:
        os.makedirs(fdir, exist_ok=True)
    except OSError:
        fdir = os.path.join(CFG["data_dir"], "files")
        os.makedirs(fdir, exist_ok=True)
    safe = "".join(c for c in (title or "document")
                   if c.isalnum() or c in "-_ ")[:50].strip() or "document"
    fname = "%s-%s.pdf" % (safe.replace(" ", "_"),
                           datetime.now().strftime("%Y%m%d-%H%M%S"))
    path = os.path.join(fdir, fname)
    n = 1
    while os.path.exists(path):            # never overwrite an earlier file
        path = os.path.join(fdir, "%s-%d.pdf" % (fname[:-4], n))
        n += 1
    with open(path, "wb") as f:
        f.write(data)
    job_id = db_add(kind, title, "File (PDF)", 1, path, source, origin_ip,
                    status="saved")
    log("[FILE] job #%d saved -> %s" % (job_id, path))
    return job_id, path

# ------------------------------------------------------------
# Auto-start at logon (visible, user-controllable)
# ------------------------------------------------------------
# v1.5.0: Windows autostart is a NORMAL STARTUP-APP SHORTCUT
# ("shell:startup\PrintHub Pro.lnk"), NOT a hidden scheduled task.
# Why it matters: Startup-folder apps appear in Task Manager ->
# "Startup apps" with name + icon, so the user can Enable/Disable
# them with one click; scheduled tasks are invisible there, which
# made the hub look uninstallable. The tray icon menu and the
# /autostart API below toggle the same shortcut.

def hub_dir():
    return os.path.dirname(os.path.abspath(__file__))


def launcher_exe():
    """Windows: prefer a sibling PrintHubPro.exe (renamed pythonw.exe) so
    Task Manager shows 'PrintHubPro' instead of 'pythonw'. Non-Windows:
    the current interpreter."""
    if IS_WIN:
        cand = os.path.join(os.path.dirname(sys.executable), "PrintHubPro.exe")
        if os.path.isfile(cand):
            return cand
    return sys.executable


def hub_icon_path():
    cand = os.path.join(hub_dir(), "printhub.ico")
    return cand if os.path.isfile(cand) else ""


def autostart_path():
    """File that controls 'start at logon' (None = unsupported platform)."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu",
                            "Programs", "Startup", "PrintHub Pro.lnk")
    if sys.platform.startswith("linux"):
        cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
        return os.path.join(cfg, "autostart", "printhub-pro.desktop")
    return None


def autostart_enabled():
    p = autostart_path()
    return bool(p) and os.path.isfile(p)


def _legacy_task_remove():
    """Old releases (v1.2 - v1.4) registered a SCHEDULED TASK named
    'PrintHub Pro'. Delete it so the hub never starts twice."""
    if not IS_WIN:
        return
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", "PrintHub Pro", "/F"],
                       creationflags=HIDE, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        pass


def autostart_set(enable):
    """Enable/disable the logon autostart. Returns the resulting state."""
    p = autostart_path()
    if not p:
        return False
    _legacy_task_remove()
    try:
        if IS_WIN:
            if enable:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                lnk = p.replace("'", "''")
                exe = launcher_exe().replace("'", "''")
                hubpy = os.path.join(hub_dir(), "printhub.py").replace("'", "''")
                ico = (hub_icon_path() or "").replace("'", "''")
                wd = hub_dir().replace("'", "''")
                ps = ("$w=New-Object -ComObject WScript.Shell;"
                      "$s=$w.CreateShortcut('{lnk}');"
                      "$s.TargetPath='{exe}';"
                      "$s.Arguments='\"{hubpy}\" serve';"
                      "$s.IconLocation='{ico},0';"
                      "$s.WorkingDirectory='{wd}';"
                      "$s.Description='PrintHub Pro silent print hub';"
                      "$s.Save()").format(lnk=lnk, exe=exe, hubpy=hubpy,
                                          ico=ico, wd=wd)
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy",
                     "Bypass", "-Command", ps],
                    creationflags=HIDE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=30)
                ok = (r.returncode == 0 and os.path.isfile(p))
                log("[AUTOSTART] %s (%s)" %
                    ("enabled - Startup shortcut created" if ok
                     else "FAILED to create Startup shortcut",
                     p))
                return ok
            if os.path.isfile(p):
                os.remove(p)
            log("[AUTOSTART] disabled - Startup shortcut removed")
            return False
        # Linux: XDG autostart desktop entry
        if enable:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            exe = launcher_exe()
            ico = os.path.join(hub_dir(), "printhub.png")
            with open(p, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\n"
                        "Name=PrintHub Pro\n"
                        "Comment=Silent print hub (localhost:9235)\n"
                        "Exec=%s %s serve\n" % (exe, os.path.join(hub_dir(),
                                                                 "printhub.py")))
                if os.path.isfile(ico):
                    f.write("Icon=%s\n" % ico)
                f.write("Terminal=false\nCategories=Utility;\n")
            return os.path.isfile(p)
        if os.path.isfile(p):
            os.remove(p)
        return False
    except Exception as e:
        log("[AUTOSTART] error: %s" % e)
        return autostart_enabled()


# ------------------------------------------------------------
# HTTP API (pure stdlib, CORS-ready for ANY browser/website)
# ------------------------------------------------------------
CORS_HEADERS = [
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers",
     "Content-Type, X-PrintHub-Token, Access-Control-Request-Private-Network"),
    ("Access-Control-Allow-Private-Network", "true"),   # Chrome/Firefox LAN preflight
    ("Access-Control-Max-Age", "86400"),
]

# v2.0 auth hardening state
_AUTH_FAILS = {}          # ip -> {count, until, first, last_audit, warned}
                          # 10 wrong tokens inside the window -> lock
                          # (v2.0.1: loopback IPs are exempt by default -
                          #  see lockout_exempt_loopback in CFG)
_AUTH_AUDIT_TS = {}       # ip -> last auth.failed audit write (survives
                          # success-clears so the audit log can never be
                          # flooded: max 1 row per 10 s per IP)
START_TS = time.time()    # for the diagnostics uptime report

def _extension_origin(origin):
    """Browser-extension origins are always trusted (they are the user's
    own install, governed by the extension's master switch)."""
    o = (origin or "").lower()
    return (o.startswith("chrome-extension://")
            or o.startswith("moz-extension://")
            or o.startswith("safari-web-extension://"))

def mask_token(tok):
    t = str(tok or "")
    return (t[:4] + "***") if len(t) > 6 else "***"

def read_json_body(handler, required=True):
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        if required:
            raise ValueError("empty or oversized body (0 bytes)")
        return {}
    if length > MAX_BODY:
        raise ValueError("oversized body (%d bytes)" % length)
    raw = handler.rfile.read(length)
    ctype = (handler.headers.get("Content-Type") or "").lower()
    if "urlencoded" in ctype:
        # Browser hidden-form fallback: field 'payload' carries the JSON.
        fields = dict(parse_qsl(raw.decode("utf-8", "replace")))
        payload = fields.get("payload") or (list(fields.values())[0] if fields else "")
        try:
            return json.loads(payload)
        except Exception:
            raise ValueError("form 'payload' field is not valid JSON")
    return json.loads(raw.decode("utf-8", "replace"))

def read_raw_body(handler):
    """Read the request body as raw bytes (raw-PDF / multipart uploads)."""
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        raise ValueError("empty body (0 bytes)")
    if length > MAX_BODY:
        raise ValueError("oversized body (%d bytes)" % length)
    return handler.rfile.read(length)

def parse_multipart(raw, ctype):
    """Minimal multipart/form-data parser (stdlib only - the cgi module was
    removed in Python 3.13). Returns (file_bytes_or_None, fields dict).
    The file part is the one carrying a filename or field name 'pdf'/'file'.
    Lets Laravel/PHP clients do Http::attach('pdf', $bytes)->post(...) with
    NO base64 encoding."""
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "", re.I)
    if not m:
        raise ValueError("multipart body without boundary")
    bnd = ("--" + m.group(1)).encode("utf-8")
    fields, fdata = {}, None
    for part in raw.split(bnd):
        p = part
        if p.startswith(b"\r\n"):
            p = p[2:]
        if p.endswith(b"\r\n"):
            p = p[:-2]
        if p in (b"", b"--") or b"\r\n\r\n" not in p:
            continue
        head, _, content = p.partition(b"\r\n\r\n")
        nm = re.search(rb'name="([^"]*)"', head)
        name = nm.group(1).decode("utf-8", "replace") if nm else ""
        if b'filename="' in head or name in ("pdf", "file"):
            fdata = content
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fdata, fields

def download_pdf(url):
    """Fetch a PDF from a URL (used by 'pdf_url' mode).
    v2.0: guarded by pdf_url_guard() - file://, ftp:// and private/local
    addresses are blocked (see pdf_url_allowed_hosts for exemptions)."""
    pdf_url_guard(url)
    req = urllib.request.Request(url, headers={"User-Agent": "PrintHubPro/%s" % VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_PDF + 1)
    if not data or len(data) > MAX_PDF:
        raise ValueError("pdf_url download too large or empty")
    if not data[:5].startswith(b"%PDF"):
        raise ValueError("pdf_url did not return a PDF")
    return data

# ------------------------------------------------------------
# REPRINT watermark (v2.0): stamps diagonal gray text on every page.
# Best-effort pure-Python PDF edit - on ANY problem the ORIGINAL bytes
# are returned so printing never breaks because of the watermark.
# ------------------------------------------------------------
def pdf_watermark(data, text="REPRINT"):
    try:
        return _pdf_watermark_impl(data, text)
    except Exception as e:
        log("[WARN] watermark skipped (%s) - printing the original file" % e)
        return data

def _pdf_watermark_impl(data, text):
    if not data or not data[:5].startswith(b"%PDF") or b"/Encrypt" in data[:2048]:
        return data
    if b"ObjStm" in data:          # compressed object streams: not edited
        raise ValueError("PDF uses object streams")
    text = (text or "REPRINT")[:24]
    # collect top-level "N 0 obj ... endobj" segments
    objs = {}                       # num -> bytes body (without obj/endobj)
    for m in re.finditer(rb"(\d+)\s+0\s+obj\b", data):
        num = int(m.group(1))
        end = data.find(b"endobj", m.end())
        if end < 0:
            raise ValueError("broken object body")
        objs[num] = data[m.end():end].strip(b"\r\n \t")
        if len(objs) > 4000:
            raise ValueError("PDF too complex to watermark")
    if not objs:
        raise ValueError("no objects found")
    pages = [n for n, b in objs.items() if re.search(rb"/Type\s*/Page\b", b)]
    if not pages:
        raise ValueError("no page objects found")
    next_id = max(objs) + 1
    gs_id, font_id = next_id, next_id + 1
    ov_id = next_id + 2
    next_id += 3
    content = (
        b"q /PHwm gs 0.72 0.72 0.72 rg BT /PHwmF 56 Tf "
        b"0.7071 0.7071 -0.7071 0.7071 60 240 Tm (" +
        _pdf_escape(text).encode("latin-1", "replace") + b") Tj ET Q")
    objs[gs_id] = b"<< /Type /ExtGState /CA 0.18 /ca 0.18 >>"
    objs[font_id] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
                     b" /Encoding /WinAnsiEncoding >>")
    objs[ov_id] = b"<< /Length %d >>\nstream\n" % len(content) + content + \
                  b"\nendstream"
    for n in pages:
        body = objs[n]
        if re.search(rb"/Contents\s*\[", body):
            body = re.sub(rb"/Contents\s*\[", b"/Contents [" +
                          b" %d 0 R" % ov_id, body, count=1)
        elif re.search(rb"/Contents\s*/?\d+\s+0\s+R", body):
            body = re.sub(rb"(/Contents\s*)/?(\d+\s+0\s+R)",
                          lambda mm: mm.group(1) + b"[%d 0 R %s]"
                          % (ov_id, mm.group(2)),
                          body, count=1)
        else:
            raise ValueError("page %d has no /Contents" % n)
        if b"/ExtGState" not in body:
            if b"/Resources" not in body:
                body += (b" /Resources << /ExtGState << /PHwm %d 0 R >>"
                         b" /Font << /PHwmF %d 0 R >> >>" % (gs_id, font_id))
            else:
                body = re.sub(rb"/Resources\s*<<",
                              b"/Resources << /ExtGState << /PHwm %d 0 R >>"
                              b" /Font << /PHwmF %d 0 R >>" % (gs_id, font_id),
                              body, count=1)
        elif b"PHwm" not in body:
            body = re.sub(rb"/ExtGState\s*<<",
                          b"/ExtGState << /PHwm %d 0 R" % gs_id, body, count=1)
            if b"PHwmF" not in body:
                body = re.sub(rb"/Font\s*<<",
                              b"/Font << /PHwmF %d 0 R" % font_id, body, count=1)
        objs[n] = body
    # re-serialize everything with a fresh classic xref table
    out = bytearray(data.split(b"%PDF-", 1)[0][:0] + b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for idx in sorted(objs):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode() + objs[idx] + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % next_id).encode()
    out += b"0000000000 65535 f \n"
    for idx in range(1, next_id):
        if idx in offsets:
            out += ("%010d 00000 n \n" % offsets[idx]).encode()
        else:
            out += b"0000000000 65535 f \n"      # gap ids keep the table aligned
    cat = next(n for n, b in objs.items() if b"/Type" in b and b"/Catalog" in b)
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (next_id, cat, xref)).encode()
    return bytes(out)

# ------------------------------------------------------------
# RAW printing (v2.0): ESC/POS receipts + ZPL labels - no driver, no PDF
#   Windows: winspool RAW datatype via ctypes (pure stdlib)
#   Unix:    CUPS "lp -o raw"
# ESC/POS helpers cover cut, cash drawer, CODE128 barcode and QR codes.
# ------------------------------------------------------------
ESC_ESC = b"\x1b"
def escpos_init():
    return ESC_ESC + b"@"                      # initialize

def escpos_align(mode):
    return ESC_ESC + b"a" + bytes([mode])      # 0 left, 1 center, 2 right

def escpos_size(big):
    return (b"\x1d!\x11" if big else b"\x1d!\x00")   # double / normal

def escpos_feed(n=4):
    return ESC_ESC + b"d" + bytes([max(0, min(255, int(n)))])

def escpos_cut():
    return b"\x1dV\x42\x00"                    # full cut

def escpos_drawer():
    return b"\x1bp\x00\x19\xfa"                # pin 2, 50 ms on / 250 ms off

def escpos_barcode(data):
    d = b"{B" + str(data or "").encode("ascii", "replace")[:60]
    return b"\x1dkI" + bytes([len(d)]) + d     # GS k 73 (CODE128)

def escpos_qr(data):
    d = str(data or "").encode("utf-8")[:500]
    nL, nH = (len(d) + 3) & 0xFF, ((len(d) + 3) >> 8) & 0xFF
    return (b"\x1d(k\x04\x001A2\x00"           # model 2
            b"\x1d(k\x03\x001C\x06"            # module size 6
            b"\x1d(k\x03\x001E\x31"            # error correction M
            b"\x1d(k" + bytes([nL, nH]) + b"31" + d +
            b"\x1d(k\x03\x0031Q")              # print

def escpos_bytes(text, cut=True, drawer=False):
    """Plain text -> ESC/POS receipt bytes. Markers:
    '#big ' double size | '|center|' centered | '|right|' right aligned
    '|cut|' cut here  | '|drawer|' open cash drawer
    '|barcode:12345|' CODE128  | '|qr:text|' QR code."""
    out = bytearray(escpos_init())
    out += escpos_align(1)
    out += b"PrintHub Pro\n\n"
    out += escpos_align(0)
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        if line.startswith("|cut|"):
            out += escpos_feed(3) + escpos_cut()
            continue
        if line.startswith("|drawer|"):
            out += escpos_drawer()
            continue
        m = re.match(r"^\|barcode:([^|]+)\|\s*$", line)
        if m:
            out += escpos_align(1) + escpos_barcode(m.group(1)) + \
                   escpos_feed(2) + escpos_align(0)
            continue
        m = re.match(r"^\|qr:([^|]*)\|\s*$", line)
        if m:
            out += escpos_align(1) + escpos_qr(m.group(1)) + \
                   escpos_feed(2) + escpos_align(0)
            continue
        big = line.startswith("#big")
        if big:
            line = line[4:].strip()
        if line.startswith("|center|"):
            out += escpos_align(1)
            line = line[8:].strip()
        elif line.startswith("|right|"):
            out += escpos_align(2)
            line = line[7:].strip()
        else:
            out += escpos_align(0)
        out += escpos_size(big)
        out += line.encode("cp437", "replace") + b"\n"
        out += escpos_size(False)
    out += escpos_feed(4)
    if drawer:
        out += escpos_drawer()
    if cut:
        out += escpos_cut()
    return bytes(out)

def raw_print_windows(data, printer, job_id=None, title="raw"):
    """Send RAW bytes to a Windows printer via winspool (DATATYPE RAW)."""
    import ctypes
    from ctypes import wintypes
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    OpenPrinterW = winspool.OpenPrinterW
    OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_void_p)]
    StartDocPrinterW = winspool.StartDocPrinterW
    StartDocPrinterW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.c_void_p)]
    WritePrinter = winspool.WritePrinter
    WritePrinter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD)]
    class DOCINFO1(ctypes.Structure):
        _fields_ = [("pDocName", ctypes.c_void_p),
                    ("pDatatype", ctypes.c_void_p),
                    ("pOutputFile", ctypes.c_void_p)]
    h = ctypes.c_void_p()
    name = ctypes.c_wchar_p(printer or "NULL")
    if not OpenPrinterW(name, ctypes.byref(h), None):
        raise RuntimeError("printer '%s' not found (winspool error %d)"
                           % (printer or "(default)", ctypes.get_last_error()))
    try:
        di = DOCINFO1()
        di.pDocName = ctypes.cast(ctypes.c_wchar_p(title or "PrintHub raw"),
                                  ctypes.c_void_p).value
        di.pDatatype = ctypes.cast(ctypes.c_wchar_p("RAW"),
                                   ctypes.c_void_p).value
        di.pOutputFile = None
        if not StartDocPrinterW(h, 1, ctypes.byref(di)):
            raise RuntimeError("StartDocPrinter failed (error %d)"
                               % ctypes.get_last_error())
        if not winspool.StartPagePrinter(h):
            raise RuntimeError("StartPagePrinter failed")
        written = wintypes.DWORD(0)
        chunk = 65536
        for off in range(0, len(data), chunk):
            view = (ctypes.c_char * min(chunk, len(data) - off)).from_buffer_copy(
                data[off:off + chunk])
            if not WritePrinter(h, view, len(data) - off, ctypes.byref(written)):
                raise RuntimeError("WritePrinter failed (error %d)"
                                   % ctypes.get_last_error())
        winspool.EndPagePrinter(h)
        winspool.EndDocPrinter(h)
    finally:
        winspool.ClosePrinter(h)
    return printer or "Windows RAW"

def print_raw(data, printer="", job_id=None, title="raw"):
    """Print RAW bytes (ESC/POS / ZPL / PCL) directly to the printer."""
    target = printer or CFG["printer"] or default_printer() or ""
    if not target:
        raise RuntimeError("raw printing needs a printer name"
                           " (no OS default printer found)")
    if IS_WIN:
        log("[RAW] winspool -> %s (%d bytes)" % (target, len(data)))
        return raw_print_windows(data, target, job_id=job_id, title=title)
    if shutil.which("lp") is None:
        raise RuntimeError("CUPS 'lp' not found - raw printing needs CUPS")
    path = os.path.join(tempfile.gettempdir(), "printhub-raw-%s.prn" % os.getpid())
    with open(path, "wb") as f:
        f.write(data)
    try:
        cmd = ["lp", "-d", target, "-o", "raw", path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError("raw print failed: %s"
                               % (proc.stderr or proc.stdout or "")[:200])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    log("[RAW] lp -o raw -> %s (%d bytes)" % (target, len(data)))
    return target

def raw_payload_bytes(body):
    """Build the raw byte stream for /print raw mode.
      raw_base64            -> verbatim bytes (ESC/POS or ZPL you prepared)
      lang=escpos + text    -> ESC/POS builder (cut/drawer/barcode/QR markers)
      lang=zpl + text       -> verbatim ZPL II text (^XA...^XZ)
    Returns (bytes, lang)."""
    lang = (body.get("lang") or "escpos").lower()
    if body.get("raw_base64"):
        data = base64.b64decode(body["raw_base64"], validate=False)
        return data, lang
    text = body.get("text")
    if text is None:
        raise ValueError("raw print needs 'text' or 'raw_base64'")
    if lang == "zpl":
        return str(text).encode("latin-1", "replace"), "zpl"
    cut = body.get("cut", True)
    if isinstance(cut, str):
        cut = cut.strip().lower() not in ("0", "false", "no", "off")
    drawer = body.get("drawer", False)
    if isinstance(drawer, str):
        drawer = drawer.strip().lower() in ("1", "true", "yes", "on")
    return escpos_bytes(text, cut=bool(cut), drawer=bool(drawer)), "escpos"

class Handler(BaseHTTPRequestHandler):
    server_version = "PrintHubPro/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- plumbing ----
    def _cors(self):
        for k, v in CORS_HEADERS:
            self.send_header(k, v)
        # v2.0 origin allowlist: echo the caller origin when allowed,
        # otherwise omit Access-Control-Allow-Origin (browser blocks it).
        # Empty list = allow every origin exactly like 1.x did.
        if CFG.get("allowed_origins"):
            origin = self.headers.get("Origin")
            if origin and (_extension_origin(origin) or origin_allowed(origin)):
                self.send_header("Access-Control-Allow-Origin", origin)
            else:
                self.send_header("Access-Control-Allow-Origin", "null")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_file(self, path, download_name, ctype="application/pdf"):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, {"ok": False, "error": "file no longer stored"})
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % download_name)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):     # quieter default logging
        if os.environ.get("PRINTHUB_VERBOSE"):
            log("[HTTP] %s %s" % (self.address_string(), fmt % args))

    # ---- auth (v2.0, fixed in v2.0.1) ----
    # * token in the X-PrintHub-Token HEADER is always accepted
    # * token in query/body: accepted on old installs; on new installs
    #   (token_header_only) it is rejected everywhere EXCEPT the few
    #   endpoints a browser must open by navigation (/dashboard,
    #   /jobs/{id}/file, /export/*.csv) - documented in docs/API.md
    # * v2.0.1 LOCKOUT RULES (the v2.0.0 lockout could lock out the OWNER):
    #     - every Chrome window/profile shares ONE IP (127.0.0.1), so a
    #       stale token in one window locked the dashboard, tray and
    #       extension of ALL windows -> loopback is now exempt by default
    #       (config: lockout_exempt_loopback, default true)
    #     - failures only count inside a sliding window (lockout_minutes)
    #       so old failures can never accumulate into a surprise lock
    #     - a successful auth clears that IP's counter immediately
    #     - REMOTE IPs still get the full 10-wrong-tokens -> 5 min lock
    # * browser Origin header must match allowed_origins (when set)
    def _client_ip(self):
        return self.client_address[0] if self.client_address else "-"

    def _is_loopback(self):
        ip = self._client_ip()
        return ip in ("127.0.0.1", "::1", "localhost",
                      "::ffff:127.0.0.1", "::ffff:127.0.0.1%0")

    def _request_site(self):
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        return o.strip()[:200] or None

    def _auth_hint(self, given):
        """Actionable hint appended to every 401 answer."""
        if given and given == LEGACY_TOKEN and CFG["token"] != LEGACY_TOKEN:
            return ("'%s' was the OLD default token and no longer works. "
                    "Get the current token from the tray menu (Open "
                    "dashboard), read it from %s, or run: "
                    "python printhub.py token"
                    % (LEGACY_TOKEN, config_path()))
        return ("get the token from the tray menu, from %s, or run: "
                "python printhub.py token" % config_path())

    def _auth_error(self, qtoken=None, body=None, allow_query=False):
        """Returns None when authorized, otherwise (code, message).
        allow_query=True marks read-only GET navigation where the query
        token is accepted even in header-only mode (v2.0.2: every GET;
        POST stays header-strict)."""
        ip = self._client_ip()
        loopback = self._is_loopback()
        exempt = loopback and CFG.get("lockout_exempt_loopback", True)
        now = time.time()
        lock = _AUTH_FAILS.get(ip)
        if lock and lock.get("until", 0) > now:
            if not exempt:
                left = int(lock["until"] - now)
                return (429, "too many failed tokens - this IP is locked"
                             " for another %ds" % left)
            _AUTH_FAILS.pop(ip, None)   # owner IP: never stay locked
        strict = bool(CFG.get("token_header_only")) and not allow_query
        given = self.headers.get("X-PrintHub-Token") or ""
        if not strict:
            given = given or str(qtoken or "") or str((body or {}).get("token") or "")
        if given and hmac.compare_digest(str(given), str(CFG["token"])):
            _AUTH_FAILS.pop(ip, None)   # success clears the counter
            return None
        # record the failure -> maybe lock this IP
        window = max(int(CFG.get("lockout_minutes", 5)), 1) * 60
        rec = _AUTH_FAILS.get(ip)
        if rec is None or now - rec.get("first", 0) > window:
            rec = {"count": 0, "until": 0.0, "first": now,
                   "last_audit": 0.0, "warned": False}
            _AUTH_FAILS[ip] = rec
            if len(_AUTH_FAILS) > 512:          # memory hygiene
                for k in [k for k, v in _AUTH_FAILS.items()
                          if now - v.get("first", 0) > window][:64]:
                    _AUTH_FAILS.pop(k, None)
        rec["count"] += 1
        # audit throttle: max 1 auth.failed row per 10 s per IP - kept in
        # a side table so clearing the counter on success cannot be used
        # to re-arm it and flood the audit log
        if now - _AUTH_AUDIT_TS.get(ip, 0) >= 10:
            _AUTH_AUDIT_TS[ip] = now
            if len(_AUTH_AUDIT_TS) > 512:       # memory hygiene
                for k in [k for k, t in _AUTH_AUDIT_TS.items()
                          if now - t > 60][:64]:
                    _AUTH_AUDIT_TS.pop(k, None)
            db_audit("auth.failed", ip=ip,
                     details="wrong token (attempt %d)" % rec["count"])
        limit = max(int(CFG.get("max_auth_failures", 10)), 1)
        if rec["count"] >= limit:
            if exempt:
                # v2.0.1: the owner's own IP is never locked - one stale
                # token must not take the whole PC's printing down
                rec["count"] = 0
                if not rec.get("warned"):
                    rec["warned"] = True
                    log("[AUTH] %d wrong tokens from loopback %s - NOT"
                        " locked (lockout_exempt_loopback=true; use the"
                        " tray menu or 'python printhub.py token' to fix)"
                        % (limit, ip))
            else:
                mins = int(CFG.get("lockout_minutes", 5))
                rec["until"] = now + mins * 60
                rec["count"] = 0        # fresh count after the lock ends
                db_audit("auth.locked", ip=ip,
                         details="IP locked for %d min after %d wrong tokens"
                                 % (mins, limit))
                log("[AUTH] IP %s locked for %d min (%d wrong tokens)"
                    % (ip, mins, limit))
                return (429, "too many failed tokens - this IP is locked"
                             " for %d minutes" % mins)
        return (401, "invalid or missing token - " + self._auth_hint(given))

    def _origin_error(self):
        """403 when the browser Origin is not on the allowed list.
        Extension origins and empty origins (curl/scripts) are exempt."""
        origin = self.headers.get("Origin")
        if not origin or _extension_origin(origin):
            return None
        if origin_allowed(origin):
            return None
        return (403, "origin %s is not on the hub's allowed_origins list"
                     % origin[:100])

    # ---- routes ----
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        qt = (q.get("token") or [""])[0]
        route = u.path.rstrip("/") or "/"
        # v2.0.2 auth rule (fixes the /audit vs /dashboard mismatch):
        # EVERY GET endpoint accepts ?token= for plain browser navigation
        # - browsers cannot send the X-PrintHub-Token header, and a token
        # that opens /dashboard must equally open /audit, /stats, /jobs.
        # Mutating calls (POST) still require the header in header-only
        # mode, so the extension/API hardening is not weakened.

        if route == "/health":                        # open: browser pre-check
            dp = default_printer()
            st = db_stats() if os.path.isfile(db_path()) else {}
            ready = sum(1 for v in printers_status().values()
                        if v == "ready")
            return self._send(200, {
                "ok": True, "app": APP_NAME, "version": VERSION,
                "branding": BRANDING,
                "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
                "default_printer": dp,
                "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
                "browser_found": find_browser() is not None,
                "paused": not RESUME_EVENT.is_set(),
                "pending": db_count_pending() if os.path.isfile(db_path()) else 0,
                "jobs_today": st.get("jobs_today", 0),
                "file_dir": default_file_dir(),
                "token_set": bool(CFG["token"]),
                "default_token_warning": DEFAULT_TOKEN_WARNING,
                "token_header_only": bool(CFG.get("token_header_only")),
                "autostart": autostart_enabled(),
                "service": service_state(),
                "queue_bypass": True,
                "held": st.get("by_status", {}).get("held", 0) if st else 0,
                "success_rate": st.get("success_rate") if st else None,
                "printers_ready": ready,
                "audit": bool(CFG.get("audit_enabled", True)),
                "v2": True,
            })

        # /dashboard - browser page with its own early auth so browser
        # users always get the HTML error page (v2.0.2: /audit, /stats
        # and every other GET accept ?token= too - see the generic rule)
        if route == "/dashboard":
            err = self._auth_error(qt, allow_query=True)
            if err:
                # v2.0.1: browsers get a readable HTML page with fix
                # instructions instead of a raw JSON blob
                if "text/html" in (self.headers.get("Accept") or ""):
                    page = dashboard_auth_error_html(err[1]).encode("utf-8")
                    self.send_response(err[0])
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    try:
                        self.wfile.write(page)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                return self._send(err[0], {"ok": False, "error": err[1]})
            html = dashboard_html(u.query).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            try:
                self.wfile.write(html)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        err = self._origin_error()
        if err:
            return self._send(err[0], {"ok": False, "error": err[1]})
        err = self._auth_error(qt, allow_query=True)   # v2.0.2: every GET
        if err:
            # v2.0.2: a browser that followed a link gets the same
            # readable HTML error page as the dashboard; API clients
            # (fetch/curl) keep the JSON error
            if "text/html" in (self.headers.get("Accept") or ""):
                page = dashboard_auth_error_html(err[1]).encode("utf-8")
                self.send_response(err[0])
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            return self._send(err[0], {"ok": False, "error": err[1]})

        if route == "/":
            return self._send(200, {
                "app": APP_NAME, "version": VERSION, "by": VENDOR,
                "branding": BRANDING,
                "endpoints": ["/health", "/dashboard?token=...",
                              "/printers", "/jobs[?status=]", "/jobs/{id}/file",
                              "/jobs/{id}/reprint (POST)", "/jobs/{id}/cancel (POST)",
                              "/jobs/{id}/retry (POST, failed/dead jobs)",
                              "/jobs/{id}/priority (POST {priority:1-9})",
                              "/print (POST) [&queue=false] [+priority,run_at,"
                              "profile,pages,duplex,paper,tray,reason,watermark,raw]",
                              "/queue (GET)", "/queue/pause|resume|clear (POST)",
                              "/autostart (GET) + /autostart (POST)",
                              "/testprint?kind=a4|thermal",
                              "/stats", "/audit[?event=]", "/audit.csv",
                              "/export/history.csv", "/export/audit.csv",
                              "/diagnostics", "/config (GET/POST)",
                              "/token/rotate (POST)", "/peers"],
            })
        if route == "/printers":
            dp = default_printer()
            st = printers_status()
            groups = CFG.get("printer_groups") or {}
            items = []
            for n in list_printers():
                items.append({"name": n, "is_default": n == dp,
                              "status": st.get(n, "unknown"),
                              "is_group": False})
            for g in groups:
                items.append({"name": g, "is_default": False,
                              "status": "group",
                              "is_group": True,
                              "members": groups[g]})
            return self._send(200, {
                "ok": True, "printers": items, "default": dp,
                "groups": groups})
        if route == "/autostart":
            return self._send(200, {
                "ok": True, "enabled": autostart_enabled(),
                "path": autostart_path(),
                "hint": "POST {\"enabled\": true|false} to change"
                        " (same toggle as the tray icon menu)"})
        if route == "/queue":
            cur = None
            with _CURRENT_LOCK:
                if _CURRENT["id"]:
                    cur = db_get(_CURRENT["id"])
            return self._send(200, {
                "ok": True,
                "paused": not RESUME_EVENT.is_set(),
                "pending": db_count_pending(),
                "held": db_count_held(),
                "current": cur})
        if route == "/jobs":
            limit = (q.get("limit") or [str(HISTORY_DEFAULT)])[0]
            status = (q.get("status") or [""])[0] or None
            return self._send(200, {"ok": True,
                                    "jobs": db_list(limit, status=status)})
        if route == "/stats":
            st = db_stats()
            st.update({
                "ok": True, "version": VERSION, "paused": not RESUME_EVENT.is_set(),
                "printers": printers_status(),
                "printers_ready": sum(1 for v in printers_status().values()
                                      if v == "ready"),
                "default_token_warning": DEFAULT_TOKEN_WARNING,
                "service": service_state(),
                "uptime_s": int(time.time() - START_TS),
            })
            return self._send(200, st)
        if route == "/audit":
            limit = (q.get("limit") or ["50"])[0]
            event = (q.get("event") or [""])[0] or None
            return self._send(200, {"ok": True,
                                    "entries": audit_list(limit, event)})
        if route == "/audit.csv":
            return self._csv_response("audit", audit_list(limit=5000))
        if route in ("/export/history.csv", "/history.csv"):
            return self._csv_response("jobs", db_list(limit=5000))
        if route == "/export/audit.csv":
            return self._csv_response("audit", audit_list(limit=5000))
        if route == "/diagnostics":
            return self._send(200, build_diagnostics())
        if route == "/config":
            return self._send(200, redacted_config())
        if route == "/peers":
            return self._send(200, {"ok": True, "peers": probe_peers()})
        if route == "/testprint":
            kind = (q.get("kind") or ["a4"])[0]
            if kind not in ("a4", "thermal"):
                kind = "a4"
            if kind == "thermal":
                data, _ = thermal_pdf_bytes(
                    "#big PrintHub Pro\n|center|Bitdream IT - TEST RECEIPT\n"
                    "--------------------------------\n"
                    "Item 1              10.00\nItem 2              25.50\n"
                    "--------------------------------\n"
                    "TOTAL               35.50\n\n"
                    "|center|Thank you!\n", "testprint")
                title = "test-thermal"
            else:
                data, _ = thermal_pdf_bytes(
                    "#big PrintHub Pro - A4 TEST"
                    "\n\nIf this page came out of your printer,"
                    "\nthe hub is working perfectly."
                    "\n\nTime: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "testprint", paper="a4")
                title = "test-a4"
            job, dup = enqueue_print(kind, title, data, dedupe=False,
                                     origin_ip=self._client_ip(),
                                     site=self._request_site())
            db_audit("print.submitted", job_id=job, actor="api",
                     site=self._request_site(), ip=self._client_ip(),
                     doc_hash=hashlib.sha256(data).hexdigest())
            return self._send(200, {"ok": True, "job_id": job, "kind": kind,
                                    "message": "queued - check your printer"})
        if route.startswith("/jobs/"):
            parts = route.strip("/").split("/")
            if len(parts) == 3 and parts[2] == "file":
                j = db_get(int(parts[1]) if parts[1].isdigit() else 0)
                if j and j.get("file_path") and os.path.exists(j["file_path"]):
                    ctype = ("application/octet-stream"
                             if j.get("kind") == "raw" else "application/pdf")
                    return self._send_file(j["file_path"],
                                           "printhub-job-%d.%s"
                                           % (j["id"], "prn"
                                              if j.get("kind") == "raw"
                                              else "pdf"), ctype)
                return self._send(404, {"ok": False,
                                        "error": "job or file not found"})
        return self._send(404, {"ok": False, "error": "unknown endpoint"})

    def _csv_response(self, which, rows):
        if which == "audit":
            cols = ["id", "ts", "event", "job_id", "actor", "site", "ip",
                    "doc_hash", "printer", "reason", "details"]
            name = "printhub-audit-%s.csv"
        else:
            cols = ["id", "created_at", "kind", "title", "printer", "copies",
                    "status", "priority", "attempts", "source", "site",
                    "origin_ip", "pages", "duplex", "paper_size", "tray",
                    "profile", "reason", "duration_ms", "error", "content_hash"]
            name = "printhub-history-%s.csv"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore",
                           lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
        data = buf.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"'
                         % (name % datetime.now().strftime("%Y%m%d-%H%M%S")))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        u = urlparse(self.path)
        route = u.path.rstrip("/")
        q = parse_qs(u.query)
        ctype = (self.headers.get("Content-Type") or "").lower()
        raw_pdf = None
        try:
            if route == "/print" and ("application/pdf" in ctype or
                                      "application/octet-stream" in ctype):
                # RAW BINARY upload - zero base64 cost.
                # application/pdf        -> PDF bytes (default)
                # application/octet-stream + ?kind=raw or ?lang=escpos|zpl
                #                        -> RAW printer bytes (ESC/POS / ZPL)
                # POST the bytes directly; parameters ride the query string:
                # /print?title=...&printer=...&copies=2&token=...
                body = {}
                raw_pdf = read_raw_body(self)
            elif route == "/print" and "multipart/form-data" in ctype:
                # multipart upload (Laravel Http::attach, curl -F, forms):
                # file field 'pdf'/'file' = PDF bytes, text fields = params
                raw_pdf, body = parse_multipart(
                    read_raw_body(self), self.headers.get("Content-Type"))
            else:
                body = read_json_body(self, required=(route == "/print"))
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"ok": False, "error": "bad request body: %s" % e})

        err = self._origin_error()
        if err:
            return self._send(err[0], {"ok": False, "error": err[1]})
        err = self._auth_error((q.get("token") or [""])[0], body)
        if err:
            return self._send(err[0], {"ok": False, "error": err[1]})
        ip = self._client_ip()
        site = self._request_site()

        # POST /jobs/{id}/reprint
        if route.startswith("/jobs/") and route.endswith("/reprint"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer stored"})
            # v2.0: the audit trail asks WHY something is printed again
            reason = str(body.get("reason") or "").strip()[:200] or None
            if CFG.get("reprint_reason_required") and not reason:
                return self._send(400, {
                    "ok": False,
                    "error": "a reprint reason is required on this hub"
                             " (reprint_reason_required) - add \"reason\""})
            wm = body.get("watermark")
            if wm is None:
                wm = CFG.get("reprint_watermark", False)
            elif isinstance(wm, str):
                wm = wm.strip().lower() in ("1", "true", "yes", "on")
            with open(j["file_path"], "rb") as f:
                data = f.read()
            if wm and j.get("kind") != "raw":
                data = pdf_watermark(data, str(body.get("watermark_text")
                                               or "REPRINT"))
            # a 'saved' (file-destination) job has no printer yet ->
            # reprinting it sends it to the OS default printer
            rpt_printer = str(body.get("printer") or "")
            if not rpt_printer:
                rpt_printer = "" if j["status"] == "saved" else (j["printer"] or "")
                if rpt_printer == "File (PDF)":
                    rpt_printer = ""
            job, dup = enqueue_print(
                j["kind"], (j["title"] or "reprint") + "-reprint", data,
                rpt_printer, j["copies"] or 1, "api", ip,
                site=site, reason=reason,
                dedupe=False,          # a reprint is never a duplicate
                priority=(j.get("priority") or 5),
                pages=j.get("pages"), duplex=j.get("duplex"),
                paper_size=j.get("paper_size"), tray=j.get("tray"),
                profile=j.get("profile"),
                content_hash=hashlib.sha256(data).hexdigest(),
                **({"watermarked": 1} if wm else {}))
            db_audit("reprint", job_id=job, actor="api", site=site, ip=ip,
                     doc_hash=hashlib.sha256(data).hexdigest(),
                     printer=rpt_printer, reason=reason,
                     details="reprint of job #%d%s"
                             % (j["id"], ", watermarked" if wm else ""))
            return self._send(200, {"ok": True, "job_id": job,
                                    "duplicate": dup is not None,
                                    "reprint_of": j["id"],
                                    "watermark": bool(wm and
                                                      j.get("kind") != "raw")})

        # POST /jobs/{id}/retry - failed/dead/held jobs, optionally on
        # ANOTHER printer (dead-letter recovery)
        if route.startswith("/jobs/") and route.endswith("/retry"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] not in ("failed", "dead", "canceled", "held",
                                   "scheduled"):
                return self._send(409, {"ok": False,
                                        "error": "job %s cannot be retried"
                                                 % j["status"]})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer stored"})
            new_printer = str(body.get("printer") or "").strip()
            db_update(j["id"], status="queued", error=None,
                      attempts=0, next_attempt_at=None, held_reason=None,
                      printer=new_printer or j.get("printer") or "")
            db_audit("print.requeued", job_id=j["id"], printer=new_printer,
                     reason=str(body.get("reason") or "")[:200] or None,
                     ip=ip, site=site,
                     details="manual retry%s"
                             % (" on printer '%s'" % new_printer
                                if new_printer else ""))
            log("[RETRY] job #%d requeued by request%s"
                % (j["id"], " on printer '%s'" % new_printer
                   if new_printer else ""))
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "printer": new_printer or j.get("printer")})

        # POST /jobs/{id}/priority {"priority": 1..9}
        if route.startswith("/jobs/") and route.endswith("/priority"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            try:
                pr = max(1, min(9, int(body.get("priority"))))
            except (TypeError, ValueError):
                return self._send(400, {"ok": False,
                                        "error": "priority must be 1-9"})
            db_update(j["id"], priority=pr)
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "priority": pr})

        # POST /jobs/{id}/cancel  (queued -> canceled; printing -> killed)
        if route.startswith("/jobs/") and route.endswith("/cancel"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] in ("printed", "failed", "canceled", "saved",
                               "dead", "forwarded"):
                return self._send(409, {"ok": False,
                                        "error": "job already finished (%s)" % j["status"]})
            db_update(j["id"], status="canceled", error="canceled by user",
                      held_reason=None)
            db_audit("job.canceled", job_id=j["id"], ip=ip, site=site,
                     printer=j.get("printer"))
            killed = cancel_current_print()
            if killed == j["id"]:
                log("[CANCELED] job #%d killed while printing" % j["id"])
            return self._send(200, {"ok": True, "canceled": j["id"],
                                    "was_printing": killed == j["id"]})

        # POST /queue/pause | /queue/resume | /queue/clear
        if route in ("/queue/pause", "/queue/resume", "/queue/clear"):
            if route == "/queue/pause":
                RESUME_EVENT.clear()
                db_audit("queue.paused", ip=ip, site=site)
                log("[QUEUE] paused by request")
            elif route == "/queue/resume":
                RESUME_EVENT.set()
                db_audit("queue.resumed", ip=ip, site=site)
                log("[QUEUE] resumed by request")
            else:
                n = 0
                for j in db_list(limit=500, status="queued"):
                    db_update(j["id"], status="canceled",
                              error="queue cleared by user")
                    n += 1
                db_audit("queue.cleared", ip=ip, site=site, details="%d jobs" % n)
                log("[QUEUE] cleared %d pending job(s)" % n)
                return self._send(200, {"ok": True, "canceled": n})
            return self._send(200, {"ok": True,
                                    "paused": not RESUME_EVENT.is_set()})

        # POST /autostart  {"enabled": true|false}
        if route == "/autostart":
            enable = body.get("enabled")
            if enable is None:
                enable = (q.get("enabled") or [""])[0].lower() in ("1", "true", "on", "yes")
            state = autostart_set(bool(enable))
            return self._send(200, {"ok": True, "enabled": state,
                                    "path": autostart_path()})

        # POST /token/rotate - generate a fresh random token (v2.0)
        if route == "/token/rotate":
            newtok = secrets.token_urlsafe(24)
            CFG["token"] = newtok
            disk = {k: CFG[k] for k in CONFIG_KEYS}
            write_config_file(disk)
            db_audit("token.rotated", ip=ip, site=site,
                     details="token changed via API")
            log("[TOKEN] rotated via API - new token saved to config.json")
            return self._send(200, {"ok": True, "token": newtok,
                                    "hint": "save this token now - enter it"
                                            " in the extension Options page"})

        # POST /config - update v2.0 settings at runtime (persists)
        if route == "/config":
            changed = []
            for key, val in (body or {}).items():
                if key == "token":
                    return self._send(400, {
                        "ok": False,
                        "error": "use POST /token/rotate to change the token"})
                if key not in CONFIG_TYPES:
                    return self._send(400, {
                        "ok": False, "error": "unknown config key '%s'" % key})
                want = CONFIG_TYPES[key]
                try:
                    if want is bool:
                        val = bool(val)
                    elif want is int:
                        val = max(0, int(val))
                    elif want is list:
                        if not isinstance(val, list):
                            raise ValueError("must be a list")
                        val = [str(x) for x in val]
                    elif want is dict:
                        if not isinstance(val, dict):
                            raise ValueError("must be an object")
                        val = val
                except (TypeError, ValueError) as e:
                    return self._send(400, {"ok": False,
                                            "error": "config '%s': %s" % (key, e)})
                CFG[key] = val
                changed.append(key)
            if changed:
                disk = {k: CFG[k] for k in CONFIG_KEYS}
                write_config_file(disk)
                db_audit("config.changed", ip=ip, site=site,
                         details=", ".join(changed))
                log("[CONFIG] updated: %s" % ", ".join(changed))
            return self._send(200, {"ok": True, "changed": changed,
                                    "config": redacted_config()})

        # POST /print
        if route == "/print":
            def bget(key, default=None):
                # JSON/multipart body first, query string second (?key=...)
                v = body.get(key)
                if v is None or v == "":
                    v = (q.get(key) or [default])[0]
                return v
            kind = (bget("kind") or "").lower()
            title = str(bget("title") or "document")[:60]
            printer = str(bget("printer") or "")[:120]
            source = str(bget("source") or "api")[:20]
            paper = (bget("paper") or ("thermal" if kind == "thermal" else "a4")).lower()
            landscape = bget("landscape")
            if isinstance(landscape, str):
                landscape = landscape.strip().lower() in ("1", "true", "yes", "on")
            copies = bget("copies") or 1
            try:
                copies = max(1, min(int(copies), 50))
            except (TypeError, ValueError):
                copies = 1
            # ---- v2.0 print options ----
            try:
                priority = max(1, min(9, int(bget("priority") or 5)))
            except (TypeError, ValueError):
                priority = 5
            pages = str(bget("pages") or "")[:60] or None
            duplex = str(bget("duplex") or "")[:20] or None
            paper_size = str(bget("paper_size") or "")[:20] or None
            tray = str(bget("tray") or "")[:40] or None
            reason = str(bget("reason") or "")[:200] or None
            profile_name = str(bget("profile") or "")[:60] or None
            lang = (bget("lang") or "").lower()
            # dedupe override (?dedupe=false / {"dedupe": false})
            dedupe_req = bget("dedupe")
            if dedupe_req is None:
                dedupe_req = True
            elif isinstance(dedupe_req, str):
                dedupe_req = dedupe_req.strip().lower() not in (
                    "0", "false", "off", "no")
            else:
                dedupe_req = bool(dedupe_req)
            # run_at: ISO datetime OR relative "+5m" / "+2h" / "+30s"
            run_at = None
            raw_run_at = str(bget("run_at") or "").strip()
            if raw_run_at:
                m = re.match(r"^\+(\d+)\s*([smhd])$", raw_run_at.lower())
                if m:
                    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
                    run_at = (datetime.now() +
                              timedelta(seconds=int(m.group(1)) * mult)) \
                        .isoformat(timespec="seconds")
                else:
                    try:
                        run_at = datetime.fromisoformat(
                            raw_run_at.replace("Z", "")).isoformat(timespec="seconds")
                    except ValueError:
                        return self._send(400, {
                            "ok": False,
                            "error": "run_at must be ISO datetime or"
                                     " +N(s|m|h|d)"})
            # print profile (v2.0): named defaults, request values win
            if profile_name:
                prof = (CFG.get("profiles") or {}).get(profile_name)
                if not isinstance(prof, dict):
                    return self._send(400, {"ok": False,
                                            "error": "unknown profile '%s'"
                                                     % profile_name})
                if not printer:
                    printer = str(prof.get("printer") or "")
                paper_size = paper_size or prof.get("paper_size") or prof.get("paper")
                tray = tray or prof.get("tray")
                duplex = duplex or prof.get("duplex")
                pages = pages or prof.get("pages")
                if "copies" in prof and copies == 1:
                    try:
                        copies = max(1, min(int(prof["copies"]), 50))
                    except (TypeError, ValueError):
                        pass
            # Queue Mode: body/query "queue": false -> print immediately,
            # bypassing the FIFO (pause has no effect on direct jobs).
            queue_mode = bget("queue")
            if queue_mode is None:
                queue_mode = True
            elif isinstance(queue_mode, str):
                queue_mode = queue_mode.strip().lower() not in (
                    "0", "false", "off", "no")
            else:
                queue_mode = bool(queue_mode)
            # destination: "printer" (default) | "file" (save as PDF, no paper)
            # printer value "__file__" is the extension's alias for destination file
            destination = (bget("destination") or
                           ("file" if printer == "__file__" else "printer")).lower()
            if destination not in ("printer", "file"):
                destination = "printer"
            if destination == "file":
                printer = ""
            data = None
            wm_flag = bget("watermark")
            if wm_flag is None:
                wm_flag = False
            elif isinstance(wm_flag, str):
                wm_flag = wm_flag.strip().lower() in ("1", "true", "yes", "on")
            wm_text = str(bget("watermark_text") or "REPRINT")[:24]

            if raw_pdf is not None:
                if (q.get("kind") or [""])[0].lower() == "raw" or lang in (
                        "escpos", "zpl"):
                    data = raw_pdf
                    kind = "raw"
                elif len(raw_pdf) > MAX_PDF:
                    return self._send(400, {"ok": False,
                                            "error": "PDF larger than %d MB" % (MAX_PDF // (1024 * 1024))})
                elif not raw_pdf[:5].startswith(b"%PDF"):
                    return self._send(400, {"ok": False,
                                            "error": "raw body is not a PDF (must start with %PDF-)"
                                                     " - add ?kind=raw for ESC/POS/ZPL bytes"})
                else:
                    data = raw_pdf
                    kind = kind or "a4"
            elif body.get("raw_base64") or (lang in ("escpos", "zpl") and
                                            body.get("text") is not None):
                try:
                    data, lang = raw_payload_bytes(body)
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                kind = "raw"
            elif body.get("pdf_base64"):
                try:
                    data = base64.b64decode(body["pdf_base64"], validate=False)
                except Exception as e:
                    return self._send(400, {"ok": False,
                                            "error": "bad pdf_base64: %s" % e})
                if not data[:5].startswith(b"%PDF"):
                    return self._send(400, {"ok": False,
                                            "error": "pdf_base64 is not a PDF"})
                kind = kind or "a4"
            elif body.get("pdf_url"):
                try:
                    data = download_pdf(body["pdf_url"])
                except Exception as e:
                    return self._send(400, {"ok": False,
                                            "error": "pdf_url failed: %s" % e})
                kind = kind or "a4"
            elif body.get("image_base64"):
                try:
                    img = base64.b64decode(body["image_base64"], validate=False)
                    if img[:3] == b"\xff\xd8\xff":
                        data, _ = image_pdf_bytes(img, title,
                                                  paper="thermal" if paper == "thermal" else "a4",
                                                  landscape=landscape)
                    else:
                        return self._send(400, {
                            "ok": False,
                            "error": "image_base64 must be a JPEG (image/jpeg);"
                                     " PNG is not supported - re-encode as JPEG"})
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                kind = "image-thermal" if paper == "thermal" else "image"
            elif body.get("html") is not None:
                try:
                    data, _ = html_to_pdf_bytes(body["html"], is_url=False,
                                                title=title)
                except Exception as e:
                    return self._send(500, {"ok": False,
                                            "error": "html render failed: %s" % e})
                kind = "page"
            elif body.get("page_url"):
                try:
                    data, _ = html_to_pdf_bytes(body["page_url"], is_url=True,
                                                title=title)
                except Exception as e:
                    return self._send(500, {"ok": False,
                                            "error": "page render failed: %s" % e})
                kind = "page"
            elif body.get("text") is not None:
                data, _ = thermal_pdf_bytes(body["text"], title,
                                            paper="thermal" if paper == "thermal" else "a4")
                kind = "thermal" if paper == "thermal" else "a4"
            else:
                return self._send(400, {"ok": False,
                                        "error": "provide pdf_base64, pdf_url,"
                                                 " image_base64, html, page_url,"
                                                 " text, raw_base64 or"
                                                 " text+lang=escpos|zpl"})

            if kind not in ("a4", "thermal", "image", "image-thermal", "page",
                            "raw"):
                kind = "a4"

            content_hash = hashlib.sha256(data).hexdigest()

            # optional REPRINT/draft watermark on the PDF itself
            if wm_flag and kind not in ("raw",):
                data = pdf_watermark(data, wm_text)

            db_audit("print.submitted", job_id=None, actor=source, site=site,
                     ip=ip, doc_hash=content_hash, printer=printer or None,
                     reason=reason)

            if destination == "file":
                if kind == "raw":
                    return self._send(400, {"ok": False,
                                            "error": "raw print cannot use"
                                                     " destination file"})
                job, fpath = save_file_job(kind, title, data, source, ip)
                return self._send(200, {
                    "ok": True, "job_id": job, "kind": kind,
                    "destination": "file", "status": "saved",
                    "file": fpath, "url_path": "/jobs/%d/file" % job,
                    "message": "saved as PDF file - no paper used",
                })

            job, dup = enqueue_print(
                kind, title, data, printer, copies, source, ip,
                queue_mode=queue_mode, priority=priority, run_at=run_at,
                site=site, dedupe=dedupe_req, content_hash=content_hash,
                reason=reason, profile=profile_name, pages=pages,
                duplex=duplex, paper_size=paper_size, tray=tray,
                **({"watermarked": 1} if (wm_flag and kind != "raw") else {}))
            resp = {
                "ok": True, "job_id": job, "kind": kind, "copies": copies,
                "destination": "printer",
                "queue_mode": "on" if queue_mode else "off",
                "duplicate": dup is not None,
                "priority": priority,
                "message": ("queued to printer" if queue_mode
                            else "printing immediately (queue mode off)"),
            }
            if dup is not None:
                resp["message"] = ("duplicate blocked - identical job #%d"
                                   " already accepted recently" % dup)
            if run_at:
                resp["scheduled_for"] = run_at
                resp["status"] = "scheduled"
            if lang:
                resp["lang"] = lang
            return self._send(200, resp)

        return self._send(404, {"ok": False, "error": "unknown endpoint"})

# ------------------------------------------------------------
# v2.0 helper views: redacted config, peers, diagnostics, dashboard
# ------------------------------------------------------------
REDACT_KEYS = ("token",)

def redacted_config():
    c = {k: CFG[k] for k in CONFIG_KEYS}
    for k in REDACT_KEYS:
        if k in c:
            c[k] = mask_token(c[k])
    peers = []
    for p in (CFG.get("peer_hubs") or []):
        q = dict(p)
        if q.get("token"):
            q["token"] = mask_token(q["token"])
        peers.append(q)
    c["peer_hubs"] = peers
    c["config_file"] = config_path()
    c["hint"] = ("POST the same keys to /config to change them;"
                 " use POST /token/rotate for the token")
    return c

_PEER_CACHE = {"t": 0.0, "v": []}

def probe_peers(timeout=3):
    """Health-probe every configured peer hub; dead ones are reported
    (and later skipped by the forwarding logic). Cached 15 s."""
    peers = CFG.get("peer_hubs") or []
    if not peers:
        return []
    if time.time() - _PEER_CACHE["t"] < 15 and _PEER_CACHE["v"]:
        return _PEER_CACHE["v"]
    out = []
    for peer in peers:
        url = (peer.get("url") or "").rstrip("/")
        entry = {"url": url, "alive": False, "version": None,
                 "latency_ms": None}
        if url:
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url + "/health",
                    headers={"X-PrintHub-Token": peer.get("token") or "",
                             "User-Agent": "PrintHubPro/%s" % VERSION})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                entry["alive"] = True
                entry["version"] = data.get("version")
                entry["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                entry["error"] = str(e)[:100]
        out.append(entry)
    _PEER_CACHE["t"] = time.time()
    _PEER_CACHE["v"] = out
    return out

def _log_tail(lines=40):
    path = os.path.join(CFG["data_dir"], "hub.log")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return []

def build_diagnostics():
    """Everything a support request needs - with the token REDACTED."""
    st = db_stats() if os.path.isfile(db_path()) else {}
    diag = {
        "ok": True,
        "app": APP_NAME, "version": VERSION, "branding": BRANDING,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
        "data_dir": CFG["data_dir"],
        "config_file": config_path(),
        "uptime_s": int(time.time() - START_TS),
        "listen": "%s:%d" % (CFG["host"], CFG["port"]),
        "token": mask_token(CFG["token"]),
        "token_header_only": bool(CFG.get("token_header_only")),
        "default_token_warning": DEFAULT_TOKEN_WARNING,
        "paused": not RESUME_EVENT.is_set(),
        "db": st,
        "printers": [{"name": n, "status": s} for n, s in
                     printers_status().items()],
        "default_printer": default_printer(),
        "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
        "browser_found": find_browser() is not None,
        "service": service_state(),
        "autostart": autostart_enabled(),
        "peers": probe_peers(),
        "config": redacted_config(),
        "log_tail": _log_tail(),
    }
    return diag

def dashboard_html(query=""):
    """The built-in web dashboard (v2.0): success rate, queue size,
    printers, live queue, history, audit trail - one file, no assets."""
    q = ("?" + query) if query else ""
    return (DASHBOARD_HTML
            .replace("@@VERSION@@", VERSION)
            .replace("@@BRANDING@@", BRANDING.replace(" - ", " &middot; "))
            .replace("@@Q@@", q))

DASHBOARD_AUTH_ERROR_TMPL = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrintHub Pro - dashboard needs the current token</title>
<style>
 body{font-family:"Segoe UI",system-ui,sans-serif;background:#f1f5f9;margin:0;
      display:flex;min-height:100vh;align-items:center;justify-content:center}
 .c{background:#fff;max-width:600px;width:92%;border-radius:12px;
    padding:26px 32px;box-shadow:0 4px 24px rgba(15,23,42,.08);
    border-top:4px solid #dc2626}
 h1{font-size:19px;margin:0 0 10px;color:#0f172a}
 p{color:#334155;line-height:1.55;margin:8px 0}
 ol{color:#334155;line-height:1.85;padding-left:22px;margin:10px 0}
 code{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;
      padding:1px 6px;font-size:12.5px;word-break:break-all}
 .m{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;
    border-radius:8px;padding:9px 12px;font-size:13px;word-break:break-word}
 .f{color:#64748b;font-size:12px;margin-top:14px;line-height:1.5}
</style></head><body><div class="c">
<h1>PrintHub Pro - dashboard needs the current token</h1>
<div class="m">__MSG__</div>
<p>The token in this link is not the hub's current token. This often
happens when a bookmark still uses the old default token
<code>PrintHub-2024</code>, or the token was rotated recently.</p>
<ol>
<li><b>Tray icon (easiest)</b> - right-click the PrintHub Pro tray icon
and choose <i>Open dashboard</i>. It always opens with the right token.</li>
<li><b>Command line</b> - in the hub folder run
<code>python printhub.py token</code>, then open
<code>/dashboard?token=THE-TOKEN</code>.</li>
<li><b>Config file</b> - the token is the <code>"token"</code> value in
<code>%USERPROFILE%\.printhub\config.json</code>
(Linux/Mac: <code>~/.printhub/config.json</code>).</li>
</ol>
<p class="f">Tip: after changing or rotating the token, also update it in
the extension (PrintHub Pro Options - Hub token) and replace old dashboard
bookmarks. Since v2.0.1 a wrong token in one Chrome window can no longer
lock out the other windows - the hub never locks the loopback IP
127.0.0.1 by default.</p>
</div></body></html>
"""


def dashboard_auth_error_html(message=""):
    """Friendly browser page when the dashboard token is wrong/missing."""
    msg = html.escape(str(message or "invalid or missing token"), quote=True)
    return DASHBOARD_AUTH_ERROR_TMPL.replace("__MSG__", msg)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PrintHub Pro Dashboard</title>
<style>
  :root{--blue:#1d4ed8;--ink:#0f172a;--mut:#64748b;--ok:#16a34a;
        --bad:#dc2626;--warn:#d97706;--bg:#f1f5f9;--card:#fff;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 "Segoe UI",system-ui,sans-serif;color:var(--ink);
       background:var(--bg);min-height:100vh}
  header{background:linear-gradient(135deg,#1e3a8a,#1d4ed8);color:#fff;
         padding:18px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  header .logo{width:34px;height:34px;border-radius:8px;background:#fff;
         color:var(--blue);font-weight:800;display:flex;align-items:center;
         justify-content:center;font-size:19px}
  header h1{font-size:18px;flex:1}
  header small{display:block;font-size:11px;opacity:.85;font-weight:400}
  main{max-width:1100px;margin:0 auto;padding:18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;
        padding:14px 16px}
  .card b{font-size:24px;display:block}
  .card span{color:var(--mut);font-size:12px}
  .warn{background:#fef3c7;border:1px solid #fcd34d;color:#92400e;
        padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:13px}
  .warn button{float:right}
  h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;
     color:var(--mut);margin:18px 0 8px}
  .panel{background:var(--card);border:1px solid #e2e8f0;border-radius:12px;
         padding:6px 12px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--mut);text-align:left;font-weight:600;padding:7px 8px;
     border-bottom:1px solid #eef2f7}
  td{padding:7px 8px;border-bottom:1px solid #f4f7fb;white-space:nowrap}
  .st{font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  .st.printed,.st.queued,.ready{background:#dcfce7;color:#166534}
  .st.printing{background:#dbeafe;color:#1e40af}
  .st.saved,.st.scheduled{background:#fef9c3;color:#854d0e}
  .st.held{background:#ffedd5;color:#9a3412}
  .st.dead,.st.failed,.st.canceled,.offline,.paper-out,.error{background:#fee2e2;color:#991b1b}
  .ready{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  .offline,.paper-out,.error{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:9px}
  button{border:1px solid #dbe2ee;background:#fff;border-radius:7px;
         padding:5px 10px;font:600 12px "Segoe UI",system-ui;cursor:pointer}
  button:hover{border-color:var(--blue);color:var(--blue)}
  button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
  .bar{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
  #msg{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);
       background:#0f172a;color:#fff;padding:9px 16px;border-radius:9px;
       font-size:13px;display:none;max-width:80vw}
</style></head><body>
<header>
  <div class="logo">P</div>
  <h1>PrintHub Pro <small>@@BRANDING@@</small></h1>
  <button class="primary" onclick="rotateToken()">Rotate token</button>
</header>
<main>
  <div class="warn" id="tokWarn" style="display:none">
    You are still using the DEFAULT token. Everyone who knows
    "PrintHub-2024" can print on this PC.
    <button onclick="rotateToken()">Rotate now</button>
  </div>
  <div class="bar">
    <button id="bPause" onclick="togglePause()">Pause queue</button>
    <button onclick="if(confirm('Cancel every waiting job?'))act('/queue/clear')">Clear queue</button>
    <a href="/export/history.csv@@Q@@"><button>History CSV</button></a>
    <a href="/audit.csv@@Q@@"><button>Audit CSV</button></a>
    <a href="/diagnostics@@Q@@"><button>Diagnostics JSON</button></a>
    <button onclick="location='/health'">Health JSON</button>
  </div>
  <div class="cards">
    <div class="card"><b id="cRate">-</b><span>success rate (7 days)</span></div>
    <div class="card"><b id="cQueue">-</b><span>queue size</span></div>
    <div class="card"><b id="cToday">-</b><span>jobs today</span></div>
    <div class="card"><b id="cPrinters">-</b><span>printers ready</span></div>
    <div class="card"><b id="cVer">v@@VERSION@@</b><span>hub version</span></div>
  </div>
  <h2>Printers</h2>
  <div class="panel" id="printers"><table><tbody>
    <tr><td>Loading printers...</td></tr></tbody></table></div>
  <h2>Queue (waiting + printing)</h2>
  <div class="panel"><table><thead><tr>
    <th>#</th><th>Title</th><th>Printer</th><th>Status</th><th></th>
  </tr></thead><tbody id="queue"><tr><td>-</td></tr></tbody></table></div>
  <h2>Recent jobs</h2>
  <div class="panel"><table><thead><tr>
    <th>#</th><th>Time</th><th>Title</th><th>Printer</th><th>Status</th><th></th>
  </tr></thead><tbody id="jobs"><tr><td>-</td></tr></tbody></table></div>
  <h2>Audit trail (latest events)</h2>
  <div class="panel"><table><thead><tr>
    <th>Time</th><th>Event</th><th>Job</th><th>Site / IP</th><th>Printer</th><th>Reason / details</th>
  </tr></thead><tbody id="audit"><tr><td>-</td></tr></tbody></table></div>
</main>
<div id="msg"></div>
<script>
const Q = location.search || "";
const H = {"X-PrintHub-Token": new URLSearchParams(Q).get("token") || ""};
function msg(t){const m=document.getElementById("msg");m.textContent=t;
  m.style.display="block";setTimeout(()=>m.style.display="none",4000);}
async function jget(p){const r=await fetch(p+Q);return r.json();}
async function act(p,body){const r=await fetch(p+Q,{method:"POST",
  headers:Object.assign({"Content-Type":"application/json"},H),
  body:JSON.stringify(body||{})});return r.json();}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));}
async function refresh(){
  try{
    const st=await jget("/stats");
    document.getElementById("cRate").textContent=
      st.success_rate==null?"-":st.success_rate+"%";
    document.getElementById("cQueue").textContent=st.queue_size;
    document.getElementById("cToday").textContent=st.jobs_today;
    const pr=st.printers_ready;
    document.getElementById("cPrinters").textContent=
      pr+"/"+Object.keys(st.printers||{}).length;
    document.getElementById("bPause").textContent=
      st.paused?"Resume queue":"Pause queue";
    if(st.default_token_warning)
      document.getElementById("tokWarn").style.display="block";
    let ph="";
    for(const[n,s]of Object.entries(st.printers||{}))
      ph+="<tr><td>"+esc(n)+"</td><td><span class='st "+esc(s)+"'>"+
          esc(s)+"</span></td></tr>";
    if(!ph)ph="<tr><td>No printers detected.</td></tr>";
    document.querySelector("#printers tbody").innerHTML=ph;
    const q=await jget("/queue");
    const jobs=await jget("/jobs?limit=12");
    let qh="";
    for(const j of (jobs.jobs||[]).filter(j=>
        ["queued","printing","held","scheduled"].includes(j.status))){
      qh+="<tr><td>"+j.id+"</td><td>"+esc(j.title)+"</td><td>"+
          esc(j.printer||"default")+"</td><td><span class='st "+esc(j.status)+
          "'>"+esc(j.status)+(j.held_reason?" - "+esc(j.held_reason):"")+
          "</span></td><td><button onclick=\"act('/jobs/"+j.id+
          "/cancel').then(refresh)\">Cancel</button></td></tr>";
    }
    document.getElementById("queue").innerHTML=
      qh||"<tr><td>Queue is empty.</td></tr>";
    let jh="";
    for(const j of (jobs.jobs||[])){
      jh+="<tr><td>"+j.id+"</td><td>"+esc((j.created_at||"").replace("T"," "))+
          "</td><td>"+esc(j.title)+"</td><td>"+esc(j.printer||"default")+
          "</td><td><span class='st "+esc(j.status)+"'>"+esc(j.status)+
          "</span></td><td>";
      if(["failed","dead","canceled"].includes(j.status))
        jh+="<button onclick=\"const p=prompt('Retry on which printer? (empty = same)');"+
           "if(p!==null)act('/jobs/"+j.id+"/retry',{printer:p}).then(refresh)\">Retry</button> ";
      else if(j.status!=="printing")
        jh+="<button onclick=\"const r=prompt('Reprint - reason?');"+
           "if(r!==null)act('/jobs/"+j.id+"/reprint',{reason:r}).then(refresh)\">Reprint</button>";
      jh+="</td></tr>";
    }
    document.getElementById("jobs").innerHTML=
      jh||"<tr><td>No jobs yet.</td></tr>";
    const a=await jget("/audit?limit=10");
    let ah="";
    for(const e of (a.entries||[])){
      ah+="<tr><td>"+esc((e.ts||"").replace("T"," "))+"</td><td>"+
          esc(e.event)+"</td><td>"+(e.job_id||"")+"</td><td>"+
          esc(e.site||e.ip||"")+"</td><td>"+esc(e.printer||"")+"</td><td>"+
          esc(e.reason||e.details||"")+"</td></tr>";
    }
    document.getElementById("audit").innerHTML=
      ah||"<tr><td>No audit events yet.</td></tr>";
  }catch(e){msg("hub offline? "+e.message);}
}
async function togglePause(){
  const st=await jget("/queue");
  await act("/queue/"+(st.paused?"resume":"pause"));
  refresh();
}
async function rotateToken(){
  if(!confirm("Generate a NEW token? The old one stops working immediately."))return;
  const r=await act("/token/rotate");
  if(r.ok){prompt("Your NEW token - copy it into the extension Options page:",r.token);}
  else msg(r.error||"failed");
}
refresh();setInterval(refresh,5000);
</script></body></html>"""

# ------------------------------------------------------------
# Optional Windows service (services.msc -> "PrintHub")
# ------------------------------------------------------------
# The DEFAULT auto-run is a normal Startup app (tray icon visible).
# Advanced users can additionally install the hub as a real Windows
# service - it then appears in services.msc and can be started/stopped
# like any service. Both at once is fine but pointless (port conflict:
# the second one to start exits gracefully).

_SVC_CACHE = {"t": 0.0, "v": None}

def service_state():
    """{'installed':bool,'running':bool,'state':str} for the optional
    Windows service (sc query, cached 10 s). Non-Windows -> None.
    Never raises - any problem degrades to state 'unknown'."""
    if not IS_WIN:
        return None
    now = time.time()
    if now - _SVC_CACHE["t"] < 10 and _SVC_CACHE["v"] is not None:
        return _SVC_CACHE["v"]
    state = {"installed": False, "running": False, "state": "not installed"}
    try:
        r = subprocess.run(["sc", "query", SERVICE_NAME],
                           capture_output=True, text=True, timeout=6)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 1060 or "STATE" not in out.upper():
            state["state"] = "not installed"
        else:
            state["installed"] = True
            for line in out.splitlines():
                if "STATE" in line:
                    s = line.split()[-1].strip().upper()
                    state["state"] = s.lower().replace("_", " ")
                    state["running"] = s == "RUNNING"
                    break
            else:
                state["state"] = "installed"
    except Exception:
        state = {"installed": False, "running": False, "state": "unknown"}
    _SVC_CACHE["t"] = now
    _SVC_CACHE["v"] = state
    return state


def _service_bat_path(action):
    """Locate (or generate) the elevated helper .bat for sc <action>.
    The installer ships service-install.bat / service-remove.bat next to
    the hub dir's parent (%LOCALAPPDATA%\\PrintHubPro); if they are not
    there we generate an equivalent one in the data dir."""
    name = "service-install.bat" if action == "install" else "service-remove.bat"
    here = hub_dir()
    for cand in (os.path.join(os.path.dirname(here), name),
                 os.path.join(here, name)):
        if os.path.isfile(cand):
            return cand
    # generate (portable layout / manual installs)
    py_exe = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if not os.path.isfile(py_exe):
        py_exe = sys.executable
    script = os.path.join(here, "service_main.py")
    lines = ["@echo off"]
    if action == "install":
        lines += [
            'sc create %s binPath= "\\"%s\\" \\"%s\\"" start= auto '
            'DisplayName= "%s"' % (SERVICE_NAME, py_exe, script,
                                   SERVICE_DISPLAYNAME),
            'sc description %s "PrintHub Pro silent print bridge '
            '(Bitdream IT) - manage in services.msc"' % SERVICE_NAME,
            'sc failure %s reset= 86400 actions= restart/5000/'
            'restart/5000/restart/60000' % SERVICE_NAME,
            "sc start %s" % SERVICE_NAME,
        ]
    else:
        lines += ["sc stop %s" % SERVICE_NAME,
                  "sc delete %s" % SERVICE_NAME]
    lines.append("exit /b 0")
    ensure_dirs()
    p = os.path.join(CFG["data_dir"], name)
    with open(p, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write("\n".join(lines))
    return p


def cmd_service(action):
    """CLI: python printhub.py service-install | service-remove |
    service-status.  install/remove elevate via UAC and run sc.exe."""
    if not IS_WIN:
        print("Windows services are only available on Windows.")
        print("On Linux/macOS use the systemd user service (install-unix.sh / .deb).")
        return
    if action == "status":
        st = service_state()
        print("Windows service '%s': %s" % (SERVICE_NAME, st["state"]))
        if st["installed"]:
            print("Manage it in services.msc (name: %s), or:" % SERVICE_NAME)
            print("  stop : python printhub.py service-remove")
        else:
            print("Install it with:  python printhub.py service-install")
            print("(a UAC prompt will appear - admin approval needed once)")
        return
    bat = _service_bat_path(action)
    if not os.path.isfile(bat):
        print("Helper script missing: %s" % bat)
        return
    print("Requesting administrator approval (UAC prompt) ...")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Start-Process -FilePath '%s' -Verb RunAs -Wait" % bat],
            timeout=240)
    except Exception as e:
        print("Elevation failed or was canceled: %s" % e)
        return
    time.sleep(1.5)
    _SVC_CACHE["t"] = 0.0
    st = service_state()
    if action == "install":
        if st["installed"]:
            print("Windows service '%s' is now: %s" % (SERVICE_NAME, st["state"]))
            print("Visible in services.msc as '%s'." % SERVICE_DISPLAYNAME)
        else:
            print("Service install did not complete - check the UAC prompt")
            print("and run 'python printhub.py service-status' to verify.")
    else:
        if not st["installed"]:
            print("Windows service '%s' removed." % SERVICE_NAME)
        else:
            print("Service still present (state: %s) - try again or use "
                  "services.msc to remove it." % st["state"])


# ------------------------------------------------------------
# GitHub update check
# ------------------------------------------------------------
def github_latest_version(timeout=8):
    """(version, url) of the newest GitHub release; raises on failure."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
        headers={"User-Agent": "PrintHubPro/%s" % VERSION,
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    tag = str(data.get("tag_name") or "").lstrip("vV")
    return tag, (data.get("html_url") or GITHUB_RELEASES)


def cmd_update_check():
    """CLI: python printhub.py update-check"""
    print(BANNER)
    print("Installed version : PrintHub Pro v%s" % VERSION)
    print("Checking GitHub .. %s" % GITHUB_RELEASES)
    try:
        latest, url = github_latest_version()
    except Exception as e:
        print("Could not reach GitHub (%s)." % e)
        print("Check manually: %s" % GITHUB_RELEASES)
        return 1
    def vnum(s):
        n = [int(x) for x in re.findall(r"\d+", s)[:3]]
        return n if len(n) == 3 else [0, 0, 0]
    if vnum(latest) > vnum(VERSION):
        print("")
        print("UPDATE AVAILABLE:  v%s   (you have v%s)" % (latest, VERSION))
        print("Download: %s" % url)
        try:
            if IS_WIN:
                os.startfile(url)          # opens the browser
            else:
                webbrowser.open(url)
        except Exception:
            pass
    else:
        print("You are up to date (latest release: v%s)." % latest)
    return 0


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------
BANNER = r"""
  ____  _             _      ____  __  __
 |  _ \| | __ _ _ __ | | ___|  _ \|  \/  | __ _ _ __   ___ ___
 | |_) | |/ _` | '_ \| |/ _ \ |_) | |\/| |/ _` | '_ \ / __/ _ \
 |  __/| | (_| | | | | |  __/  __/| |  | | (_| | | | | (_|  __/
 |_|   |_|\__,_|_| |_|_|\___|_|   |_|  |_|\__,_|_| |_|\___\___|
            v%s  by %s  -  open source (MIT)
  100%% local - no cloud, no tracking
""" % (VERSION, VENDOR)

def cmd_serve():
    db_init()
    start_worker()
    addr = (CFG["host"], CFG["port"])
    try:
        httpd = ThreadingHTTPServer(addr, Handler)
    except OSError as e:
        # second instance guard: hub already running? do not scare the user
        log("FATAL: cannot bind %s:%d (%s)" % (CFG["host"], CFG["port"], e))
        log("PrintHub Pro is probably ALREADY running (check the tray icon"
            " near the clock, or Task Manager -> 'PrintHubPro'). Exiting.")
        time.sleep(1.2)
        return
    httpd.daemon_threads = True
    print(BANNER)
    log("%s" % BRANDING)
    log("PrintHub Pro v%s listening on http://%s:%d" % (VERSION, CFG["host"], CFG["port"]))
    log("Health check -> http://127.0.0.1:%d/health" % CFG["port"])
    log("Dashboard     -> http://127.0.0.1:%d/dashboard?token=%s" % (CFG["port"], CFG["token"]))
    if DEFAULT_TOKEN_WARNING:
        log("[SECURITY] WARNING: the default token is still in use!"
            " Change it with:  python printhub.py token-rotate")
    log("Open the extension popup and click Connect. Press Ctrl+C to stop.")
    _start_tray(httpd)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopped by user (Ctrl+C)")


def _start_tray(httpd):
    """Windows tray icon ('PrintHub Pro' next to the clock) with a control
    menu. 100% optional: any failure just means no tray icon."""
    if not IS_WIN:
        return
    try:
        import tray_windows
    except Exception as e:
        log("tray icon unavailable (%s) - printing still works" % e)
        return

    def _open_status():
        webbrowser.open("http://127.0.0.1:%d/health" % CFG["port"])

    def _test():
        data, _ = thermal_pdf_bytes(
            "#big PrintHub Pro TEST PAGE\n\nIf this page printed, the hub works.\n"
            "Time: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tray-test", paper="a4")
        job, _dup = enqueue_print("a4", "tray-test", data, dedupe=False,
                                  origin_ip="tray")
        log("[OK] test page queued from tray (job #%d)" % job)

    def _pause_toggle():
        if RESUME_EVENT.is_set():
            RESUME_EVENT.clear()
            log("[QUEUE] paused via tray menu")
            return True
        RESUME_EVENT.set()
        log("[QUEUE] resumed via tray menu")
        return False

    def _auto_toggle():
        newv = not autostart_enabled()
        return autostart_set(newv)

    def _exit():
        log("PrintHub Pro stopped from the tray icon menu")
        threading.Timer(0.5, os._exit, args=(0,)).start()
        try:
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        except Exception:
            pass

    tray_windows.start(
        icon=hub_icon_path(),
        tooltip="PrintHub Pro v%s - running on http://127.0.0.1:%d"
                % (VERSION, CFG["port"]),
        callbacks={
            "on_open": _open_status,
            "on_test": _test,
            "is_paused": lambda: not RESUME_EVENT.is_set(),
            "on_pause_toggle": _pause_toggle,
            "is_autostart": autostart_enabled,
            "on_autostart_toggle": _auto_toggle,
            "on_exit": _exit,
        },
        logf=log)

def cmd_testprint(kind):
    db_init(); start_worker()
    kind = kind if kind in ("a4", "thermal") else "a4"
    if kind == "thermal":
        data, _ = thermal_pdf_bytes(
            "#big PrintHub Pro\n|center|Bitdream IT - TEST RECEIPT\n"
            "--------------------------------\n"
            "Item 1              10.00\nItem 2              25.50\n"
            "--------------------------------\nTOTAL               35.50\n"
            "\n|center|Thank you!\n", "testprint")
    else:
        data, _ = thermal_pdf_bytes(
            "#big PrintHub Pro TEST PAGE\n\nIf this page printed, the hub works.\n"
            "Time: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "testprint", paper="a4")
    job, _dup = enqueue_print(kind, "cli-" + kind, data, dedupe=False,
                              origin_ip="cli")
    print("Job #%d queued (%s). Watch the printer..." % (job, kind))

def cmd_history(limit):
    db_init()
    rows = db_list(limit)
    if not rows:
        print("No print jobs yet.")
        return
    print("%-4s %-19s %-8s %-22s %-9s %-9s %-7s %s" %
          ("ID", "TIME", "KIND", "PRINTER", "STATUS", "SOURCE", "MS", "TITLE"))
    print("-" * 100)
    for r in rows:
        print("%-4s %-19s %-8s %-22s %-9s %-9s %-7s %s" %
              (r["id"], (r["created_at"] or "")[0:19], r["kind"],
               (r["printer"] or "-")[:22], r["status"],
               r.get("source") or "-", r["duration_ms"] or "-",
               r["title"] or "-"))

def cmd_reprint(job_id, reason=None, printer=None):
    db_init(); start_worker()
    j = db_get(int(job_id))
    if not j:
        print("Job #%s not found." % job_id); sys.exit(1)
    if not (j.get("file_path") and os.path.exists(j["file_path"])):
        print("Original file of job #%s is gone - cannot reprint." % job_id); sys.exit(1)
    with open(j["file_path"], "rb") as f:
        data = f.read()
    if CFG.get("reprint_watermark"):
        data = pdf_watermark(data)
    nid, _dup = enqueue_print(j["kind"], (j["title"] or "reprint") + "-reprint",
                              data, printer or j["printer"] or "",
                              j["copies"] or 1, "cli", "cli",
                              dedupe=False, reason=reason)
    db_audit("reprint", job_id=nid, actor="cli", reason=reason,
             printer=printer or j["printer"],
             details="reprint of job #%s" % job_id)
    print("Reprinted as job #%d (copy of #%d)." % (nid, j["id"]))

def cmd_token():
    db_init()
    print("Current hub token: %s" % CFG["token"])
    print("(enter it in the extension Options page; stored in %s)"
          % config_path())
    if DEFAULT_TOKEN_WARNING:
        print("WARNING: this is the DEFAULT token - rotate it with:")
        print("  python printhub.py token-rotate")

def cmd_token_rotate():
    db_init()
    old = CFG["token"]
    CFG["token"] = secrets.token_urlsafe(24)
    disk = {k: CFG[k] for k in CONFIG_KEYS}
    write_config_file(disk)
    db_audit("token.rotated", actor="cli",
             details="token changed via CLI")
    print("Token ROTATED.")
    print("  old: %s" % old)
    print("  new: %s" % CFG["token"])
    print("Enter the new token in the extension Options page.")

def cmd_diagnostics():
    db_init()
    diag = build_diagnostics()
    fname = "diagnostics-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(CFG["data_dir"], fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2, ensure_ascii=False)
    print(BANNER)
    print("Diagnostics written to:")
    print("  %s" % path)
    print("(the token is redacted - attach this file to support requests)")
    return path

def cmd_queue():
    db_init()
    paused = not RESUME_EVENT.is_set()
    cur = None
    with _CURRENT_LOCK:
        if _CURRENT["id"]:
            cur = db_get(_CURRENT["id"])
    print("Queue: %s | pending: %d" % ("PAUSED" if paused else "running",
                                       db_count_pending()))
    if cur:
        print("Current: job #%d %s -> %s" % (cur["id"], cur["title"],
                                             cur["printer"] or "default"))

def cmd_doctor():
    print(BANNER)
    results = []
    results.append(("Python >= 3.8", sys.version_info >= (3, 8),
                    sys.version.split()[0]))
    results.append(("OS", True, "windows" if IS_WIN else ("macos" if IS_MAC else "linux")))
    if IS_WIN:
        s = find_sumatra()
        results.append(("SumatraPDF (silent PDF print)", bool(s),
                        s or "NOT FOUND - " + SUMATRA_HINT))
    else:
        lp = shutil.which("lp")
        results.append(("CUPS lp command", bool(lp), lp or "apt install cups-client"))
    b = find_browser()
    results.append(("Chrome/Edge (page printing)", bool(b), b or "optional - needed only for HTML/page printing"))
    try:
        db_init(); results.append(("Data dir + history.db writable", True, CFG["data_dir"]))
    except Exception as e:
        results.append(("Data dir + history.db writable", False, str(e)))
    import socket
    sock = socket.socket()
    try:
        sock.bind((CFG["host"], CFG["port"])); free = True
    except OSError:
        free = False
    finally:
        sock.close()
    results.append(("Port %d free" % CFG["port"], free,
                    "OK" if free else "busy - another instance running?"))
    dps = list_printers()
    results.append(("Printers detected", bool(dps),
                    ", ".join(dps[:5]) or "none found"))
    results.append(("Default printer", bool(default_printer()),
                    default_printer() or "none set"))
    try:
        db_init()
        results.append(("v2.0 config.json", True,
                        config_path() +
                        ("  [DEFAULT TOKEN! rotate it]"
                         if DEFAULT_TOKEN_WARNING else "")))
    except Exception as e:
        results.append(("v2.0 config.json", False, str(e)))
    ok = True
    for name, passed, info in results:
        print("  [%s] %-34s %s" % ("OK" if passed else "!!", name, info))
        if not passed and "Printers" not in name and "Default printer" not in name \
                and "Chrome/Edge" not in name:
            ok = False
    print("\n  %s" % ("ALL CHECKS PASSED - start the hub with: python printhub.py serve" if ok
                      else "Fix the [!!] items above, then run doctor again."))

def cmd_help():
    print(BANNER)
    print("""Commands:
  serve                     Start the hub (default) - listens on port %d
  testprint [a4|thermal]    Send a test page to the default printer
  printers                  List installed printers (+ status)
  history [n]               Show last n print jobs (default 100)
  reprint <job_id>          Print a previous job again
  queue                     Show queue status (paused / pending / held)
  doctor                    Check everything and report [OK]/[!!]
  token                     Show the current API token
  token-rotate              Generate a NEW random token (old one stops)
  diagnostics               Export a support bundle (JSON, token redacted)
  service-install           Install PrintHub as a Windows service (UAC)
  service-remove            Remove the Windows service (UAC)
  service-status            Show Windows service state
  update-check              Check GitHub for a newer release
  help                      This help

Settings (config.json in the data dir - see docs/API.md):
  allowed_origins           Restrict which websites may print (default: all)
  printer_groups            {"Front": ["A", "B"]} fallback printers
  profiles                  {"Invoice": {"paper": "a4", "duplex": true}}
  max_retries               Exponential retry attempts (default 2)
  dedupe_minutes            Block duplicate jobs window (default 5)
  hold_offline              Hold jobs while printer offline (default on)
  reprint_watermark         Stamp REPRINT on reprints (default off)
  peer_hubs / peer_forwarding   Backup hubs on the network

Options (environment variables still override config.json):
  PRINTHUB_TOKEN    API token   (new installs: random, see 'token' command)
  PRINTHUB_PORT     HTTP port   (default 9235)
  PRINTHUB_HOST     Bind addr   (default 127.0.0.1 = this PC only)
  PRINTHUB_PRINTER  Force printer name (default: OS default)
  PRINTHUB_FILE_DIR Where "destination:file" PDFs are saved
                    (default ~/Downloads/PrintHub)
  PRINTHUB_DATA     Data folder (default ~/.printhub)

Chrome extension: see extension/ folder - load it unpacked in Chrome,
then click the PrintHub icon and press Connect.
Dashboard: http://127.0.0.1:9235/dashboard?token=<your token>
""" % CFG["port"])

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    try:
        if cmd in ("serve", "start"):
            cmd_serve()
        elif cmd == "testprint":
            cmd_testprint(args[1] if len(args) > 1 else "a4")
        elif cmd == "printers":
            st = printers_status()
            ps = list_printers()
            if not ps:
                print("No printers found.")
            for p in ps:
                print("%-38s %s" % (p, st.get(p, "unknown")))
        elif cmd == "history":
            cmd_history(int(args[1]) if len(args) > 1 else HISTORY_DEFAULT)
        elif cmd == "reprint":
            if len(args) < 2:
                print("usage: python printhub.py reprint <job_id> [reason]")
                sys.exit(1)
            reason = args[2] if len(args) > 2 else None
            cmd_reprint(args[1], reason=reason)
        elif cmd == "queue":
            cmd_queue()
        elif cmd == "doctor":
            cmd_doctor()
        elif cmd == "token":
            cmd_token()
        elif cmd == "token-rotate":
            cmd_token_rotate()
        elif cmd == "diagnostics":
            cmd_diagnostics()
        elif cmd == "service-install":
            cmd_service("install")
        elif cmd == "service-remove":
            cmd_service("remove")
        elif cmd == "service-status":
            cmd_service("status")
        elif cmd == "update-check":
            rc = cmd_update_check()
            if rc:
                sys.exit(rc)
        elif cmd in ("help", "--help", "-h"):
            cmd_help()
        elif cmd in ("--version", "version"):
            print("PrintHub Pro v%s by %s" % (VERSION, VENDOR))
        else:
            print("Unknown command: %s\n" % cmd)
            cmd_help(); sys.exit(1)
    except KeyboardInterrupt:
        print("\nBye!")

if __name__ == "__main__":
    main()

