"""Score a model, with or without a LoRA adapter, on anchoring examples.

Base and fine-tuned models go through the same code: same prompts, greedy decoding, same
parsing. A blind answer must be a path or null; a shortlist answer must be one of the offered
paths or "none" (anything else counts as abstaining, as in provenum). Every answer is saved
(answers_<name>.jsonl) alongside the summary (scores_<name>.json).

Scores per mode, on numbers with a table cell: right, wrong, passed (wrong but the value check
would accept it, i.e. the wrong cell has the same rounded value) and abstain; on numbers with no
cell (settings, analyses outside the catalogue): false_anchor.

Usage:
    python evaluate.py --data data/test.jsonl data/dockprepbench.jsonl --out evals \\
        --name base [--adapter runs/qwen3-32b-r16/adapter]
"""

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

PREFIX = '{"path": '  # every reply starts here, as under provenum's JSON schema


def parse(reply: str, meta: dict) -> str | None:
    """
    Read the path from a reply, applying provenum's rules for each mode.

    Args:
        reply (str): Generated text.
        meta (dict): Example metadata (mode, traced).

    Returns:
        str | None: The path, or None (null, "none", unparsable or not offered).
    """
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    start = reply.find("{")
    try:  # the first JSON object; anything the model writes after it is ignored
        obj, _ = json.JSONDecoder().raw_decode(reply[start:]) if start >= 0 else (None, 0)
        path = obj.get("path") if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
    if not isinstance(path, str) or not path.strip() or path == "none":
        return None
    if meta["mode"] == "shortlist" and path not in meta["traced"]:
        return None
    return path


def score(rows: list[dict]) -> dict:
    """
    Summarise answers per dataset and mode.

    Args:
        rows (list[dict]): {meta, answer} per example.

    Returns:
        dict: {"<paper group>/<mode>": counts}.
    """
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        m, a = r["meta"], r["answer"]
        group = "dockprepbench" if m["paper"] == "dockprepbench" else "synthetic"
        c = out[f"{group}/{m['mode']}"]
        if m["gold"] is None:
            c["no_cell"] += 1
            c["false_anchor"] += a is not None
            continue
        c["values"] += 1
        if a is None:
            c["abstain"] += 1
        elif a == m["gold"]:
            c["right"] += 1
        else:
            c["wrong"] += 1
            c["passed"] += a in m["traced"]
    return {k: dict(v) for k, v in sorted(out.items())}


def main() -> None:
    """Generate answers for every example and write answers and scores."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--base", default="unsloth/Qwen3-32B-unsloth-bnb-4bit")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--max-len", type=int, default=12288, help="longest prompt in tokens")
    parser.add_argument("--limit", type=int, help="first N examples per file (a quick check)")
    args = parser.parse_args()

    from unsloth import FastLanguageModel

    examples = []
    for f in args.data:
        lines = f.read_text(encoding="utf-8").splitlines()[: args.limit]
        examples += [json.loads(line) for line in lines]
    model, tokenizer = FastLanguageModel.from_pretrained(
        str(args.adapter) if args.adapter else args.base,
        max_seq_length=args.max_len,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    tokenizer.padding_side = "left"

    rows, t0 = [], time.time()
    examples.sort(key=lambda e: len(e["messages"][1]["content"]))  # similar lengths per batch
    for i in range(0, len(examples), args.batch):
        batch = examples[i : i + args.batch]
        # provenum asks Ollama for JSON matching a schema, which forces the reply to start as
        # {"path": ...}. Starting the reply that way here does the same for every model;
        # without it an untuned model answers in prose and never gives a path.
        prompts = [tokenizer.apply_chat_template(e["messages"][:2], tokenize=False,
                                                 add_generation_prompt=True,
                                                 enable_thinking=False) + PREFIX
                   for e in batch]  # fmt: skip
        enc = tokenizer(prompts, return_tensors="pt", padding=True).to("cuda")
        gen = model.generate(**enc, max_new_tokens=96, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id)  # fmt: skip
        replies = tokenizer.batch_decode(gen[:, enc["input_ids"].shape[1] :],
                                         skip_special_tokens=True)  # fmt: skip
        for e, reply in zip(batch, replies, strict=True):
            reply = PREFIX + reply
            rows.append({"meta": e["meta"], "reply": reply, "answer": parse(reply, e["meta"])})
        print(f"{len(rows)}/{len(examples)} ({time.time() - t0:.0f} s)", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / f"answers_{args.name}.jsonl", "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    scores = {"name": args.name, "adapter": str(args.adapter) if args.adapter else None,
              "base": args.base, "data": [str(f) for f in args.data],
              "seconds": round(time.time() - t0), "scores": score(rows)}  # fmt: skip
    (args.out / f"scores_{args.name}.json").write_text(json.dumps(scores, indent=1),
                                                       encoding="utf-8")  # fmt: skip
    print(json.dumps(scores, indent=1))


if __name__ == "__main__":
    main()
