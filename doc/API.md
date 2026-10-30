# PrintHub Pro — Hub HTTP API (v2.3.0)

Base URL: `http://127.0.0.1:9235` (default)

Auth: header `X-PrintHub-Token: <token>`.
- **New installs (v2.0):** the token is a private random value printed at first start and stored in `config.json`. All **mutating endpoints (POST)** require the **header** — query/body tokens are rejected there. Every **GET** endpoint (v2.0.2, one uniform rule) additionally accepts `?token=` for plain browser navigation — `GET /dashboard?token=…`, `GET /audit?token=…`, `GET /jobs?token=…`, `GET /stats?token=…`, `GET /jobs/{id}/file?token=…`, `GET /export/*.csv?token=…` — because browsers cannot send headers when following a link. A leaked GET URL can therefore only *read* data, never print or change settings.
- **Old installs:** keep working exactly as before (header, `?token=` query or JSON `"token"` field all accepted) and raise `default_token_warning: true` in `/health` until the token is rotated.
- **IP lockout (fixed in v2.0.1):** 10 wrong tokens from one **remote** IP locks it for 5 minutes (HTTP 429). The loopback IP `127.0.0.1`/`::1` is **never locked by default** (`lockout_exempt_loopback: true`) — every Chrome window/profile shares that one IP, so a stale token in one window must not lock out the dashboard, tray and extension of all the others. Failures only count inside a sliding `lockout_minutes` window and any successful auth clears the counter immediately. Every 401 answer carries an actionable hint (and points out the old default token `PrintHub-2024` specifically when it is used). Browsers opening any GET link (`/dashboard`, `/audit`, `/stats`, …) with a wrong token get a readable HTML fix-it page instead of raw JSON (v2.0.2: extended from the dashboard to every GET endpoint); API clients keep the JSON error.

All responses are JSON with an `"ok"` field. The API is CORS-open with
`Access-Control-Allow-Private-Network: true`. When `allowed_origins` is set in
config.json, only listed origins (glob, e.g. `*.htncr.org`) and browser
extensions are served; everything else gets **403**.

---

## GET /health *(no token)*

```json
{
  "ok": true, "app": "PrintHub Pro", "version": "2.0.0",
  "branding": "PrintHub Pro - Version 2.0.0 - by Bitdream IT - MIT license - 100% local - no cloud, no tracking",
  "os": "windows", "default_printer": "HP LaserJet Pro",
  "sumatra_found": true, "browser_found": true,
  "paused": false, "pending": 0, "jobs_today": 12,
  "file_dir": "C:\\Users\\me\\Downloads\\PrintHub",
  "token_set": true,
  "default_token_warning": false,
  "token_header_only": true,
  "held": 0, "success_rate": 97.4, "printers_ready": 2,
  "audit": true, "v2": true
}
```

---

## GET /printers

```json
{ "ok": true,
  "printers": [
    {"name": "HP LaserJet Pro", "is_default": true,  "status": "ready",  "is_group": false},
    {"name": "XP-80C Thermal",  "is_default": false, "status": "paper-out","is_group": false},
    {"name": "Front Desk",      "is_default": false, "status": "group",  "is_group": true,
     "members": ["HP LaserJet Pro", "XP-80C Thermal"]}
  ],
  "default": "HP LaserJet Pro", "groups": {"Front Desk": ["HP LaserJet Pro", "XP-80C Thermal"]} }
```

Status values: `ready` · `offline` · `paper-out` · `error` · `unknown` · `group`.

### GET /printers/{name}/capabilities *(v2.1)*

What THIS printer + backend actually supports — drives the extension UI
and API clients so only supported options are offered. Windows reports the
SumatraPDF capability map (driver-level extras noted); Linux queries CUPS
`lpoptions -p <name> -l` live:

```json
{ "ok": true, "backend": "cups", "printer": "XP-80C",
  "pages": {"type": "ranges", "odd_even": true},
  "copies": {"min": 1, "max": 50},
  "duplex": ["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
  "per_sheet": [1, 2, 4, 6, 9, 16],
  "quality": {"presets": ["draft", "normal", "high"], "dpi": [300, 600, 1200]},
  "paper": ["A4", "A5", "Letter"], "tray": ["Tray1"], "raw_options": { } }
```

`quality.dpi` is `null` on Windows — the print driver decides the real
DPI there (both spellings are still accepted and logged per job).

---

## POST /print

One payload source is required. **Common fields:**

| Field | Default | Meaning |
|---|---|---|
| `title` | `"document"` | Shown in history/dashboard |
| `printer` | *(OS default)* | Printer name, or a **printer group** name; `"__file__"` = save as PDF |
| `copies` | `1` | 1–50 |
| `source` | `"api"` | Free tag recorded in history + audit |
| `destination` | `"printer"` | `"file"` = save as PDF, no paper |
| `queue` | `true` | `false` = **Queue Mode OFF / instant print** for this job (prints immediately, bypasses FIFO) |
| `mode` | — | **v2.3:** friendlier alias — `"instant"` / `"direct"` / `"now"` = `queue:false`, `"queue"` = FIFO. A given `queue` value always wins |
| `priority` | `5` | v2.0: `1` (urgent) … `9` (low); urgent jobs jump the FIFO |
| `pages` | — | v2.0: page range `"1-3,5"`; **v2.1: also `"odd"` / `"even"`** (CUPS `page-set` / SumatraPDF) |
| `duplex` | — | v2.0: `simplex` \| `duplex` \| `long` \| `short` |
| `paper_size` | — | v2.0: e.g. `A4`, `Letter` (CUPS media / Sumatra paper=) |
| `tray` | — | v2.0: e.g. `Tray2` (CUPS only — SumatraPDF cannot select trays) |
| `per_sheet` | `1` | v2.1: n-up printing — `2` `4` `6` `9` `16` (CUPS `number-up`; SumatraPDF logs it as unsupported) |
| `quality` | — | **v2.2: BOTH spellings** — presets `draft` \| `normal` \| `high` (aliases `best`/`fine` → `high`) → CUPS `print-quality=3/4/5`; **or DPI**: `"600"`, `"600dpi"` → CUPS `printer-resolution=600dpi`. Windows: accepted + recorded, driver decides |
| `dpi` | — | v2.2: explicit DPI number (72–2400) — same effect as `quality:"600dpi"` |
| `scale_pct` | — | v2.1: 25–400 % scale for hub-rendered jobs (text/HTML) |
| `margin_mm` | — | v2.1: page margins in mm for hub-rendered jobs |
| `orientation` | — | v2.1: `portrait` \| `landscape` |
| `profile` | — | v2.0: name of a profile from config.json `profiles` (request values win) |
| `run_at` | — | v2.0: schedule — ISO datetime `"2026-10-27T09:00:00"` or relative `+5m` `+2h` `+30s` |
| `reason` | — | v2.0: free text recorded in the audit log |
| `watermark` | `false` | v2.0: stamp a diagonal `REPRINT`-style watermark on the PDF (`watermark_text` overrides the text) |
| `dedupe` | `true` | v2.0: `false` disables duplicate blocking for this request |
| `lang` | — | v2.0: `"escpos"` or `"zpl"` → **raw printing** (with `text`) |
| `cut` / `drawer` | `true` / `false` | v2.0: ESC/POS builder extras |

**Payload sources:**

| Source field | Meaning | Notes |
|---|---|---|
| `pdf_base64` | Raw PDF bytes, base64 | Must start with `%PDF-` |
| `pdf_url` | Download a PDF | **v2.0 SSRF guard:** `file://`, `ftp://` and private/local hosts are blocked unless in `pdf_url_allowed_hosts` |
| `image_base64` | JPEG bytes, base64 | Wrapped to PDF (`paper: a4|thermal`, `landscape`) |
| `html` | HTML string | Rendered by headless Chrome/Edge |
| `page_url` | URL of a page | Rendered by headless Chrome/Edge |
| `text` | Plain text | Thermal receipt or A4 page (`paper`) |
| `raw_base64` | v2.0: pre-built ESC/POS or ZPL bytes | Sent to the printer **raw** (no driver) |
| `text` + `lang` | v2.0: `"escpos"` builds a receipt, `"zpl"` passes through | ESC/POS markers below |

**ESC/POS text markers:** `#big ` double size · `|center|` centered · `|right|` right · `|cut|` paper cut · `|drawer|` open cash drawer · `|barcode:123456|` CODE128 · `|qr:any text|` QR code.

**Raw binary uploads** (no base64):
- `POST /print` with `Content-Type: application/pdf` → PDF bytes
- `POST /print?kind=raw` (or `?lang=escpos|zpl`) with `Content-Type: application/octet-stream` → raw printer bytes

```bash
curl -X POST "http://127.0.0.1:9235/print?title=Retail-42&printer=XP-58&token=$TOKEN" \
  --data-binary @receipt.bin -H "Content-Type: application/octet-stream"
```

**Response (printer destination):**

```json
{ "ok": true, "job_id": 17, "kind": "a4", "copies": 1,
  "destination": "printer", "queue_mode": "on", "instant": false,
  "auto_queued": false, "duplicate": false, "priority": 1, "status": "queued" }
```

`status` (v2.2.1) is the truthful initial state of the job:
`queued` (FIFO), `printing` (queue mode OFF), `scheduled` (run_at set)
or `saved` (destination file). Poll `GET /jobs/{id}` for the outcome —
a 200 from `/print` means **accepted**, not paper in the tray.

**v2.3 instant-print auto-queue fallback:** queue mode OFF + the target
printer is `offline` / `paper-out` / `error` → the job is auto-queued
instead of fired into a doomed direct print: the response says
`"instant": true, "auto_queued": true, "status": "queued"` and the
message *"printer not active - job auto-queued (prints when it is
ready)"*. The job then follows the normal queue rules (with the default
`hold_offline` it waits for the printer and prints automatically).
Raw/ESC-POS jobs skip the check. Disable the fallback with
`POST /config {"instant_auto_queue": false}` (default `true`, also in
`/health`). Audit event: `print.auto_queued`.

`duplicate: true` means an identical job was already accepted within
`dedupe_minutes` — the response points at the original `job_id`.
For `run_at` requests: `"status": "scheduled"`, `"scheduled_for": "..."`.
For `destination:"file"`: `"status": "saved"`, `"file": "<path>"`.

---

## Job endpoints

| Endpoint | Meaning |
|---|---|
| `GET /jobs?limit=100[&status=queued]` | History. Statuses: `queued` `printing` `printed` `failed` `canceled` `saved` **`held`** **`scheduled`** **`dead`** **`forwarded`** |
| `GET /jobs/{id}` | **v2.2.1:** one job with full fields (`status`, `error`, `held_reason`, `duration_ms` …) — for polling |
| `GET /jobs/{id}/file` | Download the stored document |
| `POST /jobs/{id}/reprint` | Reprint. Body: `reason` (audit; required when `reprint_reason_required`), `watermark: true`, `printer` override |
| `POST /jobs/{id}/cancel` | Cancel queued / kill printing / release scheduled+held |
| `POST /jobs/{id}/retry` | **v2.0:** requeue a `failed`/`dead`/`canceled`/`held` job — body `{"printer":"OtherName"}` retries on **another printer** |
| `POST /jobs/{id}/priority` | **v2.0:** body `{"priority": 1..9}` |
| `POST /jobs/{id}/print-now` | **v2.2.1:** print THIS job immediately, bypassing the global pause AND the printer-status hold. Works on `queued`/`held`/`scheduled`/`failed`/`dead`/`saved` jobs. Response `{"ok":true,"status":"printing"}` |

### Troubleshooting: jobs stay queued, nothing prints

The hub accepts the job (extension shows OK) but no paper — walk down
this list; each cause now tells you it is happening:

1. **Hub queue paused** — `GET /queue` → `"paused": true`. The popup
   shows `PAUSED` in red; resume with the popup Pause/Resume button or
   `POST /queue/resume`.
2. **Printer-status hold** — `GET /jobs/{id}` → `status: "held"` with
   `held_reason`. Windows often reports a network printer as offline
   (stuck *Use Printer Offline*). Fixes: popup **Print now** (bypass),
   dashboard **Printer status hold** toggle (`hold_offline: false`),
   or fix the Windows printer tile.
3. **Print backend error** — `status: "failed"`, `error` holds the real
   message (e.g. SumatraPDF missing, CUPS `lp` not installed). The
   extension shows a red `!` badge + notification within ~1 minute.
4. **Worker crashed** — fixed in v2.2.1: the loop is exception-proof
   and a watchdog respawns the thread (`worker.restarted` in
   `GET /audit`). `/health` shows `worker_alive`.
5. **Duplicate blocked** — the response says `duplicate: true` and
   points at the original job.
6. **Wrong printer name** — the job prints to a name that does not
   exist → `failed` with the backend error; check spelling or set the
   printer in the extension rules.

## Queue control

`GET /queue` (adds `"held": n`) · `POST /queue/pause` · `POST /queue/resume` · `POST /queue/clear`

### POST /queue/shift *(v2.1)* — move jobs to ANOTHER PC

```json
{ "target": "http://192.168.0.60:9235",   // other hub's LAN URL
  "target_token": "PEER-TOKEN",            // optional if target is in peer_hubs
  "scope": "all" }                          // or "job" + "ids": [12,13]
```

Waiting (`queued`/`held`/`scheduled`/`failed`/`dead`/`retrying`) jobs are
re-uploaded to the target hub, marked **`forwarded`** here and audited.
The UI equivalents: extension Options → **LAN / PCs** tab (whole queue) and
**Shift to PC** buttons in the Queue tab; dashboard LAN card. Response:
`{"ok":true,"target":…,"shifted":[12,13],"shifted_count":2,"errors":[]}`.

---

## Security endpoints

| Endpoint | Meaning |
|---|---|
| `POST /token/rotate` | Generate a fresh random token; old one stops immediately. Response: `{"ok": true, "token": "..."}` |
| `GET /config` | Redacted view of config.json |
| `POST /config` | Update any config key at runtime (persisted): `allowed_origins`, `printer_groups`, `profiles`, `pdf_url_allowed_hosts`, `max_retries`, `retry_base_seconds`, `dedupe_minutes`, `hold_offline`, `audit_enabled`, `reprint_watermark`, `reprint_reason_required`, `max_auth_failures`, `lockout_minutes`, `lockout_exempt_loopback`, `peer_hubs`, `peer_forwarding`, `log_max_mb`, `log_backups`. The token is rejected here — use `/token/rotate`. |
| `GET /peers` | Health-probe every configured peer hub — `{"url","alive","version","latency_ms"}`; dead peers are skipped by forwarding |

## Audit, exports, dashboard, diagnostics

| Endpoint | Meaning |
|---|---|
| `GET /stats` | Success rate (7 d), queue size, jobs today, printers, uptime |
| `GET /audit?limit=50[&event=print.failed]` | Audit entries |
| `GET /audit.csv` · `GET /export/audit.csv` | Audit CSV download |
| `GET /export/history.csv` | Full job history CSV (id, site, hash, priority, attempts…) |
| `GET /dashboard?token=…` | Built-in web dashboard — success rate, queue size, live queue with cancel + **Shift**, **LAN sharing card**, printers, recent jobs with retry/reprint, audit trail, token rotation |
| `GET /docs?token=…` | **v2.2: the built-in user guide** — every option, LAN sharing how-to, queue shift, Laravel recipes, Bangla receipts. Served by the hub so the docs can never go missing |
| `GET /diagnostics` | Support bundle JSON: versions, config (token masked), DB stats, printers, peers, log tail |
| `GET /debug` | **v2.3: WHY is nothing printing?** — `problems` (auto-verdict list, each entry `{level, check, message, fix}`), `queue` + `worker_alive` + `paused`, `printers`, `recent_jobs` (last 15 with error/held_reason), `client_reports` (browser/JS + desktop-tool error reports), `debug` flag. `?token=` works like every GET |
| `POST /debug/report` | **v2.3:** clients report errors — body `{"source":"extension","level":"error","message":"…","context":{…},"job_id":12}` (context/job_id optional; level error\|warn\|info). Stored (last 100, persisted in `debug_reports.json`), audited `debug.report`, shown in `/debug`. The Chrome extension sends these automatically while **Debug mode** is ON (Options → Settings, or the dashboard Debug card) |

```jsonc
// GET /debug?token=… (trimmed)
{
  "ok": true, "version": "2.3.0", "debug": true,
  "worker_alive": true, "paused": false, "instant_auto_queue": true,
  "queue": { "pending": 2, "held": 1 },
  "printers": [ { "name": "XP-80C", "status": "ready" } ],
  "problems": [
    { "level": "warn", "check": "held jobs",
      "message": "1 job(s) HELD - printer 'XP-80C' is offline - …",
      "fix": "use Print now on the job, or switch off 'Printer status hold'" },
    { "level": "info", "check": "debug off",
      "message": "Debug mode is OFF - browser/extension (JS) errors are NOT being collected",
      "fix": "turn Debug ON (dashboard Debug card, or extension Options > Settings)" }
  ],
  "client_reports": [
    { "ts": "2026-10-30T10:00:00", "source": "extension", "level": "error",
      "message": "hub POST /print -> HTTP 500: lp failed",
      "context": "report-a.pdf", "job_id": 41 }
  ]
}
```

## Misc

`GET /autostart` · `POST /autostart {"enabled":bool}` · `GET /testprint?kind=a4|thermal`

---

## config.json reference

Lives in the data dir (`~/.printhub/config.json`). See the README table for
every key with defaults. **Defaults keep 1.x behaviour** except where the
feature itself is the point (`max_retries: 2`, `dedupe_minutes: 5`,
`hold_offline: true`). New installs additionally get `token_header_only: true`.
v2.3 keys: `debug` (`false` — Debug mode: verbose `[DEBUG]` logs +
client error collection for `GET /debug`) and `instant_auto_queue`
(`true` — instant print + printer not active → job auto-queued).
Auth-related keys: `max_auth_failures` (10), `lockout_minutes` (5) and
`lockout_exempt_loopback` (`true` = never lock 127.0.0.1/::1 — set `false`
to lock loopback too, the strict v2.0.0 behaviour).

## CLI

```
python printhub.py serve|testprint|printers|history|reprint <id> [reason]
python printhub.py queue|doctor|token|token-rotate|diagnostics
python printhub.py service-install|service-remove|service-status|update-check|help
```

## Peer hubs (multi-PC fallback)

```json
"peer_hubs": [ {"url": "http://192.168.1.50:9235", "token": "PEER-TOKEN"} ],
"peer_forwarding": true
```

When the local printer is unreachable and `peer_forwarding` is on, the job is
handed to the first **alive** peer that actually has that printer (dead peers
are skipped). The job is recorded locally as `forwarded` with the peer URL.
