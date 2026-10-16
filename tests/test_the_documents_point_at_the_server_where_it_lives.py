"""The prose that points a reader at the server must point at where it lives.

The server is a folder of this repository, `mcp/`, and the way in is the command
that installs it from that subfolder: no clone, and the library passed to it as a
root rather than copied into it. The documents here make that promise to a reader
who will act on it: `README.md`, which sets out what the family is, `AGENTS.md`,
which tells an agent what to run, and `mcp/README.md`, the server's own account of
what it answers and of the two variables it needs.

A promise in prose is worth what the check behind it is worth, and the library
holds the same rule over its own two documents, in a file of this name: this is
the corpus' half of it. The rule is stated twice, which this family otherwise
refuses. The discipline (`harness/discipline/`) holds what all three layers owe
alike - what may not be committed about a machine, how a workflow is read, what a
board owes a reader - and this rule is not in it because it is about each
repository's own prose. The trigger for moving it there is named rather than left
to be rediscovered, and the trigger is a third repository that needs it.

Two failures are refused, and one of them was live when this file was written:

  * the document does not give the command, so a reader who wants the server is
    told about it and not told how to get it;
  * a document sends the reader to the **standalone** repository the server was
    built in, which is private now: a reader who follows it gets nothing. That is
    what `mcp/README.md` did, in a markdown link, while the corpus' own README had
    already been through this repair and said the standalone repository is private
    and is not where a reader should be pointed. The name is not the failure - the
    package is called `international-tax-law-mcp` and its README has to be able to
    say so - the *destination* is, so the two documents a reader meets first may
    not name it at all (the library's rule, word for word) and no committed
    document may link it.

The check reads the tracked tree through the machine-trace rule's own walker, so
both read the same files and neither invents a second idea of what is committed.
"""

from pathlib import Path

import pytest

from harness.discipline import machine_traces
from support import ROOT

# The documents a reader meets before anything else, and holds the library's rule
# unchanged: the command, and no mention of the standalone repository at all.
FAMILY = ("README.md", "AGENTS.md")

# The server's own document. Its title *is* the package's name, so it is held to
# the command and to the destination, and not to silence about the name.
PACKAGE = Path("mcp") / "README.md"

# The only way in: the server, installed from the corpus' own subfolder, at main.
COMMAND = ('pip install "git+https://github.com/avvohacker/'
           'international-tax-law-corpus.git@main#subdirectory=mcp"')

# The repository the server was built in, private now: a reader sent there gets
# nothing. Named as a word in one document and as a destination in the next.
STANDALONE = "international-tax-law-mcp"
LINK = f"github.com/avvohacker/{STANDALONE}"

# How many offending lines are quoted back before the message stops growing.
QUOTED = 3

# What counts as a document: the project's prose, in the one extension every one
# of its documents is written in. The corpus' own generated views under
# `derived/` are read with it, which costs the whole set of them and spares the
# rule an exception.
DOCUMENT = "*.md"


def quotes(text: str, needle: str) -> str:
    """The lines carrying a needle, trimmed, for the failure message."""
    found = [line.strip() for line in text.splitlines() if needle in line]
    return " | ".join(found[:QUOTED])


def problems(text: str, *, strict: bool) -> list[str]:
    """Every way one document fails to say where the server lives.

    ``strict`` is for the two documents a reader meets first, where naming the
    standalone repository is itself the failure. The package's own README is not
    one of them: it has to be able to say what it is called, and what it may not
    do is send a reader to that repository.
    """
    found: list[str] = []
    if COMMAND not in text:
        found.append("it does not give the command that installs the server from "
                     f"the corpus' subfolder, word for word: {COMMAND}")
    if LINK in text:
        found.append("it links the standalone repository, which is private and is "
                     "not a way in: " + quotes(text, LINK))
    if strict and STANDALONE in text:
        found.append("it names the standalone repository, which is private and is "
                     "not where a reader should be sent: " + quotes(text, STANDALONE))
    return found


@pytest.mark.parametrize("name", FAMILY)
def test_the_family_document_points_at_the_server_in_the_corpus(name: str) -> None:
    """The command is there, word for word, and the private repository is not."""
    path = ROOT / name
    assert path.is_file(), f"{name} is missing, and a reader is sent to it"
    found = problems(path.read_text(encoding="utf-8"), strict=True)
    assert not found, "\n  ".join([f"{name}:"] + found)


def test_the_package_readme_points_at_the_server_in_the_corpus() -> None:
    """The server's own document points at this folder, not at the private one."""
    assert PACKAGE.is_file(), (f"{PACKAGE} is missing: it is the server's own "
                               "account of what it answers")
    found = problems(PACKAGE.read_text(encoding="utf-8"), strict=False)
    assert not found, "\n  ".join([f"{PACKAGE}:"] + found)


def test_no_committed_document_links_the_standalone_repository() -> None:
    """Whatever else it holds in the tree, no document sends a reader there.

    The three documents above are the ones a reader is handed; this is every
    document the repository commits, because the next one written is as free to
    paste the link as the last one was.
    """
    documents = [path for path in machine_traces.tracked(ROOT)
                 if path.match(DOCUMENT)]
    assert documents, ("no document was read at all, so this check holds nothing: "
                       f"{DOCUMENT} matched nothing under {ROOT.name}")
    offenders: list[str] = []
    for path in documents:
        text = path.read_text(encoding="utf-8")
        if LINK in text:
            offenders.append(f"{path.relative_to(ROOT)}: {quotes(text, LINK)}")
    assert not offenders, (
        f"a committed document sends a reader to the private {STANDALONE} "
        "repository:\n  " + "\n  ".join(offenders))


def test_the_check_can_fail() -> None:
    """The positive control: a rule that cannot be broken proves nothing."""
    good = (f"* **the server** — reach it with `{COMMAND}`, and pass the two roots: "
            f"this repository is the library root.\n")

    # The two documents a reader meets first: the library's rule, unchanged.
    assert problems(good, strict=True) == []

    from_the_root = good.replace("corpus.git@main#subdirectory=mcp", "corpus.git@main")
    assert problems(from_the_root, strict=True), (
        "a document that installs the server from the corpus' own root, and not "
        "from its subfolder, was accepted")

    named = good + (f"* **mcp** ([{STANDALONE}](https://github.com/avvohacker/"
                    f"{STANDALONE})) — the query mind over both\n")
    assert any(STANDALONE in problem for problem in problems(named, strict=True)), (
        f"a document that sends a reader to the private repository was accepted: "
        f"{problems(named, strict=True)}")

    # The package's own README: its name is its subject, and the link is not.
    titled = (f"# {STANDALONE}\n\n{good}\nThe standalone repository it was built "
              "in is private now, and is not a way in.\n")
    assert problems(titled, strict=False) == [], (
        f"the package's own README was refused for saying its own name: "
        f"{problems(titled, strict=False)}")
    assert problems(titled + f"\nsee {LINK}\n", strict=False), (
        "the package's README was allowed to link the private repository, which "
        "is the failure this rule exists for")
