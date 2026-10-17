"""Nothing this repository commits may describe the machine it was built on.

Invariant F14, and the defect class behind it (`d22`): the committed
`derived/index.json` once carried an absolute path into the builder's home
directory, twice. `test_invariants.py` checks the artefacts the pipeline writes,
from a list of globs; the class is wider than that list, so the rule is applied
here to every file git tracks, whichever directory it is in.

The rule itself lives in `harness/discipline/machine_traces.py`, because all
three repositories of the family hold it and the three copies had drifted apart
before anything compared them. This file holds *this* repository to it, and keeps
the two halves no other repository can check: the source catalogue in
`fixtures/` has to be able to say where a local path was without naming one, and
the corpus is the repository that carries the workflow comments, the fetcher and
the recreation document in which the word CI uses for its own account appears.

The two defects this file was born red with are worth naming, because both were
invisible from a desk:

  * it wrote its own positive control with a whole machine root in it, so the
    check failed on itself;
  * CI runs as an account whose name is an ordinary English word, and the corpus
    says that word in its own prose, so the account rule fired on lines that name
    nobody.

Both are now declared or fixed where the rule lives, and the identity CI runs
under is reproduced below, on a desk, as a test.
"""
from harness.discipline import machine_traces
from support import ROOT


def test_no_committed_file_carries_a_machine_trace():
    """The whole tracked tree, read the way the check is meant to read it."""
    problems = machine_traces.problems(ROOT)
    assert not problems, (
        "a committed file describes the machine it was built on:\n  "
        + "\n  ".join(problems[:12]))


def test_the_corpus_passes_the_rule_as_the_ci_account_sees_it():
    """The identity of the compatibility jobs, reproduced on a desk.

    CI runs as an account whose name is an ordinary English word and checks the
    repository out under its own project name. Nothing on a desk is called that,
    so a rule that collides with the repositories' own prose - "the runner reads
    what the corpus was built from" is a line of the workflow - cannot be seen
    here unless the identity is stated. It is stated instead.
    """
    problems = machine_traces.problems(
        ROOT, user="runner", checkout="international-tax-law-corpus")
    assert not problems, (
        "the corpus is red under the identity its own CI runs as:\n  "
        + "\n  ".join(problems[:12]))


def test_the_detector_catches_every_trace_it_claims_to():
    """The positive control: a detector that never fires proves nothing."""
    checkout = "a-clone-called-something-else"
    user = "somebody"
    samples = (
        ("an absolute home path", "/" + "Users" + "/somebody/corpus.xml"),
        ("a machine-local root",
         "/" + "private" + "/var" + "/folders" + "/x/y/corpus.json"),
        ("a Windows home path",
         "C:" + "\\" + "Users" + "\\" + "somebody" + "\\doc.akn.xml"),
        ("a file:// URL naming a local path", "file:" + "///tmp/corpus.json"),
        ("the directory this checkout lives in",
         "cloned into a-clone-called-something-else"),
        ("the account name on this machine", "built on somebody's laptop"),
    )
    for expectation, sample in samples:
        found = machine_traces.traces_in(sample, checkout=checkout, user=user,
                                         project="international-tax-law-corpus")
        assert any(expectation in hit for hit in found), (
            f"the detector no longer catches {expectation}: {sample!r} -> {found}")


def test_a_ci_accounts_home_path_is_still_a_trace():
    """The exemption is the account name, never the path that carries it.

    A rule that excused CI by excusing anything mentioning it would be a rule
    that stops looking exactly where the worst leak would be: a home directory
    of the runner, committed.
    """
    text = "/" + "home" + "/" + "runner" + "/work/corpus/corpora/un/model.xml"
    found = machine_traces.traces_in(text, checkout=None, user="runner")
    assert found, "the path rule stopped catching a CI account's home directory"


def test_the_exempt_accounts_are_declared_where_an_exemption_can_be_reviewed():
    """A list that grows without a second edit is a list that grows by accident.

    The names are the accounts CI runs as, each one an ordinary English word the
    repositories say in their own prose. Adding one is a decision, so it changes
    two files - this one and the rule - and the copy of the rule is pinned in two
    other repositories.
    """
    assert machine_traces.CI_ACCOUNTS == frozenset({"runner", "github-actions"}), (
        "the accounts exempt from the name rule changed: state the reason here, "
        "in the rule's own docstring, and in the SPEC's F14 section")


def test_the_detector_leaves_the_declarations_alone():
    """Naming the owner and the contact is the point of these lines."""
    text = ("Copyright (c) 2026 somebody <somebody@example.com> - project\n"
            "Contact somebody@example.com before any reuse beyond reading.\n"
            "repository: somebody/international-tax-law-corpus\n"
            "badge: https://github.com/somebody/international-tax-law-corpus\n")
    assert not machine_traces.traces_in(text, checkout="international-tax-law-corpus",
                                        user="somebody",
                                        project="international-tax-law-corpus")


def test_a_github_owner_path_without_a_scheme_is_not_a_trace():
    """A link a constant builds does not spell the scheme out, and is still a link.

    `documents.LINK` is `github.com/owner/{name}` - a host and a path, not a bare
    word. The rule used to recognise an owner only behind `https://`, so on a
    desk whose account name is also the owner's this constant read as a trace of
    the machine: three failures across the two layers, and green on CI, where the
    account is `runner`. The positive half matters as much as this one - the bare
    account name is what the rule exists to catch - so both are stated here.
    """
    built = 'LINK = f"github.com/somebody/some-repository"\n'
    assert not machine_traces.traces_in(built, checkout=None, user="somebody")
    wrapped = ("[a link](https://github.com/"
               "somebody/some-repository)\n")
    assert not machine_traces.traces_in(wrapped, checkout=None, user="somebody"), (
        "a link wrapped after `github.com/` was read as a bare account name")
    bare = "somebody built this at their desk\n"
    assert machine_traces.traces_in(bare, checkout=None, user="somebody"), (
        "the account-name rule stopped catching a bare name while the owner path "
        "was being exempted")


def test_a_checkout_named_after_the_project_is_not_a_trace():
    """CI clones into the project's own name, and that name is not a machine."""
    text = "the corpus repository international-tax-law-corpus"
    assert not machine_traces.traces_in(text, checkout="international-tax-law-corpus",
                                        user=None, project="international-tax-law-corpus")
    assert machine_traces.traces_in(text, checkout="intl", user=None,
                                    project="international-tax-law-corpus") == []


def test_the_placeholder_the_catalogue_uses_is_not_a_trace():
    """`fixtures/` has to be able to say where a local path was, without one."""
    evidence = '"' + "/" + "Users" + "/<user>/Desktop/…/corpus.xml" + '"'
    assert not machine_traces.traces_in(evidence, checkout="x", user=None)
