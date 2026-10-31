"""Render the provenum pitch: capture scene states with headless Chrome, blend, add narration.

Usage: python render.py PITCH_DIR OUT.mp4
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

D = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FPS, W, H = 30, 1920, 1080
STEPS = {"hook": 3, "problem": 4, "idea": 3, "hard": 3, "upload": 0, "review": 0, "same": 3,
         "diff": 0, "close": 2}  # reveal steps after the first state
FIRST = {"hook": 1}  # hook starts with its first line showing
PAD, FADE = 0.7, 0.35  # seconds of silence after each line; crossfade length


def capture(scene: str, step: int) -> Path:
    """Screenshot one state of a scene."""
    png = D / "frames" / f"{scene}_{step}.png"
    png.parent.mkdir(exist_ok=True)
    url = (D / "pitch.html").as_uri() + f"#{scene}:{step}"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--allow-file-access-from-files", f"--window-size={W},{H}",
                    "--virtual-time-budget=1500", f"--user-data-dir={D / 'chrome-prof'}",
                    f"--screenshot={png}", url], check=True, capture_output=True)
    return png


def seconds(path: Path) -> float:
    """Length of a wav file."""
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


lines = json.loads((D / "narration.json").read_text(encoding="utf-8"))
timeline, audio, t = [], [], 0.0  # timeline: (start, end, image path)
for line in lines:
    scene = line["scene"]
    vo = D / f"vo_{scene}.wav"
    dur = seconds(vo) + PAD
    first = FIRST.get(scene, 0)
    states = list(range(first, STEPS[scene] + 1)) if STEPS[scene] else [0]
    # reveal steps spread over the first 80% of the line
    starts = [t + dur * 0.8 * i / len(states) for i in range(len(states))]
    for i, st in enumerate(states):
        end = starts[i + 1] if i + 1 < len(states) else t + dur
        timeline.append((starts[i], end, capture(scene, st)))
    audio.append((t, vo))
    t += dur
total = t
print(f"{len(timeline)} states, {total:.1f} s")

# narration track
rate = 44100
track = np.zeros(int(total * rate) + rate, dtype=np.int16)
for start, vo in audio:
    with wave.open(str(vo)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    i = int(start * rate)
    track[i:i + len(pcm)] = pcm
with wave.open(str(D / "narration.wav"), "w") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(track.tobytes())

imgs = {p: np.asarray(Image.open(p).convert("RGB").resize((W, H))) for _, _, p in timeline}
ff = imageio_ffmpeg.get_ffmpeg_exe()
proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(D / "narration.wav"),
                         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                         str(OUT)], stdin=subprocess.PIPE)
k = 0
for n in range(int(total * FPS)):
    now = n / FPS
    while k + 1 < len(timeline) and now >= timeline[k + 1][0]:
        k += 1
    frame = imgs[timeline[k][2]]
    if k > 0 and now - timeline[k][0] < FADE:  # crossfade from the previous state
        a = (now - timeline[k][0]) / FADE
        frame = (imgs[timeline[k - 1][2]] * (1 - a) + frame * a).astype(np.uint8)
    if now < 0.5:  # fade in from black
        frame = (frame * (now / 0.5)).astype(np.uint8)
    if total - now < 0.8:  # fade out to black
        frame = (frame * max(0.0, (total - now) / 0.8)).astype(np.uint8)
    proc.stdin.write(frame.tobytes())
proc.stdin.close()
proc.wait()
print("written", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")
