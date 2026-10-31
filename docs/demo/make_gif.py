"""Record the README demo GIF by driving the running web app in headless Chrome.

Every frame is a screenshot of the real app (`provenum serve`) working on the original
DockPrepBench Results section: upload the project, upload the tables, use the hand-written spec,
let a local model link the numbers, review, apply. Chrome is driven through its DevTools protocol,
so files are chosen and buttons pressed as a user would.

Usage:
    python make_gif.py APP_URL OLLAMA_URL DOCKPREPBENCH_PAPER_DIR OUT_DIR
e.g. python make_gif.py http://127.0.0.1:8765 http://127.0.0.1:11501 snap/paper docs/demo
(DOCKPREPBENCH_PAPER_DIR is DockPrepBench's paper/ folder at commit 0d714f6, holding numbers.toml
and tables/.) Needs websocket-client and pillow.
"""

import base64
import io
import json
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

import websocket
from PIL import Image

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
WIDTH, HEIGHT = 1280, 860
MAIN = "\\documentclass{article}\n\\begin{document}\n\\input{sections/results}\n\\end{document}\n"


class Page:
    """A minimal DevTools-protocol client for one Chrome tab."""

    def __init__(self, ws_url: str):
        """
        Connect to a tab.

        Args:
            ws_url (str): The tab's webSocketDebuggerUrl.
        """
        self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        self.n = 0

    def call(self, method: str, **params) -> dict:
        """
        Send one command and wait for its reply, skipping events.

        Args:
            method (str): Protocol method, e.g. "Page.navigate".
            **params: Its parameters.

        Returns:
            dict: The command's result.
        """
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        """
        Evaluate JavaScript in the page and return its value.

        Args:
            expr (str): Expression (awaited if it is a promise).

        Returns:
            The value.
        """
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    def wait(self, expr: str, timeout: float = 60) -> None:
        """
        Wait until a JavaScript condition is true.

        Args:
            expr (str): Boolean expression.
            timeout (float): Seconds.

        Returns:
            None

        Raises:
            TimeoutError: If the condition stays false.
        """
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return
            time.sleep(0.3)
        raise TimeoutError(expr)

    def upload(self, selector: str, path: Path) -> None:
        """
        Choose a file in a file input, as a user would.

        Args:
            selector (str): CSS selector of the input.
            path (Path): File to choose.

        Returns:
            None
        """
        root = self.call("DOM.getDocument")["root"]["nodeId"]
        node = self.call("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
        self.call("DOM.setFileInputFiles", nodeId=node, files=[str(path)])

    def shot(self, scroll_to: str) -> Image.Image:
        """
        Scroll an element to the top of the window and take a screenshot.

        Args:
            scroll_to (str): CSS selector.

        Returns:
            Image.Image: The screenshot.
        """
        self.js(f"document.querySelector({json.dumps(scroll_to)}).scrollIntoView({{block: 'start'}});"
                "window.scrollBy(0, -12); document.activeElement.blur(); true")  # fmt: skip
        time.sleep(0.4)
        data = self.call("Page.captureScreenshot", format="png")["data"]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


def inputs(paper: Path, tmp: Path) -> tuple[Path, Path, str, str]:
    """
    Build the two zips a user would upload, and read the spec and notes.

    Args:
        paper (Path): DockPrepBench's paper/ folder.
        tmp (Path): Scratch folder.

    Returns:
        tuple: project zip, tables zip, hand spec text, notes text.
    """
    project, tables = tmp / "dockprepbench-overleaf.zip", tmp / "tables.zip"
    with zipfile.ZipFile(project, "w") as z:
        z.writestr("main.tex", MAIN)
        z.writestr("sections/results.tex", (EXAMPLES / "results/2026-10-30-anchoring/results_original.tex")
                   .read_text(encoding="utf-8"))  # fmt: skip
    spec = (paper / "numbers.toml").read_text(encoding="utf-8")
    with zipfile.ZipFile(tables, "w") as z:
        for t in tomllib.loads(spec)["table"]:
            z.write(paper / "tables" / t["file"], t["file"])
    notes = (EXAMPLES / "dockprepbench_notes.txt").read_text(encoding="utf-8")
    return project, tables, spec, notes


def main() -> None:
    """Record the frames, then write the GIF and a frames list."""
    app, ollama, paper, out = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="provenum-gif-"))
    project, tables, spec, notes = inputs(paper, tmp)

    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                               "--remote-debugging-port=9333", f"--user-data-dir={tmp / 'prof'}",
                               f"--window-size={WIDTH},{HEIGHT}", "about:blank"])  # fmt: skip
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
                break
            except OSError:
                time.sleep(0.2)
        page = Page(next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT,
                  deviceScaleFactor=1, mobile=False)  # fmt: skip
        page.call("Page.navigate", url=app + "/")
        page.wait("document.readyState === 'complete'")
        frames = []  # (image, seconds on screen, what it shows)

        frames.append((page.shot("#step-project"), 1.6, "1: upload the Overleaf project"))
        page.upload("#project-file", project)
        page.wait("!document.querySelector('#step-tables').hidden")
        page.upload("#tables-file", tables)
        page.wait("!document.querySelector('#step-spec').hidden")
        frames.append((page.shot("#step-tables"), 2.0, "2-3: tables uploaded, spec guessed"))

        page.js(f"document.querySelector('#spec').value = {json.dumps(spec)}; "
                "document.querySelector('#save-spec').click(); true")  # fmt: skip
        page.wait("document.querySelector('#spec-info').textContent.startsWith('28 tables')")
        page.js(f"const h = document.querySelector('#host'); h.value = {json.dumps(ollama)}; "
                "h.dispatchEvent(new Event('change')); true")  # fmt: skip
        page.wait(
            "[...document.querySelector('#model').options].some(o => o.value === 'qwen3:32b')"
        )
        page.js(f"document.querySelector('#model').value = 'qwen3:32b'; "
                f"document.querySelector('#notes').value = {json.dumps(notes)}; true")  # fmt: skip
        frames.append((page.shot("#step-spec"), 2.4, "3-4: the author's spec; model chosen"))

        time.sleep(3)  # any model-list request still in flight must not change the choice
        if page.js("document.querySelector('#model').value") != "qwen3:32b":
            raise RuntimeError("the model selection was lost before Run")
        page.js("document.querySelector('#run').click(); true")
        page.wait("!document.querySelector('#run-progress').hidden", 30)
        targets = [0.15, 0.4, 0.65, 0.9]
        while targets:
            done = page.js("document.querySelector('#run-progress').value / "
                           "document.querySelector('#run-progress').max")  # fmt: skip
            if page.js("!document.querySelector('#step-review').hidden"):
                break
            if done is not None and done >= targets[0]:
                frames.append((page.shot("#step-run"), 0.7, f"4: linking, {100 * done:.0f}%"))
                targets.pop(0)
            time.sleep(1)
        page.wait("!document.querySelector('#step-review').hidden", 900)

        frames.append((page.shot("#step-review"), 3.2, "5: review, to confirm"))
        for cat, label in (("traced", "linked"), ("untraced", "left as typed")):
            page.js(f"document.querySelector('.tabs button[data-cat=\"{cat}\"]').click(); true")
            frames.append((page.shot("#step-review"), 2.0, f"5: review, {label}"))
        page.js("document.querySelector('.tabs button[data-cat=\"check\"]').click(); true")

        page.js("document.querySelector('#apply').click(); true")
        page.wait("!document.querySelector('#step-done').hidden", 120)
        frames.append((page.shot("#step-done"), 3.5, "6: download for Overleaf"))
        sid = page.js("location.hash.slice(1)")
    finally:
        chrome.terminate()

    width = 960
    imgs = [
        f.resize((width, round(f.height * width / f.width)), Image.LANCZOS) for f, _, _ in frames
    ]
    for i, im in enumerate(imgs):
        im.save(out / f"frame_{i:02d}.png")
    pal = imgs[-4].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    gif = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    gif[0].save(out / "provenum_demo.gif", save_all=True, append_images=gif[1:], loop=0,
                duration=[round(1000 * s) for _, s, _ in frames], optimize=True)  # fmt: skip
    (out / "frames.json").write_text(json.dumps({"session": sid, "frames": [
        {"file": f"frame_{i:02d}.png", "seconds": s, "shows": what}
        for i, (_, s, what) in enumerate(frames)]}, indent=1), encoding="utf-8")  # fmt: skip
    print(out / "provenum_demo.gif", len(frames), "frames")


if __name__ == "__main__":
    main()
