"""Compare the base and fine-tuned models on the same examples, paired.

For each test set and mode: right, wrong (and wrong that the value check would pass), no answer
and false anchors for both models; Wilson 95% intervals on the share right; and, for numbers that
have a cell, the paired change (gained, lost) with an exact McNemar test. Examples where either
model ran out of memory count as no answer for that model, as in the scores.

Usage: python compare.py   (reads evals/, writes comparison.json and prints a table)
"""

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str) -> dict[tuple, dict]:
    """
    Answers of one model by example key.

    Args:
        name (str): "base" or "tuned".

    Returns:
        dict[tuple, dict]: (paper, id, mode) -> answer row.
    """
    rows = {}
    for line in (HERE / "evals" / f"answers_{name}.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        m = r["meta"]
        rows[(m["paper"], m["id"], m["mode"])] = r
    return rows


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """
    Wilson score interval for a proportion.

    Args:
        k (int): Successes.
        n (int): Trials.
        z (float): Normal quantile (95% by default).

    Returns:
        tuple[float, float]: Lower and upper bound.
    """
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def mcnemar(b: int, c: int) -> float:
    """
    Exact two-sided McNemar p-value (binomial test on the discordant pairs).

    Args:
        b (int): Pairs right only with the fine-tuned model.
        c (int): Pairs right only with the base model.

    Returns:
        float: p-value.
    """
    n, k = b + c, min(b, c)
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def outcome(r: dict) -> str:
    """
    Classify one answer.

    Args:
        r (dict): Answer row.

    Returns:
        str: right, wrong, passed (wrong but value-identical), abstain, no_cell_ok, false_anchor.
    """
    m, a = r["meta"], r["answer"]
    if m["gold"] is None:
        return "false_anchor" if a is not None else "no_cell_ok"
    if a is None:
        return "abstain"
    if a == m["gold"]:
        return "right"
    return "passed" if a in m["traced"] else "wrong"


def main() -> None:
    """Write comparison.json and print the comparison."""
    base, tuned = load("base"), load("tuned")
    assert base.keys() == tuned.keys(), "the two runs must cover the same examples"
    groups = defaultdict(list)
    for key in base:
        paper = "dockprepbench" if key[0] == "dockprepbench" else "synthetic"
        groups[f"{paper}/{key[2]}"].append(key)
    out = {}
    for g in sorted(groups):
        keys = groups[g]
        res = {}
        for name, rows in (("base", base), ("tuned", tuned)):
            counts = defaultdict(int)
            for k in keys:
                counts[outcome(rows[k])] += 1
                counts["out_of_memory"] += "error" in rows[k]
            values = sum(1 for k in keys if rows[k]["meta"]["gold"] is not None)
            lo, hi = wilson(counts["right"], values)
            res[name] = dict(counts, values=values, right_share=counts["right"] / values,
                             right_ci95=[lo, hi])  # fmt: skip
        with_cell = [k for k in keys if base[k]["meta"]["gold"] is not None]
        gained = sum(
            outcome(tuned[k]) == "right" and outcome(base[k]) != "right" for k in with_cell
        )
        lost = sum(outcome(base[k]) == "right" and outcome(tuned[k]) != "right" for k in with_cell)
        res["paired"] = {"gained": gained, "lost": lost, "mcnemar_p": mcnemar(gained, lost)}
        out[g] = res
        b, t = res["base"], res["tuned"]
        print(f"{g:24} right {b['right']:3} -> {t['right']:3} of {b['values']} "
              f"({100 * b['right_share']:.1f}% -> {100 * t['right_share']:.1f}%); "
              f"wrong {b.get('wrong', 0) + b.get('passed', 0)} -> {t.get('wrong', 0) + t.get('passed', 0)} "
              f"(passed {b.get('passed', 0)} -> {t.get('passed', 0)}); "
              f"no answer {b.get('abstain', 0)} -> {t.get('abstain', 0)}; "
              f"false anchors {b.get('false_anchor', 0)} -> {t.get('false_anchor', 0)}; "
              f"+{gained} -{lost}, p = {res['paired']['mcnemar_p']:.2g}")  # fmt: skip
    (HERE / "comparison.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
