// groundwork local UI. Plain JS, no build step.
const $ = (id) => document.getElementById(id);
const state = { meta: null, slug: null, topic: null };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
  });
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : res;
  if (!res.ok) throw new Error((data && data.error) || res.statusText);
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function copy(text, what = "Copied") {
  try { await navigator.clipboard.writeText(text); toast(what); }
  catch { toast("Copy failed: select the text and copy it by hand."); }
}

function busy(btn, on, label) {
  if (on) { btn.dataset.label = btn.textContent; btn.textContent = label || "Working..."; btn.disabled = true; }
  else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
}

// ------------------------------------------------------------------ boot

async function boot() {
  state.meta = await api("/api/meta");
  $("keyBadge").textContent = state.meta.has_api_key ? "Claude API key found" : "Free mode (no API key)";
  $("genBtn").classList.toggle("hidden", !state.meta.has_api_key);
  $("ntWeb").disabled = !state.meta.has_api_key;
  const sel = $("target");
  for (const [p, formats] of Object.entries(state.meta.platforms))
    for (const f of formats) sel.add(new Option(`${p} / ${f}`, `${p}:${f}`));
  for (const name of Object.keys(state.meta.presets)) $("preset").add(new Option(name, name));
  fillTheme(state.meta.theme);
  await loadTopics();
}

async function loadTopics() {
  const topics = await api("/api/topics");
  const ul = $("topicList"); ul.innerHTML = "";
  for (const t of topics) {
    const li = document.createElement("li");
    li.innerHTML = `${esc(t.topic)}<small>${t.sources} sources, ${t.drafts.length} drafts</small>`;
    li.classList.toggle("active", t.slug === state.slug);
    li.onclick = () => openTopic(t.slug);
    ul.appendChild(li);
  }
  if (!topics.length) show("empty");
}

function show(which) {
  for (const id of ["empty", "newTopic", "topicView"]) $(id).classList.toggle("hidden", id !== which);
}

function tab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
  if (name === "design") refreshPreview();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => tab(b.dataset.tab)));

// ------------------------------------------------------------------ topics and sources

$("newTopicBtn").onclick = () => { state.slug = null; show("newTopic"); $("ntTopic").focus(); };

$("ntGo").onclick = async () => {
  const btn = $("ntGo");
  busy(btn, true, "Fetching...");
  $("ntStatus").textContent = "This can take a minute: every page is downloaded and saved.";
  try {
    const r = await api("/api/topics", { method: "POST", body: {
      topic: $("ntTopic").value, brief: $("ntBrief").value,
      urls: $("ntUrls").value.split("\n"), use_collectors: $("ntCollectors").checked,
      use_web_search: $("ntWeb").checked } });
    $("ntStatus").textContent = "";
    if (!r.sources.length) toast("No usable sources were found. Add links that contain real text.", 6000);
    await openTopic(r.slug);
  } catch (e) { $("ntStatus").textContent = e.message; }
  busy(btn, false);
};

$("moreGo").onclick = async () => {
  const btn = $("moreGo"); busy(btn, true, "Fetching...");
  try {
    await api("/api/topics", { method: "POST", body: {
      topic: state.topic.topic, brief: state.topic.brief, urls: $("moreUrls").value.split("\n"),
      use_collectors: false } });
    $("moreUrls").value = ""; await openTopic(state.slug);
  } catch (e) { $("moreStatus").textContent = e.message; }
  busy(btn, false);
};

async function openTopic(slug) {
  state.slug = slug;
  state.topic = await api(`/api/topics/${slug}`);
  $("tvTitle").textContent = state.topic.topic;
  $("tvBrief").textContent = state.topic.brief || "";
  renderSources(); renderDrafts(); renderBuild(state.topic.build);
  show("topicView"); loadTopics();
}

function renderSources() {
  const rows = state.topic.sources.map((s) => `<tr><td>${s.id}</td>
    <td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></td>
    <td>${esc(s.publisher)}</td><td>${s.chars.toLocaleString()} chars</td>
    <td><button data-remove="${s.id}">Remove</button></td></tr>`);
  $("srcRows").innerHTML = rows.join("") || `<tr><td colspan="5" class="muted">No sources yet. Add links below.</td></tr>`;
  $("srcRows").querySelectorAll("[data-remove]").forEach((b) => (b.onclick = async () => {
    await api(`/api/topics/${state.slug}/sources/remove`, { method: "POST", body: { id: b.dataset.remove } });
    openTopic(state.slug);
  }));
}

// ------------------------------------------------------------------ writing

$("promptBtn").onclick = async () => {
  try {
    const r = await api(`/api/topics/${state.slug}/prompt`, { method: "POST", body: { target: $("target").value } });
    await copy(r.prompt, "Prompt copied. Paste it into your chatbot.");
  } catch (e) { toast(e.message); }
};

$("checkBtn").onclick = async () => {
  const btn = $("checkBtn"); busy(btn, true, "Checking...");
  try {
    const r = await api(`/api/topics/${state.slug}/reply`, { method: "POST",
      body: { target: $("target").value, text: $("reply").value } });
    renderResult(r);
    if (r.status !== "unusable") { state.topic = await api(`/api/topics/${state.slug}`); renderDrafts(); loadTopics(); }
  } catch (e) { toast(e.message); }
  busy(btn, false);
};

$("genBtn").onclick = async () => {
  const btn = $("genBtn"); busy(btn, true, "Claude is writing...");
  try {
    const r = await api(`/api/topics/${state.slug}/generate`, { method: "POST", body: { target: $("target").value } });
    renderResult(r);
    state.topic = await api(`/api/topics/${state.slug}`); renderDrafts(); loadTopics();
  } catch (e) { toast(e.message, 8000); }
  busy(btn, false);
};

function findingsHtml(findings) {
  if (!findings || !findings.length) return "<p>No problems found.</p>";
  return `<ul class="findings">${findings.map((f) =>
    `<li class="${f.severity}"><b>${f.severity}</b> ${esc(f.message)}${f.excerpt ? ` <span class="muted">(${esc(f.excerpt)})</span>` : ""}</li>`).join("")}</ul>`;
}

function renderResult(r) {
  const label = { ready: "Passed every check", needs_fix: "Needs a fix", unusable: "Reply not usable" }[r.status];
  let html = `<p class="status ${r.status}">${label}</p>`;
  if (r.error) html += `<p>${esc(r.error)}</p>`;
  if (r.findings) html += findingsHtml(r.findings);
  if (r.fix_message) html += `<p>Paste this back into the same chat, then paste the new reply here:</p>
     <pre>${esc(r.fix_message)}</pre><button id="copyFix">Copy fix message</button>`;
  $("result").innerHTML = html; $("result").classList.remove("muted");
  const b = $("copyFix"); if (b) b.onclick = () => copy(r.fix_message, "Fix message copied.");
}

function renderDrafts() {
  const drafts = Object.values(state.topic.drafts || {});
  if (!drafts.length) { $("draftList").innerHTML = `<p class="muted">None yet.</p>`; return; }
  $("draftList").innerHTML = drafts.map((d) => {
    const slides = (d.draft.design?.slides || []).map((s, i) => ({ ...s, n: i + 1 })).filter((s) => s.visual);
    const visuals = slides.map((s) => `<div>Slide ${s.n} needs: ${esc(s.visual)}
        ${s.image ? `<b>(image attached)</b>` : ""}
        <input type="file" accept="image/png,image/jpeg,image/webp" data-attach="${d.target}" data-slide="${s.n}"></div>`).join("");
    return `<div class="draft"><div><b>${esc(d.target)}</b> <span class="status ${d.status}">${d.status === "ready" ? "ready" : "needs a fix"}</span>
        <div class="muted">${esc(d.draft.hook)}</div>${visuals ? `<div class="visuals">${visuals}</div>` : ""}</div>
      <div><button data-show="${d.target}">Show checks</button> <button data-del="${d.target}">Delete</button></div></div>`;
  }).join("");
  $("draftList").querySelectorAll("[data-show]").forEach((b) => (b.onclick = () => {
    $("target").value = b.dataset.show; renderResult(state.topic.drafts[b.dataset.show]);
  }));
  $("draftList").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    await api(`/api/topics/${state.slug}/drafts/remove`, { method: "POST", body: { target: b.dataset.del } });
    openTopic(state.slug);
  }));
  $("draftList").querySelectorAll("[data-attach]").forEach((inp) => (inp.onchange = async () => {
    const fd = new FormData();
    fd.append("target", inp.dataset.attach); fd.append("slide", inp.dataset.slide); fd.append("image", inp.files[0]);
    try { await api(`/api/topics/${state.slug}/attach`, { method: "POST", body: fd }); toast("Image attached. Rebuild in Posts."); openTopic(state.slug); }
    catch (e) { toast(e.message); }
  }));
}

// ------------------------------------------------------------------ design

const THEME_FIELDS = ["heading_font", "body_font", "font_family", "align", "accent_style", "cover_style", "handle"];
const COLORS = ["background", "foreground", "accent", "muted"];

function fillTheme(t) {
  if (state.meta.presets[t.name]) $("preset").value = t.name;
  for (const c of COLORS) $("c_" + c).value = t[c].toLowerCase();
  for (const f of THEME_FIELDS) $(f).value = t[f] ?? "";
  $("slide_counter").checked = !!t.slide_counter;
}

function themeBody() {
  const overrides = {};
  for (const c of COLORS) overrides[c] = $("c_" + c).value.toUpperCase();
  for (const f of THEME_FIELDS) overrides[f] = $(f).value;
  overrides.slide_counter = $("slide_counter").checked;
  return { preset: $("preset").value, overrides };
}

let previewTimer;
async function refreshPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const res = await fetch("/api/theme/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(themeBody()) });
      if (!res.ok) { $("themeWarnings").innerHTML = `<li>${esc((await res.json()).error)}</li>`; return; }
      const warnings = JSON.parse(res.headers.get("X-Theme-Warnings") || "[]");
      $("themeWarnings").innerHTML = warnings.map((w) => `<li>${esc(w)}</li>`).join("");
      const url = URL.createObjectURL(await res.blob());
      const img = $("previewImg"); if (img.src) URL.revokeObjectURL(img.src); img.src = url;
    } catch (e) { toast(e.message); }
  }, 250);
}

$("preset").onchange = () => { fillTheme(state.meta.presets[$("preset").value]); refreshPreview(); };
for (const id of [...COLORS.map((c) => "c_" + c), ...THEME_FIELDS, "slide_counter"]) {
  $(id).addEventListener("input", refreshPreview); $(id).addEventListener("change", refreshPreview);
}

$("saveTheme").onclick = async () => {
  try {
    const r = await api("/api/theme/save", { method: "POST", body: { ...themeBody(), save_as: $("saveAs").value } });
    state.meta.theme = r.theme;
    $("themeStatus").textContent = `Saved: ${r.written.join(", ")}`;
    if ($("saveAs").value) { state.meta = await api("/api/meta"); }
  } catch (e) { $("themeStatus").textContent = e.message; }
};

// ------------------------------------------------------------------ build and posts

$("buildBtn").onclick = async () => {
  const btn = $("buildBtn"); busy(btn, true, "Building...");
  try { renderBuild(await api(`/api/topics/${state.slug}/build`, { method: "POST", body: themeBody() })); toast("Built."); }
  catch (e) { toast(e.message, 6000); }
  busy(btn, false);
};

function renderBuild(b) {
  const list = $("postList");
  if (!b) { list.innerHTML = `<p class="muted">Nothing built yet.</p>`; $("icsLink").classList.add("hidden"); return; }
  $("icsLink").href = b.ics; $("icsLink").classList.remove("hidden");
  list.innerHTML = b.posts.map((p, i) => `<div class="post">
      <div class="row"><h4>${esc(p.platform)} / ${esc(p.format)}</h4>
        <span class="status ${p.status}">${p.status === "ready" ? "ready" : "needs review"}</span>
        <span class="muted">${p.scheduled_for ? "Scheduled " + new Date(p.scheduled_for).toLocaleString() : "Not scheduled"}</span></div>
      ${p.images.length ? `<div class="gallery">${p.images.map((u) => `<a href="${u}" target="_blank"><img src="${u}?t=${Date.now()}" alt="slide"></a>`).join("")}</div>` : ""}
      ${p.pdf ? `<p><a href="${p.pdf}" download>Download PDF for LinkedIn</a></p>` : ""}
      <details><summary>Post file (text to paste, sources, evidence, publish steps)</summary>
        <button data-copy="${i}">Copy all</button><pre>${esc(p.markdown)}</pre></details>
      ${p.canva ? `<details><summary>Canva steps</summary><pre>${esc(p.canva)}</pre></details>` : ""}
    </div>`).join("");
  list.querySelectorAll("[data-copy]").forEach((btn) => (btn.onclick = () => copy(b.posts[btn.dataset.copy].markdown)));
}

boot().catch((e) => toast("Could not start: " + e.message, 10000));
