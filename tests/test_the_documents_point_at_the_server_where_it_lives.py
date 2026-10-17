"""The corpus' documents point a reader at the server, where it lives.

The server is a folder of this repository, `mcp/`, and the way in is one command:
`pip install` of the corpus' subfolder, with no clone. The rule about the prose
that says so is `harness/discipline/documents.py`, shared with the library, which
owes it over its own documents: the rule used to be a test in each repository, and
two readings of one rule are two rules - the library's had already found its
failure, the corpus' had not been written yet, and nothing compared them.

This file holds the corpus to that rule, and holds the rule to the failure that
made it exist. That failure was here: `mcp/README.md` linked
`https://github.com/avvohacker/international-tax-law-mcp`, the standalone
repository the server was built in, which is private now, from the paragraph about
where the server lives. The corpus' own README had already been through that
repair; the package's README had not, and nothing here would have said so. The
check was written first and run against the repository as it stood, and it named
the file, the link, and why the link is not a way in.

What is not shared, and is read here, is what the corpus owns: the document that
belongs to this checkout alone - the server's own README - and the fact that it is
the one document in which the package's name is its subject rather than a
misdirection.
"""
from pathlib import Path

from harness.discipline import documents
from support import ROOT


def test_the_corpus_documents_point_a_reader_at_the_server():
    """Every document a reader acts on, read whole, and every one linked."""
    problems = documents.check(ROOT)
    assert not problems, (
        "a document of the corpus does not say where the server lives:\n  "
        + "\n  ".join(problems))


def test_the_documents_read_are_the_ones_this_checkout_owes():
    """The checkout that holds the server owes its README as well as its own.

    Read rather than assumed: the set is what `owed` says it is, so a document
    that stopped being read is a failure here rather than a silence. The server's
    README is also the one document held to the destination rather than to
    silence about the name, because the package is called what it is called.
    """
    names, package = documents.owed(ROOT)
    assert names == [Path("README.md"), Path("AGENTS.md"),
                     Path("mcp") / "README.md"], names
    assert package == Path("mcp") / "README.md", package


def test_the_rule_refuses_a_document_that_sends_a_reader_to_the_private_repository():
    """The rule itself, on the two failures and the case that looks like one."""
    good = (f"* **the server** — reach it with `{documents.COMMAND}`, and pass the "
            f"two roots: this repository is the library root.\n")

    # The two documents a reader meets first: the command, and no name at all.
    assert documents.problems(good, package=False) == []

    from_the_root = good.replace("corpus.git@main#subdirectory=mcp", "corpus.git@main")
    assert documents.problems(from_the_root, package=False), (
        "a document that installs the server from the corpus' own root, and not "
        "from its subfolder, was accepted")

    # The owner is not spelled here, and that is the point of the sample: the
    # private repository's link is built from the rule's own constant, so this
    # fixture tests the rule rather than carrying the name of the account that
    # owns it. Written out, that name is also the account on this desk, and the
    # machine-trace rule reads it - correctly - as one.
    repository = "https://" + documents.LINK
    named = good + (f"* **mcp** ([{documents.STANDALONE}]({repository})) — the server\n")
    assert any(documents.STANDALONE in problem
               for problem in documents.problems(named, package=False)), (
        f"a document that sends a reader to the private repository was accepted: "
        f"{documents.problems(named, package=False)}")

    # The package's own README: its name is its subject, and the link is not.
    titled = (f"# {documents.STANDALONE}\n\n{good}\nThe standalone repository it "
              f"was built in is private now, and is not a way in.\n")
    assert documents.problems(titled, package=True) == [], (
        "the package's own README was refused for saying its own name: "
        f"{documents.problems(titled, package=True)}")
    assert documents.problems(titled + f"\nsee {documents.LINK}\n", package=True), (
        "the package's README was allowed to link the private repository, which "
        "is the failure this rule exists for")


def test_the_check_reads_what_it_owes_and_every_document_beside_it(tmp_path):
    """The rule at the level its callers use it: a checkout, and a broken one."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "README.md").write_text(
        f"# a repository\n\n{ROOT.name} is reached with `{documents.COMMAND}`.\n",
        encoding="utf-8")
    (checkout / "AGENTS.md").write_text(f"{documents.COMMAND}\n", encoding="utf-8")
    assert documents.check(checkout) == [], documents.check(checkout)

    (checkout / "NOTES.md").write_text(
        f"history: built in https://{documents.LINK}\n", encoding="utf-8")
    problems = documents.check(checkout)
    assert any("NOTES.md" in problem for problem in problems), (
        f"a document beside the ones a reader is handed links the private "
        f"repository and was not read: {problems}")
