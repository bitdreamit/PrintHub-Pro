# PrintHub Pro v2.3.0 — "Instant print + /debug: see WHY nothing prints"

Release date: 2026-10-30 · by Bitdream IT · MIT license · 100% local

## Why this release

User request: *"print direct instant print mode where . also instant print mode
when queue off if no printer active it then auto queue. debug api url need like
ip:port/debug it identify why not work js or desktop tool any error to show .
so debug on/off button need in setting so early identify when why where is
problem exist"*

## 1. Instant (direct) print mode — WHERE it is

It is the **Queue mode OFF** switch: toolbar popup → "Queue mode", or
Options → Settings → Queue mode. Every job is handed straight to the
printer the moment it arrives — nothing waits behind earlier jobs and
the Pause button has no effect on it.

API: `POST /print` with `"queue": false`, or the new
`"mode": "instant"` (`direct` / `now` are aliases; `mode: "queue"` =
FIFO). The response now carries `"instant": true` and
`"auto_queued": false|true`.

## 2. Instant + no active printer = auto-queue (never lose a job)

If the printer is **offline / paper-out / error** at the moment an
instant job arrives, the hub does NOT fire a doomed direct print — it
**auto-queues** the job (audit event `print.auto_queued`). With the
default printer-status hold it waits for the printer to come back and
prints automatically. The `/print` answer says the truth:
`"status": "queued"`, `"auto_queued": true`, message
*"printer not active - job auto-queued (prints when it is ready)"*.

Turn the fallback off (old behaviour) with
`POST /config {"instant_auto_queue": false}`. Raw/ESC-POS jobs skip the
check because receipt printers rarely report a usable status.

## 3. GET /debug — one URL answers WHEN / WHY / WHERE

```
http://127.0.0.1:9235/debug?token=YOUR-TOKEN
```

* **problems** — the hub's own verdict list, each entry with a FIX:
  worker dead, queue paused, no printers / none ready, SumatraPDF
  missing (Windows), headless browser missing, held jobs with reason,
  failed/dead jobs with their real error, default-token warning.
* **recent_jobs** — last 15 jobs with status + error + held_reason.
* **queue** — pending/held + the job printing right now.
* **client_reports** — errors reported by the browser extension and
  desktop tools (below).

Same auth as every GET (`?token=` or the header); wrong token → 401.

## 4. POST /debug/report — the browser talks back

```json
{"source": "extension", "level": "error",
 "message": "hub POST /print -> HTTP 500: lp failed",
 "context": {"url": "..."}, "job_id": 41}
```

With **Debug mode ON** the extension reports every error it hits:
network failures, rejected token (401), rate-limit (429), parked jobs,
auto-print failures, JS exceptions in the service worker, and jobs that
ended failed/dead (with the job id). The hub keeps the last 100 reports
in memory AND in `debug_reports.json`, so they survive restarts, and
audits `debug.report`. Any desktop tool can report the same way.

## 5. Debug ON/OFF button in the settings

One switch drives both sides:

* **Extension**: Options → Settings → **Debug mode** — also switches
  the hub's config, and adds a **Debug tab** (state line, problems
  table, client error reports, error-count tab badge, **Send test
  report**, **Copy report**, **Open /debug JSON**). The popup footer
  gained a **Debug** link.
* **Hub dashboard**: new **Debug card** — Enable/Disable button,
  worker/queue state, problem list, client-report count, **Copy
  report** for a bug report you can paste anywhere, toolbar **Debug**
  link to the raw JSON.

While Debug is ON the hub also logs verbose `[DEBUG]` lines (exact
printer command lines, worker picks, instant decisions). OFF (default)
= quiet, normal operation.

## Everything from v2.2.1 and before stays

Exception-proof worker + watchdog, truthful statuses, honest colors,
Print now (bypasses pause + hold), held-jobs banner, print options
(quality presets AND DPI), LAN sharing + queue shift, Bangla receipts,
built-in /docs (now with the Debug chapter, §5c).

## Files

| File | SHA-256 |
|---|---|
| PrintHub-Pro-Setup-2.3.0.exe | 88d5a390922a18b38b5cd97082a977c0062c3b362bd89d6ea4d83277588715c6 |
| PrintHub-Pro-Setup-2.3.0-exe.zip | 99a3865faee14edc0f736ece6593bb37bc5b5eac0038ab099020bbcd26f75bc5 |
| PrintHub-Pro-2.3.0.zip | 7816a325932241690c00b00887fad7d7bfba3920a55286679aebc76f0c923162 |
| PrintHub-Pro-v2.3.0-FULL.zip | 122034bf1ea598f31661934126919d08857ae32c119f1a0473b1af52ba817ee3 |
| PrintHub-Pro-Extension-v2.3.0.zip | df3ab0471a34b753e975ba2cd31989e6e800df47d81e7ae9bfd7bc23c00982cd |
| printhub-pro_2.3.0_all.deb | b584a1b95c248955f647f198542246f3316e4083508fd655cdd9b1a4373a1212 |
| ChromeWebStore-2.3.0.zip | ebb022c41f5884a037bbfab07a94efe275350fc404326177de6d5ad5a49329b8 |

## Test matrix (all green)

pytest 78/78 (13 new v2.3.0 tests) · smoke_test_v230.sh 42/42 (live
hub, fake CUPS: instant→printed, instant+offline→auto-queued, /debug,
/debug/report roundtrip, debug toggle, docs/dashboard) · legacy smoke
75/75 · v2.0.2 smoke 35/35 · options/popup Playwright UI 41/41 ·
node --check ×6 · py_compile ×4.
