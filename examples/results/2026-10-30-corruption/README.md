# Corruption test: value-only and context matching (rerun 2026-10-31)

The first rows of the paper's corruption table (value only, context) were first measured on
2026-10-30 during development, and only their totals were written down (commit messages of
`f9da213` and `5ffdc7d`). No output was saved, and the value-only script was never committed. This
folder reruns both tests on the same inputs and saves the output.

## Inputs

- **Manuscript:** DockPrepBench `paper/sections/results.tex` at commit `d54800e`, the last commit
  before the context test. It is byte-identical to `../2026-10-30-anchoring/results_original.tex`.
- **Tables:** DockPrepBench `paper/tables/` at `d54800e`: 27 CSV files, 24 after the config's
  exclusions (`agreement_per_complex.csv`, `*ligand_properties.csv`, `robust_cofactor_list.csv`).
- **Code:** provenum (then `numcheck`) at commit `5ffdc7d`. Its `check.py`, the value-only
  checker, is unchanged from the prototype `f9da213`.
- **Config:** `config_5ffdc7d.toml` (aliases from prose words to table labels, and the exclusions).

## Files

| File | What it is |
|---|---|
| `mutation_eval_5ffdc7d.py` | The context test as committed in `5ffdc7d`. |
| `mutation_eval_output.txt` | Its output on the inputs above. |
| `corruption.py` | Both tests, value only and context, scored on all 562 decimals and on the 307 prose decimals of the anchoring experiment. Written 2026-10-31. |
| `corruption_output.txt` | Its output. |

## Results

| Method | Set | Corruptions caught | Correct numbers flagged |
|---|---|---|---|
| Value only | all 562 decimals | 13 (2.3%) | 4 |
| Value only | 307 prose decimals | 10 (3.3%) | 4 |
| Context | all 562 decimals | 113 (20.1%); 23 of 26 (88.5%) where anchored | 29 |
| Context | 307 prose decimals | 57 (18.6%); 8 of 11 (72.7%) where anchored | 26 |

`mutation_eval_5ffdc7d.py` reproduces the totals recorded in the commit message of `5ffdc7d`
exactly: 20% caught overall, 88% where anchored, and 44 false alarms. The 44 count every number
the extractor finds, integers included (778 numbers); among decimals there are 29. It also finds
the 28 numbers that trace to no table (`unsourced`).

The value-only rate recorded in `f9da213` ("~1%") is **not** reproduced: the rerun catches
2.3% of all decimals, and 3.3% of prose decimals. It also flags 4 correct decimals, where the
README and paper said 0. The settings of the original run cannot be recovered (no script and no
output were saved). The paper now quotes the rerun.

The 562 decimals include numbers inside LaTeX tables. The 307 used by the model experiments are
the decimals in running prose (`provenum.anchor.items` skips `tabular` environments). Every one of
the 307 was found among the 562 by line and value.

## Reproducing

```bash
git -C DockPrepBench archive d54800e paper | tar -x -C snap/
git -C provenum archive 5ffdc7d | tar -x -C pv5/
cd pv5
PYTHONPATH=src python ../provenum/examples/results/2026-10-30-corruption/corruption.py \
    ../snap/paper/sections/results.tex ../snap/paper/tables examples/dockprepbench.toml \
    ../provenum/examples/results/2026-10-30-anchoring/items.json
PYTHONPATH=src python examples/mutation_eval.py \
    ../snap/paper/sections/results.tex ../snap/paper/tables examples/dockprepbench.toml
```
