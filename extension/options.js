/* PrintHub Pro v1.7.0 - options page logic */
const $ = (id) => document.getElementById(id);
let PRINTERS = [];

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

/* ---------- jobs ---------- */
async function loadJobs() {
  const r = await send({ type: "hubJobs", limit: 200 });
  const body = $("jobsBody");
  body.innerHTML = "";
  if (!r.ok) {
    body.innerHTML = '<tr><td colspan="7">Hub offline - start it with: python printhub.py serve</td></tr>';
    return;
  }
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

["autoPrintAllPdfs", "hookPrint", "closeAfterPrint", "failFallback", "contextMenu", "badge", "defaultPrinter"].forEach((id) =>
  $(id).addEventListener("change", saveAll));

try {
  $("aboutVer").textContent = chrome.runtime.getManifest().version;
} catch (_) {}

loadAll();
loadJobs();
