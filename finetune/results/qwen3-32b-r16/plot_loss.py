"""Plot training and validation loss against epoch from the trainer's log_history.json.

Usage: python plot_loss.py   (writes loss.png and loss.pdf next to this script)
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
TRAIN, VAL = "#2a78d6", "#eb6834"  # categorical slots 1 and 2 (validated for colour vision)
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"


def main() -> None:
    """Draw the figure."""
    log = json.loads((HERE / "log_history.json").read_text(encoding="utf-8"))
    train = [(e["epoch"], e["loss"]) for e in log if "loss" in e]
    val = [(e["epoch"], e["eval_loss"]) for e in log if "eval_loss" in e]
    # update 0: the untuned model, measured afterwards with train.py --eval-only
    step0 = HERE / "eval_step0.json"
    if step0.exists():
        val.insert(0, (0.0, json.loads(step0.read_text(encoding="utf-8"))["eval_loss"]))

    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=200)
    ax.plot(*zip(*train, strict=True), color=TRAIN, lw=1.6, label="Training (every 10 updates)")
    ax.plot(*zip(*val, strict=True), color=VAL, lw=1.6, marker="o", ms=5,
            mec="white", mew=1.2, label="Validation (692 examples)")  # fmt: skip
    ax.set_yscale("log")
    ax.set_xlim(-0.02, 1.0)
    ax.set_xlabel("Epoch (642 updates of 16 examples)", color=MUTED)
    ax.set_ylabel("Loss on the reply (log scale)", color=MUTED)
    ax.grid(axis="y", color=GRID, lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper right")
    first = train[0]
    ax.annotate(f"{first[1]:.2f} (first 10 updates)", first, xytext=(6, -12), textcoords="offset points",
                fontsize=8, color=INK)  # fmt: skip
    if val[0][0] == 0.0:
        ax.annotate(f"{val[0][1]:.2f} (untuned)", val[0], xytext=(8, 4),
                    textcoords="offset points", fontsize=8, color=INK)  # fmt: skip
    ax.annotate(f"{val[-1][1]:.4f}", val[-1], xytext=(-8, 8), textcoords="offset points",
                fontsize=8, color=INK, ha="right")  # fmt: skip
    ax.set_title("Qwen3-32B QLoRA (r16): loss during the single epoch", fontsize=10,
                 color=INK, loc="left")  # fmt: skip
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"loss.{ext}")


if __name__ == "__main__":
    main()
