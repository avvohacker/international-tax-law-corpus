"""What a careful reader gets from the same files, with no server.

This is the baseline the README's comparison is measured against: a reader that
never calls a tool, reads exactly the artefacts the server reads, and applies the
plainest rule each question suggests. It is deliberately not a strawman, and it
is deliberately not one reader: three variants are implemented, because the point
is to find *which* habit decides the answer.

* ``strict`` — a name matches when it is the name the table prints, character for
  character. This is what a reader does who has no reason to suspect a footnote
  marker, and it is how the corpus itself spells some of its countries.
* ``helpful`` — the same reader, normalising: case-folded, the marker stripped,
  and a name allowed to match a longer official form that begins with it. This is
  what a reader does who has met the marker before.
* ``analogy`` — ``helpful``, plus the habit of answering what it cannot find: a
treaty the library does not hold comes back as a treaty the MLI does not modify.

None of the three imports ``itl_mcp``: a baseline computed by the thing under
test would be the server grading itself. And note the habit none of them can
avoid, because it is not a habit but a missing rule: reading a statement that
*announces* a list as though the list had been captured, which turns a question
the data cannot frame into a "not on the list". That is measured below, not
engineered away.

The transcript it returns is the shape ``score_answers.py --score`` reads, and the
shape a model's answers are transcribed into, so the same key and the same
counters apply to both.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# The four questions, in the order the README asks them, with the id each answer
# is filed under. The ids are the drift control's own naming, so a transcript is
# comparable with the recorded fixture without a second glossary.
US_UK = "as_modified_verdict(treaty_id='uk-us-2001')"
NO_UK = "as_modified_verdict(treaty_id='no-uk-2013')"
ARTICLE_7 = "reservation_scope(mli_article='7', treaty_id='no-uk-2013')"
UNKNOWN_TREATY = "as_modified_verdict(treaty_id='no-treaty-lives-here')"

QUESTIONS = (US_UK, NO_UK, ARTICLE_7, UNKNOWN_TREATY)


def document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def signatory_rows(corpus: Path) -> list[dict]:
    """The table as it prints itself: ``jurisdiction``, ``no``, ``page``."""
    return document(corpus / "corpora" / "mli" / "signatories-and-parties.json")["rows"]


def position_documents(corpus: Path) -> dict[str, dict]:
    """Every published MLI position, by slug."""
    found: dict[str, dict] = {}
    for path in sorted((corpus / "corpora" / "mli" / "positions").glob("*.json")):
        if path.name == "batch-report.json":
            continue
        payload = document(path)
        if payload.get("country"):
            found[path.stem] = payload
    return found


def treaty(library: Path, treaty_id: str) -> dict | None:
    path = library / "treaties" / treaty_id / "treaty.json"
    return document(path) if path.is_file() else None


def _normalised(name: str) -> str:
    """A name with the footnote marker and the case removed, and nothing else."""
    return re.sub(r"\s+", " ", name.replace("*", " ")).strip().casefold()


def matches(printed: str, wanted: str, *, helpful: bool) -> bool:
    """Whether a reader would take ``printed`` to be ``wanted``."""
    if printed == wanted:
        return True
    if not helpful:
        return False
    left, right = _normalised(printed), _normalised(wanted)
    if left == right:
        return True
    # A longer official form and the shorter one a table prints: leading words.
    return left.startswith(right) or right.startswith(left)


def find_row(rows: list[dict], wanted: str, *, helpful: bool) -> dict | None:
    for row in rows:
        if matches(str(row.get("jurisdiction") or ""), wanted, helpful=helpful):
            return row
    return None


def find_position(documents: dict[str, dict], party: str, *,
                  helpful: bool) -> tuple[str, dict] | None:
    for slug, payload in documents.items():
        if matches(str(payload.get("country") or ""), party, helpful=helpful):
            return slug, payload
    return None


def listed_row(payload: dict, counterparty: str, *, helpful: bool) -> dict | None:
    """The row that names the counterparty in a document's covered agreements."""
    for row in payload.get("covered_agreements") or []:
        if matches(str(row.get("other_jurisdiction") or ""), counterparty,
                   helpful=helpful):
            return row
    return None


def answer(reader: str, corpus: Path, library: Path) -> dict:
    """One variant's answers to the four questions, as a transcript.

    The rules, stated once so they can be argued with rather than inferred:

    1. a party's MLI standing is the row whose ``jurisdiction`` is its name;
    2. the MLI modifies a treaty when **both** parties are found in the table;
    3. a reservation's scope is the list its statement prints under the Article,
       and a statement that announces one has files that were read;
    4. a treaty the reader cannot find is a treaty the MLI does not modify (the
       ``analogy`` variant only; the other two report that they cannot find it).
    """
    helpful = reader in ("helpful", "analogy")
    rows = signatory_rows(corpus)
    documents = position_documents(corpus)
    answers: list[dict] = []

    # 1 and 2: the two verdicts.
    for question, treaty_id in ((US_UK, "uk-us-2001"), (NO_UK, "no-uk-2013")):
        held = treaty(library, treaty_id)
        if held is None:
            answers.append({"question": question, "verdict": "undecidable",
                            "citations": []})
            continue
        parties = [str(party) for party in held.get("parties") or []]
        found = {party: find_row(rows, party, helpful=helpful) for party in parties}
        citations: list[list] = []
        for party, row in found.items():
            if row is not None:
                citations.append(["signatories", row.get("page"), row.get("no")])
                continue
            # A party the reader cannot find in the table: its counterparty's own
            # table may still name the treaty, so a reader that looks there finds
            # a row and cites it.
            for other in parties:
                if other == party:
                    continue
                position = find_position(documents, other, helpful=helpful)
                if position is None:
                    continue
                printed = listed_row(position[1], party, helpful=helpful)
                if printed is not None:
                    citations.append([position[0], printed.get("page"),
                                      printed.get("no")])
        both = all(row is not None for row in found.values())
        answers.append({"question": question,
                        "verdict": "modified" if both else "not-modified",
                        "citations": citations})

    # 3: is the treaty inside the Article 7 reservation?
    held = treaty(library, "no-uk-2013")
    parties = [str(party) for party in (held or {}).get("parties") or []]
    inside = False
    citations = []
    statements_seen = 0
    for party in parties:
        position = find_position(documents, party, helpful=helpful)
        if position is None:
            continue
        slug, payload = position
        for statement in (payload.get("article_sections") or {}).get("7") or []:
            statements_seen += 1
            for printed_list in statement.get("scope_lists") or []:
                for row in printed_list.get("rows") or []:
                    for other in parties:
                        if other != party and matches(
                                str(row.get("other_jurisdiction") or ""), other,
                                helpful=helpful):
                            inside = True
                            citations.append([slug, row.get("page"), row.get("no")])
    answers.append({"question": ARTICLE_7,
                    "verdict": inside if statements_seen else False,
                    "citations": citations})

    # 4: a treaty the library does not hold. Not finding a file is not a finding
    # about the treaty, and the temptation to treat it as one is the variant.
    held = treaty(library, "no-treaty-lives-here")
    if held is None:
        verdict = "not-modified" if reader == "analogy" else "undecidable"
    else:
        verdict = "not-modified"
    answers.append({"question": UNKNOWN_TREATY, "verdict": verdict,
                    "citations": []})

    return {"reader": f"plain-reader:{reader}", "answers": answers}


READERS = ("strict", "helpful", "analogy")


def transcripts(corpus: Path, library: Path) -> list[dict]:
    return [answer(reader, corpus, library) for reader in READERS]
