"""The shared discipline is vendored here, and the pin is what holds it.

`vendor/discipline/` is not this repository's own code: it is the corpus' rules -
what may not be committed about a machine, how a workflow is read, what a status
board owes a reader, what a pin says about the copy it holds, and where a document
sends a reader who wants the server - copied verbatim, and
`provenance/vendored-discipline.yaml` says which bytes traveled and where they
came from. Three ways that can stop being true - a copy edited in place, a pin
left behind by that copy, and a pin whose own claim names a branch or a tag where
it has to name a commit - and the rule about all three is the vendored
`vendor/discipline/pin.py`, read here rather than restated: it used to be stated
three times, once in this file, once in the library's copy of it and once in the
reader the corpus' control runs, and the three had drifted.

What this file adds to the shared rule is what only the copy beside it can
answer: that the bytes here are the bytes the pin declares, that the rule it runs
is the rule that passed, and that the job which compares this copy with the
corpus' *current* rules still exists. That comparison cannot be made from one
checkout: it is what the `discipline` job of the corpus' workflow asks, reading
this package where it is committed, and
`test_the_workflows_that_run_this_package_run_the_discipline_control` is what
stops that job from being deleted while every test here stays green.

The rules are then *run* here, not only hashed: equal bytes are not the same as a
rule that passes.
"""
from pathlib import Path

import yaml

from itl_mcp import ci, status
from vendor.discipline import board, machine_traces, pin

ROOT = Path(__file__).resolve().parent.parent
# The workflows that run this package, which is not ROOT when the server is
# committed inside another repository: see `itl_mcp.ci.repository`.
WORKFLOWS = ci.repository(ROOT)
VENDORED = ROOT / "vendor" / "discipline"
PIN = ROOT / "provenance" / "vendored-discipline.yaml"


def copies() -> dict[str, bytes]:
    """The vendored files, as bytes, keyed by name."""
    return {path.name: path.read_bytes() for path in sorted(VENDORED.glob("*.py"))}


def pinned() -> dict:
    return yaml.safe_load(PIN.read_text(encoding="utf-8")) or {}


def test_the_vendored_discipline_is_the_bytes_the_pin_declares():
    """A copy nobody re-vendored is a rule of this repository's own invention."""
    problems = pin.problems(pinned(), copies())
    assert not problems, (
        "the vendored discipline and its pin disagree:\n  "
        + "\n  ".join(problems)
        + "\n  re-vendor with `python scripts/vendor-discipline.py --into .` from "
          "the corpus")


def test_the_checker_can_fail():
    """The positive control, because every test above is an `assert not`.

    The copies are handed to the rule as arguments rather than read from the
    tree, which is what makes these cases possible at all: a checker that can
    only be tested on a repository that is already correct proves nothing.
    """
    here = copies()
    name = sorted(here)[0]
    stored = pinned()

    edited = dict(here)
    edited[name] = here[name] + b"\n# an edit nobody re-vendored\n"
    problems = pin.problems(stored, edited)
    assert problems and any(name in problem for problem in problems), problems

    missing = dict(here)
    missing.pop(name)
    problems = pin.problems(stored, missing)
    assert problems and any(name in problem for problem in problems), problems

    unfixed = dict(stored)
    unfixed["files"] = {key: "0" * 64 for key in (stored.get("files") or {})}
    assert pin.problems(unfixed, here), "a pin whose hashes are all wrong was accepted"

    moved = dict(stored)
    moved["source_commit"] = "main"
    assert pin.problems(moved, here), (
        "a pin naming a branch instead of a commit was accepted: it describes "
        "whatever that branch held when it was read, and not these bytes")
    tagged = dict(stored)
    tagged["source_commit"] = "v1.0.0"
    assert pin.problems(tagged, here), "a pin naming a tag was accepted as a pin"


def test_the_board_rule_holds_here():
    """The rule the family shares about the document it prints.

    Read clause by clause from the vendored rule's own facts rather than from
    `board.problems`, for one reason: the rule's fifth clause - "CI runs the
    tests, or the third clause holds nothing" - is a fact about the repository
    that runs this package rather than about the package. Committed inside the
    corpus, this package is executed by the corpus' workflows, and a rule asked
    about `mcp/` alone would report a control nobody runs. The four clauses that
    are about the document are the same either way.
    """
    found = board.facts(ROOT)
    assert found["documents"] == 1, found["documents"]
    assert found["command"], "the board does not say which command writes it"
    assert found["names_the_project"], found["project"]
    assert found["current_test"], \
        "no test names both the board and the command that writes it"
    assert ci.runs_pytest(WORKFLOWS), (
        f"no run executes that test: the workflows of {WORKFLOWS} run no pytest")


def test_the_board_names_the_control_that_runs_it():
    """The board has to name a workflow that exists, and say whose it is.

    The board is read by somebody who will go and look. A line naming the control
    at the server's own root, when the workflows that run the package belong to
    the corpus, sends them to a directory nothing runs - so the name is read from
    the same reader the line was printed from, and a board that names none of the
    workflows of `ci.repository(ROOT)` is a red run rather than a wrong address.
    """
    text = status.render(ROOT)
    names = status.control(WORKFLOWS, ROOT)
    assert names, (
        f"no workflow of {WORKFLOWS} runs pytest, so the board's line about the "
        f"workflows that run this package would be a claim about nothing")
    for name in names:
        assert f"`{name}`" in text, (
            f"the board does not name {name}, and that is a workflow that runs it")
    if not (ROOT / ".github" / "workflows").is_dir():
        assert "of the repository that holds this package" in text, (
            "the board names a workflow without saying whose it is: this package "
            "carries none of its own, so a reader would look beside it")


def test_the_rule_holds_here_as_ci_sees_it():
    """Equal bytes are not a rule that passes: the scan is run, not hashed."""
    problems = machine_traces.problems(
        ROOT, user="runner", checkout="international-tax-law-mcp")
    assert not problems, "\n  ".join(["the rule fails on this checkout:"] + problems)


def test_the_workflows_that_run_this_package_run_the_discipline_control():
    """The check that needs the corpus' current rules cannot be a test; it must be
    a run.

    Read from the repository that runs this package: `mcp/` when it is a checkout
    of its own, the corpus when the package is committed inside it. In both
    layouts the comparison of this copy with the corpus' current rules is a step
    of a workflow that exists where GitHub reads it, which is what stops the copy
    in `vendor/` from being compared with nothing while every test stays green.
    """
    workflows = ci.workflows(WORKFLOWS)
    text = "\n".join(path.read_text(encoding="utf-8") for path in workflows)
    assert workflows, "no workflow runs this package, so nothing runs at all"
    assert "discipline-drift.py" in text, (
        "no workflow step runs the corpus' discipline drift control: the copy in "
        "vendor/ would go on being compared with nothing, and every test in this "
        "file would stay green while it did")
