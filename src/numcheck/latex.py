"""Find the numbers a LaTeX manuscript states, with where they are and how precisely they are given."""

import math
import re
from dataclasses import dataclass
from pathlib import Path

# Commands whose arguments hold labels, keys, paths or layout, never results.
DROP_COMMANDS = re.compile(
    r"\\(?:label|ref|eqref|autoref|cref|Cref|cite[a-z]*|includegraphics|input|include|url|href|"
    r"setlength|addlinespace|cmidrule|hspace|vspace|begin|end|bibliography|bibliographystyle|"
    r"usepackage|documentclass|graphicspath|newcommand|renewcommand|section|subsection|caption\*?)"
    r"\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*"
)
SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\\times|×)\s*10\^\{?\s*([-−]?\d+)\s*\}?")
NUMBER = re.compile(r"(?<![\w.\\])([-−]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])")


@dataclass(frozen=True)
class Stated:
    """One number as stated in the text."""

    file: str
    line: int
    text: str  # as written, e.g. "53.0", "4.1e-4"
    value: float
    decimals: int  # digits after the point (of the mantissa for scientific notation)
    exponent: int  # power of ten for scientific notation, else 0
    percent: bool
    context: str

    @property
    def half_step(self) -> float:
        """Half the last stated digit: how far the true value can be from the stated one."""
        return 0.5 * 10.0 ** (self.exponent - self.decimals)

    @property
    def is_integer(self) -> bool:
        """Whether the number was written without a decimal point or exponent."""
        return self.decimals == 0 and self.exponent == 0


def _clean(line: str) -> str:
    """
    Remove comments and the arguments of non-result commands from one LaTeX line.

    Args:
        line (str): Source line.

    Returns:
        str: The line with comments and label-like commands blanked out.
    """
    line = re.sub(r"(?<!\\)%.*", "", line)
    line = DROP_COMMANDS.sub(" ", line)
    line = re.sub(r"\\(?:SI|num|qty)\{([^{}]*)\}(?:\{[^{}]*\})?", r" \1 ", line)  # keep the value
    line = re.sub(
        r"\\SIlist\{([^{}]*)\}\{[^{}]*\}", lambda m: " " + m.group(1).replace(";", " ") + " ", line
    )
    line = line.replace("--", " – ")  # ranges: 0.83--0.90 is two numbers, not a subtraction
    return line


def extract(path: str | Path, min_integer: int = 10) -> list[Stated]:
    """
    List the numbers stated in a LaTeX or Markdown file.

    Integers below `min_integer` (small counts, list positions, design constants) and plausible
    years are skipped: they are too ambiguous to trace.

    Args:
        path (str | Path): Manuscript file.
        min_integer (int): Smallest integer worth checking.

    Returns:
        list[Stated]: Numbers in reading order.
    """
    path = Path(path)
    found = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _clean(raw)
        taken = []
        for m in SCI.finditer(line):
            mantissa, exponent = m.group(1), int(m.group(2).replace("−", "-"))
            decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
            found.append(Stated(str(path), n, f"{mantissa}e{exponent}", float(mantissa) * 10.0**exponent,
                                decimals, exponent, False, raw.strip()[:160]))  # fmt: skip
            taken.append(m.span())
        for m in NUMBER.finditer(line):
            if any(a <= m.start() < b for a, b in taken):
                continue
            sign = -1.0 if m.group(1) else 1.0
            whole, frac = m.group(2).replace(",", ""), m.group(3) or ""
            value = sign * float(whole + frac)
            decimals = len(frac) - 1 if frac else 0
            if decimals == 0 and (abs(value) < min_integer or 1900 <= value <= 2100):
                continue
            after = line[m.end() : m.end() + 3]
            percent = after.startswith("\\%") or after.startswith("%")
            found.append(
                Stated(str(path), n, m.group(0), value, decimals, 0, percent, raw.strip()[:160])
            )
    return found


def is_close(stated: Stated, value: float) -> bool:
    """
    Whether a value would be written as the stated number after rounding.

    Args:
        stated (Stated): Number from the text.
        value (float): Candidate true value.

    Returns:
        bool: True if `value` rounds to the stated digits.
    """
    if not math.isfinite(value):
        return False
    return abs(value - stated.value) <= stated.half_step * (1 + 1e-9) + 1e-12
