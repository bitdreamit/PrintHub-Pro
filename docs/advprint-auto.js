/*! AdvPrint Auto v1.6.0 - universal light auto-print for ANY website.
 * Part of the AdvPrint Pro Page Kit - AdvMedi by Bit Dream IT
 * https://www.bitdreamit.com  -  Innovative Healthcare Solutions
 * ------------------------------------------------------------------
 * ZERO CONFIG - add one line to any page:
 *     <script src="advprint-auto.js"></script>
 * Every click on a link that points to a PDF is then printed silently
 * through the AdvPrint Pro extension. No extension or hub? Nothing
 * changes: the link opens in the browser exactly like before.
 *
 * Optional, no JS call needed:
 *   <a href="report.pdf" data-print-title="Lab report">Print</a>
 *   <button data-advprint="https://server/report.pdf">Print</button>
 *   <a href="report.pdf" data-advprint-ignore>never intercept me</a>
 * One optional call for custom selectors / title / cooldown:
 *   AdvprintAuto.init({ selector: 'a.pdf-link', title: 'Report',
 *                       cooldown: 1500 });
 *   AdvprintAuto.print(url, 'Title')   // manual, same guard + toast
 *
 * Behaviour guarantees:
 *   - intercepts ONLY when the extension helper (printPdfLink) exists;
 *     otherwise the browser handles the click (fallback = open the URL)
 *   - stands down when another script already handled the click
 *     (defaultPrevented) - never double-handles with page buttons
 *   - one click = one job: 1.5 s cooldown swallows double clicks
 *   - failures fall back to opening the URL in a new tab
 * ES5-safe, ~2.5 KB, no dependencies.
 */
(function () {
  "use strict";
  if (window.AdvprintAuto) return;

  var PDF_RE = /\.pdf($|[?#])/i;
  var busy = false;          // one job at a time
  var lastAt = 0;            // cooldown clock
  var toastEl = null;
  var cfg = { selector: null, title: null, cooldown: 1500 };

  function toast(text) {
    try {
      if (!toastEl) {
        toastEl = document.createElement("div");
        toastEl.style.cssText =
          "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);" +
          "background:#1d4ed8;color:#fff;font:600 13px/1.4 system-ui,sans-serif;" +
          "padding:9px 16px;border-radius:8px;z-index:2147483647;" +
          "box-shadow:0 4px 14px rgba(0,0,0,.25);";
        (document.body || document.documentElement).appendChild(toastEl);
      }
      toastEl.textContent = text;
      toastEl.style.display = "block";
      clearTimeout(toastEl._advprintT);
      toastEl._advprintT = setTimeout(function () {
        toastEl.style.display = "none";
      }, 2600);
    } catch (_) { /* toast is never critical */ }
  }

  function pdfHref(el) {
    if (!el || !el.getAttribute) return null;
    if (el.hasAttribute && el.hasAttribute("data-advprint-ignore")) return null;
    var direct = el.getAttribute("data-advprint");
    if (direct) return direct;
    var href = el.getAttribute("href");
    if (href && href.charAt(0) !== "#" && PDF_RE.test(href)) return href;
    return null;
  }

  function findTarget(t) {
    var el = t;
    while (el && el !== document) {
      var url = pdfHref(el);
      if (url) return { el: el, url: url };
      el = el.parentNode;
    }
    if (cfg.selector && t.closest) {
      var m = t.closest(cfg.selector);
      if (m) {
        var u = pdfHref(m) || m.getAttribute("href") ||
                m.getAttribute("data-url");
        if (u) return { el: m, url: u };
      }
    }
    return null;
  }

  function send(url, title) {
    if (busy || typeof printPdfLink !== "function") return;
    var now = Date.now();
    if (now - lastAt < cfg.cooldown) return;
    busy = true; lastAt = now;
    toast("Sending to printer...");
    printPdfLink(url, title, { timeout: 20000 }).then(
      function (job) {
        toast("Sent to printer (job " +
              (job && job.job_id != null ? job.job_id : "") + ")");
        busy = false;
      },
      function () {
        // printPdfLink already opened the URL (browser fallback)
        toast("Could not print - opened the file in the browser");
        busy = false;
      }
    );
  }

  function onClick(ev) {
    if (ev.defaultPrevented) return;      // page's own button owns this click
    if (busy || Date.now() - lastAt < cfg.cooldown) {
      if (findTarget(ev.target)) ev.preventDefault();
      return;
    }
    var hit = findTarget(ev.target);
    if (!hit) return;
    if (typeof printPdfLink !== "function") return;   // no extension: open URL
    ev.preventDefault();
    send(hit.url,
         (hit.el.getAttribute && hit.el.getAttribute("data-print-title")) ||
         cfg.title || document.title || "PDF");
  }

  window.AdvprintAuto = {
    version: "1.6.0",
    init: function (opts) {
      for (var k in (opts || {})) {
        if (Object.prototype.hasOwnProperty.call(cfg, k)) cfg[k] = opts[k];
      }
    },
    print: function (url, title) {
      if (typeof printPdfLink !== "function") {
        try { window.open(url, "_blank"); } catch (_) {}
        return false;
      }
      send(url, title || cfg.title || document.title || "PDF");
      return true;
    }
  };

  /* bind once, late enough for <body> but before user code needs it */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      document.addEventListener("click", onClick, false);
    });
  } else {
    document.addEventListener("click", onClick, false);
  }
})();
