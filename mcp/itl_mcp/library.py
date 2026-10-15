"""What the library holds, read once and read the same way by both callers.

``list_treaties`` answers from ``treaties/*/treaty.json``, and the drift control
records *that* answer as named facts. So the reading lives here rather than in
the tool: a control that re-derived the catalogue its own way would be checking
itself, and the day the tool stopped reading a field, the fixture would go on
agreeing with a payload nobody returns.

The ``library`` field of the payload is the absolute path of the checkout on the
machine that asked, which is what a caller wants from a runtime answer and is
never what a recorded one holds: the fixture is committed, and a committed path
describes the machine it was built on.
"""

from __future__ import annotations

import hashlib

from . import artefacts
from .roots import Roots


def held(roots: Roots) -> list[dict]:
    """One entry per treaty the library holds, in path order.

    Exactly the fields the README promises for this tool -- the id, the parties,
    the pages and the gaps the treaty declares on itself -- and not the title,
    which is prose: a reworded title is not an answer moving.
    """
    entries: list[dict] = []
    for path in sorted((roots.library / "treaties").glob("*/treaty.json")):
        payload = artefacts.document(path)
        entries.append({
            "id": payload.get("id", path.parent.name),
            "parties": payload.get("parties", []),
            "pages": payload.get("page_count"),
            "gaps_declared": payload.get("gaps_declared"),
            "title": payload.get("title", ""),
        })
    return entries


def listing(roots: Roots) -> dict:
    """The ``list_treaties`` payload: what is held, and what holding it is not."""
    return {
        "library": str(roots.library),
        "treaties": held(roots),
        "note": ("each treaty is held by page, not by article: the library "
                 "publishes page-anchored units, so no article-level "
                 "statement about a treaty can be made from it"),
    }


def page(roots: Roots, treaty_id: str, page: int) -> dict:
    """One page of one treaty, with the hash it was built from.

    The reading lives here, beside ``held``, for the same reason: the tool and
    the drift control that records its answer must read a page the same way. A
    control that recomputed the hash its own way would be checking itself, and
    the day the tool stopped reading a field -- a page's declared gap, say --
    the recorded fact would go on agreeing with a payload nobody returns. The
    errors are part of the answer too, and are the tool's own: a treaty the
    library does not hold, and a page it does not have, are named rather than
    raised.
    """
    path = roots.library / "treaties" / treaty_id / "treaty.json"
    if not path.is_file():
        return {"error": f"no treaty {treaty_id!r} in the library"}
    payload = artefacts.document(path)
    for unit in payload.get("units", []):
        if unit.get("page") == page:
            recomputed = hashlib.sha256(
                unit["text"].encode("utf-8")).hexdigest()
            return {
                "treaty": treaty_id,
                "page": page,
                "chars": unit.get("chars"),
                "declared_sha256": unit.get("sha256"),
                "recomputed_sha256": recomputed,
                "verified": recomputed == unit.get("sha256"),
                "gap": unit.get("gap"),
                "gap_reason": unit.get("gap_reason"),
                "text": unit.get("text"),
            }
    return {
        "error": f"{treaty_id!r} has no page {page}",
        "page_count": payload.get("page_count"),
    }
