import re
import sys
from pathlib import Path

from provenum.diff import read_values
from provenum.migrate import _plain

d = Path(sys.argv[1])
vals = read_values((d / "out/numbers.tex").read_text("utf-8"))
new = (d / "out/sections/results.tex").read_text("utf-8").split("\n")
old = (d / "project/sections/results.tex").read_text("utf-8").split("\n")
assert len(new) == len(old)
bad = 0
for a, b in zip(old, new):
    filled = re.sub(r"\\val\{([^{}]*)\}", lambda m: vals[m.group(1)], b)
    if _plain(filled) != _plain(a):
        bad += 1; print("DIFF\n ", a[:200], "\n ", filled[:200])
print("lines differing after substitution:", bad, "of", len(old))
