# Fine-tuning a model for anchoring

Goal: a local model that `provenum anchor` can use out of the box, and that finds the right table
cell more often than the base model. The base model is Qwen3-32B (best in the
[benchmark](../examples/results/README.md)); Qwen3 is Apache 2.0, so a fine-tuned adapter can be
shared.

## Pipeline

| Step | Script | Output |
|---|---|---|
| 1. Synthetic papers | `make_papers.py` | `papers/<id>/`: tables (CSV), spec, notes, `results.tex`, `items.json`, `meta.json` |
| 2. Chat examples | `make_dataset.py` | `data/train.jsonl`, `val.jsonl`, `test.jsonl`, `dockprepbench.jsonl`, `stats.json` |
| 3. Training (QLoRA) | `train.py` | `runs/<name>/`: `config.json`, `log_history.json`, `train_result.json`, `adapter/` |
| 4. Evaluation | `evaluate.py` | `evals/answers_<name>.jsonl` (every answer), `evals/scores_<name>.json` |

**Synthetic papers.** For each paper a language model (Qwen3-32B) invents a study in a given field
and its vocabulary; code generates consistent result tables (rates with Wilson intervals, paired
differences against a reference arm with intervals, gained/lost counts and adjusted p-values,
continuous measures, regression effects); the model then writes results paragraphs with
placeholders in place of numbers, and code fills them in. The correct cell of every number is
therefore known by construction. Paragraphs are rejected if a placeholder is missing or repeated,
if the model wrote a number itself, or if it left empty brackets; rejected attempts are kept in
`meta.json`. Each paper uses one of several writing styles (dense, narrative, terse), and table and
column names vary between papers.

Numbers with no cell are part of the task: a secondary-analysis table is never in the spec, some
paragraphs state protocol settings ("at pH 7.4"), and `make_dataset.py` removes one more table from
the spec of about a third of papers.

**No test leakage.** Papers from eight fields (`TEST_FIELDS`) are only used for testing, and the
DockPrepBench manuscript is only used for testing.

**Same prompts as the tool.** Examples are built with `provenum.llm.ask_prompt` and
`choose_prompt`, the functions `provenum anchor` uses, so a model is trained on exactly what it
will see.

## Where things are kept

On maddog, under `/mnt/STORAGE3/alobo/provenum-finetune/`: `papers/`, `data/`, `runs/`, `evals/`,
and the logs `gen.log`, `setup.log` and `train.log`. Small results (stats, configs, training logs,
scores and per-item answers) are copied into `finetune/results/` in this repository. The papers,
the training data and the adapter will be published on Hugging Face.

## Running it

```bash
export PYTHONPATH=/path/to/provenum/src
python make_papers.py --out papers --n 320 --n-test 40 --host http://127.0.0.1:11500 --model qwen3:32b
python make_dataset.py --papers papers --out data
python make_dataset.py --out data --dockprepbench paper/sections/results.tex --spec paper/numbers.toml \
    --tables paper/tables --notes examples/dockprepbench_notes.txt --none "pH 7.4" "2.857 times"
python train.py --data data --out runs/qwen3-32b-r16
python evaluate.py --data data/test.jsonl data/dockprepbench.jsonl --out evals --name base
python evaluate.py --data data/test.jsonl data/dockprepbench.jsonl --out evals --name r16 \
    --adapter runs/qwen3-32b-r16/adapter
```

Steps 1 and 2 need only provenum and an Ollama server; steps 3 and 4 need a CUDA GPU with about
40 GB of memory and `unsloth` (installed with `uv pip install --torch-backend cu128 unsloth`).
