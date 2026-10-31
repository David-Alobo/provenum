"""Compare the app's \\val{} links with the hand-checked migrated DockPrepBench section.

Lines are matched by their text with every \\val{} filled by its value; within a matched line the
\\val{} of the app is compared with the \\val{} at the same position in the paper. Links are
compared as cells (table file, row, column), not as path names, because a guessed spec can name
the same cell differently (e.g. keys in another order).

Usage: score_vs_paper.py TRIAL_DIR PAPER_DIR [-v]
    TRIAL_DIR holds out/ (migrated project), numbers.toml and tables/ (from web_trial.py);
    PAPER_DIR is DockPrepBench's paper/ (sections/results.tex, numbers.toml, tables/).
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

from provenum.diff import read_values
from provenum.macros import load_specs
from provenum.migrate import _plain

VAL = re.compile(r"\\val(?:\[[^\]]*\])?\{([^{}]*)\}")
trial, paper = Path(sys.argv[1]), Path(sys.argv[2])
app_vals = read_values((trial / "out/numbers.tex").read_text("utf-8"))
pap_vals = read_values((paper / "tables/numbers.tex").read_text("utf-8"))


def identities(spec_file: Path, root: Path) -> dict[str, tuple[str, int, str]]:
    """
    Map each path a spec defines to its cell (file, row index, column), as macros.cells does.

    Args:
        spec_file (Path): Spec TOML.
        root (Path): Tables directory.

    Returns:
        dict[str, tuple[str, int, str]]: Path -> cell (a later row wins a path, as in provenum).
    """
    out = {}
    for spec in load_specs(spec_file):
        prefix = re.sub(r"\.csv$", "", spec.file)
        with open(root / spec.file, newline="", encoding="utf-8") as handle:
            for i, row in enumerate(csv.DictReader(handle)):
                key = "/".join([prefix] + [row[k] for k in spec.keys])
                if spec.value_column:
                    out[key] = (spec.file, i, spec.value_column)
                else:
                    for c in row:
                        if c not in spec.keys:
                            out[f"{key}/{c}"] = (spec.file, i, c)
    return out


app_cell = identities(trial / "numbers.toml", trial / "tables")
pap_cell = identities(paper / "numbers.toml", paper / "tables")


def spans(line: str, vals: dict) -> tuple[str, list[tuple[int, str]]]:
    """
    A line's text with values filled in, and where each \\val{} sits in it.

    Args:
        line (str): Manuscript line.
        vals (dict): Values file contents.

    Returns:
        tuple[str, list[tuple[int, str]]]: Plain filled text and (offset, path) per \\val{}.
    """
    out, pos, filled = [], 0, ""
    for m in VAL.finditer(line):
        filled += line[pos : m.start()]
        out.append((len(_plain(filled)), m.group(1)))
        filled += vals.get(m.group(1), "??")
        pos = m.end()
    filled += line[pos:]
    return _plain(filled), out


paper_lines = {}
for line in (paper / "sections/results.tex").read_text("utf-8").split("\n"):
    text, refs = spans(line, pap_vals)
    paper_lines.setdefault(text, refs)
c = Counter()
for line in (trial / "out/sections/results.tex").read_text("utf-8").split("\n"):
    text, refs = spans(line, app_vals)
    if not refs:
        continue
    gold = paper_lines.get(text)
    if gold is None:
        c["line not found in paper"] += len(refs)
        continue
    gold_at = dict(gold)
    for off, path in refs:
        g = gold_at.get(off)
        if g is None:
            kind = "no \\val in paper there"
        elif app_cell.get(path) == pap_cell.get(g):
            kind = "same cell"
        else:
            kind = "different cell"
        c[kind] += 1
        if kind != "same cell" and "-v" in sys.argv:
            print(f"{kind}: app {path} = {app_vals[path]}; paper {g}\n"
                  f"    {text[max(0, off - 90) : off + 40]}")  # fmt: skip
print(dict(c))
