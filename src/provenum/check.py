"""Trace every stated number to the result tables, and report the ones that don't trace."""

import bisect
from dataclasses import dataclass

from provenum.latex import Stated, is_close
from provenum.tables import Source

TIERS = ("cell", "cell x 100", "difference", "difference x 100")


@dataclass(frozen=True)
class Verdict:
    """The outcome for one stated number."""

    stated: Stated
    status: str  # "traced", "derived" or "untraced"
    sources: tuple[Source, ...]  # every candidate that rounds to the stated number, best tier first


def check(stated: list[Stated], sources: list[Source]) -> list[Verdict]:
    """
    Match each stated number to the table values that round to it.

    A number traces directly if a cell (or a proportion as a percentage) rounds to it, and is
    derived if only a within-row difference does. Integers must match exactly. Signs are
    ignored, since text often writes a fall as a positive number ("fell by 2.1 points").

    Args:
        stated (list[Stated]): Numbers from `latex.extract`.
        sources (list[Source]): Candidates from `tables.load`.

    Returns:
        list[Verdict]: One per stated number, in input order.
    """
    by_value = sorted(sources, key=lambda s: abs(s.value))
    keys = [abs(s.value) for s in by_value]
    verdicts = []
    for st in stated:
        target, step = abs(st.value), st.half_step * (1 + 1e-9) + 1e-12
        lo, hi = bisect.bisect_left(keys, target - step), bisect.bisect_right(keys, target + step)
        hits = [s for s in by_value[lo:hi] if is_close(st, abs(s.value) * (1 if st.value >= 0 else -1))
                or is_close(st, abs(s.value))]  # fmt: skip
        if st.is_integer:
            hits = [s for s in hits if s.value == round(s.value)]
        hits.sort(key=lambda s: TIERS.index(s.how))
        if any(h.how.startswith("cell") for h in hits):
            status = "traced"
        elif hits:
            status = "derived"
        else:
            status = "untraced"
        verdicts.append(Verdict(st, status, tuple(hits)))
    return verdicts
