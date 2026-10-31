# Recorded results

Raw inputs and model answers behind the numbers quoted in the main README, kept so every
figure can be re-scored. All runs are on the Results section of the DockPrepBench manuscript.

## 2026-10-30-anchoring

The first anchoring experiment: which table value does each of 307 hand-typed decimals report?

| File | What it is |
|---|---|
| `results_original.tex` | The Results section before any migration (the input). |
| `items.json` | The 307 numbers with their sentences and paragraphs (`provenum.anchor.items`). |
| `catalogue.txt` | The catalogue of addressable values the models were shown. |
| `answers_claude_sonnet.json` | Claude Sonnet, value-blind (paths chosen from the catalogue only). |
| `answers_qwen14b.json` | Qwen2.5-14B-Instruct via Ollama, value-blind. |
| `answers_qwen32b_blind.json` | Qwen2.5-32B-Instruct, value-blind. |
| `answers_qwen14b_shortlist.json`, `answers_qwen32b_shortlist.json` | Same models, migration mode (`--shortlist`). |
| `score.py` | Scores the answer files: traced, mismatch, bad path, abstained, corrupted numbers caught, and agreement with Claude. |

Re-score from the DockPrepBench repository root (it reads `paper/tables`):

```bash
PYTHONPATH="../provenum/src;../provenum/examples" python ../provenum/examples/results/2026-10-30-anchoring/score.py \
    ../provenum/examples/results/2026-10-30-anchoring \
    answers_claude_sonnet.json answers_qwen14b.json answers_qwen32b_blind.json \
    answers_qwen14b_shortlist.json answers_qwen32b_shortlist.json
```

(Use `:` instead of `;` in `PYTHONPATH` on Linux and macOS.) The table values come from the
DockPrepBench tables as of 2026-10-30; regenerated tables with different values would change
the scores.

## 2026-10-30-migration

The second migration of DockPrepBench's Results: 245 remaining hand-typed numbers, each with the
table paths whose value matches (`items_with_candidates.json`), and Claude Sonnet's choice among
them (`answers_claude_sonnet_shortlist.json`: 211 paths, 34 none). `provenum migrate` replaced
188 of them; the compiled PDF text was identical before and after.

## Model benchmark

Results of `examples/bench_models.py` (Qwen2.5, Qwen3 and Llama on 311 gold sentences) will be
added here when the run finishes.
