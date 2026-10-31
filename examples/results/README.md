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
| `score_output.txt` | Its output (rerun 2026-10-31 on the DockPrepBench tables at `d54800e`; identical to the figures first reported). |
| `prompt_claude_sonnet.txt` | The full prompt of the Claude Code subagent that produced `answers_claude_sonnet.json`, recovered from the session transcript. Claude saw all items in one pass, with domain notes in the prompt; the local models saw one number per request, with the same notes (`examples/dockprepbench_notes.txt`). |
| `commands.txt` | The commands that produced the local-model answers. |

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
188 of them; the compiled PDF text was identical before and after. `prompt_claude_sonnet_shortlist.txt`
is the full prompt of the Claude Code subagent that chose among the candidates.

## 2026-10-30-corruption

The value-only and context rows of the corruption test, rerun on the inputs of 2026-10-30 because
the first run saved no output. Context matching reproduces the recorded totals exactly; value-only
matching does not (2.3% caught, not about 1%). See that folder's README.

## 2026-10-30-benchmark

`examples/bench_models.py` on the migrated DockPrepBench Results section: 311 numbers whose correct
cell is known from their `al{}`, plus four mentions of two settings that come from no table
(`--none "pH 7.4" "2.857 times"`). Eight models, all Q4_K_M, in Ollama 0.12.6 on one RTX 6000 Ada
(48 GB), temperature 0, both modes.

| File | What it is |
|---|---|
| `bench_results.csv` | One row per model and mode: right, wrong, caught_wrong, abstain, false_anchor, seconds per number. |
| `bench.log` | The run log (code versions, model pulls, per-run summaries). |
| `run_benchmark.sh` | The script that ran it on maddog (tmux), with the exact command line. |

Only totals were recorded, not per-number answers, so agreement between models cannot be
re-scored from these files.

## 2026-10-31-webapp

The review trial: the web application's workflow on the original Results section, scored against
the hand-checked migration. See that folder's README.
