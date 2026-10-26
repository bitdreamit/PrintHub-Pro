# PrintHub Pro — Changelog

All notable changes to **PrintHub Pro** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning is
[SemVer](https://semver.org/).

---

## [2.2.0] — 2026-10-27 — "You can SEE every feature now"

v2.1.0 shipped the new machinery as API endpoints only; the extension UI
showed nothing new and the docs were easy to miss. This release surfaces
everything.

### Added
- **Extension Options → "Default print options"** section: copies, pages
  (all / odd / even / custom range), per-sheet n-up (2/4/6/9/16), quality
  (draft/normal/high **and** 300/600/1200 dpi or any custom DPI), scale %,
  margins mm, duplex (one/two-sided long/short edge), paper size and
  layout. Stored as `printDefaults` and merged into EVERY job this
  browser sends (`applyPrintDefaults` in background.js) - per-call values
  from page scripts, rules or the popup still win. A capability line shows
  what the selected printer really supports
  (`GET /printers/{name}/capabilities`).
- **Extension Options → "LAN / PCs" tab**: LAN sharing on/off
  (`POST /config {"share_lan": ...}`) with honest "restart the hub to
  apply" state (`/health` now reports `lan_active`), copy-LAN-URL button,
  firewall command, peers table (from `/peers`) with per-peer
  **Shift all waiting jobs**, and a manual shift form (URL + optional
  peer token). Queue tab rows gained **Shift to PC** buttons.
- **Hub dashboard "LAN sharing & other PCs" card**: live state + LAN URL +
  copy + enable/disable + per-peer shift-all + per-row Shift in the queue
  + Docs button.
- **`GET /docs`** - the full user guide served by the hub itself (feature
  click-map, complete print-option table with Windows/CUPS support,
  quality presets + DPI section, LAN sharing steps incl. firewall
  command, queue on/off + shift, Laravel scheduler/webhook recipes,
  Bangla thermal notes, endpoint map). Token-protected like the
  dashboard; linked from the extension About tab and the dashboard.
- **`quality` dual mode on POST /print**: named presets
  (`draft|normal|high`, plus `best|fine` aliases) AND DPI values
  (`"600"`, `"600dpi"`, or the separate `"dpi": 600` field, clamped
  72-2400). Presets map to CUPS `print-quality=3/4/5`; DPI maps to
  `printer-resolution=<n>dpi`. Capabilities now return
  `quality: {presets, dpi}` per printer.
- `window.printhub.print()` passes `per_sheet, quality, dpi, scale_pct,
  margin_mm, duplex, paper_size, orientation` straight through.

### Changed
- Windows/Sumatra note for quality/DPI now explains per-case that the
  Windows driver keeps control (Sumatra has no quality/resolution
  switch); the requested value is still stored on the job and audited.
- Extension + installer version sweep to 2.2.0.

### Fixed
- The v2.1.0 "invisible features" regression: LAN sharing, queue shift
  and print options now have real UI instead of API-only access, and the
  documentation ships inside the hub so it cannot go missing again.

## [2.1.0] — 2026-10-26 — "Every printer option, LAN sharing, Bangla receipts"

### Added
- **Full print-option surface** on `POST /print` (API + Laravel guide):
  `pages` now accepts **"odd" / "even"** (SumatraPDF + CUPS `page-set`),
  plus new `per_sheet` (2/4/6/9/16, CUPS `number-up`), `quality`
  (draft/normal/high, CUPS `print-quality`), `scale_pct` + `margin_mm` +
  `orientation` (applied when the hub renders text/HTML jobs; injected as
  `@page`/zoom CSS for HTML). `copies`, `duplex`, `paper_size`, `tray`
  were already there - all now pass through the queue and the bypass path.
- **`GET /printers/{name}/capabilities`** - what THIS printer actually
  supports (Windows: SumatraPDF capability map; Linux: live
  `lpoptions -l`). Drives UIs/APIs to show only supported options.
- **LAN printer sharing is back** (`share_lan`, default false = old
  behaviour): listen on 0.0.0.0 so OTHER PCs print through this PC's
  printers; `/health` reports `share_lan` + `lan_url`; token always
  required, remote IPs keep the full lockout.
- **`POST /queue/shift`** - move queued/held/failed jobs to another PC's
  hub over the LAN: `scope:"all"` (full shift) or `scope:"job","ids":[..]`
  (individual shift); jobs are re-uploaded and marked `forwarded`.
  Queue on/off remains `/queue/pause` + `/queue/resume`.
- **Bangla / Unicode receipts** (`thermal_text_engine: auto`): text that
  cannot be encoded in Latin-1 is rendered through headless Chrome with
  system Bangla fonts (Nirmala UI / Noto Sans Bengali) so it prints
  correctly on 80 mm rolls instead of `????`. `escpos_codepage` (default
  cp437) makes raw ESC/POS codepages configurable; unencodable lines
  fall back safely with a warning.
- **docs/LARAVEL.md** - complete server-side guide: PrintHubService,
  scheduler recipes (daily 9:00 auto-print, 15-minute invoice sweep),
  webhook printing, `run_at` hub-side scheduling, status polling with
  backoff, ESC/POS receipts, capabilities discovery, multi-PC LAN setup.

### Fixed
- Queue-Mode-OFF (bypass) jobs now honour `pages`/`duplex`/`paper`/`tray`
  and the new options too (2.0 dropped them on the immediate path).

---

## [2.0.2] — 2026-10-26 — "One token opens every page"

### Fixed
- **`/audit?token=…` was rejected while `/dashboard?token=…` worked** with
  the same, correct token: the v2.0.0 "browser-navigation exception" was a
  per-route whitelist (`/dashboard`, `/jobs/{id}/file`, `/export/*`,
  `/audit.csv`) that forgot the JSON views — `/audit`, `/stats`, `/jobs`,
  `/printers`, `/queue`, `/config`, `/diagnostics`, `/peers`. The
  extension Options tab's *Audit* button opens exactly `/audit?token=…`
  and returned `401 invalid or missing token` for every user. **v2.0.2
  replaces the whitelist with one uniform rule: every GET endpoint
  accepts `?token=` for browser navigation.**
- **Friendly HTML auth-error page on every GET**: a browser following a
  link with a wrong/missing token now gets the same readable fix-it page
  the dashboard already used, instead of a raw JSON blob. API clients
  (curl / fetch / Laravel Http) keep receiving the JSON error because
  they do not send `Accept: text/html`.

### Security
- **Hardening unchanged where it matters**: all mutating endpoints (POST)
  still require the `X-PrintHub-Token` header when
  `token_header_only: true` (default on new installs) — a query token
  alone can read, never print or change settings. The IP lockout,
  sliding-window counting and loopback exemption from v2.0.1 are
  untouched.

---

## [2.0.1] — 2026-10-26 — "Lockout fix for multi-Chrome PCs"

### Fixed
- **Loopback is never locked out** (`lockout_exempt_loopback`, default
  `true`): in v2.0.0 every Chrome window/profile shares the single IP
  `127.0.0.1`, so one stale token (e.g. an old
  `/dashboard?token=PrintHub-2024` bookmark) could hit 10 failed tokens
  and lock the dashboard, tray, extension and all other windows out for
  5 minutes — repeatedly, because the stale client kept retrying. The
  hub now never locks its owner's loopback IP; remote/LAN IPs keep the
  full lock. Set `lockout_exempt_loopback: false` for the strict
  v2.0.0 behaviour.
- **Sliding-window failure counting**: wrong tokens only count inside a
  `lockout_minutes` window (old failures expire instead of accumulating
  into a surprise lock days later); any successful auth clears that
  IP's counter instantly.
- **Extension circuit breaker**: on HTTP 401 the extension stops sending
  immediately (no more per-minute retry storm), shows a red `KEY` badge
  plus a popup banner, and resumes + flushes the moment a fixed token or
  hub URL is saved. On HTTP 429 jobs are parked and auto-delivered after
  the lock expires. `Flush` backoff doubles 1 → 2 → 4 → 8 → 15 min.
- **Actionable 401 hints**: every invalid-token answer explains how to
  get the current token (tray menu, config.json,
  `python printhub.py token`) and specifically calls out the old default
  `PrintHub-2024` when it is used.
- **Dashboard HTML error page**: browsers opening `/dashboard` with a
  wrong/missing token now get a styled fix-it page (tray icon, CLI and
  config-file instructions) instead of a raw JSON blob.
- **Audit spam throttle**: `auth.failed` is written at most once per
  10 s per IP, so a polling stale client no longer floods the audit log
  (and the `_AUTH_FAILS` map is capped/cleaned).

### Changed
- Version anchors 2.0.0 → 2.0.1 (hub `VERSION`, branding, extension
  manifest/popup/options, docs, tests).
- README security section, docs/API.md auth section and the config table
  document the new key and behaviour.

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
