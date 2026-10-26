/* PrintHub Pro v1.7.2 - popup logic */
const $ = (id) => document.getElementById(id);
let paused = false;
let curTabUrl = "";

/* ---- v1.7.2 master enable/disable ---- */
async function reflectEnabled(on) {
  document.body.classList.toggle("off", !on);
  $("mstate").textContent = on ? "ON" : "OFF";
  $("mstate").classList.toggle("off", !on);
  $("enabledToggle").checked = !!on;
  ["bPage", "bFile", "bShot", "bTest"].forEach((id) => { $(id).disabled = !on; });
  if (!on) msg("PrintHub is disabled - silent printing is OFF", "err");
}

async function loadEnabled() {
  const cfg = await send({ type: "getCfg" });
  await reflectEnabled(cfg.ok ? cfg.cfg.enabled !== false : true);
}

$("enabledToggle").addEventListener("change", async () => {
  const r = await send({ type: "setEnabled", value: $("enabledToggle").checked });
  if (r.ok) {
    await reflectEnabled(r.enabled);
    msg(r.enabled ? "PrintHub enabled - printing is back ON"
                  : "PrintHub disabled - nothing will print", "info");
  } else {
    msg("Failed: " + r.error, "err");
    $("enabledToggle").checked = !$("enabledToggle").checked;
  }
});

function siteLabel(blocked) {
  return blocked
    ? "Auto-print on this site: BLOCKED (click to allow)"
    : "Auto-print on this site: ON (click to block)";
}

function msg(text, cls) {
  const el = $("msg");
  el.textContent = text || "";
  el.className = cls || "";
}

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}

async function refresh() {
  const st = await send({ type: "hubStatus" });
  if (st.ok) {
    $("dot").classList.add("on");
    $("stat").textContent = `Connected - hub v${st.version} on ${st.os}`;
    $("connect").textContent = "";
    paused = !!st.paused;
    $("qstate").textContent = paused ? "PAUSED" : "running";
    $("bPause").textContent = paused ? "Resume" : "Pause";
    $("qpend").textContent = st.pending ? st.pending + " pending" : "";
    // v1.7.2 queue mode chip
    const qm = st.queue_mode !== false;
    $("qmode").textContent = qm ? "(queue mode)" : "(direct mode)";
    $("qmode").title = qm
      ? "Queue mode ON - failed jobs stay queued and are retried"
      : "Queue mode OFF - jobs that cannot print fail immediately (Options > Queue)";
  } else {
    $("dot").classList.remove("on");
    $("stat").textContent = "Hub offline";
    $("connect").textContent = "Connect";
    $("qstate").textContent = "-";
    $("qpend").textContent = "";
    $("qmode").textContent = "";
    msg("Hub not reachable. Start it:  python printhub.py serve", "err");
  }

  const jobs = await send({ type: "hubJobs", limit: 8 });
  const box = $("jobs");
  box.innerHTML = "";
  if (jobs.ok && jobs.jobs && jobs.jobs.length) {
    for (const j of jobs.jobs) {
      const d = document.createElement("div");
      d.className = "job";
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = j.title || ("job #" + j.id);
      t.title = (j.title || "") + (j.error ? " - " + j.error : "");
      const s = document.createElement("span");
      s.className = "st " + j.status;
      s.textContent = j.status;
      const m = document.createElement("span");
      m.className = "m";
      m.textContent = (j.printer || "default");
      d.append(t, s, m);
      box.appendChild(d);
    }
  } else {
    box.innerHTML = '<div class="empty">No jobs yet - print something!</div>';
  }
}

/* ---- site auto-print block/unblock (v1.7.0) ---- */
chrome.tabs.query({ active: true, currentWindow: true }, ([t]) => {
  curTabUrl = (t && t.url) || "";
  const btn = $("bSiteBlock");
  if (!/^https?:/i.test(curTabUrl)) {
    btn.disabled = true;
    btn.textContent = "Auto-print toggle (not available on this page)";
    return;
  }
  send({ type: "siteBlockState", url: curTabUrl }).then((r) => {
    btn.textContent = siteLabel(r.ok && r.blocked);
  });
});

$("bSiteBlock").addEventListener("click", async () => {
  if (!/^https?:/i.test(curTabUrl)) return;
  const st = await send({ type: "siteBlockState", url: curTabUrl });
  const r = await send({ type: "setSiteBlocked", url: curTabUrl,
                         blocked: !(st.ok && st.blocked) });
  if (r.ok) {
    $("bSiteBlock").textContent = siteLabel(r.blocked);
    msg(r.blocked ? ("Auto-print blocked on " + r.host)
                  : ("Auto-print allowed again on " + r.host), "info");
  } else msg("Failed: " + r.error, "err");
});

$("bPage").addEventListener("click", async () => {
  msg("Sending page to printer...", "info");
  const r = await send({ type: "printTab" });
  if (r.ok) { msg("Queued as job #" + r.job_id + " - check the printer", "info"); refresh(); }
  else msg("Failed: " + r.error, "err");
});

$("bFile").addEventListener("click", async () => {
  msg("Saving page as PDF file...", "info");
  const r = await send({ type: "printTab", dest: "file" });
  if (r.ok) {
    msg("Saved: " + (r.file || ("job #" + r.job_id)) +
        "  (open it from the hub history)", "info");
    refresh();
  } else msg("Failed: " + r.error, "err");
});

$("bShot").addEventListener("click", async () => {
  msg("Capturing screenshot...", "info");
  const r = await send({ type: "printScreenshot" });
  if (r.ok) { msg("Screenshot queued as job #" + r.job_id, "info"); refresh(); }
  else msg("Failed: " + r.error, "err");
});

$("bTest").addEventListener("click", async () => {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return msg("Config error", "err");
  const base = cfg.cfg.hubUrl.replace(/\/+$/, "");
  const res = await fetch(base + "/testprint?kind=a4", {
    headers: { "X-PrintHub-Token": cfg.cfg.token }
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (res.ok) { msg("Test page queued as job #" + res.job_id, "info"); refresh(); }
  else msg("Failed: " + (res.error || "hub offline"), "err");
});

$("bPause").addEventListener("click", async () => {
  const r = await send({ type: "queueAction", action: paused ? "resume" : "pause" });
  if (r.ok) refresh(); else msg("Failed: " + r.error, "err");
});

$("bOpts").addEventListener("click", () => chrome.runtime.openOptionsPage());
$("lnkApi").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: chrome.runtime.getURL("options.html#api") });
});
$("lnkBrand").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "https://www.bitdreamit.com" });
});
$("connect").addEventListener("click", (e) => { e.preventDefault(); refresh(); });

refresh();
loadEnabled();   // v1.7.2: reflect the master switch on open
