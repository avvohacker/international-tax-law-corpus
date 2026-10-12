"""The declared floor must be an interpreter the CI actually runs.

`pyproject.toml` says `requires-python = ">=3.11"`, which is a claim about what
a reader may run this harness on. SPEC.md is explicit that a claim nobody
executes is an opinion, and `.github/workflows/corpus-drift.yml` answers it: the
`compatibility` job runs the drift control and the whole suite on the floor and
on the newest release, beside the 3.13 the corpus is built and published with.

The failure this file exists for is silent. The floor and the workflows are two
files, and deleting the 3.11 leg while the manifest keeps claiming it is a
one-line edit that no other test can see: the suite on 3.13 stays green, and
the claim quietly becomes an opinion. Nothing here can run a second
interpreter - it holds two declarations against each other, which is the half a
runner cannot do.
"""

from harness import ci
from support import ROOT

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
    assert floor in ci.interpreters(ROOT), (
        f"pyproject.toml declares requires-python >= {floor}, and no workflow "
        f"runs {floor}: the workflows name {ci.interpreters(ROOT)}")


def test_the_floor_is_verified_by_a_matrix_leg_not_by_a_stray_pin():
    """The floor has to be a job that runs the control, not a string in a step."""
    floor = ci.floor(ROOT)
    assert floor in ci.matrix_interpreters(ROOT), (
        f"the floor {floor} is not one of the matrix legs "
        f"{ci.matrix_interpreters(ROOT)}: the claim that a reader on {floor} can "
        f"run this would rest on a step nobody has to keep")


def test_no_interpreter_older_than_the_floor_is_run():
    """The other direction: a leg below the floor un-declares the floor."""
    versions = sorted(set(ci.interpreters(ROOT)), key=ci.order)
    assert versions[0] == ci.floor(ROOT), (
        f"the oldest interpreter the workflows run is {versions[0]}, while the "
        f"floor declared in pyproject.toml is {ci.floor(ROOT)}: {versions}")


def test_every_python_version_the_workflows_name_is_one_this_reader_can_read():
    """YAML reads an unquoted 3.10 as the number 3.1, and 3.1 is not 3.10."""
    unreadable = ci.suspect(ROOT)
    assert not unreadable, (
        f"a python-version in .github/workflows is neither a quoted X.Y nor a "
        f"matrix reference: {unreadable} - YAML reads an unquoted 3.10 as the "
        f"number 3.1, and a name that lost a digit compares equal to nothing")


def test_the_reader_reads_what_it_reads(tmp_path):
    """A walker that found nothing would make every test above vacuous."""
    _workflow(tmp_path, "sample.yml", SAMPLE)

    assert set(ci.interpreters(tmp_path)) == {"3.13", "3.9", "3.11"}
    assert ci.matrix_interpreters(tmp_path) == ["3.9", "3.11"]
    assert ci.floor(tmp_path) == "3.11"
    assert not ci.suspect(tmp_path)
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
        "",
    )))
    assert ci.interpreters(tmp_path) == ["3.11", "3.14"]
    assert ci.matrix_interpreters(tmp_path) == ["3.11", "3.14"]
    assert not ci.suspect(tmp_path)


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
