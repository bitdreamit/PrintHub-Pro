# AdvPrint Pro v1.7.2 — "Simple Install & Control"

**Release date:** 2026-10-26 · **Author:** Bit Dream IT · **License:** MIT
**Tag:** `v1.7.2`

This release makes AdvPrint Pro installable, controllable and updatable by
**non-technical users**, with one installer, one tool and one simplified package.

---

## New in v1.7.2

### 1. AdvPrint Tool — one menu does everything
A Start Menu shortcut ("AdvPrint Tool") opens a numbered console menu:

```
[1] Start AdvPrint            [5] Windows service - install
[2] Stop AdvPrint             [6] Windows service - remove
[3] Status                    [7] Start at logon: ON / OFF
[4] Print test page           [8] Check for updates (GitHub)
[9] Show recent jobs         [10] Uninstall / remove
[0] Exit
```

No command line needed for install / uninstall / service add / service remove /
auto-run / updates any more. Scriptable too: `python hub\tool.py <command>`.

### 2. Real Windows service (optional)
- Tick **"Install as Windows Service (advanced)"** in the installer — or use
  AdvPrint Tool → 5 later (a UAC prompt appears once).
- The service appears in **services.msc** as **"AdvPrint Pro Service"**
  (short name `AdvPrint`), auto-start at boot, failure auto-restart.
- Removing = Tool → 6, `python advprint.py service-remove`, or just uninstall.
- The default remains the normal **Startup app + tray icon** (per-user, correct
  default printer); the service is the optional headless mode.

### 3. Silent install / uninstall
- Install: `AdvPrint-Pro-Setup-1.7.2.exe /S` (defaults: auto-run on, no service)
- Uninstall: `%LOCALAPPDATA%\AdvPrintPro\uninstall.exe /S`

### 4. Extension master switch — AdvPrint enabled ON/OFF
- Popup switch (and Settings tab): **AdvPrint enabled**.
- OFF = the extension stops completely: no printing, no auto-print, no
  `window.print()` hook, no page API, no context menu — a gray **OFF** badge
  shows on the toolbar icon. The browser behaves 100% natively without
  uninstalling anything.

### 5. Queue Mode ON/OFF
- Popup switch (and Settings tab): **Queue mode**.
- **ON** (default): jobs go through the hub FIFO queue — ordered, Pause/Resume works.
- **OFF**: each job prints **immediately** (`queue:false` to the hub) — nothing
  waits behind earlier jobs, Pause has no effect. Also available per-call in the
  HTTP API: `POST /print` with `"queue": false`.

### 6. Tabbed options page
- Tabs: **Queue | History | Settings | About**.
- Opens automatically on **Queue** when jobs are pending/active, otherwise on **Settings**.
- Live queue auto-refreshes every 3 s (status, pending count, cancel buttons, tab badge).
- **About** tab: version, GitHub links, **Check for update** button.

### 7. Update through GitHub
- Official releases page: `https://github.com/bitdreamit/AdvPrint-Pro/releases/latest`
- Checkers built in: AdvPrint Tool → 8, hub CLI `python advprint.py update-check`,
  extension Options → About → **Check for update**.
- Install a new Setup.exe **over** the old one — settings and history are kept.

### 8. Simplified package layout
The zip now contains only three folders — nothing else to puzzle over:

```
AdvPrint-Pro-1.7.2/
├── doc/           Full-Guide PDF + API.md + EXTENSION-API.md + privacy
├── extension/     Chrome/Edge/Brave extension (load unpacked)
└── tool/
    ├── windows/   AdvPrint-Pro-Setup-1.7.2.exe   ← most users need ONLY this
    └── unix/      .deb + install-unix.sh + hub source
```
(The FULL zip additionally carries `tool/windows/portable/` with the bundled
Python runtime for no-install use.)

### 9. Fixed
- **Setup EXE "corrupted / abort" reports** were traced to damaged downloads
  (truncated transfer). Every artifact now ships with a published SHA-256
  (`SHA256SUMS-1.7.2.txt`), the EXE download is integrity-verified end-to-end,
  and the installer detects the problem itself with a clear message.

---

## Assets

| File | For |
|---|---|
| `AdvPrint-Pro-Setup-1.7.2.exe` | Windows — recommended (9.1 MB) |
| `AdvPrint-Pro-1.7.2.zip` | All platforms, simple layout (9.4 MB) |
| `AdvPrint-Pro-v1.7.2-FULL.zip` | + portable Windows runtime (20.1 MB) |
| `AdvPrint-Pro-Extension-v1.7.2.zip` | Browser extension only (34 KB) |
| `advprint-pro_1.7.2_all.deb` | Debian/Ubuntu/Mint (29 KB) |
| `SHA256SUMS-1.7.2.txt` | Verify all of the above |

**Setup-1.7.2.exe SHA-256:**
`9936020edd965b9746ce44d3d4000f62ebd34e3eef8f76e950d1aca615a966eb`

---

## Upgrade notes

- v1.5.0 or older → run the new Setup.exe over it; the old Startup shortcut,
  tray and settings carry over automatically.
- If you used v1.7.1 (unreleased externally), just install 1.7.2 over it.
- Chrome Web Store kit for the store listing: `Chrome-WebStore-Kit/AdvPrint-Pro-ChromeWebStore-1.7.2.zip`.
