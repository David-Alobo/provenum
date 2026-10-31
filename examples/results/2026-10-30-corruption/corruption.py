"""Corruption test for value-only and context matching, with the code of provenum commit 5ffdc7d.

Every decimal is shifted by three units in its last digit (46.3 becomes 46.6).

- Value only (the prototype's checker): a number is flagged only if no cell, cell x 100 or
  within-row difference rounds to it. A corruption is caught if it traces to nothing.
- Context (the audit): a corruption is caught if it is a mismatch with the cell its words point
  to, traces to nothing, or is unanchored and traces to nothing.

A false alarm is a correct number that the method flags. Each method is scored on all decimals
the context extractor finds (562: prose and LaTeX tables) and on the 307 prose decimals that the
anchoring experiment used (matched by line and written text, from ITEMS.json).

Usage (with the numcheck package of commit 5ffdc7d on PYTHONPATH):
    python corruption.py RESULTS.tex TABLES_DIR CONFIG.toml ITEMS.json
"""

import json
import sys
from collections import Counter
from dataclasses import replace

from numcheck.check import check
from numcheck.context import Config, InContext, Matcher, extract
from numcheck.tables import load

CAUGHT = {"mismatch", "unsourced", "unanchored-untraced"}


def mutate(stated, k: int = 3):
    """
    Shift a stated number by k units in its last digit, keeping its precision.

    Args:
        stated (numcheck.latex.Stated): The number as written.
        k (int): Units to add.

    Returns:
        numcheck.latex.Stated: The corrupted number.
    """
    step = 10.0 ** (stated.exponent - stated.decimals)
    v = stated.value + k * step * (1 if stated.value >= 0 else -1)
    return replace(stated, value=v, text=f"{v:.{max(stated.decimals, 0)}f}")


def in_prose(decimals: list, items_path: str) -> list[bool]:
    """
    Mark which extracted decimals are among the anchoring experiment's prose numbers.

    Numbers are matched by line and value; a line holding the same value twice uses it up to as
    many times as the items do.

    Args:
        decimals (list): Stated numbers from the context extractor.
        items_path (str): items.json of the anchoring experiment.

    Returns:
        list[bool]: One flag per decimal.
    """
    want = Counter((i["line"], round(float(i["number"].replace("−", "-")), 12))
                   for i in json.load(open(items_path, encoding="utf-8")))  # fmt: skip
    flags = []
    for s in decimals:
        key = (s.line, round(s.value, 12))
        flags.append(want[key] > 0)
        if want[key] > 0:
            want[key] -= 1
    print(f"prose items not found among the extracted decimals: {sum(want.values())}")
    return flags


def report(name: str, flags: list[bool], keep: list[bool]) -> None:
    """
    Print a count of flagged numbers.

    Args:
        name (str): What is counted.
        flags (list[bool]): Whether each number was flagged.
        keep (list[bool]): Which numbers to count.

    Returns:
        None
    """
    n = sum(keep)
    k = sum(f for f, k in zip(flags, keep) if k)
    print(f"  {name}: {k}/{n} ({100 * k / n:.1f}%)")


def main() -> None:
    """Print both corruption tests, on all decimals and on the prose decimals."""
    tex, tables, cfg_path, items_path = sys.argv[1:5]
    cfg = Config.load(cfg_path)
    items = [i for i in extract(tex, cfg) if not i.stated.is_integer]
    dec = [i.stated for i in items]
    prose = in_prose(dec, items_path)
    every = [True] * len(dec)

    sources = load([tables], derived=True, exclude=cfg.exclude)
    value_real = [v.status == "untraced" for v in check(dec, sources)]
    value_mut = [v.status == "untraced" for v in check([mutate(s) for s in dec], sources)]

    m = Matcher(load([tables], derived=False, exclude=cfg.exclude), cfg)
    ctx_real_j = [m.judge(i) for i in items]
    ctx_real = [j.status == "mismatch" for j in ctx_real_j]
    ctx_anch = [j.status == "traced" for j in ctx_real_j]
    ctx_mut = [m.judge(InContext(mutate(i.stated), i.context)).status in CAUGHT for i in items]

    for label, keep in (("all decimals", every), ("prose decimals", prose)):
        print(label)
        report("value only, corruptions caught", value_mut, keep)
        report("value only, correct numbers flagged", value_real, keep)
        report("context, corruptions caught", ctx_mut, keep)
        report("context, correct numbers flagged (mismatch)", ctx_real, keep)
        anchored = [k and a for k, a in zip(keep, ctx_anch)]
        report("context, corruptions caught where the original is anchored and traced",
               ctx_mut, anchored)  # fmt: skip


if __name__ == "__main__":
    main()
