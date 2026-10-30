import pytest

from provenum.cli import main
from provenum.diff import read_values
from provenum.guards import check, check_guard
from provenum.macros import lint

VALUES = r"""
\provenumset{s/base}{46.3}
\provenumset{s/box2}{53.0}
\provenumset{c/box2/delta}{+6.8}
\provenumset{c/box6/delta}{\ensuremath{-}2.1}
\provenumset{c/box2/p_holm}{\ensuremath{4.1 \times 10^{-4}}}
\provenumset{c/box6/p_holm}{0.31}
"""
V = read_values(VALUES)


@pytest.mark.parametrize(
    "guard, path, fails",
    [(">0", "c/box2/delta", False), (">0", "c/box6/delta", True), ("<0.05", "c/box2/p_holm", False),
     ("<0.05", "c/box6/p_holm", True), (">=40,<=50", "s/base", False), (">s/base", "s/box2", False),
     ("<s/base", "s/box2", True), ("~0", "s/base", True), (">0", "missing/path", True)],
)  # fmt: skip
def test_check_guard(guard, path, fails):
    assert (check_guard(guard, path, V) is not None) == fails


def run(tmp_path, text):
    f = tmp_path / "paper.tex"
    f.write_text(text, encoding="utf-8")
    return [x.message for x in check([f], V)]


def test_failed_guard_is_reported(tmp_path):
    msgs = run(tmp_path, r"The 6 box helped (\val[>0]{c/box6/delta} points).")
    assert msgs == ["guard [>0] fails: c/box6/delta is -2.1"]


@pytest.mark.parametrize(
    "text",
    [
        r"Success fell from \val{s/base}\% to \val{s/box2}\%.",
        r"Success rose with the 6 box (\val{c/box6/delta} points).",
        r"The 6 box was significant (Holm $p = \val{c/box6/p_holm}$).",
        r"The 2 box did not change success significantly (Holm $p = \val{c/box2/p_holm}$).",
    ],
)
def test_wording_contradicting_the_values_is_flagged(tmp_path, text):
    assert len(run(tmp_path, text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        r"Success rose from \val{s/base}\% to \val{s/box2}\% (\val{c/box2/delta} points).",
        r"Success fell with the 6 box (\val{c/box6/delta} points).",
        # A sequence, not "declined by": the first change after "declined" belongs to "from".
        (
            r"Its effect declined as the box grew, from \val{c/box2/delta} points at 2 to "
            r"\val{c/box6/delta} at 6."
        ),
        # Negation several words before the adverb.
        r"The 6 box did not change its success significantly (Holm $p = \val{c/box6/p_holm}$).",
        # Mixed claims: the negated mention has no p-value after it.
        (
            r"The 2 box was the only significant arm (Holm $p = \val{c/box2/p_holm}$), and no "
            r"arm was significant for Gnina."
        ),
        r"A guarded value \val[>0]{c/box2/delta} that holds.",
    ],
)
def test_consistent_wording_is_not_flagged(tmp_path, text):
    assert run(tmp_path, text) == []


def test_lint_ignores_guards(tmp_path):
    f = tmp_path / "paper.tex"
    f.write_text(r"A guarded value \val[<0.05]{c/box2/p_holm} and a typed 6.8 points." + "\n")
    assert [number for _, number, _ in lint(f)] == ["6.8"]


def test_cli_exit_codes(tmp_path, capsys):
    (tmp_path / "numbers.tex").write_text(VALUES, encoding="utf-8")
    paper = tmp_path / "paper.tex"
    base = ["check", str(paper), "--values", str(tmp_path / "numbers.tex")]
    paper.write_text(r"Success rose with the 6 box (\val{c/box6/delta} points)." + "\n")
    assert main(base) == 0  # wording is a warning
    assert main([*base, "--strict"]) == 1
    paper.write_text(r"It helped (\val[>0]{c/box6/delta} points)." + "\n")
    assert main(base) == 1  # a failed guard is an error
    assert "1 failed guard(s)" in capsys.readouterr().out
