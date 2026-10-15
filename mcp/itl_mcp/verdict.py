"""The as-modified verdict: what the MLI does to a treaty, from the data.

This is the promise the repository README makes -- "as-modified verdicts: the
treaty as the MLI positions modify it, with the chain shown" -- implemented
against what the two repositories actually hold.

The reasoning it performs, and the data each step rests on:

1. The treaty and its two contracting parties come from the library, with the
   page hashes recomputed.
2. Each party is looked up in the corpus's MLI signatories-and-parties table.
   A party that appears there with a date of entry into force is an MLI party
   as of that date.
3. A Covered Tax Agreement is modified by the MLI only once the MLI is in
   force for BOTH parties to it. So the verdict needs both sides, not one.
4. Whether the specific treaty is listed as covered is read from the position
   document of whichever party filed one: its ``covered_agreements`` table.

One premise in step 3 is NOT in this project's data: the corpus holds the MLI
mapping, the signatories table and the country positions, but not the MLI
convention's own text, so the rule "in force for both parties" cannot be cited
to a corpus page. It is therefore carried in ``assumptions``, clearly marked
as coming from outside the data, rather than dressed up as a finding.

And one link is constructed rather than looked up: nothing in either
repository keys a library treaty to a row of a covered-agreements table. The
match is made by counterparty name plus signature date, the two facts both
documents print. That inference is reported as such, with its evidence, so a
reader can reject it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import artefacts
from .roots import Roots
from .verify import (
    Check,
    verify_all,
    verify_mapping,
    verify_position,
    verify_signatories,
    verify_treaty,
)

# The MLI modifies a Covered Tax Agreement only when it is in force for both
# contracting parties. This is the MLI convention's own rule; the corpus does
# not hold that text, so it is stated here as an assumption and reported to
# the caller as one.
ASSUMPTION_BOTH_PARTIES = (
    "The MLI modifies a Covered Tax Agreement only once the MLI is in force "
    "for both parties to that agreement. This rule is the MLI convention's "
    "own and is NOT held in this project's data: the corpus carries the MLI "
    "mapping, the signatories table and the country positions, but not the "
    "convention text. Treat it as a premise imported from outside the data."
)

# Which of the corpus mapping's modes describe an Article that changes a
# Covered Tax Agreement. An Article the mapping records as ``none``
# (definitional) or ``admin`` (when the Convention's provisions take effect)
# carries positions but modifies no provision of a treaty, so it is kept out of
# the chain rather than listed as a modification. ``support`` is the same kind
# of case: it describes machinery the Convention relies on, not a change to a
# treaty.
MODIFYING_MODES = {"overlay", "preamble", "arbitration_part_vi"}

# The words a position document uses when it withholds an Article's entirety.
# The corpus keeps every statement verbatim, so this is a declared reading of
# the document's own sentence, not a paraphrase of it.
FULL_RESERVATION = re.compile(
    r"entirety of Article\s+(\d+)\s+not to apply", re.IGNORECASE)

# What turns an absolute reservation into a conditional one. A statement that
# carries one of these is reported as qualified, and the qualifier is named,
# so a reservation that holds only where the treaty already contains something
# is never presented as an unconditional one.
QUALIFYING_MARKERS = (
    "to the extent",
    "that already contain",
    "that do not contain",
)


# Footnote markers the corpus's own harness preserves verbatim in jurisdiction
# names (``United Kingdom*``). They are layout, not part of the name, so they
# are stripped for matching -- and the stripped form is reported, so the
# caller can see that a marker was there.
FOOTNOTE_MARKERS = "*†‡*"


@dataclass
class PartyStatus:
    """One contracting party's MLI standing, as the table has it."""

    party: str                       # the name the library gives
    matched: str | None              # the jurisdiction name as the table spells it
    row: dict | None                 # the full row, when one was found
    method: str                      # how the match was made, in words
    page: int | None = None
    ambiguous: bool = False          # several rows could match; none was picked

    @property
    def is_mli_party(self) -> bool:
        return self.row is not None and bool(self.row.get("entry_into_force"))

    @property
    def in_force_since(self) -> str | None:
        return (self.row or {}).get("entry_into_force")

    @property
    def signed(self) -> str | None:
        return (self.row or {}).get("signature")

    @property
    def deposited(self) -> str | None:
        return (self.row or {}).get("deposit")


@dataclass
class CoveredFinding:
    """Whether one party's position document lists this treaty as covered.

    ``filer`` is the party whose position document was read; ``counterparty``
    is the state that document is searched for. They are kept apart because a
    covered-agreements table belongs to the party that filed it and names the
    other state, so attributing the finding to the wrong one would read as a
    claim that the wrong country filed it.
    """

    filer: str                       # whose position document this is
    counterparty: str                # the state that document names
    has_position: bool
    listed: bool
    entry: dict | None = None
    method: str = ""
    note: str = ""


@dataclass
class MliArticle:
    """One Article of the MLI, beside what each party's own position says.

    The title, the mode, the target provisions and the note come from the
    corpus's own Article-to-provision mapping. ``recorded`` holds, per party,
    the reservations, notifications and choices that party's position document
    files on this Article, exactly as the corpus keeps them -- with the page
    each appears on and the statement itself.
    """

    number: str
    title: str
    mode: str
    convention_page: int | None
    targets: list[str]
    effect: str
    recorded: dict[str, list[dict]] = field(default_factory=dict)
    reservations_in_full: list[dict] = field(default_factory=list)
    reading: str = ""

    def as_dict(self) -> dict:
        return {
            "mli_article": self.number,
            "title": self.title,
            "mode": self.mode,
            "mli_convention_page": self.convention_page,
            "targets_treaty_articles": self.targets,
            "what_it_does": self.effect,
            "recorded_by": sorted(self.recorded),
            "recorded": self.recorded,
            "reservations_of_the_entirety": self.reservations_in_full,
            "reading": self.reading,
        }


@dataclass(frozen=True)
class Named:
    """One sentence of an answer, with the stable name of the thing it is.

    The species is that name and the reason is the sentence. Four lists a
    reader is promised beside the answer itself are built from these: the
    silences (each by the species of limit it is), the reasoning steps (each by
    the kind and subject it holds), the assumptions (each by the rule it
    imports from outside the data) and the constructed links (each by the entry
    it joins). Naming a sentence where it is written, rather than reading it
    back out of the sentence later, is what lets the drift control record it as
    a fact of its own kind: a reworded sentence moves one fact, and a kind
    appearing or disappearing is a fact appearing or disappearing, never a
    count moving under an index.
    """

    species: str
    reason: str


def _named(items: list[Named]) -> list[dict]:
    """The named sentences as the payload carries them: species beside reason."""
    return [{"species": item.species, "reason": item.reason} for item in items]


@dataclass
class Verdict:
    treaty_id: str
    title: str
    parties: list[str]
    source_sha256: str
    pages: int
    status: list[PartyStatus]
    covered: list[CoveredFinding]
    verdict: str                     # modified | not-modified | undecidable
    reasoning_with_species: list[Named]
    assumptions_with_species: list[Named] = field(default_factory=list)
    constructed_links_with_species: list[Named] = field(default_factory=list)
    silences_with_species: list[Named] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    articles: list[MliArticle] = field(default_factory=list)
    as_of: str | None = None

    # The plain sentences a reader is promised, beside the named forms the
    # drift control records. Each is the same list read for its reasons alone.
    @property
    def reasoning(self) -> list[str]:
        return [item.reason for item in self.reasoning_with_species]

    @property
    def assumptions(self) -> list[str]:
        return [item.reason for item in self.assumptions_with_species]

    @property
    def constructed_links(self) -> list[str]:
        return [item.reason for item in self.constructed_links_with_species]

    @property
    def silences(self) -> list[str]:
        return [item.reason for item in self.silences_with_species]

    def as_dict(self) -> dict:
        return {
            "treaty": self.treaty_id,
            "title": self.title,
            "parties": self.parties,
            "source_sha256": self.source_sha256,
            "pages": self.pages,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "reasoning_with_species": _named(self.reasoning_with_species),
            "mli_status": [
                {
                    "party": s.party,
                    "table_spelling": s.matched,
                    "found_in_table": s.row is not None,
                    "is_mli_party": s.is_mli_party,
                    "signed": s.signed,
                    "deposited": s.deposited,
                    "in_force_since": s.in_force_since,
                    "page": s.page,
                    "match_method": s.method,
                }
                for s in self.status
            ],
            "covered_agreement_lookups": [
                {
                    "position_document_of": c.filer,
                    "searched_for_state": c.counterparty,
                    "position_file_exists": c.has_position,
                    "treaty_listed_as_covered": c.listed,
                    "match_method": c.method,
                    "note": c.note,
                    "entry": c.entry,
                }
                for c in self.covered
            ],
            "mli_articles": [a.as_dict() for a in self.articles],
            "assumptions": self.assumptions,
            "assumptions_with_species": _named(self.assumptions_with_species),
            "constructed_links": self.constructed_links,
            "constructed_links_with_species":
                _named(self.constructed_links_with_species),
            "silences": self.silences,
            "silences_with_species": _named(self.silences_with_species),
            "provenance": {
                "status_as_of": self.as_of,
                "checks": [c.as_dict() for c in self.checks],
            },
        }


class Undecidable(Exception):
    """The data cannot decide; the caller must be told so, not guessed at."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def refusal(reason: str) -> dict:
    """The payload a verdict refusal carries: why the data cannot decide, and
    the note that a refusal is this server's answer rather than a guess.

    One builder, called by the tool and by the drift control, so the two cannot
    come to carry different refusals -- which they had.
    """
    return {
        "verdict": "undecidable",
        "reason": reason,
        "note": ("this is a real answer: the data cannot decide, and this "
                 "server does not guess"),
    }


def normalise(name: str) -> str:
    """Strip footnote markers and collapse the whitespace around them."""
    cleaned = name.strip()
    for marker in FOOTNOTE_MARKERS:
        cleaned = cleaned.replace(marker, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _signature_date_in_title(title: str) -> str | None:
    """Pull ``24 July 2001``-style dates out of a treaty title.

    Titles print the signature date in prose. This reads it for the match and
    says so; it is not a structured field anybody published.
    """
    months = ("January|February|March|April|May|June|July|August|September|"
              "October|November|December")
    found = re.search(rf"(\d{{1,2}})\s+({months})\s+(\d{{4}})", title)
    if not found:
        return None
    return f"{found.group(1)} {found.group(2)} {found.group(3)}"


def _to_ddmmyyyy(text: str) -> str | None:
    """``24-07-2001`` -> ``24 July 2001``, for comparing against a title."""
    parts = text.strip().split("-")
    if len(parts) != 3:
        return None
    day, month, year = parts
    names = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
    try:
        return f"{int(day)} {names[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return None


def _shares_leading_words(a: str, b: str) -> bool:
    """Whether one name's leading words are the other's, on word boundaries.

    The library spells a party in full (``United Kingdom of Great Britain and
    Northern Ireland``); the MLI table abbreviates (``United Kingdom*``). The
    abbreviation is a leading-words prefix of the full name, and the test must
    hold on whole words, so that ``united kingdom`` never matches ``united
    arab emirates`` and ``united`` never matches on its own.
    """
    left, right = a.lower().split(), b.lower().split()
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if not shorter or len(shorter) > len(longer):
        return False
    return longer[:len(shorter)] == shorter


def find_party(row: dict, party: str) -> PartyStatus:
    """Locate one contracting party in the signatories table.

    Matching is deliberately conservative, because a wrong party lookup would
    produce a confident and wrong verdict. The table spells names its own way
    and carries footnote markers; the library spells them canonically. So:

    * an exact match after stripping footnote markers wins outright;
    * otherwise a unique leading-words match is accepted, and the method says
      so, showing both spellings;
    * otherwise the result is ambiguous or absent, and the two are told apart
      rather than collapsed -- several candidates is not the same fact as no
      candidate, and the verdict reasons about them differently.
    """
    target = normalise(party)
    target_lower = target.lower()
    rows = row["rows"]

    exact = [r for r in rows if normalise(r["jurisdiction"]).lower() == target_lower]
    if len(exact) == 1:
        only = exact[0]
        return PartyStatus(
            party=party, matched=only["jurisdiction"], row=only, page=only.get("page"),
            method=(f"exact match after stripping the footnote marker: the "
                    f"table spells it {only['jurisdiction']!r}"),
        )

    candidates = [
        r for r in rows
        if _shares_leading_words(normalise(r["jurisdiction"]), target)
    ]
    if len(candidates) == 1:
        only = candidates[0]
        return PartyStatus(
            party=party, matched=only["jurisdiction"], row=only, page=only.get("page"),
            method=(f"leading-words match: the library names it "
                    f"{target!r}, the table abbreviates it as "
                    f"{only['jurisdiction']!r}; the table's leading words are "
                    f"the library's, uniquely across all {len(rows)} rows"),
        )

    if len(candidates) > 1:
        names = [c["jurisdiction"] for c in candidates]
        return PartyStatus(
            party=party, matched=None, row=None, page=None, ambiguous=True,
            method=(f"AMBIGUOUS: {len(candidates)} rows share the leading "
                    f"words of {target!r} ({', '.join(names)}); refusing to "
                    f"pick one, because picking wrongly would produce a "
                    f"confident and wrong verdict"),
        )

    return PartyStatus(
        party=party, matched=None, row=None, page=None, ambiguous=False,
        method=(f"not found: none of the {len(rows)} jurisdictions in the "
                f"table shares its leading words with {target!r}; this "
                f"jurisdiction is not a signatory or party to the MLI as the "
                f"table prints it"),
    )


def status(roots: Roots, jurisdiction: str) -> dict:
    """The ``mli_status`` payload: one jurisdiction's standing in the table.

    The reading lives here, beside ``find_party``, so that the tool and the
    drift control that records its answer take the same one. A control that
    built the payload its own way would be checking itself, and this one had
    already stopped carrying the match method -- the very fact that says
    whether a name was found exactly, by leading words, or not at all.
    """
    table = artefacts.document(
        roots.corpus / "corpora" / "mli" / "signatories-and-parties.json")
    found = find_party(table, jurisdiction)
    return {
        "queried": jurisdiction,
        "status_as_of": table.get("status_as_of"),
        "found": found.row is not None,
        "table_spelling": found.matched,
        "match_method": found.method,
        "signed": found.signed,
        "deposited": found.deposited,
        "in_force_since": found.in_force_since,
        "page": found.page,
        "note": ("the corpus holds no MLI position document for every "
                 "jurisdiction; a row here says the party exists, not that "
                 "its position was read"),
    }


# The two documents spell some jurisdictions differently: the MLI's covered-
# agreements tables print short forms, while the library names parties in
# full. The corpus prints "USA" where the library writes "United States of
# America". Rather than fuzzy-match across that gap, the forms that actually
# occur are listed here, so a match is a lookup against a declared table and
# not a guess. Anything not in this table falls back to leading-words
# matching, and an unmatched name is reported as unmatched.
JURISDICTION_ALIASES = {
    "usa": "united states of america",
    "us": "united states of america",
    "u.s.a.": "united states of america",
    "uk": "united kingdom",
}


def _same_jurisdiction(a: str, b: str) -> bool:
    """Whether two jurisdiction strings name the same place.

    Footnote markers are stripped first (the harness preserves them). An
    alias, when one is declared, normalises both sides; otherwise the names
    must share their leading words on word boundaries, so ``united kingdom``
    matches ``United Kingdom of Great Britain and Northern Ireland`` but never
    ``United Arab Emirates``.
    """
    left = normalise(a).lower()
    right = normalise(b).lower()
    if not left or not right:
        return False
    left = JURISDICTION_ALIASES.get(left, left)
    right = JURISDICTION_ALIASES.get(right, right)
    if left == right:
        return True
    return _shares_leading_words(left, right)


def find_covered(
    position: dict | None,
    filer: str,
    counterparty: str,
    signed_in_title: str | None,
) -> CoveredFinding:
    """Look for this treaty in one party's own covered-agreements table.

    ``filer`` is the party whose position document this is; ``counterparty``
    is the state that document is searched for. Nothing keys a library treaty
    to a covered-agreements row, so the link is built from the two facts both
    documents print: the counterparty's name and the treaty's signature date.
    Both pieces of evidence are returned so the caller can judge the match
    instead of trusting it.
    """
    if position is None:
        return CoveredFinding(
            filer=filer, counterparty=counterparty,
            has_position=False, listed=False,
            method="no position document",
            note=f"the corpus holds no MLI position document filed by "
                 f"{filer}, so that party's covered-agreements table cannot "
                 f"be read",
        )

    entries = position.get("covered_agreements", [])
    by_name = [e for e in entries
               if _same_jurisdiction(e.get("other_jurisdiction", ""), counterparty)]
    if not by_name:
        return CoveredFinding(
            filer=filer, counterparty=counterparty,
            has_position=True, listed=False,
            method=(f"scanned the {len(entries)} covered agreements filed by "
                    f"{filer}; none names {counterparty!r} as the other "
                    f"jurisdiction"),
            note="",
        )

    if signed_in_title is None:
        return CoveredFinding(
            filer=filer, counterparty=counterparty,
            has_position=True, listed=False, entry=by_name[0],
            method=(f"{len(by_name)} of the covered agreements filed by "
                    f"{filer} name {by_name[0].get('other_jurisdiction')!r}, "
                    f"but this treaty's title prints no signature date to "
                    f"confirm which one"),
            note="the signature date could not be read from the treaty title, "
                 "so the identification is left open rather than assumed",
        )

    dated = []
    for entry in by_name:
        for instrument in entry.get("instruments", []) or [entry]:
            printed = _to_ddmmyyyy(str(instrument.get("entry_into_force", "")))
            sig = instrument.get("signature")
            if sig and _to_ddmmyyyy(str(sig)) == signed_in_title:
                dated.append((entry, instrument))
                break

    if len(dated) == 1:
        entry, instrument = dated[0]
        return CoveredFinding(
            filer=filer, counterparty=counterparty,
            has_position=True, listed=True, entry=entry,
            method=(f"the covered-agreements table filed by {filer} names "
                    f"{entry.get('other_jurisdiction')!r} at no. "
                    f"{entry.get('no')} with signature "
                    f"{instrument.get('signature')}, matching the "
                    f"{signed_in_title} printed in this treaty's title"),
            note="identified by counterparty name plus signature date, the two "
                 "facts both documents print; no shared key exists in either "
                 "repository",
        )

    if len(dated) > 1:
        return CoveredFinding(
            filer=filer, counterparty=counterparty,
            has_position=True, listed=False,
            method=(f"{len(dated)} of the covered agreements filed by {filer} "
                    f"name that counterparty with a signature date of "
                    f"{signed_in_title}; refusing to pick one"),
            note="ambiguous",
        )

    return CoveredFinding(
        filer=filer, counterparty=counterparty,
        has_position=True, listed=False, entry=by_name[0],
        method=(f"an entry filed by {filer} names "
                f"{by_name[0].get('other_jurisdiction')!r} at no. "
                f"{by_name[0].get('no')}, but its signature date does not "
                f"match the {signed_in_title} in this treaty's title"),
        note="the names agree and the dates do not; reported rather than resolved",
    )


def _scope_lookup(lists: list[dict], counterparty: str | None) -> dict:
    """Whether one agreement is named in the lists a reservation prints.

    ``None`` is not ``False`` here: a reservation whose table the corpus does
    not hold leaves the question open, and answering it "not on the list"
    would turn a gap in the data into a finding about the treaty. Only a list
    that was read can say no, and every matching row is returned as evidence,
    because the caller has to be able to reject the match.
    """
    if not counterparty or not lists:
        return {"verdict": None, "evidence": []}
    evidence = []
    for index, one in enumerate(lists, 1):
        for row in one.get("rows") or []:
            if _same_jurisdiction(str(row.get("other_jurisdiction") or ""),
                                  counterparty):
                evidence.append({
                    "list": index,
                    "no": row.get("no"),
                    "page": row.get("page"),
                    "other_jurisdiction": row.get("other_jurisdiction"),
                    "provision": row.get("text"),
                })
    return {"verdict": bool(evidence), "evidence": evidence}


def _reservations_in_full(number: str, entries: list[dict],
                          counterparty: str | None = None) -> list[dict]:
    """The statements in which a party's own words withhold an Article fully.

    Everything the sentence says after the reservation is returned with it,
    and the qualifier that was found is named, because that tail is the whole
    difference between a reservation that removes an Article outright and one
    that removes it only where the treaty already contains something.

    Several of those sentences go on to print the agreements within the
    reservation's scope, and the corpus reads those tables and keeps them
    (one reading per announcement, because a statement can print two). So the
    list is looked up for the treaty being asked about: ``in_the_reservation_
    scope`` is True when the counterparty is named in a table the corpus holds,
    False when the tables were read and do not name it, and None when no table
    could be read -- a gap is reported as a gap and never as a "no".
    """
    found: list[dict] = []
    for entry in entries:
        if str(entry.get("kind")) != "Reservation":
            continue
        excerpt = str(entry.get("excerpt") or "")
        match = FULL_RESERVATION.search(excerpt)
        if not match or match.group(1) != str(number):
            continue
        tail = excerpt[match.end():].strip()
        marker = next((m for m in QUALIFYING_MARKERS if m in tail.lower()), None)
        lists = [one for one in entry.get("scope_lists") or []
                 if one.get("read")]
        scope = _scope_lookup(lists, counterparty)
        found.append({
            "page": entry.get("page"),
            "option_title": entry.get("option_title") or "",
            "statement": excerpt[:match.end()].strip(),
            "continues": tail,
            "qualified_by": marker,
            # The lists this statement prints, as the corpus holds them: the
            # page, how many rows, and the reader's reason where a table was
            # announced and not read.
            "scope_lists": [
                {"page": one.get("page"),
                 "rows": len(one.get("rows") or []),
                 "headings": one.get("headings") or [],
                 **({"reason": one.get("reason")} if not one.get("read")
                    else {})}
                for one in entry.get("scope_lists") or []
            ],
            "in_the_reservation_scope": scope["verdict"],
            "scope_evidence": scope["evidence"],
            # A statement that announces a list and whose table the corpus
            # does not hold: reported rather than passed over, and different
            # from a statement that prints no list at all.
            "announces_a_list_not_captured": (
                "following agreement" in tail.lower() and not lists),
        })
    return found


def _read_articles(
    mapping: dict,
    positions: dict[str, dict | None],
    parties: list[str],
) -> list[MliArticle]:
    """The chain: the MLI Articles that act on a Covered Tax Agreement.

    Every Article the corpus maps as modifying a treaty is listed, in Article
    order -- not only the ones a party recorded something about. That is
    deliberate: an Article with nothing recorded is one where the parties' own
    documents show no hand, and saying so is different from leaving it out and
    letting the chain read as shorter than it is.

    For each Article this returns the corpus's own statement of what it does
    and which of the treaty's numbered Articles it targets, beside the words
    each party filed, with the page. It does not decide which of them ends up
    applying: that turns on the Convention's compatibility clauses, which this
    project's data does not hold.
    """
    rows = {str(row.get("article")): row for row in mapping.get("rows", [])}
    articles: list[MliArticle] = []

    for number in sorted(rows, key=lambda n: int(n) if n.isdigit() else 0):
        row = rows[number]
        mode = str(row.get("mode") or "")
        if mode not in MODIFYING_MODES:
            continue

        recorded: dict[str, list[dict]] = {}
        reservations: list[dict] = []
        for party in parties:
            sections = (positions.get(party) or {}).get("article_sections") or {}
            entries = list(sections.get(number) or [])
            if entries:
                recorded[party] = entries
            # A reservation's list names the OTHER state, so the lookup is
            # made with the party's counterparty and never with its own name.
            counterparty = next((other for other in parties if other != party),
                                None)
            for signal in _reservations_in_full(number, entries, counterparty):
                reservations.append({"party": party, **signal})

        targets = [
            str(target)
            for group in (row.get("targets") or [])
            for target in (group if isinstance(group, list) else [group])
        ]
        reading = _article_reading(number, mode, targets, recorded,
                                  reservations, parties)
        articles.append(MliArticle(
            number=number,
            title=str(row.get("title") or ""),
            mode=mode,
            convention_page=row.get("page"),
            targets=targets,
            effect=str(row.get("note") or ""),
            recorded=recorded,
            reservations_in_full=reservations,
            reading=reading,
        ))
    return articles


def _article_reading(
    number: str,
    mode: str,
    targets: list[str],
    recorded: dict[str, list[dict]],
    reservations: list[dict],
    parties: list[str],
) -> str:
    """One sentence about an Article: only what the two documents print."""
    who = sorted(recorded)
    if not who:
        said = ("Neither party's position document records a reservation, "
                "notification or choice on this Article, so nothing in this "
                "data shows a hand either party laid on it.")
    else:
        stated = "; ".join(
            f"{party}: " + ", ".join(
                sorted({str(entry.get("kind") or "?") for entry in recorded[party]})
            )
            for party in who
        )
        if len(who) == len(parties):
            said = (f"Both parties recorded a position on this Article -- "
                    f"{stated}.")
        else:
            said = (f"Only {' and '.join(who)} recorded a position on this "
                    f"Article -- {stated}.")

    if reservations:
        said += (f" {len(reservations)} of those statements "
                 f"{'reserves' if len(reservations) == 1 else 'reserve'} the "
                 f"right for the entirety of Article {number} not to apply to "
                 f"Covered Tax Agreements")
        qualified = [r for r in reservations if r.get("qualified_by")]
        if qualified:
            said += (f", {len(qualified)} of them through a qualifier, which "
                     f"is quoted with the statement")
        said += "."
        # The statement's own list of the agreements inside the reservation,
        # when the corpus holds it. This is the one part of the question the
        # data can answer about THIS treaty, so it is answered when it can be
        # and named as unread when it cannot.
        inside = [r for r in reservations if r.get("in_the_reservation_scope")]
        if inside:
            signal = inside[0]
            row = signal["scope_evidence"][0]
            said += (f" {signal['party']}'s statement prints the agreements "
                     f"whose provisions are within the scope of the "
                     f"reservation, and this treaty is one of them (row "
                     f"{row['no']}, printed page {row['page']}; the provision "
                     f"the table gives is {row['provision']!r}).")
            if len(inside) > 1:
                others = ", ".join(sorted(r["party"] for r in inside[1:]))
                said += f" So does {others}'s statement."
        unlisted = [r for r in reservations if r.get("scope_lists")
                    and r.get("in_the_reservation_scope") is False]
        if unlisted:
            who = ", ".join(sorted(r["party"] for r in unlisted))
            held = [one for one in unlisted[0]["scope_lists"] if one.get("read")]
            shown = held[0] if held else unlisted[0]["scope_lists"][0]
            said += (f" {who} {'prints' if len(unlisted) == 1 else 'print'} "
                     f"the agreements whose provisions are within "
                     f"the scope of that reservation ({shown.get('rows')} "
                     f"row(s), printed page {shown.get('page')}), and this "
                     f"treaty is not among them: by that party's own list the "
                     f"reservation does not reach it.")
        if any(r.get("announces_a_list_not_captured") for r in reservations):
            said += (" The statement goes on to name the agreements it covers, "
                     "and no table could be read under that sentence, so "
                     "whether this particular agreement falls inside the "
                     "reservation cannot be read from this data.")

    if mode == "preamble":
        said += (" It acts on the treaty's preamble rather than on a numbered "
                 "Article.")
    elif targets:
        said += (f" The corpus maps it onto the treaty's own Article "
                 f"{', '.join(targets)}.")
    return said


def _load_position(corpus: Path, party: str) -> dict | None:
    """Find a party's position file, by the name the corpus slugs it under.

    The slug is the jurisdiction name in lowercase with spaces hyphenated, so
    matching is done on the slug with the same leading-words rule used for the
    signatories table. Matching on the first word alone would load the United
    Kingdom's file for the United States, because both start with ``united``.
    """
    directory = corpus / "corpora" / "mli" / "positions"
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob("*.json")):
        if path.name == "batch-report.json":
            continue
        if _same_jurisdiction(path.stem.replace("-", " "), party):
            return artefacts.document(path)
    return None


def as_modified(roots: Roots, treaty_id: str) -> Verdict:
    """Answer: what does the MLI do to this treaty, and how do we know.

    Raises Undecidable rather than guessing when the data cannot decide, and
    VerificationError when an artefact does not match its declared hash.
    """
    treaty_path = roots.library / "treaties" / treaty_id / "treaty.json"
    if not treaty_path.is_file():
        raise Undecidable(
            f"the library holds no treaty {treaty_id!r}; the library holds one "
            f"directory per treaty, under its own treaties/ folder"
        )

    checks: list[Check] = []
    checks += verify_treaty(roots.library, treaty_id)
    checks += verify_signatories(roots.corpus)
    verify_all(checks)   # refuses before reasoning if a hash disagrees

    treaty = artefacts.document(treaty_path)

    signatories_path = roots.corpus / "corpora" / "mli" / "signatories-and-parties.json"
    signatories = artefacts.document(signatories_path)

    parties = list(treaty.get("parties", []))
    if len(parties) != 2:
        raise Undecidable(
            f"the library declares {len(parties)} parties for {treaty_id!r}, "
            f"not two; the MLI verdict needs both sides and this server will "
            f"not invent the missing one"
        )

    status = [find_party(signatories, p) for p in parties]
    signed = _signature_date_in_title(treaty.get("title", ""))

    covered: list[CoveredFinding] = []
    checks_extra: list[Check] = []

    # Each party's position document is the one that can list the OTHER
    # state as a covered counterparty, so each party's file is read and
    # searched for its counterparty. Both names are kept, because a covered
    # table belongs to the party that filed it.
    for i, party in enumerate(parties):
        counterparty = parties[1 - i]
        position = _load_position(roots.corpus, party)
        if position is not None:
            checks_extra += verify_position(roots.corpus, position.get("slug", ""))
        covered.append(find_covered(position, party, counterparty, signed))
    verify_all(checks_extra)
    checks += checks_extra

    reasoning: list[Named] = []
    silences: list[Named] = []
    constructed: list[Named] = []
    articles: list[MliArticle] = []

    def declare(target: list[Named], species: str, reason: str) -> None:
        """One sentence of this answer, tagged with the species of thing it is.

        `target` is the family the sentence belongs to; the species is its
        stable name -- the kind of limit a silence is, the kind and subject a
        reasoning step holds, the rule an assumption imports, the entry a
        constructed link joins -- and it is named here, where the sentence is
        written, rather than read back out of it later. The drift control
        records each sentence under its species, so a reworded sentence moves
        one named fact and a new kind is a new fact rather than a line
        shifting under an index.
        """
        target.append(Named(species=species, reason=reason))

    for s in status:
        species = f"mli_standing[{s.party}]"
        if s.row is None:
            declare(reasoning, species, f"{s.party}: {s.method}.")
        else:
            declare(
                reasoning, species,
                f"{s.party}: found in the signatories table as "
                f"{s.matched!r} (row no. {s.row.get('no')}, printed page "
                f"{s.page}); signed {s.signed}, deposited {s.deposited}, "
                f"MLI in force for it since {s.in_force_since}."
            )

    not_parties = [s for s in status if s.row is None and not s.ambiguous]
    ambiguous = [s for s in status if s.ambiguous]
    parties_without_force = [s for s in status if s.row is not None and not s.is_mli_party]

    # An ambiguous lookup is not an absent one. Guessing which row was meant
    # would produce a confident and wrong verdict, so the question is refused
    # and the ambiguity is named instead of being swallowed.
    if ambiguous:
        names = "; ".join(f"{s.party}: {s.method}" for s in ambiguous)
        raise Undecidable(
            f"the MLI standing of {' and '.join(s.party for s in ambiguous)} "
            f"could not be established without guessing -- {names}. This "
            f"server will not guess which row was meant, because guessing "
            f"wrongly would produce a confident and wrong verdict."
        )

    if not_parties:
        verdict = "not-modified"
        names = " and ".join(s.party for s in not_parties)
        declare(
            reasoning, "verdict",
            f"The MLI cannot modify this treaty: it modifies a Covered Tax "
            f"Agreement only once it is in force for both parties, and "
            f"{names} {'is' if len(not_parties) == 1 else 'are'} not "
            f"{'a signatory or party' if len(not_parties) == 1 else 'signatories or parties'} "
            f"to the MLI at all."
        )
        declare(
            reasoning, "completeness",
            "This holds regardless of whether the other party lists the "
            "treaty as covered, which is checked and reported below for "
            "completeness."
        )
    elif parties_without_force:
        verdict = "not-modified"
        names = " and ".join(f"{s.party} (in force {s.in_force_since})"
                             for s in parties_without_force)
        declare(
            reasoning, "verdict",
            f"The MLI is not yet in force for {names}, so it cannot yet "
            f"modify this treaty."
        )
    else:
        listed = [c for c in covered if c.listed]
        if not listed:
            verdict = "undecidable"
            raise Undecidable(
                "both parties are MLI parties with the MLI in force, but "
                "neither position document lists this treaty as a Covered "
                "Tax Agreement, and this server will not infer coverage that "
                "the data does not print"
            )
        verdict = "modified"

        # The chain rests on the corpus's mapping, so that artefact is verified
        # before it is read -- the same register check the positions get.
        chain_checks = verify_mapping(roots.corpus)
        verify_all(chain_checks)
        checks += chain_checks
        mapping = artefacts.document(
            roots.corpus / "corpora" / "mli" / "mapping.json")
        articles = _read_articles(
            mapping,
            {party: _load_position(roots.corpus, party) for party in parties},
            parties,
        )

        declare(
            reasoning, "verdict",
            "Both parties are MLI parties with the MLI in force, and the "
            "treaty is a Covered Tax Agreement for both of them, so the "
            "MLI's modifications bear on it. The chain behind the verdict is "
            "in `mli_articles`: for every Article the corpus maps as acting "
            "on a Covered Tax Agreement, what it does and which of the "
            "treaty's own Articles it targets, beside the words each "
            "party's position document files, with the page each appears on."
        )
        with_a_record = [a for a in articles if a.recorded]
        from_both = [a for a in with_a_record if len(a.recorded) == len(parties)]
        withheld = [a for a in articles if a.reservations_in_full]
        declare(
            reasoning, "chain_summary",
            f"Of the {len(articles)} Articles the corpus maps, "
            f"{len(with_a_record)} carry a recorded position from at least one "
            f"party and {len(from_both)} carry one from both; "
            f"{len(withheld)} carry a statement withholding the entirety of "
            f"the Article from Covered Tax Agreements, quoted in the chain."
        )
        declare(
            silences, "compatibility_clauses_not_held",
            "The corpus holds each party's position and the MLI's "
            "Article-to-provision mapping, but not the Convention's own "
            "compatibility clauses. So where the two parties chose "
            "differently, or reserved on one side only, or reserved with a "
            "qualifier, this server sets out each party's own words and does "
            "not decide which modification ends up applying: that decision is "
            "not in this data."
        )
        by_mode: dict[str, list[str]] = {}
        for row in mapping.get("rows", []):
            mode_name = str(row.get("mode") or "")
            if mode_name not in MODIFYING_MODES:
                by_mode.setdefault(mode_name, []).append(str(row.get("article")))
        if by_mode:
            listed = "; ".join(
                f"{name}: {', '.join(sorted(numbers, key=int))}"
                for name, numbers in sorted(by_mode.items())
            )
            declare(
                silences, "articles_outside_the_chain",
                "The chain leaves out the Articles the corpus maps under "
                f"other modes ({listed}), because they define terms, fix when "
                "the Convention's provisions take effect, or describe "
                "machinery the Convention relies on rather than changing a "
                "treaty. Naming them keeps the chain's boundary visible "
                "instead of implied."
            )

    for c in covered:
        species = f"covered_agreement[{c.filer}]"
        if c.listed:
            declare(
                reasoning, species,
                f"{c.filer}'s position document lists this treaty as covered "
                f"by {c.counterparty}: {c.method}."
            )
            declare(
                constructed, species,
                "The link between this treaty and that covered-agreements "
                "entry was built by counterparty name plus signature date. "
                "Neither repository publishes a key joining them; the two "
                "facts both documents print were used instead, and the "
                "evidence is shown so the match can be rejected."
            )
        elif c.has_position:
            declare(
                reasoning, species,
                f"{c.filer}'s position document, searched for "
                f"{c.counterparty}: {c.method}."
                + (f" {c.note}" if c.note else "")
            )
        else:
            declare(reasoning, species, f"{c.filer}: {c.method}.")

    missing_position = [c for c in covered if not c.has_position]
    if missing_position:
        names = ", ".join(c.filer for c in missing_position)
        declare(
            silences, "no_position_document",
            f"The corpus holds no MLI position document filed by {names}, so "
            f"nothing can be said about what that party reserved, notified "
            f"or listed as covered."
        )

    declare(
        silences, "convention_text_not_held",
        "The corpus does not hold the MLI convention's own text, so the rule "
        "that decides this verdict cannot be cited to a corpus page."
    )
    declare(
        silences, "treaty_held_by_page_not_article",
        "The library holds this treaty by page, not by article, so no "
        "article-level statement about it can be made from this data."
    )

    return Verdict(
        treaty_id=treaty_id,
        title=treaty.get("title", ""),
        parties=parties,
        source_sha256=treaty.get("source", {}).get("sha256", ""),
        pages=treaty.get("page_count", 0),
        status=status,
        covered=covered,
        verdict=verdict,
        reasoning_with_species=reasoning,
        assumptions_with_species=[
            Named(species="mli_in_force_for_both_parties",
                  reason=ASSUMPTION_BOTH_PARTIES)
        ],
        constructed_links_with_species=constructed,
        silences_with_species=silences,
        checks=checks,
        articles=articles,
        as_of=(signatories.get("status_as_of") or {}).get("printed"),
    )
