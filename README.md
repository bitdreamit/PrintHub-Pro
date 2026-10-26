# PrintHub Pro — Print from Any Web Page to Any Printer

**Silent. Local. Open source. No subscription.**

**AdvMedi by Bit Dream IT — Innovative Healthcare Solutions** · [www.bitdreamit.com](https://www.bitdreamit.com)

PrintHub Pro prints from any web page to **any printer** — thermal, receipt, label, or standard — with **no print dialog and no confirmation**. It is a free, 100%-local, MIT-licensed alternative to paid products like Ultraprint Hub: a small **desktop hub** (single Python file, zero pip dependencies) plus a **Chrome extension** that talk to each other on `localhost` — or across your whole office LAN with one click.

```
Web page ──► Chrome extension ──► PrintHub Pro hub (localhost or LAN) ──► ANY printer
             (right-click /       • queue: pause·resume·cancel·retry      thermal · receipt
              popup / API /       • history: unlimited (SQLite) + clear    label · A4 · POS
              auto rules)         • LAN sharing: one hub for many PCs      80mm roll
                                  • failover: job hops to a peer hub
```

---

## Feature highlights

| | PrintHub Pro |
|---|---|
| **Any printer** | Thermal, receipt, label, or standard. If the OS sees it, the hub can print to it. |
| **Save as PDF (File)** | Any job can go to a **File** destination instead of paper — the hub writes the PDF into `~/Downloads/PrintHub` (configurable). No dialog, no paper. |
| **No print dialog** | Jobs are sent straight to the OS print system (SumatraPDF on Windows, CUPS `lp` on Linux/macOS). |
| **Auto-routing rules** | Match URLs to printers automatically — orders page → receipt printer, shipping page → label printer. |
| **Auto-print on open** | Open a report URL (e.g. your Laravel `/medical_reports/pdf-test/...` route) and it prints instantly — the tab closes right after, so there is **zero browser view**. |
| **Print interception** | `window.print()` calls **and Ctrl+P / Cmd+P** from any web app (Odoo, SAP, POS) are rerouted silently. Injection is CSP-safe: it works even on strict-CSP sites with no console errors. |
| **Works everywhere** | Any web application: ERP, POS, e-commerce, logistics, healthcare. |
| **Developer API** | Global one-liner `printPdfLink(url, title)` on every page (silent + automatic browser fallback) + `window.printhub` API + plain HTTP `POST /print` (raw binary PDF = no base64) for any language. |
| **Screenshot printing** | Capture and print the visible page with one click. |
| **Print queue** | Pause, resume, cancel — live, and the queue survives hub restarts. |
| **Industrial queue (v1.7.0)** | **Unlimited** job list. Failed jobs **auto-retry** with growing delay, stay visible in the history with Retry / Cancel buttons, and can **fail over**: if this PC cannot print, the job is forwarded to a peer hub on the LAN and that PC prints it. Clear failed / completed / all with one click. |
| **Network sharing (v1.7.0)** | One-click **share the hub on the office LAN**: every PC installs only the extension, pastes the **connect code** (`http://192.168.x.x:9235|TOKEN`) and prints through this one hub + printer. Token-protected — nobody without the token can use the shared IP. Toggle in Options → Sharing, from the tray menu, or `python printhub.py share on`. |
| **Site block/unblock (v1.7.0)** | Quick popup button + right-click item: **"Auto-print on this site: ON/BLOCKED"** — instantly silence a chatty system without touching your rules. |
| **Job history** | Unlimited jobs with status, printer, timing, retry counter — reprint or requeue any job, clear what you don't need. |
| **Performance (v1.7.0)** | Raw binary PDF upload (no base64), thread-local SQLite + WAL, event-driven worker, cached printer discovery, automatic job-file cleanup, `fit` page-scaling parameter. |
| **Enterprise ready** | Managed-storage schema (`managed.json`) for GPO/MDM deployment of settings and locked rules. |
| **Private by design** | No data collection, no external servers, no accounts. Hub binds to `127.0.0.1` and is token-protected. |

**Extra features beyond the paid original:** auto-print PDF URLs with login cookies (Laravel signed routes work), silent printing of raw text to 80 mm thermal rolls, **save-as-PDF File destination for every job type**, reprint-from-history via HTTP and CLI, `doctor` self-diagnosis, optional LAN mode for shared office printers.

---

## Quick start (3 steps)

### 1. Install the hub (one-time, zero questions)

**Easiest — native installers (v1.7.0):**

| | file | what it does |
|---|---|---|
| **Windows** | `PrintHub-Pro-Setup-1.7.0.exe` | **STANDALONE installer — Python is included inside** (bundled 3.11 runtime + `PrintHubPro.exe`): copies everything to `%LOCALAPPDATA%\PrintHubPro`, registers **auto-run as a visible Startup app** (Task Manager → Startup apps → "PrintHub Pro"), starts the hub, adds Start Menu shortcuts + a real **Add/Remove Programs uninstaller**. The hub shows a **"PrintHub Pro" tray icon** (right-click = status page, test page, pause, **share on network**, **copy connect code**, auto-run on/off, exit). No admin, no Python install, no dialogs, never shows as "python". Note: unsigned EXE → SmartScreen may ask once: *More info → Run anyway*. |
| **Linux (Debian/Ubuntu/Mint)** | `printhub-pro_1.7.0_all.deb` | `sudo apt install ./printhub-pro_1.7.0_all.deb` — installs to `/opt/printhub`, ships a **systemd user service** (auto-run at login, restarts on crash) + XDG autostart fallback. CLI: `printhub doctor`. |
| **macOS / other Linux** | `install/install-unix.sh` | same auto-run via LaunchAgent / systemd --user / XDG, no sudo needed. |

**Or the portable way (both platforms):**

**Windows** — double-click one file:
```
install\install-windows.bat        ← starts the hub NOW + auto-run at every logon,
                                     uses the BUNDLED Python runtime (installer\runtime)
                                     if present - no system Python needed, no prompts
```

**Linux / macOS** — one command:
```
bash install/install-unix.sh       ← starts the hub NOW + auto-run at every login,
                                     no sudo needed (systemd --user / LaunchAgent)
```

Both installers register **auto-run automatically** — after a reboot the hub is
always there, no shortcut needed. To undo it:

| | stop auto-run + hub | keep / remove print data |
|---|---|---|
| **Windows** | `install\UNINSTALL-WINDOWS.bat` | data in `%USERPROFILE%\.printhub` |
| **Linux / macOS** | `bash install/uninstall-unix.sh` | data in `~/.printhub` |

Windows notes (v1.5.0): the hub runs as `PrintHubPro.exe` (a renamed
`pythonw.exe`), so Task Manager shows **"PrintHubPro"** — not "python".
Auto-run is a normal **Startup app** shortcut: open **Task Manager →
Startup apps** and you will find "PrintHub Pro" there with its icon —
right-click → Enable/Disable any time (same switch as the tray icon
menu, or `UNINSTALL-WINDOWS.bat`). The installer also removes
Mark-of-the-Web from the downloaded files automatically, and the
installer/upgrader deletes the invisible scheduled task that v1.2–v1.4
used to create. If the hub ever fails to start after a reboot, open
`%USERPROFILE%\.printhub\hub.log` — the hub logs every
startup and print there.

The hub starts on `http://127.0.0.1:9235` with default token `PrintHub-2024`.

### 2. Load the extension

1. Open `chrome://extensions` in Chrome / Edge / Brave
2. Enable **Developer mode** (top-right)
3. Click **Load unpacked** → select the `extension/` folder

### 3. Connect & print

1. Click the PrintHub icon → the popup shows **Connected**
2. Right-click any page → **PrintHub Pro → Print this page**
3. Or open a URL matching a routing rule (the default rule auto-prints `*://www.htncr.org/lab/medical_reports/*`) — it prints with no dialog

---

## Share one hub across the office (v1.7.0)

Turn the PC with the printer into the print server — the other PCs need **only the extension**, no hub, no printer drivers:

1. **On the printer PC** — any ONE of these:
   - Extension **Options → Sharing → Enable sharing**, or
   - Tray icon → *Share on network (LAN)*, or
   - CLI: `python printhub.py share on`
2. Copy the **connect code** shown there (or tray → *Copy connect code*):
   ```
   http://192.168.1.20:9235|PH-A1B2C3D4E5F6A7B8C9
   ```
3. **On every other PC** — install the extension, open Options → *Sharing*, paste the code → **Use connect code**. Done: popups, rules, auto-print, everything now prints through the shared hub.

**Security:** the token is always required; enabling sharing with an empty token auto-generates a random one. Traffic never leaves your LAN. Remote callers never see the full token (`/share` masks it to `****`).

**Queue failover (shared queue):** add **peer hubs** (Options → Sharing, one per line: `http://192.168.1.30:9235|TOKEN2`). If a job fails here after its retries, the hub **forwards the PDF to the first peer that accepts** — the job shows as `forwarded` here and prints there. Jobs received from a peer are never re-forwarded (no loops).

**Queue mode:** failed jobs are **never dropped** — they stay in the list with the error and an attempt counter, auto-retried up to `retry_max` times with a growing delay, and can be requeued with **Retry** or removed with **Clear failed / completed / all**.

---

## The HTTP API (any language, any tool)

```bash
# list printers
curl -H "X-PrintHub-Token: PrintHub-2024" http://127.0.0.1:9235/printers

# print a PDF from a URL (silent)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"pdf_url":"https://example.com/invoice.pdf","title":"Invoice 42"}'

# print a thermal receipt
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"text":"|center|MY SHOP\nItem 1      10.00\nTOTAL        10.00","paper":"thermal"}'

# pause / resume / clear the queue
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" http://127.0.0.1:9235/queue/pause

# v1.7.0: share the hub on the LAN (then paste the connect code into other PCs)
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"enabled":true}' http://127.0.0.1:9235/share

# v1.7.0: retry a failed job / clear history scopes
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" http://127.0.0.1:9235/jobs/12/retry
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"scope":"failed"}' http://127.0.0.1:9235/jobs/clear

# v1.7.0: raw binary PDF with fit scaling (no base64)
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/pdf" \
  --data-binary @report.pdf "http://127.0.0.1:9235/print?title=Report&fit=noscale"
```

Full reference: [`docs/API.md`](docs/API.md) · Browser API: [`docs/EXTENSION-API.md`](docs/EXTENSION-API.md)

---

## Configuration

Settings live in **`~/.printhub/config.json`** (the extension Options → Sharing page and the tray menu write the same file). Environment variables still override it:

| Environment variable | Default | Meaning |
|---|---|---|
| `PRINTHUB_TOKEN` | `PrintHub-2024` | API token (header `X-PrintHub-Token`) |
| `PRINTHUB_PORT` | `9235` | HTTP port |
| `PRINTHUB_HOST` | `127.0.0.1` | Bind address — `0.0.0.0` shares with the whole LAN |
| `PRINTHUB_PRINTER` | *(OS default)* | Force a specific printer |
| `PRINTHUB_FILE_DIR` | `~/Downloads/PrintHub` | Where `destination:"file"` PDFs are saved |
| `PRINTHUB_DATA` | `~/.printhub` | Data folder (SQLite history + job files + config.json) |

**config.json keys:** `host`, `port`, `token`, `auto_retry` (true), `retry_max` (3), `retry_interval` (60 s, grows per attempt), `forward_on_fail` (true), `peers` ([]), `retention_days` (7 — finished job PDF files are cleaned; history rows stay forever).

**CLI:** `python hub/printhub.py serve | testprint [a4|thermal] | printers | history [n] | reprint <id> | queue | share [on\|off] | doctor | help`

---

## Privacy & security

- **No data collection.** There is no telemetry, no account, no analytics.
- **Localhost by default.** The hub binds to `127.0.0.1` unless you explicitly enable Sharing.
- **Token-protected.** Every endpoint (except `/health`) requires the token, compared in constant time. Remote `/share` calls never see the full token.
- **Open source, MIT.** Audit every line — the whole hub is one readable Python file.

## Requirements

- Python 3.8+ (no pip packages)
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) (free, installer offers it via winget)
- **Linux/macOS:** CUPS (`cups-client`)
- Optional: Chrome/Chromium/Edge — used only for *page* printing (HTML → PDF); PDF/image/text printing works without it

## Changelog

- **v1.7.0 — Network & Queue Edition:** one-click LAN sharing with connect-code pairing + token protection; shared-queue failover to peer hubs; unlimited job history with Retry / Clear failed / Clear completed / Clear all; auto-retry with backoff; site block/unblock (popup + right-click + Options); "Close tab after auto-print" now OFF by default; raw binary PDF upload from the extension; thread-local SQLite + WAL, event-driven worker, printer cache, job-file cleanup, `fit` scaling param; **AdvMedi by Bit Dream IT** branding.
- **v1.6.0 — (folded into v1.7.0):** performance & control release.
- **v1.5.0:** tray icon identity, visible Startup-app auto-run, PrintHubPro.exe process name, double-start guard.
- **v1.4.0:** standalone Windows Setup.exe with bundled Python runtime.
- **v1.3.0:** native installers (NSIS Setup.exe + .deb).
- **v1.2.x:** MotW/Unblock fix, logon-task hardening.
- **v1.1.x:** File destination, managed schema fix, global `printPdfLink` API.

## License

MIT © Bit Dream IT (AdvMedi) — free for personal and commercial use.
