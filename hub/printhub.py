#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
#  PrintHub Pro v1.7.0  -  Print from any web page to any printer
#  AdvMedi by Bit Dream IT  -  Innovative Healthcare Solutions
#  MIT licensed, 100% local & open source
# ------------------------------------------------------------
#  Chrome extension <-> this hub (localhost or LAN) -> ANY printer
#  NO print dialog. NO subscription. NO cloud. NO data collection.
#
#  * ZERO pip dependencies - pure Python 3.8+ standard library
#  * Cross-platform: Windows (SumatraPDF) / Linux & macOS (CUPS lp)
#  * Any printer: thermal, receipt, label, A4 - hub sees it, you print
#  * Print queue with pause / resume / cancel (survives restarts)
#  * Job history: unlimited in SQLite, reprint / retry / clear anytime
#  * Screenshot printing (JPEG -> PDF, pure Python)
#  * HTML / web page printing via headless Chrome or Edge
#  * Token auth, CORS + Private-Network headers, localhost by default
#  * v1.7.0 NETWORK SHARING: one-click share the hub on the LAN
#    (0.0.0.0 or your 192.168.x.x IP) so every PC prints through ONE
#    hub + ONE printer. Token-protected, connect-code pairing.
#  * v1.7.0 INDUSTRIAL QUEUE: auto-retry with backoff, failed jobs
#    stay in the list (Retry / Clear), failover forwarding to peer
#    hubs - if this PC cannot print, another PC's hub takes the job.
#
#  Quick start:   python printhub.py serve
#  Health check:  http://127.0.0.1:9235/health
#  Full check:    python printhub.py doctor
#  Help:          python printhub.py help
# ============================================================

import base64
import hmac
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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, parse_qsl, quote

VERSION = "1.7.0"
APP_NAME = "PrintHub Pro"
VENDOR = "Bit Dream IT"
BRAND_LINE = "AdvMedi by Bit Dream IT - Innovative Healthcare Solutions"
BRAND_URL = "https://www.bitdreamit.com"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HIDE = 0x08000000 if IS_WIN else 0          # no console window flash on Windows
MAX_BODY = 40 * 1024 * 1024                 # 40 MB hard cap on request body
MAX_PDF = 25 * 1024 * 1024                  # 25 MB cap for downloaded pdf_url
HISTORY_DEFAULT = 100                       # Ultraprint-style: last 100 jobs

# ------------------------------------------------------------
# Configuration (environment variables override defaults)
# ------------------------------------------------------------
CFG = {
    "host": os.environ.get("PRINTHUB_HOST", "127.0.0.1"),     # localhost by default
    "port": int(os.environ.get("PRINTHUB_PORT", "9235")),
    "token": os.environ.get("PRINTHUB_TOKEN", "PrintHub-2024"),
    "printer": os.environ.get("PRINTHUB_PRINTER", ""),        # empty = OS default
    "data_dir": os.environ.get(
        "PRINTHUB_DATA",
        os.path.join(os.path.expanduser("~"), ".printhub")),
    # destination "file": save the rendered PDF here instead of printing
    "file_dir": os.environ.get("PRINTHUB_FILE_DIR", ""),
    "keep_files": True,   # keep printed files so /reprint works
}

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

# ------------------------------------------------------------
# v1.7.0: persistent settings (config.json in the data dir).
# The hub can be SHARED on the LAN in one click: listen on 0.0.0.0
# (or a specific 192.168.x.x IP) so every PC in the office prints
# through this ONE hub + ONE printer. A token is ALWAYS required;
# when sharing is enabled an empty token is replaced by a random one
# so "just anyone" on the network cannot use the shared IP.
# ------------------------------------------------------------
DEFAULT_SETTINGS = {
    "auto_retry": True,        # failed jobs are re-queued automatically
    "retry_max": 3,            # ...up to this many print attempts
    "retry_interval": 60,      # seconds before the 1st retry (grows per attempt)
    "forward_on_fail": True,   # final local failure: offer the job to peer hubs
    "peers": [],               # ["http://192.168.1.20:9235|TOKEN2", ...]
    "retention_days": 7,       # delete finished job PDF files after N days
}
SETTINGS = dict(DEFAULT_SETTINGS)

def config_path():
    return os.path.join(CFG["data_dir"], "config.json")

def load_settings():
    """Read config.json (written by POST /share, the tray menu or the CLI).
    PRINTHUB_HOST/PORT/TOKEN environment variables keep priority."""
    global SETTINGS
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    for k, dv in DEFAULT_SETTINGS.items():
        v = saved.get(k, dv)
        if isinstance(dv, list):
            SETTINGS[k] = [x for x in v] if isinstance(v, list) else [x for x in dv]
        elif isinstance(dv, bool):
            SETTINGS[k] = bool(v)
        else:
            SETTINGS[k] = v
    if not os.environ.get("PRINTHUB_HOST"):
        h = saved.get("host")
        if isinstance(h, str) and h.strip():
            CFG["host"] = h.strip()
    if not os.environ.get("PRINTHUB_PORT"):
        p = saved.get("port")
        if isinstance(p, int) and 0 < p < 65536:
            CFG["port"] = p
    if not os.environ.get("PRINTHUB_TOKEN"):
        t = saved.get("token")
        if isinstance(t, str) and t.strip():
            CFG["token"] = t.strip()

def save_settings():
    """Persist host/port/token + queue settings to config.json (atomic)."""
    ensure_dirs()
    data = dict(SETTINGS)
    data["host"] = CFG["host"]
    data["port"] = CFG["port"]
    data["token"] = CFG["token"]
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, config_path())

def generate_token():
    return "PH-" + secrets.token_hex(9).upper()    # 18 hex chars, PH- prefix

def is_loopback_host(host):
    return str(host or "").lower() in ("127.0.0.1", "localhost", "::1")

def sharing_enabled():
    return not is_loopback_host(CFG["host"])

def get_lan_ip():
    """Best-effort primary LAN IPv4. UDP connect sends NO traffic."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for inf in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = inf[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"

def share_address():
    ip = CFG["host"]
    if ip in ("0.0.0.0", "::", ""):
        ip = get_lan_ip()
    return "http://%s:%d" % (ip, CFG["port"])

def connect_code():
    """One line to paste into the extension on ANOTHER PC:
    http://192.168.x.x:9235|TOKEN"""
    return "%s|%s" % (share_address(), CFG["token"])

def normalize_peer(p):
    """Accept 'http://ip:port|token', 'http://ip:port' or {url, token}."""
    if isinstance(p, dict):
        url = str(p.get("url") or "").strip().rstrip("/")
        tok = str(p.get("token") or "").strip()
        return {"url": url, "token": tok} if url else None
    s = str(p or "").strip()
    if not s:
        return None
    if "|" in s:
        url, tok = s.rsplit("|", 1)
        return {"url": url.strip().rstrip("/"), "token": tok.strip()}
    return {"url": s.rstrip("/"), "token": ""}

def ensure_dirs():
    os.makedirs(CFG["data_dir"], exist_ok=True)
    os.makedirs(os.path.join(CFG["data_dir"], "jobs"), exist_ok=True)
    try:
        os.makedirs(default_file_dir(), exist_ok=True)
    except OSError:
        pass

def db_path():
    return os.path.join(CFG["data_dir"], "history.db")

def log(msg):
    """Console + file log with timestamp."""
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        ensure_dirs()
        with open(os.path.join(CFG["data_dir"], "hub.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ------------------------------------------------------------
# Print history + queue state (SQLite)
# v1.7.0: one thread-local connection per thread (no reopen cost) +
# WAL mode; writes stay serialized through _DB_LOCK.
# ------------------------------------------------------------
_TLS = threading.local()
_DB_LOCK = threading.Lock()

def db():
    """Thread-local connection: one per thread, reused; busy_timeout
    guards against cross-thread contention."""
    conn = getattr(_TLS, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path(), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
        except sqlite3.Error:
            pass
        _TLS.conn = conn
    return conn

def db_init():
    ensure_dirs()
    with _DB_LOCK:
        conn = db()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   kind       TEXT NOT NULL,            -- a4 | thermal | image | page
                   title      TEXT,
                   printer    TEXT,
                   copies     INTEGER DEFAULT 1,
                   status     TEXT NOT NULL,            -- queued|printing|printed|failed|canceled|saved|forwarded
                   error      TEXT,
                   file_path  TEXT,
                   source     TEXT DEFAULT 'api',       -- extension | website | api | cli | peer
                   origin_ip  TEXT,
                   duration_ms INTEGER DEFAULT 0
               )"""
        )
        # v1.7.0 columns (safe on an existing 1.x database)
        for col in ("attempts INTEGER DEFAULT 0",
                    "next_retry_at REAL",
                    "forwarded_to TEXT",
                    "fit TEXT DEFAULT ''"):
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN %s" % col)
            except sqlite3.OperationalError:
                pass        # column already exists
        conn.commit()

def db_add(kind, title, printer, copies, file_path, source, origin_ip,
           status="queued", fit=""):
    with _DB_LOCK:
        cur = db().execute(
            "INSERT INTO jobs (created_at, kind, title, printer, copies, status,"
            " file_path, source, origin_ip, fit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), kind, title, printer,
             copies, status, file_path, source, origin_ip, fit or ""))
        db().commit()
        return cur.lastrowid

def db_update(job_id, **fields):
    sets = ", ".join("%s=?" % k for k in fields)
    with _DB_LOCK:
        db().execute("UPDATE jobs SET %s WHERE id=?" % sets,
                     (*fields.values(), job_id))
        db().commit()

def db_get(job_id):
    row = db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None

def db_list(limit=HISTORY_DEFAULT, status=None):
    if status:
        rows = db().execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, int(limit))).fetchall()
    else:
        rows = db().execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]

def db_next_queued():
    """Oldest queued job whose retry timer (if any) has expired - FIFO.
    The worker is DB-driven so the queue survives hub restarts and can
    be paused / cancelled / retried live."""
    row = db().execute(
        "SELECT * FROM jobs WHERE status='queued' AND (next_retry_at IS NULL"
        " OR next_retry_at<=?) ORDER BY id ASC LIMIT 1",
        (time.time(),)).fetchone()
    return dict(row) if row else None

def db_next_retry_time():
    row = db().execute(
        "SELECT MIN(next_retry_at) AS t FROM jobs WHERE status='queued'"
        " AND next_retry_at IS NOT NULL").fetchone()
    return row["t"] if row else None

def db_count_pending():
    row = db().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','printing')"
    ).fetchone()
    return int(row["n"])

def db_count_failed():
    row = db().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status='failed'").fetchone()
    return int(row["n"])

def db_count_today():
    today = datetime.now().strftime("%Y-%m-%d")
    row = db().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE created_at LIKE ?",
        (today + "%",)).fetchone()
    return int(row["n"])

def db_clear_jobs(scope="failed"):
    """Delete job rows (and their stored PDF files) by scope:
       failed | completed | all. History is otherwise UNLIMITED -
       this is only housekeeping. Returns (rows_deleted, files_deleted)."""
    scopes = {
        "failed": ("failed",),
        "forwarded": ("forwarded",),
        "completed": ("printed", "saved", "canceled", "forwarded"),
    }
    if scope == "all":
        rows = db_list(limit=1000000)
        with _DB_LOCK:
            db().execute("DELETE FROM jobs")
            db().commit()
    else:
        sts = scopes.get(scope)
        if not sts:
            return 0, 0
        ph = ",".join("?" * len(sts))
        with _DB_LOCK:
            rows = [dict(r) for r in db().execute(
                "SELECT * FROM jobs WHERE status IN (%s)" % ph, sts).fetchall()]
            db().execute("DELETE FROM jobs WHERE status IN (%s)" % ph, sts)
            db().commit()
    files = 0
    for r in rows:
        p = r.get("file_path")
        if p and os.path.exists(p):
            try:
                os.unlink(p)
                files += 1
            except OSError:
                pass
    return len(rows), files

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

_PR_CACHE = {"t": 0.0, "printers": []}      # v1.7.0: 15 s cache - the
_PR_TTL = 15.0                              # Options page polls /printers

def list_printers(force=False):
    """Return list of installed printer names (best effort, cached 15 s)."""
    now = time.time()
    if not force and _PR_CACHE["printers"] and now - _PR_CACHE["t"] < _PR_TTL:
        return _PR_CACHE["printers"]
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
        return _PR_CACHE["printers"]
    _PR_CACHE["printers"] = names
    _PR_CACHE["t"] = now
    return names

_DP_CACHE = {"t": 0.0, "value": None, "set": False}   # None = no default

def default_printer(force=False):
    """Return the OS default printer name (best effort, cached 15 s)."""
    now = time.time()
    if not force and _DP_CACHE["set"] and now - _DP_CACHE["t"] < _PR_TTL:
        return _DP_CACHE["value"]
    name = None
    try:
        if IS_WIN:
            ps = ("(Get-CimInstance Win32_Printer | Where-Object Default)"
                  ".Name")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            name = (out.stdout or "").strip() or None
        else:
            out = subprocess.run(["lpstat", "-d"], capture_output=True,
                                 text=True, timeout=10)
            for l in (out.stdout or "").splitlines():
                if "system default destination" in l:
                    name = l.split(":")[-1].strip()
                    break
    except Exception:
        name = None
    _DP_CACHE["value"] = name
    _DP_CACHE["set"] = True
    _DP_CACHE["t"] = now
    return name

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

def print_file(path, kind="a4", printer="", copies=1, job_id=None, fit=""):
    """
    Print a PDF file SILENTLY (no dialog) to the given printer
    or the OS default. Raises RuntimeError with a friendly message.
    The spawned process is registered so /jobs/{id}/cancel can kill it.
    fit: "" (auto), "fit" (always scale to page), "noscale" (1:1),
    "shrink" (only shrink large pages - SumatraPDF shrinkfit).
    """
    copies = max(1, min(int(copies or 1), 50))
    target = printer or CFG["printer"] or default_printer() or ""
    fit = (fit or "").lower()
    if fit not in ("fit", "noscale", "shrink"):
        fit = ""

    def register(proc):
        with _CURRENT_LOCK:
            _CURRENT["id"] = job_id
            _CURRENT["proc"] = proc
        return proc

    try:
        if IS_WIN:
            sumatra = find_sumatra()
            if not sumatra:
                raise RuntimeError(
                    "SumatraPDF not found. Install it first: %s" % SUMATRA_HINT)
            if fit == "fit":
                settings = "fit"
            elif fit == "noscale":
                settings = "noscale"
            elif fit == "shrink":
                settings = "shrinkfit"
            else:
                settings = ("noscale" if kind in ("thermal", "image-thermal")
                            else "shrinkfit")
            if copies > 1:
                settings += ",%dx" % copies
            cmd = [sumatra, "-silent", "-exit-when-done",
                   "-print-settings", settings]
            if target:
                cmd += ["-print-to", target]
            cmd.append(path)
            log("[PRINT] SumatraPDF -> %s (%s, %d copy/copies)"
                % (target or "OS default", kind, copies))
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
            if fit == "noscale":
                lp_opt = "noscale"
            elif fit in ("fit", "shrink"):
                lp_opt = "fit-to-page"
            else:
                lp_opt = "fit-to-page" if kind in ("a4", "image") else "noscale"
            cmd += ["-o", lp_opt, path]
            log("[PRINT] lp -> %s (%s, %d copy/copies)"
                % (target or "OS default", kind, copies))
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
# Print queue: DB-driven FIFO worker with global pause
# v1.7.0: event-driven wake (no 0.35 s polling), auto-retry with
# backoff, failed jobs STAY in the queue list (Retry / Clear), and
# final failures can be forwarded to peer hubs on the LAN (failover).
# ------------------------------------------------------------
RESUME_EVENT = threading.Event()   # set = queue running, clear = paused
RESUME_EVENT.set()
JOB_WAKE = threading.Event()       # set = "wake up, there is queue work"

def wake_worker():
    JOB_WAKE.set()

def forward_job_to_peers(job):
    """Shared-queue failover: after the FINAL local failure, offer the PDF
    to peer hubs configured in Settings > peers. The first peer that
    accepts prints it (its history shows the job with source 'peer').
    Jobs that arrived FROM a peer are never re-forwarded (no loops)."""
    if not SETTINGS.get("forward_on_fail"):
        return None
    if (job.get("source") or "") == "peer":
        return None
    if not (job.get("file_path") and os.path.exists(job["file_path"])):
        return None
    peers = [normalize_peer(p) for p in (SETTINGS.get("peers") or [])]
    peers = [p for p in peers if p and p["url"]]
    if not peers:
        return None
    try:
        with open(job["file_path"], "rb") as f:
            data = f.read()
    except OSError:
        return None
    q = "title=%s&printer=%s&copies=%d&source=peer" % (
        quote(job.get("title") or "document"),
        quote(job.get("printer") or ""),
        int(job.get("copies") or 1))
    for p in peers:
        try:
            req = urllib.request.Request(
                p["url"] + "/print?" + q, data=data, method="POST",
                headers={"Content-Type": "application/pdf",
                         "X-PrintHub-Token": p["token"] or CFG["token"],
                         "X-PrintHub-Forwarded-By": share_address(),
                         "User-Agent": "PrintHubPro/%s" % VERSION})
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads((r.read() or b"{}").decode("utf-8", "replace"))
            if resp.get("ok"):
                log("[FORWARD] job #%d -> %s (peer job #%s)"
                    % (job["id"], p["url"], resp.get("job_id")))
                return p["url"]
        except Exception as e:
            log("[FORWARD] peer %s refused job #%d: %s" % (p["url"], job["id"], e))
    return None

def worker():
    # recover jobs stuck in 'printing' from a previous crash/restart
    for j in db_list(limit=200, status="printing"):
        log("[RECOVER] job #%d was interrupted -> requeued" % j["id"])
        db_update(j["id"], status="queued",
                  error="requeued after hub restart")
    while True:
        RESUME_EVENT.wait()                     # pause support
        job = db_next_queued()
        if not job:
            # sleep until a new job arrives or the earliest retry is due
            nxt = db_next_retry_time()
            delay = 2.0
            if nxt is not None:
                delay = max(0.2, min(2.0, nxt - time.time()))
            JOB_WAKE.wait(timeout=delay)
            JOB_WAKE.clear()
            continue
        JOB_WAKE.clear()
        t0 = time.time()
        db_update(job["id"], status="printing", error=None)
        try:
            target = print_file(job["file_path"], job["kind"],
                                job["printer"], job["copies"],
                                job_id=job["id"], fit=job.get("fit") or "")
            ms = int((time.time() - t0) * 1000)
            db_update(job["id"], status="printed", error=None,
                      duration_ms=ms, printer=target, next_retry_at=None)
            log("[OK] job #%d printed on %s in %d ms"
                % (job["id"], target, ms))
        except Exception as e:
            latest = db_get(job["id"]) or {}
            if latest.get("status") == "canceled":
                log("[CANCELED] job #%d killed mid-print" % job["id"])
            else:
                attempts = (latest.get("attempts") or 0) + 1
                rmax = max(1, int(SETTINGS.get("retry_max", 3) or 3))
                if SETTINGS.get("auto_retry", True) and attempts < rmax:
                    delay = max(5, int(SETTINGS.get("retry_interval", 60)
                                       or 60)) * attempts
                    db_update(job["id"], status="queued", attempts=attempts,
                              error="attempt %d/%d failed: %s"
                                    % (attempts, rmax, str(e)[:300]),
                              next_retry_at=time.time() + delay)
                    log("[RETRY] job #%d failed (attempt %d/%d) - retry in %ds"
                        % (job["id"], attempts, rmax, delay))
                else:
                    peer = None
                    try:
                        peer = forward_job_to_peers(job)
                    except Exception as fe:
                        log("[FORWARD] error while handing off: %s" % fe)
                    if peer:
                        db_update(job["id"], status="forwarded",
                                  attempts=attempts, next_retry_at=None,
                                  forwarded_to=peer,
                                  error="printed by peer hub %s after local"
                                        " failure: %s" % (peer, str(e)[:200]))
                        log("[FAIL->PEER] job #%d handed to %s"
                            % (job["id"], peer))
                    else:
                        db_update(job["id"], status="failed",
                                  attempts=attempts, next_retry_at=None,
                                  error="%s (kept in queue - Retry or Clear"
                                        " it)" % str(e)[:400])
                        log("[FAIL] job #%d: %s" % (job["id"], e))
        finally:
            # keep the file for reprint (unless keep_files is off)
            if not CFG["keep_files"] and job.get("file_path") \
                    and os.path.exists(job["file_path"]):
                try:
                    os.unlink(job["file_path"])
                except OSError:
                    pass

def start_worker():
    threading.Thread(target=worker, daemon=True, name="printhub-worker").start()

def housekeeping():
    """v1.7.0: free disk - delete stored job PDFs older than
    retention_days. DB rows (the history) are kept forever, only the
    files are cleaned; reprinting an old job then reports 410."""
    while True:
        time.sleep(3600)
        try:
            days = max(1, int(SETTINGS.get("retention_days", 7) or 7))
            cutoff = time.time() - days * 86400
            jdir = os.path.join(CFG["data_dir"], "jobs")
            if not os.path.isdir(jdir):
                continue
            n = 0
            for fn in os.listdir(jdir):
                p = os.path.join(jdir, fn)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.unlink(p)
                        n += 1
                except OSError:
                    pass
            if n:
                log("[CLEANUP] removed %d job file(s) older than %d day(s)"
                    % (n, days))
        except Exception as e:
            log("[CLEANUP] error: %s" % e)

def start_housekeeping():
    threading.Thread(target=housekeeping, daemon=True,
                     name="printhub-housekeeping").start()

def save_job_file(kind, title, data):
    """Write payload bytes into the jobs dir; returns full path."""
    ensure_dirs()
    safe = "".join(c for c in (title or "job") if c.isalnum() or c in "-_ ")[:40] or "job"
    fname = "%s-%s-%s.pdf" % (safe.replace(" ", "_"),
                              datetime.now().strftime("%Y%m%d%H%M%S"),
                              os.getpid())
    path = os.path.join(CFG["data_dir"], "jobs", fname)
    with open(path, "wb") as f:
        f.write(data)
    return path

def enqueue_print(kind, title, data, printer="", copies=1,
                  source="api", origin_ip="-", fit=""):
    """Save file + insert DB row (worker picks it up). Returns job id."""
    path = save_job_file(kind, title, data)
    job_id = db_add(kind, title, printer, copies, path, source, origin_ip,
                    fit=fit)
    log("[QUEUE] job #%d queued (%s, %s) from %s"
        % (job_id, kind, title or "untitled", source))
    wake_worker()
    return job_id

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
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers",
     "Content-Type, X-PrintHub-Token, Access-Control-Request-Private-Network"),
    ("Access-Control-Allow-Private-Network", "true"),   # Chrome/Firefox LAN preflight
    ("Access-Control-Max-Age", "86400"),
]

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
    """Fetch a PDF from a URL (used by 'pdf_url' mode)."""
    req = urllib.request.Request(url, headers={"User-Agent": "PrintHubPro/%s" % VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_PDF + 1)
    if not data or len(data) > MAX_PDF:
        raise ValueError("pdf_url download too large or empty")
    if not data[:5].startswith(b"%PDF"):
        raise ValueError("pdf_url did not return a PDF")
    return data

class Handler(BaseHTTPRequestHandler):
    server_version = "PrintHubPro/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- plumbing ----
    def _cors(self):
        for k, v in CORS_HEADERS:
            self.send_header(k, v)

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

    def _send_file(self, path, download_name):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, {"ok": False, "error": "file no longer stored"})
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % download_name)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):     # quieter default logging
        if os.environ.get("PRINTHUB_VERBOSE"):
            log("[HTTP] %s %s" % (self.address_string(), fmt % args))

    # ---- auth ----
    def _is_local(self):
        try:
            return self.client_address[0] in ("127.0.0.1", "::1", "localhost")
        except Exception:
            return False

    def _token_ok(self, qtoken=None, body=None):
        given = (self.headers.get("X-PrintHub-Token")
                 or qtoken
                 or (body or {}).get("token")
                 or "")
        return hmac.compare_digest(str(given), str(CFG["token"]))

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

        if route == "/health":                        # open: browser pre-check
            dp = default_printer()
            return self._send(200, {
                "ok": True, "app": APP_NAME, "version": VERSION,
                "brand": BRAND_LINE, "vendor_url": BRAND_URL,
                "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
                "default_printer": dp,
                "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
                "browser_found": find_browser() is not None,
                "paused": not RESUME_EVENT.is_set(),
                "pending": db_count_pending(),
                "failed": db_count_failed(),
                "jobs_today": db_count_today(),
                "file_dir": default_file_dir(),
                "token_set": bool(CFG["token"]),
                "autostart": autostart_enabled(),
                "sharing": sharing_enabled(),
                "address": share_address(),
                "lan_ip": get_lan_ip(),
            })

        if not self._token_ok(qt):
            return self._send(401, {"ok": False,
                                    "error": "invalid or missing token"})

        if route == "/":
            return self._send(200, {
                "app": APP_NAME, "version": VERSION, "by": VENDOR,
                "brand": BRAND_LINE,
                "endpoints": ["/health", "/printers", "/jobs", "/jobs/{id}/file",
                              "/jobs/{id}/reprint (POST)", "/jobs/{id}/cancel (POST)",
                              "/jobs/{id}/retry (POST)", "/jobs/clear (POST)",
                              "/print (POST)", "/queue (GET)",
                              "/queue/pause|resume|clear (POST)",
                              "/share (GET/POST)", "/config (POST = /share)",
                              "/autostart (GET) + /autostart (POST)",
                              "/testprint?kind=a4|thermal"],
            })
        if route == "/printers":
            dp = default_printer()
            return self._send(200, {
                "ok": True,
                "printers": [{"name": n, "is_default": n == dp}
                             for n in list_printers()],
                "default": dp})
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
                "failed": db_count_failed(),
                "current": cur})
        if route == "/jobs":
            raw = (q.get("limit") or [str(HISTORY_DEFAULT)])[0]
            if str(raw).lower() in ("all", "0"):
                limit = 1000000
            else:
                try:
                    limit = max(1, min(1000000, int(raw)))
                except ValueError:
                    limit = HISTORY_DEFAULT
            return self._send(200, {"ok": True, "jobs": db_list(limit)})
        if route == "/share":
            local = self._is_local()
            return self._send(200, {
                "ok": True,
                "sharing": sharing_enabled(),
                "host": CFG["host"], "port": CFG["port"],
                "lan_ip": get_lan_ip(),
                "address": share_address(),
                "token": CFG["token"] if local else "****",
                "connect_code": connect_code() if local else "",
                "peers": SETTINGS.get("peers") or [],
                "auto_retry": bool(SETTINGS.get("auto_retry")),
                "retry_max": SETTINGS.get("retry_max"),
                "retry_interval": SETTINGS.get("retry_interval"),
                "forward_on_fail": bool(SETTINGS.get("forward_on_fail")),
                "retention_days": SETTINGS.get("retention_days"),
                "config_file": config_path(),
                "brand": BRAND_LINE,
                "hint": "POST {\"enabled\": true} to share on the LAN;"
                        " other PCs connect with the connect code"
                        " (Options > Sharing)",
            })
        if route == "/testprint":
            kind = (q.get("kind") or ["a4"])[0]
            if kind not in ("a4", "thermal"):
                kind = "a4"
            if kind == "thermal":
                data, _ = thermal_pdf_bytes(
                    "#big PrintHub Pro\n|center|Bit Dream IT - TEST RECEIPT\n"
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
            job = enqueue_print(kind, title, data, origin_ip=self.client_address[0])
            return self._send(200, {"ok": True, "job_id": job, "kind": kind,
                                    "message": "queued - check your printer"})
        if route.startswith("/jobs/"):
            parts = route.strip("/").split("/")
            if len(parts) == 3 and parts[2] == "file":
                j = db_get(int(parts[1]) if parts[1].isdigit() else 0)
                if j and j.get("file_path") and os.path.exists(j["file_path"]):
                    return self._send_file(j["file_path"],
                                           "printhub-job-%d.pdf" % j["id"])
                return self._send(404, {"ok": False,
                                        "error": "job or file not found"})
        return self._send(404, {"ok": False, "error": "unknown endpoint"})

    def do_POST(self):
        u = urlparse(self.path)
        route = u.path.rstrip("/")
        q = parse_qs(u.query)
        ctype = (self.headers.get("Content-Type") or "").lower()
        raw_pdf = None
        try:
            if route == "/print" and ("application/pdf" in ctype or
                                      "application/octet-stream" in ctype):
                # RAW BINARY PDF upload - zero base64 cost.
                # POST the PDF bytes directly; parameters ride the query
                # string: /print?title=...&printer=...&copies=2&token=...
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

        if not self._token_ok((q.get("token") or [""])[0], body):
            return self._send(401, {"ok": False,
                                    "error": "invalid or missing token"})

        # POST /jobs/{id}/reprint
        if route.startswith("/jobs/") and route.endswith("/reprint"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer stored"})
            with open(j["file_path"], "rb") as f:
                data = f.read()
            # a 'saved' (file-destination) job has no printer yet ->
            # reprinting it sends it to the OS default printer
            rpt_printer = "" if j["status"] == "saved" else (j["printer"] or "")
            if rpt_printer == "File (PDF)":
                rpt_printer = ""
            job_id = enqueue_print(j["kind"], (j["title"] or "reprint") + "-reprint",
                                   data, rpt_printer, j["copies"] or 1,
                                   "api", self.client_address[0])
            return self._send(200, {"ok": True, "job_id": job_id,
                                    "reprint_of": j["id"]})

        # POST /jobs/{id}/cancel  (queued -> canceled; printing -> killed)
        if route.startswith("/jobs/") and route.endswith("/cancel"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] in ("printed", "failed", "canceled", "saved"):
                return self._send(409, {"ok": False,
                                        "error": "job already finished (%s)" % j["status"]})
            db_update(j["id"], status="canceled", error="canceled by user")
            killed = cancel_current_print()
            if killed == j["id"]:
                log("[CANCELED] job #%d killed while printing" % j["id"])
            return self._send(200, {"ok": True, "canceled": j["id"],
                                    "was_printing": killed == j["id"]})

        # POST /jobs/{id}/retry  (failed | forwarded | canceled -> queued)
        if route.startswith("/jobs/") and route.endswith("/retry"):
            jid = route.strip("/").split("/")[1]
            j = db_get(int(jid) if jid.isdigit() else 0)
            if not j:
                return self._send(404, {"ok": False, "error": "job not found"})
            if j["status"] not in ("failed", "forwarded", "canceled"):
                return self._send(409, {"ok": False,
                    "error": "only failed/forwarded/canceled jobs can be"
                             " retried (this one is %s)" % j["status"]})
            if not (j.get("file_path") and os.path.exists(j["file_path"])):
                return self._send(410, {"ok": False,
                                        "error": "original file no longer stored"})
            db_update(j["id"], status="queued", attempts=0,
                      next_retry_at=None, error=None, forwarded_to=None)
            wake_worker()
            log("[RETRY] job #%d requeued by request" % j["id"])
            return self._send(200, {"ok": True, "job_id": j["id"],
                                    "status": "queued",
                                    "message": "job requeued - the worker picks it up now"})

        # POST /jobs/clear  {"scope": "failed"|"completed"|"all"}
        if route == "/jobs/clear":
            scope = str(body.get("scope")
                        or (q.get("scope") or ["failed"])[0] or "failed").lower()
            if scope == "all":
                cancel_current_print()
            n, files = db_clear_jobs(scope)
            log("[JOBS] cleared scope=%s: %d row(s), %d file(s)"
                % (scope, n, files))
            return self._send(200, {"ok": True, "scope": scope,
                                    "deleted": n, "files": files})

        # POST /queue/pause | /queue/resume | /queue/clear
        if route in ("/queue/pause", "/queue/resume", "/queue/clear"):
            if route == "/queue/pause":
                RESUME_EVENT.clear()
                log("[QUEUE] paused by request")
            elif route == "/queue/resume":
                RESUME_EVENT.set()
                log("[QUEUE] resumed by request")
            else:
                n = 0
                for j in db_list(limit=500, status="queued"):
                    db_update(j["id"], status="canceled",
                              error="queue cleared by user")
                    n += 1
                log("[QUEUE] cleared %d pending job(s)" % n)
                return self._send(200, {"ok": True, "canceled": n})
            return self._send(200, {"ok": True,
                                    "paused": not RESUME_EVENT.is_set()})

        # POST /share (alias /config) - v1.7.0 easy network sharing:
        #   {"enabled": true}         -> listen on 0.0.0.0 (token ensured)
        #   {"enabled": false}        -> back to localhost only
        #   {"host": "192.168.1.10"}  -> bind a specific LAN IP
        #   {"port": 9235}            -> change port
        #   {"token": "..."} / {"regenerate_token": true}
        #   {"peers": ["http://192.168.1.20:9235|TOKEN2"]}  -> failover targets
        #   {"auto_retry": true, "retry_max": 3, "retry_interval": 60,
        #    "forward_on_fail": true, "retention_days": 7}
        # Changing host/port re-binds the HTTP server live (no restart).
        if route in ("/share", "/config"):
            rebind = False
            if "enabled" in body:
                if body["enabled"]:
                    CFG["host"] = "0.0.0.0"
                    if not CFG["token"]:
                        CFG["token"] = generate_token()
                else:
                    CFG["host"] = "127.0.0.1"
                rebind = True
            if isinstance(body.get("host"), str) and body["host"].strip():
                CFG["host"] = body["host"].strip()
                if not is_loopback_host(CFG["host"]) and not CFG["token"]:
                    CFG["token"] = generate_token()
                rebind = True
            if isinstance(body.get("port"), int) and 0 < body["port"] < 65536 \
                    and body["port"] != CFG["port"]:
                CFG["port"] = body["port"]
                rebind = True
            if body.get("regenerate_token"):
                CFG["token"] = generate_token()
            if isinstance(body.get("token"), str) and body["token"].strip():
                CFG["token"] = body["token"].strip()
            for k in ("auto_retry", "forward_on_fail"):
                if k in body:
                    SETTINGS[k] = bool(body[k])
            if "retry_max" in body:
                try:
                    SETTINGS["retry_max"] = max(1, min(20, int(body["retry_max"])))
                except (TypeError, ValueError):
                    pass
            if "retry_interval" in body:
                try:
                    SETTINGS["retry_interval"] = max(5, min(3600, int(body["retry_interval"])))
                except (TypeError, ValueError):
                    pass
            if "retention_days" in body:
                try:
                    SETTINGS["retention_days"] = max(1, min(365, int(body["retention_days"])))
                except (TypeError, ValueError):
                    pass
            if "peers" in body and isinstance(body["peers"], list):
                peers = [normalize_peer(p) for p in body["peers"]]
                SETTINGS["peers"] = [p for p in peers if p and p["url"]]
            save_settings()
            wake_worker()
            if rebind:
                _rebind_server()
                time.sleep(0.3)      # give the new listener a moment
            sharing = sharing_enabled()
            log("[SHARE] %s on %s:%d (peers: %d)"
                % ("ON" if sharing else "OFF", CFG["host"], CFG["port"],
                   len(SETTINGS.get("peers") or [])))
            return self._send(200, {
                "ok": True,
                "sharing": sharing,
                "host": CFG["host"], "port": CFG["port"],
                "address": share_address(),
                "lan_ip": get_lan_ip(),
                "token": CFG["token"] if self._is_local() else "****",
                "connect_code": connect_code() if self._is_local() else "",
                "peers": SETTINGS.get("peers") or [],
                "auto_retry": bool(SETTINGS.get("auto_retry")),
                "retry_max": SETTINGS.get("retry_max"),
                "retry_interval": SETTINGS.get("retry_interval"),
                "forward_on_fail": bool(SETTINGS.get("forward_on_fail")),
                "message": ("sharing ON - other PCs connect to %s with the"
                            " connect code" % share_address()) if sharing
                           else "sharing OFF - this hub answers on localhost only",
            })

        # POST /autostart  {"enabled": true|false}
        if route == "/autostart":
            enable = body.get("enabled")
            if enable is None:
                enable = (q.get("enabled") or [""])[0].lower() in ("1", "true", "on", "yes")
            state = autostart_set(bool(enable))
            return self._send(200, {"ok": True, "enabled": state,
                                    "path": autostart_path()})

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
            # v1.7.0 fit: "" (auto by kind) | fit | noscale | shrink
            fit = str(bget("fit") or "").strip().lower()
            if fit not in ("fit", "noscale", "shrink"):
                fit = ""
            # destination: "printer" (default) | "file" (save as PDF, no paper)
            # printer value "__file__" is the extension's alias for destination file
            destination = (bget("destination") or
                           ("file" if printer == "__file__" else "printer")).lower()
            if destination not in ("printer", "file"):
                destination = "printer"
            if destination == "file":
                printer = ""
            data = None

            if raw_pdf is not None:
                if len(raw_pdf) > MAX_PDF:
                    return self._send(400, {"ok": False,
                                            "error": "PDF larger than %d MB" % (MAX_PDF // (1024 * 1024))})
                if not raw_pdf[:5].startswith(b"%PDF"):
                    return self._send(400, {"ok": False,
                                            "error": "raw body is not a PDF (must start with %PDF-)"})
                data = raw_pdf
                kind = kind or "a4"
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
                                                 " image_base64, html, page_url or text"})

            if kind not in ("a4", "thermal", "image", "image-thermal", "page"):
                kind = "a4"

            if destination == "file":
                job, fpath = save_file_job(kind, title, data, source,
                                           self.client_address[0])
                return self._send(200, {
                    "ok": True, "job_id": job, "kind": kind,
                    "destination": "file", "status": "saved",
                    "file": fpath, "url_path": "/jobs/%d/file" % job,
                    "message": "saved as PDF file - no paper used",
                })

            job = enqueue_print(kind, title, data, printer, copies,
                                source, self.client_address[0], fit=fit)
            return self._send(200, {
                "ok": True, "job_id": job, "kind": kind, "copies": copies,
                "destination": "printer",
                "message": "queued to printer",
            })

        return self._send(404, {"ok": False, "error": "unknown endpoint"})

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
""" % (VERSION, VENDOR)

def cmd_serve():
    load_settings()
    if sharing_enabled() and not CFG["token"]:
        CFG["token"] = generate_token()
        save_settings()
    db_init()
    start_worker()
    start_housekeeping()
    print(BANNER)
    t = threading.Thread(target=_server_loop, daemon=True,
                         name="printhub-http")
    t.start()
    _start_tray()
    try:
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("stopped by user (Ctrl+C)")

# v1.7.0: the listener runs in its own loop thread so POST /share and the
# tray menu can re-bind to a new host/port LIVE (stop old server -> new
# ThreadingHTTPServer) without killing the process or losing the queue.
STOP_EVENT = threading.Event()
REBIND_EVENT = threading.Event()
_HTTPD = None

def _rebind_server():
    """Ask the server loop to close the current listener and open a new
    one with the current CFG host/port."""
    REBIND_EVENT.set()
    srv = _HTTPD
    if srv:
        try:
            threading.Thread(target=srv.shutdown, daemon=True).start()
        except Exception:
            pass

def _server_loop():
    global _HTTPD
    while not STOP_EVENT.is_set():
        try:
            srv = ThreadingHTTPServer((CFG["host"], CFG["port"]), Handler)
        except OSError as e:
            log("FATAL: cannot bind %s:%d (%s)"
                % (CFG["host"], CFG["port"], e))
            if sharing_enabled():
                log("Sharing is ON (%s). The port may be in use, or another"
                    " PrintHub instance is running - check the tray icon."
                    " Fix config.json or the extension Options > Sharing."
                    % CFG["host"])
            else:
                log("PrintHub Pro is probably ALREADY running (check the"
                    " tray icon near the clock, or Task Manager ->"
                    " 'PrintHubPro'). Exiting.")
            time.sleep(1.2)
            return
        srv.daemon_threads = True
        _HTTPD = srv
        REBIND_EVENT.clear()
        log("PrintHub Pro v%s listening on http://%s:%d  (%s)"
            % (VERSION, CFG["host"], CFG["port"],
               "SHARED on the LAN - token required"
               if sharing_enabled() else "localhost only"))
        if sharing_enabled():
            log("[SHARE] other PCs connect with:  %s" % connect_code())
        try:
            srv.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                srv.server_close()
            except Exception:
                pass
        _HTTPD = None
        if REBIND_EVENT.is_set() and not STOP_EVENT.is_set():
            log("[SHARE] re-binding to %s:%d ..." % (CFG["host"], CFG["port"]))
            time.sleep(0.2)
            continue
        break


def _start_tray():
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
        job = enqueue_print("a4", "tray-test", data, origin_ip="tray")
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
        STOP_EVENT.set()
        threading.Timer(0.5, os._exit, args=(0,)).start()
        _rebind_server()          # breaks the serve_forever loop

    def _share_toggle():
        if sharing_enabled():
            CFG["host"] = "127.0.0.1"
            save_settings()
            _rebind_server()
            log("[SHARE] disabled via tray menu - localhost only")
            return False
        CFG["host"] = "0.0.0.0"
        if not CFG["token"]:
            CFG["token"] = generate_token()
        save_settings()
        _rebind_server()
        log("[SHARE] enabled via tray menu - %s (token: %s)"
            % (share_address(), CFG["token"]))
        return True

    def _copy_share():
        code = connect_code()
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Set-Clipboard -Value '%s'" % code.replace("'", "''")],
                creationflags=HIDE, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("[SHARE] connect code copied to clipboard: %s" % code)
        except Exception as e:
            log("[SHARE] clipboard failed (%s) - connect code: %s" % (e, code))

    tray_windows.start(
        icon=hub_icon_path(),
        tooltip="PrintHub Pro v%s - running on http://%s:%d"
                % (VERSION, CFG["host"] if not sharing_enabled()
                   else get_lan_ip(), CFG["port"]),
        callbacks={
            "on_open": _open_status,
            "on_test": _test,
            "is_paused": lambda: not RESUME_EVENT.is_set(),
            "on_pause_toggle": _pause_toggle,
            "is_autostart": autostart_enabled,
            "on_autostart_toggle": _auto_toggle,
            "is_shared": sharing_enabled,
            "on_share_toggle": _share_toggle,
            "on_copy_share": _copy_share,
            "on_exit": _exit,
        },
        logf=log)

def cmd_testprint(kind):
    db_init(); start_worker()
    kind = kind if kind in ("a4", "thermal") else "a4"
    if kind == "thermal":
        data, _ = thermal_pdf_bytes(
            "#big PrintHub Pro\n|center|Bit Dream IT - TEST RECEIPT\n"
            "--------------------------------\n"
            "Item 1              10.00\nItem 2              25.50\n"
            "--------------------------------\nTOTAL               35.50\n"
            "\n|center|Thank you!\n", "testprint")
    else:
        data, _ = thermal_pdf_bytes(
            "#big PrintHub Pro TEST PAGE\n\nIf this page printed, the hub works.\n"
            "Time: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "testprint", paper="a4")
    job = enqueue_print(kind, "cli-" + kind, data, origin_ip="cli")
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

def cmd_reprint(job_id):
    db_init(); start_worker()
    j = db_get(int(job_id))
    if not j:
        print("Job #%s not found." % job_id); sys.exit(1)
    if not (j.get("file_path") and os.path.exists(j["file_path"])):
        print("Original file of job #%s is gone - cannot reprint." % job_id); sys.exit(1)
    with open(j["file_path"], "rb") as f:
        data = f.read()
    nid = enqueue_print(j["kind"], (j["title"] or "reprint") + "-reprint",
                        data, j["printer"] or "", j["copies"] or 1, "cli", "cli")
    print("Reprinted as job #%d (copy of #%d)." % (nid, j["id"]))

def cmd_queue():
    db_init()
    paused = not RESUME_EVENT.is_set()
    cur = None
    with _CURRENT_LOCK:
        if _CURRENT["id"]:
            cur = db_get(_CURRENT["id"])
    print("Queue: %s | pending: %d | failed: %d"
          % ("PAUSED" if paused else "running", db_count_pending(),
             db_count_failed()))
    if cur:
        print("Current: job #%d %s -> %s" % (cur["id"], cur["title"],
                                             cur["printer"] or "default"))

def cmd_share(arg=""):
    """CLI for easy network sharing:  python printhub.py share [on|off|status]"""
    load_settings()
    a = (arg or "status").lower()
    if a in ("on", "share", "enable", "true", "1"):
        CFG["host"] = "0.0.0.0"
        if not CFG["token"]:
            CFG["token"] = generate_token()
        save_settings()
        print("Sharing ON  - the hub will listen on 0.0.0.0:%d (all network" % CFG["port"])
        print("  adapters, reachable as %s)" % share_address())
        print()
        print("  CONNECT CODE for the extension on other PCs:")
        print("    %s" % connect_code())
        print()
        print("  On each other PC: open the extension Options > Sharing >")
        print("  paste the code > Use. The token protects the hub - share it")
        print("  only with people who may print. Restart the hub to apply.")
    elif a in ("off", "local", "disable", "false", "0"):
        CFG["host"] = "127.0.0.1"
        save_settings()
        print("Sharing OFF - localhost only (http://127.0.0.1:%d)."
              " Restart the hub to apply." % CFG["port"])
    else:
        print("Sharing: %s" % ("ON  - %s" % share_address()
                                if sharing_enabled() else "OFF (localhost only)"))
        print("  connect code: %s" % connect_code())
        print("  peers (failover): %s" % (", ".join(
            p["url"] for p in SETTINGS.get("peers") or []) or "none"))
        print("usage: python printhub.py share [on|off]")

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
  printers                  List installed printers
  history [n]               Show last n print jobs (default 100)
  reprint <job_id>          Print a previous job again
  queue                     Show queue status (paused / pending / failed)
  share [on|off]            Share the hub on the LAN / go localhost-only
  doctor                    Check everything and report [OK]/[!!]
  help                      This help

Settings live in %s (host, port, token, retry, peers).
The extension Options > Sharing page edits the same file via /share.

Environment overrides (win over config.json):
  PRINTHUB_TOKEN    API token   (default PrintHub-2024)
  PRINTHUB_PORT     HTTP port   (default 9235)
  PRINTHUB_HOST     Bind addr   (default 127.0.0.1 = this PC only;
                                0.0.0.0 = share with the whole LAN)
  PRINTHUB_PRINTER  Force printer name (default: OS default)
  PRINTHUB_FILE_DIR Where "destination:file" PDFs are saved
                    (default ~/Downloads/PrintHub)
  PRINTHUB_DATA     Data folder (default ~/.printhub)

Network sharing (v1.7.0): share ON makes this PC the print server for
the office - every other PC just installs the extension and pastes the
connect code. Failed jobs auto-retry, stay in the queue list, and can
fail over to peer hubs. Token always required.
""" % (CFG["port"], config_path()))

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    try:
        if cmd in ("serve", "start"):
            cmd_serve()
        elif cmd == "testprint":
            cmd_testprint(args[1] if len(args) > 1 else "a4")
        elif cmd == "printers":
            ps = list_printers()
            print("\n".join(ps) or "No printers found.")
        elif cmd == "history":
            cmd_history(int(args[1]) if len(args) > 1 else HISTORY_DEFAULT)
        elif cmd == "reprint":
            if len(args) < 2:
                print("usage: python printhub.py reprint <job_id>"); sys.exit(1)
            cmd_reprint(args[1])
        elif cmd == "queue":
            cmd_queue()
        elif cmd == "share":
            cmd_share(args[1] if len(args) > 1 else "status")
        elif cmd == "doctor":
            cmd_doctor()
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

