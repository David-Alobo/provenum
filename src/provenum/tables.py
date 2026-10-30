"""Load the numbers a project's result tables hold, and the simple values derived from them."""

import csv
import fnmatch
import itertools
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    """Where a candidate value comes from."""

    value: float
    file: str
    row: int  # 1-based data row
    column: str
    label: str  # the row's text cells, to show a reader which row it is
    how: str  # "cell", "cell x 100", "difference", ...


def _float(cell: str) -> float | None:
    """
    Parse a table cell as a number.

    Args:
        cell (str): Cell text.

    Returns:
        float | None: The number, or None for text and empty cells.
    """
    try:
        return float(cell)
    except ValueError:
        return None


def load(paths: list[str | Path], derived: bool = True, exclude: list[str] = ()) -> list[Source]:
    """
    Read every numeric cell of the given CSV files (directories are searched recursively).

    Each cell also yields its value times 100 when it looks like a proportion (|v| <= 1), so
    that 0.530 matches "53.0%". With `derived`, differences between numeric cells of the same
    row are added (and times 100), so that "+6.8 points" can trace to two rates.

    Args:
        paths (list[str | Path]): CSV files or directories holding them.
        derived (bool): Also generate within-row differences.
        exclude (list[str]): Glob patterns (matched against path endings) of files to skip.

    Returns:
        list[Source]: Candidate values with their provenance.
    """
    files = []
    for p in map(Path, paths):
        files += sorted(p.rglob("*.csv")) if p.is_dir() else [p]
    files = [
        f for f in files if not any(fnmatch.fnmatch(f.as_posix(), "*" + pat) for pat in exclude)
    ]
    out = []
    for f in files:
        with open(f, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            continue
        header = rows[0]
        for i, row in enumerate(rows[1:], 1):
            label = " ".join(c for c in row if c and _float(c) is None)[:80]
            numeric = [(header[j] if j < len(header) else str(j), v)
                       for j, c in enumerate(row) if (v := _float(c)) is not None]  # fmt: skip
            for col, v in numeric:
                out.append(Source(v, str(f), i, col, label, "cell"))
                if abs(v) <= 1:
                    out.append(Source(100 * v, str(f), i, col, label, "cell x 100"))
            if derived:
                for (c1, a), (c2, b) in itertools.permutations(numeric, 2):
                    if abs(a) <= 1 and abs(b) <= 1:
                        out.append(
                            Source(
                                100 * (a - b), str(f), i, f"{c1} - {c2}", label, "difference x 100"
                            )
                        )
                    out.append(Source(a - b, str(f), i, f"{c1} - {c2}", label, "difference"))
    return out
