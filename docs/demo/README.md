# README demo

`provenum_demo.gif` (960 px wide, 11 frames, about 20 s) shows the web app on the Results section
of the DockPrepBench manuscript: upload the project, upload the tables, use the author's spec,
let Qwen3-32B link the numbers, review the three lists, download. Recorded 2026-10-31.

Every frame is a screenshot of the running app (`provenum serve`), driven in headless Chrome
through the DevTools protocol: files are chosen in the file inputs and buttons are clicked, as a
user would. Nothing on screen is mocked up.

| File | What it is |
|---|---|
| `make_gif.py` | Records the frames and writes the GIF. |
| `frame_00.png` … `frame_10.png` | The frames at full width (1280 px, saved at 960). |
| `frames.json` | Each frame's time on screen and what it shows, and the session id. |

Inputs: `examples/results/2026-10-30-anchoring/results_original.tex` as the paper, and the 28
tables and `numbers.toml` of DockPrepBench at commit `0d714f6`; `qwen3:32b` in Ollama on maddog
(GPU 2), reached through an SSH tunnel on port 11501; the notes in
`examples/dockprepbench_notes.txt`. The run behind the GIF linked 248 numbers; its answers and
how they differ from the saved trial are in
`examples/results/2026-10-31-webapp/rerun_text_fixes`.

To record again (about 8 minutes, most of it the model):

```bash
git -C DockPrepBench archive 0d714f6 paper/numbers.toml paper/tables | tar -x -C snap/
uv run --no-project --with websocket-client --with pillow python docs/demo/make_gif.py \
    http://127.0.0.1:8765 http://127.0.0.1:11501 snap/paper docs/demo
```

Recording it found three bugs, fixed before this version: a late model-list reply could clear the
chosen model; `\SI{2}{\angstrom}` lost its unit; the first sentence of a paragraph lost its first
letter. The review screen also now shows `\ge` and similar as symbols.
