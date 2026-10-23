#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
#  PrintHub Pro v1.6.0  -  Print from any web page to any printer
#  AdvMedi by Bit Dream IT  -  https://www.bitdreamit.com
#  Innovative Healthcare Solutions - MIT licensed, 100% local
# ------------------------------------------------------------
#  Chrome extension <-> this hub (localhost) -> ANY printer
#  NO print dialog. NO subscription. NO cloud. NO data collection.
#
#  * ZERO pip dependencies - pure Python 3.8+ standard library
#  * Cross-platform: Windows (SumatraPDF) / Linux & macOS (CUPS lp)
#  * Any printer: thermal, receipt, label, A4 - hub sees it, you print
#  * Print queue with pause / resume / cancel (survives restarts)
#  * Job history: last 100+ jobs in SQLite, reprint anytime
#  * Screenshot printing (JPEG -> PDF, pure Python)
#  * HTML / web page printing via headless Chrome or Edge
#  * Token auth, CORS + Private-Network headers, localhost by default
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
import shutil
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
from urllib.parse import urlparse, parse_qs, parse_qsl

VERSION = "1.6.0"
APP_NAME = "PrintHub Pro"
VENDOR = "Bit Dream IT"
BRAND = "AdvMedi by Bit Dream IT - Innovative Healthcare Solutions"
BRAND_URL = "https://www.bitdreamit.com"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HIDE = 0x08000000 if IS_WIN else 0          # no console window flash on Windows
MAX_BODY = 40 * 1024 * 1024                 # 40 MB hard cap on request body
MAX_PDF = 25 * 1024 * 1024                  # 25 MB cap for downloaded pdf_url
HISTORY_DEFAULT = 100                       # Ultraprint-style: last 100 jobs
# v1.6.0: stored job PDFs older than this are auto-deleted (0 = keep forever).
# Keeps the data folder small on PCs that print thousands of reports.
KEEP_DAYS = float(os.environ.get("PRINTHUB_KEEP_DAYS", "14") or 14)

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
# Print history + queue state (SQLite) - thread-safe via one lock
# ------------------------------------------------------------
_DB_LOCK = threading.Lock()

def db():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    ensure_dirs()
    with _DB_LOCK, db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   kind       TEXT NOT NULL,            -- a4 | thermal | image | page
                   title      TEXT,
                   printer    TEXT,
                   copies     INTEGER DEFAULT 1,
                   status     TEXT NOT NULL,            -- queued|printing|printed|failed|canceled
                   error      TEXT,
                   file_path  TEXT,
                   source     TEXT DEFAULT 'api',      -- extension | website | api | cli
                   origin_ip  TEXT,
                   duration_ms INTEGER DEFAULT 0
               )"""
        )
        # v1.6.0: page-scaling preference ('' | noscale | shrinkfit | fit)
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN fit TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        # v1.6.0 PERF: WAL journal = faster writes, fewer fsync stalls while
        # the HTTP threads and the print worker hit the DB at the same time
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass

def db_add(kind, title, printer, copies, file_path, source, origin_ip,
           status="queued", fit=""):
    with _DB_LOCK, db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (created_at, kind, title, printer, copies, status,"
            " file_path, source, origin_ip, fit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), kind, title, printer,
             copies, status, file_path, source, origin_ip, fit or ""),
        )
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
    """Oldest queued job (FIFO). The worker is DB-driven so the queue
    survives hub restarts and can be paused / cancelled live."""
    with _DB_LOCK, db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
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

# ------------------------------------------------------------
# Printer + browser discovery (best effort, pure stdlib)
# ------------------------------------------------------------
# v1.6.0 PERF: every /health and /printers call used to spawn PowerShell
# (0.3-1.5 s each on Windows). Results are cached for 30 s now - the popup
# and status page feel instant and idle CPU drops to almost zero.
_PRINTER_TTL = 30.0
_PRINTER_CACHE = {"at": 0.0, "list": None}
_DEFAULT_CACHE = {"at": 0.0, "name": None}

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

def list_printers(force=False):
    """Return list of installed printer names (best effort, 30 s cache)."""
    now = time.time()
    if (not force and _PRINTER_CACHE["list"] is not None
            and now - _PRINTER_CACHE["at"] < _PRINTER_TTL):
        return _PRINTER_CACHE["list"]
    try:
        if IS_WIN:
            ps = "Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name"
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            names = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
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
        if names:   # v1.6.0: never cache a transient empty result
            _PRINTER_CACHE["list"] = names
            _PRINTER_CACHE["at"] = now
        return names
    except Exception as e:
        log("[WARN] list_printers failed: %s" % e)
        return []

def default_printer(force=False):
    """Return the OS default printer name (best effort, 30 s cache)."""
    now = time.time()
    if (not force and _DEFAULT_CACHE["name"] is not None
            and now - _DEFAULT_CACHE["at"] < _PRINTER_TTL):
        return _DEFAULT_CACHE["name"]
    try:
        if IS_WIN:
            ps = ("(Get-CimInstance Win32_Printer | Where-Object Default)"
                  ".Name")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=HIDE)
            name = (out.stdout or "").strip()
        else:
            name = None
            out = subprocess.run(["lpstat", "-d"], capture_output=True,
                                 text=True, timeout=10)
            for l in (out.stdout or "").splitlines():
                if "system default destination" in l:
                    name = l.split(":")[-1].strip()
                    break
        _DEFAULT_CACHE["name"] = name or None
        _DEFAULT_CACHE["at"] = now
        return name or None
    except Exception:
        return None

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
               "--virtual-time-budget=8000",
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
    fit: '' (kind default) | 'noscale' | 'shrinkfit' | 'fit' (v1.6.0).
    """
    copies = max(1, min(int(copies or 1), 50))
    target = printer or CFG["printer"] or default_printer() or ""

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
            fitv = (fit or "").lower()
            if fitv in ("noscale", "shrinkfit", "fit"):
                settings = fitv
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
            cmd += ["-o", "fit-to-page" if kind in ("a4", "image") else "noscale", path]
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
# ------------------------------------------------------------
RESUME_EVENT = threading.Event()   # set = queue running, clear = paused
RESUME_EVENT.set()
WAKE_EVENT = threading.Event()     # v1.6.0: instant wake-up when a job arrives

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
            # v1.6.0: sleep until a new job signals WAKE (instant start)
            # or a 1 s heartbeat passes - no more busy 0.35 s polling
            WAKE_EVENT.wait(timeout=1.0)
            WAKE_EVENT.clear()
            continue
        t0 = time.time()
        db_update(job["id"], status="printing", error=None)
        try:
            target = print_file(job["file_path"], job["kind"],
                                job["printer"], job["copies"],
                                job_id=job["id"], fit=job.get("fit") or "")
            ms = int((time.time() - t0) * 1000)
            db_update(job["id"], status="printed", error=None,
                      duration_ms=ms, printer=target)
            log("[OK] job #%d printed on %s in %d ms"
                % (job["id"], target, ms))
        except Exception as e:
            latest = db_get(job["id"]) or {}
            if latest.get("status") == "canceled":
                log("[CANCELED] job #%d killed mid-print" % job["id"])
            else:
                db_update(job["id"], status="failed", error=str(e)[:500])
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
    WAKE_EVENT.set()          # v1.6.0: print starts immediately, no poll delay
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
# Disk hygiene (v1.6.0): auto-delete old stored job files
# ------------------------------------------------------------
def cleanup_old_job_files():
    """Delete stored job PDFs older than KEEP_DAYS days (0 = keep forever).
    History rows stay in SQLite; reprinting a cleaned job answers with the
    usual friendly 'file no longer stored' error."""
    if KEEP_DAYS <= 0:
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    removed = 0
    try:
        with _DB_LOCK, db() as conn:
            rows = conn.execute(
                "SELECT file_path FROM jobs WHERE file_path IS NOT NULL"
            ).fetchall()
    except Exception:
        return
    for r in rows:
        fp = r["file_path"]
        if not fp or not os.path.exists(fp):
            continue
        try:
            if os.path.getmtime(fp) < cutoff:
                os.unlink(fp)
                removed += 1
        except OSError:
            pass
    if removed:
        log("[CLEANUP] removed %d job file(s) older than %g day(s)"
            % (removed, KEEP_DAYS))

def _cleanup_loop():
    while True:
        time.sleep(6 * 3600)
        cleanup_old_job_files()

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
                "os": "windows" if IS_WIN else ("macos" if IS_MAC else "linux"),
                "default_printer": dp,
                "sumatra_found": (find_sumatra() is not None) if IS_WIN else None,
                "browser_found": find_browser() is not None,
                "paused": not RESUME_EVENT.is_set(),
                "pending": db_count_pending(),
                "jobs_today": db_count_today(),
                "file_dir": default_file_dir(),
                "token_set": bool(CFG["token"]),
                "autostart": autostart_enabled(),
                "brand": BRAND,
                "brand_url": BRAND_URL,
            })

        if not self._token_ok(qt):
            return self._send(401, {"ok": False,
                                    "error": "invalid or missing token"})

        if route == "/":
            return self._send(200, {
                "app": APP_NAME, "version": VERSION, "by": VENDOR,
                "brand": BRAND, "brand_url": BRAND_URL,
                "endpoints": ["/health", "/printers", "/jobs", "/jobs/clear (POST)", "/jobs/{id}/file",
                              "/jobs/{id}/reprint (POST)", "/jobs/{id}/cancel (POST)",
                              "/print (POST)", "/queue (GET)",
                              "/queue/pause|resume|clear (POST)",
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
                "current": cur})
        if route == "/jobs":
            limit = (q.get("limit") or [str(HISTORY_DEFAULT)])[0]
            return self._send(200, {"ok": True, "jobs": db_list(limit)})
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

        # POST /jobs/clear  (v1.6.0: wipe the job history - files stay on
        # disk, the popup and Options 'Clear' buttons call this)
        if route == "/jobs/clear":
            with _DB_LOCK, db() as conn:
                n = conn.execute("DELETE FROM jobs").rowcount
            log("[HISTORY] cleared %d job(s) by request" % n)
            return self._send(200, {"ok": True, "cleared": n})

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
                                   "api", self.client_address[0],
                                   fit=j.get("fit") or "")
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

        # POST /queue/pause | /queue/resume | /queue/clear
        if route in ("/queue/pause", "/queue/resume", "/queue/clear"):
            if route == "/queue/pause":
                RESUME_EVENT.clear()
                log("[QUEUE] paused by request")
            elif route == "/queue/resume":
                RESUME_EVENT.set()
                WAKE_EVENT.set()      # v1.6.0: wake the worker right away
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
            # v1.6.0: page scaling - 'noscale' | 'shrinkfit' | 'fit'
            # ('' = per-kind default: thermal noscale, A4 shrinkfit)
            fit = str(bget("fit") or "").lower()
            if fit not in ("", "noscale", "shrinkfit", "fit"):
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
   %s
   %s
""" % (VERSION, VENDOR, BRAND, BRAND_URL)

def cmd_serve():
    db_init()
    start_worker()
    threading.Thread(target=_cleanup_loop, daemon=True,
                     name="printhub-cleanup").start()
    threading.Thread(target=cleanup_old_job_files, daemon=True,
                     name="printhub-cleanup-start").start()
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
    log("PrintHub Pro v%s listening on http://%s:%d" % (VERSION, CFG["host"], CFG["port"]))
    log("Health check -> http://127.0.0.1:%d/health   (token: %s)"
        % (CFG["port"], CFG["token"]))
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
  queue                     Show queue status (paused / pending / current)
  doctor                    Check everything and report [OK]/[!!]
  help                      This help

Options (environment variables):
  PRINTHUB_TOKEN    API token   (default PrintHub-2024)
  PRINTHUB_PORT     HTTP port   (default 9235)
  PRINTHUB_HOST     Bind addr   (default 127.0.0.1 = this PC only)
  PRINTHUB_PRINTER  Force printer name (default: OS default)
  PRINTHUB_FILE_DIR Where "destination:file" PDFs are saved
                    (default ~/Downloads/PrintHub)
  PRINTHUB_DATA     Data folder (default ~/.printhub)
  PRINTHUB_KEEP_DAYS  Auto-delete stored job PDFs older than N days
                    (default 14, set 0 to keep everything forever)

Chrome extension: see extension/ folder - load it unpacked in Chrome,
then click the PrintHub icon and press Connect.
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

