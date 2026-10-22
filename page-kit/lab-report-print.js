/* ═════════════ SILENT PRINT — PrintHub Pro integration (v2) ═════════════
 * Print chain, best path first:
 *   1. PrintHub Pro extension -> local hub  : SILENT, no dialog, session
 *      cookies included (login-protected report URLs work)
 *   2. Hidden iframe -> browser print dialog: works without the hub,
 *      needs the URL to stream the PDF INLINE (not attachment)
 *   3. window.open(url)                     : last resort, user prints there
 *
 * v2 - fixes "the same page prints twice":
 *   - URL DEDUPE: the same URL cannot be sent twice within 25 s, no matter
 *     how many times the button fires or how many copies of an older print
 *     block are still wired to it (old blocks keep their own guard, so the
 *     only safe place to stop duplicates is the URL itself)
 *   - NATIVE PRINT BYPASS: the dialog fallback calls the iframe's
 *     __printhubNativePrint when the extension's print hook is around, so
 *     the fallback can never be hijacked and routed to the hub again
 *     (extension <= 1.5.0 hooked iframes; fixed in extension 1.5.1)
 *   - TIMEOUT -> HISTORY CHECK: if printPdfLink times out (a slow report
 *     generator can easily exceed 20 s while the hub job is still fine),
 *     the hub history is checked first; only when NO matching job exists
 *     does the dialog fallback start - this kills the classic double print
 *     (hub finishes late + dialog prints too)
 *
 * v1 fixes kept: guard always resets (onerror + watchdog), double-fire
 * guard on all paths, PDF-viewer settle beat, toast feedback,
 * DOMContentLoaded-safe binding. Drop-in: same ids (print_form,
 * print_selected_btn, silent_print_frame), same function names. */
(function () {

    var PRINT_TITLE   = 'Lab report';
    var LOAD_TIMEOUT  = 20000;   /* watchdog: src assigned -> must load in 20s */
    var HUB_TIMEOUT   = 20000;   /* printPdfLink relay timeout (ms)           */
    var DEDUPE_MS     = 25000;   /* same URL cannot be sent twice in 25 s     */
    var PRINTED_FRESH = 45000;   /* a 'printed' job counts as sent this long  */

    var printing = false;        /* one print at a time, ALL paths guarded    */
    var lastSent = { key: '', at: 0, job: null };

    /* ---------- tiny toast (self-contained, never breaks printing) ------ */
    function toast(msg) {
        try {
            var el = document.getElementById('printhub_toast');
            if (!el) {
                el = document.createElement('div');
                el.id = 'printhub_toast';
                el.style.cssText =
                    'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);' +
                    'background:#1e293b;color:#fff;padding:10px 18px;border-radius:8px;' +
                    'font:13px/1.4 system-ui,Segoe UI,Arial,sans-serif;z-index:999999;' +
                    'box-shadow:0 6px 20px rgba(0,0,0,.25);pointer-events:none;';
                document.body.appendChild(el);
            }
            el.textContent = msg;
            el.style.display = 'block';
            clearTimeout(el.__t);
            el.__t = setTimeout(function () { el.style.display = 'none'; }, 4000);
        } catch (e) { /* toast is cosmetic - ignore every failure */ }
    }

    /* ---------- build the GET url from the form (+ cache buster) -------- */
    function buildPrintUrl() {
        var form = document.getElementById('print_form');
        if (!form) return null;
        return form.action + '?' +
            new URLSearchParams(new FormData(form)).toString() +
            '&_=' + Date.now();
    }

    /* URL WITHOUT the cache buster - two clicks produce different _= values,
     * so the dedupe must compare the stable part of the URL */
    function dedupeKey(url) {
        return String(url).replace(/([?&])_=\d+/g, '$1').replace(/[?&]$/, '');
    }

    /* ---------- hidden-iframe print (browser dialog path) --------------- */
    function hiddenIframePrint(url, done) {
        var fr = document.getElementById('silent_print_frame');
        if (!fr) {
            fr = document.createElement('iframe');
            fr.id = 'silent_print_frame';
            fr.style.cssText =
                'position:fixed;width:0;height:0;border:0;left:-9999px;';
            document.body.appendChild(fr);
        }

        var finished = false;

        function finish(err) {
            if (finished) return;
            finished = true;
            clearTimeout(watchdog);
            fr.onload = null;
            fr.onerror = null;
            if (done) done(err);
        }

        function openTab() {
            try { window.open(url, '_blank'); } catch (e) { /* popup blocked */ }
        }

        /* print the frame; on failure hand over to a normal tab.
         * NATIVE BYPASS: with extension <= 1.5.0 the hook replaced
         * window.print in iframes too - calling the saved native function
         * guarantees a real dialog instead of a second hub job.          */
        function printFrame() {
            try {
                var w = fr.contentWindow;
                var pfn = w.print;
                try { if (w.__printhubNativePrint) pfn = w.__printhubNativePrint; }
                catch (e) { /* cross-origin (PDF viewer) - w.print is fine */ }
                if (w.focus) w.focus();
                pfn.call(w);
                finish(null);
            } catch (err) {
                finish(err);
                openTab();
            }
        }

        /* watchdog: onload NEVER fires for downloads / dead network ->
         * without this the button used to stay dead until reload */
        var watchdog = setTimeout(function () {
            finish(new Error('iframe load timeout (' + (LOAD_TIMEOUT / 1000) + 's)'));
            openTab();
        }, LOAD_TIMEOUT);

        fr.onerror = function () {
            finish(new Error('iframe failed to load'));
            openTab();
        };

        fr.onload = function () {
            var tries = 0, MAX = 20;   /* 20 x 150ms = 3s max extra wait */

            (function wait() {
                if (finished) return;
                tries++;

                var doc = null, readable = false, isPdfEmbed = false;
                try {
                    doc = fr.contentDocument;
                    readable = !!(doc &&
                                  doc.readyState === 'complete' &&
                                  doc.body &&
                                  (doc.body.children.length ||
                                   (doc.body.textContent || '').trim()));
                    if (readable && doc.querySelector) {
                        isPdfEmbed = !!doc.querySelector(
                            'embed[type*="pdf"], object[type*="pdf"]');
                    }
                } catch (err) {
                    /* cross-origin = Chrome's PDF viewer iframe: it IS a
                     * real PDF, just give it a settle beat before printing */
                    if (tries >= 4) { printFrame(); return; }
                }

                if (readable) {
                    /* HTML page or an inspectable <embed> PDF: settled ->
                     * print now (small delay for the PDF embed only)      */
                    setTimeout(function () {
                        if (!finished) printFrame();
                    }, isPdfEmbed ? 600 : 0);
                    return;
                }

                if (doc && doc.readyState === 'complete' && tries >= 8) {
                    /* same-origin but empty body ~1.2s: viewer we cannot
                     * inspect - try printing anyway                        */
                    printFrame();
                    return;
                }

                if (tries < MAX) return setTimeout(wait, 150);

                printFrame();
            })();
        };

        fr.src = url;
    }

    /* ---------- hub history check (timeout race guard) ------------------
     * Returns a Promise for a recent job that matches our title and is
     * still queued/printing, or was printed within PRINTED_FRESH ms.
     * Used ONLY when printPdfLink times out: the hub may still be working
     * on the job, so the dialog fallback must not add a second copy.     */
    function hubHasFreshJob() {
        if (!window.printhub || !window.printhub.history) {
            return Promise.resolve(null);
        }
        return Promise.resolve(window.printhub.history(10)).then(function (r) {
            var jobs = (r && r.jobs) || [];
            for (var i = 0; i < jobs.length; i++) {
                var j = jobs[i];
                if (!j || String(j.title || '').indexOf(PRINT_TITLE) < 0) continue;
                if (j.status === 'queued' || j.status === 'printing') return j;
                if (j.status === 'printed') {
                    var t = Date.parse(j.created_at || '');
                    if (t && (Date.now() - t) < PRINTED_FRESH) return j;
                }
            }
            return null;
        }).catch(function () { return null; });
    }

    /* ---------- main entry: hub silent first, dialog second ------------- */
    function doSilentPrint(e) {
        if (e) e.preventDefault();

        var url = buildPrintUrl();
        if (!url) return;

        /* URL DEDUPE - first line of defence against double prints:
         * covers double-clicks, old print blocks still wired to the same
         * button (they have their own guard), and nervous re-clicking.
         * Compared WITHOUT the _= cache buster (it changes every click). */
        if (dedupeKey(url) === lastSent.key &&
            (Date.now() - lastSent.at) < DEDUPE_MS) {
            console.log('[PrintHub] duplicate ignored (sent',
                        Math.round((Date.now() - lastSent.at) / 1000) + 's ago' +
                        (lastSent.job ? ', job ' + lastSent.job : '') + ')');
            toast('Already sent' +
                  (lastSent.job ? ' (job ' + lastSent.job + ')' : '') +
                  ' - check the printer');
            return;
        }

        /* guard covers BOTH paths now (was iframe-only before) */
        if (printing) return;
        printing = true;
        lastSent = { key: dedupeKey(url), at: Date.now(), job: null };

        var released = false;
        function release() {
            if (released) return;
            released = true;
            printing = false;
        }

        /* path 2+3: browser print dialog via hidden iframe */
        function dialogFallback(reason) {
            console.warn('[PrintHub] silent print unavailable -> print dialog:',
                         reason && reason.message || reason);
            toast('Print dialog opening\u2026');
            hiddenIframePrint(url, function (err2) {
                release();
                if (err2) console.warn('[PrintHub] fallback:', err2.message);
            });
        }

        /* path 1: PrintHub Pro extension -> hub -> silent print */
        if (typeof printPdfLink === 'function') {
            toast('Sending to printer\u2026');
            Promise.resolve(
                printPdfLink(url, PRINT_TITLE,
                             { fallback: false, timeout: HUB_TIMEOUT })
            ).then(function (job) {
                console.log('[PrintHub] queued:', job);
                lastSent.job = (job && job.job_id) || null;
                toast('Sent to printer' +
                      (lastSent.job ? ' (job ' + lastSent.job + ')' : ''));
                release();
            }).catch(function (err) {
                var msg = String(err && err.message || err);
                if (/timed?\s?-?out/i.test(msg)) {
                    /* TIMEOUT RACE: the hub may still print the job -
                     * check history before adding a dialog copy */
                    hubHasFreshJob().then(function (j) {
                        if (j) {
                            console.log('[PrintHub] hub slow but job is alive:', j);
                            lastSent.job = j.id || null;
                            toast('Still printing (job ' + (j.id || '?') +
                                  ') - please wait');
                            release();
                            return;
                        }
                        dialogFallback(err);
                    });
                    return;
                }
                dialogFallback(err);
            });
            return;
        }

        /* extension not loaded (other browser / disabled / file://) */
        dialogFallback(new Error('PrintHub Pro extension not loaded'));
    }
    window.doSilentPrint = doSilentPrint;   /* allow onclick="..." if needed */

    /* ---------- bind (waits for the button to exist) -------------------- */
    function bind() {
        var btn = document.getElementById('print_selected_btn');
        if (btn && btn.addEventListener) {
            btn.addEventListener('click', doSilentPrint);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }

})();
