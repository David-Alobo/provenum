"""Score anchoring answer files against Claude's."""
import json, sys
from collections import Counter
sys.path.insert(0, "../provenum/examples")
from anchor_eval import corrupt
from provenum.anchor import judge, values
from provenum.macros import load_specs
S = sys.argv[1]
items = {i["id"]: i for i in json.load(open(f"{S}/items.json", encoding="utf-8"))}
table = values(load_specs("../provenum/examples/dockprepbench_values.toml"), "paper/tables")
load = lambda f: {a["id"]: a["path"] for a in json.load(open(f"{S}/{f}", encoding="utf-8"))}
cl = load("answers_claude_sonnet.json")
for f in sys.argv[2:]:
    a = load(f); real = {i: judge(items[i]["number"], a.get(i), table) for i in items}; c = Counter(real.values())
    traced = [i for i in items if real[i] == "traced"]
    caught = sum(judge(corrupt(items[i]["number"]), a[i], table) == "mismatch" for i in traced)
    both = [i for i in items if cl.get(i) and a.get(i)]
    print(f"{f:34} traced {c['traced']:3} mismatch {c['mismatch']:3} bad {c['bad-path']:3} none {c['unanchored']:3} | caught {caught}/{len(traced)} | same as Claude {sum(cl[i]==a[i] for i in both)}/{len(both)}")
