"""Guess a starting spec (numbers.toml) from a folder of result tables.

The guesses are the ones a person would make on first reading a results table: text columns name
the row, a column called p or p_* holds p-values, values between 0 and 1 are proportions shown as
percentages, signed differences show their sign, and whole numbers are counts. The spec is a
starting point: every guess is written down with a comment so it can be checked and edited.
"""

import csv
import math
import re
from collections import Counter
from pathlib import Path

RECORDED = ("name", "value", "format")  # columns of a table written by provenum.record
DIFF = re.compile(r"(^|_)(delta|diff|difference|change|effect)(_|$)", re.IGNORECASE)
BOUND = re.compile(r"_?(low|lo|lower|high|hi|upper)$", re.IGNORECASE)
# Between 0 and 1 but conventionally written as decimals, not percentages.
SCORE = re.compile(r"(auc|auroc|auprc|r2|rsq|corr|pearson|spearman|kappa|brier|f1_?score|icc)",
                   re.IGNORECASE)  # fmt: skip
RATIO = re.compile(r"(ratio|fold|times)", re.IGNORECASE)


def _numbers(cells: list[str]) -> list[float] | None:
    """
    The column's values as numbers, or None if any non-empty cell is not a number.

    Args:
        cells (list[str]): One column.

    Returns:
        list[float] | None: Finite values, or None for a text column.
    """
    out = []
    for c in cells:
        if c.strip() == "" or c.strip().lower() in ("nan", "na", "none"):
            continue
        try:
            out.append(float(c))
        except ValueError:
            return None
    return [x for x in out if math.isfinite(x)]


def _is_p(name: str) -> bool:
    """
    Whether a column name means p-values (or q-values).

    Args:
        name (str): Column name.

    Returns:
        bool: True for p, q, p_*, *_p, pvalue, p_value.
    """
    n = name.lower()
    return n in ("pvalue", "p_value", "pval") or re.search(r"(^|_)[pq](_|$)", n) is not None


def guess_format(name: str, xs: list[float], proportion_stems: set[str]) -> tuple[str, str]:
    """
    Guess how one numeric column should be written in the text.

    Args:
        name (str): Column name.
        xs (list[float]): Its values.
        proportion_stems (set[str]): Columns already judged proportions (so their interval
            bounds follow them).

    Returns:
        tuple[str, str]: (format, reason).
    """
    stem = BOUND.sub("", name)
    if _is_p(name):
        return "p", "p-values"
    if xs and all(x == round(x) for x in xs) and max(abs(x) for x in xs) >= 1:
        return "int", "whole numbers"
    top = max((abs(x) for x in xs), default=0)
    if RATIO.search(stem):
        return "f2", "a ratio"
    if SCORE.search(stem):
        return "f3", "a score between 0 and 1, written as a decimal"
    if stem in proportion_stems or (xs and all(0 <= x <= 1 for x in xs) and not DIFF.search(name)):
        return "pct1", "proportions, shown as percentages"
    if DIFF.search(stem):
        # Differences of small quantities (scores) keep their precision; differences of
        # percentages are in points, one decimal.
        how = "f3" if top < 1 else "f1"
        if BOUND.search(name):
            return how, "bounds of a difference"
        return "+" + how, "a signed difference"
    if top >= 100:
        return "f0", "large values"
    if top >= 1:
        return "f1" if top >= 10 else "f2", "values above 1"
    return "f3", "values below 1"


def guess_keys(header: list[str], rows: list[dict], numeric: dict[str, list[float] | None]
               ) -> tuple[list[str], bool]:  # fmt: skip
    """
    Guess the columns that name a row: the text columns, plus small integer columns if needed.

    Args:
        header (list[str]): Column names in order.
        rows (list[dict]): The table.
        numeric (dict[str, list[float] | None]): Column values, None for text columns.

    Returns:
        tuple[list[str], bool]: Key columns, and whether they identify every row uniquely.
    """
    flags = {"true", "false", "yes", "no", "t", "f", ""}
    keys = [c for c in header if numeric[c] is None
            and not {r[c].strip().lower() for r in rows} <= flags]  # fmt: skip

    def unique(ks: list[str]) -> bool:
        """
        Whether the columns identify every row.

        Args:
            ks (list[str]): Candidate key columns.

        Returns:
            bool: True if no two rows share the same key values.
        """
        return len({tuple(r[k] for k in ks) for r in rows}) == len(rows)

    if unique(keys):
        # Drop text columns that the columns before them already determine (a label such as
        # "2 A box" next to the arm id). The first column is always kept, so a factor with one
        # value today (a single engine) still names the row when more are added.
        kept = keys[:1]
        for c in keys[1:]:
            seen: dict[tuple, str] = {}
            determined = all(seen.setdefault(tuple(r[k] for k in kept), r[c]) == r[c]
                             for r in rows)  # fmt: skip
            if not determined:
                kept.append(c)
        return (kept, True) if unique(kept) else (keys, True)
    # Integer-coded factors such as level 0-5 or padding 2/4/6/8.
    for c in header:
        xs = numeric[c]
        if c in keys or not xs or not all(x == round(x) for x in xs) or len(set(xs)) > 20:
            continue
        keys.append(c)
        if unique(keys):
            return [k for k in header if k in keys], True
    return [k for k in header if k in keys], False


def table_spec(path: Path, root: Path) -> str:
    """
    The spec block for one table, with its guesses as comments.

    Args:
        path (Path): CSV file.
        root (Path): Tables directory (the spec's file paths are relative to it).

    Returns:
        str: A [[table]] TOML block.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    rel = path.relative_to(root).as_posix()
    if all(c in header for c in RECORDED):
        return (f'# {rel}: values recorded with provenum.record ({len(rows)} rows)\n'
                f'[[table]]\nfile = "{rel}"\nkeys = ["name"]\nvalue = "value"\n'
                f'format = "format"\n')  # fmt: skip
    numeric = {c: _numbers([r[c] for r in rows]) for c in header}
    keys, ok = guess_keys(header, rows, numeric)
    formats, reasons, stems = {}, {}, set()
    last = None  # the previous value column, for bare "low"/"high" bounds that follow it
    for c in header:
        if c in keys or numeric[c] is None:
            continue
        if last and BOUND.fullmatch(c) and not BOUND.sub("", c):
            how, why = formats[last].lstrip("+"), f"bounds of {last}"
        else:
            how, why = guess_format(c, numeric[c], stems)
            last = c
        if how == "pct1":
            stems.add(BOUND.sub("", c))
        formats[c], reasons[c] = how, why
    # In a table of rates, a small difference is a difference of proportions: show it in points.
    if stems and not any(SCORE.search(c) for c in formats):
        for c, how in formats.items():
            if how in ("+f3", "f3") and DIFF.search(BOUND.sub("", c)):
                formats[c] = how.replace("f3", "pct1")
                reasons[c] = "a difference of proportions, in points"
    default = Counter(formats.values()).most_common(1)[0][0] if formats else "auto"
    lines = [f"# {rel}: {len(rows)} rows; keys {', '.join(keys) or '(none)'}"]
    if not ok:
        lines.append("# CHECK: these keys do not identify every row; add or change a key column")
    groups: dict[str, list[str]] = {}
    for c, how in formats.items():
        groups.setdefault(f"{how} ({reasons[c]})", []).append(c)
    lines += [f"#   {', '.join(cs)}: {g}" for g, cs in groups.items()]
    other = {c: how for c, how in formats.items() if how != default}
    fmt_line = ", ".join(f'{_toml_key(c)} = "{how}"' for c, how in other.items())
    lines += ["[[table]]", f'file = "{rel}"', f"keys = {_toml_list(keys)}",
              f'default = "{default}"']  # fmt: skip
    if fmt_line:
        lines.append(f"formats = {{ {fmt_line} }}")
    return "\n".join(lines) + "\n"


def _toml_key(name: str) -> str:
    """
    A column name as a TOML key, quoted if needed.

    Args:
        name (str): Column name.

    Returns:
        str: Bare key or quoted string.
    """
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else '"' + name.replace('"', '\\"') + '"'


def _toml_list(items: list[str]) -> str:
    """
    A list of strings in TOML.

    Args:
        items (list[str]): Strings.

    Returns:
        str: e.g. ["engine", "arm"].
    """
    return "[" + ", ".join('"' + i.replace('"', '\\"') + '"' for i in items) + "]"


def scaffold(tables: Path) -> tuple[str, int]:
    """
    A starting spec for every CSV under a directory.

    Args:
        tables (Path): Directory of result tables (searched recursively).

    Returns:
        tuple[str, int]: The spec text and the number of tables.
    """
    files = sorted(tables.rglob("*.csv"))
    head = ("# provenum spec, guessed by `provenum init` from the tables in "
            f"{tables.as_posix()}.\n# Check each guess, then run: provenum values <this file> "
            "--tables <dir> --out numbers.tex\n")  # fmt: skip
    return head + "\n" + "\n".join(table_spec(f, tables) for f in files), len(files)
