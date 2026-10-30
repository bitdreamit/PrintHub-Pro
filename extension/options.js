/* PrintHub Pro - options page logic */
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
  $("closeAfterPrint").checked = c.closeAfterPrint !== false;
  $("failFallback").value = c.failFallback === "none" ? "none" : "tab";
  $("contextMenu").checked = !!c.contextMenu;
  $("badge").checked = !!c.badge;
  $("instantPrint").checked = !!c.instantPrint;
  $("debugMode").checked = !!c.debugMode;
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
      defaultPrinter: $("defaultPrinter").value,
      autoPrintAllPdfs: $("autoPrintAllPdfs").checked,
      hookPrint: $("hookPrint").checked,
      closeAfterPrint: $("closeAfterPrint").checked,
      failFallback: $("failFallback").value,
      contextMenu: $("contextMenu").checked,
      badge: $("badge").checked,
      instantPrint: $("instantPrint").checked,
      debugMode: $("debugMode").checked,
      rules: collect()
    }
  });
  saved(r.ok ? "Saved" : "Save failed: " + r.error);
  if (r.ok) syncHubConfig();
}

/* v2.4.0: push the debug flag to the hub too, so /config + the audit
 * trail (config.changed "debug") and the live dashboard all agree. */
async function syncHubConfig() {
  try {
    const base = ($("hubUrl").value.trim() || "http://127.0.0.1:9235").replace(/\/+$/, "");
    const r = await fetch(base + "/config", {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 "X-PrintHub-Token": $("token").value.trim() || "PrintHub-2024" },
      body: JSON.stringify({ debug: $("debugMode").checked })
    }).then((x) => x.json());
    if (r.ok && r.changed && r.changed.length) {
      saved("Saved (hub: " + r.changed.join(", ") + " updated)");
    }
  } catch (_) { /* hub offline - local setting still stored */ }
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
  if (r.ok) {
    await loadPrinters();
    showDiag();
  }
  if (verbose) await loadAll();
}

/* v2.4.0: show hub-side diagnostics (sumatra / debug / held) in options */
async function showDiag() {
  try {
    const base = ($("hubUrl").value.trim() || "http://127.0.0.1:9235").replace(/\/+$/, "");
    const tok = $("token").value.trim() || "PrintHub-2024";
    const d = await fetch(base + "/debug?token=" + encodeURIComponent(tok), {
      headers: { "X-PrintHub-Token": tok } }).then((x) => x.json());
    if (!d || !d.ok) return;
    const bits = [];
    if (typeof d.sumatra_found === "boolean") {
      bits.push("SumatraPDF: " + (d.sumatra_found ? "found" : "NOT FOUND"));
    }
    bits.push("debug " + (d.debug ? "ON" : "OFF"));
    bits.push("held jobs: " + ((d.queue && d.queue.held) || 0));
    bits.push("queue " + (d.paused ? "PAUSED" : "running"));
    if (d.sumatra_path) bits.push("path: " + d.sumatra_path);
    $("diagInfo").textContent = bits.join("  |  ");
  } catch (_) {}
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
    if (j.status === "queued" || j.status === "printing") {
      const bc = document.createElement("button");
      bc.className = "mini danger"; bc.textContent = "Cancel";
      bc.addEventListener("click", async () => {
        await send({ type: "jobAction", id: j.id, action: "cancel" });
        loadJobs();
      });
      tdBtn.appendChild(bc);
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
["autoPrintAllPdfs", "hookPrint", "closeAfterPrint", "failFallback", "contextMenu", "badge", "instantPrint", "debugMode", "defaultPrinter"].forEach((id) =>
  $(id).addEventListener("change", saveAll));

/* v2.4.0: live debug + test tool shortcuts */
$("bDashboard").addEventListener("click", openHubPage("/dashboard"));
$("bDebugJson").addEventListener("click", openHubPage("/debug"));
$("bAuditLog").addEventListener("click", openHubPage("/audit"));
function openHubPage(path) {
  return async () => {
    const cfg = await send({ type: "getCfg" });
    if (!cfg.ok) return;
    const base = (cfg.cfg.hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
    chrome.tabs.create({ url: base + path + "?token=" + encodeURIComponent(cfg.cfg.token) });
  };
}

loadAll();
loadJobs();
