"""Why the guessed spec links fewer numbers: compare trial_model and trial_model_guess per number.

Usage: python scripts/spec_effect.py > spec_effect.txt   (from examples/results/2026-10-31-webapp)
"""

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def reason(it: dict) -> str:
    """
    A short label for why a number is in its review list.

    Args:
        it (dict): One item from items.json.

    Returns:
        str: The list name, or the reason a number was left as typed.
    """
    r = it["reason"]
    if it["category"] != "untraced":
        return it["category"]
    if r.startswith("no table"):
        return "no matching value"
    if "format it as" in r:
        return "all matching cells print differently"
    if r.startswith("the model chose"):
        return "model chose a cell that prints differently"
    if "model judged" in r:
        return "model chose none"
    return r[:40]


def load(name: str) -> dict[str, dict]:
    """
    Items of one trial by key.

    Args:
        name (str): Trial folder name.

    Returns:
        dict[str, dict]: Items by key.
    """
    items = json.loads((HERE / name / "items.json").read_text(encoding="utf-8"))
    return {i["key"]: i for i in items}


hand, guess = load("trial_model"), load("trial_model_guess")
for name, items in (("trial_model", hand), ("trial_model_guess", guess)):
    print(name, dict(Counter(reason(i) for i in items.values())))
lost = [k for k in hand if hand[k]["selected"] and not guess[k]["selected"]]
gained = [k for k in hand if guess[k]["selected"] and not hand[k]["selected"]]
print("linked with hand, not with guess:", len(lost), dict(Counter(reason(guess[k]) for k in lost)))
print("linked with guess, not with hand:", len(gained),
      dict(Counter(reason(hand[k]) for k in gained)))  # fmt: skip
