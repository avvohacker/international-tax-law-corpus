"""Where the documents of a checkout send a reader who wants the server.

The server is the folder `mcp/` of the corpus, and the way in is one command:
`pip install` of the corpus' subfolder, with no clone. The prose that says so is
a small set of documents - a repository's `README.md`, its `AGENTS.md`, and the
server's own `README.md` - and it has failed in both directions already. The
library's `README.md` kept pointing at the private repository the server was
built in, found by hand; the package's `README.md` kept a markdown link to the
same repository, found by writing the check. A reader who follows either gets
nothing, which is the one failure a document about where to find something
cannot afford.

Both were then held by a test in each repository, and a rule about prose written
twice is two rules - the drift this package exists for. It is stated once here
now, and read by each repository's own test and by
`scripts/discipline-drift.py`, which reads the documents of every checkout it is
handed in one run. Which checkouts those are is the run's business, not the
rule's: the library's own run reads the corpus' documents and the library's
together, so that half cannot part company quietly, and the corpus' own run reads
what this repository holds.

The rule, in full:

  * the documents a reader acts on give the command, word for word - a document
    that says a server exists and not how to reach it is an advertisement;
  * no committed document *links* the standalone repository the server was built
    in. The name is not the failure and the destination is: the package is called
    `international-tax-law-mcp`, and the document about the package has to be
    able to say so;
  * the documents a reader meets first - the repository's own README and its
    instructions to an agent - may not name it either. Naming is what half a
    repair looks like: the corpus' README says the standalone repository is
    private and is not where a reader should be pointed, and a sentence that says
    where something is *not* is only useful next to prose that says where it is.

What counts as a document is every file a checkout tracks with the extension
every one of them is written in, and the corpus' own generated views are read
with the rest: a rule with an exception for the files it walks is a rule with a
hole in it. The tree is walked by the machine-trace rule's own walker, so one
idea of what is committed serves both rules.
"""
from __future__ import annotations

from pathlib import Path

from .machine_traces import tracked

# The only way in: the server, installed from the corpus' own subfolder, at main.
COMMAND = ('pip install "git+https://github.com/avvohacker/'
           'international-tax-law-corpus.git@main#subdirectory=mcp"')

# The repository the server was built in, private now: a reader sent there gets
# nothing. The link is the destination; the name is what the package is called.
STANDALONE = "international-tax-law-mcp"
LINK = f"github.com/avvohacker/{STANDALONE}"

# The documents a reader meets before anything else, in every repository of the
# family, and the server's own document in the checkout that holds it.
FIRST = (Path("README.md"), Path("AGENTS.md"))
PACKAGE = Path("mcp") / "README.md"

# The extension every document is written in, and the package's own directory -
# the one thing in a checkout that says "this is the server itself".
DOCUMENT = "*.md"
SERVER = "itl_mcp"

# How many offending lines a failure quotes before it stops growing.
QUOTED = 3


def quotes(text: str, needle: str) -> str:
    """The lines carrying a needle, trimmed, for a failure message."""
    found = [line.strip() for line in text.splitlines() if needle in line]
    return " | ".join(found[:QUOTED])


def problems(text: str, *, package: bool) -> list[str]:
    """Every way one document fails to say where the server lives.

    ``package`` marks the document that is *about* the package, which is the one
    place its name belongs: there, naming it is the subject and sending a reader
    to the private repository is still the failure.
    """
    found: list[str] = []
    if COMMAND not in text:
        found.append("it does not give the command that installs the server from "
                     f"the corpus' subfolder, word for word: {COMMAND}")
    if LINK in text:
        found.append("it links the standalone repository, which is private and is "
                     "not a way in: " + quotes(text, LINK))
    if not package and STANDALONE in text:
        found.append("it names the standalone repository, which is private and is "
                     "not where a reader should be sent: "
                     + quotes(text, STANDALONE))
    return found


def owed(root: Path) -> tuple[list[Path], Path | None]:
    """What this checkout owes a reader, and which of it is the package's own.

    Read from what the checkout holds rather than named per repository: a
    repository of the family owes its `README.md` and its `AGENTS.md`; the
    checkout that holds the server owes the server's `README.md` as well; and the
    checkout that *is* the server owes that document alone, because a folder
    carries no agent instructions of its own and its `README.md` is the same file
    the corpus reads under `mcp/`.
    """
    if (root / SERVER).is_dir():
        return [Path("README.md")], Path("README.md")
    documents = list(FIRST)
    if (root / PACKAGE).parent.is_dir():
        documents.append(PACKAGE)
        return documents, PACKAGE
    return documents, None


def check(root: Path) -> list[str]:
    """Every way this checkout's documents fail to say where the server lives.

    The documents a reader acts on are read whole, and then every committed
    document is read for the one thing that is wrong wherever it appears: the
    link to the private repository.
    """
    documents, package = owed(root)
    found: list[str] = []
    for name in documents:
        path = root / name
        if not path.is_file():
            found.append(f"{name}: it is missing, and a reader is sent to it")
            continue
        text = path.read_text(encoding="utf-8")
        found += [f"{name}: {problem}"
                  for problem in problems(text, package=(name == package))]

    read = 0
    for path in tracked(root):
        if not path.match(DOCUMENT):
            continue
        read += 1
        text = path.read_text(encoding="utf-8")
        if LINK in text:
            found.append(f"{path.relative_to(root)}: it links the private "
                         f"{STANDALONE} repository: " + quotes(text, LINK))
    if not read:
        found.append(f"no document was read at all, so the sweep holds nothing: "
                     f"{DOCUMENT} matched nothing under {root.name}")
    return found
