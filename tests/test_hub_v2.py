"""PrintHub Pro v2.0.1 - pytest suite (pure stdlib hub, no real printer).

Covers the 22 feature areas: security (random token, header-only, origins,
SSRF guard, lockout + v2.0.1 loopback exemption, rotate), printer (status,
groups, raw ESC/POS+ZPL, profiles, page ranges), queue (retry, priority,
dedupe, schedule, dead-letter, peers), audit (log, reason, watermark, CSV,
diagnostics, dashboard) plus repo sanity (version anchors, migrations).
"""
import json
import os
import sqlite3
import time
import urllib.request

import pytest

import printhub
from conftest import wait_until  # noqa: E402


# ============================================================
# 1. health / security
# ============================================================

def test_health_open_no_token(hub):
    code, d = hub.get("/health", token=None)
    assert code == 200 and d["ok"] is True
    assert d["version"] == "2.2.0"
    assert d["v2"] is True
    assert "100% local" in d["branding"]


def test_new_install_random_token(hub):
    assert hub.token and hub.token != "PrintHub-2024"
    assert printhub.CFG["token_header_only"] is True     # fresh install = strict


def test_auth_required_without_token(hub):
    code, _ = hub.get("/jobs", token=None)
    assert code == 401


def test_header_token_works_on_every_get_v202(hub):
    # v2.0.2: the /audit vs /dashboard mismatch is gone - the SAME token
    # must open EVERY GET endpoint, with or without a browser header
    for path in ("/jobs", "/audit", "/stats", "/diagnostics",
                 "/printers", "/queue", "/config", "/peers"):
        code, _ = hub.get(path)                           # header call
        assert code == 200, path
        code, _ = hub.get(path + "?token=" + hub.token,
                          token=None)                     # browser link
        assert code == 200, path


def test_post_query_token_still_rejected_v202(hub):
    # v2.0.2 hardening kept: mutating POSTs require the header in
    # header-only mode - a query token alone is not enough
    code, _ = hub.post("/queue/pause?token=" + hub.token,
                       {}, token=None)
    assert code == 401
    code, _ = hub.post("/queue/pause", {})                # header works
    assert code == 200
    hub.post("/queue/resume", {})                         # restore


def test_wrong_token_get_gives_json_for_api_clients(hub):
    code, d = hub.get("/audit", token="nope-" + hub.token)
    assert code == 401 and d["ok"] is False and "error" in d


def test_wrong_token_counts_and_lockout(hub, cfg_reset):
    # v2.0.1: loopback is exempt by default -> disable the exemption to
    # exercise the remote-IP lock path (tests always come from 127.0.0.1)
    printhub.CFG["lockout_exempt_loopback"] = False
    printhub._AUTH_FAILS.clear()
    codes = []
    for i in range(printhub.CFG["max_auth_failures"]):
        code, _ = hub.get("/jobs", token="wrong-%d" % i)
        codes.append(code)
    assert codes[: printhub.CFG["max_auth_failures"] - 1] == [401] * (
        printhub.CFG["max_auth_failures"] - 1)
    code, d = hub.get("/jobs")          # even the CORRECT token is locked now
    assert code == 429
    printhub._AUTH_FAILS.clear()


def test_loopback_never_locked_by_default(hub):
    """v2.0.1 core fix: many Chrome windows share 127.0.0.1 - a stale
    token in one window must never lock the dashboard/tray/extension
    of every other window out."""
    printhub._AUTH_FAILS.clear()
    n = int(printhub.CFG["max_auth_failures"]) + 5
    codes = set()
    for i in range(n):
        code, _ = hub.get("/jobs", token="still-wrong-%d" % i)
        codes.add(code)
    assert 429 not in codes             # no lock, no matter how many fails
    code, d = hub.get("/jobs")          # the correct token keeps working
    assert code == 200 and d["ok"] is True
    assert not printhub._AUTH_FAILS.get("127.0.0.1", {}).get("until")
    printhub._AUTH_FAILS.clear()


def test_success_clears_failure_counter(hub):
    printhub._AUTH_FAILS.clear()
    for i in range(int(printhub.CFG["max_auth_failures"]) - 1):
        hub.get("/jobs", token="bad-%d" % i)
    code, _ = hub.get("/jobs")          # one success -> counter reset
    assert code == 200
    rec = printhub._AUTH_FAILS.get("127.0.0.1")
    assert rec is None                  # success clears the IP entirely
    printhub._AUTH_FAILS.clear()


def test_failures_expire_with_sliding_window(hub):
    printhub._AUTH_FAILS.clear()
    for i in range(int(printhub.CFG["max_auth_failures"]) - 1):
        hub.get("/jobs", token="old-%d" % i)
    rec = printhub._AUTH_FAILS["127.0.0.1"]
    rec["first"] -= int(printhub.CFG["lockout_minutes"]) * 60 + 1  # age out
    code, _ = hub.get("/jobs", token="after-window")
    assert code == 401                  # still rejected, but...
    fresh = printhub._AUTH_FAILS["127.0.0.1"]
    assert fresh["count"] == 1          # ...counted in a NEW window
    printhub._AUTH_FAILS.clear()


def test_old_default_token_gets_clear_hint(hub):
    code, d = hub.get("/jobs", token="PrintHub-2024")
    assert code == 401
    assert "OLD default token" in d["error"]
    assert "printhub.py token" in d["error"]


def test_dashboard_wrong_token_html_error(hub):
    """Browsers opening /dashboard with a stale ?token= now get a
    readable HTML page (fix instructions), not a raw JSON blob."""
    code, body = hub.get("/dashboard?token=PrintHub-2024",
                         token="PrintHub-2024",
                         headers={"Accept": "text/html"})
    assert code == 401
    assert b"<!DOCTYPE html>" in body and b"tray icon" in body.lower()
    # JSON clients still get JSON
    code, d = hub.get("/dashboard?token=PrintHub-2024", token="PrintHub-2024")
    assert code == 401 and d["ok"] is False and "error" in d


def test_origin_allowlist(hub, cfg_reset):
    hub.post("/config", {"allowed_origins": ["*.htncr.org"]})
    code, d = hub.post("/print", {"text": "origin test", "title": "o1",
                                  "kind": "thermal"},
                       headers={"Origin": "https://app.htncr.org",
                                "X-PrintHub-Token": hub.token})
    assert code == 200
    code, _ = hub.post("/print", {"text": "evil", "title": "o2",
                                  "kind": "thermal"},
                       headers={"Origin": "https://evil.example",
                                "X-PrintHub-Token": hub.token})
    assert code == 403
    hub.post("/config", {"allowed_origins": []})   # back to allow-all


def test_pdf_url_scheme_blocked(hub):
    for bad in ("file:///etc/passwd", "ftp://host/x.pdf", "gopher://x/y"):
        code, d = hub.post("/print", {"pdf_url": bad})
        assert code == 400 and "blocked" in d["error"], bad


def test_pdf_url_private_ip_blocked(hub, cfg_reset):
    code, d = hub.post("/print", {"pdf_url": "http://192.168.1.1/a.pdf"})
    assert code == 400 and "private" in d["error"]
    code, d = hub.post("/print", {"pdf_url": "http://127.0.0.1:9235/health"})
    assert code == 400 and "private" in d["error"]
    # allowlist override accepts the host (download then fails for other
    # reasons - NOT the SSRF guard). Use the hub itself as the allowed
    # host so the check never depends on unreachable networks.
    hub.post("/config", {"pdf_url_allowed_hosts": ["127.0.0.1"]})
    code, d = hub.post("/print", {
        "pdf_url": hub.base + "/a-not-a-pdf"})
    assert code == 400 and "private" not in str(d.get("error", ""))
    assert "blocked" not in str(d.get("error", ""))
    hub.post("/config", {"pdf_url_allowed_hosts": []})


def test_token_rotate_api(hub):
    old = hub.token
    code, d = hub.post("/token/rotate")
    assert code == 200 and d["token"]
    new = d["token"]
    code, _ = hub.get("/jobs", token=old)
    assert code == 401                      # old token dead immediately
    code, _ = hub.get("/jobs", token=new)
    assert code == 200
    hub.token = new
    assert printhub.CFG["token_header_only"] is True


def test_config_post_persists(hub):
    code, d = hub.post("/config", {"max_retries": 3})
    assert code == 200 and "max_retries" in d["changed"]
    disk = json.load(open(printhub.config_path()))
    assert disk["max_retries"] == 3
    code, d = hub.post("/config", {"token": "hack"})
    assert code == 400                      # token only via /token/rotate


def test_config_view_masks_token(hub):
    code, d = hub.get("/config")
    assert code == 200 and d["token"].endswith("***")


# ============================================================
# 2. queue: dedupe / priority / schedule / retry / dead-letter
# ============================================================

def test_duplicate_blocking(hub, clean_queue):
    code, d1 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal"})
    assert code == 200 and d1["duplicate"] is False
    code, d2 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal"})
    assert code == 200 and d2["duplicate"] is True
    assert d2["job_id"] == d1["job_id"]
    code, d3 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal", "dedupe": False})
    assert code == 200 and d3["duplicate"] is False


def test_priority_urgent_first(hub, clean_queue):
    printhub.RESUME_EVENT.clear()                       # hold the queue
    code, lo = hub.post("/print", {"text": "low prio", "title": "low",
                                   "priority": 9})
    code, hi = hub.post("/print", {"text": "urgent", "title": "urgent",
                                   "priority": 1})
    assert lo["priority"] == 9 and hi["priority"] == 1
    printhub.RESUME_EVENT.set()
    ok = wait_until(lambda: len(hub.printed) >= 2)
    assert ok
    assert hub.printed[0]["job_id"] == hi["job_id"]     # urgent jumped the line
    assert hub.printed[1]["job_id"] == lo["job_id"]


def test_scheduled_print(hub, clean_queue):
    code, d = hub.post("/print", {"text": "later", "title": "sched",
                                  "run_at": "+1h", "kind": "thermal"})
    assert code == 200 and d["status"] == "scheduled" and d["scheduled_for"]
    j = printhub.db_get(d["job_id"])
    assert j["status"] == "scheduled"
    assert printhub.db_promote_scheduled() == 0         # 1h away: not yet
    printhub.db_update(j["id"], run_at="2020-01-01T00:00:00")
    assert printhub.db_promote_scheduled() == 1
    ok = wait_until(lambda: (printhub.db_get(j["id"]) or {})
                    .get("status") in ("printed", "failed"))
    assert ok


def test_retry_then_dead_letter(hub, clean_queue, cfg_reset):
    printhub.CFG["max_retries"] = 1
    printhub.CFG["retry_base_seconds"] = 0
    # make printing explode
    orig = printhub.print_file
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("printer on fire")
    printhub.print_file = boom
    try:
        printhub.RESUME_EVENT.clear()
        code, d = hub.post("/print", {"text": "will fail", "title": "boom",
                                      "kind": "thermal"})
        printhub.RESUME_EVENT.set()
        ok = wait_until(lambda: (printhub.db_get(d["job_id"]) or {})
                        .get("status") == "dead")
        assert ok, "job should reach dead-letter after retries"
        assert calls["n"] >= 2                          # 1st + 1 retry
        # dead-letter recovery: retry on ANOTHER printer
        code, d2 = hub.post("/jobs/%d/retry" % d["job_id"],
                            {"printer": "BackupLab"})
        assert code == 200
        j = printhub.db_get(d["job_id"])
        assert j["status"] in ("queued", "printing", "printed")
        assert j["printer"] == "BackupLab"
    finally:
        printhub.print_file = orig


def test_hold_when_printer_offline(hub, clean_queue, cfg_reset, monkeypatch):
    printhub.CFG["hold_offline"] = True
    monkeypatch.setattr(printhub, "printer_ready",
                        lambda name="": "offline")
    code, d = hub.post("/print", {"text": "wait for paper", "title": "hold",
                                  "kind": "thermal", "printer": "FrontDesk"})
    jid = d["job_id"]
    ok = wait_until(lambda: (printhub.db_get(jid) or {}).get("status") == "held")
    assert ok
    j = printhub.db_get(jid)
    assert "offline" in (j.get("held_reason") or "")
    # printer back online -> released
    monkeypatch.setattr(printhub, "printer_ready", lambda name="": "ready")
    printhub._UNHOLD_TS[0] = 0.0
    ok = wait_until(lambda: (printhub.db_get(jid) or {}).get("status")
                    in ("printed", "printing"))
    assert ok


# ============================================================
# 3. printer status / groups / raw / profiles
# ============================================================

def test_printer_group_fallback(hub, clean_queue, cfg_reset, monkeypatch):
    printhub.CFG["printer_groups"] = {"Front": ["A", "B"]}
    monkeypatch.setattr(printhub, "printers_status",
                        lambda force=False: {"A": "offline", "B": "ready"})
    assert printhub.pick_group_printer("Front") == "B"
    code, d = hub.post("/print", {"text": "to group", "title": "grp",
                                  "kind": "thermal", "printer": "Front"})
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok and hub.printed[-1]["printer"] == "B"


def test_printers_endpoint_has_status(hub):
    code, d = hub.get("/printers")
    assert code == 200
    for p in d["printers"]:
        assert "status" in p and "is_group" in p


def test_escpos_builder_markers():
    b = printhub.escpos_bytes(
        "HI\n#big HEAD\n|center|C\n|barcode:12345|\n|qr:tbl-9|\n|drawer|\n|cut|")
    assert b[:2] == b"\x1b@"                  # init
    assert b"\x1dV" in b                      # cut
    assert b"\x1bp\x00" in b                  # cash drawer
    assert b"\x1d(k" in b                     # QR
    assert b"\x1dkI" in b                     # CODE128 barcode
    assert b"\x1d!\x11" in b                  # double-size text


def test_raw_escpos_and_zpl_end_to_end(hub, clean_queue):
    code, d = hub.post("/print", {"lang": "escpos", "text": "COFFEE\n|cut|",
                                  "title": "receipt", "printer": "XP-58"})
    assert code == 200 and d["kind"] == "raw"
    ok = wait_until(lambda: len(hub.raw_printed) >= 1)
    assert ok
    data, printer = hub.raw_printed[-1]
    assert printer == "XP-58" and b"\x1dV" in data      # cut command inside
    code, d = hub.post("/print", {"lang": "zpl",
                                  "text": "^XA^FDHELLO^XZ",
                                  "title": "label", "printer": "Zebra"})
    ok = wait_until(lambda: len(hub.raw_printed) >= 2)
    assert ok
    data, printer = hub.raw_printed[-1]
    assert printer == "Zebra" and data == b"^XA^FDHELLO^XZ"


def test_pages_and_profile_reach_print_backend(hub, clean_queue, cfg_reset):
    hub.post("/config", {"profiles": {
        "Invoice": {"paper_size": "A4", "duplex": "long", "copies": 2}}})
    code, d = hub.post("/print", {"text": "x", "title": "withprof",
                                  "kind": "thermal", "profile": "Invoice",
                                  "pages": "1-3,5", "printer": "P1"})
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    rec = hub.printed[-1]
    assert rec["pages"] == "1-3,5"
    assert rec["duplex"] == "long" and rec["paper_size"] == "A4"
    assert rec["copies"] == 2                        # profile default applied


def test_unknown_profile_rejected(hub):
    code, d = hub.post("/print", {"text": "x", "title": "badprof",
                                  "profile": "Nope"})
    assert code == 400 and "unknown profile" in d["error"]


# ============================================================
# 4. audit / watermark / exports / dashboard / diagnostics
# ============================================================

def test_audit_trail(hub, clean_queue):
    code, d = hub.post("/print", {"text": "audit me", "title": "aud",
                                  "kind": "thermal"})
    wait_until(lambda: (printhub.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    code, d = hub.get("/audit?event=print.submitted")
    assert code == 200 and any(e["event"] == "print.submitted"
                               for e in d["entries"])
    code, d = hub.get("/audit.csv")
    assert code == 200 and b"ts,event,job_id" in d


def test_job_records_site_and_hash(hub, clean_queue):
    code, d = hub.post("/print", {"text": "hash me", "title": "hash",
                                  "kind": "thermal"})
    j = printhub.db_get(d["job_id"])
    assert j["content_hash"] and len(j["content_hash"]) == 64


def test_reprint_reason_and_required(hub, clean_queue, cfg_reset):
    code, d = hub.post("/print", {"text": "orig", "title": "rep",
                                  "kind": "thermal"})
    wait_until(lambda: (printhub.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    printhub.CFG["reprint_reason_required"] = True
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"], {})
    assert code == 400 and "reason" in e["error"]
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"],
                       {"reason": "customer lost the copy"})
    assert code == 200
    code, d2 = hub.get("/audit?event=reprint")
    assert any("customer lost" in (x.get("reason") or "")
               for x in d2["entries"])
    printhub.CFG["reprint_reason_required"] = False


def test_reprint_watermark(hub, clean_queue, cfg_reset):
    code, d = hub.post("/print", {"text": "wm source", "title": "wmsrc",
                                  "kind": "thermal"})
    wait_until(lambda: (printhub.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"],
                       {"reason": "again", "watermark": True})
    assert code == 200 and e["watermark"] is True


def test_pdf_watermark_function():
    data, _ = printhub.thermal_pdf_bytes("WATERMARK UNIT TEST", "wm")
    out = printhub.pdf_watermark(data, "REPRINT")
    assert out[:5] == b"%PDF-" and len(out) > len(data)
    assert b"REPRINT" in out and b"PHwm" in out


def test_csv_history_export(hub, clean_queue):
    hub.post("/print", {"text": "csv row", "title": "csv", "kind": "thermal"})
    code, body = hub.get("/export/history.csv")
    assert code == 200
    head = body.split(b"\n")[0]
    for col in (b"priority", b"site", b"content_hash", b"attempts"):
        assert col in head


def test_stats_and_dashboard(hub):
    code, d = hub.get("/stats")
    assert code == 200
    for k in ("success_rate", "queue_size", "jobs_today", "by_status"):
        assert k in d
    code, body = hub.get("/dashboard?token=" + hub.token)
    assert code == 200 and b"success rate" in body


def test_diagnostics_redacts_token(hub):
    code, d = hub.get("/diagnostics")
    assert code == 200 and d["ok"] is True
    assert d["token"].endswith("***")
    assert hub.token not in json.dumps(d)


def test_peers_endpoint(hub, cfg_reset):
    printhub.CFG["peer_hubs"] = [{"url": "http://127.0.0.1:59999", "token": "x"}]
    printhub._PEER_CACHE["t"] = 0.0
    code, d = hub.get("/peers")
    assert code == 200 and d["peers"][0]["alive"] is False
    printhub.CFG["peer_hubs"] = []


# ============================================================
# 5. repo sanity: migration of a v1.x database + version anchors
# ============================================================

def test_v1_database_migration(tmp_path):
    dbf = tmp_path / "history.db"
    conn = sqlite3.connect(str(dbf))
    conn.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL, kind TEXT NOT NULL, title TEXT, printer TEXT,
        copies INTEGER DEFAULT 1, status TEXT NOT NULL, error TEXT,
        file_path TEXT, source TEXT DEFAULT 'api', origin_ip TEXT,
        duration_ms INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO jobs (created_at,kind,title,printer,copies,"
                 "status,file_path,source,origin_ip,duration_ms) VALUES"
                 "('2025-01-01T00:00:00','a4','old job','X',1,'printed',"
                 "'/x.pdf','api','127',100)")
    conn.commit()
    conn.close()
    old_dir = printhub.CFG["data_dir"]
    printhub.CFG["data_dir"] = str(tmp_path)
    try:
        printhub.db_init()
        row = printhub.db_get(1)
        assert row["title"] == "old job"                 # data untouched
        assert all(k in row for k in ("priority", "attempts", "site",
                                      "content_hash", "held_reason"))
    finally:
        printhub.CFG["data_dir"] = old_dir


def test_version_anchors():
    assert printhub.VERSION == "2.2.0"
    ext = os.path.join(os.path.dirname(printhub.__file__), "..",
                       "extension", "manifest.json")
    with open(ext) as f:
        assert json.load(f)["version"] == "2.2.0"


def test_log_rotation(tmp_path):
    old = printhub.CFG["data_dir"]
    printhub.CFG["data_dir"] = str(tmp_path)
    old_max = printhub.CFG["log_max_mb"]
    printhub.CFG["log_max_mb"] = 0        # rotate on every write
    try:
        printhub.log("rotation test entry")
        assert os.path.isfile(os.path.join(str(tmp_path), "hub.log"))
    finally:
        printhub.CFG["data_dir"] = old
        printhub.CFG["log_max_mb"] = old_max


# ============================================================
# v2.2.0: print options, capabilities, LAN share, queue shift
# ============================================================

@pytest.fixture(autouse=True)
def _v21_sync_token(hub):
    """Token rotation tests earlier in this module change CFG["token"] -
    keep the client's token in sync for every test."""
    hub.token = printhub.CFG["token"]
    yield


def test_v21_capabilities_endpoint(hub):
    code, d = hub.get("/printers/FakeLaser/capabilities")
    assert code == 200 and d["ok"] is True
    assert d["backend"] in ("sumatra", "cups")
    assert d["pages"]["odd_even"] is True


def test_v21_per_sheet_quality_reach_backend(hub, clean_queue):
    code, d = hub.post("/print", {"text": "nup", "title": "nup",
                                  "kind": "thermal", "printer": "P1",
                                  "per_sheet": 2, "quality": "draft"})
    assert code == 200
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    rec = hub.printed[-1]
    assert rec["per_sheet"] == 2 and rec["quality"] == "draft"


def test_v21_odd_even_reach_backend(hub, clean_queue):
    code, d = hub.post("/print", {"text": "oe", "title": "oe",
                                  "kind": "thermal", "printer": "P1",
                                  "pages": "odd"})
    assert code == 200
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    assert hub.printed[-1]["pages"] == "odd"


def test_v21_thermal_builder_overrides():
    data, _ = printhub.thermal_pdf_bytes("A\nB", title="t",
                                         margin_mm=10, scale_pct=200,
                                         landscape=True)
    assert data[:5] == b"%PDF-"
    data2, _ = printhub.thermal_pdf_bytes("x")          # old signature works
    assert data2[:5] == b"%PDF-"


def test_v21_helpers():
    assert printhub.text_needs_browser("বাংলা রসিদ") is True
    assert printhub.text_needs_browser("COFFEE 35.50") is False
    h = printhub.inject_page_css("<html><head></head><body>x</body></html>",
                                 margin_mm=8, scale_pct=150, landscape=True)
    assert "margin:8mm" in h and "zoom:150%" in h and "landscape" in h
    assert h.index("<style") < h.index("<body")
    assert printhub.pdf_page_count(b"%PDF-1.4 ... /Type /Page ... "
                                   b"/Type /Page ...") == 2
    assert printhub.pdf_page_count(b"not a pdf") is None


def test_v21_queue_shift_to_fake_peer(hub, clean_queue, cfg_reset):
    """Full-shift pending jobs to a fake peer hub over HTTP."""
    import http.server, threading as th
    got = {}

    class FakePeer(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            ln = int(self.headers.get("Content-Length") or 0)
            got["body"] = json.loads(self.rfile.read(ln) or b"{}")
            got["token"] = self.headers.get("X-PrintHub-Token")
            body = json.dumps({"ok": True, "job_id": 777}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    psrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakePeer)
    pport = psrv.server_address[1]
    th.Thread(target=psrv.serve_forever, daemon=True).start()
    try:
        code, d = hub.post("/print", {"text": "shift me", "title": "sh",
                                      "kind": "thermal", "printer": "P1"})
        jid = d["job_id"]
        printhub._PAUSED.clear() if hasattr(printhub, "_PAUSED") else None
        code, d = hub.post("/queue/shift", {
            "target": "http://127.0.0.1:%d" % pport,
            "target_token": "peersecret", "scope": "all"})
        assert code == 200 and d["ok"] is True, d
        assert d["shifted_count"] == 1 and jid in d["shifted"]
        assert got["token"] == "peersecret"
        assert got["body"]["title"] == "sh"
        assert (printhub.db_get(jid) or {}).get("status") == "forwarded"
        # individual shift: unknown id list shifts nothing
        code, d = hub.post("/queue/shift", {
            "target": "http://127.0.0.1:%d" % pport, "scope": "job",
            "ids": [424242]})
        assert code == 200 and d["shifted_count"] == 0
    finally:
        psrv.shutdown()


def test_v21_share_lan_config_roundtrip(hub, cfg_reset):
    code, d = hub.post("/config", {"share_lan": True})
    assert code == 200 and d["config"]["share_lan"] is True
    code, d = hub.get("/health", token=None)
    assert d["share_lan"] is True and d["lan_url"]
    hub.post("/config", {"share_lan": False})
    code, d = hub.get("/health", token=None)
    assert d["share_lan"] is False and d["lan_url"] is None


def test_v21_escpos_codepage_config(hub, cfg_reset, monkeypatch):
    printhub.CFG["escpos_codepage"] = "cp850"
    data = printhub.escpos_bytes("caf\xe9")       # \xe9 is 0x82 in cp850
    assert b"caf\x82" in data
    printhub.CFG["escpos_codepage"] = "cp437"
    data = printhub.escpos_bytes("caf\xe9")
    assert b"caf" in data                          # replaced, no crash

# ============================================================
# v2.2.0: quality presets AND DPI, built-in /docs page,
# dashboard LAN card, health lan_active
# ============================================================

def test_v22_quality_preset_still_works(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q", "title": "q",
                                  "kind": "thermal", "printer": "P1",
                                  "quality": "draft"})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "draft"


def test_v22_quality_dpi_spellings(hub, clean_queue):
    """v2.2: quality accepts draft/normal/high AND DPI - all 3 forms."""
    for given, want in (("600dpi", "dpi:600"), ("600", "dpi:600"),
                        ("1200 dpi", "dpi:1200")):
        n = len(hub.printed)
        code, d = hub.post("/print", {"text": "q-" + given, "title": "q-" + given,
                                      "kind": "thermal", "printer": "P1",
                                      "quality": given})
        assert code == 200, (given, d)
        assert wait_until(lambda: len(hub.printed) > n)
        assert hub.printed[-1]["quality"] == want, given


def test_v22_dpi_field(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q-dpi", "title": "q-dpi",
                                  "kind": "thermal", "printer": "P1",
                                  "dpi": 300})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "dpi:300"


def test_v22_quality_alias_and_clamp(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q-best", "title": "q-best",
                                  "kind": "thermal", "printer": "P1",
                                  "quality": "best"})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "high"
    # clamp: 99999 dpi -> 2400
    code, d = hub.post("/print", {"text": "q-clamp", "title": "q-clamp",
                                  "kind": "thermal", "printer": "P1",
                                  "dpi": 99999})
    assert code == 200
    assert wait_until(lambda: hub.printed[-1]["quality"] == "dpi:2400")


def test_v22_capabilities_quality_shape(hub):
    code, d = hub.get("/printers/FakeLaser/capabilities")
    assert code == 200 and d["ok"] is True
    q = d["quality"]
    assert isinstance(q, dict) and "draft" in q["presets"]
    # dpi is either a list (CUPS) or None (Windows driver-controlled)
    assert q["dpi"] is None or isinstance(q["dpi"], list)


def test_v22_docs_page_served(hub):
    code, d = hub.get("/docs")
    assert code == 200
    # the client falls back to raw bytes for non-JSON responses
    body = (d.decode("utf-8", "replace") if isinstance(d, bytes)
            else d if isinstance(d, str) else json.dumps(d))
    assert "LAN sharing" in body and "POST /print" in body
    assert "2.2.0" in body


def test_v22_docs_wrong_token_json(hub):
    code, d = hub.get("/docs", token="wrong-token")
    assert code == 401 and d.get("ok") is False


def test_v22_dashboard_has_lan_card_and_docs(hub):
    html = printhub.dashboard_html("")
    assert 'id="lanBody"' in html and "LAN sharing" in html
    assert "/docs" in html and "shiftJob" in html
    assert "2.2.0" in html


def test_v22_health_lan_active(hub):
    code, d = hub.get("/health")
    assert code == 200
    assert d["lan_active"] is False      # test server binds 127.0.0.1
