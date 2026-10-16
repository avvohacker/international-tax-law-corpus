"""The control holds the half a reader of its own run can repair.

The job that runs `scripts/discipline-drift.py` holds the two checkouts this
repository holds - itself, and the server committed inside it under `mcp/` - and the
library's half is read by the same control in the library's own run, over this
corpus. That job used to check the library out as well, and reported whatever pin
that checkout happened to carry: a red whose only repair is a push into another
repository, which is not a thing a reader of this run can make.

The rule is one module, `harness/discipline/holds.py`, and it is read here and by
the probe `d28` rather than restated - two readings of one rule are two rules. This
file holds the rule to the shapes it has to refuse, holds this repository's own job
to it, and then runs the command that job declares, because the run is what the last
claim is about.

Three claims, and each of them can fail on its own:

  * the rule refuses a sibling checkout, a switch naming one, a checkout the control
    is not handed, a run with no source, and a repository whose job runs nothing -
    and accepts the two shapes the family has;
  * this repository's job holds exactly the two checkouts this repository holds, and
    leaves the library out;
  * the run names every layer it was not handed, with the reason the rule states for
    it, so that a run which stopped at the checkouts it was given fails here.
"""
import shlex
import subprocess
import sys
from pathlib import Path

from harness.discipline import holds
from support import ROOT

# The command a scratch job runs, in each shape the rule has to decide.
GOOD = "--corpus . --mcp mcp"
SIBLING_BY_SWITCH = "--corpus . --mcp mcp --library ../library"
SIBLING_BY_EQUALS = "--corpus . --mcp mcp --library=../library"
SIBLING_BY_MCP = "--corpus . --mcp ../some-other-checkout"
NO_SOURCE = "--mcp mcp"
# The library's own job, which the rule has to accept as much as this repository's:
# it reads this corpus as its source and holds itself, which is the copy it repairs.
LIBRARY_SHAPE = "--corpus corpus --library . --mcp corpus/mcp"


def _checkout(tmp_path: Path, command: str | None, checkout: str | None = None,
              at: str = "library") -> Path:
    """A checkout whose workflow runs the control the way one case describes.

    ``command`` is what the job runs - `None` for a job that runs something else -
    and ``checkout`` is a repository the job checks out besides its own, at ``at``.
    """
    root = tmp_path / "checkout"
    (root / ".github" / "workflows").mkdir(parents=True)
    steps = ["      - uses: actions/checkout@v4"]
    if checkout:
        steps += ["      - uses: actions/checkout@v4", "        with:",
                  f"          repository: {checkout}", f"          path: {at}"]
    if command:
        steps += [f"      - run: python {holds.CONTROL} {command}"]
    root.joinpath(".github", "workflows", "sample.yml").write_text(
        "\n".join(["name: sample", "on: [push]", "jobs:", f"  {holds.JOB}:",
                   "    runs-on: ubuntu-latest", "    steps:"] + steps + [""]),
        encoding="utf-8")
    return root


def _refused(root: Path) -> str:
    return "\n  ".join(holds.problems(root))


def test_the_rule_refuses_each_clause(tmp_path):
    """A rule that accepts everything is not a rule: every clause fires here.

    The two shapes the family actually has are the positive control - the corpus'
    job, which holds its own two checkouts, and the library's, which reads this
    corpus and holds itself.
    """
    assert _refused(_checkout(tmp_path / "good", GOOD)) == "", (
        "the rule refuses the shape this repository's job has")
    assert _refused(_checkout(tmp_path / "library", LIBRARY_SHAPE,
                              checkout="somebody/corpus", at="corpus")) == "", (
        "the rule refuses the shape the library's own job has, and a rule only this "
        "repository satisfies would be a rule about this repository")

    by_switch = _refused(_checkout(tmp_path / "switch", SIBLING_BY_SWITCH))
    assert "not this repository's to write" in by_switch, (
        f"a `--library` checkout beside the root was accepted: {by_switch!r}")
    by_equals = _refused(_checkout(tmp_path / "equals", SIBLING_BY_EQUALS))
    assert "not this repository's to write" in by_equals, (
        f"a `--library=<path>` switch was read as if it were not there: "
        f"{by_equals!r}")
    by_mcp = _refused(_checkout(tmp_path / "mcp", SIBLING_BY_MCP))
    assert "not this repository's to write" in by_mcp, (
        f"a sibling handed in under another switch was accepted: {by_mcp!r}")
    checked_out = _refused(_checkout(tmp_path / "checked-out", GOOD,
                                     checkout="somebody/library"))
    assert "a checkout nothing reads" in checked_out, (
        f"a checkout of somebody else's repository was accepted: {checked_out!r}")
    no_source = _refused(_checkout(tmp_path / "no-source", NO_SOURCE))
    assert "without `--corpus`" in no_source, (
        f"a run with no source to compare against was accepted: {no_source!r}")
    nothing = _refused(_checkout(tmp_path / "nothing", None))
    assert "no job runs" in nothing, (
        f"a repository whose workflows run no control was accepted: {nothing!r}")


def test_the_job_holds_only_the_checkouts_this_repository_holds():
    """This repository's own job, against the rule and against its own facts."""
    found = holds.runs(ROOT)
    assert len(found) == 1, (
        f"exactly one job runs the control, and {len(found)} do: "
        f"{[(r['file'].name, r['job']) for r in found]}")
    problems = holds.problems(ROOT)
    assert not problems, "\n  ".join(problems)
    job = found[0]
    assert job["source"] == ".", (
        f"the run is handed {job['source']!r} as the source of the rules, and the "
        f"checkout it stands in is what owns them")
    assert job["hands_in"] == ["corpus", "mcp"], (
        f"the run holds {job['hands_in']}: the two checkouts this repository holds "
        f"are itself and the server committed in it")
    assert job["leaves"] == ["library"], (
        f"the run leaves {job['leaves']} out, and the library is the layer this "
        f"repository does not hold: its copy is repaired by a re-vendor there")
    assert not job["checkouts"], (
        f"the job checks out {job['checkouts']}: the source is the only repository "
        f"a run of this control may read without holding it")


def test_the_run_names_the_layer_it_was_not_handed():
    """The job's own command, run here, has to say where the other half is read.

    The reason is compared against the rule's own text, so a run that printed a
    sentence of its own - or that stopped at the checkouts it was handed, which is
    the silence that reads as a run over the whole family - fails here.
    """
    run = holds.runs(ROOT)[0]
    command = shlex.split(run["commands"][0])
    assert command[:2] == ["python", holds.CONTROL], (
        f"the job runs the control as {command[:2]}: this test runs the command the "
        f"job declares, from this checkout's root, and a prefix it does not expect "
        f"is a command it would run differently from the runner")
    result = subprocess.run([sys.executable, *command[1:]], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"the command the job runs is red on this checkout:\n"
        f"{result.stdout}\n{result.stderr}")
    assert run["leaves"], (
        "this run holds every layer, and the split this file is about is not in it")
    for layer in run["leaves"]:
        line = f"not read here: {layer} - {holds.NOT_READ[layer]}"
        assert line in result.stdout, (
            f"the run does not say, in the rule's own words, that the {layer}'s half "
            f"was not read and where it is read. It printed:\n{result.stdout}")
