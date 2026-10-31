# Release Notes — AdvPrint Pro v2.6.5 (2026-10-31)

**AdvPrint Pro (Advanced Printer) — by Bit Dream IT - Innovative Healthcare Solutions**
MIT license — 100% local — no cloud, no tracking.

## Why v2.6.5 exists

An intermediate build had accidentally been started from the old **1.5.0**
tree instead of the real v2.6.4 source. It shipped with **fewer features**
(missing tray icon, missing Control-Tool menu items, reduced extension) and
users were right to refuse the update.

**v2.6.5 is built directly from the published v2.6.4 source tag — the full
v2.6.4 feature set is kept 1:1 and nothing was reduced.**

## Feature parity check (v2.6.4 → v2.6.5)

| Area | v2.6.4 baseline | v2.6.5 |
|---|---|---|
| Control Tool menu | [0]–[13] (start/stop/status, test page, service install/remove, start-at-logon, update check, history, uninstall, LIVE TEST, dashboard, Diagnose & fix) | all 13 kept |
| Tray icon | self-drawn themed menu, dashboard/test/pause/autostart/exit | kept + verified wiring |
| Endpoints | /health /audit /debug /diagnostics /dashboard /token/current /config /jobs /print … | all kept |
| Extension tabs | Queue · History · Settings · Debug · LAN · About + Hub settings (advanced) | all 6 kept + UI refresh |
| Power switches | master switch, queue mode, retry-offline, alarms, managed policy | all kept |
| Printing engines | SumatraPDF (Windows) + CUPS lp (unix), ESC/POS + ZPL, browser HTML→PDF | all kept |
| Queue features | priority, dedupe, scheduled, held/offline auto-release, groups, profiles | all kept |
| Security | random token, header-only, origin allowlist, lockout, rotate, peers | all kept + token_hint |
| Installers | NSIS per-machine + portable FULL zip + unix scripts/systemd | all kept |

## Fixed

1. **Missing `import glob`** — the SumatraPDF folder scans and the
   **all-users profile scan** (`C:\Users\*\AppData\Local\SumatraPDF\SumatraPDF.exe`)
   raised `NameError` that `find_sumatra()` swallowed as "not found".
   Service-mode PDF printing had silently lost its last-resort detection
   (same Windows-only bug family as the v2.6.4 `winreg` fix).
2. **SumatraPDF per-user detection widened** — new candidate
   `%LOCALAPPDATA%\Programs\SumatraPDF\SumatraPDF.exe` for the newest
   installers, on top of per-user `%LOCALAPPDATA%`, both Program Files,
   registry (HKCU+HKLM, both views), `PATH`, folder scan and the
   all-users profile scan. **User names are never hardcoded** — every
   Windows account resolves dynamically.
3. **Windows service can no longer hang in START_PENDING** — the service
   imports + binds synchronously with SCM checkpoints every 2 s and
   reports RUNNING only after a real bind. If the port is busy (the normal
   Startup copy already owns 9235) or anything fails, the service reports
   **STOPPED immediately** with the reason in
   `ProgramData\AdvPrintPro\hub.log`.
4. **GitHub URLs corrected** to `github.com/bitdreamit/AdvPrint-Pro`
   (hub update check, extension manifest homepage, Options update check +
   releases link, all docs).

## Improved

- **/health now carries `token_hint`** (last 4 characters of the active
  token) — verify the token pasted in the extension matches the hub in
  seconds (end of the 401 / auth.failed mystery). The token itself never
  appears in /health.
- **Extension Options UI refresh** — live hub status pill in the header
  (online / token problem / starting / offline), tab-bar hover states,
  and saving with an EMPTY token field keeps the stored token instead of
  quietly writing the legacy default.
- **Control Tool [13] Diagnose & fix unblocks more** — the install folder
  PLUS per-user locations (legacy `%LOCALAPPDATA%\AdvPrintPro`, per-user
  SumatraPDF folders). A blocked per-user exe can no longer hold print
  jobs in "queued" silently. Step [1/5] also prints the detected
  SumatraPDF path up front.

## Removed

- Stale prebuilt binaries (the 2.6.4 Setup exe + .deb) from the package —
  every release should ship binaries that match its own version. Build
  fresh ones from `installer/setup.nsi` (NSIS 3) when needed.

## Upgrade notes

- Extract over the old folder (or run the Setup exe once built), then:
  `AdvPrint-Tool.bat` → **[13]** once (unblock) → **[1] Start**.
- Chrome → `chrome://extensions` → AdvPrint Pro → **Reload**.
- Verify: Tool → **[11] LIVE TEST (A-to-Z)**, or the tray icon →
  Open dashboard → *Send test print & watch live*.
- Token check: `/health` → `token_hint` must match the last 4 characters
  of the token in extension Options → Settings.
