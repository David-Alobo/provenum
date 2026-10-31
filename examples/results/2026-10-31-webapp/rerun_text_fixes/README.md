# Rerun after the sentence-text fixes (2026-10-31, 15:45)

The run recorded for the README demo GIF (`docs/demo`): the same inputs as `trial_model` (hand
spec, `qwen3:32b` through Ollama on maddog, temperature 0, the same notes), through the web app,
after three fixes to the text the model and the reviewer see:

- `\SI{2}{\angstrom}` now keeps its unit ("within 2 Å"; `latex._clean`);
- the first sentence of a paragraph no longer loses its first character (`anchor.items`);
- the review screen shows `\ge`, `\le`, `\times`, `\pm`, `\approx` as symbols (display only).

The same 307 numbers were found on the same lines; 157 sentences read differently.

Result: 248 linked (181 to confirm, 67 linked, 59 left typed), against 249 (182, 67, 58) in
`trial_model`. Five numbers changed (`differences_from_trial_model.json`). Reading each sentence
(Claude's reading, to be checked by the author):

| Number | `trial_model` | This run | Reading |
|---|---|---|---|
| 48.1 | `engines/smina/vina/shared/rate_b` | `engines/gnina/vina/shared/rate_b` | wrong → right (the sentence compares Vina with Gnina; this was one of the 8 wrong cells) |
| 44.2 | left typed | `summary/vina/box_padding_8/top1` | newly linked; Vina's lowest rate over the protocols, apparently right |
| 0.014 | `posebusters_published/docked/p` | left typed (model chose none) | a correct link lost |
| 4.2 | `followup_interaction/2/diff_pts` | left typed (chosen cell prints differently) | a correct link lost |
| 0.67 | left typed | left typed | another cell considered; no change in outcome |

The published trial results (`trial_model`, the paper's Table 4) come from the code before these
fixes and stand as recorded. `items.json` holds every number of this run.
