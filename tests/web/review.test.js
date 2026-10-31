import { describe, expect, it } from "vitest";
import {
  escapeHtml, filterItems, fitting, groupItems, initialDecisions, markSentence,
  progressText, summary,
} from "../../src/provenum/web/static/review.js";

const cell = (path, fits = true) => ({ path, text: "53.0", fits });
const ITEMS = [
  { key: "a.tex#0", file: "a.tex", written: "53.0", sentence: "Success rose to [[53.0]]%.",
    category: "traced", pick: "summary/vina/top1", selected: "summary/vina/top1",
    candidates: [cell("summary/vina/top1")] },
  { key: "a.tex#1", file: "a.tex", written: "0.12", sentence: "A gap of [[0.12]].",
    category: "check", pick: null, selected: null,
    candidates: [cell("cmp/x/delta"), cell("cmp/y/delta"), cell("cmp/z/delta", false)] },
  { key: "b.tex#0", file: "b.tex", written: "7.4", sentence: "At pH [[7.4]].",
    category: "untraced", pick: null, selected: null, candidates: [] },
  { key: "b.tex#1", file: "b.tex", written: "2.5", sentence: "Ratio [[2.5]].",
    category: "check", pick: null, selected: null, candidates: [cell("recorded/ratio")] },
];

describe("fitting and grouping", () => {
  it("keeps only cells that reproduce the written text", () => {
    expect(fitting(ITEMS[1]).map((c) => c.path)).toEqual(["cmp/x/delta", "cmp/y/delta"]);
  });

  it("splits numbers into the three lists in manuscript order", () => {
    const g = groupItems(ITEMS);
    expect(g.traced.map((i) => i.key)).toEqual(["a.tex#0"]);
    expect(g.check.map((i) => i.key)).toEqual(["a.tex#1", "b.tex#1"]);
    expect(g.untraced.map((i) => i.key)).toEqual(["b.tex#0"]);
  });
});

describe("decisions", () => {
  it("starts from the model's choices and leaves the rest as typed", () => {
    expect(initialDecisions(ITEMS)).toEqual({
      "a.tex#0": "summary/vina/top1", "a.tex#1": null, "b.tex#0": null, "b.tex#1": null,
    });
  });

  it("counts linked, left and unconfirmed numbers", () => {
    const d = { ...initialDecisions(ITEMS), "a.tex#1": "cmp/x/delta" };
    expect(summary(ITEMS, d)).toEqual({ total: 4, linked: 2, left: 2, undecidedChecks: 1 });
  });
});

describe("display", () => {
  it("escapes HTML before highlighting the number", () => {
    expect(markSentence("x <b> [[1.5]] & y")).toBe("x &lt;b&gt; <mark>1.5</mark> &amp; y");
    expect(escapeHtml(`"'`)).toBe("&quot;&#39;");
  });

  it("searches sentences, files and cell paths, ignoring case", () => {
    expect(filterItems(ITEMS, "PH").map((i) => i.key)).toEqual(["b.tex#0"]);
    expect(filterItems(ITEMS, "cmp/y").map((i) => i.key)).toEqual(["a.tex#1"]);
    expect(filterItems(ITEMS, "  ")).toHaveLength(4);
  });

  it("describes run progress", () => {
    expect(progressText({ status: "running", done: 3, total: 10, model: "qwen3:32b" }))
      .toBe("asking qwen3:32b: 3 of 10 numbers");
    expect(progressText({ status: "running", done: 0, total: 0, model: null }))
      .toBe("matching values: reading the manuscript");
    expect(progressText({ status: "error", error: "no server" })).toBe("Stopped: no server");
    expect(progressText({ status: "idle" })).toBe("");
  });
});
