"""A local web app for the whole workflow, on the standard library's HTTP server.

Routes (JSON unless noted):
    GET    /                                 the page (static/)
    POST   /api/session                      body: zipped LaTeX project -> {id, state}
    GET    /api/session/<id>                 state, including run progress
    DELETE /api/session/<id>                 delete the session and its files
    POST   /api/session/<id>/tables          body: zip of CSVs, or JSON {"folder": ...}
    PUT    /api/session/<id>/spec            body: TOML text (Content-Type application/toml)
    POST   /api/session/<id>/run             JSON {"model", "host", "notes"}; model "" = no model
    POST   /api/session/<id>/apply           JSON {"decisions": {key: path | null}}
    GET    /api/session/<id>/download/<f>    project.zip, numbers.toml or report.html
    GET    /api/models?host=...              models installed in Ollama

Manuscripts stay on this machine: the only outbound requests go to the Ollama host chosen.

Requests from other websites are refused: the Host header must name this server (which also
defeats DNS rebinding), a request that changes anything must come from this page's origin, and
every body must carry a JSON, zip or TOML content type, which a cross-site form cannot send
without a preflight this server never answers. Session ids are 192-bit random tokens, and a
session's files are deleted when it is deleted or has been idle for `ttl` seconds.
"""

import json
import mimetypes
import re
import secrets
import shutil
import threading
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from provenum.llm import choose
from provenum.web.session import MARKER, Session, SessionError, new_root, to_json

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 2**20
DEFAULT_TTL = 6 * 3600  # seconds a session may sit idle before its files are deleted
DOWNLOADS = {"project.zip": "application/zip", "numbers.toml": "text/plain; charset=utf-8",
             "report.html": "text/html; charset=utf-8"}  # fmt: skip
ROUTE = re.compile(
    r"^/api/session/([A-Za-z0-9_-]{16,64})(?:/(tables|spec|run|apply|download/[\w.]+))?$"
)
BODY_TYPES = {"run": ("application/json",), "apply": ("application/json",),
              "tables": ("application/json", "application/zip"), "spec": ("application/toml",),
              "": ("application/zip",)}  # fmt: skip
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def model_host(url: str) -> str:
    """
    Check a model server URL: http or https with a host name, nothing else.

    Args:
        url (str): URL as entered on the page.

    Returns:
        str: The URL without a trailing slash.

    Raises:
        SessionError: For other schemes (file:, ftp:, ...) or a URL without a host.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SessionError("the model server must be an http:// or https:// address")
    return url.strip().rstrip("/")


class App:
    """Sessions held in memory, each with its own directory."""

    def __init__(self, base: Path | None = None, ttl: float = DEFAULT_TTL,
                 allow_hosts: tuple[str, ...] = ()) -> None:  # fmt: skip
        """
        Args:
            base (Path | None): Where session directories go (default: system temp).
            ttl (float): Seconds a session may sit idle before it is deleted.
            allow_hosts (tuple[str, ...]): Extra Host header values to accept (host:port),
                e.g. the name a reverse proxy forwards.
        """
        self.base = base
        self.ttl = ttl
        self.allow_hosts = set(allow_hosts)
        self.sessions: dict[str, Session] = {}
        self.used: dict[str, float] = {}
        self.lock = threading.Lock()

    def add(self, s: Session) -> str:
        """
        Register a session under a new random id.

        Args:
            s (Session): The session.

        Returns:
            str: Its id (32 URL-safe characters, 192 random bits).
        """
        sid = secrets.token_urlsafe(24)
        with self.lock:
            self.sessions[sid] = s
            self.used[sid] = time.monotonic()
        return sid

    def get(self, sid: str) -> Session | None:
        """
        Look up a session and mark it as used.

        Args:
            sid (str): Session id.

        Returns:
            Session | None: The session, or None.
        """
        with self.lock:
            s = self.sessions.get(sid)
            if s is not None:
                self.used[sid] = time.monotonic()
        return s

    def delete(self, sid: str) -> bool:
        """
        Forget a session and delete its files.

        Args:
            sid (str): Session id.

        Returns:
            bool: Whether the session existed.
        """
        with self.lock:
            s = self.sessions.pop(sid, None)
            self.used.pop(sid, None)
        if s is None:
            return False
        shutil.rmtree(s.root, ignore_errors=True)
        return True

    def sweep(self) -> int:
        """
        Delete sessions idle for longer than the ttl (a running model keeps its session alive).

        Returns:
            int: Number of sessions deleted.
        """
        now = time.monotonic()
        with self.lock:
            old = [
                sid
                for sid, t in self.used.items()
                if now - t > self.ttl and self.sessions[sid].run.get("status") != "running"
            ]
        return sum(self.delete(sid) for sid in old)  # fmt: skip

    def start_run(self, sid: str, model: str, host: str, notes: str) -> None:
        """
        Anchor every number in a background thread, updating the session's progress.

        Args:
            sid (str): Session id.
            model (str): Ollama model name, or "" to skip the model.
            host (str): Ollama base URL (checked with `model_host`).
            notes (str): Project notes on vocabulary for the model.
        """
        s = self.sessions[sid]
        s.run = {"status": "running", "done": 0, "total": 0, "model": model or None}

        def ask(item: dict, candidates: list[str]) -> str | None:
            return choose(item, candidates, notes, model, host)

        def progress(done: int, total: int) -> None:
            s.run.update(done=done, total=total)
            with self.lock:
                self.used[sid] = time.monotonic()

        def work() -> None:
            try:
                s.anchor(ask if model else None, progress)
                s.run["status"] = "done"
            except OSError as err:
                s.run.update(status="error", error=f"could not reach the model at {host}: {err}")
            except Exception as err:  # noqa: BLE001 - shown on the page, not lost in a thread
                s.run.update(status="error", error=f"{type(err).__name__}: {err}")

        threading.Thread(target=work, daemon=True).start()


def remove_stale(base: Path | None, ttl: float) -> int:
    """
    Delete session directories left by an earlier run of the server.

    Only directories carrying provenum's marker file are touched.

    Args:
        base (Path | None): Session parent directory (None: the system temp directory).
        ttl (float): Age in seconds after which a directory is deleted.

    Returns:
        int: Number of directories deleted.
    """
    import tempfile

    parent = base or Path(tempfile.gettempdir())
    n = 0
    for d in parent.glob("provenum-*"):
        marker = d / MARKER
        if marker.is_file() and time.time() - marker.stat().st_mtime > ttl:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def ollama_models(host: str) -> list[str]:
    """
    Names of the models installed on an Ollama server.

    Args:
        host (str): Ollama base URL (checked with `model_host`).

    Returns:
        list[str]: Model names (empty if the server cannot be reached).
    """
    try:
        with urllib.request.urlopen(f"{model_host(host)}/api/tags", timeout=5) as r:
            return sorted(m["name"] for m in json.loads(r.read())["models"])
    except (OSError, ValueError, KeyError, SessionError):
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
            Write a response, with the security headers.

            Args:
                status (int): HTTP status.
                body (bytes): Body.
                ctype (str): Content type.
                extra (dict | None): Further headers.
            """
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {**HEADERS, **(extra or {})}.items():
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

        def _trusted(self, changes: bool, action: str | None = None) -> bool:
            """
            Refuse requests that may come from another website, answering them.

            Args:
                changes (bool): Whether the request changes anything (POST, PUT, DELETE).
                action (str | None): Route action, to look up the body types it accepts.

            Returns:
                bool: True if the request may proceed (otherwise a response was sent).
            """
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", *app.allow_hosts}
            host = self.headers.get("Host", "")
            if host not in hosts:
                self._error(HTTPStatus.FORBIDDEN, f"unexpected Host header {host!r}")
                return False
            if not changes:
                return True
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{h}" for h in hosts} | {
                f"https://{h}" for h in app.allow_hosts
            }:
                self._error(HTTPStatus.FORBIDDEN, "request from another website refused")
                return False
            if action is not None:
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype not in BODY_TYPES.get(action, ()):
                    self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                                f"content type {ctype or 'none'} not accepted here")  # fmt: skip
                    return False
            return True

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
            s = app.get(sid)
            if s is None:
                self._error(HTTPStatus.NOT_FOUND, "session not found; upload the project again")
            return s

        def do_GET(self) -> None:
            """Serve the page, static files, state, downloads and the model list."""
            if not self._trusted(changes=False):
                return
            app.sweep()
            path, _, query = self.path.partition("?")
            if path == "/":
                path = "/index.html"
            if path == "/api/models":
                host = urllib.parse.parse_qs(query).get("host", ["http://127.0.0.1:11434"])[0]
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
            m = ROUTE.match(self.path)
            action = "" if self.path == "/api/session" else m.group(2) if m else None
            if action is None or action not in BODY_TYPES:
                if self._trusted(changes=True):
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            if not self._trusted(changes=True, action=action):
                return
            app.sweep()
            try:
                body = self._body()
                if action == "":
                    root = new_root(app.base)
                    try:
                        s = Session.create(body, root)
                    except SessionError:
                        shutil.rmtree(root, ignore_errors=True)
                        raise
                    sid = app.add(s)
                    self._send(HTTPStatus.OK, to_json({"id": sid, "state": s.state()}))
                    return
                s = self._session(m.group(1))
                if s is None:
                    return
                if action == "tables":
                    if self.headers.get("Content-Type", "").startswith("application/json"):
                        s.set_tables(folder=json.loads(body).get("folder"))
                    else:
                        s.set_tables(data=body)
                elif action == "run":
                    if s.run.get("status") == "running":
                        raise SessionError("a run is already in progress")
                    opts = json.loads(body or b"{}")
                    host = model_host(opts.get("host") or "http://127.0.0.1:11434")
                    app.start_run(m.group(1), opts.get("model", ""), host, opts.get("notes", ""))
                elif action == "apply":
                    s.apply(json.loads(body).get("decisions", {}))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                    return
                self._send(HTTPStatus.OK, to_json(s.state()))
            except SessionError as err:
                self._error(HTTPStatus.BAD_REQUEST, str(err))
            except (json.JSONDecodeError, AttributeError):
                self._error(HTTPStatus.BAD_REQUEST, "malformed request")

        def do_PUT(self) -> None:
            """Save an edited spec."""
            m = ROUTE.match(self.path)
            if not m or m.group(2) != "spec":
                if self._trusted(changes=True):
                    self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            if not self._trusted(changes=True, action="spec"):
                return
            s = self._session(m.group(1))
            if s is None:
                return
            try:
                s.set_spec(self._body().decode("utf-8"))
                s.items, s.applied = [], None
                self._send(HTTPStatus.OK, to_json(s.state()))
            except (SessionError, UnicodeDecodeError) as err:
                self._error(HTTPStatus.BAD_REQUEST, str(err))

        def do_DELETE(self) -> None:
            """Delete a session and its files."""
            if not self._trusted(changes=True):
                return
            m = ROUTE.match(self.path)
            if not m or m.group(2):
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            if app.delete(m.group(1)):
                self._send(HTTPStatus.OK, to_json({"deleted": True}))
            else:
                self._error(HTTPStatus.NOT_FOUND, "session not found")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, base: Path | None = None,
          ttl: float = DEFAULT_TTL, allow_hosts: tuple[str, ...] = ()) -> None:  # fmt: skip
    """
    Run the web app until interrupted.

    Args:
        host (str): Interface to listen on (keep 127.0.0.1 unless behind a trusted proxy).
        port (int): Port.
        base (Path | None): Where session directories go.
        ttl (float): Seconds a session may sit idle before its files are deleted.
        allow_hosts (tuple[str, ...]): Extra Host header values to accept (host:port).
    """
    stale = remove_stale(base, ttl)
    server = ThreadingHTTPServer((host, port), handler(App(base, ttl, allow_hosts)))
    print(f"provenum web app on http://127.0.0.1:{port} (Ctrl+C to stop)"
          + (f"; removed {stale} old session(s)" if stale else ""), flush=True)  # fmt: skip
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: listening on {host} without a login; anyone who can reach this port "
              "can upload and download manuscripts", flush=True)  # fmt: skip
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
