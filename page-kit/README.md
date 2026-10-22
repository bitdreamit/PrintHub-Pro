# PrintHub Pro — Page Integration Kit (fixed silent-print button)

Fixed, tested version of the lab app's print-button snippet, plus a demo page
you can open right now to see the whole chain working.

**Files**

| File | What it is |
|------|------------|
| `lab-report-print.js` | The fixed snippet — drop-in replacement for the old block |
| `demo.html` | Standalone demo: open it, press the button, watch the log |
| `README.md` | This file |

---

## 1. What was wrong in the old snippet

1. **Print button could get permanently stuck.** The `printing` guard was only
   reset inside `fr.onload`. But `onload` never fires when the network dies or
   when the URL answers with `Content-Disposition: attachment` (Laravel
   `->download()`) — after one such failure the button did nothing until F5.
2. **Double-click printed two copies.** The guard did not cover the hub path
   (`printPdfLink`), so a fast double-click queued two jobs.
3. **Blank / early prints from the PDF viewer.** Chrome's built-in PDF viewer
   inside an iframe is a cross-origin document; the old code printed it after
   only ~450 ms, before it finished rendering. Firefox cannot print it at all.
4. **No feedback.** A silent print looks like nothing happened, so staff
   clicked again — more duplicate copies.

## 2. The print chain (unchanged, now reliable)

```
button click
   │
   ├─ printPdfLink(url, 'Lab report', {fallback:false})   ← extension injected
   │     browser fetches the URL WITH session cookies (login-protected URLs OK)
   │     → hub 127.0.0.1:9235 queues the job → silent print, no dialog
   │
   ├─ on any failure → hidden iframe → browser print dialog (path 2)
   │
   └─ iframe print fails / 20 s watchdog → window.open(url) (path 3)
```

Toast messages tell staff which path ran; `job N` in the toast matches the job
id in the popup's *Recent jobs* list and in `hub.log`.

## 3. How to install in your Laravel app

1. Copy `lab-report-print.js` to `public/js/`.
2. Load it once in the layout (before `</body>`):

   ```blade
   <script src="{{ asset('js/lab-report-print.js') }}"></script>
   ```

3. Keep your existing markup — the ids are unchanged:

   ```html
   <form id="print_form" action="{{ route('reports.print') }}" method="GET">
       {{ $hiddenFields }}
   </form>
   <button type="button" id="print_selected_btn">Print selected</button>
   ```

   Use `type="button"` so the browser never submits/reloads the page.
4. Done. No other changes needed.

### Make the iframe fallback bulletproof: stream PDFs INLINE

The hub path works with any disposition, but path 2 (dialog) needs the browser
to *display* the PDF inside the iframe. If your controller uses
`Destination::DOWNLOAD` (or `->download()`), switch it to inline:

```php
// mPDF
$mpdf->Output('lab-report.pdf', \Mpdf\Output\Destination::INLINE);

// or full control:
return response($pdfBytes, 200, [
    'Content-Type'        => 'application/pdf',
    'Content-Disposition' => 'inline; filename="lab-report.pdf"',
]);
```

With `inline`, even a machine without the hub still gets a working print dialog.

## 4. Verify it

1. Open `demo.html` in Chrome (double-click, file:// is fine).
2. Put one of your real report URLs into the URL box (while logged in).
3. Press **Print selected**:
   - toast *“Sending to printer…”* → *“Sent to printer (job N)”* = silent path;
     paper should come out.
   - toast *“Print dialog opening…”* = fallback; the dialog shows the report.
4. Console shows `[PrintHub] queued: {job_id…}` on success and
   `[PrintHub] silent print unavailable -> …` with the reason on fallback.

Cross-checks: tray icon → *Open status page*, popup → *Recent jobs*, or
`GET http://127.0.0.1:9235/jobs?token=PrintHub-2024`.

## 5. Reading the failures

| Symptom | Cause | Fix |
|---|---|---|
| Toast says *dialog* every time, console: “extension not loaded” | Extension disabled / page opened in another browser | Enable it in `chrome://extensions` |
| Console: “URL did not return a PDF - got HTML? login expired?” | Session expired in that tab; hub got the login page | Log in again, retry |
| Dialog opens but shows a login/error page | Same — auth expired, or wrong `form.action` | Re-login / check the route |
| “Sent to printer” but no paper | Hub-side problem (printer off, wrong default) | Tray icon → *Print test page*; check `hub.log` |
| Two copies printed | Rapid double-clicks in the OLD snippet | Fixed here; upgrade the page code |

## 6. Requirements

- PrintHub Pro extension **v1.2.0 or newer** (the `printPdfLink` global exists
  since v1.1.6; cookie-authenticated PDF fetch since v1.1.x). Current release:
  **v1.5.0**.
- Hub running (tray icon) for silent mode; everything else degrades gracefully.
- Works on http/https pages in Chrome/Edge. No server-side dependency.
