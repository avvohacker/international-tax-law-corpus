"""Nothing this repository commits may describe the machine it was built on.

The corpus calls this class F14 ("no environment leakage") and states it there,
because a committed artefact of its pipeline once carried an absolute path into
the builder's home directory. This layer commits no corpus artefact, but it
commits a package, a fixture and a workflow, and the class applies to all three:
a path that only exists on one desk, the name of the directory this checkout
happens to live in, or the account name of the machine that ran the checks.

The rule itself is not written here. It is `vendor/discipline/machine_traces.py`,
copied verbatim from the corpus and pinned in
`provenance/vendored-discipline.yaml`, because the three repositories kept three
copies of it and the copies had drifted apart - and because the copy this file
replaced failed its own CI: its positive control contained a machine root written
whole, and the scan read its own sample as a leak.

What stays here is the server's own half: the samples this layer's files use (a
recorded answer, a module of the package), and the identity CI gives this
checkout, reproduced below on a desk.
"""
from pathlib import Path

from vendor.discipline import machine_traces

ROOT = Path(__file__).resolve().parent.parent


def test_no_committed_file_carries_a_machine_trace():
    """The whole tracked tree, read under the identity of this package's name.

    The identity is stated instead of left to the default, and where this package
    is committed is why. `problems(ROOT)` reads the rule's second clause - "the
    name of the directory the checkout happens to live in" - against `ROOT.name`,
    and that directory is `mcp/`, inside the corpus. `mcp` is not a fact about a
    desk: it is committed, it is the same in every clone, and it is the subject of
    most of the prose here, so the clause would report the word this package
    exists for. A folder named after its own project is the one directory name the
    rule already exempts, and this is that case read properly -
    `international-tax-law-mcp` is the name the manifest gives the package, and
    the name CI checks the checkout out as.

    Nothing the rule is really holding is given up. A home path, a machine root, a
    `file://` URL and this desk's own account name are all still read, from every
    file and from this machine. The desk's *directory* name is a fact about the
    checkout the package is committed in rather than about the package, and it is
    read there: the corpus' own copy of this rule scans every file it tracks,
    `mcp/` included.
    """
    problems = machine_traces.problems(
        ROOT, checkout=machine_traces.project_name(ROOT))
    assert not problems, (
        "a committed file describes the machine it was built on:\n  "
        + "\n  ".join(problems[:12]))


def test_the_server_passes_the_rule_as_the_ci_account_sees_it():
    """The identity of the compatibility jobs, reproduced on a desk.

    CI checks this repository out under its own project name and runs as an
    account whose name is an ordinary English word - which this repository's own
    workflow says, of the thing that reads what the corpus was built from. A rule
    that reads that word as a trace of a person is red on every run, and cannot
    be seen on a desk unless the identity is stated. It is stated instead.
    """
    problems = machine_traces.problems(
        ROOT, user="runner", checkout="international-tax-law-mcp")
    assert not problems, (
        "the server is red under the identity its own CI runs as:\n  "
        + "\n  ".join(problems[:12]))


def test_the_detector_catches_every_trace_it_claims_to():
    """The positive control: a detector that never fires proves nothing."""
    checkout = "a-clone-called-something-else"
    user = "somebody"
    samples = (
        ("an absolute home path", "/" + "Users" + "/somebody/answers.json"),
        ("a machine-local root",
         "/" + "private" + "/var" + "/folders" + "/x/y/fixture.json"),
        ("a Windows home path",
         "C:" + "\\" + "Users" + "\\" + "somebody" + "\\verify.py"),
        ("a file:// URL naming a local path", "file:" + "///tmp/fixture.json"),
        ("the directory this checkout lives in",
         "cloned into a-clone-called-something-else"),
        ("the account name on this machine", "built on somebody's laptop"),
    )
    for expectation, sample in samples:
        found = machine_traces.traces_in(sample, checkout=checkout, user=user,
                                         project="international-tax-law-mcp")
        assert any(expectation in hit for hit in found), (
            f"the detector no longer catches {expectation}: {sample!r} -> {found}")


def test_a_ci_accounts_home_path_is_still_a_trace():
    """The exemption is the account name, never the path that carries it."""
    text = "/" + "home" + "/" + "runner" + "/work/mcp/fixtures/answers.json"
    found = machine_traces.traces_in(text, checkout=None, user="runner")
    assert found, "the path rule stopped catching a CI account's home directory"


def test_the_exempt_accounts_are_declared_where_an_exemption_can_be_reviewed():
    """A list that grows without a second edit is a list that grows by accident."""
    assert machine_traces.CI_ACCOUNTS == frozenset({"runner", "github-actions"}), (
        "the accounts exempt from the name rule changed: the rule's own docstring "
        "and the corpus' SPEC state the reason, and the copy here is pinned")


def test_the_detector_leaves_the_declarations_alone():
    """Naming the owner and the contact is the point of these lines."""
    text = ("Copyright (c) 2026 somebody <somebody@example.com> - project\n"
            "Contact somebody@example.com before any reuse beyond reading.\n"
            "repository: somebody/international-tax-law-corpus\n"
            "badge: https://github.com/somebody/international-tax-law-mcp\n")
    assert not machine_traces.traces_in(text, checkout="international-tax-law-mcp",
                                        user="somebody",
                                        project="international-tax-law-mcp")


def test_a_checkout_named_after_the_project_is_not_a_trace():
    """CI clones into the project's own name, and that name is not a machine."""
    text = "the server repository international-tax-law-mcp"
    assert not machine_traces.traces_in(text, checkout="international-tax-law-mcp",
                                        user=None, project="international-tax-law-mcp")
    assert machine_traces.traces_in(text, checkout="intl-mcp", user=None,
                                    project="international-tax-law-mcp") == []


def test_the_placeholder_a_catalogue_uses_is_not_a_trace():
    """A path written with a placeholder is not a path to a machine."""
    evidence = '"' + "/" + "Users" + "/<user>/Desktop/…/treaty.json" + '"'
    assert not machine_traces.traces_in(evidence, checkout="x", user=None)
