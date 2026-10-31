"""A local web app for the whole workflow, on the standard library's HTTP server.

Routes (JSON unless noted):
    GET  /                                 the page (static/)
    POST /api/session                      body: zipped LaTeX project -> {id, state}
    GET  /api/session/<id>                 state, including run progress
    POST /api/session/<id>/tables          body: zip of CSVs, or JSON {"folder": ...}
    PUT  /api/session/<id>/spec            body: TOML text
    POST /api/session/<id>/run             JSON {"model", "host", "notes"}; model "" = no model
    POST /api/session/<id>/apply           JSON {"decisions": {key: path | null}}
    GET  /api/session/<id>/download/<f>    project.zip, numbers.toml or report.html
    GET  /api/models?host=...              models installed in Ollama

Manuscripts stay on this machine: the only outbound requests go to the Ollama host chosen.
"""

import json
import mimetypes
import re
import threading
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from provenum.llm import choose
from provenum.web.session import Session, SessionError, new_root, to_json

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 2**20
DOWNLOADS = {"project.zip": "application/zip", "numbers.toml": "text/plain; charset=utf-8",
             "report.html": "text/html; charset=utf-8"}  # fmt: skip
ROUTE = re.compile(r"^/api/session/([a-z0-9_-]+)(?:/(tables|spec|run|apply|download/[\w.]+))?$")


class App:
    """Sessions held in memory, each with its own directory."""

    def __init__(self, base: Path | None = None) -> None:
        """
        Args:
            base (Path | None): Where session directories go (default: system temp).
        """
        self.base = base
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def start_run(self, sid: str, model: str, host: str, notes: str) -> None:
        """
        Anchor every number in a background thread, updating the session's progress.

        Args:
            sid (str): Session id.
            model (str): Ollama model name, or "" to skip the model.
            host (str): Ollama base URL.
            notes (str): Project notes on vocabulary for the model.
        """
        s = self.sessions[sid]
        s.run = {"status": "running", "done": 0, "total": 0, "model": model or None}

        def ask(item: dict, candidates: list[str]) -> str | None:
            return choose(item, candidates, notes, model, host)

        def progress(done: int, total: int) -> None:
            s.run.update(done=done, total=total)

        def work() -> None:
            try:
                s.anchor(ask if model else None, progress)
                s.run["status"] = "done"
            except OSError as err:
                s.run.update(status="error", error=f"could not reach the model at {host}: {err}")
            except Exception as err:  # noqa: BLE001 - shown on the page, not lost in a thread
                s.run.update(status="error", error=f"{type(err).__name__}: {err}")

        threading.Thread(target=work, daemon=True).start()


def ollama_models(host: str) -> list[str]:
    """
    Names of the models installed on an Ollama server.

    Args:
        host (str): Ollama base URL.

    Returns:
        list[str]: Model names (empty if the server cannot be reached).
    """
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=5) as r:
            return sorted(m["name"] for m in json.loads(r.read())["models"])
    except (OSError, ValueError, KeyError):
        return []


def handler(app: App) -> type[BaseHTTPRequestHandler]:
    """
    A request handler class bound to one App.

    Args:
        app (App): Application state.

    Returns:
        type[BaseHTTPRequestHandler]: Handler class for ThreadingHTTPServer.
    """

    class Handler(BaseHTTPRequestHandler):
        """Routes requests to the session workflow."""

        def log_message(self, format: str, *args: object) -> None:
            """Keep the console quiet apart from errors."""

        def _send(self, status: int, body: bytes, ctype: str = "application/json",
                  extra: dict | None = None) -> None:  # fmt: skip
            """
            Write a response.

            Args:
                status (int): HTTP status.
                body (bytes): Body.
                ctype (str): Content type.
                extra (dict | None): Further headers.
            """
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            """
            Write a JSON error.

            Args:
                status (int): HTTP status.
                message (str): Shown to the researcher.
            """
            self._send(status, to_json({"error": message}))

        def _body(self) -> bytes:
            """
            Read the request body.

            Returns:
                bytes: Body.

            Raises:
                SessionError: If the body is larger than the upload limit.
            """
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise SessionError("upload larger than 200 MB")
            return self.rfile.read(n)

        def _session(self, sid: str) -> Session | None:
            """
            Look up a session, answering 404 if it does not exist.

            Args:
                sid (str): Session id.

            Returns:
                Session | None: The session, or None (response already sent).
            """
            s = app.sessions.get(sid)
            if s is None:
                self._error(HTTPStatus.NOT_FOUND, "session not found; upload the project again")
            return s

        def do_GET(self) -> None:
            """Serve the page, static files, state, downloads and the model list."""
            path, _, query = self.path.partition("?")
            if path == "/":
                path = "/index.html"
            if path == "/api/models":
                host = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get(
                    "host", "http://127.0.0.1:11434"
                )
                host = urllib.request.unquote(host)
                self._send(HTTPStatus.OK, to_json({"models": ollama_models(host)}))
                return
            m = ROUTE.match(path)
            if m:
                s = self._session(m.group(1))
                if s is None:
                    return
                action = m.group(2) or ""
                if not action:
                    self._send(HTTPStatus.OK, to_json(s.state()))
                elif action.startswith("download/") and action[9:] in DOWNLOADS:
                    f = s.root / action[9:]
                    if not f.exists():
                        self._error(HTTPStatus.NOT_FOUND, "apply the review first")
                        return
                    self._send(
                        HTTPStatus.OK,
                        f.read_bytes(),
                        DOWNLOADS[action[9:]],
                        {"Content-Disposition": f'attachment; filename="{action[9:]}"'},
                    )
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            f = (STATIC / path.lstrip("/")).resolve()
            if f.parent != STATIC.resolve() or not f.is_file():
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or f.suffix == ".js":
                ctype = ("text/javascript" if f.suffix == ".js" else ctype) + "; charset=utf-8"
            self._send(HTTPStatus.OK, f.read_bytes(), ctype)

        def do_POST(self) -> None:
            """Create a session, set tables, start a run or apply decisions."""
            try:
                body = self._body()
                if self.path == "/api/session":
                    root = new_root(app.base)
                    s = Session.create(body, root)
                    sid = root.name.removeprefix("provenum-").lower()
                    with app.lock:
                        app.sessions[sid] = s
                    self._send(HTTPStatus.OK, to_json({"id": sid, "state": s.state()}))
                    return
                m = ROUTE.match(self.path)
                s = self._session(m.group(1)) if m else None
                if s is None:
                    if not m:
                        self._error(HTTPStatus.NOT_FOUND, "not found")
                    return
                action = m.group(2)
                if action == "tables":
                    if (self.headers.get("Content-Type") or "").startswith("application/json"):
                        s.set_tables(folder=json.loads(body).get("folder"))
                    else:
                        s.set_tables(data=body)
                elif action == "run":
                    if s.run.get("status") == "running":
                        raise SessionError("a run is already in progress")
                    opts = json.loads(body or b"{}")
                    app.start_run(m.group(1), opts.get("model", ""),
                                  opts.get("host") or "http://127.0.0.1:11434",
                                  opts.get("notes", ""))  # fmt: skip
                elif action == "apply":
                    s.apply(json.loads(body).get("decisions", {}))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                    return
                self._send(HTTPStatus.OK, to_json(s.state()))
            except SessionError as err:
                self._error(HTTPStatus.BAD_REQUEST, str(err))
            except json.JSONDecodeError:
                self._error(HTTPStatus.BAD_REQUEST, "malformed request")

        def do_PUT(self) -> None:
            """Save an edited spec."""
            m = ROUTE.match(self.path)
            if not m or m.group(2) != "spec":
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            s = self._session(m.group(1))
            if s is None:
                return
            try:
                s.set_spec(self._body().decode("utf-8"))
                s.items, s.applied = [], None
                self._send(HTTPStatus.OK, to_json(s.state()))
            except SessionError as err:
                self._error(HTTPStatus.BAD_REQUEST, str(err))

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, base: Path | None = None) -> None:
    """
    Run the web app until interrupted.

    Args:
        host (str): Interface to listen on (keep 127.0.0.1 unless behind a trusted proxy).
        port (int): Port.
        base (Path | None): Where session directories go.
    """
    server = ThreadingHTTPServer((host, port), handler(App(base)))
    print(f"provenum web app on http://{host}:{port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
