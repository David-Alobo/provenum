"""AI-assisted anchoring: a language model says which table value each stated number reports.

The model only chooses a `\\val{}` path (or none); provenum then checks the value itself, so the
model can propose but never certify. The same paths drive prevention mode, so a confirmed
anchor doubles as an automatic conversion of a hard-coded number into `\\val{...}`.
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from provenum.latex import SCI, _clean
from provenum.macros import TableSpec, cells, fmt


def catalogue(specs: list[TableSpec], root: str | Path) -> str:
    """
    Describe the addressable values for the model: path pattern, key values and columns.

    Args:
        specs (list[TableSpec]): Tables in prevention mode.
        root (str | Path): Directory the spec paths are relative to.

    Returns:
        str: A compact plain-text catalogue.
    """
    parts = []
    for spec in specs:
        with open(Path(root) / spec.file, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        prefix = spec.file.removesuffix(".csv")
        values = {k: sorted({r[k] for r in rows}) for k in spec.keys}
        if spec.value_column:  # one value per row: the path ends at the keys
            parts.append(
                f"{prefix}/" + "/".join(f"<{k}>" for k in spec.keys) + "\n"
                + "".join(f"  {k}: {', '.join(v)}\n" for k, v in values.items())
            )  # fmt: skip
            continue
        columns = [c for c in rows[0] if c not in spec.keys] if rows else []
        parts.append(
            f"{prefix}/"
            + "/".join(f"<{k}>" for k in spec.keys)
            + "/<column>\n"
            + "".join(f"  {k}: {', '.join(v)}\n" for k, v in values.items())
            + f"  columns: {', '.join(columns)}\n"
        )
    return "\n".join(parts)


def values(specs: list[TableSpec], root: str | Path) -> dict[str, tuple[float, str]]:
    """
    Every addressable value: path -> (raw value, formatted text).

    Args:
        specs (list[TableSpec]): Tables in prevention mode.
        root (str | Path): Directory the spec paths are relative to.

    Returns:
        dict[str, tuple[float, str]]: Values by `\\val{}` path.
    """
    out = {}
    for spec in specs:
        for path, v, how in cells(spec, root):
            out[path] = (v, fmt(v, how, spec.value_column or path.rpartition("/")[2]))
    return out


def items(path: str | Path) -> list[dict]:
    """
    Decimal numbers in prose, each with its sentence and paragraph, for the model to anchor.

    Args:
        path (str | Path): Manuscript file.

    Returns:
        list[dict]: {id, line, number, sentence, paragraph} per hard-coded decimal.
    """
    raws = Path(path).read_text(encoding="utf-8").splitlines()
    out, para, in_tab = [], [], False
    paragraphs = []
    for i, raw in enumerate(raws + [""]):
        if "\\begin{tabular" in raw:
            in_tab = True
        if raw.strip() and not in_tab:
            para.append(i)
        elif para:
            paragraphs.append(para)
            para = []
        if "\\end{tabular" in raw:
            in_tab = False
    for para in paragraphs:
        text = " ".join(_clean(raws[i]) for i in para)
        starts, pos = [], 0
        for i in para:
            starts.append((pos, i))
            pos += len(_clean(raws[i])) + 1
        # Scientific notation first (4.1 \times 10^{-4} is one number), then plain decimals.
        found = [(m.start(), m.end(), f"{m.group(1)}e{m.group(2).replace('−', '-')}", m.group(0))
                 for m in SCI.finditer(text)]  # fmt: skip
        found += [(m.start(), m.end(), m.group(), m.group())
                  for m in re.finditer(r"(?<![\w.\\])[-−]?\d+\.\d+(?![\w])", text)
                  if not any(a <= m.start() < b for a, b, _, _ in found)]  # fmt: skip
        for start, end, number, written in sorted(found):
            s0 = max(text.rfind(". ", 0, start) + 2, 0)
            s1 = text.find(". ", end)
            sentence = text[s0 : s1 + 1 if s1 > 0 else len(text)]
            line = max(i for p, i in starts if p <= start) + 1
            marked = sentence.replace(written, f"[[{written}]]", 1)
            out.append({"id": len(out), "line": line, "number": number, "written": written,
                        "sentence": " ".join(marked.split()),
                        "paragraph": " ".join(text.split())[:1200]})  # fmt: skip
    return out


def judge(stated: str, path: str | None, table: dict[str, tuple[float, str]]) -> str:
    """
    Check a stated number against the value at the model's chosen path.

    Args:
        stated (str): The number as written.
        path (str | None): The model's `\\val{}` path, or None.
        table (dict): Output of `values`.

    Returns:
        str: "unanchored", "bad-path", "traced" or "mismatch".
    """
    if not path:
        return "unanchored"
    if path not in table:
        return "bad-path"
    value, _ = table[path]
    s = float(stated.replace("−", "-"))
    mantissa, _, exponent = stated.replace("−", "-").partition("e")
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    half = 0.5 * 10.0 ** (int(exponent or 0) - decimals) * (1 + 1e-9) + 1e-15
    for candidate in (value, 100 * value, -value, -100 * value):
        if abs(abs(candidate) - abs(s)) <= half:
            return "traced"
    return "mismatch"


def by_status(results: list[str]) -> dict[str, int]:
    """
    Count judgements.

    Args:
        results (list[str]): Output of `judge` per item.

    Returns:
        dict[str, int]: Count per status.
    """
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        counts[r] += 1
    return dict(counts)


def dump(path: str | Path, rows: list[dict]) -> None:
    """
    Write items or answers as JSON.

    Args:
        path (str | Path): Output file.
        rows (list[dict]): Data.
    """
    Path(path).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
