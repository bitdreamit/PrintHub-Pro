# Changelog — PrintHub Pro

## v2.5.0 — the merge release (2026-10-30)

### Fixed
- **Feature regression in 2.4.0/2.4.1** — those builds were assembled from a
  stale 1.5.0 tree (dev-machine reset) and silently dropped the v2.0–v2.3
  feature set. v2.5.0 is built on the REAL 2.3.0 source (recovered from
  github.com/bitdreamit/PrintHub-Pro) and re-unites everything: LAN sharing
  (`share_lan` 0.0.0.0 bind + `/peers` + peer forwarding), ESC/POS + ZPL raw
  printing (cut/drawer/barcode/QR, `escpos_codepage`, Bangla auto-routed via
  headless Chrome), scheduled prints (`run_at` + promotion), printer groups,
  profiles, priority queue, dedupe, exponential retry, `/capabilities`,
  `/stats`, `/diagnostics`, in-hub `/docs` guide, Windows service wrapper
  (`service_main.py` + PrintHubProService.cs) and `tool.py` control menu.
- **SumatraPDF under Windows services** — new all-users profile scan
  (`C:\Users\*\AppData\Local\SumatraPDF`) + HKLM registry views: found even
  when the hub's service account is not the logged-in user (user name stays
  dynamic). `/debug` now reports `sumatra_path` + the full `sumatra_searched`
  list; `sumatra_path` is a first-class config key (dashboard Settings box,
  POST /config, PRINTHUB_SUMATRA env).
- **Folder churn ended at the git level** — the package tree is now 1:1 with
  the repo (`tool/`, `extension/`, `docs/`, `tests/`, `pytest.ini`,
  `.gitignore`); full.zip extracts over the repo working copy cleanly.
  `tests/conftest.py` path fixed (hub lives at `tool/windows/portable/hub`).

### Added
- Virtual-PDF direct save ported onto the 2.3.0 worker (`_save_virtual_pdf`,
  status `saved`, `print.saved` audit) — "Microsoft Print to PDF" works
  without a physical printer and without SumatraPDF.
- `POST /jobs/{id}/release` + `POST /jobs/release_all` (print-now aliases)
  and `POST /client/report` (alias of `/debug/report`).
- Dashboard "Live debug & test tool" panel: Send test print & watch live
  (verdict REAL PRINTER HIT / SAVED / HELD / FAILED+reason), Release ALL
  held jobs, Settings → sumatra_path; token injected via `@@TOKEN@@`.
- `{"instant": true}` accepted as alias of `mode:"instant"`.
- Repo parity files restored into the package: `i18n.js` (Bangla UI strings),
  service bats/ps1, PrintHub-Tool.bat, RELEASE-NOTES-*.md, HOW-TO-*, sample
  report, store assets.

### Tests
- pytest: 78/78 (repo suite; version anchors updated to 2.5.0, layout-aware
  manifest check). Smoke: 64/64 (fake-lp end-to-end incl. virtual-PDF save,
  release_all, dashboard token injection, sumatra_path round-trip).

## v2.4.1 — packaging & docs release (2026-10-30)

### Fixed
- **Folder churn between releases** ("why does every folder change?") —
  packaging is now a frozen contract: every zip (full.zip, portable zip,
  extension zip) unpacks to the SAME root folder `PrintHubPro/` with no
  version in the name. Updates = extract over the old folder. The v1.x loose
  layout and the per-version root folders (`PrintHubPro-2.4.0/…`) are gone
  for good; old folders are safe to delete (data lives in
  `%USERPROFILE%\.printhub`, never inside the program folder).
- Version strings synced in every surface: hub `VERSION`, extension
  `manifest.json` + `window.printhub.version` + popup header, installer
  metadata (NSIS `DisplayVersion` / `FileVersion` / `ProductVersion`), deb
  `control`, smoke-test version anchor.

### Added
- `docs/EXTENSION-TEST.md` — step-by-step extension tool test (hub → token →
  debug mode → popup test page → live dashboard verdict → physical proof),
  status-meaning table, troubleshooting table (symptom → where → fix), pass
  checklist. Answers "did the REAL printer get hit?" with evidence.
- `docs/FOLDER-MAP.md` — why layouts differed before, the frozen layout with
  a one-line purpose for every folder/file, where user data lives, and the
  2-minute migration from old per-version folders.
- START-HERE.txt rewritten around the folder promise + the live test.

## v2.4.0 — debug & reliability release (2026-10-30)

### Fixed
- **SumatraPDF "not found" although installed** — detection is rebuilt and
  fully dynamic: per-user install folder `%LOCALAPPDATA%\SumatraPDF` (resolves
  to the CURRENT Windows user — the user name is never hardcoded), both
  Program Files folders, Windows registry (App Paths + Uninstall for HKCU and
  HKLM, 32/64-bit views), `PATH`, and a folder scan fallback. A manual
  override (`sumatra_path` in Settings / `config.json` / `PRINTHUB_SUMATRA`
  env var) always wins. `/debug` and `doctor` print the exact list of paths
  searched, so a miss is instantly explainable.
- **Stale detection / restart required** — SumatraPDF and printer status are
  re-checked fresh on EVERY job. Installing SumatraPDF takes effect on the
  next print; no hub restart. Failed jobs auto-retry 2× (60 s apart) with
  `retry N/2 in 60s: <reason>` shown in history, then `failed` with the
  reason.

### Added
- **Live debug & test tool**: `GET /dashboard?token=...` — send a real test
  print to any printer and watch every status change live with a final
  verdict (REAL PRINTER HIT / saved as PDF / held / failed+fix hint);
  Release held jobs, pause/resume, settings toggles, problems list.
- **`GET /debug`** — full diagnostics JSON (same shape as the dashboard):
  version, uptime, worker alive, paused, hold_offline, instant_auto_queue,
  masked token, printers with ready/offline status, default printer,
  sumatra_found + sumatra_path + sumatra_searched[], browser found,
  db stats (by_status, queue_size, jobs_today, success_rate, printed_7d,
  failed_7d), recent_jobs, problems[] with fixes, client_reports[].
- **`GET /audit`** — persistent audit trail in SQLite (survives restarts):
  print.submitted (actor/site/ip/doc_hash), print.held, print.requeued,
  print.saved, auth.failed (attempt counter), config.changed,
  queue.paused/resumed.
- **Instant / direct print mode** — `POST /print` with `instant:true` or
  `mode:"instant"` (extension toggle: "Instant / direct print mode") jumps
  the queue (priority dispatch). If no printer is ready, the job
  auto-falls back to the normal queue (`instant_auto_queue`, default on) —
  the job is never lost.
- **Held jobs** — with `hold_offline` (default on) a job for an offline
  printer is parked as `held` with a reason; a watcher auto-releases it
  when the printer is ready again; `POST /jobs/{id}/release` ("Print now")
  and `POST /jobs/release_all` force it.
- **Virtual PDF printers** — targeting "Microsoft Print to PDF" now saves
  the PDF directly to the Downloads/PrintHub folder (status `saved`, path in
  dashboard/`/debug`) instead of popping a Save-As dialog. Printing works
  even with no physical printer installed.
- **Debug on/off switch** — dashboard Settings card + extension options.
  When on, the extension reports browser-side JS errors via
  `POST /client/report`; `/debug` lists them next to desktop-side errors.
  Toggling is audit-logged (`config.changed: debug`).
- **`GET/POST /config`** — live settings (debug, hold_offline,
  instant_auto_queue, token_header_only, sumatra_path, file_dir, printer,
  token) persisted to `<data dir>/config.json`.
- **`GET /jobs/{id}`** — single-job fetch (used by the live watcher).

### Notes
- Auth rules unchanged: GET accepts `?token=` or header; POST is
  header-only (`token_header_only`). Loopback is exempt from lockout;
  remote IPs: 10 wrong-token attempts / 5 min → 5 min lock.
- Extension bumped to 2.4.0 (instant + debug toggles, error reporting,
  live-dashboard shortcuts). Reload the unpacked extension after update.
