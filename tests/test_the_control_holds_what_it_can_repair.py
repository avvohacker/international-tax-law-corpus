"""The corpus' control holds the half a reader of its own run can repair.

The `discipline` job of `.github/workflows/corpus-drift.yml` runs
`scripts/discipline-drift.py` over the two checkouts this repository holds: itself,
and the server committed inside it under `mcp/`. It used to check the library out as
well, and reported whatever pin the library happened to carry - a red whose only
repair is a push into another repository, which is not a thing a reader of this run
can make. The library's half is read by the same script in the library's own
`discipline-drift` run, over this corpus, where `revendor-discipline` opens the
repair.

Three claims are held here, and each of them can fail on its own:

  * a job called `discipline` runs the control, or the others hold nothing;
  * that job checks out no other repository, and hands the control no `--library`
    checkout: either one would put a copy back into the run that no reader of it can
    write;
  * the command the job runs is run here, and it *says* which layer it was not
    handed and where that half is read - a layer a run passes over in silence reads
    as a layer that passed.

The command is taken from the workflow rather than typed again, and its interpreter
is the one running the tests: a test that ran its own copy of that command would go
on passing after the job had been pointed at a different pair of checkouts, which is
the drift this whole control exists to refuse.
"""
import shlex
import subprocess
import sys

from harness import ci
from support import ROOT

# The job, the control it runs, the layer it does not hold and the switch that
# would name a checkout of it. Named once: every claim below is about these.
JOB = "discipline"
CONTROL = "scripts/discipline-drift.py"
LAYER = "library"
SWITCH = "--library"
HANDED_IN = ("--corpus", "--mcp")
STEPS = ci.steps(ROOT, JOB)


def _commands() -> list[str]:
    """Every `run:` line of the job, in the order the file declares them."""
    return [value for _, step in STEPS for value in ci.values_for(step, "run")
            if isinstance(value, str)]


def _control() -> list[str]:
    """The job's command that runs the control, as the runner's shell splits it."""
    found = [command for command in _commands() if CONTROL in command]
    assert len(found) == 1, (
        f"the `{JOB}` job must run {CONTROL} exactly once - a job that runs the "
        f"control twice, or not at all, is a control nobody can point at. Found "
        f"{len(found)}: {found}")
    return shlex.split(found[0])


def test_the_job_that_holds_the_discipline_is_there():
    """The other claims are about a job; this is what keeps them from being vacuous."""
    assert STEPS, (
        f"no workflow declares a `{JOB}` job, so nothing holds the copies of the "
        f"shared rules against their source and the rest of this file is about "
        f"nothing")
    assert _control()


def test_the_job_checks_out_no_repository_it_cannot_repair():
    """A checkout here is a red in this repository about somebody else's bytes."""
    repositories = [value for _, step in STEPS
                    for value in ci.values_for(step, "repository")]
    assert not repositories, (
        f"the `{JOB}` job checks out another repository: {repositories}. Its run "
        f"would then report a copy no reader of it can write - the library's half is "
        f"read by this same control in the library's own run, over this corpus, "
        f"where the repair is a re-vendor")


def test_the_job_hands_the_control_no_library_checkout():
    """The switch is the other way in: a checkout made outside these steps."""
    switches = _control()
    handed = [token for token in switches
              if token == SWITCH or token.startswith(f"{SWITCH}=")]
    assert not handed, (
        f"the `{JOB}` job hands the control {handed}: whatever checkout that names "
        f"is one this repository does not hold, and a red about it is repaired "
        f"somewhere else")
    missing = [switch for switch in HANDED_IN if switch not in switches]
    assert not missing, (
        f"the `{JOB}` job no longer hands the control {missing}: the two checkouts "
        f"this repository holds are what this run is for. It runs {switches}")


def test_the_run_names_the_layer_it_was_not_handed():
    """The job's own command, run here, has to say where the other half is read.

    A summary that stopped at the checkouts it was handed would make every run of
    this control read as a run over the whole family, and the layer it left out would
    be the one nobody notices leaving.
    """
    switches = _control()
    assert switches[:2] == ["python", CONTROL], (
        f"the `{JOB}` job runs the control as {switches[:2]}: this test runs the "
        f"command the job declares, from this checkout's root, and a prefix it does "
        f"not expect is a command it would run differently from the runner")
    result = subprocess.run([sys.executable, *switches[1:]], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"the command the `{JOB}` job runs is red on this checkout:\n"
        f"{result.stdout}\n{result.stderr}")
    assert f"not read here: {LAYER}" in result.stdout, (
        f"the run does not say that the {LAYER}'s half was not read, so it reads as "
        f"a run over the whole family. It printed:\n{result.stdout}")
    assert f"{LAYER}'s own run" in result.stdout, (
        f"the run names the layer it left out and not where that half is read, which "
        f"leaves this repository's reader nowhere to look. It printed:\n"
        f"{result.stdout}")
