"""Benchmark local models on anchoring, using a migrated manuscript as the gold standard.

Every \\val{path} in a migrated manuscript is a human-written sentence whose correct table
value is known exactly. This script rebuilds each sentence with the number written out, asks a
model which value it reports, and scores the answer against the path. A few settings that come
from no table (passed with --none) test whether a model abstains instead of guessing.

Usage:
    python bench_models.py MANUSCRIPT.tex --spec SPEC --tables DIR --host URL \\
        --models qwen2.5:7b-instruct llama3.1:8b-instruct ... [--modes blind shortlist] \\
        [--none "pH 7.4" "2.857"] [--out results.csv]
"""

import argparse
import csv
import re
import time
from collections import Counter
from pathlib import Path

from provenum.anchor import catalogue, judge, values
from provenum.llm import ask, choose
from provenum.macros import load_specs

VAL = re.compile(r"\\val\{([^{}]*)\}")


def _plain(formatted: str) -> str:
    """
    Turn a formatted value into the text a reader sees, and provenum's canonical number.

    Args:
        formatted (str): Output of `macros.fmt`, e.g. "\\ensuremath{4.1 \\times 10^{-4}}".

    Returns:
        str: e.g. "4.1 \\times 10^{-4}" for the sentence (the extractor reads it back).
    """
    text = re.sub(r"\\ensuremath\{(.*)\}$", r"\1", formatted)
    return text.replace(r"\ensuremath{-}", "-")


def _canonical(shown: str) -> str:
    """
    The number provenum compares against, from the shown text.

    Args:
        shown (str): Number as shown, e.g. "4.1 \\times 10^{-4}" or "+6.8".

    Returns:
        str: "4.1e-4", "6.8", ...
    """
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)\s*\\times\s*10\^\{(-?\d+)\}", shown)
    if m:
        return f"{m.group(1)}e{m.group(2)}"
    return shown.lstrip("+")


def gold_items(path: Path, table: dict, none_markers: list[str]) -> list[dict]:
    """
    One item per \\val{} occurrence (gold = its path), plus marked settings (gold = None).

    Args:
        path (Path): Migrated manuscript.
        table (dict): `anchor.values` output.
        none_markers (list[str]): Phrases whose number is a setting, not a table value
            (e.g. "pH 7.4"); every occurrence becomes a gold-None item.

    Returns:
        list[dict]: Items with number, written, sentence, paragraph and gold.
    """
    text = path.read_text(encoding="utf-8")
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if "\\begin{tabular" not in p]
    items = []
    for para in paragraphs:
        refs = list(VAL.finditer(para))
        shown = [_plain(table[m.group(1)][1]) if m.group(1) in table else "??" for m in refs]
        for k, m in enumerate(refs):
            pieces, last = [], 0
            for j, other in enumerate(refs):
                pieces.append(para[last : other.start()])
                pieces.append(f"[[{shown[j]}]]" if j == k else shown[j])
                last = other.end()
            pieces.append(para[last:])
            rebuilt = " ".join("".join(pieces).split())
            start = rebuilt.find("[[")
            s0 = rebuilt.rfind(". ", 0, start) + 2 if rebuilt.rfind(". ", 0, start) >= 0 else 0
            s1 = rebuilt.find(". ", start)
            sentence = rebuilt[s0 : s1 + 1 if s1 > 0 else len(rebuilt)]
            items.append({
                "number": _canonical(shown[k]), "written": shown[k], "sentence": sentence,
                "paragraph": rebuilt.replace("[[", "").replace("]]", "")[:1200],
                "gold": m.group(1),
            })  # fmt: skip
        plain = " ".join(
            VAL.sub(lambda m: _plain(table.get(m.group(1), (0, "??"))[1]), para).split()
        )
        for marker in none_markers:
            for m in re.finditer(re.escape(marker), plain):
                num = re.search(r"\d+(?:\.\d+)?", marker).group()
                marked = plain[: m.start()] + marker.replace(num, f"[[{num}]]") + plain[m.end() :]
                items.append({"number": num, "written": num, "sentence": marked[max(0, m.start() - 200) : m.end() + 200],
                              "paragraph": plain[:1200], "gold": None})  # fmt: skip
    for i, it in enumerate(items):
        it["id"] = i
    return items


def score(items: list[dict], answers: dict[int, str | None], table: dict) -> dict:
    """
    Count right, wrong and abstained answers, separately for table values and settings.

    Args:
        items (list[dict]): Gold items.
        answers (dict[int, str | None]): Item id -> proposed path.
        table (dict): `anchor.values` output.

    Returns:
        dict: right, wrong, abstain (on table values), false_anchor (on settings), and
            caught_wrong: wrong proposals that the value check would reject.
    """
    c = Counter()
    for it in items:
        a = answers.get(it["id"])
        if it["gold"] is None:
            c["settings"] += 1
            c["false_anchor"] += a is not None
            continue
        c["values"] += 1
        if a is None:
            c["abstain"] += 1
        elif a == it["gold"]:
            c["right"] += 1
        else:
            c["wrong"] += 1
            c["caught_wrong"] += judge(it["number"], a, table) != "traced"
    return dict(c)


def main() -> None:
    """Run every model in every mode and write a results table."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manuscript", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--modes", nargs="+", default=["blind", "shortlist"])
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--none", nargs="*", default=[], dest="none_markers")
    parser.add_argument("--limit", type=int, help="only the first N items (a quick check)")
    parser.add_argument("--out", type=Path, default=Path("bench_results.csv"))
    args = parser.parse_args()

    specs = load_specs(args.spec)
    table = values(specs, args.tables)
    cat = catalogue(specs, args.tables)
    notes = args.notes.read_text(encoding="utf-8") if args.notes else ""
    items = gold_items(args.manuscript, table, args.none_markers)[: args.limit]
    print(f"{len(items)} items ({sum(i['gold'] is None for i in items)} settings)")
    rows = []
    for model in args.models:
        for mode in args.modes:
            answers, t0 = {}, time.time()
            for it in items:
                try:
                    if mode == "blind":
                        answers[it["id"]] = ask(it, cat, notes, model, args.host)
                    else:
                        cands = [p for p in table if judge(it["number"], p, table) == "traced"]
                        answers[it["id"]] = (
                            choose(it, cands, notes, model, args.host) if cands else None
                        )
                except OSError as e:
                    print(f"  {model} {mode}: request failed ({e}); counted as abstain")
                    answers[it["id"]] = None
            seconds = time.time() - t0
            s = score(items, answers, table)
            row = {"model": model, "mode": mode, **s, "seconds_per_item": seconds / len(items)}
            rows.append(row)
            print(row, flush=True)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("model", "mode"), k))
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
