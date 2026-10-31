"""Recompute every number in this folder's README from the saved files alone.

For each trial folder (items.json and score_vs_paper.txt): numbers found, review lists, numbers
linked, agreement with the hand-checked DockPrepBench migration, and which review list each
disagreement was in. For repeat_runs/: how often the model's pick for a number changed between
identical runs. Writes summary.json next to this script's parent folder.

Usage: python scripts/summarise.py   (from examples/results/2026-10-31-webapp)
"""

import ast
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def trial(d: Path) -> dict:
    """
    Summarise one trial folder.

    Args:
        d (Path): Folder with items.json and score_vs_paper.txt.

    Returns:
        dict: Counts.
    """
    items = json.loads((d / "items.json").read_text(encoding="utf-8"))
    lines = (d / "score_vs_paper.txt").read_text(encoding="utf-8").splitlines()
    counts = ast.literal_eval(lines[-1])
    # which list held each link that differs from the paper (a path may be linked more than once;
    # the first linked occurrence is used, as in the analysis reported on 2026-10-31)
    first = {}
    for it in items:
        path = it["selected"] or _single(it)
        if path and path not in first:
            first[path] = it["category"]
    lists = Counter()
    for line in lines[:-1]:
        m = re.search(r"app (\S+) =", line)
        if m:
            lists[first.get(m.group(1), "?")] += 1
    return {
        "numbers": len(items),
        "lists": dict(Counter(it["category"] for it in items)),
        "with_matching_cell": sum(1 for it in items if any(c["fits"] for c in it["candidates"])),
        "single_matching_cell": sum(1 for it in items
                                    if sum(c["fits"] for c in it["candidates"]) == 1),
        "linked": sum(counts.values()),
        "vs_paper": counts,
        "differing_links_by_list": dict(lists),
        "pdf_lines_changed": (d / "same_text.txt").read_text(encoding="utf-8").strip(),
    }  # fmt: skip


def _single(it: dict) -> str | None:
    """
    The cell applied without a model: the only fitting cell of a 'check' item, if there is one.

    Args:
        it (dict): One item.

    Returns:
        str | None: Path or None.
    """
    fit = [c["path"] for c in it["candidates"] if c["fits"]]
    return fit[0] if it["pick"] is None and it["category"] == "check" and len(fit) == 1 else None


def repeats(d: Path) -> dict:
    """
    Compare the model's picks across identical runs.

    Args:
        d (Path): Folder of run*.json files ({key: {pick, category}}).

    Returns:
        dict: Per run linked counts and, per pair of runs, how many picks differ.
    """
    runs = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("run*.json"))}
    out = {"runs": {k: {"picks": sum(1 for v in r.values() if v["pick"]),
                        "lists": dict(Counter(v["category"] for v in r.values()))}
                    for k, r in runs.items()}}  # fmt: skip
    pairs = {}
    for (a, ra), (b, rb) in combinations(runs.items(), 2):
        diff = [k for k in ra if ra[k]["pick"] != rb[k]["pick"]]
        pairs[f"{a}-{b}"] = {"numbers": len(ra), "picks_differ": len(diff), "keys": diff}
    out["pairs"] = pairs
    if runs:
        keys = next(iter(runs.values())).keys()
        out["numbers_with_any_change"] = sum(
            1 for k in keys if len({r[k]["pick"] for r in runs.values()}) > 1)
    return out


summary = {d.name: trial(d) for d in sorted(HERE.glob("trial_*")) if (d / "items.json").exists()}
for d in sorted(HERE.glob("repeat*")):
    if any(d.glob("run*.json")):
        summary[d.name] = repeats(d)
(HERE / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "pairs"} for k, v in summary.items()},
                 indent=1))  # fmt: skip
