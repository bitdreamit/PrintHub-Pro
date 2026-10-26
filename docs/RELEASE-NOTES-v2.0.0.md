# PrintHub Pro v2.0.0 — "Security, Audit & Production Control"

> PrintHub Pro — Version 2.0.0 · by Bitdream IT · MIT license · 100% local — no cloud, no tracking.

**22 new features across security, printers, queue, audit, extension and repo.**
Old installs, old databases and old connect codes keep working. New settings
live in `config.json` and the Options page; defaults keep the 1.x behaviour.

## Assets

| File | What it is | For |
|---|---|---|
| `PrintHub-Pro-Setup-2.0.0.exe` | Windows installer (Python included) — install / uninstall / optional Windows service / silent `/S` | Windows users |
| `PrintHub-Pro-Setup-2.0.0-exe.zip` | The same EXE wrapped in a ZIP (for hosts that refuse raw `.exe`) | Windows users |
| `PrintHub-Pro-2.0.0.zip` | Main package: `doc/ + extension/ + tool/{windows,unix}` | Everyone |
| `PrintHub-Pro-v2.0.0-FULL.zip` | Main package + portable hub (bundled runtime) + `tests/` + `.github/` + repo hygiene files | Portable / repo users |
| `PrintHub-Pro-Extension-v2.0.0.zip` | Extension only | Manual loads |
| `printhub-pro_2.0.0_all.deb` | Debian package (systemd user service) | Debian/Ubuntu/Mint |
| `SHA256SUMS-2.0.0.txt` | Checksums — verify before installing | Everyone |

## Highlights

**Security**
- New installs get a **private random token** (the shared default `PrintHub-2024` is gone). Old installs keep working and show a *change default token* warning until rotated.
- **Header-only tokens** on new installs (browser-navigation endpoints still accept `?token=`).
- **Allowed origins** (`allowed_origins: ["*.htncr.org"]`) — empty list = allow all, as before.
- **SSRF-guarded `pdf_url`** — `file://`, `ftp://`, private/local IPs blocked (exempt list available).
- **IP lockout** — 10 wrong tokens ⇒ 5 minutes locked.
- **Token rotation** — dashboard button, `POST /token/rotate`, `python printhub.py token-rotate`.

**Printers**
- Live **printer status** (ready / offline / paper-out / error); jobs **hold** while offline and print when it returns.
- **Printer groups + fallback** (`"Front": ["A","B"]`).
- **Raw printing** — ESC/POS (cut, cash drawer, CODE128 barcode, QR) and ZPL.
- **Print profiles** (paper / tray / duplex / copies) + **page ranges** (`"pages": "1-3,5"`).

**Queue**
- **Exponential retry** · **priority** (urgent first) · **duplicate blocking** · **scheduled prints** (`run_at`) · **dead-letter list** with *retry on another printer* · **peer hubs** (dead peers skipped, optional forwarding).

**Audit**
- **Audit log** — who / which site / document hash / printer / time.
- **Reprint reason** (optionally required) + optional **REPRINT watermark**.
- **Log rotation** · **diagnostics export** · **CSV exports** · built-in **web dashboard** (`/dashboard?token=…`).

**Extension**
- Rules: glob **or regex** + page-title filter + per-site on/off.
- **Offline banner + automatic retry** when the hub is unreachable.
- **English + বাংলা (Bangla)** UI.

**Repo**
- **pytest** suite (35 tests) · **GitHub Actions** CI + tag-driven release pipeline · `.gitignore` · `CHANGELOG.md`.

## Upgrade

1. Run `PrintHub-Pro-Setup-2.0.0.exe` over the old install — settings, history and autostart are kept.
2. Old installs: the popup shows a yellow *default token* warning → click **Rotate token** (dashboard) or run `python printhub.py token-rotate`, then paste the new token into the extension Options.
3. Reload the extension (`chrome://extensions` → PrintHub Pro → reload icon).
4. New hub toys: open `http://127.0.0.1:9235/dashboard?token=YOURTOKEN`.

Full changelog: [CHANGELOG.md](https://github.com/bitdreamit/PrintHub-Pro/blob/main/CHANGELOG.md)
