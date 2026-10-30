"""Record values straight from analysis code, so a number never has to be copied by hand.

A number computed in a script or notebook, such as a ratio or a count, often never reaches a
results table, and then nothing in the paper can be traced to it. `record` writes it to a small
table (recorded.csv by default) with a name, the value, the format to show it in, and the file
that recorded it:

    import provenum
    provenum.record("vina_vs_gnina/ratio", gnina_rate / vina_rate, fmt="f1")

The manuscript then writes `\\val{recorded/vina_vs_gnina/ratio}`. Recording the same name again
replaces the row, so rerunning a notebook cell does not add duplicates. `provenum init` recognises
the table, and its spec entry is:

    [[table]]
    file = "recorded.csv"
    keys = ["name"]
    value = "value"
    format = "format"
"""

import csv
import inspect
import math
import os
import re
from pathlib import Path

from provenum.macros import fmt as format_value

COLUMNS = ["name", "value", "format", "source"]
NAME = re.compile(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*")
ENV = "PROVENUM_RECORD"


def record(name: str, value: float, fmt: str = "auto", file: str | Path | None = None) -> Path:
    """
    Write one named value to the recorded-values table, replacing any earlier value of that name.

    Args:
        name (str): Path below the table, e.g. "vina/box2/ratio" (letters, digits, _ . + -,
            separated by /).
        value (float): The number.
        fmt (str): provenum format, e.g. "pct1", "+f1", "p", "int" (see `macros.fmt`).
        file (str | Path | None): Table to write; default $PROVENUM_RECORD, else recorded.csv.

    Returns:
        Path: The table written.

    Raises:
        ValueError: If the name, value or format is not usable.
    """
    if not NAME.fullmatch(name):
        raise ValueError(f"name {name!r}: use letters, digits, _ . + - separated by /")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name}: value is {value}")
    format_value(value, fmt)  # raises ValueError for an unknown format
    path = Path(file or os.environ.get(ENV) or "recorded.csv")
    rows = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle) if r.get("name") != name]
    rows.append({"name": name, "value": repr(value), "format": fmt, "source": _caller()})
    rows.sort(key=lambda r: r["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)  # never leave a half-written table
    return path


def _caller() -> str:
    """
    The file that called `record`, for provenance (a notebook shows as its kernel file).

    Returns:
        str: File name, or "" if unknown.
    """
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame and frame.f_back else None
    return Path(caller.f_code.co_filename).name if caller else ""
