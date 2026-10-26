# PrintHub Pro — Print from Any Web Page to Any Printer

**Silent. Local. Open source. No subscription.**

PrintHub Pro prints from any web page to **any printer** — thermal, receipt, label, or standard — with **no print dialog and no confirmation**. It is a free, 100%-local, MIT-licensed alternative to paid products like Ultraprint Hub: a small **desktop hub** (single Python file, zero pip dependencies) plus a **Chrome extension** that talk to each other on `localhost` only.

```
Web page ──► Chrome extension ──► PrintHub Pro hub (localhost:9235) ──► ANY printer
             (right-click /       • queue: pause · resume · cancel      thermal · receipt
              popup / API /       • history: last 100 jobs (SQLite)     label · A4 · POS
              auto rules)         • screenshot & HTML → PDF              80mm roll
```

**Downloads / updates:** everything ships on the GitHub Releases page —
**https://github.com/bitdreamit/PrintHub-Pro/releases/latest**
Update anytime: run `PrintHub Tool` → **8: Check for updates**, or click
**Check for update** in the extension Options → About tab. Installing a
new Setup.exe over the old one keeps all settings and history.

---

## What's new in v1.7.2

- **PrintHub Tool** — a friendly numbered menu (Start Menu shortcut) that handles
  **install, uninstall, start, stop, service add / service remove, auto-run on/off,
  test page, history and GitHub update check**. No command-line skills needed.
- **Optional real Windows service** — "PrintHub Pro Service" appears in
  `services.msc` (installer optional section, or Tool menu item 5/6).
- **Silent install / uninstall** — `PrintHub-Pro-Setup-1.7.2.exe /S` and
  `uninstall.exe /S` for scripted deployments.
- **Extension master switch** — "PrintHub enabled" ON/OFF in the popup and Options.
  OFF = zero activity (no printing, no auto-print, no `window.print()` hook, no page
  API, gray **OFF** badge) without uninstalling.
- **Queue Mode ON/OFF** — ON (default): jobs print in FIFO order and Pause works.
  OFF: every job prints immediately (`queue:false`), skipping the line.
- **Tabbed options page** — **Queue | History | Settings | About** tabs; opens on
  **Queue** automatically when jobs are pending, otherwise on Settings; live queue
  auto-refresh every 3 s.
- **GitHub update check** built into the Tool, the hub CLI (`printhub.py update-check`)
  and the extension About tab.
- Simplified package layout: only **doc/**, **extension/** and **tool/**.

---

## Package layout (this zip)

```
PrintHub-Pro-1.7.2/
├── README.md            ← you are here
├── doc/                 guides + API reference
│   ├── PrintHub-Pro-Full-Guide.pdf / .html   (step-by-step manual)
│   ├── API.md           full HTTP reference
│   ├── EXTENSION-API.md window.printhub + rules + GPO
│   └── PRIVACY-POLICY.md
├── extension/           Chrome/Edge/Brave extension (load unpacked)
└── tool/
    ├── windows/         PrintHub-Pro-Setup-1.7.2.exe  ← the installer
    │                    (+ portable\ variant in the FULL zip)
    └── unix/            install-unix.sh · uninstall-unix.sh · .deb · hub source
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
| **Print queue** | Pause, resume, cancel — live, and the queue survives hub restarts. Queue Mode OFF = instant printing, no line. |
| **Job history** | Last 100 jobs with status, printer, timing — reprint any job in one click. |
| **One-stop Tool** | Start / stop / status / service add-remove / auto-run / update / uninstall in one numbered menu. |
| **Enterprise ready** | Managed-storage schema (`managed.json`) for GPO/MDM deployment of settings and locked rules. |
| **Private by design** | No data collection, no external servers, no accounts. Hub binds to `127.0.0.1` and is token-protected. |

**Extra features beyond the paid original:** auto-print PDF URLs with login cookies (Laravel signed routes work), silent printing of raw text to 80 mm thermal rolls, **save-as-PDF File destination for every job type**, reprint-from-history via HTTP and CLI, `doctor` self-diagnosis, optional LAN mode for shared office printers.

---

## Quick start (3 steps)

### 1. Install the hub (one-time, zero questions)

**Windows — recommended:**

```
tool\windows\PrintHub-Pro-Setup-1.7.2.exe
```

**STANDALONE installer — Python is included inside** (bundled 3.11 runtime +
`PrintHubPro.exe`): copies everything to `%LOCALAPPDATA%\PrintHubPro`,
registers **auto-run as a visible Startup app**, starts the hub, adds Start
Menu shortcuts (**Start PrintHub Pro · PrintHub Tool · Uninstall**) and a real
**Add/Remove Programs uninstaller**. The hub shows a **"PrintHub Pro" tray
icon** (right-click = status page, test page, pause, auto-run on/off, exit).
No admin, no Python install, never shows as "python".

- **Silent install:** `PrintHub-Pro-Setup-1.7.2.exe /S` (defaults: auto-run on, no service)
- **Optional Windows service:** tick *Install as Windows Service (advanced)* during
  setup, or run **PrintHub Tool → 5** later (asks UAC once). It then appears in
  `services.msc` as **PrintHub Pro Service** and can be started/stopped there.
- Unsigned EXE → SmartScreen may ask once: *More info → Run anyway*.
  If a downloaded EXE ever reports "corrupted": re-download, compare the SHA-256
  in `SHA256SUMS-1.7.2.txt`, and unblock with right-click → Properties → Unblock.

**Linux (Debian/Ubuntu/Mint):**

```
sudo apt install ./tool/unix/printhub-pro_1.7.2_all.deb
```

installs to `/opt/printhub`, ships a **systemd user service** (auto-run at login,
restarts on crash) + XDG autostart fallback. CLI: `printhub doctor`.

**macOS / other Linux:** `bash tool/unix/install-unix.sh` (auto-run via
LaunchAgent / systemd --user / XDG, no sudo needed).

**Windows portable (no install):** FULL zip → `tool\windows\portable\install-windows.bat`
(uses the bundled runtime, no system Python needed).

| | stop auto-run + hub | keep / remove print data |
|---|---|---|
| **Windows** | PrintHub Tool → 10 (uninstall) or Settings → Apps → PrintHub Pro → Uninstall | data in `%USERPROFILE%\.printhub` |
| **Linux / macOS** | `bash tool/unix/uninstall-unix.sh` | data in `~/.printhub` |

The hub starts on `http://127.0.0.1:9235` with default token `PrintHub-2024`.

### 2. Load the extension

1. Open `chrome://extensions` in Chrome / Edge / Brave
2. Enable **Developer mode** (top-right)
3. Click **Load unpacked** → select the `extension/` folder

### 3. Connect & print

1. Click the PrintHub icon → the popup shows **Connected**
2. Right-click any page → **PrintHub Pro → Print this page**
3. Or open a URL matching a routing rule (the default rule auto-prints `*://www.htncr.org/lab/medical_reports/*`) — it prints with no dialog

Popup switches: **PrintHub enabled** (master on/off) and **Queue mode**
(FIFO queue vs instant print).

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

Scriptable too: `python hub\tool.py status | start | stop | testprint |
history [n] | autorun on|off | service-install | service-remove |
service-status | update-check | uninstall`

---

## The HTTP API (any language, any tool)

```bash
# list printers
curl -H "X-PrintHub-Token: PrintHub-2024" http://127.0.0.1:9235/printers

# print a PDF from a URL (silent, queued)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"pdf_url":"https://example.com/invoice.pdf","title":"Invoice 42"}'

# print IMMEDIATELY (skip the queue line - Queue Mode OFF for this job)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"text":"HELLO","queue":false}'

# print a thermal receipt
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"text":"|center|MY SHOP\nItem 1      10.00\nTOTAL        10.00","paper":"thermal"}'

# pause / resume / clear the queue
curl -X POST -H "X-PrintHub-Token: PrintHub-2024" http://127.0.0.1:9235/queue/pause
```

Full reference: [`doc/API.md`](doc/API.md) · Browser API: [`doc/EXTENSION-API.md`](doc/EXTENSION-API.md)

---

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `PRINTHUB_TOKEN` | `PrintHub-2024` | API token (header `X-PrintHub-Token`) |
| `PRINTHUB_PORT` | `9235` | HTTP port |
| `PRINTHUB_HOST` | `127.0.0.1` | Bind address — set `0.0.0.0` for office LAN sharing |
| `PRINTHUB_PRINTER` | *(OS default)* | Force a specific printer |
| `PRINTHUB_FILE_DIR` | `~/Downloads/PrintHub` | Where `destination:"file"` PDFs are saved |
| `PRINTHUB_DATA` | `~/.printhub` | Data folder (SQLite history + job files) |

**CLI:** `python hub/printhub.py serve | testprint [a4|thermal] | printers | history [n] | reprint <id> | queue | doctor | service-install | service-remove | service-status | update-check | help`

**LAN mode:** set `PRINTHUB_HOST=0.0.0.0` and point the extension (Options → Settings → Hub URL) at your PC's LAN IP, e.g. `http://192.168.1.20:9235`. Token is always required.

---

## Privacy & security

- **No data collection.** There is no telemetry, no account, no analytics.
- **Localhost only.** The hub binds to `127.0.0.1` unless you explicitly enable LAN mode.
- **Token-protected.** Every endpoint (except `/health`) requires the token, compared in constant time.
- **Open source, MIT.** Audit every line — the whole hub is one readable Python file.

## Requirements

- Python 3.8+ (no pip packages) — the Windows Setup EXE bundles its own runtime
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) (free, installer offers it via winget)
- **Linux/macOS:** CUPS (`cups-client`)
- Optional: Chrome/Chromium/Edge — used only for *page* printing (HTML → PDF); PDF/image/text printing works without it

## License

MIT © Bitdream IT — free for personal and commercial use.
