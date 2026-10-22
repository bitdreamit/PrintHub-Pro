/* PrintHub Pro - MAIN world hook (v1.5.1).
 * Injected by the BROWSER itself (dynamic content-script registration on
 * Chrome 111+, or chrome.scripting.executeScript from the service worker).
 * Both routes are extension-initiated and therefore immune to the page's
 * Content-Security-Policy - strict-CSP pages (bank sites, chat apps ...)
 * cannot block it, unlike <script> tag injection.
 *
 * What it intercepts (TOP FRAME ONLY since v1.5.1):
 *   1. window.print()  - JS calls (Odoo, POS, dashboards, report apps)
 *   2. Ctrl+P / Cmd+P  - the keyboard shortcut NEVER calls window.print(),
 *                        it goes straight to Chrome's print preview, so it
 *                        must be caught with a capture-phase keydown.
 * Both are redirected to the hub: silent, no dialog, no preview.
 *
 * v1.5.1 FIX: iframes are NOT hooked any more. The background can only
 * ever print the TOP tab (sender.tab), so an iframe calling print()
 * would silently print the WRONG content (the top page) while the page
 * expected its own print dialog - e.g. a hidden fallback iframe doing
 * iframe.print() made the same report come out of the printer twice.
 * Iframes now keep the native print behavior. Pages that want to print
 * an iframe natively from the top frame can still bypass the hook with
 * win.__printhubNativePrint.call(win). */
(function () {
  if (window.__printhubHooked) return;   // idempotent: never double-install
  if (window.top !== window) return;     // v1.5.1: top frame only (see above)
  window.__printhubHooked = true;
  try {
    var native = window.print;            // kept so we can restore behavior
    var last = 0;                         // 1.2 s throttle, shared by both paths
    var on = true;                        // follows Options "Print interception"

    function fire() {
      var now = Date.now();
      if (now - last < 1200) return;      // swallow double triggers
      last = now;
      window.postMessage({ __printhub: true, kind: "window.print" }, "*");
    }

    var hookedFn = function () {
      if (on) fire();
      else return native.apply(window, arguments);   // disabled: native behavior
    };
    window.print = hookedFn;
    window.__printhubNativePrint = native;

    /* Ctrl+P / Cmd+P (also Ctrl+Shift+P): capture phase on window, so we
     * run before the page's own handlers. preventDefault() here stops
     * Chrome's print preview from ever opening. Uses e.code so it also
     * works on non-Latin keyboard layouts. */
    window.addEventListener("keydown", function (e) {
      if (!on) return;
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      if (e.code !== "KeyP" && String(e.key || "").toLowerCase() !== "p") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      fire();
    }, true);

    window.addEventListener("message", function (ev) {
      var d = ev.data;
      if (!d || d.__printhub !== true) return;
      if (d.kind === "unhook" || (d.kind === "state" && d.hookOn === false)) {
        on = false;                        // restore native print + preview
      } else if (d.kind === "state" && d.hookOn !== false) {
        on = true;                         // (re-)enable interception
      }
    });
  } catch (_) { /* sandboxed page - nothing to do */ }
})();
