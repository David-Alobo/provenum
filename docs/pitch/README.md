# Pitch video

`provenum_pitch.mp4`: a draft pitch video, 2 min 5 s, 1080p, with a synthetic British voiceover
(Windows "Microsoft Hazel Desktop"). Made 2026-10-31.

- `narration.json`: the script, one line per scene.
- `pitch.html`: the scenes; `#scene:step` shows one state.
- `tts.ps1`: writes `vo_<scene>.wav` from the script (Windows speech synthesis).
- `render.py`: captures each scene state with headless Chrome, crossfades them and muxes the
  narration with ffmpeg (from `imageio-ffmpeg`).
- `shot_upload_c.png`, `shot_review_model.png`: screenshots of the web app on the DockPrepBench
  results section. The review screenshot comes from the guessed-spec run, reproduced in
  `examples/results/2026-10-31-webapp/trial_model_guess`.

Where the numbers on screen come from:
- **"17 cells hold this value"**: `trial_hand/items.json`, first item (46.3), 17 candidates.
- **249 of 307 linked, 228 same cell, 20/21 others flagged, 0 of 504 lines changed**:
  `examples/results/2026-10-31-webapp/trial_model` (see that folder's README).
- **The "after the next rerun" scene** uses the example output from provenum's README, and the
  video says so on screen.

To render again:

```bash
powershell -File tts.ps1 -Dir .
uv run --no-project --with imageio-ffmpeg --with pillow --with numpy python render.py . provenum_pitch.mp4
```
