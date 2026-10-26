/* ============================================================
 * PrintHub Pro - background service worker (MV3)
 * Bridges web pages <-> local hub (http://127.0.0.1:9235).
 * All printing is silent: the hub prints via the OS, never a dialog.
 * ============================================================ */

const DEFAULTS = {
  hubUrl: "http://127.0.0.1:9235",
  token: "PrintHub-2024",
  defaultPrinter: "",
  enabled: true,            // MASTER SWITCH: false = PrintHub fully off
                            // (no printing, no auto-print, no hook/API,
                            //  gray OFF badge on the toolbar icon)
  queueMode: true,          // ON  = jobs go through the hub FIFO queue
                            //      (pause/resume, ordered)
                            // OFF = hub prints each job immediately
                            //      (queue:false - no waiting in line)
  retryOffline: true,       // v2.0: keep jobs in the browser while the hub
                            // is unreachable and send them when it returns
  lang: "auto",             // v2.0 UI language: auto | en | bn
  hookPrint: true,          // intercept window.print() on every page
  failFallback: "tab",      // page print call failed: "tab"=open URL in new tab, "none"=stay silent
  autoPrintAllPdfs: true,   // SIMPLE MODE: any PDF opened in the browser prints silently
  closeAfterPrint: true,    // auto-printed URLs: close the tab after -> no browser view
  contextMenu: true,        // right-click "PrintHub Pro" menu
  badge: true,              // show ok/fail on the toolbar icon
  rules: [
    {
      pattern: "*://www.htncr.org/lab/medical_reports/pdf/*",
      type: "glob",           // "glob" (1.x style) or "regex" (v2.0)
      title: "",              // v2.0: only match when the page title contains this
      printer: "",
      action: "auto",         // pdf if the URL serves a PDF, else page render
      auto: true,             // print automatically when the URL is opened
      enabled: true           // v2.0: per-site on/off switch
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

/* ---------------- offline retry queue (v2.0) ------------------------ */
/* When the hub cannot be reached, jobs are kept here and flushed by a
 * 1-minute alarm as soon as /health answers again. The popup shows an
 * offline banner with the waiting count + a Retry-now button. */
const RETRY_ALARM = "printhub-retry";

async function retryQueueInfo() {
  const st = await chrome.storage.local.get({ retryQueue: [] });
  return st.retryQueue || [];
}

async function queueForRetry(payload) {
  const q = await retryQueueInfo();
  q.push({ payload, added_at: new Date().toISOString(), tries: 0 });
  await chrome.storage.local.set({ retryQueue: q.slice(-100) });
  await updateRetryBadge();
  try {
    await chrome.alarms.create(RETRY_ALARM, { periodInMinutes: 1 });
  } catch (_) {}
  console.warn("[PrintHub] hub offline - job parked for retry (" +
               q.length + " waiting)");
}

async function flushRetries(reason) {
  const cfg = await loadCfg();
  if (cfg.enabled === false) return 0;
  const q = await retryQueueInfo();
  if (!q.length) return 0;
  let sent = 0;
  const remaining = [];
  let stopped = null;           // "auth" | "locked" | null
  for (let i = 0; i < q.length; i++) {
    const item = q[i];
    try {
      const data = await hubFetch("/print", {
        method: "POST", body: item.payload });
      await rememberJob({ id: data.job_id,
                          title: (item.payload && item.payload.title) || "retry",
                          status: data.status || "queued",
                          printer: "retry" });
      sent++;
    } catch (e) {
      if (e && (e.auth || e.locked)) {
        // v2.1.0 circuit breaker: STOP immediately. Every extra request
        // just feeds the hub's failure counter and (with several Chrome
        // windows on one IP) locks everyone out longer. Tries are NOT
        // burned - this is a config problem, not a dead job.
        stopped = e.auth ? "auth" : "locked";
        remaining.push(...q.slice(i));
        break;
      }
      item.tries = (item.tries || 0) + 1;
      if (item.tries < 20) remaining.push(item);   // give up after ~20 min
    }
  }
  await chrome.storage.local.set({ retryQueue: remaining });
  await updateRetryBadge();
  if (!remaining.length) {
    try { await chrome.alarms.clear(RETRY_ALARM); } catch (_) {}
  }
  if (stopped) {
    await setAuthProblem(true, stopped);
    FLUSH_BACKOFF_MIN = Math.min(FLUSH_BACKOFF_MIN * 2 || 2, 15);
    await scheduleRetryAlarm();      // slow down: 1 -> 2 -> 4 -> 8 -> 15 min
    console.warn("[PrintHub] retry paused for " + FLUSH_BACKOFF_MIN +
                 " min (" + remaining.length + " job(s) kept)");
    return sent;
  }
  if (sent) {
    FLUSH_BACKOFF_MIN = 1;
    await setAuthProblem(false);
    console.log("[PrintHub] " + sent + " parked job(s) delivered" +
                (reason ? " (" + reason + ")" : ""));
    await flashBadge(true, "OK");
  }
  return sent;
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm && alarm.name === RETRY_ALARM) {
    flushRetries("alarm");
  }
});

/* v2.1.0: the moment the user fixes the token or hub URL (Options page,
 * popup Connect) clear the KEY state, reset the backoff and retry at
 * once - no need to wait for the next alarm tick. */
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.token || changes.hubUrl) {
    FLUSH_BACKOFF_MIN = 1;
    setAuthProblem(false).then(() => flushRetries("config-changed"));
  } else if (changes.authProblem && !changes.authProblem.newValue) {
    updateRetryBadge();       // KEY badge can go away
  }
});

async function updateRetryBadge() {
  const cfg = await loadCfg();
  if (!cfg.badge || cfg.enabled === false) return;
  try {
    const st = await chrome.storage.local.get({ authProblem: null });
    if (st.authProblem) {           // v2.1.0: token problem outranks count
      await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
      await chrome.action.setBadgeText({ text: "KEY" });
      return;
    }
    const q = await retryQueueInfo();
    if (q.length) {
      await chrome.action.setBadgeBackgroundColor({ color: "#d97706" });
      await chrome.action.setBadgeText({ text: String(q.length) });
    } else {
      await chrome.action.setBadgeText({ text: "" });
    }
  } catch (_) {}
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
    // v2.1.0: tag auth/lock errors so callers can stop hammering the
    // hub (every wrong request feeds its IP failure counter)
    const err = new HubError(data.error || ("HTTP " + res.status));
    err.status = res.status;
    err.auth = res.status === 401;
    err.locked = res.status === 429;
    throw err;
  }
  return data;
}

/* ---------------- auth problem state (v2.1.0) ------------------- */
/* When the hub answers 401 (token rejected) or 429 (IP temporarily
 * locked) the extension must NOT keep retrying - with several Chrome
 * windows sharing one IP that would lock the dashboard and the other
 * windows out too. State is stored so the popup can show a banner. */
let FLUSH_BACKOFF_MIN = 1;      // alarm period: 1 -> 2 -> 4 -> 8 -> 15 min

async function setAuthProblem(on, why) {
  const st = await chrome.storage.local.get({ authProblem: null });
  if (on) {
    await chrome.storage.local.set({
      authProblem: { why: why || "token", at: new Date().toISOString() }
    });
    try {
      await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
      await chrome.action.setBadgeText({ text: "KEY" });
    } catch (_) {}
    console.warn("[PrintHub] " + (why === "locked"
      ? "hub is rate-limiting this IP (429) - backing off"
      : "hub rejected the token (401) - update it in PrintHub options"));
  } else if (st.authProblem) {
    await chrome.storage.local.remove("authProblem");
  }
}

async function scheduleRetryAlarm() {
  try {
    await chrome.alarms.create(RETRY_ALARM,
                               { periodInMinutes: FLUSH_BACKOFF_MIN });
  } catch (_) {}
}

/* ---------------- URL pattern matching (glob + regex + title) -------- */
function patternToRegex(pattern, type) {
  if (type === "regex") return new RegExp(pattern, "i");
  let rx = "";
  for (const ch of pattern) {
    if (ch === "*") rx += ".*";
    else rx += ch.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp("^" + rx + "$", "i");
}

/* v2.0 rules: type glob|regex, optional page-title filter, and a
 * per-rule on/off switch (per-site settings). First matching wins. */
function matchRule(url, rules, title) {
  for (const r of rules || []) {
    if (!r || !r.pattern) continue;
    if (r.enabled === false) continue;          // per-site OFF switch
    try {
      if (!patternToRegex(r.pattern, r.type).test(url)) continue;
      if (r.title &&
          !(title || "").toLowerCase().includes(String(r.title).toLowerCase())) {
        continue;                                 // title filter miss
      }
      return r;
    } catch (_) {}
  }
  return null;
}

/* ---------------- badge + history ---------------- */
/* Master switch state on the toolbar icon: gray OFF badge while
 * disabled, cleared when enabled. Applied on install/startup and
 * whenever the config changes. */
async function applyEnabledBadge() {
  const cfg = await loadCfg();
  try {
    if (cfg.enabled === false) {
      await chrome.action.setBadgeBackgroundColor({ color: "#64748b" });
      await chrome.action.setBadgeText({ text: "OFF" });
    } else {
      await chrome.action.setBadgeText({ text: "" });
    }
  } catch (_) {}
}

async function flashBadge(ok, text) {
  const cfg = await loadCfg();
  if (!cfg.badge || cfg.enabled === false) return;
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

/* ---------------- print pipelines ---------------- */
async function resolvePrinter(url, title) {
  const cfg = await loadCfg();
  const rule = matchRule(url, cfg.rules, title);
  return (rule && rule.printer) || cfg.defaultPrinter || "";
}

/* "__file__" = destination File: hub saves a PDF, no paper is used */
function printerLabel(p) {
  return p === "__file__" ? "File (PDF)" : (p || "default");
}

function hubPrint(payload) {
  if (payload.printer === "__file__") {
    payload.destination = "file";
    payload.printer = "";
  }
  // Queue Mode OFF -> tell the hub to print THIS job immediately
  // (bypasses the FIFO; pause/resume does not hold it back).
  return loadCfg().then((cfg) => {
    if (cfg.queueMode === false) payload.queue = false;
    return hubFetch("/print", { method: "POST", body: payload })
      .catch(async (e) => {
        // v2.1.0: 401 = the token is wrong. Flag it (KEY badge + popup
        // banner) and say so plainly; do NOT park the job - printing
        // cannot succeed until the token is fixed.
        if (e && e.auth) {
          await setAuthProblem(true, "token");
          throw new HubError("hub rejected the token - fix it in " +
                             "PrintHub Pro options (Hub token field)");
        }
        if (e && e.locked) {
          // v2.1.0: 429 = this IP is temporarily locked (too many bad
          // tokens from SOME client). Transient -> park and auto-retry.
          if (cfg.retryOffline !== false && payload.destination !== "file") {
            await queueForRetry(payload);
            await setAuthProblem(true, "locked");
            throw new HubError("hub is rate-limiting this IP - job saved " +
                               "and will retry automatically");
          }
          throw new HubError("hub is rate-limiting this IP - try again " +
                             "in a few minutes");
        }
        // v2.0: network-level failure (hub down) -> park for auto-retry
        const msg = String((e && e.message) || e);
        const networkish = /failed to fetch|networkerror|load failed/i.test(msg);
        if (cfg.retryOffline !== false && networkish &&
            payload.destination !== "file") {
          await queueForRetry(payload);
          throw new HubError("hub offline - job saved and will retry");
        }
        throw e;
      });
  });
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
    source: "extension"
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
  const printer = printerOverride || (await resolvePrinter(url, tab.title));
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
  const printer = await resolvePrinter(url, tab.title);
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

async function shouldAutoPrint(url, title) {
  const cfg = await loadCfg();
  const rule = matchRule(url, cfg.rules, title);
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
    const cfg0 = await loadCfg();
    if (cfg0.enabled === false) return;      // master switch OFF - do nothing
    const rule = await shouldAutoPrint(tab.url, tab.title);
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
    // Master switch OFF -> inject NOTHING: no window.print() hook, no
    // window.printhub API, nothing. Pages keep their native behavior.
    if (cfg.enabled === false) return;
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
  if (cfg.enabled === false) return;         // master switch OFF
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
  // MASTER SWITCH OFF: pull out every registration and inject nothing.
  // Enabled again -> applyHook re-registers what the toggles ask for.
  if (cfg.enabled === false) {
    try {
      const regs = await chrome.scripting.getRegisteredContentScripts();
      const ids = regs.map((r) => r.id)
        .filter((id) => id === "printhub-api" || id === "printhub-hook");
      if (ids.length) {
        await chrome.scripting.unregisterContentScripts({ ids });
      }
    } catch (_) {}
    return;
  }
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
          if (hcfg.enabled === false) {
            reply({ ok: false, error: "PrintHub is disabled - enable it from the toolbar popup" });
            break;
          }
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
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "PrintHub is disabled - enable it in the popup" });
            break;
          }
          const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
          // msg.dest === "file" -> save as PDF instead of printing on paper
          const over = msg.dest === "file" ? "__file__" : undefined;
          reply({ ok: true, ...(await printTab(tab, msg.force, over)) });
          break;
        }
        case "printPdfUrl": {
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "PrintHub is disabled - enable it in the popup" });
            break;
          }
          const printer = await resolvePrinter(msg.url, msg.title);
          const out = await printPdfUrl(msg.url, msg.title, printer);
          reply({ ok: true, ...out });
          break;
        }
        case "printSelection":
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "PrintHub is disabled - enable it in the popup" });
            break;
          }
          reply({ ok: true, ...(await printSelection(msg.text, msg.title)) });
          break;
        case "printScreenshot": {
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "PrintHub is disabled - enable it in the popup" });
            break;
          }
          const win = await chrome.windows.getCurrent();
          reply({ ok: true, ...(await printScreenshot(win.id)) });
          break;
        }
        case "hubStatus":
          reply(await hubFetch("/health"));
          break;
        case "retryInfo": {
          const q = await retryQueueInfo();
          reply({ ok: true, count: q.length });
          break;
        }
        case "flushRetries": {
          const sent = await flushRetries("manual");
          reply({ ok: true, sent });
          break;
        }
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
        case "jobRetry":
          reply(await hubFetch(`/jobs/${msg.id}/retry`, {
            method: "POST",
            body: { printer: msg.printer || "", reason: msg.reason || "" } }));
          break;
        case "jobReprint":
          reply(await hubFetch(`/jobs/${msg.id}/reprint`, {
            method: "POST",
            body: { reason: msg.reason || "" } }));
          break;
        case "saveCfg":
          await saveCfg(msg.patch || {});
          await applyHook();
          await rebuildMenus();
          await applyEnabledBadge();
          reply({ ok: true });
          break;
        case "getCfg":
          reply({ ok: true, cfg: await loadCfg() });
          break;
        default:
          reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // async reply
});

async function handleApi(msg) {
  const cfg = await loadCfg();
  const req = msg.payload || {};
  // read-only calls stay available even while disabled; printing calls
  // are refused so a disabled PrintHub never prints from a page
  const PRINT_FNS = ["printPage", "printPdf", "print"];
  if (PRINT_FNS.includes(req.fn) && cfg.enabled === false) {
    throw new HubError("PrintHub is disabled - enable it in the toolbar popup");
  }
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
        : (req.printer || (await resolvePrinter(tab.url || "", tab.title || req.title)));
      const out = await printPageDom(tab, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "printPdf": {
      const printer = req.destination === "file" ? "__file__"
        : (req.printer || (await resolvePrinter(req.url || "", req.title)));
      const out = await printPdfUrl(req.url, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "print": {
      // generic: {title, printer, copies, destination, priority, pages,
      //           profile, reason, watermark,
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
      if (o.lang) body.lang = o.lang;                 // v2.0 raw: escpos|zpl
      if (o.rawBase64) body.raw_base64 = o.rawBase64; // v2.0 raw bytes
      if (o.priority) body.priority = o.priority;     // v2.0: 1 = urgent
      if (o.pages) body.pages = o.pages;              // v2.0: "1-3,5"
      if (o.profile) body.profile = o.profile;        // v2.0: hub profile name
      if (o.reason) body.reason = o.reason;           // v2.0: audit reason
      if (o.watermark != null) body.watermark = o.watermark;
      if (!body.pdf_base64 && !body.pdf_url && body.text == null &&
          body.html == null && !body.page_url && !body.raw_base64) {
        throw new HubError("printhub.print: provide pdfBase64, pdfUrl, text, html, pageUrl or rawBase64");
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
  if (!cfg.contextMenu || cfg.enabled === false) return;   // no menu while disabled
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
    if ((await loadCfg()).enabled === false) return;   // master switch OFF
    if (info.menuItemId === "ph-print-page" && tab) {
      await printTab(tab);
    } else if (info.menuItemId === "ph-print-sel" && info.selectionText) {
      await printSelection(info.selectionText, "selection");
    } else if (info.menuItemId === "ph-print-link" && info.linkUrl) {
      const printer = await resolvePrinter(info.linkUrl, "");
      await printPdfUrl(info.linkUrl, "link", printer);
    } else if (info.menuItemId === "ph-shot") {
      const win = await chrome.windows.getCurrent();
      await printScreenshot(win.id);
    }
  } catch (e) {
    await flashBadge(false, "!");
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "PrintHub Pro", message: String(e.message || e)
    });
  }
});

/* ---------------- toolbar command (Alt+P) ---------------- */
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "print-current-tab") return;
  if ((await loadCfg()).enabled === false) return;     // master switch OFF
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  try {
    await printTab(tab);
  } catch (e) {
    await flashBadge(false, "!");
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
  await applyEnabledBadge();
  await updateRetryBadge();
  await flushRetries("installed");
  await rebuildMenus();
  await applyHook();
});

chrome.runtime.onStartup.addListener(async () => {
  await applyEnabledBadge();
  await updateRetryBadge();
  await flushRetries("startup");
  await rebuildMenus();
  await applyHook();
});

// MV3 service workers wake on events - make sure open tabs always have
// the hook (idempotent; cheap because of the __printhub* guards).
applyEnabledBadge();
injectIntoOpenTabs();
