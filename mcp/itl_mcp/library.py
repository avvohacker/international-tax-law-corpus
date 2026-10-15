"""One page of a treaty, read once and read the same way by both callers.

``read_treaty_page`` answers from ``treaties/*/treaty.json``, and the drift
control records *that* answer as named facts. So the reading lives here rather
than in the tool: a control that recomputed the hash its own way would be
checking itself, and the day the tool stopped reading a field -- a page's
declared gap, say -- the recorded fact would go on agreeing with a payload
nobody returns.

The catalogue of what the library holds is deliberately not read here any more:
listing directories is what a reader can do with the repository itself, and this
server exists for the answers a reader cannot reach that way. Where the library
does reach an answer it is through this page, whose declared hash is the
library's own statement about its text.
"""

from __future__ import annotations

import hashlib

from . import artefacts
from .roots import Roots


def page(roots: Roots, treaty_id: str, page: int) -> dict:
    """One page of one treaty, with the hash it was built from.

    The tool and the drift control that records its answer must read a page the
    same way, which is why the reading is here and not in either of them. The
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
