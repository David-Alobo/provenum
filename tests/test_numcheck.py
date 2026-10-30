import pytest

from numcheck.anchor import judge, values
from numcheck.macros import TableSpec, fmt, generate, lint
from numcheck.migrate import migrate


@pytest.mark.parametrize(
    "value, how, expected",
    [
        (0.53037, "pct1", "53.0"),
        (6.776, "+f1", "+6.8"),
        (-1.86, "f1", r"\ensuremath{-}1.9"),
        (0.000413, "p", r"\ensuremath{4.1 \times 10^{-4}}"),
        (0.2, "p", "0.20"),
        (41.0, "int", "41"),
    ],
)
def test_fmt(value, how, expected):
    assert fmt(value, how) == expected


@pytest.fixture
def project(tmp_path):
    (tmp_path / "summary.csv").write_text(
        "engine,run,top1\nvina,baseline,0.46262\nvina,box2,0.53037\n"
    )
    spec = [TableSpec("summary.csv", ["engine", "run"], default="pct1")]
    tex = tmp_path / "paper.tex"
    tex.write_text("Success rose from 46.3\\% to 53.0\\% and then to 99.9\\%.\n", newline="\n")
    return tmp_path, spec, tex


def test_generate_defines_every_cell(project):
    root, spec, _ = project
    text, n = generate(spec, root)
    assert n == 2
    assert r"\numcheckset{summary/vina/box2/top1}{53.0}" in text


def test_judge_traces_and_flags(project):
    root, spec, _ = project
    table = values(spec, root)
    assert judge("53.0", "summary/vina/box2/top1", table) == "traced"
    assert judge("53.3", "summary/vina/box2/top1", table) == "mismatch"
    assert judge("53.0", "summary/vina/box9/top1", table) == "bad-path"
    assert judge("53.0", None, table) == "unanchored"


def test_migrate_replaces_only_checked_numbers_and_keeps_line_endings(project):
    root, spec, tex = project
    table = values(spec, root)
    answers = [
        {"id": 0, "path": "summary/vina/baseline/top1"},
        {"id": 1, "path": "summary/vina/box2/top1"},
        {"id": 2, "path": "summary/vina/box2/top1"},
    ]  # 99.9 is wrong: must stay
    report = migrate(tex, answers, table)
    out = tex.read_bytes().decode()
    assert r"\val{summary/vina/baseline/top1}" in out and r"\val{summary/vina/box2/top1}" in out
    assert "99.9" in out and "\r\n" not in out
    assert [r["status"] for r in report] == ["replaced", "replaced", "mismatch"]
    assert lint(tex) == [(1, "99.9", out.strip())]
