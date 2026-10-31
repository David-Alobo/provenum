"""One researcher's pass through the workflow: upload, tables, spec, run, review, apply.

A session lives in its own directory: the uploaded LaTeX project (`project/`, never modified),
the result tables (`tables/`, or a folder inside the project), the spec (`numbers.toml`) and,
after applying, the migrated copy (`out/`) with its zip and report. The model only proposes
which cell a number reports; a number is replaced only if the researcher accepts a cell whose
value, formatted by the spec, reproduces exactly what is written.
"""

import html
import io
import json
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from provenum.anchor import items, judge, values
from provenum.macros import VAL, generate, lint, load_specs
from provenum.migrate import find_span, migrate
from provenum.scaffold import scaffold

MAX_UNPACKED = 200 * 2**20  # bytes; a LaTeX project with figures is rarely above 50 MB
NUMBERS = "numbers.tex"


class SessionError(ValueError):
    """A problem the researcher can fix (bad zip, no tables, invalid spec)."""


def unpack(data: bytes, dest: Path) -> list[str]:
    """
    Extract a zip into a directory, refusing paths that would land outside it.

    Args:
        data (bytes): Zip file contents.
        dest (Path): Empty directory to extract into.

    Returns:
        list[str]: Extracted file paths, relative and POSIX-style.

    Raises:
        SessionError: If the data is not a zip, a path is unsafe or the contents are too large.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as err:
        raise SessionError("this file is not a zip archive") from err
    names, total = [], 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = PurePosixPath(info.filename.replace("\\", "/"))
        if name.is_absolute() or ".." in name.parts:
            raise SessionError(f"unsafe path in zip: {info.filename}")
        if name.parts[0] in ("__MACOSX",) or name.name == ".DS_Store":
            continue
        total += info.file_size
        if total > MAX_UNPACKED:
            raise SessionError("the zip unpacks to more than 200 MB")
        target = dest / Path(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(info))
        names.append(name.as_posix())
    return sorted(names)


def _strip_single_root(root: Path) -> None:
    """
    Move the contents of a lone top-level folder up, as when a project is zipped as a folder.

    Args:
        root (Path): Directory just extracted into.
    """
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for child in list(inner.iterdir()):
            shutil.move(str(child), str(root / child.name))
        inner.rmdir()


def _display(latex: str) -> str:
    """
    Plain text for a formatted value, for the review screen.

    Args:
        latex (str): Output of `macros.fmt`, e.g. "\\ensuremath{-}1.9" or "$4.1 \\times 10^{-4}$".

    Returns:
        str: e.g. "−1.9" or "4.1 × 10^-4".
    """
    text = latex.replace("\\ensuremath{-}", "−").replace("$-$", "−").replace("\\ensuremath", "")
    text = text.replace("$", "").replace("\\times", "×").replace("^{", "^")
    return " ".join(text.replace("}", "").replace("{", "").replace("-", "−").split())


def _readable(sentence: str) -> str:
    """
    A sentence as a reader sees it, for the review screen (the [[...]] mark is kept).

    Args:
        sentence (str): Sentence from `anchor.items`, with LaTeX.

    Returns:
        str: e.g. "within 2 Å of ... for [[46.3]]% of complexes" instead of "2~\\AA{} ... \\%".
    """
    text = sentence.replace("\\%", "%").replace("~", " ").replace("\\AA", "Å")
    text = re.sub(r"\\(?:emph|textit|textbf|mathrm|text)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\([A-Za-z]+)\{\}", r"\1", text)  # argument-less macros such as \pbvalid{}
    text = text.replace("{}", "").replace("$", "").replace("\\,", " ").replace("--", "–")
    return " ".join(text.split())


def categorise(written: str, candidates: list[dict], pick: str | None,
               used_model: bool) -> tuple[str, str]:  # fmt: skip
    """
    Which review list a number belongs in, and why.

    Args:
        written (str): The number as written.
        candidates (list[dict]): Cells whose value matches ({path, text, fits}).
        pick (str | None): The model's choice among the candidates, if a model was asked.
        used_model (bool): Whether a model was asked.

    Returns:
        tuple[str, str]: ("traced" | "check" | "untraced", reason shown to the researcher).
    """
    fitting = [c["path"] for c in candidates if c["fits"]]
    if not candidates:
        return "untraced", f"no table value matches {written}"
    if not fitting:
        shown = ", ".join(sorted({c["text"] for c in candidates}))
        return "untraced", (f"{len(candidates)} cell(s) hold this value but format it as "
                            f"{shown}; change the format in the spec to link it")  # fmt: skip
    if not used_model:
        return "check", f"{len(fitting)} cell(s) match the value; choose the one the text means"
    if pick is None:
        return "untraced", (f"{len(fitting)} cell(s) hold this value, but the model judged that "
                            "none is what the sentence reports")  # fmt: skip
    if len(fitting) == 1:
        return "traced", "the only cell with this value, and the model's choice"
    return "check", (f"{len(fitting)} cells hold this value; the model chose one. Same-value "
                     "cells are the case the value check cannot catch, so confirm it")  # fmt: skip


@dataclass
class Session:
    """State of one pass through the workflow."""

    root: Path
    tex_files: list[str] = field(default_factory=list)
    main: str | None = None
    table_dirs: list[str] = field(default_factory=list)
    tables: str | None = None  # "upload" or a folder inside the project
    spec_text: str = ""
    n_tables: int = 0
    n_values: int = 0
    run: dict = field(default_factory=lambda: {"status": "idle", "done": 0, "total": 0})
    items: list[dict] = field(default_factory=list)
    applied: dict | None = None

    @property
    def project(self) -> Path:
        """Path: The uploaded project (read-only)."""
        return self.root / "project"

    @property
    def tables_root(self) -> Path:
        """Path: The directory the spec's file names are relative to."""
        if self.tables == "upload":
            return self.root / "tables"
        return self.project / (self.tables or "")

    @classmethod
    def create(cls, data: bytes, root: Path) -> "Session":
        """
        Start a session from a zipped LaTeX project (e.g. Overleaf's Download → Source).

        Args:
            data (bytes): Zip contents.
            root (Path): New, empty session directory.

        Returns:
            Session: The session, with its .tex files, main file and table folders found.

        Raises:
            SessionError: If the zip is unusable or holds no .tex file.
        """
        s = cls(root)
        s.project.mkdir(parents=True)
        unpack(data, s.project)
        _strip_single_root(s.project)
        files = sorted(p.relative_to(s.project).as_posix() for p in s.project.rglob("*.tex"))
        s.tex_files = [f for f in files if PurePosixPath(f).name != NUMBERS]
        if not s.tex_files:
            raise SessionError("no .tex file in this zip")
        mains = [
            f
            for f in s.tex_files
            if "\\documentclass" in (s.project / f).read_text("utf-8", errors="replace")
        ]
        s.main = next((m for m in mains if PurePosixPath(m).name == "main.tex"),
                      mains[0] if mains else s.tex_files[0])  # fmt: skip
        dirs = Counter(p.parent.relative_to(s.project).as_posix()
                       for p in s.project.rglob("*.csv"))  # fmt: skip
        s.table_dirs = sorted(dirs)
        return s

    def set_tables(self, data: bytes | None = None, folder: str | None = None) -> None:
        """
        Use uploaded tables (a zip of CSVs) or a folder of the project, and guess a spec.

        Args:
            data (bytes | None): Zip of CSV files.
            folder (str | None): Folder inside the project holding CSV files.

        Raises:
            SessionError: If no CSV file is found.
        """
        if data is not None:
            shutil.rmtree(self.root / "tables", ignore_errors=True)
            (self.root / "tables").mkdir()
            unpack(data, self.root / "tables")
            _strip_single_root(self.root / "tables")
            self.tables = "upload"
        else:
            if folder not in self.table_dirs:
                raise SessionError(f"no CSV tables in project folder {folder!r}")
            self.tables = folder
        text, n = scaffold(self.tables_root)
        where = "the uploaded tables" if self.tables == "upload" else f"project folder {folder}"
        text = text.replace(self.tables_root.as_posix(), where, 1)  # not the session's temp path
        if not n:
            raise SessionError("no CSV tables found")
        self.set_spec(text)
        self.items, self.applied = [], None

    def set_spec(self, text: str) -> None:
        """
        Save and check a spec: it must parse and every table it names must load.

        Args:
            text (str): TOML spec.

        Raises:
            SessionError: If the spec does not parse or a table cannot be read.
        """
        path = self.root / "numbers.toml"
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            specs = load_specs(path)
            _, n = generate(specs, self.tables_root)
        except Exception as err:  # tomllib, csv and key errors all mean the spec needs fixing
            raise SessionError(f"spec problem: {type(err).__name__}: {err}") from err
        self.spec_text, self.n_tables, self.n_values = text, len(specs), n

    def anchor(self, ask: Callable[[dict, list[str]], str | None] | None,
               progress: Callable[[int, int], None] | None = None) -> None:  # fmt: skip
        """
        Find every hand-typed number, its value-matching cells and, if asked, the model's choice.

        Args:
            ask (Callable[[dict, list[str]], str | None] | None): Given an item and its
                candidate paths, returns the model's choice (or None). None means no model:
                every number with a matching cell goes to the researcher.
            progress (Callable[[int, int], None] | None): Called with (done, total).
        """
        specs = load_specs(self.root / "numbers.toml")
        table = values(specs, self.tables_root)
        found = [(f, it) for f in self.tex_files for it in items(self.project / f)]
        out = []
        for n, (f, it) in enumerate(found, 1):
            line = (self.project / f).read_text(encoding="utf-8").split("\n")[it["line"] - 1]
            paths = [p for p in table if judge(it["number"], p, table) == "traced"]
            candidates = [{"path": p, "text": _display(table[p][1]),
                           "fits": find_span(line, it["written"], table[p][1]) is not None}
                          for p in paths]  # fmt: skip
            pick = ask(it, paths) if ask and paths else None
            category, reason = categorise(it["written"], candidates, pick, ask is not None)
            out.append({"key": f"{f}#{it['id']}", "file": f, "id": it["id"], "line": it["line"],
                        "written": it["written"], "sentence": _readable(it["sentence"]),
                        "candidates": candidates, "pick": pick, "category": category,
                        "reason": reason,
                        "selected": pick if category in ("traced", "check") else None})  # fmt: skip
            if progress:
                progress(n, len(found))
        self.items, self.applied = out, None

    def apply(self, decisions: dict[str, str | None]) -> dict:
        """
        Write the migrated project: accepted numbers become \\val{}, plus numbers.tex.

        Args:
            decisions (dict[str, str | None]): Item key -> accepted path, or None to leave the
                number as written. Items not listed keep no path.

        Returns:
            dict: Summary (replaced, left, per file) also written into the report.

        Raises:
            SessionError: If a decision names a cell that is not one of the item's fitting
                candidates.
        """
        by_key = {it["key"]: it for it in self.items}
        for key, path in decisions.items():
            it = by_key.get(key)
            if it is None:
                raise SessionError(f"unknown number {key}")
            if path is not None and path not in [c["path"] for c in it["candidates"] if c["fits"]]:
                raise SessionError(f"{path} is not a matching cell for {key}")
        out = self.root / "out"
        shutil.rmtree(out, ignore_errors=True)
        shutil.copytree(self.project, out)
        specs = load_specs(self.root / "numbers.toml")
        table = values(specs, self.tables_root)
        replaced: Counter = Counter()
        for f in self.tex_files:
            answers = [{"id": it["id"], "path": decisions.get(it["key"])}
                       for it in self.items if it["file"] == f]  # fmt: skip
            if any(a["path"] for a in answers):
                report = migrate(out / f, answers, table)
                (out / (f + ".bak")).unlink(missing_ok=True)
                replaced[f] = sum(r["status"] == "replaced" for r in report)
        main_dir = PurePosixPath(self.main).parent
        numbers_name = (
            NUMBERS if not (out / main_dir / NUMBERS).exists() else "provenum_numbers.tex"
        )
        text, _ = generate(specs, self.tables_root)
        (out / main_dir / numbers_name).write_text(text, encoding="utf-8", newline="\n")
        inserted = _add_input(out / self.main, numbers_name.removesuffix(".tex"))
        (out / "numbers.toml").write_text(self.spec_text, encoding="utf-8", newline="\n")
        left = {f: len(lint(out / f)) for f in self.tex_files}
        cited = sum(len(VAL.findall((out / f).read_text(encoding="utf-8")))
                    for f in self.tex_files)  # fmt: skip
        self.applied = {"replaced": sum(replaced.values()), "per_file": dict(replaced),
                        "left": sum(left.values()), "left_per_file": left, "cited": cited,
                        "numbers_file": (main_dir / numbers_name).as_posix(),
                        "input_added": inserted}  # fmt: skip
        self._zip(out)
        (self.root / "report.html").write_text(self.report(decisions), encoding="utf-8")
        return self.applied

    def _zip(self, out: Path) -> None:
        """
        Zip the migrated project for re-upload to Overleaf.

        Args:
            out (Path): The migrated project directory.
        """
        with zipfile.ZipFile(self.root / "project.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(out).as_posix())

    def report(self, decisions: dict[str, str | None]) -> str:
        """
        A standalone HTML report: what was linked, what was left as typed and why.

        Args:
            decisions (dict[str, str | None]): As passed to `apply`.

        Returns:
            str: HTML document.
        """
        a = self.applied or {}
        esc = html.escape
        linked = [it for it in self.items if decisions.get(it["key"])]
        left = [it for it in self.items if not decisions.get(it["key"])]

        def row(it: dict, cell: str) -> str:
            sentence = esc(it["sentence"]).replace("[[", "<mark>").replace("]]", "</mark>")
            return (f"<tr><td>{esc(it['file'])}:{it['line']}</td><td>{sentence}</td>"
                    f"<td>{cell}</td></tr>")  # fmt: skip

        rows_linked = "".join(row(it, f"<code>{esc(decisions[it['key']])}</code>") for it in linked)
        rows_left = "".join(row(it, esc(it["reason"])) for it in left)
        total = len(self.items)
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>provenum report</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 16px;
color:#1d2433;background:#fff}} table{{border-collapse:collapse;width:100%}}
td,th{{border-top:1px solid #dde1e8;padding:.4rem;vertical-align:top;text-align:left}}
mark{{background:#ffe9a8}} code{{font-size:13px;word-break:break-all}}
</style></head><body>
<h1>provenum report</h1>
<p><strong>{len(linked)} of {total}</strong> hand-typed numbers are now linked to the result
tables with <code>\\val{{}}</code>; {len(left)} are left as typed. Values come from
{self.n_tables} tables ({self.n_values} values) through <code>numbers.toml</code>, written to
<code>{esc(a.get("numbers_file", NUMBERS))}</code>. A linked number was replaced only where its
cell, formatted by the spec, gives exactly the text that was written, so the PDF reads the same.</p>
<h2>Linked ({len(linked)})</h2>
<table><tr><th>Where</th><th>Sentence</th><th>Cell</th></tr>{rows_linked}</table>
<h2>Left as typed ({len(left)})</h2>
<table><tr><th>Where</th><th>Sentence</th><th>Why</th></tr>{rows_left}</table>
</body></html>"""

    def state(self) -> dict:
        """
        Everything the page needs to show the session.

        Returns:
            dict: JSON-serialisable state.
        """
        return {"tex_files": self.tex_files, "main": self.main, "table_dirs": self.table_dirs,
                "tables": self.tables, "spec": self.spec_text, "n_tables": self.n_tables,
                "n_values": self.n_values, "checks": self.spec_text.count("# CHECK"),
                "run": self.run, "items": self.items, "applied": self.applied}  # fmt: skip


def _add_input(main: Path, name: str) -> bool:
    """
    Add \\input{name} before \\begin{document}, unless the file already inputs it.

    Args:
        main (Path): Main .tex file.
        name (str): File to input, without .tex.

    Returns:
        bool: Whether a line was added.
    """
    text = main.read_text(encoding="utf-8")
    if f"\\input{{{name}}}" in text or "\\begin{document}" not in text:
        return False
    line = f"\\input{{{name}}} % values generated by provenum from the result tables\n"
    main.write_text(text.replace("\\begin{document}", line + "\\begin{document}", 1),
                    encoding="utf-8", newline="")  # fmt: skip
    return True


def new_root(base: Path | None = None) -> Path:
    """
    A fresh directory for a session.

    Args:
        base (Path | None): Parent directory (default: the system temp directory).

    Returns:
        Path: The new directory.
    """
    return Path(tempfile.mkdtemp(prefix="provenum-", dir=base))


def to_json(obj: dict) -> bytes:
    """
    Encode a response body.

    Args:
        obj (dict): Data.

    Returns:
        bytes: UTF-8 JSON.
    """
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")
