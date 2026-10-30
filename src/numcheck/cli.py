"""numcheck: check that the numbers in a manuscript trace to its result tables.

Usage:
    numcheck MANUSCRIPT... --tables TABLES... [--show traced|derived|untraced|all]
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from numcheck.check import check
from numcheck.latex import extract
from numcheck.tables import load


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the check and print a report.

    Args:
        argv (Sequence[str] | None): Command-line arguments; sys.argv if None.

    Returns:
        int: 1 if any number is untraced, else 0 (so CI can fail on drift).
    """
    parser = argparse.ArgumentParser(prog="numcheck", description=__doc__.splitlines()[0])
    parser.add_argument("manuscript", nargs="+", type=Path, help=".tex or .md files")
    parser.add_argument("--tables", nargs="+", required=True, type=Path, help="CSV files or directories")
    parser.add_argument("--show", default="untraced", choices=["traced", "derived", "untraced", "all"])
    parser.add_argument("--no-derived", action="store_true", help="don't trace via differences")
    args = parser.parse_args(argv)

    sources = load(args.tables, derived=not args.no_derived)
    stated = [s for f in args.manuscript for s in extract(f)]
    verdicts = check(stated, sources)
    for v in verdicts:
        if args.show in ("all", v.status):
            s = v.stated
            where = ""
            if v.sources:
                src = v.sources[0]
                where = f"  <- {Path(src.file).name} row {src.row} [{src.column}] ({src.how}); {len(v.sources)} candidate(s)"
            print(f"{s.file}:{s.line}: {v.status:8} {s.text:>10}{where}")
            if v.status == "untraced":
                print(f"      {s.context}")
    counts = Counter(v.status for v in verdicts)
    print(f"\n{len(verdicts)} numbers: {counts['traced']} traced, {counts['derived']} derived, "
          f"{counts['untraced']} untraced ({len(sources)} candidate values from the tables)")  # fmt: skip
    return 1 if counts["untraced"] else 0


if __name__ == "__main__":
    sys.exit(main())
