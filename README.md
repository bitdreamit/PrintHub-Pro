# PrintHub Pro — Print from Any Web Page to Any Printer

**PrintHub Pro — Version 2.0.0 · by Bitdream IT · MIT license · 100% local — no cloud, no tracking.**

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

## What's new in v2.0.0 — "Security, Audit & Production Control"

**Security**
- **Random install token** — new installs generate a private random token; the shared default `PrintHub-2024` is gone. Old installs keep working and show a *change default token* warning until rotated.
- **Header-only tokens** on new installs (query/body tokens rejected; browser-navigation endpoints keep accepting `?token=`).
- **Allowed origins** — restrict which websites may print (`allowed_origins: ["*.htncr.org"]`). Empty list = allow all, like 1.x.
- **SSRF-guarded `pdf_url`** — `file://`, `ftp://` and private/local addresses are blocked (exempt list: `pdf_url_allowed_hosts`).
- **IP lockout** — 10 wrong tokens ⇒ that IP is locked for 5 minutes.
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
| `max_auth_failures` / `lockout_minutes` | `10` / `5` | Wrong-token lockout |
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
