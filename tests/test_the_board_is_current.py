"""The status board, held against the repository and against itself.

`docs/harness-status.md` is the one document a reader is told to trust without
reading the code (README, "what exists now"), and it is generated - so there
are two ways it can lie: by being older than the repository it describes, and
by printing a number that contradicts the table under it. Both are checked
here, and both are the same rule the views obey: a generated document is the
command's output, never an edit.

One property is checked that no test can see in a passing board: the board must
not describe the machine that built it (invariant F14). A clone called
`corpus` in CI, `intl` in one checkout and anything else elsewhere has to print
the *project's* name, or the same repository produces three different documents
and none of them says which project it is about; `d22` cannot catch that,
because a directory name is not an absolute path.
"""
import re
import shutil

from harness import report
from support import ROOT

SOURCES_SUMMARY = re.compile(r"^- sources: (\d+) — (\d+) built", re.M)
SOURCES_HEADING = "## Sources, and what is built from each"

# Rendering the board runs every probe, so it is done once for the whole file
# rather than once per test.
BOARD = report.render(ROOT)


def _table_rows(text):
    """The source table, as (id, state) pairs, read from the rendered board.

    Read from under its own heading rather than by the shape of a line. A row of a
    four-column table is six pipe-separated cells like a source row, so a reader
    that took any such line would count another section's rows as sources - which
    is what the table of what the control holds and leaves, whose first cell is a
    backticked job name, did the moment it was added.
    """
    rows = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == SOURCES_HEADING
            continue
        if not inside:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) == 6 and cells[1].startswith("`") and cells[1].endswith("`"):
            rows.append((cells[1].strip("`"), cells[4]))
    return rows


def test_the_committed_board_is_what_the_command_writes():
    """`python -m harness report` is the only author of this file."""
    committed = (ROOT / "docs" / "harness-status.md").read_text(encoding="utf-8")
    assert committed == BOARD, (
        "docs/harness-status.md is not what `python -m harness --write` "
        "writes now: regenerate it rather than editing it")


def test_the_summary_counts_the_table_below_it():
    """Every number in the summary is a count of rows the board itself shows.

    The line said `4 built` while the table printed five rows whose state
    begins with `built`, because a family that published 103 of its 110
    documents was counted as not built. A reader had to reconcile the two by
    hand; this test does not let the two drift apart again.
    """
    text = BOARD
    summary = SOURCES_SUMMARY.search(text)
    assert summary, "the board no longer prints a sources summary line"
    declared, built = (int(g) for g in summary.groups())
    rows = _table_rows(text)
    assert declared == len(rows), "the summary counts sources the table does not list"
    assert built == sum(1 for _, state in rows if state.startswith("built")), (
        "the summary's built count is not the table's")
    in_part = [name for name, state in rows if state.startswith("built") and "unread" in state]
    if in_part:
        assert all(f"`{name}` in part" in text for name in in_part), (
            "a family built in part is not named as such in the summary")


def test_a_probe_appended_to_the_catalogue_does_not_break_the_reading_order():
    """The board reads in catalogue-number order, not in file order.

    `d24` was appended after `d26`, and the table listed the probes in the order
    the entries sit in the file. The ids carry an ordinal, so the board sorts by
    it, and stays a function of the set of probes rather than of where each one
    was written.
    """
    ids = [row["id"] for row in report.probe_rows(ROOT)]
    heads = [i.partition("-")[0] for i in ids]
    assert heads == sorted(heads, key=lambda h: int(h[1:]) if h[1:].isdigit() else 10**6)


def test_the_board_names_the_project_not_the_directory(tmp_path):
    """F14: an artefact must not describe the machine that built it."""
    clone = tmp_path / "a-clone-called-something-else"
    (clone / "docs").mkdir(parents=True)
    shutil.copy(ROOT / "pyproject.toml", clone / "pyproject.toml")
    text = report.render(clone)
    assert "a-clone-called-something-else" not in text
    assert "`international-tax-law-corpus`" in text


def test_a_clone_with_no_manifest_still_names_the_project(tmp_path):
    """The fallback is the project's name too, never the empty directory's."""
    text = report.render(tmp_path)
    assert tmp_path.name not in text
    assert report.PROJECT_NAME in text
