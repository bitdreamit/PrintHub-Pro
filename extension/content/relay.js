/* AdvPrint Pro - ISOLATED world relay (static content script, v1.1.3).
 * Bridges the MAIN world (hook.js / api.js) to the service worker:
 *   window.postMessage  ->  chrome.runtime.sendMessage  ->  hub
 * Responses travel back the same way. Nothing leaves the machine.
 *
 * NOTE: this relay deliberately does NOT inject <script> tags into the
 * page. DOM-injected scripts are subject to the page's CSP, so on
 * strict-CSP sites (chat.z.ai, banks, Google ...) Chrome blocked them
 * and logged "Executing inline script violates ... CSP directive".
 * The MAIN-world hook is instead injected by the browser itself
 * (chrome.scripting.registerContentScripts / executeScript), which page
 * CSP cannot block. */
(function () {
  if (window.__advprintRelay) return;
  window.__advprintRelay = true;

  /* ---- honor the toggles (Options) ---- */
  var hookOn = true;
  var failFallback = "tab";   // "tab" = open URL in new tab, "none" = stay silent

  /* v2.6.2 SINGLE VERSION SOURCE: the MAIN-world api.js cannot read
   * chrome.runtime (MAIN world has no extension APIs), so the relay
   * (ISOLATED world) stamps the REAL manifest version into the DOM.
   * window.advprint.version then reads this attribute - the version
   * shown on every page always equals the manifest version, with no
   * hardcoded copy to drift out of sync. */
  function stampVersion() {
    try {
      var el = document.documentElement;
      if (el && !el.hasAttribute("data-advprint-ver")) {
        el.setAttribute("data-advprint-ver",
                        chrome.runtime.getManifest().version);
      }
    } catch (_) {}
  }
  stampVersion();
  document.addEventListener("readystatechange", stampVersion);

  function applyState() {
    // tell the MAIN-world hook + api what to do
    window.postMessage({ __advprint: true, kind: "state", hookOn: hookOn,
                         failFallback: failFallback }, "*");
    if (!hookOn) {
      window.postMessage({ __advprint: true, kind: "unhook" }, "*");
    }
  }

  try {
    chrome.storage.local.get({ hookPrint: true, failFallback: "tab" }, function (st) {
      hookOn = st.hookPrint !== false;
      failFallback = st.failFallback === "none" ? "none" : "tab";
      applyState();
    });
    // live toggle: no reload needed when the user flips an option
    chrome.storage.onChanged.addListener(function (changes, area) {
      if (area === "local" && (changes.hookPrint || changes.failFallback)) {
        if (changes.hookPrint) hookOn = changes.hookPrint.newValue !== false;
        if (changes.failFallback) {
          failFallback = changes.failFallback.newValue === "none" ? "none" : "tab";
        }
        applyState();
      }
    });
  } catch (_) {}

  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__advprint !== true) return;

    if (d.kind === "window.print") {
      if (!hookOn) return;
      try { chrome.runtime.sendMessage({ type: "hookPrint" }); } catch (_) {}
      return;
    }
    if (d.kind === "api" && d.requestId) {
      let p;
      try {
        p = chrome.runtime.sendMessage({ type: "api", payload: d.payload });
      } catch (e) {
        window.postMessage({
          __advprint: true, kind: "api-resp", requestId: d.requestId,
          response: { ok: false, error: "extension context lost - reload the page" }
        }, "*");
        return;
      }
      p.then((response) => {
        window.postMessage({
          __advprint: true, kind: "api-resp",
          requestId: d.requestId, response
        }, "*");
      }).catch((e) => {
        window.postMessage({
          __advprint: true, kind: "api-resp",
          requestId: d.requestId,
          response: { ok: false, error: String(e && e.message || e) }
        }, "*");
      });
    }
  });
})();
