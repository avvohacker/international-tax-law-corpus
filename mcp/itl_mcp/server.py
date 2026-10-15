"""The MCP server: the tools an agent calls, and what each one refuses.

Every tool here answers from the corpus and library checkouts, cites the units
it used, and says so plainly when the data cannot answer. The server never
reaches for the network and never reads a PDF: it reads the committed JSON and
the hashes the projects declare about it.

Run it with the two roots named:

    ITL_CORPUS_ROOT=/path/to/corpus \\
    ITL_LIBRARY_ROOT=/path/to/library \\
    itl-mcp
"""

from __future__ import annotations

import json

from mcp.server import MCPServer

from .roots import RootsError, load_roots
from .verdict import Undecidable, as_modified, refusal

mcp = MCPServer(
    "international-tax-law",
    title="International tax law corpus and library",
    description=(
        "Answers questions about the UN Model Tax Convention, the OECD MLI, "
        "and the bilateral treaties in the library — from the committed data, "
        "with citations, and with silence where the data is silent."
    ),
    instructions=(
        "Every answer this server gives is traceable to a committed artefact "
        "and carries the hashes it was verified against. When a tool reports "
        "a silence or an undecidable verdict, that IS the answer: the data "
        "cannot say more, and guessing would be inventing. Do not fill the "
        "gaps on this server's behalf."
    ),
    version="0.1.0",
)

# Resolved once at import so a misconfigured checkout fails at startup with a
# clear message, not on the first question.
try:
    ROOTS = load_roots()
except RootsError as error:
    raise SystemExit(f"international-tax-law-mcp: {error}") from error


def _pretty(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def as_modified_verdict(treaty_id: str) -> str:
    """What the MLI does to one treaty in the library, with the chain shown.

    Args:
        treaty_id: the treaty's stable slug, e.g. "uk-us-2001". Use
            list_treaties() to see what the library holds.
    """
    try:
        verdict = as_modified(ROOTS, treaty_id)
    except Undecidable as error:
        return _pretty(refusal(error.reason))
    return _pretty(verdict.as_dict())


@mcp.tool()
def list_treaties() -> str:
    """The treaties the library holds, with their parties and declared gaps."""
    # The reading is `itl_mcp.library`'s, not this function's: the drift control
    # records this answer as named facts, and it can only record what the tool
    # really returns if both call the same reader.
    from .library import listing

    return _pretty(listing(ROOTS))


@mcp.tool()
def read_treaty_page(treaty_id: str, page: int) -> str:
    """One page of one treaty, with the hash that page was built from.

    Args:
        treaty_id: the treaty's stable slug, e.g. "uk-us-2001".
        page: the 1-based page number, from 1 to the treaty's page_count.
    """
    # One reading, in `itl_mcp.library`, taken by this tool and by the drift
    # control that records its answer: a control that recomputed the hash its
    # own way would be checking itself, and the day this tool stopped reading a
    # field the recorded fact would go on agreeing with a payload nobody
    # returns.
    from .library import page as read_page

    return _pretty(read_page(ROOTS, treaty_id, page))


@mcp.tool()
def mli_status(jurisdiction: str) -> str:
    """One jurisdiction's MLI standing: signed, deposited, in force.

    Args:
        jurisdiction: a country name as the MLI table prints it, or any
            normalised form, e.g. "United Kingdom" or "Italy".
    """
    # One reading, in `itl_mcp.verdict`, taken by this tool and by the drift
    # control that records its answer: a control that built the payload its own
    # way would be checking itself, and this one had already stopped carrying
    # the match method.
    from .verdict import status as mli_standing

    return _pretty(mli_standing(ROOTS, jurisdiction))


@mcp.tool()
def compare_model_editions(article: str) -> str:
    """One UN Model Article in both editions, and the edition that is silent.

    The 2017 and 2021 editions are two documents, and one of them may print no
    Article where the other does: Article 12B exists only in 2021. This tool
    cites the units of each edition from its own node index and says plainly
    which edition is silent, rather than answering from the edition that
    happens to have the provision.

    Args:
        article: the Article number as the document prints it, e.g. "5",
            "12B", "23 A".
    """
    # One reading, in `itl_mcp.editions`, taken by this tool and by the drift
    # control that records its answer -- including the refusal, which the two
    # had come to carry differently.
    from .editions import compare, uncomparable

    try:
        answer = compare(ROOTS.corpus, article)
    except (FileNotFoundError, ValueError) as error:
        return _pretty(uncomparable(str(error)))
    return _pretty(answer)


@mcp.tool()
def reservation_scope(treaty_id: str, mli_article: str) -> str:
    """Is this treaty inside the reservation a party filed on one MLI Article?

    The answer is the list of agreements a reservation prints under itself, and
    it travels with the row and the page that name this treaty -- or with the
    rows of the list that was read and does not name it -- so the match can be
    checked at the source and rejected. A list the corpus could not read leaves
    the answer null with the reader's own reason: a gap in the data is never
    reported as "not on the list".

    Args:
        treaty_id: the treaty's stable slug, e.g. "no-uk-2013". Use
            list_treaties() to see what the library holds.
        mli_article: the MLI Article, e.g. "4", "7", "17".
    """
    from .reservations import CannotAnswer, refusal, scope, unverifiable
    from .verify import VerificationError

    try:
        payload = scope(ROOTS, treaty_id, mli_article)
    except CannotAnswer as error:
        return _pretty(refusal(error.reason))
    except VerificationError as error:
        return _pretty(unverifiable(str(error)))
    return _pretty(payload)


@mcp.tool()
def sources() -> str:
    """What this server reads, from where, and how each artefact was verified."""
    # One reading, in `itl_mcp.verify`, taken by this tool and by the drift
    # control that records its answer. The two roots are added here alone: they
    # are where this process read from, and the control never records a path.
    from .verify import sources as walk

    return _pretty({
        "corpus_root": str(ROOTS.corpus),
        "library_root": str(ROOTS.library),
        **walk(ROOTS),
    })


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
