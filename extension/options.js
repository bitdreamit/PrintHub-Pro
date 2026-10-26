/* PrintHub Pro v1.7.2 - options page logic (tabbed UI) */
const $ = (id) => document.getElementById(id);
let PRINTERS = [];

/* ---------- tabs (v1.7.2) ----------
   Opens on the QUEUE tab when the hub already has jobs, otherwise on
   SETTINGS. Any tab can be deep-linked: options.html#sharing etc. */
const TABS = ["queue", "settings", "sharing", "service", "api", "about"];
let ACTIVE_TAB = "settings";
let TAB_CHOSEN = false;

function showTab(id, push) {
  if (!TABS.includes(id)) id = "settings";
  ACTIVE_TAB = id;
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === id));
  TABS.forEach((t) => { const p = $("panel-" + t); if (p) p.hidden = (t !== id); });
  if (push) {
    try { history.replaceState(null, "", "#" + id); } catch (_) {}
  }
  if (id === "queue") loadJobs();
  if (id === "service") loadService();
}

function tabFromHash() {
  const h = (location.hash || "").replace("#", "");
  return TABS.includes(h) ? h : null;
}

function chooseDefaultTab(jobsCount) {
  if (TAB_CHOSEN) return;
  TAB_CHOSEN = true;
  showTab(tabFromHash() || (jobsCount > 0 ? "queue" : "settings"), true);
}

function updateQueueBadge(jobs) {
  const b = $("qBadge");
  if (!b) return;
  const list = jobs || [];
  const failed = list.filter((j) => j.status === "failed" || j.status === "canceled").length;
  const active = list.filter((j) => j.status === "queued" || j.status === "printing").length;
  b.textContent = String(list.length);
  b.classList.toggle("zero", list.length === 0);
  b.classList.toggle("blue", failed === 0);
  b.title = failed ? (failed + " failed - open the Queue tab to retry")
           : active ? (active + " waiting to print") : "print history";
}

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}
function saved(text) {
  $("saveMsg").textContent = text || "Saved";
  setTimeout(() => { $("saveMsg").textContent = ""; }, 2500);
}

/* ---------- rules table ---------- */
function ruleRow(rule) {
  const tr = document.createElement("tr");

  const tdP = document.createElement("td");
  const inP = document.createElement("input");
  inP.type = "text"; inP.value = rule.pattern || "";
  inP.placeholder = "*://example.com/reports/*";
  inP.addEventListener("change", collect);
  tdP.appendChild(inP);

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

  tr.append(tdP, tdPr, tdA, tdAuto, tdX);
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
    const [p, pr, a, auto] = tr.querySelectorAll("input, select, select, input");
    if (p.value.trim()) {
      rules.push({ pattern: p.value.trim(), printer: pr.value,
                   action: a.value, auto: auto.checked });
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
    sel.appendChild(new Option(p.name + (p.is_default ? "  (OS default)" : ""), p.name)));
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
  $("enabledToggle").checked = c.enabled !== false;   // v1.7.2 master switch
  $("autoPrintAllPdfs").checked = c.autoPrintAllPdfs !== false;
  $("hookPrint").checked = !!c.hookPrint;
  $("closeAfterPrint").checked = c.closeAfterPrint === true;   // v1.7.0: default OFF
  $("failFallback").value = c.failFallback === "none" ? "none" : "tab";
  $("contextMenu").checked = !!c.contextMenu;
  $("badge").checked = !!c.badge;
  $("blockedSites").value = (c.blockedSites || []).join("\n");
  await loadPrinters();
  $("defaultPrinter").value = c.defaultPrinter || "";
  testHub(false);
  loadShare();
}

async function saveAll() {
  const r = await send({
    type: "saveCfg",
    patch: {
      hubUrl: $("hubUrl").value.trim() || "http://127.0.0.1:9235",
      token: $("token").value.trim() || "PrintHub-2024",
      enabled: $("enabledToggle").checked,          // v1.7.2 master switch
      defaultPrinter: $("defaultPrinter").value,
      autoPrintAllPdfs: $("autoPrintAllPdfs").checked,
      hookPrint: $("hookPrint").checked,
      closeAfterPrint: $("closeAfterPrint").checked,
      failFallback: $("failFallback").value,
      contextMenu: $("contextMenu").checked,
      badge: $("badge").checked,
      blockedSites: $("blockedSites").value.split(/\n+/)
        .map((s) => s.trim().toLowerCase()).filter(Boolean),
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

/* ---------- sharing (v1.7.0) ---------- */
async function loadShare() {
  const r = await send({ type: "hubShare" });
  const st = $("shareState");
  if (!r.ok) {
    st.textContent = "hub offline";
    st.style.color = "#dc2626";
    return;
  }
  st.textContent = r.sharing ? "SHARED on the LAN" : "Local only (this PC)";
  st.style.color = r.sharing ? "#16a34a" : "#64748b";
  $("shareAddr").textContent = r.address || "-";
  $("shareLan").textContent = r.lan_ip ? ("(LAN IP: " + r.lan_ip + ")") : "";
  $("connectCode").textContent = r.connect_code || "(enable sharing to get the code)";
  $("shareToken").value = (r.token && r.token !== "****") ? r.token : "";
  $("forwardOnFail").checked = !!r.forward_on_fail;
  $("autoRetry").checked = !!r.auto_retry;
  // v1.7.2 Queue Mode switch (also shown on the Queue tab)
  const qm = r.queue_mode !== false;
  const qBox = $("queueMode");
  if (qBox) {
    qBox.checked = qm;
    const st = $("qModeState");
    if (st) {
      st.textContent = qm ? "ON" : "OFF";
      st.style.color = qm ? "#16a34a" : "#dc2626";
    }
  }
  $("retryMax").value = (r.retry_max != null) ? r.retry_max : 3;
  $("retryInt").value = (r.retry_interval != null) ? r.retry_interval : 60;
  $("peersBox").value = (r.peers || [])
    .map((p) => p.token ? (p.url + "|" + p.token) : p.url).join("\n");
}

async function sharePatch(patch, okMsg) {
  const r = await send({ type: "shareAction", patch });
  saved(r.ok ? okMsg : "Failed: " + r.error);
  if (r.ok) {
    await testHub(false);
    await loadShare();
  }
  return r;
}

function parsePeers(text) {
  return text.split(/\n+/).map((s) => s.trim()).filter(Boolean);
}

/* ---------- windows service (v1.7.2) ---------- */
async function loadService() {
  const st = await send({ type: "hubService", action: "status" });
  const el = $("svcState"), det = $("svcDetail");
  if (!st.ok) {
    el.textContent = "hub offline";
    el.style.color = "#dc2626";
    det.textContent = "";
  } else {
    const s = st.service;
    if (st.service_mode) {
      el.textContent = "RUNNING as the Windows service";
      el.style.color = "#16a34a";
      det.textContent = "this hub IS the service (session 0 - no tray icon)";
    } else if (!s) {
      el.textContent = "not available (not Windows)";
      el.style.color = "#64748b";
      det.textContent = "";
    } else if (!s.installed) {
      el.textContent = "Not installed (startup-app mode)";
      el.style.color = "#64748b";
      det.textContent = "install to see 'PrintHub Pro Service' in services.msc";
    } else {
      el.textContent = s.running ? "Installed & RUNNING" : "Installed (stopped)";
      el.style.color = s.running ? "#16a34a" : "#dc2626";
      det.textContent = "manage it in services.msc -> 'PrintHub Pro Service'";
    }
  }
  const a = await send({ type: "hubAutostart" });
  const as = $("autoStartState");
  if (a.ok) {
    as.textContent = a.enabled ? "ON (Startup app)" : "OFF";
    as.style.color = a.enabled ? "#16a34a" : "#64748b";
  } else {
    as.textContent = "hub offline";
    as.style.color = "#dc2626";
  }
}

/* ---------- jobs ---------- */
async function loadJobs() {
  const r = await send({ type: "hubJobs", limit: 200 });
  const body = $("jobsBody");
  body.innerHTML = "";
  if (!r.ok) {
    body.innerHTML = '<tr><td colspan="7">Hub offline - start it with: python printhub.py serve</td></tr>';
    updateQueueBadge([]);
    chooseDefaultTab(0);
    return;
  }
  updateQueueBadge(r.jobs || []);
  chooseDefaultTab((r.jobs || []).length);
  for (const j of r.jobs || []) {
    const tr = document.createElement("tr");
    const status = j.status || "queued";
    const tip = ((j.error || "") + (j.forwarded_to ? " -> " + j.forwarded_to : ""))
      .replace(/"/g, "").slice(0, 200);
    tr.innerHTML =
      `<td>${j.id}</td><td class="mono">${(j.created_at || "").replace("T", " ")}</td>` +
      `<td>${(j.title || "-").slice(0, 42)}</td><td>${(j.printer || "default").slice(0, 28)}</td>` +
      `<td>${j.kind}</td><td><span class="st ${status}" title="${tip}">${status}` +
      (j.attempts > 1 ? " x" + j.attempts : "") + `</span></td>`;
    const tdBtn = document.createElement("td");
    if (j.status === "queued" || j.status === "printing") {
      const bc = document.createElement("button");
      bc.className = "mini danger"; bc.textContent = "Cancel";
      bc.addEventListener("click", async () => {
        await send({ type: "jobAction", id: j.id, action: "cancel" });
        loadJobs();
      });
      tdBtn.appendChild(bc);
    } else if (j.status === "failed" || j.status === "forwarded" ||
               j.status === "canceled") {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Retry";
      br.title = "Put this job back into the queue";
      br.addEventListener("click", async () => {
        const rr = await send({ type: "jobAction", id: j.id, action: "retry" });
        saved(rr.ok ? "Job #" + j.id + " requeued" : "Failed: " + rr.error);
        loadJobs();
      });
      tdBtn.appendChild(br);
    } else {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Reprint";
      br.addEventListener("click", async () => {
        await send({ type: "jobAction", id: j.id, action: "reprint" });
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

async function clearJobs(scope, ask) {
  if (ask && !confirm(ask)) return;
  const r = await send({ type: "jobsClear", scope });
  saved(r.ok ? "Cleared " + r.deleted + " job(s)" : "Failed: " + r.error);
  loadJobs();
}

/* ---------- wire up ---------- */
$("bTestHub").addEventListener("click", () => testHub(true));
$("bReloadPrinters").addEventListener("click", loadPrinters);
$("bAddRule").addEventListener("click", () => {
  $("rulesBody").appendChild(ruleRow({ pattern: "", printer: "", action: "auto", auto: false }));
});
$("bSave").addEventListener("click", saveAll);

/* sharing */
$("bShareOn").addEventListener("click", () =>
  sharePatch({ enabled: true }, "Sharing enabled - other PCs use the connect code"));
$("bShareOff").addEventListener("click", () =>
  sharePatch({ enabled: false }, "Sharing stopped - hub is localhost-only again"));
$("bCopyCode").addEventListener("click", async () => {
  const code = $("connectCode").textContent.trim();
  if (!code || code.indexOf("|") < 0) return saved("Enable sharing first");
  try { await navigator.clipboard.writeText(code); saved("Connect code copied"); }
  catch (_) { saved("Copy failed - select the code manually"); }
});
$("bJoin").addEventListener("click", async () => {
  const code = $("joinCode").value.trim();
  const i = code.lastIndexOf("|");
  if (!/^https?:\/\//i.test(code) || i < 0) {
    return saved("Format: http://192.168.x.x:9235|TOKEN");
  }
  const url = code.slice(0, i).replace(/\/+$/, "");
  const tok = code.slice(i + 1).trim();
  await send({ type: "saveCfg", patch: { hubUrl: url, token: tok } });
  saved("Connected to " + url);
  await testHub(true);
});
$("bRegenToken").addEventListener("click", async () => {
  const r = await send({ type: "shareAction", patch: { regenerate_token: true } });
  if (r.ok) {
    // keep the extension's own token in sync with the hub
    await send({ type: "saveCfg", patch: { token: r.token } });
    $("token").value = r.token;
    saved("New token generated - update other PCs!");
    await testHub(false);
    await loadShare();
  } else saved("Failed: " + r.error);
});
$("bSaveShare").addEventListener("click", () =>
  sharePatch({
    forward_on_fail: $("forwardOnFail").checked,
    auto_retry: $("autoRetry").checked,
    retry_max: parseInt($("retryMax").value, 10) || 3,
    retry_interval: parseInt($("retryInt").value, 10) || 60,
    peers: parsePeers($("peersBox").value)
  }, "Queue settings saved"));

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

/* windows service + autostart (v1.7.2) */
$("bSvcInstall").addEventListener("click", async () => {
  $("svcDetail").textContent = "waiting for the Windows admin (UAC) prompt...";
  const r = await send({ type: "hubService", action: "install" });
  $("svcDetail").textContent = r.ok
    ? (r.detail || "service installed - open services.msc")
    : "failed: " + (r.error || r.detail || "unknown");
  saved(r.ok ? "Windows service installed" : "Service install failed");
  loadService();
});
$("bSvcRemove").addEventListener("click", async () => {
  $("svcDetail").textContent = "waiting for the Windows admin (UAC) prompt...";
  const r = await send({ type: "hubService", action: "remove" });
  $("svcDetail").textContent = r.ok
    ? (r.detail || "service removed")
    : "failed: " + (r.error || r.detail || "unknown");
  saved(r.ok ? "Windows service removed" : "Service removal failed");
  loadService();
});
$("bAutoStart").addEventListener("click", async () => {
  const r = await send({ type: "hubAutostartToggle" });
  saved(r.ok ? (r.enabled ? "Startup app ON" : "Startup app OFF")
             : "Failed: " + (r.error || "?"));
  loadService();
});

/* tabs */
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab, true)));

/* jobs */
$("bReloadJobs").addEventListener("click", loadJobs);
$("bClearFailed").addEventListener("click", () => clearJobs("failed"));
$("bClearCompleted").addEventListener("click", () =>
  clearJobs("completed", "Delete every printed/saved/canceled job from the hub history?"));
$("bClearAll").addEventListener("click", () =>
  clearJobs("all", "Delete the WHOLE hub job history (including queued jobs)? This cannot be undone."));
$("bClearHist").addEventListener("click", async () => {
  await chrome.storage.local.set({ history: [] });
  saved("Extension history copy cleared (hub history untouched)");
});

["enabledToggle", "autoPrintAllPdfs", "hookPrint", "closeAfterPrint", "failFallback", "contextMenu", "badge", "defaultPrinter"].forEach((id) =>
  $(id).addEventListener("change", saveAll));

/* v1.7.2 Queue Mode switch on the Queue tab - saves to the hub at once */
$("queueMode").addEventListener("change", async () => {
  const on = $("queueMode").checked;
  const r = await send({ type: "shareAction", patch: { queue_mode: on } });
  saved(r.ok ? (on ? "Queue mode ON - failed jobs stay queued and retry"
                   : "Queue mode OFF - jobs fail immediately if they cannot print")
             : "Failed: " + r.error);
  const st = $("qModeState");
  if (st) {
    st.textContent = on ? "ON" : "OFF";
    st.style.color = on ? "#16a34a" : "#dc2626";
  }
  if (r.ok) loadJobs();
});

try {
  $("aboutVer").textContent = chrome.runtime.getManifest().version;
} catch (_) {}

/* v1.7.2: refresh the queue list every 4 s while the Queue tab is visible */
setInterval(() => {
  if (ACTIVE_TAB === "queue" && !document.hidden) loadJobs();
}, 4000);

loadAll();
loadJobs();        // also picks the default tab (queue if jobs exist, else settings)
loadService();     // keeps the Windows-service tab ready before it is opened
