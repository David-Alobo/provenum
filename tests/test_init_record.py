import tomllib

import pytest

import provenum
from provenum.cli import main
from provenum.macros import generate, load_specs
from provenum.scaffold import scaffold


@pytest.fixture
def tables(tmp_path):
    d = tmp_path / "tables"
    d.mkdir()
    (d / "summary.csv").write_text(
        "engine,arm,top1,top1_low,top1_high,n\n"
        "vina,baseline,0.463,0.416,0.510,428\nvina,box2,0.530,0.483,0.577,428\n"
    )
    (d / "comparisons.csv").write_text(
        "engine,arm,label,delta_pts,delta_low,delta_high,p_holm,auroc,significant\n"
        "vina,box2,2 A box,6.8,3.5,10.0,0.00041,0.83,True\n"
        "vina,box6,6 A box,-2.1,-5.0,0.8,0.31,0.71,False\n"
    )
    (d / "dupes.csv").write_text("engine,value\nvina,1.5\nvina,2.5\n")
    return d


def test_scaffold_guesses_keys_and_formats(tables):
    text, n = scaffold(tables)
    assert n == 3
    spec = {t["file"]: t for t in tomllib.loads(text)["table"]}
    s, c = spec["summary.csv"], spec["comparisons.csv"]
    assert s["keys"] == ["engine", "arm"]
    assert s["default"] == "pct1" and s["formats"] == {"n": "int"}
    # The label column is not needed to identify rows; the True/False column is never a key.
    assert c["keys"] == ["engine", "arm"]
    fm = {**{k: c["default"] for k in ("delta_pts", "delta_low")}, **c.get("formats", {})}
    assert fm["delta_pts"] == "+f1" and fm["delta_low"] == "f1"
    assert fm["p_holm"] == "p" and fm["auroc"] == "f3"
    assert "# CHECK" in text  # dupes.csv has no unique key


def test_scaffolded_spec_generates_values(tables, tmp_path):
    text, _ = scaffold(tables)
    spec = tmp_path / "numbers.toml"
    spec.write_text(text, encoding="utf-8")
    out, _ = generate(load_specs(spec), tables)
    assert r"\provenumset{summary/vina/box2/top1}{53.0}" in out
    assert r"\provenumset{comparisons/vina/box2/delta_pts}{+6.8}" in out


def test_record_writes_replaces_and_generates(tmp_path):
    f = tmp_path / "tables" / "recorded.csv"
    provenum.record("vina_vs_gnina/ratio", 1.3519, fmt="f2", file=f)
    provenum.record("excluded", 16, fmt="int", file=f)
    provenum.record("vina_vs_gnina/ratio", 1.3601, fmt="f2", file=f)  # rerun: replaces
    rows = f.read_text().splitlines()
    assert rows[0] == "name,value,format,source"
    assert len(rows) == 3 and rows[1].startswith("excluded,")  # sorted by name
    assert rows[2].endswith(",test_init_record.py")  # the file that recorded it

    text, _ = scaffold(tmp_path / "tables")
    spec = tmp_path / "numbers.toml"
    spec.write_text(text, encoding="utf-8")
    out, n = generate(load_specs(spec), tmp_path / "tables")
    assert n == 2
    assert r"\provenumset{recorded/vina_vs_gnina/ratio}{1.36}" in out
    assert r"\provenumset{recorded/excluded}{16}" in out


@pytest.mark.parametrize(
    "name, value, fmt",
    [("has space", 1, "f1"), ("a//b", 1, "f1"), ("ok", float("nan"), "f1"), ("ok", 1, "nope")],
)
def test_record_rejects_bad_input(tmp_path, name, value, fmt):
    with pytest.raises(ValueError):
        provenum.record(name, value, fmt=fmt, file=tmp_path / "r.csv")


def test_record_uses_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVENUM_RECORD", str(tmp_path / "env.csv"))
    assert provenum.record("x", 1.5, fmt="f1") == tmp_path / "env.csv"


def test_cli_init_does_not_overwrite(tables, tmp_path):
    out = tmp_path / "numbers.toml"
    assert main(["init", str(tables), "--out", str(out)]) == 0
    assert main(["init", str(tables), "--out", str(out)]) == 1
    assert main(["init", str(tables), "--out", str(out), "--force"]) == 0
