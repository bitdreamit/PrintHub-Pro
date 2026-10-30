# PrintHub Pro — Extension Tool Test Guide (v2.4.1)

How to test the whole chain end-to-end and **prove the real printer was hit** —
not just "the extension shows OK". Total time: about 5 minutes.

---

## 0. What you need

| Thing | Where |
|---|---|
| Hub running | Tray icon "PrintHub Pro", or `python printhub.py serve` |
| Extension loaded | `chrome://extensions` → PrintHub Pro → enabled, version **2.4.1** |
| Token | Default `PrintHub-2024` (or your own — must match hub `config.json`) |
| A printer | Physical printer, OR "Microsoft Print to PDF" if you have no printer today |

---

## 1. The 5-minute test

### Step 1 — Hub is alive
Open in any browser:

```
http://127.0.0.1:9235/health
```

Expect JSON with `"ok": true` and `"version": "2.4.1"`.
If this fails, the hub is not running — start it first. Nothing else matters until this works.

### Step 2 — Extension connects with the RIGHT token
Open the extension **Options** (right-click the P icon → Options, or popup → Options):

1. **Hub URL**: `http://127.0.0.1:9235`
2. **Token**: your token (default `PrintHub-2024`)
3. Click **Connect**.

Expect: `CONNECTED - v2.4.1 - Windows` in green.

> Wrong token = the #1 cause of "extension shows OK but nothing prints".
> The hub audit log records every wrong attempt: `auth.failed "wrong token"`.
> If the hub and the extension token ever differ, every job is rejected.

### Step 3 — Turn Debug mode ON
Same Options page → **Behavior** section → tick **"Debug mode (find problems early)"**
→ **Save settings**.

Debug mode makes the browser side report every JS error to the hub, so the
dashboard shows BOTH sides of the story (page JS + desktop tool) in one place.

### Step 4 — Send the first job from the extension
Click the **P** icon in the toolbar → click **Test page**.

Expect:
- Popup shows the job in **Recent jobs** with status **printed** (green).
- The toolbar badge turns green OK.

### Step 5 — The REAL printer check (live dashboard)
This is the step that answers *"did the real printer get hit or not"*:

1. Options page → **Live debug & test tool** → **Open live debug dashboard**
   (or open `http://127.0.0.1:9235/dashboard?token=PrintHub-2024`).
2. Click **Send test print & watch live**.
3. The dashboard shows every step live — job queued → dispatching → printer
   command — and ends with a final verdict:
   - **REAL PRINTER HIT** — the OS accepted the job for that printer.
   - **SAVED to Downloads\PrintHub** — virtual PDF printer (no paper needed).
   - **HELD** — target printer is offline; job waits and auto-prints when the
     printer is ready. Press **Print now** to force.
   - **FAILED + reason** — exact cause and the fix (e.g. "SumatraPDF not
     found" + the paths that were searched).

### Step 6 — Physical proof (choose what matches your setup)
| Setup | Proof the printer was really hit |
|---|---|
| Physical printer | Paper comes out. Also: Windows Settings → Bluetooth & devices → Printers & scanners → your printer → **Open print queue** — the job appears there during printing. |
| Microsoft Print to PDF | A new PDF file appears in **Downloads\PrintHub** named like `2026-10-30_16-45_test-page.pdf`. |
| OneNote | OneNote opens / the page is inserted into your notebook. |

---

## 2. Test from YOUR site (Laravel / htncr.com)

The page-side API `window.printhub.printPdfLink(url, title, opts)` is injected
on every page. On your lab report page:

```js
printPdfLink('/lab/medical_reports/pdf/198809', 'Lab report', {fallback:false});
```

What to expect, in order:

1. Toast **"Sending to printer..."** on the page.
2. Extension background fetches the URL (with your login session —
   login-protected URLs work), verifies `%PDF-` magic, sends it to the hub.
3. Toast **"Sent to printer (job N)"** — N is the hub job id.
4. Dashboard → Job N appears; ends **printed** (or **held**/**failed** with reason).
5. In the hub audit log (`/audit`) you will see `print.submitted` with the
   site origin and the document hash.

If the button stops after "Sending to printer..." → open the dashboard; with
debug mode ON the browser-side error is shown there too (e.g. PDF fetch
returned HTML login page instead of a PDF).

---

## 3. Job status meanings

| Status | Meaning | Action |
|---|---|---|
| `queued` | In the queue, waiting for the worker | none |
| `printing` | Being sent to the printer right now | none |
| `printed` | OS accepted the job — paper/output | done |
| `saved` | Virtual PDF printer — file written to Downloads\PrintHub | done |
| `held` | Printer offline — job kept, auto-released when ready | wait, or **Print now** |
| `failed` | Could not print — reason stored | read reason in dashboard |
| `canceled` | You canceled it | reprint from history |

---

## 4. Troubleshooting — symptom → where → fix

| Symptom | Look at | Fix |
|---|---|---|
| Extension popup red "hub not running" | `/health` | Start hub (tray icon / `python printhub.py serve`) |
| Extension OK but nothing prints | `/audit` → `auth.failed` | Token mismatch — set the same token in Options and hub config |
| `SumatraPDF not found` although installed | `/debug` → `sumatra_path`, `sumatra_searched` | v2.4.1 finds `C:\Users\<any-user>\AppData\Local\SumatraPDF` automatically. Still failing? Dashboard → Settings → paste full path to `SumatraPDF.exe` |
| Jobs stuck as `held` | Dashboard held list | Printer offline — plug it / choose another printer / **Print now** / turn off "hold offline printer jobs" in Settings |
| `retry 2/2 in 60s` | Dashboard job detail | Transient printer error — it retries twice, then fails with the reason |
| Nothing anywhere, no job id | Dashboard with debug mode ON | Browser-side JS error is reported there (fetch failed, PDF not a PDF, blocked by page) |
| Queue says paused | Popup queue bar / `/debug` → `queue.paused` | Click **Resume** (popup) or dashboard toggle |
| Wrong printer got the job | `/debug` → `default_printer` | Options → Printing → Default printer, or set printer per rule/call |

**One command dump for a support ticket** — copy these three into a message:

```
http://127.0.0.1:9235/debug?token=PrintHub-2024
http://127.0.0.1:9235/audit?token=PrintHub-2024&limit=50
http://127.0.0.1:9235/health
```

---

## 5. Pass checklist

- [ ] `/health` → `ok: true`, version 2.4.1
- [ ] Options → Connect → `CONNECTED - v2.4.1`
- [ ] Popup → **Test page** → job status `printed`
- [ ] Dashboard → **Send test print & watch live** → verdict **REAL PRINTER HIT** (or **SAVED** with the file present in Downloads\PrintHub)
- [ ] Your Laravel page print → toast + job id + `printed` in dashboard
- [ ] `/audit` shows `print.submitted` with your site origin

All boxes ticked = the chain page → extension → hub → printer is proven working.
