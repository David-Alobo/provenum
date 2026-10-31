// Review logic for the provenum web app: no DOM here, so Vitest can test it directly.

export const CATEGORIES = ["check", "traced", "untraced"];

/**
 * Cells whose formatted value reproduces the written number (the only ones that can be applied).
 * @param {object} item A number from the session state.
 * @returns {object[]} Candidates with fits = true.
 */
export function fitting(item) {
  return item.candidates.filter((c) => c.fits);
}

/**
 * Split numbers into the three review lists, keeping manuscript order inside each.
 * @param {object[]} items Numbers from the session state.
 * @returns {{check: object[], traced: object[], untraced: object[]}}
 */
export function groupItems(items) {
  const groups = { check: [], traced: [], untraced: [] };
  for (const it of items) groups[it.category].push(it);
  return groups;
}

/**
 * The starting decisions: the model's choice where it made one, otherwise leave as typed.
 * @param {object[]} items Numbers from the session state.
 * @returns {Record<string, string|null>} Item key -> accepted path or null.
 */
export function initialDecisions(items) {
  return Object.fromEntries(items.map((it) => [it.key, it.selected ?? null]));
}

/**
 * Counts for the summary bar.
 * @param {object[]} items Numbers from the session state.
 * @param {Record<string, string|null>} decisions Current decisions.
 * @returns {{total: number, linked: number, left: number, undecidedChecks: number}}
 */
export function summary(items, decisions) {
  const linked = items.filter((it) => decisions[it.key]).length;
  const undecidedChecks = items.filter((it) => it.category === "check" && !decisions[it.key]).length;
  return { total: items.length, linked, left: items.length - linked, undecidedChecks };
}

/**
 * Whether a model server address is on this computer, so the manuscript text never leaves it.
 * @param {string} url Address as entered, e.g. "http://127.0.0.1:11434".
 * @returns {boolean} True for localhost, 127.x.x.x and ::1; false otherwise or if unparsable.
 */
export function isLocalHost(url) {
  let host;
  try { host = new URL(url.trim()).hostname; } catch { return false; }
  return host === "localhost" || host === "[::1]" || /^127(\.\d{1,3}){3}$/.test(host);
}

/**
 * Escape text for HTML.
 * @param {string} text Any text.
 * @returns {string} Safe HTML.
 */
export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/**
 * The sentence as HTML, with the number under review ([[...]]) highlighted.
 * @param {string} sentence Sentence from the session state.
 * @returns {string} HTML.
 */
export function markSentence(sentence) {
  return escapeHtml(sentence).replace(/\[\[(.*?)\]\]/, "<mark>$1</mark>");
}

/**
 * Numbers matching a search over file, sentence, written number and cell paths.
 * @param {object[]} items Numbers.
 * @param {string} query Search text (case-insensitive); empty keeps everything.
 * @returns {object[]} Matching numbers.
 */
export function filterItems(items, query) {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((it) =>
    [it.file, it.sentence, it.written, ...it.candidates.map((c) => c.path)]
      .some((s) => s.toLowerCase().includes(q)));
}

/**
 * One line describing a run's progress.
 * @param {{status: string, done: number, total: number, model?: string|null, error?: string}} run
 * @returns {string} Text for the page.
 */
export function progressText(run) {
  if (run.status === "running") {
    const who = run.model ? `asking ${run.model}` : "matching values";
    return run.total ? `${who}: ${run.done} of ${run.total} numbers` : `${who}: reading the manuscript`;
  }
  if (run.status === "error") return `Stopped: ${run.error}`;
  if (run.status === "done") return `Done: ${run.total} numbers read`;
  return "";
}
