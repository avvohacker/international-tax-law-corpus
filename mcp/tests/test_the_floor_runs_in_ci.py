"""The declared floor must be an interpreter the CI actually runs.

`pyproject.toml` says `requires-python = ">=3.11"`, which is a claim about what
a user may install this server on. A claim nobody executes is an opinion, and
`.github/workflows/mcp-drift.yml` answers it: the `compatibility` job asks the
same answers again on the floor and on the newest release, beside the 3.13 the
answers are recorded and verified on. The floor is this family's own choice
rather than the MCP SDK's - the SDK supports 3.10 - which is exactly why it has
to be run rather than asserted.

The claim and the execution are in two different directories, and no longer even
in the same repository. The manifest read below is this package's own, because
that is the sentence a user installs on; the workflows that run the tests of that
package are the ones of the checkout that holds it, which is this directory when
the server is a repository of its own and the corpus when it is committed inside
it. Both readings come from `itl_mcp.ci` - one reader, one answer - and a run
that resolved them differently from the board would be the drift this file exists
to catch.

The failure this file exists for is silent. The floor and the workflow are two
files, and deleting the 3.11 leg while the manifest keeps claiming it is a
one-line edit that no other test can see: the suite on 3.13 stays green, and the
claim quietly becomes an opinion. Nothing here can run a second interpreter - it
holds two declarations against each other, which is the half a runner cannot do.
"""

from pathlib import Path

from itl_mcp import ci

ROOT = Path(__file__).resolve().parent.parent
# The workflows that run this package, which is not ROOT when the server is
# committed inside another repository: see `itl_mcp.ci.repository`.
WORKFLOWS = ci.repository(ROOT)

SAMPLE = "\n".join((
    "jobs:",
    "  control:",
    "    steps:",
    "      - uses: actions/setup-python@v5",
    "        with:",
    "          python-version: '3.13'",
    "  compatibility:",
    "    strategy:",
    "      fail-fast: false",
    "      matrix:",
    "        python-version: ['3.9', '3.11']",
    "",
))


def _workflow(tmp_path, name: str, body: str, requires: str = ">=3.11"):
    workflow = tmp_path / ".github" / "workflows" / name
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(body, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "sample"\nrequires-python = "{requires}"\n',
        encoding="utf-8")


def test_the_declared_floor_is_an_interpreter_the_workflows_run():
    floor = ci.floor(ROOT)
    assert floor in ci.interpreters(WORKFLOWS), (
        f"pyproject.toml declares requires-python >= {floor}, and no workflow "
        f"runs {floor}: the workflows name {ci.interpreters(WORKFLOWS)}")


def test_the_floor_is_verified_by_a_matrix_leg_not_by_a_stray_pin():
    """The floor has to be a job that runs the control, not a string in a step."""
    floor = ci.floor(ROOT)
    assert floor in ci.matrix_interpreters(WORKFLOWS), (
        f"the floor {floor} is not one of the matrix legs "
        f"{ci.matrix_interpreters(WORKFLOWS)}: the claim that a user on {floor} "
        f"can install this would rest on a step nobody has to keep")


def test_no_interpreter_older_than_the_floor_is_run():
    """The other direction: a leg below the floor un-declares the floor."""
    versions = sorted(set(ci.interpreters(WORKFLOWS)), key=ci.order)
    assert versions[0] == ci.floor(ROOT), (
        f"the oldest interpreter the workflows run is {versions[0]}, while the "
        f"floor declared in pyproject.toml is {ci.floor(ROOT)}: {versions}")


def test_every_python_version_the_workflows_name_is_one_this_reader_can_read():
    """YAML reads an unquoted 3.10 as the number 3.1, and 3.1 is not 3.10."""
    unreadable = ci.suspect(WORKFLOWS)
    assert not unreadable, (
        f"a python-version in .github/workflows is neither a quoted X.Y nor a "
        f"matrix reference: {unreadable} - YAML reads an unquoted 3.10 as the "
        f"number 3.1, and a name that lost a digit compares equal to nothing")


def test_the_control_names_the_library_and_never_itself():
    """What the control checks out, read from the workflows that run this package.

    Two layouts have to hold here, and they are one fact. Checked out as a
    repository of its own, the server is run by workflows that check out both the
    corpus and the library beside it. Committed inside the corpus, under `mcp/`,
    it is run by the corpus' own workflows: the corpus is not checked out at all,
    because the run is standing in it. The library is named either way - it is the
    one repository this server reads that never holds it - and the server is never
    named as a repository in either layout: a `repository:` key means somebody
    else's code, and a document that listed the checkouts from memory would go on
    naming them after the control had been pointed at a different pair.
    """
    repositories = ci.checked_out_repositories(WORKFLOWS)
    # Named by the repository, not by its owner: who owns them is the account's
    # business and is already in the README, and writing it bare here would put
    # the account name of a machine in a committed file - which
    # `tests/test_no_machine_traces.py` refuses, this file included.
    assert any(name.endswith("international-tax-law-library")
               for name in repositories), (
        f"no workflow that runs this package checks out the library it answers "
        f"from: {repositories}")
    assert not any(name.endswith("international-tax-law-mcp")
                   for name in repositories), (
        "the server is checked out by the run, never named as another "
        "repository: a `repository:` key here means somebody else's code")


def test_the_reader_reads_what_it_reads(tmp_path):
    """A walker that found nothing would make every test above vacuous."""
    _workflow(tmp_path, "sample.yml", SAMPLE)

    assert set(ci.interpreters(tmp_path)) == {"3.13", "3.9", "3.11"}
    assert ci.matrix_interpreters(tmp_path) == ["3.9", "3.11"]
    assert ci.floor(tmp_path) == "3.11"
    assert not ci.suspect(tmp_path)
    assert ci.checked_out_repositories(tmp_path) == []
    # 3.9 is older than the floor and is run: the reader tells those two numbers
    # apart by value, not as strings, where "3.11" would sort below "3.9".
    assert sorted(set(ci.interpreters(tmp_path)), key=ci.order)[0] == "3.9"


def test_a_matrix_reference_is_not_read_as_an_interpreter(tmp_path):
    """`${{ matrix.python-version }}` names the matrix, not a version."""
    _workflow(tmp_path, "reference.yml", "\n".join((
        "jobs:",
        "  compatibility:",
        "    strategy:",
        "      matrix:",
        "        python-version: ['3.11', '3.14']",
        "    steps:",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: ${{ matrix.python-version }}",
        "          repository: somebody/other",
        "",
    )))
    assert ci.interpreters(tmp_path) == ["3.11", "3.14"]
    assert ci.matrix_interpreters(tmp_path) == ["3.11", "3.14"]
    assert not ci.suspect(tmp_path)
    assert ci.checked_out_repositories(tmp_path) == ["somebody/other"]


def test_the_reader_names_a_version_yaml_damaged(tmp_path):
    """The positive control for `suspect`: an unquoted 3.10 is not a 3.10."""
    _workflow(tmp_path, "damaged.yml", "\n".join((
        "jobs:",
        "  control:",
        "    steps:",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: 3.10",
        "",
    )))
    assert ci.suspect(tmp_path) == ["3.1"], (
        "an unquoted version is read by YAML as a number; `suspect` has to name "
        "it, or an interpreter nobody declared would pass the check")


def test_the_reader_names_a_version_it_cannot_read_at_all(tmp_path):
    """`nightly` is not a version: named, never silently dropped."""
    _workflow(tmp_path, "odd.yml", "\n".join((
        "jobs:",
        "  control:",
        "    steps:",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: nightly",
        "",
    )))
    assert ci.interpreters(tmp_path) == []
    assert ci.suspect(tmp_path) == ["nightly"]
