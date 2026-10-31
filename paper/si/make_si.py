"""Write the generated parts of the supplementary information from the saved results.

Every table and listing in si.tex that holds a number or a prompt comes from this script, which
reads only files in examples/results/ and provenum's own source. Outputs go to si/generated/.

Usage (from the repository root): uv run python paper/si/make_si.py
"""

import ast
import csv
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "examples" / "results"
OUT = Path(__file__).resolve().parent / "generated"
sys.path.insert(0, str(ROOT / "src"))

from provenum import llm

MODELS = {
    "qwen2.5:7b-instruct": "Qwen2.5-7B",
    "qwen2.5:14b-instruct": "Qwen2.5-14B",
    "qwen2.5:32b-instruct": "Qwen2.5-32B",
    "qwen3:8b": "Qwen3-8B",
    "qwen3:14b": "Qwen3-14B",
    "qwen3:32b": "Qwen3-32B",
    "llama3.1:8b-instruct-q4_K_M": "Llama3.1-8B",
    "llama3.3:70b-instruct-q4_K_M": "Llama3.3-70B",
}
LISTS = {"check": "to confirm", "traced": "linked", "untraced": "left typed"}
UNICODE = {"−": "$-$", "×": r"$\times$", "≥": r"$\geq$", "≤": r"$\leq$", "–": "--",
           "…": r"\ldots{}", "Å": r"\AA{}", "±": r"$\pm$"}  # fmt: skip


def tex(text: str) -> str:
    """
    Escape plain text for LaTeX, including the Unicode signs the sentences use.

    Args:
        text (str): Plain text.

    Returns:
        str: LaTeX source that prints the text.
    """
    out = []
    for ch in text:
        if ch in "&%$#_{}":
            out.append("\\" + ch)
        elif ch == "\\":
            out.append(r"\textbackslash{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        else:
            out.append(UNICODE.get(ch, ch))
    return "".join(out)


def path(p: str) -> str:
    """
    Typeset a table path so that it can break at slashes and underscores.

    Args:
        p (str): A \\val{} path or another identifier.

    Returns:
        str: LaTeX source.
    """
    return r"\nolinkurl{" + p.replace("%", r"\%").replace("#", r"\#") + "}"


def write(name: str, body: str) -> None:
    """
    Write one generated file.

    Args:
        name (str): File name inside si/generated/.
        body (str): Its content.

    Returns:
        None
    """
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(body, encoding="utf-8")
    print("wrote", name)


def _capture(fn, *args) -> tuple[str, str]:
    """
    Run one of provenum's prompt builders and capture the messages instead of sending them.

    Args:
        fn: `llm.ask` or `llm.choose`.
        *args: Its arguments before `model` and `host`.

    Returns:
        tuple[str, str]: The system prompt and the user message.
    """
    seen = {}

    def fake(system, user, schema, model, host, timeout):
        """
        Stand-in for `llm._chat` that records the messages.

        Args:
            system (str): System prompt.
            user (str): User message.
            schema (dict): Reply schema.
            model (str): Model name.
            host (str): Server URL.
            timeout (float): Seconds.

        Returns:
            str: An empty answer.
        """
        seen.update(system=system, user=user)
        return '{"path": null}'

    real, llm._chat = llm._chat, fake
    try:
        fn(*args, "model", "host")
    finally:
        llm._chat = real
    return seen["system"], seen["user"]


def prompts() -> None:
    """Write the local models' prompts, with one example item in each mode."""
    notes = (ROOT / "examples" / "dockprepbench_notes.txt").read_text(encoding="utf-8").strip()
    first = RES / "2026-10-30-anchoring"
    items = json.loads((first / "items.json").read_text(encoding="utf-8"))
    cat = (first / "catalogue.txt").read_text(encoding="utf-8").strip()
    system, user = _capture(llm.ask, items[0], cat, notes)
    write("prompt_blind_system.txt", system + "\n")
    write("prompt_blind_user.txt", user + "\n")
    mig = json.loads((RES / "2026-10-30-migration" / "items_with_candidates.json")
                     .read_text(encoding="utf-8"))  # fmt: skip
    item = next(i for i in mig if i["id"] == 3)
    system, user = _capture(llm.choose, item, item["candidates"], notes)
    write("prompt_shortlist_system.txt", system + "\n")
    write("prompt_shortlist_user.txt", user + "\n")
    for name, src in (("prompt_claude_blind.txt", first / "prompt_claude_sonnet.txt"),
                      ("prompt_claude_shortlist.txt",
                       RES / "2026-10-30-migration" / "prompt_claude_sonnet_shortlist.txt")):  # fmt: skip
        body = [ln for ln in src.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        text = "\n".join(body).strip()
        text = re.sub(r"C:\\Users\\[^ ]*?\\scratchpad\\", "SCRATCH/", text)
        write(name, text + "\n")


def spec() -> None:
    """Write the table of the 28 tables in DockPrepBench's specification."""
    hand = tomllib.loads((RES / "2026-10-31-webapp" / "trial_model" / "numbers.toml")
                         .read_text(encoding="utf-8"))["table"]  # fmt: skip
    first = {t["file"] for t in tomllib.loads((ROOT / "examples" / "dockprepbench_values.toml")
                                              .read_text(encoding="utf-8"))["table"]}  # fmt: skip
    rows = []
    for t in hand:
        mark = "$^a$" if t["file"] in first else ""
        rows.append(f"{path(t['file'].removesuffix('.csv'))}{mark} & "
                    f"{tex(', '.join(t['keys']))} & {tex(t.get('default', 'sig3'))} & "
                    f"{len(t.get('formats', {}))} \\\\")  # fmt: skip
    write("spec_tables.tex", "\n".join(rows) + "\n")


def corruption() -> None:
    """Write the corruption-test table from the saved outputs."""
    text = (RES / "2026-10-30-corruption" / "corruption_output.txt").read_text(encoding="utf-8")
    after_all = text.split("all decimals\n", 1)[1]
    segments = dict(zip(("all decimals", "prose decimals"),
                        after_all.split("prose decimals\n", 1), strict=True))  # fmt: skip
    blocks = {part: {m.group(1): (int(m.group(2)), int(m.group(3)))
                     for m in re.finditer(r"  (.+?): (\d+)/(\d+)", seg)}
              for part, seg in segments.items()}  # fmt: skip
    score = (RES / "2026-10-30-anchoring" / "score_output.txt").read_text(encoding="utf-8")
    claude = re.search(r"answers_claude_sonnet.json\s+traced\s+(\d+).*caught (\d+)/(\d+)", score)
    traced, caught = int(claude.group(1)), int(claude.group(2))

    def pct(k: int, n: int) -> str:
        """
        Format a count with its share.

        Args:
            k (int): Count.
            n (int): Denominator.

        Returns:
            str: "k of n (p%)".
        """
        return f"{k} of {n} ({100 * k / n:.1f}\\%)"

    rows = []
    for part, label in (("all decimals", "All decimals (prose and tables)"),
                        ("prose decimals", "Prose decimals")):  # fmt: skip
        b = blocks[part]
        n = b["value only, corruptions caught"][1]
        rows.append(rf"\multicolumn{{4}}{{l}}{{\emph{{{label}, $n = {n}$}}}} \\")
        rows.append(f"\\quad Value only & {pct(*b['value only, corruptions caught'])} & -- & "
                    f"{b['value only, correct numbers flagged'][0]} \\\\")  # fmt: skip
        anch = b["context, corruptions caught where the original is anchored and traced"]
        rows.append(f"\\quad Context (audit) & {pct(*b['context, corruptions caught'])} & "
                    f"{pct(*anch)} & {b['context, correct numbers flagged (mismatch)'][0]} \\\\")  # fmt: skip
        if part == "prose decimals":
            rows.append(f"\\quad Claude Sonnet proposes, code verifies & {pct(caught, n)} & "
                        f"{pct(caught, traced)} & 0 \\\\")  # fmt: skip
    write("corruption.tex", "\n".join(rows) + "\n")


def anchoring() -> None:
    """Write the first anchoring experiment's per-model scores."""
    names = {"answers_claude_sonnet.json": ("Claude Sonnet", "blind"),
             "answers_qwen14b.json": ("Qwen2.5-14B", "blind"),
             "answers_qwen32b_blind.json": ("Qwen2.5-32B", "blind"),
             "answers_qwen14b_shortlist.json": ("Qwen2.5-14B", "shortlist"),
             "answers_qwen32b_shortlist.json": ("Qwen2.5-32B", "shortlist")}  # fmt: skip
    rows = []
    pat = re.compile(r"(\S+)\s+traced\s+(\d+) mismatch\s+(\d+) bad\s+(\d+) none\s+(\d+) \| "
                     r"caught (\d+)/(\d+) \| same as Claude (\d+)/(\d+)")  # fmt: skip
    text = (RES / "2026-10-30-anchoring" / "score_output.txt").read_text(encoding="utf-8")
    for m in pat.finditer(text):
        model, mode = names[m.group(1)]
        same = "--" if model == "Claude Sonnet" else f"{m.group(8)} of {m.group(9)}"
        rows.append(f"{model} & {mode} & {m.group(2)} & {m.group(3)} & {m.group(4)} & "
                    f"{m.group(5)} & {same} \\\\")  # fmt: skip
    write("anchoring.tex", "\n".join(rows) + "\n")


def benchmark() -> None:
    """Write the full benchmark table, both modes, every recorded column."""
    with open(RES / "2026-10-30-benchmark" / "bench_results.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for mode in ("blind", "shortlist"):
        out.append(rf"\multicolumn{{9}}{{l}}{{\emph{{{mode.capitalize()} mode}}}} \\")
        for r in (r for r in rows if r["mode"] == mode):
            right, wrong = int(r["right"]), int(r["wrong"])
            abstain = int(r["abstain"] or 0)
            passed = wrong - int(r["caught_wrong"])
            chosen = right + wrong
            out.append(f"\\quad {MODELS[r['model']]} & {right} & {wrong} & "
                       f"{passed if mode == 'blind' else '--'} & {abstain} & "
                       f"{100 * right / int(r['values']):.1f} & {100 * right / chosen:.1f} & "
                       f"{r['false_anchor']} & {float(r['seconds_per_item']):.2f} \\\\")  # fmt: skip
    write("benchmark.tex", "\n".join(out) + "\n")


def review() -> None:
    """Write the review-trial tables: lists, disagreements, single matches, spec effect."""
    web = RES / "2026-10-31-webapp"
    summary = json.loads((web / "summary.json").read_text(encoding="utf-8"))
    rows = []
    for key, spec_name, chooser in (("trial_hand", "hand", "no model"),
                                    ("trial_guess", "guessed", "no model"),
                                    ("trial_model", "hand", "Qwen3-32B"),
                                    ("trial_model_guess", "guessed", "Qwen3-32B")):  # fmt: skip
        s = summary[key]
        lists = s["lists"]
        rows.append(f"{spec_name} & {chooser} & {s['with_matching_cell']} & "
                    f"{s['single_matching_cell']} & {lists.get('check', 0)} & "
                    f"{lists.get('traced', 0)} & {lists.get('untraced', 0)} & {s['linked']} \\\\")  # fmt: skip
    write("review_lists.tex", "\n".join(rows) + "\n")

    rep = summary["repeat_hand"]
    picks = sorted({r["picks"] for r in rep["runs"].values()})
    write("review_repeats.tex",
          f"{len(rep['runs'])} repeats; cells chosen per run: {', '.join(map(str, picks))}; "
          f"numbers whose choice changed in any run: {rep['numbers_with_any_change']}.\n")  # fmt: skip

    with open(web / "trial_model" / "disagreements_classified.csv", encoding="utf-8") as f:
        dis = list(csv.DictReader(f))
    out = [f"{r['n']} & {LISTS[r['list']]} & {tex(r['value'])} & {path(r['app_cell'])} & "
           f"{path(r['paper_cell']) if r['paper_cell'].startswith('(') is False else tex(r['paper_cell'])} & "
           f"{tex(r['reading'])} \\\\"
           for r in dis]  # fmt: skip
    write("disagreements.tex", "\n".join(out) + "\n")

    with open(web / "trial_hand" / "disagreements_classified.csv", encoding="utf-8") as f:
        single = list(csv.DictReader(f))
    model = {}
    for line in (web / "trial_hand" / "model_on_single_matches.txt").read_text(
            encoding="utf-8").splitlines():  # fmt: skip
        value, cell, _, rest = line.split("\t")
        m = re.match(r"model: (\w+), pick (.+)", rest)
        model.setdefault((value, cell), []).append((m.group(1), m.group(2)))
    out = []
    for r in single:
        lst, pick = model[(r["value"], r["app_cell"])].pop(0)
        if lst == "traced":
            did = "linked the same cell"
        elif pick == "None":
            did = "chose none; left typed"
        else:
            did = "chose another cell, which prints differently; left typed"
        out.append(f"{r['n']} & {tex(r['value'])} & {path(r['app_cell'])} & {tex(r['reading'])} & "
                   f"{did} \\\\")  # fmt: skip
    write("single_matches.tex", "\n".join(out) + "\n")

    text = (web / "spec_effect.txt").read_text(encoding="utf-8")
    lost = re.search(r"linked with hand, not with guess: (\d+) (\{.*\})", text)
    gained = re.search(r"linked with guess, not with hand: (\d+) (\{.*\})", text)

    reasons = ast.literal_eval(lost.group(2))
    out = [f"\\quad {tex(k)} & {v} \\\\" for k, v in reasons.items()]
    out.insert(0, rf"Linked with the hand specification only & {lost.group(1)} \\")
    g = ast.literal_eval(gained.group(2))
    out.append(rf"Linked with the guessed specification only & {gained.group(1)} \\")
    out += [f"\\quad {tex(k)} (with the hand specification) & {v} \\\\" for k, v in g.items()]
    write("spec_effect.tex", "\n".join(out) + "\n")


def main() -> None:
    """Write every generated file."""
    prompts()
    spec()
    corruption()
    anchoring()
    benchmark()
    review()


if __name__ == "__main__":
    main()
