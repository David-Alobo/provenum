// Page wiring for the provenum web app. The review logic lives in review.js.
import {
  acceptSingles, escapeHtml, filterItems, fitting, groupItems, initialDecisions, markSentence,
  progressText, summary,
} from "./review.js";

const $ = (id) => document.getElementById(id);
const CATEGORY_HELP = {
  check: "Several cells hold the same value, or no model was asked. Same-value cells are the case the value check cannot catch, so pick the one the sentence means.",
  traced: "The only cell with this value, and the model's choice. Change any that are wrong.",
  untraced: "No cell matches, or the model judged none is meant. These stay as typed unless you pick a cell.",
};
let sid = null;
let state = null;
let decisions = {};
let tab = "check";

/** Show or clear the error line. @param {string} [message] */
function showError(message) {
  $("error").hidden = !message;
  $("error").textContent = message || "";
}

/**
 * Call the API and return the JSON body; errors become exceptions with the server's message.
 * @param {string} path URL path.
 * @param {RequestInit} [init] Fetch options.
 * @returns {Promise<object>}
 */
async function api(path, init) {
  const r = await fetch(path, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `request failed (${r.status})`);
  return body;
}

/** Run an async action with the error line cleared first and filled on failure. */
async function guarded(action) {
  showError("");
  try { await action(); } catch (err) { showError(err.message); }
}

function render() {
  if (!state) return;
  $("project-info").innerHTML = `${state.tex_files.length} .tex file(s); main file
    <code>${escapeHtml(state.main)}</code>`;
  $("step-tables").hidden = false;
  $("table-dirs").innerHTML = state.table_dirs.map((d) =>
    `<button class="secondary" data-dir="${escapeHtml(d)}">Use project folder ${escapeHtml(d || "(top level)")}</button>`).join("");
  const hasSpec = Boolean(state.spec);
  $("step-spec").hidden = !hasSpec;
  $("step-run").hidden = !hasSpec;
  if (hasSpec) {
    $("tables-info").textContent = `Using ${state.tables === "upload" ? "the uploaded tables" : `project folder ${state.tables}`}.`;
    if (document.activeElement !== $("spec")) $("spec").value = state.spec;
    $("spec-info").textContent = `${state.n_tables} tables, ${state.n_values} values` +
      (state.checks ? `; ${state.checks} key guess(es) marked CHECK` : "");
  }
  renderRun();
  $("step-review").hidden = !state.items.length;
  if (state.items.length) renderReview();
  $("step-done").hidden = !state.applied;
  if (state.applied) renderDone();
}

function renderRun() {
  const run = state.run;
  $("run-info").textContent = progressText(run);
  $("run").disabled = run.status === "running";
  $("run-progress").hidden = run.status !== "running";
  if (run.total) { $("run-progress").max = run.total; $("run-progress").value = run.done; }
}

function renderReview() {
  const s = summary(state.items, decisions);
  $("summary").innerHTML = `<div><b>${s.total}</b>numbers typed by hand</div>
    <div><b class="status-ok">${s.linked}</b>will be linked</div>
    <div><b>${s.left}</b>left as typed</div>
    <div><b class="status-warn">${s.undecidedChecks}</b>to confirm, not yet chosen</div>`;
  $("accept-singles").hidden = Boolean(state.run.model);
  const groups = groupItems(state.items);
  for (const b of document.querySelectorAll(".tabs button")) {
    b.setAttribute("aria-selected", String(b.dataset.cat === tab));
    b.querySelector("span").textContent = `(${groups[b.dataset.cat].length})`;
  }
  $("cat-help").textContent = CATEGORY_HELP[tab];
  const shown = filterItems(groups[tab], $("search").value);
  $("items").innerHTML = shown.map(itemHtml).join("") ||
    `<li class="info">Nothing in this list.</li>`;
}

/** @param {object} it A number. @returns {string} HTML for its review row. */
function itemHtml(it) {
  const fit = fitting(it);
  const options = [`<option value="">Leave as typed</option>`].concat(fit.map((c) =>
    `<option value="${escapeHtml(c.path)}" ${decisions[it.key] === c.path ? "selected" : ""}>${escapeHtml(c.path)} = ${escapeHtml(c.text)}${c.path === it.pick ? " (model's choice)" : ""}</option>`));
  const other = it.candidates.length - fit.length;
  return `<li>
    <div class="where">${escapeHtml(it.file)}, line ${it.line}</div>
    <div>${markSentence(it.sentence)}</div>
    <div class="reason">${escapeHtml(it.reason)}${other ? `; ${other} more cell(s) match the value but print differently` : ""}</div>
    ${fit.length ? `<select data-key="${escapeHtml(it.key)}" aria-label="Cell for ${escapeHtml(it.written)}">${options.join("")}</select>` : ""}
  </li>`;
}

function renderDone() {
  const a = state.applied;
  $("done-info").innerHTML = `<p><b>${a.replaced}</b> numbers now read their values from
    <code>${escapeHtml(a.numbers_file)}</code>; ${a.left} decimal(s) are still typed by hand.
    ${a.input_added ? `An <code>\\input</code> line was added to <code>${escapeHtml(state.main)}</code>.` : ""}</p>`;
  for (const [id, f] of [["dl-project", "project.zip"], ["dl-report", "report.html"], ["dl-spec", "numbers.toml"]]) {
    $(id).href = `/api/session/${sid}/download/${f}`;
  }
}

async function poll() {
  state = await api(`/api/session/${sid}`);
  if (state.run.status === "running") { renderRun(); setTimeout(() => guarded(poll), 1000); return; }
  decisions = initialDecisions(state.items);
  render();
}

async function loadModels() {
  const host = $("host").value;
  const { models } = await api(`/api/models?host=${encodeURIComponent(host)}`);
  $("model").innerHTML = `<option value="">No model: I will choose</option>` +
    models.map((m) => `<option>${escapeHtml(m)}</option>`).join("");
  const preferred = models.find((m) => m.startsWith("qwen3:32b")) || models.find((m) => m.startsWith("qwen"));
  if (preferred) $("model").value = preferred;
}

$("project-file").addEventListener("change", (e) => guarded(async () => {
  const file = e.target.files[0];
  if (!file) return;
  $("project-info").textContent = "Reading the project…";
  const r = await api("/api/session", { method: "POST", body: file, headers: { "Content-Type": "application/zip" } });
  sid = r.id; state = r.state; decisions = {};
  location.hash = sid; // a reload comes back to this session
  render();
  await loadModels().catch(() => {});
}));

$("tables-file").addEventListener("change", (e) => guarded(async () => {
  const file = e.target.files[0];
  if (!file) return;
  $("tables-info").textContent = "Reading the tables…";
  state = await api(`/api/session/${sid}/tables`, { method: "POST", body: file, headers: { "Content-Type": "application/zip" } });
  render();
}));

$("table-dirs").addEventListener("click", (e) => guarded(async () => {
  const dir = e.target.closest("button")?.dataset.dir;
  if (dir === undefined) return;
  state = await api(`/api/session/${sid}/tables`, { method: "POST", body: JSON.stringify({ folder: dir }), headers: { "Content-Type": "application/json" } });
  render();
}));

$("save-spec").addEventListener("click", () => guarded(async () => {
  state = await api(`/api/session/${sid}/spec`, { method: "PUT", body: $("spec").value });
  render();
}));

$("host").addEventListener("change", () => guarded(loadModels));

$("run").addEventListener("click", () => guarded(async () => {
  state = await api(`/api/session/${sid}/run`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: $("model").value, host: $("host").value, notes: $("notes").value }) });
  tab = "check";
  await poll();
}));

$("items").addEventListener("change", (e) => {
  const key = e.target.dataset.key;
  if (key) { decisions[key] = e.target.value || null; renderReview(); }
});
$("search").addEventListener("input", renderReview);
$("accept-singles").addEventListener("click", () => { decisions = acceptSingles(state.items, decisions); renderReview(); });
document.querySelector(".tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) { tab = b.dataset.cat; renderReview(); }
});

if (location.hash.length > 1) {
  guarded(async () => {
    sid = location.hash.slice(1);
    await poll();
    await loadModels().catch(() => {});
  });
}

$("apply").addEventListener("click", () => guarded(async () => {
  $("apply").disabled = true;
  $("apply-info").textContent = "Building…";
  try {
    state = await api(`/api/session/${sid}/apply`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions }) });
    render();
    $("step-done").scrollIntoView({ behavior: "smooth" });
  } finally { $("apply").disabled = false; $("apply-info").textContent = ""; }
}));
