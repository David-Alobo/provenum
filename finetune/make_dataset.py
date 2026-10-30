"""Turn synthetic papers (and, for testing, a migrated manuscript) into chat examples.

Every example is the exact prompt provenum sends at inference (`llm.ask_prompt` for blind mode,
`llm.choose_prompt` for shortlist mode) plus the gold reply, so training matches use. Each line
also carries metadata for scoring: paper, mode, number, gold path and the paths whose value
matches the number (`traced`), which tells a wrong answer the value check catches from one it
does not.

Papers whose id starts with "test" (held-out fields) go to test.jsonl; the rest are split by
paper into train.jsonl and val.jsonl. With --dockprepbench, the DockPrepBench gold set is
written to dockprepbench.jsonl instead; it is never used for training.

Usage:
    python make_dataset.py --papers papers --out data
    python make_dataset.py --out data --dockprepbench MANUSCRIPT --spec SPEC --tables DIR \\
        --notes NOTES --none "pH 7.4" "2.857 times"
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from provenum.anchor import catalogue, judge, values
from provenum.llm import ask_prompt, choose_prompt
from provenum.macros import load_specs


def examples(items: list[dict], table: dict, cat: str, notes: str, paper: str) -> list[dict]:
    """
    Blind and shortlist examples for the items of one paper.

    Args:
        items (list[dict]): Gold items (number, written, sentence, paragraph, gold).
        table (dict): `anchor.values` output for the paper.
        cat (str): `anchor.catalogue` output.
        notes (str): Project notes (may be empty).
        paper (str): Paper id.

    Returns:
        list[dict]: {messages, meta} per example; shortlist examples only where some cell
            matches the number (provenum asks the model nothing otherwise).
    """
    out = []
    for it in items:
        traced = [p for p in table if judge(it["number"], p, table) == "traced"]
        meta = {"paper": paper, "id": it["id"], "number": it["number"], "gold": it["gold"],
                "traced": traced, "hidden": it.get("hidden", False),
                "setting": it.get("setting", False)}  # fmt: skip
        system, user, _ = ask_prompt(it, cat, notes)
        out.append({"messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user},
                                 {"role": "assistant", "content": json.dumps({"path": it["gold"]})}],
                    "meta": {**meta, "mode": "blind"}})  # fmt: skip
        if traced:
            answer = it["gold"] if it["gold"] in traced else "none"
            system, user, _ = choose_prompt(it, traced, notes)
            out.append({"messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": user},
                                     {"role": "assistant", "content": json.dumps({"path": answer})}],
                        "meta": {**meta, "mode": "shortlist"}})  # fmt: skip
    return out


def from_papers(papers: Path, out: Path, val_frac: float, seed: int) -> dict:
    """
    Write train/val/test JSONL from generated papers.

    Args:
        papers (Path): Directory of papers from make_papers.py.
        out (Path): Output directory.
        val_frac (float): Fraction of training papers held out for validation.
        seed (int): Seed for the train/val split.

    Returns:
        dict: Counts per split and mode, for stats.json.
    """
    dirs = sorted(d for d in papers.iterdir() if (d / "meta.json").exists())
    train_ids = [d.name for d in dirs if d.name.startswith("train")]
    random.Random(seed).shuffle(train_ids)
    val_ids = set(train_ids[: max(1, round(val_frac * len(train_ids)))])
    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for d in dirs:
        items = json.loads((d / "items.json").read_text(encoding="utf-8"))
        if not items:
            continue
        specs = load_specs(d / "spec.toml")
        table = values(specs, d / "tables")
        cat = catalogue(specs, d / "tables")
        notes = (d / "notes.txt").read_text(encoding="utf-8")
        split = "test" if d.name.startswith("test") else "val" if d.name in val_ids else "train"
        splits[split] += examples(items, table, cat, notes, d.name)
    stats = {}
    for name, rows in splits.items():
        random.Random(seed).shuffle(rows)
        _write(out / f"{name}.jsonl", rows)
        stats[name] = _stats(rows)
    stats["papers"] = {"train": len(train_ids) - len(val_ids), "val": len(val_ids),
                       "test": sum(d.name.startswith("test") for d in dirs)}  # fmt: skip
    return stats


def from_manuscript(args: argparse.Namespace) -> dict:
    """
    Write the DockPrepBench gold set (test only) in the same format.

    Args:
        args (argparse.Namespace): Parsed arguments (dockprepbench, spec, tables, notes, none).

    Returns:
        dict: Counts per mode, for stats.json.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from bench_models import gold_items

    specs = load_specs(args.spec)
    table = values(specs, args.tables)
    cat = catalogue(specs, args.tables)
    notes = args.notes.read_text(encoding="utf-8") if args.notes else ""
    items = gold_items(args.dockprepbench, table, args.none_markers)
    for it in items:
        it["setting"] = it["gold"] is None
    rows = examples(items, table, cat, notes, "dockprepbench")
    _write(args.out / "dockprepbench.jsonl", rows)
    return {"dockprepbench": _stats(rows)}


def _write(path: Path, rows: list[dict]) -> None:
    """
    Write rows as JSON lines.

    Args:
        path (Path): Output file.
        rows (list[dict]): Examples.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _stats(rows: list[dict]) -> dict:
    """
    Counts that describe a split.

    Args:
        rows (list[dict]): Examples.

    Returns:
        dict: Examples per mode, gold-null examples and shortlists with several candidates.
    """
    c = Counter()
    for r in rows:
        m = r["meta"]
        c[m["mode"]] += 1
        c[f"{m['mode']}_gold_null"] += m["gold"] is None
        c["shortlist_multi"] += m["mode"] == "shortlist" and len(m["traced"]) > 1
    return dict(c)


def main() -> None:
    """Build the dataset files and update stats.json."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--papers", type=Path)
    parser.add_argument("--val-frac", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dockprepbench", type=Path, help="migrated manuscript (test set only)")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--tables", type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--none", nargs="*", default=[], dest="none_markers")
    args = parser.parse_args()

    stats_path = args.out / "stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    if args.papers:
        stats.update(from_papers(args.papers, args.out, args.val_frac, args.seed))
    if args.dockprepbench:
        stats.update(from_manuscript(args))
    args.out.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
