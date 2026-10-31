# Results: Qwen3-32B QLoRA, rank 16 (`qwen3-32b-r16`)

One epoch on 10,268 anchoring examples from 304 synthetic papers (setup in `../../README.md`),
trained on maddog (RTX 6000 Ada) from 2026-10-30 23:20 to 2026-10-31 07:48 UTC.

## Training

| File | What it is |
|---|---|
| `config.json` | Every training argument and library version. |
| `log_history.json` | Training loss every 10 updates, validation loss every 100. |
| `train_result.json` | The trainer's final metrics (mean training loss 0.041, 30,394 s). |
| `eval_step0.json`, `eval_step0.log` | Validation loss before training (update 0), measured afterwards with `train.py --eval-only` on the same 692 examples: 2.18. |
| `plot_loss.py` → `loss.png`, `loss.pdf` | Loss against epoch. |
| `pipeline.log` | Every step of the overnight pipeline and the reruns, with times and code versions. |

Validation loss fell from 2.18 (update 0) to 0.0105 at update 100 and 0.0050 at update 200, then
stayed between 0.0050 and 0.0062 to the end (0.0054). The line between updates 0 and 100 in the
figure joins two measurements; the loss between them was not measured.

## Evaluation

`evals/` holds every answer of both models (`answers_*.jsonl`: the reply, the parsed path and the
example's metadata) and their scores. Both runs used `evaluate.py` at provenum `05d1523`: greedy
decoding, at most 96 new tokens, replies started with `{"path":`. The test sets are the 16
held-out synthetic papers (559 numbers with a cell, 103 and 53 without) and the DockPrepBench
Results section (311 numbers with a cell, 4 and 3 without), which was never used in training.

`compare.py` pairs the two runs example by example and writes `comparison.json`;
`comparison.txt` is its output.

| Test set | Mode | Base right | Fine-tuned right | Gained / lost | Exact McNemar p |
|---|---|---|---|---|---|
| DockPrepBench | blind | 152 / 311 (48.9% [43.4, 54.4]) | 210 (67.5% [62.1, 72.5]) | +74 / −16 | 4.4 × 10⁻¹⁰ |
| DockPrepBench | shortlist | 271 (87.1% [83.0, 90.4]) | 288 (92.6% [89.1, 95.0]) | +25 / −8 | 0.0046 |
| Synthetic | blind | 361 / 559 (64.6% [60.5, 68.4]) | 533 (95.3% [93.3, 96.8]) | +177 / −5 | 5.3 × 10⁻⁴⁶ |
| Synthetic | shortlist | 512 (91.6% [89.0, 93.6]) | 551 (98.6% [97.2, 99.3]) | +41 / −2 | 2.2 × 10⁻¹⁰ |

Intervals are Wilson 95%. Other outcomes (base → fine-tuned):

- **Wrong cells:** DockPrepBench blind 158 → 94, of which the value check would pass 11 → 1;
  shortlist 19 → 17, all of which pass (every shortlist candidate holds the written value).
  Synthetic blind 187 → 24, shortlist 12 → 6.
- **False anchors** (a cell given for a number that has none): DockPrepBench blind 3 → 0;
  synthetic blind 27 → 3, shortlist 5 → 0.
- **No answer:** DockPrepBench blind 1 → 7, shortlist 21 → 6.

The base model's DockPrepBench scores agree with the Ollama benchmark of the same model
(`examples/results/2026-10-30-benchmark`): 152 right in blind mode in both, and 271 here against
274 there in shortlist mode, which used Ollama's 4-bit build and a JSON schema instead of a reply
prefix.

**Out of memory.** The fine-tuned model could not answer three examples, the three longest
prompts (13,122 to 21,531 characters), even one at a time on a 48 GB GPU; one each in
DockPrepBench shortlist, synthetic blind and synthetic shortlist. They count as no answer. The
base model answered all of them.

## Runs that failed or were superseded

All kept in `evals_failed/` or on maddog, and recorded in `pipeline.log`:

1. **Tuned evaluation, first attempt** (07:48): ran out of memory on the last batch at 1,900 of
   1,903 and saved nothing (`evaluate.py` now falls back to one example at a time, commit
   `fa9ba4a`).
2. **Tuned evaluation, second attempt** (11:53): ran out of memory on single examples and saved
   nothing (such examples are now recorded as errors, commit `731854c`).
3. **Base and tuned evaluations with the prefix `{"path": `** (`evals_failed/`): the trailing
   space forced a token split that the fine-tuned model never saw in training (Qwen's tokenizer
   writes ` "` as one token), and it answered `{"path": 0}` for 723 examples, scoring 73 right on
   DockPrepBench shortlist. The base model was barely affected (251 there against 271 with the
   fixed prefix). Superseded by `evals/` (commit `05d1523`).
