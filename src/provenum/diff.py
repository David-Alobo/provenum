"""What a rerun changed: compare two values files and find the sentences that cite each change.

Regenerating `numbers.tex` updates every number in the paper, but the words around a number do
not update. This module lists the cited values that changed, with their sentences, and flags the
changes that can break the claim around a number: a difference that changes sign, a p-value that
crosses the significance level, and an interval that starts or stops including zero.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from provenum.latex import _clean

SET = r"\provenumset{"
VAL = re.compile(r"\\val\{([^{}]*)\}")
LOW = re.compile(r"^(.*?)_?(low|lo|lower)$")
HIGH = re.compile(r"^(.*?)_?(high|hi|upper)$")


@dataclass
class Change:
    """One value that differs between the old and new values files."""

    path: str
    old: str | None  # formatted text, None if the value is new
    new: str | None  # formatted text, None if the value was removed
    flags: list[str] = field(default_factory=list)


@dataclass
class Use:
    """One citation of a value in the manuscript."""

    file: str
    line: int
    sentence: str


def read_values(text: str) -> dict[str, str]:
    """
    Parse a values file into path -> formatted text.

    Args:
        text (str): Content of a file written by `provenum values`.

    Returns:
        dict[str, str]: Formatted text per `\\val{}` path, e.g. "+6.8" or "\\ensuremath{-}2.1".
    """
    out, i = {}, 0
    while (i := text.find(SET, i)) >= 0:
        j = text.find("}", i + len(SET))
        path = text[i + len(SET) : j]
        if j + 1 >= len(text) or text[j + 1] != "{":
            i = j
            continue
        depth, k = 0, j + 1
        for k in range(j + 1, len(text)):
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            if depth == 0:
                break
        out[path] = text[j + 2 : k]
        i = k
    return out


def number(text: str | None) -> float | None:
    """
    The numeric value of a formatted value.

    Args:
        text (str | None): e.g. "+6.8", "\\ensuremath{-}2.1", "\\ensuremath{4.1 \\times 10^{-4}}".

    Returns:
        float | None: The value, or None if the text is not a number (e.g. "--").
    """
    if text is None:
        return None
    t = text.replace(r"\ensuremath{-}", "-")
    t = re.sub(r"\\ensuremath\{(.*)\}", r"\1", t).replace("−", "-")
    m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*\\times\s*10\^\{?(-?\d+)\}?\s*", t)
    if m:
        return float(m.group(1)) * 10 ** int(m.group(2))
    try:
        return float(t.strip().lstrip("+").replace(",", ""))
    except ValueError:
        return None


def old_from_git(path: Path, rev: str) -> str:
    """
    The content of a file at a git revision.

    Args:
        path (Path): File in a git working tree.
        rev (str): Revision, e.g. "HEAD" or "main".

    Returns:
        str: The file's content at that revision.

    Raises:
        RuntimeError: If git cannot show the file.
    """
    result = subprocess.run(
        ["git", "show", f"{rev}:./{path.name}"],
        cwd=path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git show {rev} failed")
    return result.stdout


def _is_p(column: str) -> bool:
    """
    Whether a column holds p-values (or q-values).

    Args:
        column (str): Column name, the last part of a path.

    Returns:
        bool: True for p, q, p_*, *_p.
    """
    return column in ("p", "q") or column.startswith("p_") or column.endswith("_p")


def _bounds(values: dict[str, str]) -> dict[str, tuple[str, str]]:
    """
    Pair interval bounds that share a row and a column stem (x_low/x_high, ci_lo/ci_hi, ...).

    Args:
        values (dict[str, str]): Values by path.

    Returns:
        dict[str, tuple[str, str]]: Row prefix plus stem -> (low path, high path).
    """
    lows, highs = {}, {}
    for path in values:
        row, _, column = path.rpartition("/")
        if m := LOW.match(column):
            lows[f"{row}/{m.group(1)}"] = path
        elif m := HIGH.match(column):
            highs[f"{row}/{m.group(1)}"] = path
    return {k: (lows[k], highs[k]) for k in lows.keys() & highs.keys()}


def compare(old: dict[str, str], new: dict[str, str], alpha: float = 0.05) -> list[Change]:
    """
    Every value that was added, removed or changed, with flags for claim-breaking changes.

    Args:
        old (dict[str, str]): Values before the rerun.
        new (dict[str, str]): Values after the rerun.
        alpha (float): Significance level for p-value crossings.

    Returns:
        list[Change]: Sorted by path.
    """
    changes = {}
    for path in old.keys() | new.keys():
        a, b = old.get(path), new.get(path)
        if a == b:
            continue
        c = Change(path, a, b)
        x, y = number(a), number(b)
        if x is not None and y is not None:
            if x * y < 0:
                c.flags.append("sign changed")
            if _is_p(path.rpartition("/")[2]) and (x < alpha) != (y < alpha):
                c.flags.append(f"now {'below' if y < alpha else 'not below'} {alpha:g}")
        changes[path] = c
    for low, high in _bounds(new).values():
        if low not in changes and high not in changes:
            continue
        before = [number(old.get(p)) for p in (low, high)]
        after = [number(new.get(p)) for p in (low, high)]
        if None in before or None in after:
            continue
        had, has = before[0] <= 0 <= before[1], after[0] <= 0 <= after[1]
        if had != has:
            flag = "interval now includes 0" if has else "interval no longer includes 0"
            for p in (low, high):
                if p in changes:
                    changes[p].flags.append(flag)
    return sorted(changes.values(), key=lambda c: c.path)


def uses(files: list[Path]) -> dict[str, list[Use]]:
    """
    Where each path is cited, with the sentence around each citation.

    Args:
        files (list[Path]): Manuscript files.

    Returns:
        dict[str, list[Use]]: Citations per path.
    """
    out: dict[str, list[Use]] = {}
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        para: list[int] = []
        for i, raw in enumerate([*lines, ""]):
            if raw.strip():
                para.append(i)
                continue
            if not para:
                continue
            text, starts = "", []
            for n in para:
                starts.append((len(text), n))
                text += re.sub(r"(?<!\\)%.*", "", lines[n]).strip() + " "
            for m in VAL.finditer(text):
                line = max(n for pos, n in starts if pos <= m.start()) + 1
                s0 = text.rfind(". ", 0, m.start())
                s1 = text.find(". ", m.end())
                sentence = text[s0 + 2 if s0 >= 0 else 0 : s1 + 1 if s1 >= 0 else len(text)]
                out.setdefault(m.group(1), []).append(Use(str(f), line, sentence.strip()))
            para = []
    return out


def _plain(text: str | None) -> str:
    """
    A formatted value as plain text.

    Args:
        text (str | None): Formatted value, or None.

    Returns:
        str: e.g. "-2.1", "4.1e-04", or "(none)".
    """
    if text is None:
        return "(none)"
    x = number(text)
    if x is not None and r"\times" in text:
        return f"{x:.1e}"
    return text.replace(r"\ensuremath{-}", "-")


def _show(sentence: str, changed: dict[str, Change], new: dict[str, str]) -> str:
    """
    A sentence as a reader sees it, with each changed value shown as [old -> new].

    Args:
        sentence (str): LaTeX sentence with `\\val{}` calls.
        changed (dict[str, Change]): Changes by path.
        new (dict[str, str]): New values, for the unchanged citations.

    Returns:
        str: Plain text.
    """

    def one(m: re.Match) -> str:
        """
        Text for one citation.

        Args:
            m (re.Match): A `\\val{}` match.

        Returns:
            str: The value, or [old -> new] for a changed path.
        """
        c = changed.get(m.group(1))
        if c:
            return f"[{_plain(c.old)} -> {_plain(c.new)}]"
        return _plain(new.get(m.group(1)))

    text = _clean(VAL.sub(one, sentence))
    for latex, shown in ((r"\%", "%"), (r"\AA{}", "Å"), (r"\AA", "Å"), ("~", " "), ("$", "")):
        text = text.replace(latex, shown)
    return " ".join(text.split())


def _notes(c: Change) -> list[str]:
    """
    What a reader should check about one change.

    Args:
        c (Change): A change.

    Returns:
        list[str]: Its flags, plus a note if the value was removed.
    """
    return c.flags + (["removed: the text will show ??"] if c.new is None else [])


def report(changes: list[Change], cited: dict[str, list[Use]], new: dict[str, str],
           markdown: bool = False, show_all: bool = False) -> str:  # fmt: skip
    """
    A readable report, one entry per affected sentence, flagged sentences first.

    Args:
        changes (list[Change]): From `compare`.
        cited (dict[str, list[Use]]): From `uses`.
        new (dict[str, str]): New values.
        markdown (bool): Markdown (e.g. for a pull-request comment) instead of plain text.
        show_all (bool): Also list changed values the manuscript does not cite.

    Returns:
        str: The report.
    """
    # A value that is new (a table added since the old version) changes no existing claim, so it
    # is counted, not listed.
    added = [c for c in changes if c.old is None and c.path in cited]
    by_path = {c.path: c for c in changes if c.path in cited and c.old is not None}
    sentences: dict[tuple[str, str], dict] = {}
    for path, c in by_path.items():
        for u in cited[path]:
            s = sentences.setdefault((u.file, u.sentence), {"line": u.line, "changes": {}})
            s["line"] = min(s["line"], u.line)
            s["changes"][path] = c
    look = sum(any(_notes(c) for c in s["changes"].values()) for s in sentences.values())
    title = (f"{'## ' if markdown else ''}provenum diff: {len(by_path)} cited value(s) changed "
             f"in {len(sentences)} sentence(s); {look} need a look")  # fmt: skip
    lines = [title, ""]

    def order(item: tuple) -> tuple:
        """
        Flagged sentences first, then by file and line.

        Args:
            item (tuple): ((file, sentence), info).

        Returns:
            tuple: Sort key.
        """
        (file, _), info = item
        return (not any(_notes(c) for c in info["changes"].values()), file, info["line"])

    for (file, sentence), info in sorted(sentences.items(), key=order):
        text = _show(sentence, info["changes"], new)
        flagged = [(p, c) for p, c in sorted(info["changes"].items()) if _notes(c)]
        if markdown:
            mark = " **needs a look**" if flagged else ""
            lines.append(f"- `{file}:{info['line']}`{mark}\n  > {text}")
            lines += [f"  - `{p}` {_plain(c.old)} → {_plain(c.new)}: {'; '.join(_notes(c))}"
                      for p, c in flagged]  # fmt: skip
        else:
            lines.append(f"{file}:{info['line']}{'  NEEDS A LOOK' if flagged else ''}")
            lines.append(f"    {text}")
            lines += [f"    ! {p}: {_plain(c.old)} -> {_plain(c.new)}: {'; '.join(_notes(c))}"
                      for p, c in flagged]  # fmt: skip
        lines.append("")
    if added:
        lines.append(f"{len(added)} cited value(s) are new since the old values file.")
    others = [c for c in changes if c.path not in cited and c.old is not None]
    new_uncited = sum(c.path not in cited and c.old is None for c in changes)
    if new_uncited:
        lines.append(f"{new_uncited} uncited value(s) are new.")
    if others:
        lines.append(f"{len(others)} changed value(s) are not cited in the text.")
        if show_all:
            lines += [f"  {c.path}: {_plain(c.old)} -> {_plain(c.new)}"
                      + (f"  ({'; '.join(c.flags)})" if c.flags else "") for c in others]  # fmt: skip
    return "\n".join(lines).rstrip() + "\n"
