"""Context-anchored checking: a number must match the cell its own words point to.

Matching by value alone is too permissive: a results table holds thousands of values, so a
wrong number almost always equals some unrelated cell. Here each stated number carries the
words around it (or, inside a LaTeX table, its row label and column header), each table cell
carries its file, column and row labels, and the cells whose labels best match the number's
words are its anchors. The number is traced if it equals an anchor, a mismatch if the anchors
hold other values, and unanchored if its words point to no cell clearly enough to judge.
"""

import math
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from numcheck.latex import NUMBER, SCI, Stated, _clean, is_close
from numcheck.tables import Source

WORD = re.compile(r"[a-z][a-z0-9_]*|\d+")
BEFORE, AFTER = 12, 4  # context window, in tokens
CARRY = 0.25  # weight of earlier tokens in the same paragraph (who or what it is about)
# Confidence levels and similar fixed phrases are settings, not results ("95% Wilson interval").
SETTING = re.compile(r"\s*\\?%\s*(?:wilson|confidence|ci\b|bootstrap|interval|paired|credible)", re.I)


@dataclass
class Config:
    """Project-specific vocabulary linking prose to table labels."""

    aliases: list[tuple[re.Pattern, str]] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)  # table path globs to ignore
    min_anchor: float = 4.0  # context score below which a number is not judged
    ratio: float = 0.85  # a value match within this fraction of the best anchor counts

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        """
        Read a TOML config: [aliases] pattern = "replacement", exclude = [...], thresholds.

        Args:
            path (str | Path | None): Config file, or None for defaults.

        Returns:
            Config: The configuration.
        """
        if path is None:
            return cls()
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        aliases = [(re.compile(p, re.I), r) for p, r in data.get("aliases", {}).items()]
        return cls(aliases, data.get("exclude", []), data.get("min_anchor", 4.0), data.get("ratio", 0.85))


BUILTIN = [
    (re.compile(r"\\%|%"), " pct "),
    (re.compile(r"top-1"), " top1 "),
    (re.compile(r"pb-?valid|\\pbvalid\{?\}?"), " pb_valid "),
    (re.compile(r"\bpoints?\b|\bpts\b"), " pts "),
    (re.compile(r"\$?\bp\s*[=<]"), " p "),
]


def tokens(text: str, config: Config) -> list[str]:
    """
    Normalise text into match tokens: built-in and project aliases, then words and integers.

    Args:
        text (str): Prose, a LaTeX row, or a table label.
        config (Config): Project aliases.

    Returns:
        list[str]: Tokens in order.
    """
    text = text.lower()
    for pattern, repl in BUILTIN + config.aliases:
        text = pattern.sub(f" {repl} ", text)
    return WORD.findall(text)


@dataclass(frozen=True)
class InContext:
    """A stated number with the weighted tokens of its context."""

    stated: Stated
    context: dict[str, float]


def _numbers(text: str) -> list[tuple[int, int, str, float, int, int]]:
    """
    Find numbers in cleaned text: (start, end, text, value, decimals, exponent).

    Args:
        text (str): Cleaned LaTeX.

    Returns:
        list: Numbers with their spans, scientific notation first.
    """
    out, taken = [], []
    for m in SCI.finditer(text):
        mant, exp = m.group(1), int(m.group(2).replace("−", "-"))
        dec = len(mant.split(".")[1]) if "." in mant else 0
        out.append((m.start(), m.end(), f"{mant}e{exp}", float(mant) * 10.0**exp, dec, exp))
        taken.append(m.span())
    for m in NUMBER.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        whole, frac = m.group(2).replace(",", ""), m.group(3) or ""
        value = (-1.0 if m.group(1) else 1.0) * float(whole + frac)
        out.append((m.start(), m.end(), m.group(0), value, len(frac) - 1 if frac else 0, 0))
    return sorted(out)


def extract(path: str | Path, config: Config, min_integer: int = 10) -> list[InContext]:
    """
    Numbers in a LaTeX file, each with its weighted context tokens.

    Prose numbers take tokens from up to BEFORE tokens before and AFTER after them in the same
    paragraph, weighted by closeness. Numbers in a tabular row take the row's first cell and
    the column's header (the row before the first \\midrule), at full weight.

    Args:
        path (str | Path): Manuscript file.
        config (Config): Project aliases.
        min_integer (int): Smallest integer worth checking.

    Returns:
        list[InContext]: Numbers in reading order.
    """
    path = Path(path)
    lines = [_clean(raw) for raw in path.read_text(encoding="utf-8").splitlines()]
    raws = path.read_text(encoding="utf-8").splitlines()
    out: list[InContext] = []

    def keep(value: float, dec: int, exp: int) -> bool:
        return not (dec == 0 and exp == 0 and (abs(value) < min_integer or 1900 <= value <= 2100))

    # Tables: rows containing & inside a tabular.
    in_tab, header, table_lines = False, [], set()
    for i, raw in enumerate(raws):
        if "\\begin{tabular" in raw:
            in_tab, header = True, []
        if in_tab:
            table_lines.add(i)
            cells = [c.strip() for c in lines[i].replace("\\\\", "").split("&")]
            if "\\midrule" in raw:
                continue
            if len(cells) > 1 and not header and not _numbers(" ".join(cells[1:])):
                header = cells
            elif len(cells) > 1:
                for j, cell in enumerate(cells):
                    for _, _, text, value, dec, exp in _numbers(cell):
                        if not keep(value, dec, exp):
                            continue
                        ctx = defaultdict(float)
                        for t in tokens(cells[0], config) + (tokens(header[j], config) if j < len(header) else []):
                            ctx[t] = 1.0
                        if "pct" in tokens(cell + " " + (header[j] if j < len(header) else ""), config):
                            ctx["pct"] = 1.0
                        st = Stated(str(path), i + 1, text, value, dec, exp, "pct" in ctx, raws[i].strip()[:160])
                        out.append(InContext(st, dict(ctx)))
        if "\\end{tabular" in raw:
            in_tab = False

    # Prose: join paragraphs so a sentence can wrap across lines.
    para: list[int] = []
    for i in range(len(lines) + 1):
        if i < len(lines) and lines[i].strip() and i not in table_lines:
            para.append(i)
            continue
        if not para:
            continue
        joined, starts = "", []
        for k in para:
            starts.append((len(joined), k))
            joined += lines[k] + " "
        toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", joined)]
        for start, end, text, value, dec, exp in _numbers(joined):
            if not keep(value, dec, exp):
                continue
            line = max(k for pos, k in starts if pos <= start)
            idx = next((n for n, (pos, _) in enumerate(toks) if pos >= start), len(toks))
            ctx: dict[str, float] = defaultdict(float)
            sentence_start = joined.rfind(". ", 0, start) + 1
            if SETTING.match(joined[end:end + 30]):
                continue
            for n in range(0, idx):
                for t in tokens(toks[n][1], config):
                    ctx[t] = max(ctx[t], CARRY)
            for n in range(max(0, idx - BEFORE), min(len(toks), idx + AFTER + 1)):
                pos, word = toks[n]
                if pos < sentence_start or n == idx:
                    continue
                weight = 1.0 / (1 + abs(n - idx) / 4)
                for t in tokens(word, config):
                    ctx[t] = max(ctx[t], weight)
            percent = joined[end:end + 3].startswith(("\\%", "%"))
            if percent:
                ctx["pct"] = 1.0
            st = Stated(str(path), line + 1, text, value, dec, exp, percent, raws[line].strip()[:160])
            out.append(InContext(st, dict(ctx)))
        para = []
    return sorted(out, key=lambda c: c.stated.line)


@dataclass(frozen=True)
class Judgement:
    """The outcome for one number."""

    item: InContext
    status: str  # "traced", "mismatch", "unanchored-traced", "unanchored-untraced"
    best: Source | None  # the best anchor (expected value for a mismatch)
    score: float


class Matcher:
    """Index of table cells by label tokens, for anchored matching."""

    def __init__(self, sources: list[Source], config: Config):
        """
        Build the token index.

        Args:
            sources (list[Source]): Candidates from `tables.load`.
            config (Config): Project aliases and thresholds.
        """
        self.sources, self.config = sources, config
        self.labels: list[set[str]] = []
        index: dict[str, list[int]] = defaultdict(list)
        for i, s in enumerate(sources):
            words = set(tokens(f"{Path(s.file).stem} {s.column} {s.label}", config))
            words |= {w for w in s.label.lower().split()}  # whole cell values, e.g. box_padding_2
            if s.how.endswith("x 100"):
                words.add("pct")
            if s.how.startswith("difference"):
                words.add("pts")
            self.labels.append(words)
            for w in words:
                index[w].append(i)
        n = len(sources)
        self.idf = {w: math.log(n / len(ids)) for w, ids in index.items()}
        self.index = index

    def judge(self, item: InContext) -> Judgement:
        """
        Decide whether a number matches the cells its context points to.

        Args:
            item (InContext): Number with context.

        Returns:
            Judgement: The verdict, the best anchor and its score.
        """
        scores: dict[int, float] = defaultdict(float)
        for t, w in item.context.items():
            for i in self.index.get(t, ()):
                scores[i] += w * self.idf[t]
        st = item.stated
        value_ok = lambda s: is_close(st, s.value) or is_close(st, -s.value)  # noqa: E731
        if not scores:
            return Judgement(item, "unanchored-untraced", None, 0.0)
        best_i = max(scores, key=scores.get)
        best = scores[best_i]
        candidates = [s for s in self.sources if value_ok(s)]
        if st.is_integer:
            candidates = [s for s in candidates if s.value == round(s.value)]
        if not candidates:  # no table holds this value at all: it was computed elsewhere
            return Judgement(item, "unsourced", self.sources[best_i], best)
        if "pts" not in item.context:  # a plain number never traces to a derived difference
            scores = {i: v for i, v in scores.items() if not self.sources[i].how.startswith("difference")}
            if not scores:
                return Judgement(item, "unanchored-untraced", None, 0.0)
            best_i = max(scores, key=scores.get)
            best = scores[best_i]
        matching = [i for i in scores if value_ok(self.sources[i])]
        if st.is_integer:
            matching = [i for i in matching if self.sources[i].value == round(self.sources[i].value)]
        if best < self.config.min_anchor:
            any_match = matching or any(value_ok(s) for s in self.sources)
            return Judgement(item, "unanchored-traced" if any_match else "unanchored-untraced",
                             self.sources[best_i], best)  # fmt: skip
        if matching and max(scores[i] for i in matching) >= self.config.ratio * best:
            top = max(matching, key=scores.get)
            return Judgement(item, "traced", self.sources[top], scores[top])
        return Judgement(item, "mismatch", self.sources[best_i], best)
