# PrintHub Pro — Print from Any Web Page to Any Printer

**PrintHub Pro — Version 2.2.0 · by Bitdream IT · MIT license · 100% local — no cloud, no tracking.**

PrintHub Pro prints from any web page to **any printer** — thermal, receipt, label, or standard — with **no print dialog and no confirmation**. It is a free, 100%-local, MIT-licensed alternative to paid products like Ultraprint Hub: a small **desktop hub** (single Python file, zero pip dependencies) plus a **Chrome extension** that talk to each other on `localhost` only.

```
Web page ──► Chrome extension ──► PrintHub Pro hub (localhost:9235) ──► ANY printer
             (right-click /       • queue: priority · retry · schedule   thermal · receipt
              popup / API /       • audit: who / site / doc hash / time  label · A4 · POS
              auto rules)         • dashboard + CSV + REPRINT watermark  80mm roll · ZPL
```

**Downloads / updates:** everything ships on the GitHub Releases page —
**https://github.com/bitdreamit/PrintHub-Pro/releases**
Update anytime: run `PrintHub Tool` → **8: Check for updates**, or click
**Check for update** in the extension Options → About tab. Installing a
new Setup.exe over the old one keeps all settings and history.

---

## What's new in v2.2.1 — "OK means OK: nothing can silently stall the queue"

Fixes the *"extension shows OK but the printer never prints; history
shows queued; queue on/off does not help"* report at every layer:

- **The print worker can no longer die silently.** One unexpected error
  used to kill the print thread — the hub kept saying `ok` while every
  later job waited forever. The loop is now exception-proof and a
  watchdog respawns it within 30 s (`worker.error` / `worker.restarted`
  in the audit log; `/health` shows `worker_alive`).
- **One-click "Print now"** on every stuck job (popup, Options history,
  dashboard queue) — bypasses the paused queue AND the printer-status
  hold. The popup also gained a **Print all now** button on the new
  held-jobs banner.
- **Honest colors**: `queued` is now GRAY (waiting) — only `printed`
  is green. Held jobs are orange with the reason written under them
  (usually *Windows reports the printer offline*).
- **The extension checks back**: one minute after submitting, a
  verification alarm folds the real outcome (printed / failed + the
  actual error / held) into the extension history and shows a red `!`
  badge + notification when a job failed.
- **Dashboard "Printer status hold" toggle** — Windows mis-reports many
  network printers as offline (stuck *Use Printer Offline*), which HELD
  jobs; turn the check off with one click (`hold_offline`).
- `POST /print` now returns a truthful `status`, `GET /jobs/{id}` gives
  one job for polling, `/health` reports `worker_alive` +
  `hold_offline`. Full walk-through: docs/API.md → *"Troubleshooting:
  jobs stay queued, nothing prints"*.

---

## What's new in v2.2.0 — "You can SEE every feature now"

v2.1.0 shipped the print-option, LAN-sharing and queue-shift machinery as
**API endpoints only** — install it and the extension looked exactly like
v2.0. v2.2.0 puts every one of those features on screen, and the
documentation can no longer go missing:

- **Extension Options → "Default print options"**: copies, pages
  (all / **odd** / **even** / custom range), per-sheet n-up (1/2/4/6/9/16),
  **quality — draft / normal / high AND DPI (300/600/1200 or any custom
  value)**, scale %, margins mm, duplex (two-sided), paper size, layout
  (portrait/landscape). Saved once, sent with **every** job from that
  browser; page scripts and rules still override per job.
- **Extension Options → "LAN / PCs" tab** (the big miss is back in the
  UI): turn **LAN sharing** on/off, copy this PC's LAN URL
  (`http://192.168.x.x:9235`), see peer PCs with online status, and
  **shift the whole waiting queue — or any single job from the Queue tab —
  to another PC**, where it prints immediately.
- **Quality accepts both spellings**: `"quality": "draft"` → CUPS
  `print-quality=3`; `"quality": "600dpi"` (or `"600"`, or `"dpi": 600`)
  → CUPS `printer-resolution=600dpi`. The capabilities endpoint reports
  presets + DPI list per printer; on Windows the driver decides the real
  DPI and the choice is logged on the job.
- **Documentation ships INSIDE the hub**: open
  `http://127.0.0.1:9235/docs?token=…` — the full user guide (feature
  click-map, every print option with backend support matrix, LAN sharing
  steps + firewall command, queue shift, Laravel cron/webhook recipes,
  Bangla receipt notes). Buttons: extension About → *Open user guide*,
  dashboard → *Docs (user guide)*.
- **Dashboard LAN card**: live share_lan state, copy URL, per-peer
  "Shift all waiting jobs", per-row Shift buttons in the queue — plus an
  honest "restart the hub to apply" hint until the listener rebinds.

## What's new in v2.1.0 — "Every printer option, LAN sharing, Bangla receipts"

- **All printer options in the API**: `pages` accepts `odd`/`even`, plus
  `per_sheet`, `quality` (draft/normal/high), `scale_pct`, `margin_mm`,
  `orientation` — alongside the existing `copies`, `duplex`, `paper_size`,
  `tray`. `GET /printers/{name}/capabilities` reports exactly what THIS
  printer supports so UIs show only those options.
- **LAN printer sharing** (`share_lan: true`): other PCs print through
  this PC's printers over `http://<lan-ip>:9235` (token required);
  `POST /queue/shift` moves individual jobs (`ids`) or the whole queue
  (`scope:"all"`) to another PC; pause/resume unchanged.
- **Bangla receipts that actually print**: non-Latin thermal text is
  auto-rendered via headless Chrome (Nirmala UI / Noto Sans Bengali)
  instead of turning into `????`; `escpos_codepage` configurable.
- **New: docs/LARAVEL.md** — scheduled & webhook printing from Laravel
  (PrintHubService + scheduler recipes + retry/backoff pattern).

## What's new in v2.0.2 — "One token opens every page"

Hotfix on top of v2.0.1, from user feedback: the same correct token opened
`/dashboard?token=…` but was **rejected on `/audit?token=…`** — the Options
tab's *Audit* button and any manually opened audit/stats link returned
`401 invalid or missing token`. The v2.0.0 browser-navigation exception was
whitelisted per-route, and `/audit`, `/stats`, `/jobs`, `/diagnostics` were
missing from that list. v2.0.2 replaces the whitelist with one simple rule:

- **Every GET endpoint accepts `?token=`** — a token that opens the
  dashboard equally opens `/audit`, `/stats`, `/printers`, `/jobs`,
  `/queue`, `/config`, `/peers` and the CSV exports. Read-only pages are
  exactly what a browser follows links to; no more "works here, fails
  there" surprises.
- **Mutating calls stay hardened** — every POST (print, queue actions,
  config, token rotate) still requires the `X-PrintHub-Token` header when
  `token_header_only: true` (the v2.0 default). A leaked URL therefore
  cannot trigger prints or change settings.
- **Readable browser errors everywhere** — following any GET link with a
  wrong/missing token now shows the same friendly HTML fix-it page the
  dashboard already used, instead of a raw JSON blob. API clients
  (curl / fetch / Laravel) keep getting the JSON error.

### Fixed in v2.0.1 (previous hotfix)

On multi-Chrome PCs a single stale token could lock the whole machine out
of the hub for 5 minutes. Fixes that shipped in v2.0.1:

- **The owner's PC is never locked out** — the loopback IP is exempt from
  the wrong-token lockout by default (`lockout_exempt_loopback: true` in
  config.json). Remote/LAN IPs keep the full 10-strikes → 5-minute lock.
- **Sliding window + instant recovery** — failures only count inside a
  5-minute window, and one successful auth clears the counter immediately.
- **Self-limiting extension** — on a `401` the extension stops retrying at
  once (circuit breaker, red `KEY` badge, popup banner), instead of
  feeding the hub's failure counter every minute; the moment you save a
  fixed token it retries automatically. On a `429` jobs are parked and
  delivered after the lock expires.
- **Readable errors** — every `401` answer now carries an actionable hint
  ("the old default token no longer works — use the tray menu or
  `python printhub.py token`"); browsers opening `/dashboard` with a wrong
  token get a friendly HTML fix-it page instead of a raw JSON blob.
- **Quieter audit log** — wrong-token attempts are audited at most once
  per 10 s per IP (a polling stale client no longer floods `auth.failed`).

## What's new in v2.0.0 — "Security, Audit & Production Control"

**Security**
- **Random install token** — new installs generate a private random token; the shared default `PrintHub-2024` is gone. Old installs keep working and show a *change default token* warning until rotated.
- **Header-only tokens** on new installs (query/body tokens rejected; browser-navigation endpoints keep accepting `?token=`).
- **Allowed origins** — restrict which websites may print (`allowed_origins: ["*.htncr.org"]`). Empty list = allow all, like 1.x.
- **SSRF-guarded `pdf_url`** — `file://`, `ftp://` and private/local addresses are blocked (exempt list: `pdf_url_allowed_hosts`).
- **IP lockout (v2.0.1)** — 10 wrong tokens from a **remote** IP ⇒ locked 5 minutes. The loopback IP (`127.0.0.1`) is **never locked by default** — all Chrome windows/profiles share that one IP, so a stale token in one window can no longer lock out the dashboard, tray and extension of the others (`lockout_exempt_loopback`). Failures count only inside a sliding 5-minute window and any successful auth clears the counter. Wrong-token 401 answers carry a fix-it hint; the dashboard shows a friendly HTML error page instead of raw JSON.
- **Token rotation** — dashboard button, `POST /token/rotate`, CLI `token-rotate`.

**Printers**
- **Printer status** (ready / offline / paper-out / error) everywhere; jobs **hold** while a printer is offline and print automatically when it returns.
- **Printer groups + fallback** — `"Front": ["A","B"]` prints on the first ready member.
- **Raw printing** — ESC/POS (cut, cash drawer, barcode, QR) and ZPL, no driver, no PDF.
- **Print profiles** (paper, tray, duplex, copies) and **page ranges** (`"pages": "1-3,5"`).

**Queue**
- **Exponential retry**, **priority** (urgent first), **duplicate blocking**, **scheduled prints** (`run_at`), **dead-letter list** with *retry on another printer*, and **peer hubs** (dead peers skipped, optional forwarding).

**Audit**
- **Audit log** — who / which site / document hash / printer / time.
- **Reprint reason** (optionally required) + optional **REPRINT watermark**.
- **Log rotation**, **diagnostics export**, **CSV history/audit export**, and a built-in **web dashboard** (`/dashboard`) with success rate + queue size.

**Extension**
- **Better rules** — glob *or* regex, page-title filter, per-site on/off.
- **Offline banner + automatic retry** when the hub is unreachable.
- **English + বাংলা (Bangla) UI**.

**Repository**
- **pytest suite** (35 tests), **GitHub Actions** CI + tag-driven Release pipeline (zips, .deb, NSIS Setup exe, SHA256SUMS), **.gitignore**, **CHANGELOG.md**.

*(v1.7.2 additions remain: PrintHub Tool one-stop menu, optional Windows service, silent `/S` install, master Enable/Disable switch, Queue Mode On/Off, tabbed Options, GitHub update checks.)*

---

## Package layout (this zip)

```
PrintHub-Pro-2.0.0/
├── README.md            ← you are here
├── CHANGELOG.md         every version, what changed
├── doc/                 guides + API reference
│   ├── PrintHub-Pro-Full-Guide.pdf / .html   (step-by-step manual)
│   ├── API.md           full HTTP reference (v2.0 endpoints)
│   ├── EXTENSION-API.md window.printhub + rules + GPO
│   └── PRIVACY-POLICY.md
├── extension/           Chrome/Edge/Brave extension (load unpacked)
├── tool/
│   ├── windows/         PrintHub-Pro-Setup-2.0.0.exe  ← the installer
│   │                    (+ portable\ variant in the FULL zip)
│   └── unix/            install-unix.sh · uninstall-unix.sh · .deb · hub source
├── tests/               pytest suite (python -m pytest tests)
└── .github/workflows/   CI + Release automation for the GitHub repo
```

---

## Feature highlights

| | PrintHub Pro |
|---|---|
| **Any printer** | Thermal, receipt, label, or standard. If the OS sees it, the hub can print to it. |
| **Printer status + fallback** | Live ready/offline/paper-out/error per printer; jobs hold while offline; groups fail over automatically. |
| **Raw ESC/POS + ZPL** | Receipts with cut / cash drawer / barcode / QR straight to the printer — no driver, no PDF. |
| **Production queue** | Priority, exponential retry, duplicate blocking, scheduled prints, dead-letter list, printer groups, peer hubs. |
| **Audit trail** | Who, which site, document hash, printer, time — plus reprint reasons, optional REPRINT watermark, CSV export. |
| **Dashboard** | Built-in web dashboard: success rate, queue size, live queue, printers, audit trail, token rotation. |
| **Hardened by default** | Random install token, header-only tokens, origin allowlist, SSRF-guarded pdf_url, IP lockout, rotation. |
| **Save as PDF (File)** | Any job can go to a **File** destination instead of paper — `~/Downloads/PrintHub` (configurable). |
| **No print dialog** | Straight to the OS print system (SumatraPDF on Windows, CUPS `lp` on Linux/macOS). |
| **Auto-routing rules** | Glob *or* regex + page-title filter + per-site on/off; auto-print on open with zero browser view. |
| **Print interception** | `window.print()` **and Ctrl+P / Cmd+P** silently rerouted — CSP-safe on strict sites. |
| **Developer API** | `printPdfLink()` one-liner + `window.printhub` + plain HTTP with `priority / pages / profile / run_at / lang / reason / watermark`. |
| **One-stop Tool** | Start / stop / status / service add-remove / auto-run / update / uninstall in one numbered menu. |
| **English + Bangla** | Popup and Options in English or বাংলা (auto-detect or manual). |
| **Enterprise ready** | Managed-storage schema (`managed.json`) for GPO/MDM deployment. |
| **Private by design** | No data collection, no external servers, no accounts. Localhost bind + token. |

---

## Quick start (3 steps)

### 1. Install the hub (one-time, zero questions)

**Windows — recommended:**

```
tool\windows\PrintHub-Pro-Setup-2.0.0.exe
```

**STANDALONE installer — Python is included inside** (bundled 3.11 runtime +
`PrintHubPro.exe`): copies everything to `%LOCALAPPDATA%\PrintHubPro`,
registers **auto-run as a visible Startup app**, starts the hub, adds Start
Menu shortcuts (**Start PrintHub Pro · PrintHub Tool · Uninstall**) and a real
**Add/Remove Programs uninstaller**. The hub shows a **"PrintHub Pro" tray
icon**. No admin, no Python install, never shows as "python".

- **Silent install:** `PrintHub-Pro-Setup-2.0.0.exe /S`
- **Optional Windows service:** tick *Install as Windows Service (advanced)*, or PrintHub Tool → 5.
- Unsigned EXE → SmartScreen may ask once. If an EXE ever reports "corrupted":
  re-download and compare the SHA-256 in `SHA256SUMS-2.0.0.txt`.

**Linux (Debian/Ubuntu/Mint):**

```
sudo apt install ./tool/unix/printhub-pro_2.0.0_all.deb
```

**macOS / other Linux:** `bash tool/unix/install-unix.sh` · **Windows portable:** FULL zip → `tool\windows\portable\install-windows.bat`.

> **v2.0 token:** a fresh install creates a **private random token**. Read it
> with `python printhub.py token` (or in the hub console / dashboard link) and
> paste it once into the extension Options. **Old installs** keep their current
> token and the UI shows a yellow *default token* warning until you rotate it.

### 2. Load the extension

1. Open `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select the `extension/` folder

### 3. Connect & print

1. Click the PrintHub icon → popup shows **Connected** (enter your token in Options if asked)
2. Right-click any page → **PrintHub Pro → Print this page**
3. Or open a URL matching a routing rule — it prints with no dialog and the tab closes

---

## The PrintHub Tool (Windows Start Menu → "PrintHub Tool")

```
[1] Start PrintHub            [5] Windows service - install
[2] Stop PrintHub             [6] Windows service - remove
[3] Status                    [7] Start at logon: ON / OFF
[4] Print test page           [8] Check for updates (GitHub)
[9] Show recent jobs         [10] Uninstall / remove
[0] Exit
```

---

## The HTTP API (any language, any tool)

```bash
# list printers WITH live status
curl -H "X-PrintHub-Token: $TOKEN" http://127.0.0.1:9235/printers

# urgent PDF print, only pages 1-3, double-sided
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"pdf_url":"https://example.com/invoice.pdf","title":"Invoice 42",
       "priority":1,"pages":"1-3","duplex":"long"}'

# raw ESC/POS receipt with cut + cash drawer + QR (no driver needed)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"lang":"escpos","text":"|center|MY SHOP\nItem 1   10.00\n|qr:order-42|\n|drawer|\n|cut|","printer":"XP-58"}'

# schedule a print for 9:00 tomorrow
curl -X POST http://127.0.0.1:9235/print -H "X-PrintHub-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"morning report","run_at":"2026-10-27T09:00:00"}'

# recover a dead-letter job on ANOTHER printer
curl -X POST -H "X-PrintHub-Token: $TOKEN" \
  http://127.0.0.1:9235/jobs/42/retry -d '{"printer":"BackupLab"}' \
  -H "Content-Type: application/json"

# web dashboard (success rate, queue, audit trail) + CSV exports
start http://127.0.0.1:9235/dashboard?token=$TOKEN
curl -H "X-PrintHub-Token: $TOKEN" http://127.0.0.1:9235/export/history.csv -o history.csv
```

Full reference: [`doc/API.md`](doc/API.md) · Browser API: [`doc/EXTENSION-API.md`](doc/EXTENSION-API.md)

---

## Configuration

Settings now live in **`config.json`** inside the data dir (`~/.printhub/config.json`) —
editable by hand, via `POST /config`, or from the dashboard. Environment
variables still override config.json for the classic keys.

| config.json key | Default | Meaning |
|---|---|---|
| `token` | *(random on new installs)* | API token — rotate with `token-rotate` / `POST /token/rotate` |
| `token_header_only` | `false` (old installs) / `true` (new) | Reject `?token=`/body tokens except browser-navigation endpoints |
| `allowed_origins` | `[]` = allow all | Which websites may print, e.g. `["*.htncr.org"]` |
| `pdf_url_allowed_hosts` | `[]` | Hosts exempt from the private-IP block |
| `max_auth_failures` / `lockout_minutes` | `10` / `5` | Wrong-token lockout (remote IPs) |
| `lockout_exempt_loopback` | `true` | v2.0.1: never lock 127.0.0.1/::1 (all Chrome windows share it) |
| `printer_groups` | `{}` | `{"Front": ["A", "B"]}` fallback order |
| `profiles` | `{}` | `{"Invoice": {"paper_size":"A4","duplex":"long","copies":2}}` |
| `max_retries` / `retry_base_seconds` | `2` / `30` | Exponential retry (0 = off, 1.7.2 behaviour) |
| `dedupe_minutes` | `5` | Duplicate-job blocking window |
| `hold_offline` | `true` | Hold jobs while the printer is offline |
| `audit_enabled` | `true` | Audit log on/off |
| `reprint_watermark` | `false` | Stamp REPRINT on reprints |
| `reprint_reason_required` | `false` | Require a reason for every reprint |
| `peer_hubs` / `peer_forwarding` | `[]` / `false` | Backup hubs + auto-forwarding |
| `log_max_mb` / `log_backups` | `5` / `3` | hub.log rotation |

| Environment variable | Default | Meaning |
|---|---|---|
| `PRINTHUB_TOKEN` | — | Overrides config.json token (1.x compatibility) |
| `PRINTHUB_PORT` | `9235` | HTTP port |
| `PRINTHUB_HOST` | `127.0.0.1` | Bind address — `0.0.0.0` for office LAN sharing |
| `PRINTHUB_PRINTER` | *(OS default)* | Force a specific printer |
| `PRINTHUB_FILE_DIR` | `~/Downloads/PrintHub` | Where File-destination PDFs are saved |
| `PRINTHUB_DATA` | `~/.printhub` | Data folder (SQLite history + job files + config.json) |

**CLI:** `python hub/printhub.py serve | testprint [a4|thermal] | printers | history [n] | reprint <id> [reason] | queue | doctor | token | token-rotate | diagnostics | service-install | service-remove | service-status | update-check | help`

**LAN mode:** set `PRINTHUB_HOST=0.0.0.0` and point the extension at your PC's LAN IP. Token is always required; consider `allowed_origins` for websites.

---

## Privacy & security

- **No data collection.** No telemetry, no account, no analytics — 100% local, no cloud, no tracking.
- **Localhost only** unless you explicitly enable LAN mode.
- **Hardened auth:** constant-time token compare, header-only mode on new installs, origin allowlist, IP lockout, SSRF-guarded `pdf_url`, rotation.
- **Open source, MIT.** Audit every line — the hub is one readable Python file; tests in `tests/`.

## Requirements

- Python 3.8+ (no pip packages) — the Windows Setup EXE bundles its own runtime
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) (free; setup offers it via winget). Raw ESC/POS printing needs no Sumatra.
- **Linux/macOS:** CUPS (`cups-client`)
- Optional: Chrome/Chromium/Edge — only for *page* printing (HTML → PDF)

## License

MIT © Bitdream IT — free for personal and commercial use.
