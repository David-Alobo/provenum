"""What the model did with the numbers that a single cell matched and the paper left typed.

Reads trial_hand (no model), its classification, and trial_model (qwen3:32b), and prints, for each
classified single match, the reading and the model's review list and choice.

Usage: python scripts/single_matches.py > trial_hand/model_on_single_matches.txt
"""

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
hand = json.loads((HERE / "trial_hand/items.json").read_text(encoding="utf-8"))
model = {i["key"]: i for i in
         json.loads((HERE / "trial_model/items.json").read_text(encoding="utf-8"))}  # fmt: skip
with open(HERE / "trial_hand/disagreements_classified.csv", encoding="utf-8") as f:
    reading = {r["app_cell"]: r["reading"] for r in csv.DictReader(f)}
for it in hand:
    fit = [c["path"] for c in it["candidates"] if c["fits"]]
    if it["category"] == "check" and len(fit) == 1 and fit[0] in reading:
        m = model[it["key"]]
        print(f"{it['written']}\t{fit[0]}\t{reading[fit[0]]}\tmodel: {m['category']}, "
              f"pick {m['pick']}")  # fmt: skip
