"""The library is pinned by commit, and every run that reads it uses that commit.

The server owns no data: a treaty answer it prints is a claim about bytes held by
another repository. `mcp/provenance/library.yaml` is where this repository says
which bytes, and `.github/workflows/mcp-drift.yml` is the only thing that checks
them out. Two ways that pairing can stop being true, and one of them is silent:

  * the pin can name a branch, or nothing, and then the run describes whatever
    that branch held the day it was read - the same reason the vendored
    discipline's pin refuses a ref instead of a commit;
  * a workflow can check the library out without asking the pin at all, which
    reads correctly today because the pin happens to agree with the branch, and
    goes on being green while the answers quietly track a repository that moved.

The second is the one nothing else can see: the suite passes on the bytes it was
given either way, and only the workflow's own text says which bytes those were.
So the readings here are of the workflow and the register, held against each
other - which is the half a runner cannot do.

What this file cannot check is that the commit exists, or that it holds the bytes
the answers were earned on: the first is the checkout's job, and the second is
`python -m itl_mcp.drift` on the checkout the pin produces.
"""
import re
from pathlib import Path

import yaml

from itl_mcp import ci

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "provenance" / "library.yaml"
# The workflows that run this package: this directory's when the server is a
# checkout of its own, the corpus' root when it is committed inside it.
WORKFLOWS = ci.repository(ROOT) / ".github" / "workflows"

REPOSITORY = "https://github.com/avvohacker/international-tax-law-library"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
# The one expression every library checkout must carry, so that no job can be
# pointed at a different library than the one the pin names.
FROM_THE_PIN = "${{ steps.library.outputs.commit }}"


def pinned() -> dict:
    return yaml.safe_load(PIN.read_text(encoding="utf-8")) or {}


def library_checkouts(workflow: str) -> list[dict]:
    """Every step of these bytes that checks out the library, as written."""
    data = yaml.safe_load(workflow) or {}
    found: list[dict] = []
    for job in (data.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            with_ = step.get("with") or {}
            if str(with_.get("repository") or "").endswith(
                    "international-tax-law-library"):
                found.append(step)
    return found


def test_the_pin_names_the_library_by_commit():
    """A pin that names a branch is not a pin, and one that names nothing is worse."""
    pin = pinned()
    assert pin.get("repository") == REPOSITORY, (
        f"the pin names the repository {pin.get('repository')!r}, and the server "
        f"answers from {REPOSITORY}")
    commit = str(pin.get("commit") or "")
    assert COMMIT.match(commit), (
        f"the pin names {commit!r} as the commit it was pinned to, and that is "
        f"neither a git object id nor anything a checkout can be asked for")
    assert pin.get("pinned_on"), (
        "the pin does not say when it was taken: the date is what tells a reader "
        "whether the library has moved since")


def test_every_run_that_reads_the_library_reads_it_at_the_pin():
    """The workflow is where the pin becomes the bytes the suite is handed."""
    workflows = sorted(WORKFLOWS.glob("*.y*ml"))
    assert workflows, f"no workflow under {WORKFLOWS} runs this package"

    checkouts = []
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        for step in library_checkouts(text):
            checkouts.append((path.name, step))
    assert checkouts, (
        "no workflow checks the library out: the suite would skip for want of a "
        "root, and a skip is green - the failure this family refuses everywhere")

    for name, step in checkouts:
        with_ = step.get("with") or {}
        assert with_.get("ref") == FROM_THE_PIN, (
            f"{name} checks the library out at {with_.get('ref')!r}, and the "
            f"answers the suite asserts are about the commit the pin names: "
            f"`mcp/provenance/library.yaml` is the only place that commit may be "
            f"chosen")

    assert any("mcp/provenance/library.yaml" in path.read_text(encoding="utf-8")
               for path in workflows), (
        "no workflow reads `mcp/provenance/library.yaml`: a pin nothing reads is "
        "a document, and the checkouts above would be reading a commit from "
        "somewhere else")


def test_the_reader_refuses_a_library_checkout_that_names_no_commit():
    """The positive control: every test above is an `assert` on a green tree."""
    sample = "\n".join((
        "jobs:",
        "  control:",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "        with:",
        "          repository: somebody/international-tax-law-library",
        "          path: library",
        "",
    ))
    steps = library_checkouts(sample)
    assert len(steps) == 1, "the reader did not see the library being checked out"
    assert (steps[0].get("with") or {}).get("ref") is None, (
        "a checkout with no `ref` was read as naming one: the check above would "
        "pass on the very workflow it exists to refuse")

    pinned_sample = sample.replace(
        "          path: library",
        f"          path: library\n          ref: {FROM_THE_PIN}")
    assert (library_checkouts(pinned_sample)[0].get("with") or {}).get("ref") == (
        FROM_THE_PIN), "the reader cannot see a `ref` the pin supplies"
