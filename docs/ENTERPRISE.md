# AdvPrint Pro — Enterprise Deployment Guide

**AdvPrint Pro (Advanced Printer) by Bit Dream IT — Innovative Healthcare Solutions**
Version 2.6.2 — 100% local, no cloud, no tracking. MIT licensed.

---

## 1. What "enterprise edition" means here

* **Per-user install with zero elevation** — `AdvPrint-Pro-Setup-2.6.2.exe` installs to
  `%LOCALAPPDATA%\AdvPrintPro`, needs no admin and no UAC. Works on locked-down PCs.
* **Silent install** — `AdvPrint-Pro-Setup-2.6.2.exe /S` (NSIS silent flag), scriptable via
  Intune / GPO / SCCM / any RMM: push per user.
* **Headless service mode** — run the hub as a real Windows service (`services.msc` →
  *AdvPrint Pro Service*) for print-server PCs; systemd service on Linux servers.
* **Central policy (managed storage)** — force extension settings on every PC.
* **Audit + compliance** — audit trail, reprint reasons, reprint watermark, CSV exports.
* **Hardening** — token header-only mode, allowed origins allow-list, lockout policy
  (your own PC is never locked out; foreign IPs are), optional LAN sharing.

---

## 2. Rollout recipes

### 2.1 Windows — per-user silent rollout

```
AdvPrint-Pro-Setup-2.6.2.exe /S
```

The setup registers the visible Startup app **AdvPrint Pro** and starts the hub.
Detection rule for RMM: registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro`
`DisplayVersion` = `2.6.2`.

### 2.2 Windows — print-server mode (service)

```
python advprint.py service-install      (one UAC prompt)
python advprint.py service-status
python advprint.py service-remove
```

The service runs **before logon** with no tray; everything is logged to
`%USERPROFILE%\.advprint\hub.log`. If the normal Startup app also runs, the second
instance exits gracefully (port guard).

### 2.3 Linux (Debian/Ubuntu/Mint)

```
sudo apt install ./advprint-pro_2.6.2_all.deb
advprint-start
sudo /opt/advprint/install/install-unix.sh --service   # headless server mode
```

Desktops: `install-unix.sh` without sudo installs a **systemd --user** service
(auto-run at login). CLI: `advprint`, `advprint-start`, `advprint-tool`.

### 2.4 Browser extension (every client PC)

1. `chrome://extensions` → Developer mode → **Load unpacked** → the `extension/` folder
   (on Windows also installed to `%LOCALAPPDATA%\AdvPrintPro\extension`).
2. Options → Settings → set Hub URL (local `http://127.0.0.1:9235` or the print-server's
   LAN URL) → **Detect token** → Connect.

---

## 3. Central policy (managed storage)

Deploy the JSON below as Chrome **managed storage** for the extension (via
`ExtensionSettings` policy / `chrome.storage.managed`). Managed values **override**
user settings; `rules` fully replaces local rules.

```json
{
  "hubUrl":            "http://127.0.0.1:9235",
  "token":             "SET-PER-SITE",
  "defaultPrinter":    "FrontDesk-Laser",
  "enabled":           true,
  "queueMode":         true,
  "retryOffline":      true,
  "lang":              "en",
  "hookPrint":         true,
  "autoPrintAllPdfs":  true,
  "failFallback":      "none",
  "closeAfterPrint":   true,
  "rules": [
    { "pattern": "*://reports.internal.example/*pdf/*", "type": "glob",
      "action": "pdf", "auto": true, "enabled": true, "printer": "" }
  ]
}
```

Fields: `hubUrl`, `token`, `defaultPrinter`, `enabled`, `queueMode`, `retryOffline`,
`lang` (auto/en/bn), `hookPrint`, `autoPrintAllPdfs`, `failFallback` (tab/none),
`closeAfterPrint`, `rules[]` (`pattern`, `type` glob|regex, `title`, `printer`,
`action` auto|pdf|page, `auto`, `enabled`).

## 4. Hub hardening checklist (config.json / Options → Hub settings)

| Goal | Setting |
| --- | --- |
| Only your web app may print | `allowed_origins: ["https://app.internal.example"]` |
| Strict API auth | `token_header_only: true` + rotated token everywhere |
| Rotate tokens regularly | `python advprint.py token-rotate` / `POST /token/rotate` |
| Lock out wrong foreign IPs fast | `max_auth_failures: 5`, `lockout_minutes: 15` |
| Owner PC can never self-lock | keep `lockout_exempt_loopback: true` |
| One shared print PC | `share_lan: true` ONLY there + firewall TCP 9235 |
| Compliance trail | `audit_enabled: true`, `reprint_reason_required: true`, `reprint_watermark: true` |
| Support bundles without secrets | `/diagnostics` (token redacted), Debug → Copy report |

## 5. Health, monitoring, testing

* `GET /health` — no token needed: version, queue, printers ready, worker alive (perfect for uptime probes).
* `POST /livetest` (token) — the full A-to-Z self-test as JSON; CLI: `python advprint.py livetest`.
* Dashboard → **Full self-test** / **Send test print & watch live** with verdict.
* Audit + history CSV for SIEM/backup: `http://127.0.0.1:9235/audit.csv`, `/export/history.csv`.

## 6. Upgrade & rollback

* Run the new setup over the old one — data folder (`.advprint`) and settings are preserved;
  old `PrintHub Pro` auto-runs/services/registry entries are removed automatically.
* First run after a pre-2.6 upgrade migrates `~/.printhub` → `~/.advprint` (old folder kept).
* Rollback = uninstall + run the older setup; data folder untouched.

---
*AdvPrint Pro is 100% local: no cloud, no telemetry, no accounts. The only network
listener is the hub (loopback by default; LAN only when you enable it, token required).*
