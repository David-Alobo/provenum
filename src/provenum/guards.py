"""Claim checks: do the words around each number still match its value?

Two kinds of check run on the manuscript with the current values:

- Guards are written by the author: `\\val[>0]{path}` says the value must be positive. A guard is
  one or more comparisons separated by commas (`>`, `>=`, `<`, `<=`, `=`, `!=`) against a number
  or another path, e.g. `\\val[<0.05]{...}` or `\\val[>summary/vina/base/top1]{...}`. A failed
  guard is an error.
- Wording checks are heuristics on common phrasings: "rose from X to Y" with X above Y (or "fell"
  with X below Y); a direction word next to a signed change of the opposite sign ("rose by
  -2.1"); and "significant" or "not significant" contradicted by every p-value in the sentence.
  They are warnings, to be read by a person.
"""

import operator
import re
from dataclasses import dataclass
from pathlib import Path

from provenum.diff import number, sentences
from provenum.macros import VAL

OPS = {">=": operator.ge, "<=": operator.le, "!=": operator.ne, ">": operator.gt,
       "<": operator.lt, "=": operator.eq}  # fmt: skip
GUARD = re.compile(r"\s*(>=|<=|!=|>|<|=)\s*([^,\s]+)\s*")

UP = r"(?:rose|risen|increased|improved|grew|climbed|went up|raised)"
DOWN = r"(?:fell|fallen|decreased|dropped|declined|went down|lowered|worsened)"
# A citation, allowing an optional guard; the path is captured.
CITE = r"\\val(?:\[[^\]]*\])?\{([^{}]*)\}"
FROM_TO = re.compile(rf"\b({UP}|{DOWN})\s+from\s+{CITE}[^.;]{{0,25}}?\bto\s+{CITE}", re.IGNORECASE)
# "rose by +6.8", "raising success to 53.0% (+6.8 points", "an increase of +3.0": a direction
# word, judged by the first signed change cited after it in the same clause.
DIRECTION = re.compile(
    rf"\b({UP}|{DOWN}|raising|lowering|an increase of|a decrease of|a gain of|a drop of|"
    rf"a loss of)\b",
    re.IGNORECASE,
)
UP_PHRASES = ("raising", "an increase of", "a gain of")
REACH = 300  # LaTeX characters after the direction word to search (\val paths are long)
SIGNIFICANT = re.compile(r"\b(?:in)?significan(?:t|tly|ce)\b", re.IGNORECASE)
# A negation in the same clause shortly before the word: "did not change ... significantly",
# "no significant", "neither ... significant", "insignificant".
NEGATION = re.compile(r"\b(?:not|no|non|nor|neither|without)\b[^;:,()]{0,40}$", re.IGNORECASE)


@dataclass
class Finding:
    """One failed guard or suspicious wording."""

    file: str
    line: int
    kind: str  # "guard" (error) or "wording" (warning)
    message: str
    sentence: str


def _is_p(path: str) -> bool:
    """
    Whether a path's column holds p-values (or q-values).

    Args:
        path (str): A `\\val{}` path.

    Returns:
        bool: True for p, q, p_*, *_p columns.
    """
    column = path.rpartition("/")[2]
    return column in ("p", "q") or column.startswith("p_") or column.endswith("_p")


def _signed(text: str | None) -> bool:
    """
    Whether a formatted value shows its sign (a change rather than a magnitude).

    Args:
        text (str | None): Formatted value.

    Returns:
        bool: True for "+6.8" or "\\ensuremath{-}2.1".
    """
    return bool(text) and (text.startswith(("+", r"\ensuremath{-}")))


def check_guard(guard: str, path: str, values: dict[str, str]) -> str | None:
    """
    Evaluate one guard.

    Args:
        guard (str): e.g. ">0", "<0.05", ">=40,<=60" or ">summary/vina/base/top1".
        path (str): The guarded path.
        values (dict[str, str]): Current values.

    Returns:
        str | None: Why the guard fails, or None if it holds.
    """
    if path not in values:
        return f"{path} has no value"
    x = number(values[path])
    if x is None:
        return f"{path} is not a number ({values[path]})"
    for part in guard.split(","):
        m = GUARD.fullmatch(part)
        if not m:
            return f"cannot read guard [{part.strip()}]"
        op, rhs = m.groups()
        y = number(values[rhs]) if rhs in values else number(rhs)
        if y is None:
            return f"guard [{part.strip()}]: {rhs} is neither a number nor a known path"
        if not OPS[op](x, y):
            other = f" ({rhs} is {y:g})" if rhs in values else ""
            return f"guard [{part.strip()}] fails: {path} is {x:g}{other}"
    return None


def check(files: list[Path], values: dict[str, str], alpha: float = 0.05) -> list[Finding]:
    """
    Run guards and wording checks over the manuscript.

    Args:
        files (list[Path]): Manuscript files.
        values (dict[str, str]): Current values (from `diff.read_values`).
        alpha (float): Significance level for the "significant" wording check.

    Returns:
        list[Finding]: Failed guards and suspicious wording, in reading order.
    """
    out = []
    for f, line, sentence in sentences(files):

        def add(kind: str, message: str, f: Path = f, line: int = line, s: str = sentence) -> None:
            """
            Record a finding for the current sentence.

            Args:
                kind (str): "guard" or "wording".
                message (str): What is wrong.
                f (Path): File.
                line (int): Line.
                s (str): Sentence.
            """
            out.append(Finding(str(f), line, kind, message, s))

        for m in VAL.finditer(sentence):
            if m.group(1) is not None and (why := check_guard(m.group(1), m.group(2), values)):
                add("guard", why)

        for m in FROM_TO.finditer(sentence):
            word, a, b = (
                m.group(1).lower(),
                number(values.get(m.group(2))),
                number(values.get(m.group(3))),
            )
            if a is None or b is None or a == b:
                continue
            up = re.fullmatch(UP, word) is not None
            if up != (b > a):
                add("wording", f'"{m.group(1)} from {a:g} to {b:g}"')

        for m in DIRECTION.finditer(sentence):
            for c in VAL.finditer(sentence, m.end(), m.end() + REACH):
                between = sentence[m.end() : c.start()]
                # A new clause, or a "from ... to ..." sequence, ends the search.
                if ";" in between or re.search(r"\bfrom\b", between, re.IGNORECASE):
                    break
                text = values.get(c.group(2))
                if not _signed(text):
                    continue  # a rate or bound, not the change
                x = number(text)
                word = m.group(1).lower()
                up = re.fullmatch(UP, word) is not None or word in UP_PHRASES
                if x and up != (x > 0):
                    add("wording", f'"{m.group(1)}" with a {"negative" if x < 0 else "positive"} '
                                   f"change ({x:g})")  # fmt: skip
                break

        # Each mention of significance is judged by the first p-value cited after it in the
        # sentence ("did not differ significantly (p = ...)"); a mention with no p-value after it
        # is skipped, since the sentence may be about values it does not cite.
        ps = [(m.start(), number(values.get(m.group(2))))
              for m in VAL.finditer(sentence) if _is_p(m.group(2))]  # fmt: skip
        for m in SIGNIFICANT.finditer(sentence):
            after = [p for pos, p in ps if pos > m.end() and p is not None]
            if not after:
                continue
            negated = m.group().lower().startswith("insig") or bool(
                NEGATION.search(sentence[: m.start()])
            )
            p = after[0]
            if negated and p < alpha:
                add("wording", f'"not significant" but the p-value after it is {p:g}')
            elif not negated and p >= alpha:
                add("wording", f'"{m.group()}" but the p-value after it is {p:g}')
    return out
