# PrintHub Pro — Hub HTTP API

Base URL: `http://127.0.0.1:9235` (default)
Auth: header `X-PrintHub-Token: <token>` (default `PrintHub-2024`), or `?token=` query, or `"token"` JSON field.
All responses are JSON with an `"ok"` field. The API is CORS-open with `Access-Control-Allow-Private-Network: true`, so browser JS from any site can call it.

---

## GET /health *(no token)*

```json
{
  "ok": true,
  "app": "PrintHub Pro",
  "version": "1.0.0",
  "os": "windows",
  "default_printer": "HP LaserJet Pro",
  "sumatra_found": true,
  "browser_found": true,
  "paused": false,
  "pending": 0,
  "jobs_today": 12,
  "token_set": true
}
```

---

## GET /printers

```json
{ "ok": true,
  "printers": [ {"name": "HP LaserJet Pro", "is_default": true},
                {"name": "XP-80C Thermal", "is_default": false} ],
  "default": "HP LaserJet Pro" }
```

---

## POST /print

One of the payload sources is required. Common optional fields: `title`, `printer` (empty = default), `copies` (1–50), `source` (free tag shown in history), `destination` (`"printer"` default or `"file"` to save as PDF without printing).

| Source field | Meaning | Notes |
|---|---|---|
| `pdf_base64` | Raw PDF bytes, base64 | Must start with `%PDF-` |
| `pdf_url` | Download a PDF | Max 25 MB, must be a real PDF |
| `image_base64` | JPEG bytes, base64 | Wrapped to PDF (`paper: a4|thermal`, `landscape`) |
| `html` | HTML string | Rendered by headless Chrome/Edge |
| `page_url` | URL of a page | Rendered by headless Chrome/Edge |
| `text` | Plain text | `paper:"thermal"` → 80 mm roll; `paper:"a4"` → A4. Markers: `#big `, `|center| ` |

```bash
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"pdf_base64":"JVBERi0...","title":"Invoice 42","printer":"HP LaserJet Pro","copies":2}'
```

Response: `{"ok": true, "job_id": 17, "kind": "a4", "copies": 2, "destination": "printer", "message": "queued to printer"}`

### Raw binary PDF — no base64 (fastest path)

POST the PDF bytes **directly** with `Content-Type: application/pdf` — no base64 encode, no JSON, no +33% size overhead. Parameters ride the **query string** (`title`, `printer`, `copies`, `destination`, `paper`, `token` also accepted as query param).

```bash
curl -X POST "http://127.0.0.1:9235/print?title=Lab%20report&copies=1" \
  -H "X-PrintHub-Token: PrintHub-2024" \
  -H "Content-Type: application/pdf" \
  --data-binary @report.pdf
```

**Laravel (mPDF, zero encoding):**

```php
Http::withHeaders(['X-PrintHub-Token' => 'PrintHub-2024'])
    ->withBody($pdf->output(), 'application/pdf')
    ->post('http://127.0.0.1:9235/print?title=' . urlencode('Lab report 197253'));
```

**Laravel multipart (`Http::attach`)** — file field `pdf`/`file`, text fields become parameters:

```php
Http::withHeaders(['X-PrintHub-Token' => 'PrintHub-2024'])
    ->attach('pdf', $pdf->output(), 'report.pdf')
    ->post('http://127.0.0.1:9235/print', ['title' => 'Lab report 197253']);
```

**No bytes at all — `pdf_url`:** the hub downloads the PDF itself (max 25 MB). For login-protected Laravel routes use a signed URL: `URL::temporarySignedRoute('reports.pdf', now()->addMinutes(5), [...])`.

Raw limits: max 25 MB, body must start with `%PDF-`; anything else → `400`.

### Destination "file" — save as PDF, no paper

Add `"destination": "file"` (or set `printer` to the extension alias `"__file__"`) and the hub **saves the rendered PDF into a folder instead of printing** — no dialog, no paper, no queue. Default folder: `~/Downloads/PrintHub` (override with `PRINTHUB_FILE_DIR`).

```bash
curl -X POST http://127.0.0.1:9235/print \
  -H "X-PrintHub-Token: PrintHub-2024" -H "Content-Type: application/json" \
  -d '{"text":"Daily summary","paper":"a4","title":"summary","destination":"file"}'
```

Response: `{"ok": true, "job_id": 18, "kind": "a4", "destination": "file", "status": "saved", "file": "/home/me/Downloads/PrintHub/summary-20240101-120000.pdf", "url_path": "/jobs/18/file", "message": "saved as PDF file - no paper used"}`

The job appears in history with status `saved`; download it any time via `GET /jobs/18/file`, or print it later with `POST /jobs/18/reprint` (goes to the OS default printer).

Errors: `400` bad payload · `401` bad token · `500` render failure (html/page).

---

## Queue control

| Endpoint | Effect |
|---|---|
| `GET /queue` | `{"ok":true,"paused":false,"pending":2,"current":{...job...}}` |
| `POST /queue/pause` | Worker stops taking jobs (already-running job finishes) |
| `POST /queue/resume` | Worker continues; queued jobs print in FIFO order |
| `POST /queue/clear` | All `queued` jobs become `canceled` |

The queue is **DB-driven** (SQLite): pending jobs survive hub restarts, and jobs stuck in `printing` after a crash are re-queued at startup.

---

## Jobs & history

| Endpoint | Meaning |
|---|---|
| `GET /jobs?limit=100` | Last N jobs (newest first). Statuses: `queued printing printed saved failed canceled` |
| `GET /jobs/{id}/file` | Download the original PDF of a job |
| `POST /jobs/{id}/reprint` | Queue an exact copy of the job |
| `POST /jobs/{id}/cancel` | Cancel a queued job; if it is printing, the print process is killed |

---

## GET /testprint?kind=a4|thermal

Queue a built-in test page/receipt. No body needed.

---

## CLI equivalents

```
python hub/printhub.py serve          # start (default command)
python hub/printhub.py testprint a4   # test page
python hub/printhub.py printers       # list printers
python hub/printhub.py history 20     # last 20 jobs
python hub/printhub.py reprint 17     # reprint job 17
python hub/printhub.py queue          # paused? pending? current?
python hub/printhub.py doctor         # environment self-check
```

## Browser fallback form

Strict CSP environments can POST `application/x-www-form-urlencoded` with a single field `payload` containing the JSON — same endpoints, same responses.

---

## v1.7.0 — Sharing, queue retry & failover

### GET /share *(token required)*

Current sharing state. The full token/connect code is only returned to **loopback** callers; remote callers see `****`.

```json
{ "ok": true, "sharing": false, "host": "127.0.0.1", "port": 9235,
  "lan_ip": "192.168.1.20", "address": "http://192.168.1.20:9235",
  "token": "PrintHub-2024", "connect_code": "http://192.168.1.20:9235|PrintHub-2024",
  "peers": [], "auto_retry": true, "retry_max": 3, "retry_interval": 60,
  "forward_on_fail": true, "retention_days": 7,
  "config_file": "~/.printhub/config.json" }
```

### POST /share (alias `POST /config`)

One call to enable/disable LAN sharing and tune the queue. Changing `host`/`port` **re-binds the HTTP server live** — no restart, queue and history untouched.

| body field | effect |
|---|---|
| `{"enabled": true}` | bind `0.0.0.0` (all LAN adapters); auto-generates a random token if none is set |
| `{"enabled": false}` | back to localhost-only |
| `{"host": "192.168.1.20"}` | bind that specific IP instead |
| `{"port": 9235}` | change port |
| `{"token": "..."}` / `{"regenerate_token": true}` | set / rotate the token |
| `{"peers": ["http://192.168.1.30:9235|TOKEN2"]}` | failover targets (first accepting peer wins) |
| `{"auto_retry": true, "retry_max": 3, "retry_interval": 60}` | queue retry policy (delay grows per attempt) |
| `{"forward_on_fail": true}` | hand the PDF to a peer hub after the final local failure |
| `{"retention_days": 7}` | delete finished job PDF files older than N days (history rows stay) |

The response always includes the fresh `connect_code` to paste into other PCs' extensions (`http://192.168.x.x:9235|TOKEN`).

**Security:** the token is ALWAYS required. Non-loopback callers get `token: "****"` and an empty `connect_code`.

### POST /jobs/{id}/retry

Requeue a `failed`, `forwarded` or `canceled` job whose file still exists. Returns `{"ok": true, "status": "queued"}`. `409` for finished jobs, `410` when the stored file was cleaned up.

### POST /jobs/clear  `{"scope": "failed" | "completed" | "all"}`

Delete history rows **and** their stored PDF files. `completed` = printed + saved + canceled + forwarded. `all` also cancels any printing/queued jobs. Returns `{"ok": true, "scope": "...", "deleted": n, "files": m}`.

### `fit` print parameter

`POST /print` accepts `fit` (also via query string on raw uploads): `""` auto by kind, `"fit"` always scale to page, `"noscale"` 1:1, `"shrink"` only shrink oversized pages (SumatraPDF `shrinkfit`). The value is stored per job and honored on every attempt/retry.

### Failover forwarding

After the final local failure (auto-retry exhausted) the worker POSTs the stored PDF to each configured peer (`POST peer/print?title=...&source=peer` with `X-PrintHub-Token` of the peer). First `{"ok": true}` wins: the local job becomes `forwarded` with `forwarded_to` set; the peer records a normal job with `source: "peer"`. Jobs arriving from peers are **never re-forwarded** (loop protection).

## v1.7.1 — Windows service (Windows only)

- `GET /health` adds `"service": {"installed": bool, "running": bool}`
  (null off-Windows) and `"service_mode": bool` (this process IS the service).
- `POST /service/install` / `POST /service/remove` (token-gated): the hub writes
  `service\service.json`, pops ONE UAC prompt (PowerShell RunAs), and the elevated
  child compiles `hub/service/PrintHubProService.cs` with the machine's own `csc.exe`,
  registers + starts "PrintHub Pro Service" (auto start, failure recovery 60 s) and
  turns the Startup-app shortcut OFF. Returns `{"ok": bool, "detail": "..."}`.
  Refused with 400 on non-Windows.
- CLI: `python printhub.py service install|remove|status` (self-elevates).
