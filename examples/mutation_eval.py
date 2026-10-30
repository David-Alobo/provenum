"""Mutation test for provenum: false alarms on the real text, catch rate on corrupted numbers."""
import sys, time
from collections import Counter
from dataclasses import replace
from provenum.context import Config, InContext, Matcher, extract
from provenum.tables import load

tex, tables, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = Config.load(cfg_path)
t0 = time.time()
m = Matcher(load([tables], derived=False, exclude=cfg.exclude), cfg)
items = extract(tex, cfg)
real = [m.judge(i) for i in items]
print(f"{len(m.sources)} candidate values; {len(items)} numbers; {time.time()-t0:.0f}s")
print("real text:", dict(Counter(j.status for j in real)))

def mutate(i, k=3):
    s = i.stated
    step = 10.0 ** (s.exponent - s.decimals)
    v = s.value + k * step * (1 if s.value >= 0 else -1)
    return InContext(replace(s, value=v, text=f"{v:.{max(s.decimals,0)}f}"), i.context)

dec = [i for i in items if not i.stated.is_integer]
mut = [m.judge(mutate(i)) for i in dec]
orig = {id(i): j for i, j in zip(items, real)}
# Only numbers whose original traces (anchored) can show detection; report both views.
anch = [(i, j0, j1) for i, j0, j1 in zip(dec, [orig[id(i)] for i in dec], mut)]
traced_orig = [x for x in anch if x[1].status == "traced"]
caught = sum(x[2].status in ('mismatch','unsourced') for x in traced_orig)
print(f"decimals: {len(dec)}; originals traced (anchored): {len(traced_orig)}; "
      f"corruptions caught among those: {caught} ({100*caught/max(1,len(traced_orig)):.0f}%)")
print(f"overall catch rate on all decimals: {100*sum(j.status in ('mismatch','unsourced','unanchored-untraced') for j in mut)/len(dec):.0f}%")
fa = [j for j in real if j.status == "mismatch"]
print(f"false alarms (real numbers flagged mismatch): {len(fa)}")
for j in fa[:12]:
    print(f"  {j.item.stated.line:4} {j.item.stated.text:>8} expected {j.best.value:.4g} [{j.best.column}] {j.best.label[:40]} | {j.item.stated.context[:70]}")
