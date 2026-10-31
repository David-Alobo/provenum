"""Migrate a manuscript to \\val{}: replace anchored numbers whose value checks out, and only those.

A number is replaced only when the anchored value, formatted as the spec says, reproduces what
is written (so the compiled text does not change). Everything else is left as written and
reported: a path the model gave that doesn't exist, a value that doesn't match (a real
discrepancy to look at), or a formatting difference (e.g. the text rounds to two decimals and
the spec to three).
"""

import re
import shutil
from collections import defaultdict
from pathlib import Path

from provenum.anchor import items as find_items
from provenum.anchor import judge


def _plain(text: str) -> str:
    """
    Reduce LaTeX number text to a comparable plain form.

    Args:
        text (str): e.g. "\\ensuremath{-}1.9", "$4.1 \\times 10^{-4}$", "+6.8".

    Returns:
        str: e.g. "-1.9", "4.1x10^-4", "+6.8".
    """
    text = re.sub(r"\\ensuremath\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", r"\1", text)
    text = text.replace("$", "").replace("−", "-").replace("\\times", "x").replace(" ", "")
    return text.replace("{", "").replace("}", "")


def find_span(line: str, written: str, formatted: str) -> tuple[int, int] | None:
    """
    Where a written number can be replaced by a value without changing the compiled text.

    Args:
        line (str): Manuscript line holding the number.
        written (str): The number as written (from `anchor.items`).
        formatted (str): The value's LaTeX text (from `anchor.values`).

    Returns:
        tuple[int, int] | None: (start, end) of the span to replace, or None if no span around
            the number reproduces the formatted value.
    """
    target = _plain(formatted)
    # Candidate spans around the written number: as is, with a sign, or a whole $...$.
    spans = [re.escape(written)]
    spans = [rf"\$\s*{s}\s*\$" for s in spans] + [rf"[+]{s}" for s in spans] + spans
    for pattern in spans:
        m = next((m for m in re.finditer(rf"(?<![\w.]){pattern}(?![\w])", line)), None)
        if m and _plain(m.group()) == target:
            return m.start(), m.end()
    return None


def migrate(
    path: str | Path, answers: list[dict], table: dict, dry_run: bool = False
) -> list[dict]:
    """
    Replace anchored numbers with \\val{path} in a manuscript.

    Args:
        path (str | Path): Manuscript file (rewritten in place, with a .bak copy, unless dry_run).
        answers (list[dict]): [{id, path}] from anchoring, ids as in `anchor.items`.
        table (dict): `anchor.values` output (path -> (value, formatted text)).
        dry_run (bool): Report only.

    Returns:
        list[dict]: Per anchored item: line, number, path and status ("replaced",
            "bad-path", "mismatch", "format-differs", "not-found").
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").split("\n")
    found = {i["id"]: i for i in find_items(path)}
    by_line = defaultdict(list)
    report = []
    for a in answers:
        item = found.get(a["id"])
        if not item or not a.get("path"):
            continue
        status = judge(item["number"], a["path"], table)
        entry = {
            "id": item["id"],
            "line": item["line"],
            "number": item["number"],
            "path": a["path"],
            "status": status,
        }
        report.append(entry)
        if status == "traced":
            by_line[item["line"]].append((item, a["path"], entry))
    for line_no, group in by_line.items():
        line = lines[line_no - 1]
        for item, val_path, entry in group:
            written = item.get("written", item["number"])
            span = find_span(line, written, table[val_path][1])
            if span:
                line = line[: span[0]] + rf"\val{{{val_path}}}" + line[span[1] :]
                entry["status"] = "replaced"
            else:
                entry["status"] = (
                    "format-differs" if re.search(re.escape(written), line) else "not-found"
                )
        lines[line_no - 1] = line
    if not dry_run:
        shutil.copy(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(
            "\n".join(lines), encoding="utf-8", newline=""
        )  # keep the file's line endings
    return report
