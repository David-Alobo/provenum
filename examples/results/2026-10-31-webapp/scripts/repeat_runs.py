"""Run the web app's anchoring step N times with identical inputs and compare the model's picks.

Usage: repeat_runs.py EXAMPLES TABLES OUT MODEL HOST N
"""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

from provenum.llm import choose
from provenum.macros import load_specs
from provenum.web.session import Session

ex, tables, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
model, host, n = sys.argv[4], sys.argv[5], int(sys.argv[6])
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
spec_path = tables.parent / "numbers.toml"
with zipfile.ZipFile(tbuf, "w") as z:
    for s in load_specs(spec_path):
        z.write(tables / s.file, s.file)
s = Session.create(buf.getvalue(), out)
s.set_tables(data=tbuf.getvalue())
s.set_spec(spec_path.read_text("utf-8"))
notes = (ex / "dockprepbench_notes.txt").read_text("utf-8")
out.joinpath("runs").mkdir(exist_ok=True)
for r in range(1, n + 1):
    t = time.time()
    s.anchor(lambda it, c: choose(it, c, notes, model, host))
    picks = {it["key"]: {"pick": it["pick"], "category": it["category"]} for it in s.items}
    (out / "runs" / f"run{r}.json").write_text(json.dumps(picks, indent=1), "utf-8")
    print(f"run {r}: {time.time() - t:.0f} s, linked {sum(1 for it in s.items if it['selected'])}",
          flush=True)
