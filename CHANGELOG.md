# PrintHub Pro — Changelog

All notable changes to **PrintHub Pro** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning is
[SemVer](https://semver.org/).

---

## [2.0.0] — 2026-10-26 — "Security, Audit & Production Control"

The largest release ever: 22 features across security, printers, queue,
audit, the extension and the repository. Old installs, old databases and
old connect codes keep working; every new setting lives in `config.json`
and defaults to the 1.x behaviour unless explicitly noted.

### Security
- **Random install token**: brand-new installs generate a private random
  token (saved to `config.json`). The old shared default `PrintHub-2024`
  is no longer used for new installs. Old installs keep working and raise
  a `default_token_warning` in `/health` + the UI until the token is
  rotated.
- **Header-only tokens**: new installs accept the token only in the
  `X-PrintHub-Token` header (query/body tokens are rejected). Old installs
  keep accepting `?token=` (browser navigation endpoints `/dashboard`,
  `/jobs/{id}/file`, `/export/*.csv` always accept it).
- **Allowed origins**: `allowed_origins` in config.json (e.g.
  `["*.htncr.org"]`). Empty list = allow all, exactly like 1.x. Browser
  extension origins are always trusted.
- **SSRF-guarded `pdf_url`**: `file://`, `ftp://` and every non-HTTP(S)
  scheme are blocked; hosts resolving to private/loopback/link-local
  addresses are blocked unless listed in `pdf_url_allowed_hosts`.
- **IP lockout**: 10 wrong tokens from one IP locks that IP for 5 minutes
  (`max_auth_failures` / `lockout_minutes`), all recorded in the audit log.
- **Token rotation**: `POST /token/rotate`, CLI `python printhub.py
  token-rotate`, and a one-click button in the dashboard.

### Printers
- **Printer status**: ready / offline / paper-out / error per printer
  (Win32_Printer on Windows, `lpstat -p` on Unix), shown in `/printers`,
  the Options page and the dashboard.
- **Offline hold**: jobs are HELD while the target printer is offline /
  out of paper and print automatically when it comes back
  (`hold_offline`, default on).
- **Printer groups + fallback**: `printer_groups: {"Front": ["A","B"]}` —
  the first ready member prints; failures fall through the remaining
  members.
- **Raw printing**: ESC/POS (init, sizes, alignment, cut, cash drawer,
  CODE128 barcode, QR) and ZPL passthrough — `POST /print` with
  `lang: "escpos"|"zpl"` + `text`, or pre-built bytes via `raw_base64` /
  `application/octet-stream?kind=raw`. Windows prints RAW via winspool
  (ctypes), Unix via `lp -o raw`.
- **Print profiles + page ranges**: named profiles (paper, tray, duplex,
  copies, printer) in `profiles`; `pages: "1-3,5"` and `duplex` /
  `paper_size` / `tray` per request (SumatraPDF page ranges + duplex;
  tray via CUPS).

### Queue
- **Exponential retry** (`max_retries` = 2, backoff 30 s → 60 s → 120 s,
  `retry_base_seconds`).
- **Job priority** 1 (urgent) … 9 (low) — `priority` on `/print`,
  `POST /jobs/{id}/priority`; urgent jobs jump the FIFO.
- **Duplicate blocking**: identical documents (sha256 fingerprint +
  printer) are blocked within `dedupe_minutes` (5); response reports
  `duplicate: true`; `dedupe: false` opts out per request.
- **Scheduled printing**: `run_at` (ISO datetime or `+5m`/`+2h`) — jobs
  wait as `scheduled` and enter the queue automatically when due.
- **Dead-letter list**: after the final retry the job becomes `dead`
  (`GET /jobs?status=dead`) and can be recovered with
  `POST /jobs/{id}/retry` — optionally **on another printer**.
- **Peer hubs**: `peer_hubs` + `peer_forwarding` — `/peers` health-probes
  every peer; dead peers are skipped; jobs can be handed to a live peer
  that actually has the printer.

### Audit
- **Audit log**: who (source), which site (Origin/Referer), document
  sha256, printer, time — `GET /audit` (+ `.csv`).
- **Reprint reason**: `reason` on reprint, recorded in the audit log;
  `reprint_reason_required` makes it mandatory; the UI always asks.
- **REPRINT watermark**: `reprint_watermark` config or `watermark: true`
  per reprint — a diagonal gray stamp on every page (pure-Python PDF
  overlay; original bytes on any parse problem).
- **Log rotation + diagnostics**: `hub.log` rotates at `log_max_mb`
  keeping `log_backups` copies; `GET /diagnostics` / CLI `diagnostics`
  export a support bundle (token redacted).
- **CSV export + dashboard**: `GET /export/history.csv`,
  `/export/audit.csv`, and a built-in web dashboard at
  `/dashboard?token=…` (success rate, queue size, live queue, printers,
  audit trail, token rotation).

### Extension
- **Better rules**: glob **or regex** patterns, page-title filter, and a
  per-site on/off switch per rule.
- **Offline banner + retry**: when the hub is unreachable, jobs are kept
  in the browser, a red banner shows the waiting count, and a 1-minute
  alarm delivers them automatically once the hub answers (`retryOffline`).
- **English + Bangla UI**: popup + Options are fully translated
  (English / বাংলা / auto-detect), selectable in Options.
- Default-token warning banner in the popup, printer status in the
  printer dropdowns, dashboard/audit shortcuts.

### Repository
- **pytest suite**: 35 tests booting the real hub over HTTP (no printer
  needed) — security, queue, audit, raw printing, migration.
- **GitHub Actions**: `ci.yml` (pytest + JS syntax + JSON checks on every
  push) and `release.yml` (tag push → zips + .deb + NSIS Setup exe →
  GitHub Release with SHA256SUMS).
- **Hygiene**: `.gitignore` (binaries, `docs/node_modules`, build output,
  data dirs) and this `CHANGELOG.md`.

### Compatibility notes
- Old `history.db` is migrated in place with `ALTER TABLE`; nothing is
  rewritten or dropped.
- `PRINTHUB_TOKEN` env var still overrides config.json.
- The extension still connects to old 1.x hubs and vice versa (the hub
  reports `v2: true` so the UI can enable new panels).

---

## [1.7.2] — 2026-10-22 — "Simple Install & Control"
- Setup-1.7.2.exe: install / uninstall / optional Windows service / silent
  `/S` in one standalone NSIS installer.
- PrintHub Tool menu (start/stop/service/autorun/history/update).
- Extension: master Enable/Disable switch, Queue Mode On/Off, tabbed
  Options (Queue | History | Settings | About, default tab = Queue when
  data exists), GitHub update checks.
- Package layout reduced to `doc/ + extension/ + tool/{windows,unix}`.
- Windows service wrapper `service_main.py` (services.msc entry).

## [1.7.0] — 2026-10-20 — "Network & Queue Edition"
- Share Printer over LAN + Queue Mode + cross-PC failover (folded from
  the v1.6.0 "Performance & Control" work).

## [1.5.0] — 2026-10-18 — "Identity & Control"
- System tray icon, Startup-app autostart (Task Manager visible),
  `PrintHubPro.exe` process identity, double-start guard.

## [1.4.0] / [1.3.0] — 2026-10-16
- Chrome Web Store kit (privacy policy, listing texts, screenshots),
  silent-print reliability fixes.

## [1.2.0] — 2026-10-15
- page-side snippet kit (`lab-report-print.js`), guard fixes, toast.

## [1.1.0] — 2026-10-14
- File destination (`__file__` → save-as-PDF), `PRINTHUB_FILE_DIR`.

## [1.0.0] — 2026-10-12
- First public release: pure-stdlib hub, MV3 extension, silent printing
  via SumatraPDF / CUPS, DB-backed queue, SQLite history, token auth.
