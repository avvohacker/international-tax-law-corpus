"""The reservation-scope question, answered on its own.

``verdict.py`` answers the whole question -- what the MLI does to a treaty --
and carries every reservation's own list of agreements inside that chain. This
module answers the single question an agent usually actually has: is this
treaty inside the reservation a party filed on MLI Article N? The answer
travels with the printed row and the page it stands on, so the match can be
checked at the source rather than believed.

What it reads is the committed artefacts only: the library's treaty for the two
parties, and the corpus's position documents for what each party filed. The
loaders and the jurisdiction matching are ``verdict.py``'s own -- a second
matcher would eventually disagree with the first, and that disagreement would
surface as a wrong answer rather than as a bug.

The rule this module keeps hardest is the one the chain already keeps: a list
the corpus could not read leaves the question open and answers ``None`` with the
reader's own reason. It never answers "not on the list", because turning a gap
in the data into a finding about the treaty is the one mistake this project's
voice exists to prevent.
"""

from __future__ import annotations

import re

from . import artefacts
from .roots import Roots
from .verdict import _load_position, _scope_lookup
from .verify import verify_all, verify_position, verify_treaty


class CannotAnswer(Exception):
    """The data cannot frame the question: no such treaty, or not two parties.

    Carried as its own exception, with the reason in words, so the tool above
    can report a refusal instead of a traceback -- the shape
    ``verdict.Undecidable`` has for the chain.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def refusal(reason: str) -> dict:
    """The payload a reservation refusal carries: the question the data could
    not frame, and the note that a refusal is this server's answer rather than
    a guess.

    One builder, called by the tool and by the drift control, so the two cannot
    come to carry different refusals -- which they had.
    """
    return {
        "verdict": "undecidable",
        "reason": reason,
        "note": ("this is a real answer: the data cannot frame the "
                 "question, and this server does not guess"),
    }


def unverifiable(message: str) -> dict:
    """The payload for an artefact that does not match the hash it declares.

    Shared the same way ``refusal`` is, and for the same reason.
    """
    return {
        "error": message,
        "note": ("nothing is answered from an artefact that does not match "
                 "the hash the project declares for it"),
    }


# A caller may name an Article the way a document prints it ("Article 4") or
# the way the corpus keys it ("4"). The corpus's key is what the position
# artefacts are filed under, so the argument is normalised to it here and the
# normalised form is reported back, rather than assumed to be bare digits.
_ARTICLE_RE = re.compile(r"^(?:article\s+)?(\S+)$", re.IGNORECASE)


def article_key(raw: str) -> str:
    """The corpus's key for one MLI Article, from however a caller wrote it."""
    match = _ARTICLE_RE.match(raw.strip())
    return match.group(1) if match else raw.strip()


def _sort_key(number: str):
    """Section numbers sorted as numbers, and anything else after them."""
    return (0, int(number), "") if str(number).isdigit() else (1, 0, str(number))


def _why(lookup: dict, lists: list[dict], readable: list[dict],
         counterparty: str | None, announced: bool) -> str:
    """One sentence saying where an answer came from, or why there is none."""
    if lookup["verdict"] is True:
        row = lookup["evidence"][0]
        return (f"the list this statement prints names {counterparty} at row "
                f"{row.get('no')} on page {row.get('page')}: "
                f"{row.get('provision')!r}")
    if lookup["verdict"] is False:
        rows = sum(len(one.get("rows") or []) for one in readable)
        return (f"the {len(readable)} list(s) this statement prints were read "
                f"({rows} row(s) together) and none names {counterparty}")
    if readable:
        # The lookup answers None with nothing to look for: a statement whose
        # list was read places no agreement anywhere when the counterparty is
        # not nameable, and saying that is different from saying "no".
        return (f"the counterparty to look for could not be named, so the "
                f"{len(readable)} list(s) this statement prints place no "
                f"agreement inside the reservation")
    if lists:
        reasons = "; ".join(str(one.get("reason") or "") for one in lists)
        return (f"the statement announces a list of agreements and the corpus "
                f"could not read its table: {reasons}")
    if announced:
        return ("the statement's own words announce a list of agreements "
                "('following agreement') and the corpus holds no table under "
                "that sentence, so the question is left open rather than "
                "answered 'no'")
    return ("the statement prints no list of agreements under it, so nothing "
            "in this data places an agreement inside it")


def _statements(position: dict | None, article: str,
                counterparty: str | None) -> list[dict]:
    """The reservations this position files on this Article, each answered.

    Only statements the corpus read as ``Reservation`` are listed: a
    notification or a choice prints tables of its own, but a notification does
    not withhold an Article, and reading its table as a reservation's scope
    would put agreements under words that do not act on them.

    Each entry carries the reading *and* the answer, so a caller that disagrees
    with the answer still has the row it was drawn from. ``answer`` is
    three-valued on purpose: ``True`` when a list the statement prints names
    the counterparty, ``False`` when the lists it prints were read and none
    names it, and ``None`` when no list could be read or none is printed --
    which is not the same fact as "not on the list".
    """
    if position is None:
        return []
    entries = list((position.get("article_sections") or {}).get(article) or [])
    found: list[dict] = []
    for entry in entries:
        if str(entry.get("kind")) != "Reservation":
            continue
        lists = list(entry.get("scope_lists") or [])
        readable = [one for one in lists if one.get("read")]
        # The lookup is verdict.py's own, so this tool and the chain answer with
        # the same matcher and the same evidence keys.
        lookup = _scope_lookup(readable, counterparty)
        announced = "following agreement" in str(entry.get("excerpt") or "").lower()
        found.append({
            "page": entry.get("page"),
            "option_title": entry.get("option_title") or "",
            "statement": entry.get("excerpt") or "",
            "lists": [
                {"page": one.get("page"),
                 "rows": len(one.get("rows") or []),
                 "read": bool(one.get("read")),
                 "headings": one.get("headings") or [],
                 **({"reason": one.get("reason")} if not one.get("read") else {})}
                for one in lists
            ],
            "answer": lookup["verdict"],
            "evidence": lookup["evidence"],
            "why": _why(lookup, lists, readable, counterparty, announced),
            # A statement whose words announce a list and whose table the
            # corpus does not hold: reported rather than passed over, because
            # it is the one case where "no list" and "an unread list" look
            # alike from outside.
            "announces_a_list_not_captured": bool(announced and not readable),
        })
    return found


def _nothing_filed(position: dict | None, article: str, party: str) -> str:
    """Why one party's documents answer nothing on this Article.

    Told apart on purpose: no position document at all, a document with no
    section for the Article, and a section that files no reservation are three
    different facts, and collapsing them would hide which one the answer rests
    on.
    """
    if position is None:
        return (f"the corpus holds no MLI position document filed by {party}, "
                f"so nothing can be read about what {party} reserved")
    sections = position.get("article_sections") or {}
    entries = list(sections.get(article) or [])
    if article not in sections:
        numbers = ", ".join(sorted(sections, key=_sort_key)) or "none"
        return (f"{party}'s position document prints no Article {article} "
                f"section; the sections it prints are {numbers}")
    if not entries:
        return (f"{party}'s position document files nothing at all under "
                f"Article {article}")
    kinds = sorted({str(entry.get("kind") or "?") for entry in entries})
    return (f"{party}'s position document files no reservation under Article "
            f"{article}: the {len(entries)} statement(s) it files there are "
            f"of kind {', '.join(kinds)}")


def _party_reading(position: dict | None, article: str, party: str,
                   counterparty: str) -> dict:
    """One party's answer, its statements, and the words behind both."""
    statements = _statements(position, article, counterparty)
    answers = [statement["answer"] for statement in statements]
    if not statements:
        answer = None
        why = _nothing_filed(position, article, party)
    elif any(value is True for value in answers):
        answer = True
        why = f"{party}'s own list names {counterparty}"
    elif any(value is None for value in answers):
        # One unread list is enough to keep the party's answer open: a no from
        # a sibling statement cannot close a question another table holds.
        answer = None
        why = ("a list a reservation on this Article prints is not read, so "
               "the question stays open for this party")
    else:
        answer = False
        why = (f"every list a reservation on this Article prints was read and "
               f"none names {counterparty}")
    return {
        "party": party,
        "counterparty": counterparty,
        "position_document": (position or {}).get("slug"),
        "statements": statements,
        "answer": answer,
        "why": why,
    }


def scope(roots: Roots, treaty_id: str, mli_article: str) -> dict:
    """Answer: is this treaty inside the reservation each party filed on this Article?

    Raises ``CannotAnswer`` when the question cannot be framed at all -- the
    library holds no such treaty, or cannot name its two parties -- and
    ``verify.VerificationError`` when an artefact it read does not match the
    hash that artefact declares. Neither is guessed through: the checks run
    before any reasoning, exactly as the chain's do.

    The answer reported for one party is three-valued. ``True`` means a list
    that party prints names this treaty; ``False`` means the lists it prints
    were read and none names it; ``None`` means there is no list to read, or a
    list the corpus could not read. The answer for the treaty as a whole is
    true if any party's list names it, false only when every party whose
    position document the corpus holds answered false, and null otherwise --
    so a party that files nothing leaves the treaty's question open instead of
    silently closing it.
    """
    path = roots.library / "treaties" / treaty_id / "treaty.json"
    if not path.is_file():
        raise CannotAnswer(
            f"the library holds no treaty {treaty_id!r}; the library holds one "
            f"directory per treaty, under its own treaties/ folder"
        )
    article = article_key(mli_article)

    checks = list(verify_treaty(roots.library, treaty_id))
    verify_all(checks)
    treaty = artefacts.document(path)

    parties = list(treaty.get("parties", []))
    if len(parties) != 2:
        raise CannotAnswer(
            f"the library declares {len(parties)} parties for {treaty_id!r}, "
            f"not two; a reservation's list names the OTHER contracting "
            f"state, so the question needs both and this server will not "
            f"invent the missing one"
        )

    loaded: list[tuple[str, str, dict | None]] = []
    for index, party in enumerate(parties):
        position = _load_position(roots.corpus, party)
        if position is not None:
            checks += list(verify_position(roots.corpus,
                                           str(position.get("slug") or "")))
        loaded.append((party, parties[1 - index], position))
    verify_all(checks)          # refuses before reasoning if a hash disagrees

    readings = [_party_reading(position, article, party, counterparty)
                for party, counterparty, position in loaded]
    filed = [reading["answer"] for reading in readings
             if reading["position_document"]]
    if any(value is True for value in filed):
        answer: bool | None = True
    elif not filed or any(value is None for value in filed):
        answer = None
    else:
        answer = False

    return {
        "treaty": {
            "id": treaty_id,
            "title": treaty.get("title", ""),
            "parties": parties,
            "pages": treaty.get("page_count"),
        },
        "mli_article": article,
        "question": (f"Does this treaty fall inside the reservation each party "
                     f"filed on MLI Article {article}?"),
        "parties": readings,
        "answer": answer,
        "answered_by": [reading["party"] for reading in readings
                        if reading["answer"] is True],
        "answer_is": (
            "true when a list one party prints names this treaty; false when "
            "every party whose position document the corpus holds answered "
            "false on this Article; null when no such list could be read, "
            "when a party that filed a document has a list on this Article "
            "the corpus could not read, or when no document the corpus holds "
            "files a reservation on this Article"
        ),
        "note": (
            "This answers what the parties' own lists print, not which "
            "modification ends up applying to the treaty: the corpus does not "
            "hold the Convention's compatibility clauses, so "
            "as_modified_verdict is the tool for the effect and this one for "
            "the list."
        ),
        "checks": [check.as_dict() for check in checks],
    }
