# PrintHub Pro — Print from Any Web Page to Any Printer

**Silent. Local. Open source. No subscription.**

PrintHub Pro prints from any web page to **any printer** — thermal, receipt, label, or standard — with **no print dialog and no confirmation**. It is a free, 100%-local, MIT-licensed alternative to paid products like Ultraprint Hub: a small **desktop hub** (single Python file, zero pip dependencies) plus a **Chrome extension** that talk to each other on `localhost` only.

```
Web page ──► Chrome extension ──► PrintHub Pro hub (localhost:9235) ──► ANY printer
             (right-click /       • queue: pause · resume · cancel      thermal · receipt
              popup / API /       • history: last 100 jobs (SQLite)     label · A4 · POS
              auto rules)         • screenshot & HTML → PDF              80mm roll
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
| **Job history** | Last 100 jobs with status, printer, timing — reprint any job in one click. |
| **Enterprise ready** | Managed-storage schema (`managed.json`) for GPO/MDM deployment of settings and locked rules. |
| **Private by design** | No data collection, no external servers, no accounts. Hub binds to `127.0.0.1` and is token-protected. |

**Extra features beyond the paid original:** auto-print PDF URLs with login cookies (Laravel signed routes work), silent printing of raw text to 80 mm thermal rolls, **save-as-PDF File destination for every job type**, reprint-from-history via HTTP and CLI, `doctor` self-diagnosis, optional LAN mode for shared office printers.

> **What's new in v1.5.1 — double-print fix:** the `window.print()` interception hook is now **top-frame only**. Previously it was also injected into hidden iframes, so a page's own iframe-print fallback (e.g. a hidden iframe calling `iframe.print()` when the hub path fails) got hijacked and sent to the hub again — the same report could come out of the printer twice. Iframes now keep the native print dialog, and pages can bypass the hook explicitly via `win.__printhubNativePrint.call(win)`. Page-side hardening (URL dedupe + timeout→history check) ships in the **PrintHub-Pro-Page-Kit**.

---

## Quick start (3 steps)

### 1. Install the hub (one-time, zero questions)

**Easiest — native installers (v1.5.1):**

| | file | what it does |
|---|---|---|
| **Windows** | `PrintHub-Pro-Setup-1.5.1.exe` | **STANDALONE installer — Python is included inside** (bundled 3.11 runtime + `PrintHubPro.exe`): copies everything to `%LOCALAPPDATA%\PrintHubPro`, registers **auto-run as a visible Startup app** (Task Manager → Startup apps → "PrintHub Pro"), starts the hub, adds Start Menu shortcuts + a real **Add/Remove Programs uninstaller**. The hub shows a **"PrintHub Pro" tray icon** (right-click = status page, test page, pause, auto-run on/off, exit). No admin, no Python install, no dialogs, never shows as "python". Note: unsigned EXE → SmartScreen may ask once: *More info → Run anyway*. |
| **Linux (Debian/Ubuntu/Mint)** | `printhub-pro_1.5.1_all.deb` | `sudo apt install ./printhub-pro_1.5.1_all.deb` — installs to `/opt/printhub`, ships a **systemd user service** (auto-run at login, restarts on crash) + XDG autostart fallback. CLI: `printhub doctor`. |
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

Windows notes (v1.5.1): the hub runs as `PrintHubPro.exe` (a renamed
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
```

Full reference: [`docs/API.md`](docs/API.md) · Browser API: [`docs/EXTENSION-API.md`](docs/EXTENSION-API.md)

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

**CLI:** `python hub/printhub.py serve | testprint [a4|thermal] | printers | history [n] | reprint <id> | queue | doctor | help`

**LAN mode:** set `PRINTHUB_HOST=0.0.0.0` and point the extension (Options → Hub URL) at your PC's LAN IP, e.g. `http://192.168.1.20:9235`. Token is always required.

---

## Privacy & security

- **No data collection.** There is no telemetry, no account, no analytics.
- **Localhost only.** The hub binds to `127.0.0.1` unless you explicitly enable LAN mode.
- **Token-protected.** Every endpoint (except `/health`) requires the token, compared in constant time.
- **Open source, MIT.** Audit every line — the whole hub is one readable Python file.

## Requirements

- Python 3.8+ (no pip packages)
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) (free, installer offers it via winget)
- **Linux/macOS:** CUPS (`cups-client`)
- Optional: Chrome/Chromium/Edge — used only for *page* printing (HTML → PDF); PDF/image/text printing works without it

## License

MIT © Bitdream IT — free for personal and commercial use.
