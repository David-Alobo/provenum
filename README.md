# numcheck

Keep the numbers in a manuscript tied to the data that produced them.

When results are rerun, or text is rewritten by hand or by an AI assistant, numbers in the prose
can drift from the analysis output. numcheck works from the result tables your analysis writes
(CSV), not from the typeset paper, so a wrong table is caught as well as a wrong sentence.

- **`numcheck values`**: generate `\val{...}` entries from the tables, so the manuscript writes
  `\val{comparisons/vina/top1/box_padding_2/delta_pts}` instead of a hard-coded "+6.8".
- **`numcheck lint`**: list numbers still written by hand.
- **`numcheck migrate`**: replace numbers that an anchoring step has linked to a table value,
  only where the generated value reproduces the written text.
- **`numcheck audit`**: trace numbers to tables by their surrounding words, without macros.

Status: prototype. Evaluated on the DockPrepBench manuscript (see `examples/`).
