# provenum manuscript

LaTeX source for the methods paper (arXiv preprint first).

```bash
cd paper
latexmk main.tex        # output in build/main.pdf
```

`\result{...}` (orange) marks numbers still to come, mainly the local-model benchmark; `\todo{...}`
(red) marks other gaps. Search for both before submitting.

Every reference in `references.bib` was checked against Crossref or DataCite; add new ones the
same way. Numbers in the text come from `examples/results/` and the README's evaluation tables.
