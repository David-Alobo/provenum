"""provenum: keep the numbers in a manuscript tied to the data that produced them.

Commands:
    provenum values SPEC --tables DIR --out numbers.tex   generate \\val{} entries from tables
    provenum lint MANUSCRIPT...                            list hard-coded decimals in prose
    provenum migrate MANUSCRIPT --answers A.json SPEC --tables DIR
                                                           replace anchored numbers with \\val{}
    provenum audit MANUSCRIPT... --tables DIR [--config C] trace numbers to tables by context
    provenum diff numbers.tex [--rev HEAD | --old OLD.tex] --manuscript FILE...
                                                           what a rerun changed in the text
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path


def _values(args: argparse.Namespace) -> int:
    """
    Write numbers.tex from the tables named in the spec.

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        int: Exit code.
    """
    from provenum.macros import generate, load_specs

    text, n = generate(load_specs(args.spec), args.tables)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{n} values written to {args.out}")
    return 0


def _lint(args: argparse.Namespace) -> int:
    """
    Print hard-coded decimals; exit 1 if any (so CI can enforce \\val{} once a paper is migrated).

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        int: Exit code.
    """
    from provenum.macros import lint

    total = 0
    for f in args.manuscript:
        hits = lint(f)
        total += len(hits)
        for line, number, text in hits:
            print(f"{f}:{line}: hard-coded {number}  | {text[:90]}")
    print(f"{total} hard-coded decimal(s)")
    return 1 if total and args.strict else 0


def _migrate(args: argparse.Namespace) -> int:
    """
    Replace anchored, value-checked numbers with \\val{} in place (writes a .bak copy first).

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        int: Exit code.
    """
    from provenum.anchor import values
    from provenum.macros import load_specs
    from provenum.migrate import migrate

    table = values(load_specs(args.spec), args.tables)
    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    report = migrate(args.manuscript, answers, table, dry_run=args.dry_run)
    for status, n in Counter(r["status"] for r in report).items():
        print(f"{status}: {n}")
    for r in report:
        if r["status"] != "replaced":
            print(f"  line {r['line']}: {r['number']} -> {r.get('path')} ({r['status']})")
    return 0


def _audit(args: argparse.Namespace) -> int:
    """
    Context-anchored audit without macros: trace each number to the cell its words point to.

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        int: 1 if any mismatch or unsourced number, else 0.
    """
    from provenum.context import Config, Matcher, extract
    from provenum.tables import load

    cfg = Config.load(args.config)
    matcher = Matcher(load(args.tables, derived=False, exclude=cfg.exclude), cfg)
    flagged = 0
    for f in args.manuscript:
        for item in extract(f, cfg):
            j = matcher.judge(item)
            if j.status in ("mismatch", "unsourced"):
                flagged += 1
                exp = (
                    f" (anchor: {j.best.value:.4g} in {Path(j.best.file).name} [{j.best.column}])"
                    if j.best
                    else ""
                )
                print(f"{f}:{item.stated.line}: {j.status} {item.stated.text}{exp}")
    print(f"{flagged} number(s) flagged")
    return 1 if flagged else 0


def _diff(args: argparse.Namespace) -> int:
    """
    Report cited values that changed between two values files, flagging claim-breaking changes.

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        int: 1 with --strict if a cited value changed sign, crossed alpha, changed whether its
            interval includes zero, or was removed; else 0.
    """
    from provenum.diff import compare, old_from_git, read_values, report, uses

    if hasattr(sys.stdout, "reconfigure"):  # the report has non-ASCII text (Å, →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    new = read_values(args.values.read_text(encoding="utf-8"))
    try:
        old_text = (
            args.old.read_text(encoding="utf-8")
            if args.old
            else old_from_git(args.values, args.rev)
        )
    except (OSError, RuntimeError) as e:
        print(f"provenum diff: cannot read the old values ({e})", file=sys.stderr)
        return 2
    changes = compare(read_values(old_text), new, args.alpha)
    cited = uses(args.manuscript)
    print(
        report(changes, cited, new, markdown=args.format == "markdown", show_all=args.all), end=""
    )
    flagged = [c for c in changes if c.path in cited and (c.flags or c.new is None)]
    return 1 if args.strict and flagged else 0


def main(argv: Sequence[str] | None = None) -> int:
    """
    Dispatch a provenum command.

    Args:
        argv (Sequence[str] | None): Command-line arguments; sys.argv if None.

    Returns:
        int: Exit code.
    """
    parser = argparse.ArgumentParser(prog="provenum", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("values", help="generate \\val{} entries from tables")
    p.add_argument("spec", type=Path)
    p.add_argument("--tables", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(run=_values)

    p = sub.add_parser("lint", help="list hard-coded decimals in prose")
    p.add_argument("manuscript", nargs="+", type=Path)
    p.add_argument("--strict", action="store_true", help="exit 1 if any are found")
    p.set_defaults(run=_lint)

    p = sub.add_parser("migrate", help="replace anchored numbers with \\val{}")
    p.add_argument("manuscript", type=Path)
    p.add_argument("--answers", type=Path, required=True, help="JSON [{id, path}] from anchoring")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--tables", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(run=_migrate)

    p = sub.add_parser("audit", help="trace numbers to tables by context (no macros needed)")
    p.add_argument("manuscript", nargs="+", type=Path)
    p.add_argument("--tables", nargs="+", type=Path, required=True)
    p.add_argument("--config", type=Path)
    p.set_defaults(run=_audit)

    p = sub.add_parser("diff", help="what a rerun changed in the text")
    p.add_argument("values", type=Path, help="the regenerated values file (numbers.tex)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--rev", default="HEAD", help="git revision of the old values (default HEAD)")
    src.add_argument("--old", type=Path, help="old values file, instead of git")
    p.add_argument("--manuscript", nargs="+", type=Path, default=[], help="files citing \\val{}")
    p.add_argument("--alpha", type=float, default=0.05, help="significance level (default 0.05)")
    p.add_argument("--format", choices=["text", "markdown"], default="text")
    p.add_argument("--all", action="store_true", help="also list changes not cited in the text")
    p.add_argument("--strict", action="store_true", help="exit 1 if a cited claim needs a look")
    p.set_defaults(run=_diff)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
