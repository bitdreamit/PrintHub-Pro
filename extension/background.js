/* ============================================================
 * PrintHub Pro - background service worker (MV3)
 * Bridges web pages <-> local hub (http://127.0.0.1:9235).
 * All printing is silent: the hub prints via the OS, never a dialog.
 * ============================================================ */

const DEFAULTS = {
  hubUrl: "http://127.0.0.1:9235",
  token: "PrintHub-2024",
  defaultPrinter: "",
  hookPrint: true,          // intercept window.print() on every page
  failFallback: "tab",      // page print call failed: "tab"=open URL in new tab, "none"=stay silent
  autoPrintAllPdfs: true,   // SIMPLE MODE: any PDF opened in the browser prints silently
  closeAfterPrint: true,    // auto-printed URLs: close the tab after -> no browser view
  contextMenu: true,        // right-click "PrintHub Pro" menu
  badge: true,              // show ok/fail on the toolbar icon
  instantPrint: false,      // v2.4.0: instant/direct mode - jobs jump the queue;
                            // if no printer is ready the hub auto-queues them
  debugMode: false,         // v2.4.0: report browser-side errors to the hub
                            // (visible in /debug and the live dashboard)
  rules: [
    {
      pattern: "*://www.htncr.org/lab/medical_reports/pdf/*",
      printer: "",
      action: "auto",         // pdf if the URL serves a PDF, else page render
      auto: true              // print automatically when the URL is opened
    }
  ]
};

/* ---------------- config (managed -> local merge) ---------------- */
let CFG = null;

async function loadCfg() {
  if (CFG) return CFG;
  let managed = {};
  try { managed = await chrome.storage.managed.get(null); } catch (_) {}
  const local = await chrome.storage.local.get(null);
  CFG = Object.assign({}, DEFAULTS, local, managed);
  // managed rules fully override local rules (enterprise lockdown)
  if (managed.rules) CFG.rules = managed.rules;
  return CFG;
}

function invalidateCfg() { CFG = null; }

async function saveCfg(patch) {
  await chrome.storage.local.set(patch);
  invalidateCfg();
  CFG = await loadCfg();
}

/* ---------------- hub client ---------------- */
class HubError extends Error {}

async function hubFetch(path, opts = {}) {
  const cfg = await loadCfg();
  const base = (cfg.hubUrl || DEFAULTS.hubUrl).replace(/\/+$/, "");
  const res = await fetch(base + path, {
    method: opts.method || "GET",
    headers: Object.assign(
      { "X-PrintHub-Token": cfg.token },
      opts.body ? { "Content-Type": "application/json" } : {}
    ),
    body: opts.body ? JSON.stringify(opts.body) : undefined
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok || data.ok === false) {
    throw new HubError(data.error || ("HTTP " + res.status));
  }
  return data;
}

/* ---------------- URL pattern matching (glob style) ---------------- */
function patternToRegex(pattern) {
  let rx = "";
  for (const ch of pattern) {
    if (ch === "*") rx += ".*";
    else rx += ch.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp("^" + rx + "$", "i");
}

function matchRule(url, rules) {
  for (const r of rules || []) {
    if (!r || !r.pattern) continue;
    try {
      if (patternToRegex(r.pattern).test(url)) return r;
    } catch (_) {}
  }
  return null;
}

/* ---------------- badge + history ---------------- */
async function flashBadge(ok, text) {
  const cfg = await loadCfg();
  if (!cfg.badge) return;
  try {
    await chrome.action.setBadgeBackgroundColor(
      { color: ok ? "#16a34a" : "#dc2626" });
    await chrome.action.setBadgeText({ text });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
  } catch (_) {}
}

async function rememberJob(record) {
  const st = await chrome.storage.local.get({ history: [] });
  const history = st.history || [];
  history.unshift(Object.assign({ at: new Date().toISOString() }, record));
  await chrome.storage.local.set({ history: history.slice(0, 100) });
}

function safeOrigin(u) {
  try { return new URL(u).origin; } catch (_) { return "extension"; }
}

/* v2.4.0 Debug mode: send browser-side errors to the hub so /debug and
 * the live dashboard show BOTH sides (desktop hub errors + JS errors).
 * Fail-safe: never throws, never blocks printing. */
async function reportError(message, url) {
  try {
    const cfg = await loadCfg();
    if (!cfg.debugMode) return;
    await hubFetch("/client/report", { method: "POST", body: {
      level: "error",
      message: String(message || "").slice(0, 480),
      url: String(url || "extension").slice(0, 280)
    }});
  } catch (_) {}
}

/* ---------------- print pipelines ---------------- */
async function resolvePrinter(url) {
  const cfg = await loadCfg();
  const rule = matchRule(url, cfg.rules);
  return (rule && rule.printer) || cfg.defaultPrinter || "";
}

/* "__file__" = destination File: hub saves a PDF, no paper is used */
function printerLabel(p) {
  return p === "__file__" ? "File (PDF)" : (p || "default");
}

async function hubPrint(payload) {
  if (payload.printer === "__file__") {
    payload.destination = "file";
    payload.printer = "";
  }
  const cfg = await loadCfg();
  if (cfg.instantPrint && payload.destination !== "file") {
    payload.instant = 1;    // instant/direct mode (hub auto-queues if no printer)
  }
  return hubFetch("/print", { method: "POST", body: payload });
}

async function printPdfUrl(url, title, printer, extra = {}) {
  // fetch with cookies so login-protected PDFs (Laravel etc.) work
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new HubError("PDF fetch failed: HTTP " + res.status);
  return printPdfResponse(res, url, title, printer, extra);
}

async function printPdfResponse(res, url, title, printer, extra = {}) {
  const blob = await res.blob();
  const buf = new Uint8Array(await blob.arrayBuffer());
  if (buf.length < 5 || String.fromCharCode(...buf.slice(0, 5)) !== "%PDF-") {
    throw new HubError("URL did not return a PDF - got HTML? login expired?");
  }
  let bin = "";
  const CH = 32768;
  for (let i = 0; i < buf.length; i += CH) {
    bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
  }
  const data = await hubPrint(Object.assign({
    pdf_base64: btoa(bin),
    title: title || "document",
    printer: printer || "",
    source: "extension",
    site: safeOrigin(url)
  }, extra));
  // record in the shared 60 s dedupe so an auto rule will not print the
  // same URL again when a fallback tab (or the user) opens it right after
  await markPrinted(url);
  await rememberJob({ id: data.job_id, title: title || "document", url,
                      printer: printerLabel(printer),
                      status: data.status || "queued" });
  return data;
}

async function printPageDom(tab, title, printer) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => document.documentElement.outerHTML
  });
  const html = result && result.result;
  if (!html) throw new HubError("could not read page content");
  const data = await hubPrint({
    html: html,
    title: title || (tab.title || "page"),
    printer: printer || "",
    source: "extension"
  });
  await markPrinted(tab.url || "");
  await rememberJob({ id: data.job_id, title: title || tab.title, url: tab.url,
                      printer: printerLabel(printer),
                      status: data.status || "queued" });
  return data;
}

async function printTab(tab, force, printerOverride) {
  const url = tab.url || "";
  const printer = printerOverride || (await resolvePrinter(url));
  const looksPdf = /\.pdf(\?|#|$)/i.test(url);
  if (!looksPdf && force !== "pdf") {
    // render the live DOM -> hub prints via headless Chrome
    const out = await printPageDom(tab, tab.title, printer);
    await flashBadge(true, "OK");
    return out;
  }
  const out = await printPdfUrl(url, tab.title, printer);
  await flashBadge(true, "OK");
  return out;
}

async function printTabAuto(tab) {
  const url = tab.url || "";
  const printer = await resolvePrinter(url);
  const looksPdf = /\.pdf(\?|#|$)/i.test(url);
  if (looksPdf) return printPdfUrl(url, tab.title, printer);
  // ask the server what it is: PDF content-type -> pdf path, else DOM path
  try {
    const res = await fetch(url, { credentials: "include" });
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/pdf")) {
      const out = await printPdfUrl(url, tab.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
  } catch (_) { /* fall through to DOM render */ }
  const out = await printPageDom(tab, tab.title, printer);
  await flashBadge(true, "OK");
  return out;
}

async function printSelection(text, title) {
  const cfg = await loadCfg();
  const data = await hubPrint({
    text: text,
    paper: "a4",
    title: title || "selection",
    printer: cfg.defaultPrinter || "",
    source: "extension"
  });
  await rememberJob({ id: data.job_id, title: title || "selection",
                      printer: printerLabel(cfg.defaultPrinter),
                      status: data.status || "queued" });
  await flashBadge(true, "OK");
  return data;
}

async function printScreenshot(windowId) {
  const cfg = await loadCfg();
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, {
    format: "jpeg", quality: 92
  });
  const b64 = dataUrl.split(",")[1] || "";
  const data = await hubPrint({
    image_base64: b64,
    landscape: true,
    title: "screenshot",
    printer: cfg.defaultPrinter || "",
    source: "extension"
  });
  await rememberJob({ id: data.job_id, title: "screenshot",
                      printer: printerLabel(cfg.defaultPrinter),
                      status: data.status || "queued" });
  await flashBadge(true, "OK");
  return data;
}

/* ---------------- auto-print on URL open (deduped 60 s) ---------------- */
/* After a rule auto-prints a URL, close the tab (if closeAfterPrint is on
 * and the tab still shows a rule-matching URL). Open URL -> paper comes
 * out -> tab disappears: zero browser view. */
async function maybeCloseTab(tabId, force) {
  const cfg = await loadCfg();
  if (!cfg.closeAfterPrint) return;
  setTimeout(async () => {
    try {
      const t = await chrome.tabs.get(tabId);
      if (force || matchRule(t.url || "", (await loadCfg()).rules)) {
        await chrome.tabs.remove(tabId);
      }
    } catch (_) { /* tab already gone */ }
  }, 800);
}

/* shared 60 s print dedupe - fed by auto rules AND manual prints
 * (printPdfUrl / printPageDom), so the same URL is never printed twice
 * within a minute no matter which path delivered it */
async function printedRecently(url) {
  const st = await chrome.storage.session.get({ seen: {} });
  const seen = st.seen || {};
  const now = Date.now();
  const fresh = !!(url && seen[url] && now - seen[url] < 60000);
  // prune
  for (const k of Object.keys(seen)) {
    if (now - seen[k] > 300000) delete seen[k];
  }
  return { seen, now, fresh };
}

async function markPrinted(url) {
  if (!url || !/^https?:/i.test(url)) return;
  const { seen, now } = await printedRecently(url);
  seen[url] = now;
  await chrome.storage.session.set({ seen });
}

async function shouldAutoPrint(url) {
  const cfg = await loadCfg();
  const rule = matchRule(url, cfg.rules);
  if (!rule || !rule.auto) return null;
  const { seen, now, fresh } = await printedRecently(url);
  if (fresh) return null;
  seen[url] = now;
  await chrome.storage.session.set({ seen });
  return rule;
}

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "complete" || !tab || !/^https?:/i.test(tab.url || "")) return;
  try {
    const rule = await shouldAutoPrint(tab.url);
    if (rule) {
      const printer = rule.printer || (await loadCfg()).defaultPrinter || "";
      if (rule.action === "page") {
        await printPageDom(tab, tab.title, printer);
      } else if (rule.action === "pdf") {
        await printPdfUrl(tab.url, tab.title, printer);
      } else {
        await printTabAuto(tab);
      }
      await flashBadge(true, "OK");
      await maybeCloseTab(tabId);
      return;
    }
    /* ---- SIMPLE MODE (v1.1.9): ANY pdf opened in the browser prints
     * silently and its tab closes. No rules, no setup. PDF URLs (.pdf)
     * are printed directly; any other URL is content-type checked with
     * login cookies. The shared 60 s dedupe stops double prints when the
     * page's own button already printed the same URL. */
    const cfg = await loadCfg();
    if (!cfg.autoPrintAllPdfs) return;
    const { fresh } = await printedRecently(tab.url);
    const looksPdf = /\.pdf(\?|#|$)/i.test(tab.url);
    let res = null;
    if (!looksPdf) {
      if (fresh) return;   // just printed another way, and not even a .pdf URL
      try {
        res = await fetch(tab.url, { credentials: "include" });
      } catch (_) { return; }
      const ct = (res.ok ? res.headers.get("content-type") || "" : "").toLowerCase();
      if (!ct.includes("application/pdf")) return;   // a normal page - ignore
    }
    if (fresh) { await maybeCloseTab(tabId, true); return; }  // printed <60 s ago: just close the viewer
    const printer = cfg.defaultPrinter || "";
    if (looksPdf) {
      await printPdfUrl(tab.url, tab.title, printer);
    } else {
      await printPdfResponse(res, tab.url, tab.title, printer);
    }
    await flashBadge(true, "OK");
    await maybeCloseTab(tabId, true);
  } catch (e) {
    await flashBadge(false, "!");
    await rememberJob({ title: "AUTO " + (tab.title || tab.url),
                        url: tab.url, status: "failed", error: String(e.message || e) });
    await reportError("auto-print failed: " + (e.message || e), tab && tab.url);
    console.warn("[PrintHub] auto-print failed:", e);
  }
});

/* ---------------- window.print() hook + page API bridge ---------------- */
/* Legacy-Chrome safety net: registerContentScripts(world:"MAIN") needs
 * Chrome 111+. For anything older, push hook.js into every tab at commit
 * time. chrome.scripting injection is browser-initiated, so page CSP
 * cannot block it (unlike <script> tag injection - never use that). */
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "loading" || !/^https?:/i.test(tab.url || "")) return;
  try {
    const cfg = await loadCfg();
    // v1.1.6: api.js (window.printhub + global printPdfLink) is injected
    // ALWAYS; hook.js (window.print interception) follows the toggle.
    const files = cfg.hookPrint
      ? ["content/hook.js", "content/api.js"]
      : ["content/api.js"];
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files,
      world: "MAIN"
    });
  } catch (_) { /* restricted page or injection unsupported */ }
});

async function injectIntoOpenTabs() {
  // Pages opened BEFORE registration have nothing yet - push the scripts
  // into every open http(s) tab now. All scripts are idempotent, so
  // re-running them is safe. api.js goes in regardless of the hook toggle
  // so window.printhub / printPdfLink stay global (v1.1.6).
  const cfg = await loadCfg();
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  } catch (_) { return; }
  for (const tab of tabs) {
    if (!tab || !tab.id) continue;
    const files = cfg.hookPrint
      ? ["content/hook.js", "content/api.js"]
      : ["content/api.js"];
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files,
        world: "MAIN"
      });
    } catch (_) { /* restricted page - per-navigation fallback covers the rest */ }
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files: ["content/relay.js"]
      });
    } catch (_) {}
  }
}

async function applyHook() {
  const cfg = await loadCfg();
  const wanted = !!cfg.hookPrint;
  const existing = await chrome.scripting.getRegisteredContentScripts();
  const hasApi = existing.some((s) => s.id === "printhub-api");
  const hookReg = existing.find((s) => s.id === "printhub-hook");
  // legacy (<=1.1.5) registration bundles api.js into printhub-hook
  const legacy = !!hookReg && (hookReg.js || []).includes("content/api.js");

  // v1.1.6: API registration must ALWAYS exist - window.printhub and the
  // global printPdfLink() one-liner work even with interception disabled.
  if (!hasApi) {
    try {
      await chrome.scripting.registerContentScripts([{
        id: "printhub-api",
        matches: ["<all_urls>"],
        js: ["content/api.js"],
        runAt: "document_start",
        world: "MAIN",
        allFrames: true,
        persistAcrossSessions: true
      }]);
    } catch (_) { /* older Chrome: the per-navigation fallback covers it */ }
  }

  // migrate the legacy combined registration to hook-only
  if (legacy) {
    try {
      await chrome.scripting.unregisterContentScripts({ ids: ["printhub-hook"] });
    } catch (_) {}
  }

  // hook.js strictly follows the "Print interception" toggle
  if (wanted && (legacy || !hookReg)) {
    try {
      await chrome.scripting.registerContentScripts([{
        id: "printhub-hook",
        matches: ["<all_urls>"],
        js: ["content/hook.js"],
        runAt: "document_start",
        world: "MAIN",
        allFrames: true,
        persistAcrossSessions: true
      }]);
    } catch (_) { /* older Chrome: the per-navigation fallback below takes over */ }
  } else if (!wanted && hookReg && !legacy) {
    try {
      await chrome.scripting.unregisterContentScripts({ ids: ["printhub-hook"] });
    } catch (_) {}
  }
  await injectIntoOpenTabs();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      switch (msg && msg.type) {
        case "hookPrint": {
          // window.print() was called on a page -> print that page silently
          const hcfg = await loadCfg();
          if (!hcfg.hookPrint) {
            reply({ ok: false, error: "print interception is disabled in Options" });
            break;
          }
          const tab = sender.tab ||
            (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
          const out = await printTabAuto(tab);
          reply({ ok: true, job_id: out.job_id });
          break;
        }
        case "api": {
          // window.printhub developer API (see content/api.js)
          reply(await handleApi(msg));
          break;
        }
        case "printTab": {
          const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
          // msg.dest === "file" -> save as PDF instead of printing on paper
          const over = msg.dest === "file" ? "__file__" : undefined;
          reply({ ok: true, ...(await printTab(tab, msg.force, over)) });
          break;
        }
        case "printPdfUrl": {
          const printer = await resolvePrinter(msg.url);
          const out = await printPdfUrl(msg.url, msg.title, printer);
          reply({ ok: true, ...out });
          break;
        }
        case "printSelection":
          reply({ ok: true, ...(await printSelection(msg.text, msg.title)) });
          break;
        case "printScreenshot": {
          const win = await chrome.windows.getCurrent();
          reply({ ok: true, ...(await printScreenshot(win.id)) });
          break;
        }
        case "hubStatus":
          reply(await hubFetch("/health"));
          break;
        case "hubPrinters":
          reply(await hubFetch("/printers"));
          break;
        case "hubJobs":
          reply(await hubFetch("/jobs?limit=" + (msg.limit || 100)));
          break;
        case "queueAction":
          reply(await hubFetch("/queue/" + msg.action, { method: "POST", body: {} }));
          break;
        case "jobAction":
          reply(await hubFetch(`/jobs/${msg.id}/${msg.action}`,
                               { method: "POST", body: {} }));
          break;
        case "saveCfg":
          await saveCfg(msg.patch || {});
          await applyHook();
          await rebuildMenus();
          reply({ ok: true });
          break;
        case "getCfg":
          reply({ ok: true, cfg: await loadCfg() });
          break;
        default:
          reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      await reportError("extension api: " + (e.message || e));
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // async reply
});

async function handleApi(msg) {
  const cfg = await loadCfg();
  const req = msg.payload || {};
  switch (req.fn) {
    case "status":
      return await hubFetch("/health");
    case "printers":
      return await hubFetch("/printers");
    case "history":
      return await hubFetch("/jobs?limit=" + (req.limit || 20));
    case "printPage": {
      const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      const printer = req.destination === "file" ? "__file__"
        : (req.printer || (await resolvePrinter(tab.url || "")));
      const out = await printPageDom(tab, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "printPdf": {
      const printer = req.destination === "file" ? "__file__"
        : (req.printer || (await resolvePrinter(req.url || "")));
      const out = await printPdfUrl(req.url, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "print": {
      // generic: {title, printer, copies, destination,
      //           pdfBase64 | pdfUrl | text | html | pageUrl}
      const o = req;
      const body = {
        title: o.title || "api",
        printer: o.printer || "",
        copies: o.copies || 1,
        source: "website"
      };
      if (o.destination === "file") { body.destination = "file"; body.printer = ""; }
      if (o.pdfBase64) body.pdf_base64 = o.pdfBase64;
      if (o.pdfUrl) body.pdf_url = o.pdfUrl;
      if (o.text != null) body.text = o.text;
      if (o.html != null) body.html = o.html;
      if (o.pageUrl) body.page_url = o.pageUrl;
      if (!body.pdf_base64 && !body.pdf_url && body.text == null &&
          body.html == null && !body.page_url) {
        throw new HubError("printhub.print: provide pdfBase64, pdfUrl, text, html or pageUrl");
      }
      const out = await hubPrint(body);
      await rememberJob({ id: out.job_id, title: body.title,
                          printer: body.destination === "file" ? "File (PDF)" : "default",
                          status: out.status || "queued" });
      await flashBadge(true, "OK");
      return out;
    }
    default:
      throw new HubError("unknown api fn: " + req.fn);
  }
}

/* ---------------- context menus ---------------- */
async function rebuildMenus() {
  const cfg = await loadCfg();
  await chrome.contextMenus.removeAll();
  if (!cfg.contextMenu) return;
  chrome.contextMenus.create({
    id: "printhub-root", title: "PrintHub Pro", contexts: ["all"]
  });
  chrome.contextMenus.create({
    id: "ph-print-page", parentId: "printhub-root",
    title: "Print this page", contexts: ["page"]
  });
  chrome.contextMenus.create({
    id: "ph-print-sel", parentId: "printhub-root",
    title: "Print selection", contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "ph-print-link", parentId: "printhub-root",
    title: "Print linked PDF", contexts: ["link"]
  });
  chrome.contextMenus.create({
    id: "ph-shot", parentId: "printhub-root",
    title: "Print screenshot", contexts: ["page"]
  });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "ph-print-page" && tab) {
      await printTab(tab);
    } else if (info.menuItemId === "ph-print-sel" && info.selectionText) {
      await printSelection(info.selectionText, "selection");
    } else if (info.menuItemId === "ph-print-link" && info.linkUrl) {
      const printer = await resolvePrinter(info.linkUrl);
      await printPdfUrl(info.linkUrl, "link", printer);
    } else if (info.menuItemId === "ph-shot") {
      const win = await chrome.windows.getCurrent();
      await printScreenshot(win.id);
    }
  } catch (e) {
    await flashBadge(false, "!");
    await reportError("context menu: " + (e.message || e), info && info.pageUrl);
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "PrintHub Pro", message: String(e.message || e)
    });
  }
});

/* ---------------- toolbar command (Alt+P) ---------------- */
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "print-current-tab") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  try {
    await printTab(tab);
  } catch (e) {
    await flashBadge(false, "!");
    await reportError("hotkey print: " + (e.message || e), tab && tab.url);
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "PrintHub Pro", message: String(e.message || e)
    });
  }
});

/* ---------------- icon click (no popup case) ---------------- */
chrome.action.onClicked?.addListener?.(async () => { /* popup handles it */ });

/* ---------------- lifecycle ---------------- */
chrome.runtime.onInstalled.addListener(async () => {
  const st = await chrome.storage.local.get({ initialized: false });
  if (!st.initialized) {
    // seed defaults once so Options shows the htncr.org example rule
    await chrome.storage.local.set(Object.assign({}, DEFAULTS, { initialized: true }));
  }
  await rebuildMenus();
  await applyHook();
});

chrome.runtime.onStartup.addListener(async () => {
  await rebuildMenus();
  await applyHook();
});

// MV3 service workers wake on events - make sure open tabs always have
// the hook (idempotent; cheap because of the __printhub* guards).
injectIntoOpenTabs();
