# Web app trials on the DockPrepBench results section (2026-10-31)

These trials run the web app's workflow (`provenum.web.session.Session`) without a browser, on the
original hand-typed DockPrepBench results section. Each link it makes is scored against the
hand-checked migration of that section in the DockPrepBench paper. Every number below can be
recomputed from the files in this folder with `python scripts/summarise.py`, which writes
`summary.json`.

## Inputs

- **Manuscript:** `../2026-10-30-anchoring/results_original.tex`, the section before migration:
  504 lines and 307 hand-typed decimals. The app treats it as `sections/results.tex` of a
  two-file project.
- **Tables:** the 28 CSV tables named in DockPrepBench's `paper/numbers.toml`, 3452 values.
  DockPrepBench commit `0d714f6` (2026-10-30); `paper/` was unmodified.
- **Specs:**
  - **hand:** DockPrepBench's own `paper/numbers.toml`.
  - **guess:** the spec `provenum init` guessed from the same tables (3472 values; it shows some
    columns the hand spec leaves out).
- **Reference ("paper"):** DockPrepBench's migrated `paper/sections/results.tex` and its
  `numbers.tex`, at the same commit.
- **Model:** `qwen3:32b` through Ollama on maddog (GPU 2), temperature 0, thinking off, project
  notes from `../../dockprepbench_notes.txt`. In shortlist mode it chooses among cells whose value
  matches the number.

## How links are scored

- **PDF unchanged** (`scripts/same_text.py`): every `\val{}` in the migrated section is replaced by
  its generated value, and each line is compared with the original after normalising LaTeX number
  markup.
- **Agreement with the paper** (`scripts/score_vs_paper.py`):
  - Lines are matched by their text with values filled in. Within a line, each link is compared
    with the paper's link at the same position.
  - Links are compared as **cells** (table file, row, column), not as path names, because the
    guessed spec names some cells differently. A first version compared names and reported 25
    differences for `trial_guess`; 19 of those were the same cell under another name.
  - The outcomes are:
    - *same cell*: the paper links the same cell;
    - *different cell*: the paper links another cell;
    - *no `\val` in paper there*: the paper left that number as typed.

## Results

| Trial | Spec | Who chooses | Numbers | Linked | Same cell | Different cell | Paper left typed | PDF lines changed |
|---|---|---|---|---|---|---|---|---|
| `trial_hand` | hand | nobody: accept every number with exactly one matching cell | 307 | 78 | 68 | 0 | 10 | 0 of 504 |
| `trial_guess` | guess | the same | 307 | 83 | 67 | 6 | 10 | 0 of 504 |
| `trial_model` | hand | qwen3:32b, every suggestion accepted | 307 | 249 | 228 | 18 | 3 | 0 of 504 |
| `trial_model_guess` | guess | the same | 307 | 224 | 207 | 16 | 1 | 0 of 504 |

**Why the guessed spec links fewer numbers.** In `trial_model_guess` the review lists were 161
to confirm, 63 linked and 83 left as typed. Compared number by number with `trial_model`, 26
numbers were linked with the hand spec but not the guessed one, and 1 the other way round, a net
25. Of the 26:
- **17 are formatting.** Either the model chose a cell that the guessed spec prints differently
  from the text (10; for example another number of decimals), or every matching cell does (7).
  Correcting formats at the spec step, step 3 of the app, would let the app link these.
- **9 are the model choosing "none"** among the guessed spec's differently named cells.

All 17 disagreements in this trial were in the "to confirm" list; none were in "linked".

**Review lists in `trial_model`.** The app put the 307 numbers into three lists:

| List | Numbers | Disagreements |
|---|---|---|
| To confirm (several cells share the value) | 182 | 20 |
| Linked (one matching cell, and the model's choice) | 67 | 1 |
| Left as typed | 58 | – |

**The 21 disagreements, one by one.** The file `trial_model/disagreements_classified.csv` gives
the sentence, both cells and a reading of each disagreement. This is Claude's reading, to be
checked by the author.

| Reading | Count | In "to confirm" | In "linked" |
|---|---|---|---|
| Wrong cell | 8 | 8 | 0 |
| Same quantity, stored in another table (e.g. Vina's baseline rate in `summary` and in `comparisons`) | 8 | 8 | 0 |
| Probably the same quantity | 2 | 2 | 0 |
| Correct, where the paper left the number typed | 2 | 1 | 1 |
| Probably correct, where the paper left the number typed | 1 | 1 | 0 |

So, on this reading, 8 of the 249 suggested links (3.2%) point to the wrong cell. All 8 were in
the list the app asks the researcher to confirm.

**Without a model, a single matching cell is not enough evidence.** In `trial_hand`, 10 of the
78 numbers with exactly one matching cell were linked where the paper left the number typed. In
`trial_guess` that was 16 of 83.

`trial_hand/disagreements_classified.csv` reads the 10 one by one: 9 are coincidences, for
example:
- "a spread of 8.9 points" linked to an interval bound;
- "odds ratio 10.5" linked to a share column.

The tenth, a standard deviation of 0.4 points, is a correct link that the paper left typed. This
is Claude's reading, to be checked by the author. An earlier note (commit `6cf86f3`) said all 10
were coincidences, which was wrong.

So 9 of 78 single-match links (11.5%) point to a cell holding the same value by chance. This is
why the app no longer offers "accept every number with one matching cell".

## Repeat runs

`repeat_hand/run1.json` to `run3.json` hold the model's pick and review list for every number,
from three identical runs: hand spec, same notes, same model. See `summary.json` → `repeat_hand`
for the pairwise differences.

**The model's choices did not change between runs.**
- Each of the three runs took about 410 s for 307 numbers and linked 249.
- All 307 picks were identical in every pair of runs, and identical to `trial_model`. That makes
  four identical runs in total.
- With temperature 0, a fixed model and fixed inputs, these results reproduce exactly on this
  setup (one Ollama server, one GPU).

The two app runs that linked different numbers of cells (249 and 224) therefore differed because
of the spec, not because of the model: the second used the guessed spec. `trial_model_guess`
reruns that condition and reproduces it exactly: 224 linked, with lists of 161, 63 and 83.

## Not saved, or aborted

- **The app run used for the pitch-video screenshot** (guessed spec, qwen3:32b, 224 linked) kept
  its picks only in the server's memory, and they were lost when the server restarted.
  `trial_model_guess` reruns the same condition and reproduces its counts.
- **An earlier `trial_model` run, before the fix in commit `2afc283`,** crashed at the apply step.
  The model had chosen a cell that prints differently from the text, and the app had preselected
  it. Its lists were 190 to confirm, 69 linked and 48 left as typed. That run is superseded by
  `trial_model`, which ran after the fix.
- **The first attempt at `trial_model_guess` was aborted** when the SSH tunnel to the Ollama server
  dropped and a request timed out after 120 s. It saved no data. The run in this folder is the
  second attempt, through a new tunnel.

## Reproducing

```bash
# trials (each writes a session folder with the migrated project; items.json is copied here)
python scripts/web_trial.py EXAMPLES DOCKPREPBENCH/paper/tables OUT hand|guess [MODEL HOST]
python scripts/same_text.py OUT
python scripts/score_vs_paper.py OUT DOCKPREPBENCH/paper -v
python scripts/repeat_runs.py EXAMPLES DOCKPREPBENCH/paper/tables OUT qwen3:32b HOST 3
python scripts/summarise.py
```

`EXAMPLES` is provenum's `examples/` folder. Run the scripts with provenum installed
(`uv run python ...` from the repository).
