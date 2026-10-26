/* PrintHub Pro - options page logic (v2.2: print defaults + LAN/PCs) */
const $ = (id) => document.getElementById(id);
let PRINTERS = [];
let QUEUE_TIMER = null;
let LAN_TIMER = null;
let CAPS = null;

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}
function saved(text) {
  $("saveMsg").textContent = text || "Saved";
  setTimeout(() => { $("saveMsg").textContent = ""; }, 2500);
}

/* ---------- tabs (Queue | History | Settings | LAN | About) ---------- */
function showTab(name) {
  const valid = ["queue", "history", "settings", "lan", "about"].includes(name)
    ? name : "settings";
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === valid));
  document.querySelectorAll("section.panel").forEach((p) =>
    p.classList.toggle("active", p.id === "panel-" + valid));
  if (valid === "queue") startQueueLoop(); else stopQueueLoop();
  if (valid === "lan") startLanLoop(); else stopLanLoop();
  if (valid === "history") loadJobs();
}

function stopLanLoop() {
  if (LAN_TIMER) { clearInterval(LAN_TIMER); LAN_TIMER = null; }
}
function startLanLoop() {
  stopLanLoop();
  loadLan();
  LAN_TIMER = setInterval(loadLan, 8000);
}

function stopQueueLoop() {
  if (QUEUE_TIMER) { clearInterval(QUEUE_TIMER); QUEUE_TIMER = null; }
}

function startQueueLoop() {
  stopQueueLoop();
  refreshQueue();
  QUEUE_TIMER = setInterval(refreshQueue, 3000);
}

/* default tab: Queue when the queue/jobs hold data, otherwise Settings.
 * #hash links (options.html#api etc.) always win. */
async function pickDefaultTab() {
  const hash = (location.hash || "").replace("#", "");
  if (hash) {
    showTab(hash === "api" ? "about" : hash);
    return;
  }
  try {
    const st = await send({ type: "hubStatus" });
    if (st.ok && (st.pending > 0 || st.paused)) { showTab("queue"); return; }
    const jobs = await send({ type: "hubJobs", limit: 100 });
    const active = (jobs.ok ? jobs.jobs : []).filter(
      (j) => j.status === "queued" || j.status === "printing");
    if (active.length) { showTab("queue"); return; }
  } catch (_) { /* offline -> settings */ }
  showTab("settings");
}

/* ---------- live queue ---------- */
async function refreshQueue() {
  const body = $("queueBody");
  const st = await send({ type: "hubStatus" });
  if (!st.ok) {
    $("qDot").className = "dot offline";
    $("qState").textContent = "Hub offline";
    $("qInfo").textContent = "start it: python printhub.py serve (or PrintHub Tool > 1)";
    body.innerHTML = '<tr><td colspan="6">Hub offline - nothing to show.</td></tr>';
    $("bQPause").textContent = "Pause";
    return;
  }
  const pausedNow = !!st.paused;
  $("qDot").className = "dot" + (pausedNow ? " paused" : "");
  $("qState").textContent = pausedNow ? "PAUSED" : "Running";
  $("qInfo").textContent = st.pending + " pending · " +
    (st.jobs_today || 0) + " today · hub v" + st.version;
  $("bQPause").textContent = pausedNow ? "Resume" : "Pause";
  // update the tab badge: active queue items
  const jobs = await send({ type: "hubJobs", limit: 100 });
  const active = (jobs.ok ? jobs.jobs : []).filter(
    (j) => j.status === "queued" || j.status === "printing");
  const badge = $("tabQBadge");
  badge.textContent = String(active.length);
  badge.classList.toggle("show", active.length > 0);
  body.innerHTML = "";
  if (!active.length) {
    body.innerHTML = '<tr><td colspan="6">Queue is empty - nothing waiting.</td></tr>';
    return;
  }
  for (const j of active) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${j.id}</td><td>${(j.title || "-").slice(0, 42)}</td>` +
      `<td>${(j.printer || "default").slice(0, 28)}</td><td>${j.kind}</td>` +
      `<td><span class="st ${j.status}">${j.status}</span></td>`;
    const tdBtn = document.createElement("td");
    const bc = document.createElement("button");
    bc.className = "mini danger"; bc.textContent = "Cancel";
    bc.addEventListener("click", async () => {
      await send({ type: "jobAction", id: j.id, action: "cancel" });
      refreshQueue();
    });
    tdBtn.appendChild(bc);
    if (j.status !== "printing") {
      const bs = document.createElement("button");
      bs.className = "mini"; bs.textContent = "Shift to PC";
      bs.title = "Print this job on ANOTHER PC's hub over the LAN";
      bs.addEventListener("click", () => shiftJobPrompt(j.id));
      tdBtn.appendChild(bs);
    }
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  }
}

/* v2.2: shift one job (or the whole queue) to another PC's hub */
async function shiftJobPrompt(id) {
  const t = prompt(
    `Shift job #${id} to which PC?\n` +
    "Enter the OTHER PrintHub's LAN URL, e.g. http://192.168.0.60:9235",
    $("shiftTarget").value.trim());
  if (!t) return;
  $("shiftTarget").value = t.trim();
  const r = await send({ type: "queueShift", scope: "job", ids: [id],
                         target: t.trim(), targetToken: $("shiftToken").value.trim() });
  alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
  refreshQueue();
}

/* ---------- GitHub update check ---------- */
async function updateCheck() {
  const out = $("updState"), live = $("updLive");
  out.textContent = "checking...";
  live.innerHTML = "";
  let manifestVer = "2.2.0";
  try { manifestVer = chrome.runtime.getManifest().version; } catch (_) {}
  try {
    const r = await fetch("https://api.github.com/repos/bitdreamit/PrintHub-Pro/releases/latest",
      { headers: { "Accept": "application/vnd.github+json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    const tag = String(d.tag_name || "").replace(/^v/i, "");
    const url = d.html_url || "https://github.com/bitdreamit/PrintHub-Pro/releases/latest";
    const num = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number);
    const [a = [0, 0, 0], b = [0, 0, 0]] = [num(tag), num(manifestVer)];
    const newer = a.some((v, i) => v > (b[i] || 0));
    if (newer) {
      out.textContent = "";
      live.innerHTML = 'UPDATE AVAILABLE: <b>v' + tag + '</b> (you have v' + manifestVer +
        ') - <a href="' + url + '" target="_blank" rel="noreferrer">download from GitHub</a>';
    } else {
      out.textContent = "up to date (latest release: v" + tag + ")";
    }
  } catch (e) {
    out.textContent = "could not reach GitHub (" + e.message + ")";
  }
}

/* ---------- rules table (v2.0: type glob/regex, title filter, on/off) -- */
function ruleRow(rule) {
  const tr = document.createElement("tr");

  const tdP = document.createElement("td");
  const inP = document.createElement("input");
  inP.type = "text"; inP.value = rule.pattern || "";
  inP.placeholder = "*://example.com/reports/*";
  inP.addEventListener("change", collect);
  tdP.appendChild(inP);

  const tdT = document.createElement("td");
  const selT = document.createElement("select");
  selT.appendChild(new Option("Glob", "glob"));
  selT.appendChild(new Option("Regex", "regex"));
  selT.value = rule.type || "glob";
  selT.title = "Glob = 1.x style wildcards; Regex = v2.0 regular expression";
  selT.addEventListener("change", collect);
  tdT.appendChild(selT);

  const tdTi = document.createElement("td");
  const inTi = document.createElement("input");
  inTi.type = "text"; inTi.value = rule.title || "";
  inTi.placeholder = "invoice?";
  inTi.title = "Only match when the page title contains this text";
  inTi.addEventListener("change", collect);
  tdTi.appendChild(inTi);

  const tdPr = document.createElement("td");
  const sel = document.createElement("select");
  sel.appendChild(new Option("(default printer)", ""));
  sel.appendChild(new Option("File (save as PDF)", "__file__"));
  PRINTERS.forEach((p) => sel.appendChild(new Option(p.name, p.name)));
  sel.value = rule.printer || "";
  sel.addEventListener("change", collect);
  tdPr.appendChild(sel);

  const tdA = document.createElement("td");
  const selA = document.createElement("select");
  [["auto", "Auto (PDF or page)"], ["pdf", "PDF only"], ["page", "Page render"]]
    .forEach(([v, t]) => selA.appendChild(new Option(t, v)));
  selA.value = rule.action || "auto";
  selA.addEventListener("change", collect);
  tdA.appendChild(selA);

  const tdOn = document.createElement("td");
  const onChk = document.createElement("input");
  onChk.type = "checkbox"; onChk.checked = rule.enabled !== false;
  onChk.title = "Per-site on/off switch";
  onChk.addEventListener("change", collect);
  tdOn.appendChild(onChk);

  const tdAuto = document.createElement("td");
  const chk = document.createElement("input");
  chk.type = "checkbox"; chk.checked = !!rule.auto;
  chk.title = "Print automatically when the URL is opened";
  chk.addEventListener("change", collect);
  tdAuto.appendChild(chk);

  const tdX = document.createElement("td");
  const bx = document.createElement("button");
  bx.className = "mini danger"; bx.textContent = "Delete";
  bx.addEventListener("click", () => { tr.remove(); collect(); });
  tdX.appendChild(bx);

  tr.append(tdP, tdT, tdTi, tdPr, tdA, tdOn, tdAuto, tdX);
  return tr;
}

function renderRules(rules) {
  const body = $("rulesBody");
  body.innerHTML = "";
  (rules && rules.length ? rules : []).forEach((r) => body.appendChild(ruleRow(r)));
}

function collect() {
  const rules = [];
  $("rulesBody").querySelectorAll("tr").forEach((tr) => {
    const [p, ty, ti, pr, a, on, auto] =
      tr.querySelectorAll("input, select, select, select, select, input, input");
    if (p.value.trim()) {
      rules.push({ pattern: p.value.trim(), type: ty.value,
                   title: ti.value.trim(), printer: pr.value,
                   action: a.value, enabled: on.checked,
                   auto: auto.checked });
    }
  });
  return rules;
}

/* ---------- v2.2: default print options (stored as cfg.printDefaults) */
function PD() {
  return {
    copies: ($("dCopies").value || "").trim(),
    pagesMode: $("dPagesMode").value,
    pagesCustom: ($("dPagesCustom").value || "").trim(),
    quality: $("dQuality").value,
    qualityCustom: ($("dQualityCustom").value || "").trim(),
    perSheet: $("dPerSheet").value,
    duplex: $("dDuplex").value,
    orient: $("dOrient").value,
    scale: ($("dScale").value || "").trim(),
    margin: ($("dMargin").value || "").trim(),
    paper: $("dPaper").value
  };
}

function applyPrintDefaults(pd) {
  pd = pd || {};
  $("dCopies").value = pd.copies || "";
  $("dPagesMode").value = pd.pagesMode || "";
  $("dPagesCustom").value = pd.pagesCustom || "";
  $("dQuality").value = pd.quality || "";
  $("dQualityCustom").value = pd.qualityCustom || "";
  $("dPerSheet").value = pd.perSheet || "";
  $("dDuplex").value = pd.duplex || "";
  $("dOrient").value = pd.orient || "";
  $("dScale").value = pd.scale || "";
  $("dMargin").value = pd.margin || "";
  $("dPaper").value = pd.paper || "";
}

/* What the hub will actually receive for the current defaults - the same
 * merge logic background.js applies before POST /print. */
function effectiveOptions(pd) {
  pd = pd || PD();
  const o = {};
  if (pd.copies && parseInt(pd.copies, 10) > 1) o.copies = parseInt(pd.copies, 10);
  if (pd.pagesMode === "odd" || pd.pagesMode === "even") o.pages = pd.pagesMode;
  else if (pd.pagesMode === "custom" && pd.pagesCustom) o.pages = pd.pagesCustom;
  if (pd.quality === "custom" && pd.qualityCustom) o.quality = pd.qualityCustom;
  else if (pd.quality) o.quality = pd.quality;
  if (pd.perSheet && parseInt(pd.perSheet, 10) > 1) o.per_sheet = parseInt(pd.perSheet, 10);
  if (pd.duplex) o.duplex = pd.duplex;
  if (pd.orient) o.orientation = pd.orient;
  if (pd.scale && parseInt(pd.scale, 10) !== 100) o.scale_pct = parseInt(pd.scale, 10);
  if (pd.margin) o.margin_mm = parseFloat(pd.margin);
  if (pd.paper) o.paper_size = pd.paper;
  return o;
}

async function refreshCaps() {
  const note = $("capsNote");
  const p = $("defaultPrinter").value;
  if (!p) {
    CAPS = null;
    note.innerHTML = "Using the OS default printer - the hub reports what it supports per job.";
    return;
  }
  const r = await send({ type: "hubCaps", name: p });
  if (!r.ok) {
    CAPS = null;
    note.innerHTML = "Could not read capabilities (hub offline?).";
    return;
  }
  CAPS = r.caps;
  const parts = [];
  parts.push("backend: <b>" + (r.caps.backend || "?") + "</b>");
  if (r.caps.pages) parts.push("odd/even pages: <b>" + (r.caps.pages.odd_even ? "yes" : "no") + "</b>");
  if (r.caps.copies) parts.push("copies: <b>" + r.caps.copies.max + "</b>");
  if (r.caps.per_sheet) parts.push("per-sheet: <b>" +
    (Array.isArray(r.caps.per_sheet) ? r.caps.per_sheet.join("/") : r.caps.per_sheet) + "</b>");
  else parts.push("per-sheet: <b>no (driver)</b>");
  if (r.caps.quality) {
    if (Array.isArray(r.caps.quality)) parts.push("quality: <b>" + r.caps.quality.join("/") + "</b>");
    else parts.push("quality: <b>" + (r.caps.quality.presets || []).join("/") +
                    "</b>, dpi: <b>" + (r.caps.quality.dpi ? (Array.isArray(r.caps.quality.dpi) ? r.caps.quality.dpi.join("/") : r.caps.quality.dpi) : "driver decides") + "</b>");
  }
  if (r.caps.duplex) parts.push("duplex: <b>" + r.caps.duplex.join("/") + "</b>");
  if (r.caps.tray === null) parts.push("tray: <b>no</b>");
  note.innerHTML = "<b>" + p + "</b> supports: " + parts.join(" &middot; ");
}

/* ---------- v2.2: LAN sharing + peers (LAN / PCs tab) ---------- */
async function loadLan() {
  const st = await send({ type: "hubStatus" });
  const dot = $("lanDot"), state = $("lanState"), url = $("lanUrl");
  if (!st.ok) {
    dot.className = "dot offline";
    state.textContent = "Hub offline";
    url.textContent = "start the hub first";
    $("bLanToggle").textContent = "Enable";
    $("peersBody").innerHTML = '<tr><td colspan="4">Hub offline.</td></tr>';
    return;
  }
  const on = !!st.share_lan;
  dot.className = "dot" + (on ? "" : " paused");
  state.textContent = on ? "ON - other PCs can print through this PC" : "OFF - this PC only (127.0.0.1)";
  url.textContent = on ? (st.lan_url || "") : "";
  if (on && st.lan_active === false)
    state.textContent = "SAVED - restart the hub (tray icon > Exit, start again) to apply";
  $("bLanToggle").textContent = on ? "Disable" : "Enable";
  const pr = await send({ type: "hubPeers" });
  const peers = (pr.ok && (pr.peers || pr.parsed)) || [];
  const body = $("peersBody");
  if (!peers.length) {
    body.innerHTML = '<tr><td colspan="4">No peer PCs configured. Add them in the hub config.json under "peer_hubs" - see About > Open user guide. (You can still shift by typing the other PC\'s LAN URL below.)</td></tr>';
    return;
  }
  body.innerHTML = "";
  for (const p of peers) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="mono">${p.url || ""}</td>` +
      `<td><span class="st ${p.alive ? "printed" : "failed"}">${p.alive ? "online" : "offline"}</span></td>` +
      `<td>${p.version || ""}</td>`;
    const td = document.createElement("td");
    const b = document.createElement("button");
    b.className = "mini"; b.textContent = "Shift all waiting";
    b.addEventListener("click", async () => {
      if (!confirm("Shift ALL waiting jobs to " + p.url + "?")) return;
      const r = await send({ type: "queueShift", scope: "all", target: p.url });
      alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
      loadLan();
    });
    td.appendChild(b);
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

/* ---------- load / save ---------- */
async function loadPrinters() {
  const r = await send({ type: "hubPrinters" });
  PRINTERS = (r.ok && r.printers) || [];
  const sel = $("defaultPrinter");
  sel.innerHTML = "";
  sel.appendChild(new Option("OS default printer", ""));
  sel.appendChild(new Option("File (save as PDF, no paper)", "__file__"));
  PRINTERS.forEach((p) =>
    sel.appendChild(new Option(
      p.name + (p.is_group ? "  (group)"
              : (p.status && p.status !== "unknown"
                 ? "  [" + p.status + "]" : "") +
              (p.is_default ? "  (OS default)" : ""), p.name))));
  // refresh printer dropdowns in rules
  const cfg = await send({ type: "getCfg" });
  if (cfg.ok) renderRules(cfg.cfg.rules);
}

async function loadAll() {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const c = cfg.cfg;
  $("hubUrl").value = c.hubUrl || "";
  $("token").value = c.token || "";
  $("enabled").checked = c.enabled !== false;
  $("queueMode").checked = c.queueMode !== false;
  $("retryOffline").checked = c.retryOffline !== false;
  $("langSelect").value = c.lang || "auto";
  $("autoPrintAllPdfs").checked = c.autoPrintAllPdfs !== false;
  $("hookPrint").checked = !!c.hookPrint;
  $("closeAfterPrint").checked = c.closeAfterPrint !== false;
  $("failFallback").value = c.failFallback === "none" ? "none" : "tab";
  $("contextMenu").checked = !!c.contextMenu;
  $("badge").checked = !!c.badge;
  applyPrintDefaults(c.printDefaults);
  await loadPrinters();
  $("defaultPrinter").value = c.defaultPrinter || "";
  refreshCaps();
  testHub(false);
}

async function saveAll() {
  const r = await send({
    type: "saveCfg",
    patch: {
      hubUrl: $("hubUrl").value.trim() || "http://127.0.0.1:9235",
      token: $("token").value.trim() || "PrintHub-2024",
      enabled: $("enabled").checked,
      queueMode: $("queueMode").checked,
      retryOffline: $("retryOffline").checked,
      lang: $("langSelect").value || "auto",
      defaultPrinter: $("defaultPrinter").value,
      autoPrintAllPdfs: $("autoPrintAllPdfs").checked,
      hookPrint: $("hookPrint").checked,
      closeAfterPrint: $("closeAfterPrint").checked,
      failFallback: $("failFallback").value,
      contextMenu: $("contextMenu").checked,
      badge: $("badge").checked,
      printDefaults: PD(),
      rules: collect()
    }
  });
  saved(r.ok ? "Saved" : "Save failed: " + r.error);
}

/* ---------- hub test ---------- */
async function testHub(verbose = true) {
  const prev = await send({ type: "getCfg" });
  if (prev.ok) {
    // test with what's typed, not what's stored
    await send({ type: "saveCfg", patch: {
      hubUrl: $("hubUrl").value.trim() || prev.cfg.hubUrl,
      token: $("token").value.trim() || prev.cfg.token } });
  }
  const r = await send({ type: "hubStatus" });
  $("hubState").textContent = r.ok
    ? "CONNECTED - v" + r.version + " - " +
      ((r.printers_count) || "") + (r.default_printer ? " default: " + r.default_printer : "")
    : "OFFLINE - start the hub first";
  $("hubState").style.color = r.ok ? "#16a34a" : "#dc2626";
  if (r.ok) await loadPrinters();
  if (verbose) await loadAll();
}

/* ---------- jobs ---------- */
async function loadJobs() {
  const r = await send({ type: "hubJobs", limit: 100 });
  const body = $("jobsBody");
  body.innerHTML = "";
  if (!r.ok) {
    body.innerHTML = '<tr><td colspan="7">Hub offline - start it with: python printhub.py serve</td></tr>';
    return;
  }
  for (const j of r.jobs || []) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${j.id}</td><td class="mono">${(j.created_at || "").replace("T", " ")}</td>` +
      `<td>${(j.title || "-").slice(0, 42)}</td><td>${(j.printer || "default").slice(0, 28)}</td>` +
      `<td>${j.kind}</td><td><span class="st ${j.status}">${j.status}</span></td>`;
    const tdBtn = document.createElement("td");
    if (j.status === "queued" || j.status === "printing" || j.status === "scheduled"
        || j.status === "held") {
      const bc = document.createElement("button");
      bc.className = "mini danger"; bc.textContent = "Cancel";
      bc.addEventListener("click", async () => {
        await send({ type: "jobAction", id: j.id, action: "cancel" });
        loadJobs();
      });
      tdBtn.appendChild(bc);
    } else if (j.status === "failed" || j.status === "dead" || j.status === "canceled") {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Retry";
      br.title = "Queue this job again - choose another printer if you like";
      br.addEventListener("click", async () => {
        const p = prompt("Retry on which printer? (empty = the same printer)",
                         j.printer || "");
        if (p === null) return;                       // user canceled
        await send({ type: "jobRetry", id: j.id, printer: p.trim() });
        loadJobs();
      });
      tdBtn.appendChild(br);
    } else {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Reprint";
      br.addEventListener("click", async () => {
        const reason = prompt("Reprint - reason? (saved to the audit log)");
        if (reason === null) return;
        await send({ type: "jobReprint", id: j.id, reason: reason });
        loadJobs();
      });
      tdBtn.appendChild(br);
    }
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  }
  if (!(r.jobs || []).length) {
    body.innerHTML = '<tr><td colspan="7">No jobs yet.</td></tr>';
  }
}

/* ---------- wire up ---------- */
$("bTestHub").addEventListener("click", () => testHub(true));
$("bReloadPrinters").addEventListener("click", loadPrinters);
$("bAddRule").addEventListener("click", () => {
  $("rulesBody").appendChild(ruleRow({ pattern: "", printer: "", action: "auto", auto: false }));
});
$("bSave").addEventListener("click", saveAll);
$("bTestPage").addEventListener("click", async () => {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const base = cfg.cfg.hubUrl.replace(/\/+$/, "");
  const res = await fetch(base + "/testprint?kind=a4", {
    headers: { "X-PrintHub-Token": cfg.cfg.token }
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  saved(res.ok ? "Test page queued" : "Failed: " + (res.error || "offline"));
  loadJobs();
});
$("bPrintPdf").addEventListener("click", async () => {
  const url = $("pdfUrl").value.trim();
  if (!url) return saved("Enter a PDF URL first");
  const r = await send({ type: "printPdfUrl", url, title: "manual-print" });
  saved(r.ok ? "Queued as job #" + r.job_id : "Failed: " + r.error);
  loadJobs();
});
$("bReloadJobs").addEventListener("click", loadJobs);
$("bClearHist").addEventListener("click", async () => {
  await chrome.storage.local.set({ history: [] });
  saved("Extension history copy cleared (hub history untouched)");
});
["enabled", "queueMode", "retryOffline", "autoPrintAllPdfs", "hookPrint",
 "closeAfterPrint", "failFallback", "contextMenu", "badge", "defaultPrinter"].forEach((id) =>
  $(id).addEventListener("change", saveAll));

$("langSelect").addEventListener("change", async () => {
  await saveAll();
  const lang = await PrintHubI18n.currentLang();
  PrintHubI18n.apply(lang);
});

/* v2.0: hub dashboard + audit log (token comes from the saved config) */
async function openHubPath(path) {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const base = (cfg.cfg.hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
  chrome.tabs.create({ url: base + path + "?token=" +
                       encodeURIComponent(cfg.cfg.token || "") });
}
$("bDashboard").addEventListener("click", () => openHubPath("/dashboard"));
$("bAudit").addEventListener("click", () => openHubPath("/audit"));
$("bOpenDocs").addEventListener("click", () => openHubPath("/docs"));

/* ---------- v2.2: LAN / PCs wiring ---------- */
$("bLanToggle").addEventListener("click", async () => {
  const st = await send({ type: "hubStatus" });
  if (!st.ok) return alert("Hub offline - start it first");
  const on = !st.share_lan;
  if (!confirm(on ?
      "Enable LAN sharing?\n\nAfter this, RESTART the hub (tray icon > Exit, start again) and allow TCP 9235 through the firewall. Other PCs will need your token." :
      "Disable LAN sharing? Other PCs will no longer reach this printer.")) return;
  const r = await send({ type: "hubConfigSet", patch: { share_lan: on } });
  if (r.ok) alert(on ?
      "Saved. NOW: 1) restart the hub (tray icon > Exit, start PrintHub Pro again)  2) allow TCP 9235 through the firewall.\nThis PC's LAN URL will be shown after the restart." :
      "Saved. Restart the hub to fully apply.");
  else alert("Failed: " + r.error);
  loadLan();
});
$("bLanCopy").addEventListener("click", async () => {
  const u = $("lanUrl").textContent.trim();
  if (!u) return;
  try { await navigator.clipboard.writeText(u); alert("Copied: " + u); }
  catch (_) { prompt("Copy this LAN URL:", u); }
});
$("bLanRefresh").addEventListener("click", loadLan);
$("bShiftAll").addEventListener("click", async () => {
  const target = $("shiftTarget").value.trim();
  if (!target) return alert("Enter the other PC's LAN URL first\n(e.g. http://192.168.0.60:9235)");
  if (!confirm("Shift ALL waiting jobs to " + target + "?")) return;
  const r = await send({ type: "queueShift", scope: "all", target,
                         targetToken: $("shiftToken").value.trim() });
  alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
  loadLan();
});

/* default print options: save on change + capability hints */
["dCopies", "dPagesMode", "dPagesCustom", "dQuality", "dQualityCustom",
 "dPerSheet", "dDuplex", "dOrient", "dScale", "dMargin", "dPaper"]
 .forEach((id) => $(id).addEventListener("change", saveAll));
$("dPagesMode").addEventListener("change", () => {
  $("dPagesCustom").style.display = $("dPagesMode").value === "custom" ? "" : "none";
});
$("dQuality").addEventListener("change", () => {
  $("dQualityCustom").style.display = $("dQuality").value === "custom" ? "" : "none";
});
$("defaultPrinter").addEventListener("change", refreshCaps);

/* ---------- tab bar + queue/about wiring ---------- */
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
$("bQPause").addEventListener("click", async () => {
  const st = await send({ type: "hubStatus" });
  await send({ type: "queueAction", action: st.ok && st.paused ? "resume" : "pause" });
  refreshQueue();
});
$("bQClear").addEventListener("click", async () => {
  await send({ type: "queueAction", action: "clear" });
  refreshQueue();
});
$("bQRefresh").addEventListener("click", refreshQueue);
$("bUpdateCheck").addEventListener("click", updateCheck);

loadAll();
pickDefaultTab();
PrintHubI18n.currentLang().then((lang) => PrintHubI18n.apply(lang));
