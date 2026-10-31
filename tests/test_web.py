import http.client
import io
import json
import threading
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

import pytest

from provenum.web.server import App, handler, model_host, remove_stale
from provenum.web.session import MARKER, Session, SessionError, _readable, categorise, unpack


def test_readable_sentence_drops_latex_markup_but_keeps_the_mark():
    s = r"Within 2~\AA{} for [[46.3]]\% of complexes, \pbvalid{} in \emph{all} ($n=428$)."
    assert _readable(s) == "Within 2 Å for [[46.3]]% of complexes, pbvalid in all (n=428)."


MAIN = r"""\documentclass{article}
\begin{document}
\input{sections/results}
\end{document}
"""
RESULTS = r"""Vina's success rose to 53.0\% with the 2~\AA{} box, against 46.3\% at baseline.
Both engines reached 53.0\% in one arm. The buffer was at pH 7.4.
"""
SUMMARY = "engine,arm,top1\nvina,baseline,0.463\nvina,box2,0.530\ngnina,box2,0.530\n"


def _zip(files: dict[str, str], folder: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(folder + name, text)
    return buf.getvalue()


@pytest.fixture
def session(tmp_path):
    s = Session.create(
        _zip({"main.tex": MAIN, "sections/results.tex": RESULTS}, "paper/"), tmp_path / "s"
    )
    s.set_tables(data=_zip({"summary.csv": SUMMARY}))
    return s


def test_create_finds_main_file_and_strips_the_top_folder(session):
    assert session.main == "main.tex"
    assert session.tex_files == ["main.tex", "sections/results.tex"]
    assert session.n_tables == 1 and session.n_values == 3


def test_unpack_refuses_paths_outside_the_folder(tmp_path):
    with pytest.raises(SessionError, match="unsafe"):
        unpack(_zip({"../evil.tex": "x"}), tmp_path)
    with pytest.raises(SessionError, match="not a zip"):
        unpack(b"plain text", tmp_path)


def test_bad_spec_is_reported_not_raised(session):
    with pytest.raises(SessionError, match="spec problem"):
        session.set_spec('[[table]]\nfile = "missing.csv"\nkeys = ["engine"]\n')


def test_without_a_model_every_matched_number_goes_to_review(session):
    session.anchor(None)
    by_written = {it["written"]: it for it in session.items}
    assert set(by_written) == {"53.0", "46.3", "7.4"}
    assert by_written["46.3"]["category"] == "check"
    assert by_written["46.3"]["selected"] is None
    assert by_written["7.4"]["category"] == "untraced"


def test_model_choice_and_same_value_cells(session):
    def ask(item, candidates):
        return candidates[0]

    session.anchor(ask)
    first, baseline = session.items[0], session.items[1]
    assert first["written"] == "53.0" and first["category"] == "check"  # vina and gnina box2
    assert len(first["candidates"]) == 2
    assert baseline["category"] == "traced"
    assert baseline["selected"] == "summary/vina/baseline/top1"


def test_categorise_explains_format_differences():
    cat, reason = categorise("53", [{"path": "p", "text": "53.0", "fits": False}], None, True)
    assert cat == "untraced" and "53.0" in reason


def test_model_pick_that_prints_differently_is_not_preselected():
    cands = [
        {"path": "a", "text": "0.530", "fits": False},
        {"path": "b", "text": "0.53", "fits": True},
    ]
    cat, reason = categorise("0.53", cands, "a", True)
    assert cat == "untraced" and "0.530" in reason
    assert categorise("0.53", cands, "b", True)[0] == "traced"


def test_apply_links_accepted_numbers_and_keeps_the_original(session):
    session.anchor(None)
    keys = {it["written"]: it["key"] for it in session.items}
    summary = session.apply({keys["46.3"]: "summary/vina/baseline/top1"})
    assert summary["replaced"] == 1 and summary["input_added"]
    text = (session.root / "out/sections/results.tex").read_text(encoding="utf-8")
    assert r"\val{summary/vina/baseline/top1}" in text and "53.0" in text
    assert "46.3" in (session.project / "sections/results.tex").read_text(encoding="utf-8")
    assert r"\input{numbers}" in (session.root / "out/main.tex").read_text(encoding="utf-8")
    names = zipfile.ZipFile(session.root / "project.zip").namelist()
    assert {"main.tex", "numbers.tex", "numbers.toml", "sections/results.tex"} <= set(names)
    assert "Linked (1)" in (session.root / "report.html").read_text(encoding="utf-8")


def test_apply_rejects_a_cell_that_was_not_offered(session):
    session.anchor(None)
    key = session.items[0]["key"]
    with pytest.raises(SessionError, match="not a matching cell"):
        session.apply({key: "summary/vina/baseline/top1"})


def test_http_workflow_end_to_end(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(App(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, data=None, method=None, ctype="application/json"):
        req = urllib.request.Request(
            base + path, data=data, method=method, headers={"Content-Type": ctype}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    try:
        assert b"provenum" in call("/")
        assert b"export function" in call("/review.js")
        r = json.loads(
            call(
                "/api/session",
                _zip({"main.tex": MAIN.replace(r"\input{sections/results}", RESULTS)}),
                ctype="application/zip",
            )
        )
        sid = r["id"]
        call(f"/api/session/{sid}/tables", _zip({"summary.csv": SUMMARY}), ctype="application/zip")
        call(f"/api/session/{sid}/run", json.dumps({"model": ""}).encode())
        for _ in range(100):
            state = json.loads(call(f"/api/session/{sid}"))
            if state["run"]["status"] != "running":
                break
            threading.Event().wait(0.05)
        assert state["run"]["status"] == "done"
        key = next(it["key"] for it in state["items"] if it["written"] == "46.3")
        call(
            f"/api/session/{sid}/apply",
            json.dumps({"decisions": {key: "summary/vina/baseline/top1"}}).encode(),
        )
        z = zipfile.ZipFile(io.BytesIO(call(f"/api/session/{sid}/download/project.zip")))
        assert r"\val{summary/vina/baseline/top1}" in z.read("main.tex").decode()
        with pytest.raises(urllib.error.HTTPError):
            call("/../pyproject.toml")
    finally:
        server.shutdown()


@pytest.fixture
def live(tmp_path):
    """A running server: yields (app, request function returning (status, headers, body))."""
    app = App(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        conn.close()
        return out

    def new_session():
        status, _, body = request("POST", "/api/session", _zip({"main.tex": MAIN}),
                                  {"Content-Type": "application/zip"})  # fmt: skip
        assert status == 200
        return json.loads(body)["id"]

    request.new_session = new_session
    request.port = port
    yield app, request
    server.shutdown()


def test_session_ids_are_long_random_tokens(live):
    _, request = live
    ids = {request.new_session() for _ in range(3)}
    assert len(ids) == 3 and all(len(i) >= 32 for i in ids)


def test_foreign_host_header_is_refused(live):
    # DNS rebinding: a page on evil.example resolved to 127.0.0.1 sends Host: evil.example
    _, request = live
    status, _, _ = request("GET", "/", headers={"Host": "evil.example:80"})
    assert status == 403


def test_cross_site_requests_are_refused(live):
    _, request = live
    sid = request.new_session()
    body = json.dumps({"model": "m", "host": "http://evil.example"}).encode()
    # a form on another site can only send text/plain (no preflight)
    status, _, _ = request("POST", f"/api/session/{sid}/run", body, {"Content-Type": "text/plain"})
    assert status == 415
    status, _, _ = request(
        "POST", f"/api/session/{sid}/run", body,
        {"Content-Type": "application/json", "Origin": "https://evil.example"},
    )  # fmt: skip
    assert status == 403
    status, _, _ = request("PUT", f"/api/session/{sid}/spec", b"x", {"Content-Type": "text/plain"})
    assert status == 415


def test_model_host_must_be_http(live):
    _, request = live
    sid = request.new_session()
    request("POST", f"/api/session/{sid}/tables", _zip({"summary.csv": SUMMARY}),
            {"Content-Type": "application/zip"})  # fmt: skip
    body = json.dumps({"model": "m", "host": "file:///C:/Windows/win.ini"}).encode()
    status, _, out = request("POST", f"/api/session/{sid}/run", body,
                             {"Content-Type": "application/json"})  # fmt: skip
    assert status == 400 and b"http" in out


def test_security_headers_on_every_response(live):
    _, request = live
    for path in ("/", "/app.js", "/api/session/" + "x" * 32):
        _, headers, _ = request("GET", path)
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"


def test_delete_removes_the_files(live):
    app, request = live
    sid = request.new_session()
    root = app.sessions[sid].root
    assert root.exists()
    status, _, _ = request("DELETE", f"/api/session/{sid}")
    assert status == 200 and not root.exists()
    assert request("GET", f"/api/session/{sid}")[0] == 404


def test_idle_sessions_are_swept(live):
    app, request = live
    sid = request.new_session()
    root = app.sessions[sid].root
    app.ttl = -1  # every session is idle
    request("GET", "/")
    assert sid not in app.sessions and not root.exists()


def test_stale_directories_from_an_earlier_run_are_removed(tmp_path):
    old = tmp_path / "provenum-old"
    old.mkdir()
    (old / MARKER).write_text("x")
    other = tmp_path / "provenum-not-ours"
    other.mkdir()
    assert remove_stale(tmp_path, ttl=-1) == 1
    assert not old.exists() and other.exists()


def test_spec_cannot_read_outside_the_tables_folder(session, tmp_path):
    (tmp_path / "secret.csv").write_text("k,v\na,1.5\n")
    good = session.spec_text
    with pytest.raises(SessionError, match="outside the tables folder"):
        session.set_spec('[[table]]\nfile = "../../secret.csv"\nkeys = ["k"]\n')
    assert session.spec_text == good
    assert "secret" not in (session.root / "numbers.toml").read_text()


@pytest.mark.parametrize("name", ["C:evil.tex", "a.tex:stream", "a\x01.tex", "/etc/x.tex"])
def test_unpack_refuses_drive_stream_and_control_names(tmp_path, name):
    with pytest.raises(SessionError, match="unsafe"):
        unpack(_zip({name: "x"}), tmp_path)


def test_model_host_check():
    assert model_host(" http://127.0.0.1:11434/ ") == "http://127.0.0.1:11434"
    for bad in ("file:///etc/passwd", "ftp://x", "http://", "127.0.0.1:11434"):
        with pytest.raises(SessionError):
            model_host(bad)
