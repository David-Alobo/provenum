"""Trial the web workflow on the original DockPrepBench results section.

Usage: web_trial.py EXAMPLES TABLES OUT guess|hand [MODEL HOST]
"""
import io
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

from provenum.llm import choose
from provenum.macros import load_specs
from provenum.web.session import Session

ex, tables, out, spec_mode = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
model, host = (sys.argv[5], sys.argv[6]) if len(sys.argv) > 6 else (None, None)
main = r"""\documentclass{article}
\begin{document}
\input{sections/results}
\end{document}
"""
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("main.tex", main)
    z.writestr("sections/results.tex",
               (ex / "results/2026-10-30-anchoring/results_original.tex").read_text("utf-8"))
tbuf = io.BytesIO()
with zipfile.ZipFile(tbuf, "w") as z:
    for s in load_specs(tables.parent / "numbers.toml"):
        z.write(tables / s.file, s.file)
s = Session.create(buf.getvalue(), out)
s.set_tables(data=tbuf.getvalue())
print("guessed spec:", s.n_tables, "tables", s.n_values, "values")
if spec_mode == "hand":
    s.set_spec((tables.parent / "numbers.toml").read_text("utf-8"))
    print("hand spec:", s.n_tables, "tables", s.n_values, "values")
notes = (ex / "dockprepbench_notes.txt").read_text("utf-8")
ask = (lambda it, c: choose(it, c, notes, model, host)) if model else None
t = time.time()
s.anchor(ask, lambda d, n: print(f"  {d}/{n}", flush=True) if d % 50 == 0 else None)
print(f"anchor {time.time() - t:.0f}s; items {len(s.items)}",
      dict(Counter(it["category"] for it in s.items)))
kinds = Counter(it["reason"].split(" ")[0] if it["reason"][0].isdigit() is False
                else " ".join(it["reason"].split(" ")[1:5]) for it in s.items
                if it["category"] == "untraced")
print("untraced reasons:", dict(kinds.most_common(5)))
(out / "items.json").write_text(json.dumps(s.items, indent=1, ensure_ascii=False), "utf-8")
if model:
    dec = {it["key"]: it["selected"] for it in s.items}
else:  # the "accept every number with one matching cell" button
    dec = {it["key"]: next(x["path"] for x in it["candidates"] if x["fits"])
           for it in s.items
           if it["category"] == "check" and sum(x["fits"] for x in it["candidates"]) == 1}
a = s.apply(dec)
print("apply:", {k: v for k, v in a.items() if "per_file" not in k})
