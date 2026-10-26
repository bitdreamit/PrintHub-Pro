"""Pytest fixtures: boot a real PrintHub Pro v2.0.1 hub (pure stdlib) on a
random port with an isolated data dir, then hand tests an HTTP client.

The print backends are monkeypatched (no printer needed) - print_file /
print_raw record their calls so queueing, priority, retry, hold and
raw printing are all testable end-to-end through the real HTTP API.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "hub"))

import printhub  # noqa: E402  (path set above)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_until(fn, timeout=8.0, step=0.05):
    """Poll fn() until truthy (worker threads are async)."""
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return False


class Hub:
    """Live hub handle + tiny JSON client."""

    def __init__(self, base, token):
        self.base = base
        self.token = token
        self.printed = []          # dicts recorded by the print_file stub
        self.raw_printed = []      # (data, printer) recorded by print_raw stub

    # ---- client ----
    def req(self, method, path, token="use-default", body=None, headers=None,
            raw=None, content_type="application/json"):
        h = dict(headers or {})
        if token == "use-default":
            h["X-PrintHub-Token"] = self.token
        elif token is not None:
            h["X-PrintHub-Token"] = token
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", content_type)
        r = urllib.request.Request(self.base + path, data=data,
                                   headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                payload = resp.read()
                code = resp.getcode()
        except urllib.error.HTTPError as e:
            payload = e.read()
            code = e.code
        try:
            return code, json.loads(payload.decode("utf-8"))
        except Exception:
            return code, payload

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body=body, **kw)


@pytest.fixture(scope="session")
def hub(tmp_path_factory):
    data_dir = str(tmp_path_factory.mktemp("printhub-data"))
    port = _free_port()
    printhub.CFG["data_dir"] = data_dir
    printhub.CFG["port"] = port
    printhub.CFG["host"] = "127.0.0.1"
    printhub.db_init()          # also bootstraps config.json + random token
    printhub.RESUME_EVENT.set()
    printhub.start_worker()

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", port), printhub.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    h = Hub("http://127.0.0.1:%d" % port, printhub.CFG["token"])

    # ---- stub the OS print backends (no real printer in CI) ----
    def fake_print_file(path, kind="a4", printer="", copies=1, job_id=None,
                        pages=None, duplex=None, paper_size=None, tray=None,
                        per_sheet=None, quality=None):
        h.printed.append(dict(path=path, kind=kind, printer=printer,
                              copies=copies, job_id=job_id, pages=pages,
                              duplex=duplex, paper_size=paper_size,
                              per_sheet=per_sheet, quality=quality,
                              tray=tray))
        return printer or "StubPrinter"

    def fake_print_raw(data, printer="", job_id=None, title="raw"):
        h.raw_printed.append((bytes(data), printer))
        return printer or "StubPrinter"

    printhub.print_file = fake_print_file
    printhub.print_raw = fake_print_raw

    yield h
    httpd.shutdown()


@pytest.fixture()
def clean_queue(hub):
    """Fresh queue state + printed-log per test."""
    printhub.RESUME_EVENT.set()
    hub.printed.clear()
    hub.raw_printed.clear()
    for j in printhub.db_list(limit=500):
        if j["status"] in ("queued", "printing", "held", "scheduled"):
            printhub.db_update(j["id"], status="canceled", error="test reset")
    yield hub


@pytest.fixture()
def cfg_reset(hub):
    """Snapshot config keys a test may mutate; restore afterwards."""
    snap = {k: printhub.CFG[k] for k in
            ("allowed_origins", "max_retries", "dedupe_minutes",
             "hold_offline", "reprint_reason_required", "reprint_watermark",
             "printer_groups", "profiles", "peer_forwarding",
             "lockout_exempt_loopback", "max_auth_failures",
             "lockout_minutes")}
    yield hub
    printhub.CFG.update(snap)
    printhub._AUTH_FAILS.clear()
