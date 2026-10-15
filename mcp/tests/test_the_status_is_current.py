"""The status board, held against the repository and against itself.

`docs/status.md` is the one document of this repository a reader is told to
trust without reading the code, and it is generated - so there are two ways it
can lie: by being older than the repository it describes, and by printing a
number that contradicts the table under it. Both are checked here, and both are
the same rule the fixture obeys: a generated document is the command's output,
never an edit.

Two properties are checked that no passing board can show. The board must not
describe the machine that built it: a checkout called anything at all has to
print the project's name, or one repository produces a different document on
every desk and none of them says which project it is about. And the claim this
layer makes about itself - that it reaches no network and reads no PDF - has to
be read off the package, because that is the only way a claim like it can be
refused when it stops being true.
"""

import re

from itl_mcp import drift, status

ROOT = status.ROOT

# Rendering the board reads the fixture and runs the scans, which is cheap
# enough to do once for the whole file rather than once per test.
BOARD = status.render(ROOT)

QUESTIONS = re.compile(r"^- recorded questions: (\d+) over (\d+) tools", re.M)
FACTS = re.compile(r"^- recorded facts: (\d+)", re.M)


def _table_rows(text):
    """The recorded-answers table, as (tool, questions, facts) triples."""
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) == 5 and cells[1].startswith("`") and cells[1].endswith("`"):
            rows.append((cells[1].strip("`"), int(cells[2]), int(cells[3])))
    return rows


def test_the_committed_board_is_what_the_command_writes():
    """`python -m itl_mcp.status --write` is the only author of this file."""
    committed = (ROOT / "docs" / "status.md").read_text(encoding="utf-8")
    assert committed == BOARD, (
        "docs/status.md is not what `python -m itl_mcp.status --write` writes "
        "now: regenerate it rather than editing it")


def test_the_summary_counts_the_table_below_it():
    """Every number in the summary is a count of rows the board itself shows."""
    questions = QUESTIONS.search(BOARD)
    facts = FACTS.search(BOARD)
    assert questions and facts, "the board no longer prints its summary lines"

    rows = _table_rows(BOARD)
    assert int(questions.group(1)) == sum(row[1] for row in rows), \
        "the summary counts questions the table does not list"
    assert int(questions.group(2)) == len(rows), \
        "the summary counts tools the table does not list"
    assert int(facts.group(1)) == sum(row[2] for row in rows), \
        "the summary's recorded facts are not the table's"


def test_every_row_covers_a_tool_the_questions_name():
    """A row nobody asks a question with would be a tool with no evidence."""
    asked = {question["tool"] for question in drift.QUESTIONS}
    assert {tool for tool, _, _ in _table_rows(BOARD)} == asked


def test_the_board_names_the_project_not_the_directory(tmp_path):
    """A checkout is a place; the project's name is the thing that travels."""
    text = status.render(tmp_path)
    assert tmp_path.name not in text
    assert status.PROJECT_NAME in text
    assert not re.search(r"/" + "Users" + "/", text)


def test_a_missing_fixture_is_stated_not_silently_zero(tmp_path):
    """No fixture is a state of the repository, and the board has to say which."""
    text = status.render(tmp_path)
    assert "- recorded facts: 0 — " in text
    assert "is absent" in text
    assert "python -m itl_mcp.drift --write" in text


def test_the_package_reaches_no_network_and_reads_no_pdf():
    """The claim this layer makes about itself, read off the package."""
    assert status.external_readers(ROOT) == [], (
        "this server answers from the two checkouts and from nothing else: an "
        "import of a network client or a PDF reader here breaks that, and the "
        "board would go on claiming it does not")


def test_the_scan_catches_a_module_that_would(tmp_path):
    """The positive control: a scan that can never fire proves nothing."""
    package = tmp_path / "itl_mcp"
    package.mkdir()
    (package / "reader.py").write_text("import fitz\n", encoding="utf-8")
    assert status.external_readers(tmp_path) == ["reader.py"]

    (package / "reader.py").write_text(
        "from urllib.request import urlopen\n", encoding="utf-8")
    assert status.external_readers(tmp_path) == ["reader.py"]


def test_the_scan_ignores_a_module_that_only_names_a_client(tmp_path):
    """Naming a client in a list is not importing one."""
    package = tmp_path / "itl_mcp"
    package.mkdir()
    (package / "clean.py").write_text(
        "REACHES = ('urllib', 'requests')\nimport json\n", encoding="utf-8")
    assert status.external_readers(tmp_path) == [], (
        "a module that merely names a client in a list is not importing one")
