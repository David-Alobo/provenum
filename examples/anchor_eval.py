"""Score AI anchoring: coverage, agreement on the real text, and catch rate on corrupted numbers.

Usage: python anchor_eval.py ITEMS.json ANSWERS.json SPEC.toml TABLES_DIR
"""

import json
import sys
from collections import Counter

from numcheck.anchor import judge, values
from numcheck.macros import load_specs


def corrupt(number: str, k: int = 3) -> str:
    """
    Shift a number by k units in its last digit, keeping its precision.

    Args:
        number (str): Number as written.
        k (int): Units to add.

    Returns:
        str: The corrupted number.
    """
    mantissa, _, exponent = number.replace("−", "-").partition("e")
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    m = float(mantissa) + k * 10.0**-decimals * (1 if float(mantissa) >= 0 else -1)
    return f"{m:.{decimals}f}" + (f"e{exponent}" if exponent else "")


def main() -> None:
    """Print the evaluation."""
    items = {i["id"]: i for i in json.load(open(sys.argv[1], encoding="utf-8"))}
    answers = {a["id"]: a.get("path") for a in json.load(open(sys.argv[2], encoding="utf-8"))}
    table = values(load_specs(sys.argv[3]), sys.argv[4])
    real = {i: judge(items[i]["number"], answers.get(i), table) for i in items}
    print(f"{len(items)} numbers; answered {sum(1 for i in items if answers.get(i))}")
    print("real text:", dict(Counter(real.values())))
    anchored = [i for i in items if real[i] == "traced"]
    caught = sum(judge(corrupt(items[i]["number"]), answers[i], table) == "mismatch" for i in anchored)
    print(f"corrupted numbers caught among anchored-and-traced: {caught}/{len(anchored)}")
    for i in items:
        if real[i] in ("mismatch", "bad-path"):
            v = table.get(answers[i], (None, "-"))[1]
            print(f"  {real[i]:8} line {items[i]['line']}: {items[i]['number']} -> {answers[i]} = {v} | {items[i]['sentence'][:90]}")


if __name__ == "__main__":
    main()
