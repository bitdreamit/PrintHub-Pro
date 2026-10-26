/* PrintHub Pro - options page logic */
const $ = (id) => document.getElementById(id);
let PRINTERS = [];
let QUEUE_TIMER = null;

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}
function saved(text) {
  $("saveMsg").textContent = text || "Saved";
  setTimeout(() => { $("saveMsg").textContent = ""; }, 2500);
}

/* ---------- tabs (Queue | History | Settings | About) ---------- */
function showTab(name) {
  const valid = ["queue", "history", "settings", "about"].includes(name)
    ? name : "settings";
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === valid));
  document.querySelectorAll("section.panel").forEach((p) =>
    p.classList.toggle("active", p.id === "panel-" + valid));
  if (valid === "queue") startQueueLoop(); else stopQueueLoop();
  if (valid === "history") loadJobs();
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
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  }
}

/* ---------- GitHub update check ---------- */
async function updateCheck() {
  const out = $("updState"), live = $("updLive");
  out.textContent = "checking...";
  live.innerHTML = "";
  let manifestVer = "2.0.2";
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
  await loadPrinters();
  $("defaultPrinter").value = c.defaultPrinter || "";
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
