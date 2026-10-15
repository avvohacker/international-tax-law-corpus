"""The answers this server must still give, recorded so a move is named.

This repository owns no data, so the drift it can see is the only drift only it
can see: an answer moving because the corpus or the library moved underneath
it. The test suite asserts answers directly, but an assertion says *that* a
claim broke; it does not say which answer moved, from what to what, or what
kind of upstream change could have moved it.

So the answers the README promises are recorded here as named facts -- the
verdict, the MLI standing, the page hash, the reservation question, the edition
that is silent, the inventory of what was read -- and compared field by field. A
run
that goes red says which fact moved, what it was, what it is now, and what a
move of that fact implies. That last part is declared per fact (see `MEANING`),
because "the verdict changed" and "a page's bytes changed" call for different
repairs.

The fixture is *generated* from the live checkouts, never hand-written:

    ITL_CORPUS_ROOT=... ITL_LIBRARY_ROOT=... python -m itl_mcp.drift --write

Recording by command rather than by hand matters for the same reason it does in
the corpus: a value somebody typed can only ever be compared with what somebody
typed, and a fact copied out of an answer stops being a check the moment it is
copied. The *selection* of which facts to record is code, reviewed here; the
*values* are read from the artefacts every time.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .roots import load_roots
from .verdict import Undecidable, as_modified, refusal

FIXTURE = (Path(__file__).resolve().parent.parent
           / "fixtures" / "expected-answers.json")

# The questions. Each is a tool the README documents, with the arguments it is
# documented to answer, so a recorded fact is always the answer to a question a
# reader can ask too.
QUESTIONS: tuple[dict, ...] = (
    {"tool": "as_modified_verdict", "arguments": {"treaty_id": "uk-us-2001"}},
    {"tool": "as_modified_verdict", "arguments": {"treaty_id": "no-uk-2013"}},
    {"tool": "read_treaty_page",
     "arguments": {"treaty_id": "uk-us-2001", "page": 1}},
    {"tool": "read_treaty_page",
     "arguments": {"treaty_id": "no-uk-2013", "page": 1}},
    {"tool": "mli_status", "arguments": {"jurisdiction": "Norway"}},
    {"tool": "mli_status", "arguments": {"jurisdiction": "United Kingdom"}},
    {"tool": "mli_status",
     "arguments": {"jurisdiction": "United States of America"}},
    # Article 12B is the case this tool exists for: the 2021 edition prints it
    # and the 2017 edition does not, so the recorded fact carries the silence.
    {"tool": "compare_model_editions", "arguments": {"article": "12B"}},
    # And an ordinary Article, printed by both, so the recorded facts also pin
    # the case where neither edition is silent.
    {"tool": "compare_model_editions", "arguments": {"article": "5"}},
    # The reservation question on its own, in both directions. Article 4 is
    # inside Norway's list and carries the row and page; Article 8 is the case
    # where one party's list was read and does not name the treaty while the
    # other prints no list at all, so the recorded fact is the open question -
    # which this server reports as an answer and never as a "no".
    {"tool": "reservation_scope",
     "arguments": {"treaty_id": "no-uk-2013", "mli_article": "4"}},
    {"tool": "reservation_scope",
     "arguments": {"treaty_id": "no-uk-2013", "mli_article": "8"}},
    # What every other answer here rests on: which artefacts were read, and how
    # strongly each one was verified before anything was said about it.
    {"tool": "sources", "arguments": {}},
)

# What a move of a given fact implies. This is the "and why" half of the
# report: the test can see that a value changed, and only this map can say what
# changed it. Every entry whose prefix occurs in the fact is a candidate, and
# the sharper one wins -- see `explain` for how sharper is decided.
MEANING: tuple[tuple[str, str], ...] = (
    (".verdict",
     "the verdict moved. It is decided from the parties' MLI standing and the "
     "covered-agreement lookups, so one of those moved: an MLI row was added, "
     "removed or re-dated, or a position document gained or lost this treaty"),
    (".reasoning.count",
     "the reasoning gained or lost a sentence, so the branch that decides this "
     "verdict took a different path through the same data"),
    (".reasoning[",
     "one step of the verdict's reasoning moved: the data that step rests on "
     "changed, or the verdict took a different branch through the same data. "
     "The step is named by its place in the argument, and the verdict is only "
     "as sound as the steps it was reached by"),
    (".mli_status[",
     "a party's MLI standing moved: the signatories and parties table changed "
     "for that jurisdiction, or the name it matches under did"),
    (".covered_agreement_lookups[",
     "a covered-agreements lookup moved: a position document's table gained, "
     "lost or renumbered this treaty, or the filer's own document changed"),
    (".mli_articles.count",
     "the chain changed length. It is one Article per row of the corpus's MLI "
     "mapping whose mode acts on a treaty, so a mapping row was added, removed "
     "or re-moded"),
    (".mli_articles[",
     "one link of the chain moved: what the Article targets, or the words a "
     "party's position document files on it, changed in the corpus"),
    (".in_the_reservation_scope[",
     "the answer to whether this treaty falls inside that reservation moved: "
     "the list the statement prints within its scope changed in the corpus - a "
     "row was added, removed or re-read - or a list that could be read stopped "
     "being readable. The answer is the corpus's list read against this "
     "treaty's counterparty, so a move here is about the list or about the "
     "lookup, never about this server's opinion"),
    (".silences.count",
     "the silences moved: what this data admits it cannot say has changed, "
     "which is itself an answer"),
    (".silences[",
     "one of the silences this answer admits moved: the words the server uses "
     "for a limit of the data changed, the data the admission rests on moved, "
     "or a kind of admission that was there is there no longer. The species is "
     "named in the fact itself, and a silence is an answer here, so a movement "
     "in one is a movement in what the server promises"),
    (".assumptions.count",
     "the number of rules the verdict imports from outside the data changed"),
    (".assumptions[",
     "one assumption the verdict rests on moved: a rule it imports from "
     "outside the data was reworded, or a rule was added or dropped. An "
     "assumption is labelled here on purpose, so a movement in one is a change "
     "in what the verdict admits it owes to something the data does not hold"),
    (".constructed_links.count",
     "the number of links the verdict built rather than looked up changed"),
    (".constructed_links[",
     "one constructed link moved: the sentence joining this treaty to a "
     "covered-agreements entry by counterparty name plus signature date "
     "changed. The link is an inference this server made, not a lookup, so a "
     "movement here is about the identification the verdict stands on"),
    (".provenance.status_as_of",
     "the date the signatories table is dated moved, so the table was "
     "republished"),
    (".provenance.checks",
     "a verification changed: an artefact gained, lost or altered a "
     "declaration, or a kind of check became unprovable. Which one is named in "
     "the fact itself rather than in this line"),
    (".declared_gap",
     "a page's declaration of what it could not yield moved: the library "
     "declared a gap where it had none, dropped one it had, or reworded the "
     "reason. A gap is a page the library itself could not read, reported "
     "rather than filled, so a movement here is a change in what the library "
     "admits about its own text"),
    ("read_treaty_page",
     "a page of the library moved. A declared hash is what the library says "
     "about its own text and a recomputed one is what this process made of it, "
     "so a moved hash means the library's text for that page changed, and a "
     "false verdict means the committed text no longer matches its own "
     "declaration"),
    (".present_in[",
     "whether an edition prints this Article moved: one edition's node index "
     "gained or lost the Article's eId altogether. That silence is the answer "
     "this tool exists to give, so it is recorded and it is checked"),
    (".units[",
     "the units of this Article in one edition moved: the edition was "
     "rebuilt, or the Article gained, lost or was renumbered a unit, and the "
     "cited eIds are what says which"),
    (".reading",
     "the comparison's own sentence moved: which edition prints the Article, "
     "the silence of the one that does not, or how the corpus's own edition "
     "diff classifies it. It is the answer in words, so a movement here is the "
     "change a reader would notice first"),
    ("compare_model_editions",
     "the comparison of the two editions moved for this Article: which "
     "edition prints it, the units it is made of, or how the corpus's own "
     "edition diff classifies it"),
    (".parties[",
     "one party's answer about this MLI Article moved: the position document "
     "the corpus holds for it, the reservation it files, the row and page its "
     "list prints, or whether that list could be read at all. This is the "
     "corpus' reading of that document, never this server's opinion of it"),
    ("reservation_scope",
     "the reservation question moved for the Article asked: the treaty's own "
     "answer, the party whose list names it, or the list that was read and "
     "does not. The answer is three-valued, so a `null` appearing where a "
     "true or false was means a list stopped being readable - a change in the "
     "data, not a change of opinion, and one this server reports rather than "
     "rounds to 'no'"),
    # Written with the tool's own name in front, not as `.checks.disproved`: the
    # verdict's payload carries a `provenance.checks.disproved` of its own, and a
    # bare prefix would have explained that fact - correctly about verifications,
    # but about the wrong file and the wrong count - with this sentence.
    ("sources().checks.disproved[",
     "an artefact no longer matches the hash its own project declares for it. "
     "This is never a legitimate movement: one of the two checkouts is "
     "internally inconsistent, and every answer this server gives is suspect "
     "until it is repaired"),
    ("sources().checks.disproved",
     "the number of artefacts that failed their own declaration changed. Any "
     "value above zero is a red run on its own terms, whatever else moved"),
    ("sources().checks.kind[",
     "the strength of the verification moved: an artefact gained or lost a "
     "declared hash, or a check that recomputed bytes now only matches a "
     "register entry, which changes what the answers were proven against "
     "rather than what they say"),
    ("sources()",
     "the inventory of what this server reads moved: an artefact was added to "
     "or removed from the corpus or the library, so the checks standing behind "
     "every other answer here changed in number"),
    (".match_method",
     "the way this jurisdiction was matched to the table moved: an exact "
     "spelling gave way to a leading-words match or an ambiguity, a row that "
     "was found is not, or the table's spelling of it changed. The method is "
     "why the answer can be checked at the source, so a movement in it is a "
     "change in how the lookup was made and not only in what it found"),
    ("mli_status",
     "the MLI signatories and parties table moved for this jurisdiction: a "
     "date, a spelling, or the row itself"),
    ("",
     "an answer this repository promises has moved"),
)


def answer(roots, tool: str, arguments: dict) -> dict:
    """One tool's answer, as the payload the tool itself returns.

    The tools serialise this to JSON for the wire; the drift control wants the
    structure, so the reading is shared and a fact can be pointed at by name.
    """
    if tool == "as_modified_verdict":
        try:
            return as_modified(roots, arguments["treaty_id"]).as_dict()
        except Undecidable as error:
            # The refusal is `itl_mcp.verdict`'s, taken by the tool too: this
            # control had been returning a bodiless one, without the tool's
            # note, and a refusal is an answer like any other.
            return refusal(error.reason)
    if tool == "read_treaty_page":
        # The same reading the tool takes, from `itl_mcp.library`: a control that
        # recomputed the hash its own way would be checking itself, and it had
        # already stopped reading the page's own declared gap.
        from .library import page as read_page
        return read_page(roots, arguments["treaty_id"], arguments["page"])
    if tool == "compare_model_editions":
        # The refusal is `itl_mcp.editions`'s, taken by the tool too: this
        # control had been answering with an `article` key the tool never
        # returns, and omitting the note the tool does.
        from .editions import compare as compare_editions, uncomparable
        try:
            return compare_editions(roots.corpus, arguments["article"])
        except (FileNotFoundError, ValueError) as error:
            return uncomparable(str(error))
    if tool == "reservation_scope":
        # Both refusals are `itl_mcp.reservations`'s, taken by the tool too;
        # this control had been returning them without the tool's notes.
        from .reservations import (
            CannotAnswer,
            refusal as reservation_refusal,
            scope,
            unverifiable,
        )
        from .verify import VerificationError
        try:
            return scope(roots, arguments["treaty_id"], arguments["mli_article"])
        except CannotAnswer as error:
            return reservation_refusal(error.reason)
        except VerificationError as error:
            return unverifiable(str(error))
    if tool == "sources":
        # The same reading the tool takes, from `itl_mcp.verify`. It does not
        # carry the two roots: they are paths on the machine that asked, and a
        # recorded answer is committed, so what is recorded is what was checked
        # and how, never where it lives.
        from .verify import sources as walk
        return walk(roots)
    if tool == "mli_status":
        # The same reading the tool takes, from `itl_mcp.verdict`: a control
        # that built the payload its own way would be checking itself, and it
        # had already stopped carrying the match method.
        from .verdict import status as mli_standing
        return mli_standing(roots, arguments["jurisdiction"])
    raise ValueError(f"no such tool: {tool}")


def question_name(question: dict) -> str:
    """How a question is written in the fixture: the tool and its arguments."""
    arguments = ", ".join(f"{key}={value!r}"
                          for key, value in sorted(question["arguments"].items()))
    return f"{question['tool']}({arguments})"


def facts(question: dict, payload: dict) -> dict:
    """The named facts one answer records, read out of the payload.

    Which facts are recorded is a decision of this module and is reviewed here;
    the values come from the artefacts on every run. The selection is
    deliberately about things a reader was promised -- the verdict, the MLI
    standing, the page hash, the row a reservation prints, the strength of a
    verification -- and not about every field, because a fixture that records
    everything turns every legitimate upstream addition into a red run and stops
    being read.
    """
    name = question_name(question)
    out: dict[str, object] = {}

    def record(suffix: str, value: object) -> None:
        out[f"{name}{suffix}"] = value

    # The two answers below are selected by the question and not by whichever
    # keys their payload happens to carry: a `reservation_scope` that cannot
    # frame the question also returns `{"verdict": "undecidable"}`, and read by
    # keys it would be recorded as though it were a chain of MLI Articles.
    if question["tool"] == "reservation_scope":
        record(".mli_article", payload.get("mli_article"))
        record(".answer", payload.get("answer"))
        record(".answered_by", ", ".join(payload.get("answered_by") or []))
        readings = payload.get("parties") or []
        record(".parties.count", len(readings))
        for reading in readings:
            key = f"[{reading.get('party')}]"
            record(f".parties{key}.position_document",
                   reading.get("position_document"))
            record(f".parties{key}.answer", reading.get("answer"))
            statements = reading.get("statements") or []
            record(f".parties{key}.statements.count", len(statements))
            for index, statement in enumerate(statements):
                where = f".parties{key}.statements[{index}]"
                record(f"{where}.page", statement.get("page"))
                record(f"{where}.answer", statement.get("answer"))
                record(f"{where}.announces_a_list_not_captured",
                       statement.get("announces_a_list_not_captured"))
                # The lists this statement prints within its scope, and how much
                # each one holds: a `false` answer stands on the rows that were
                # read, and that is the half of the answer a reader is promised
                # and cannot reconstruct from the verdict alone.
                for index, printed in enumerate(statement.get("lists") or []):
                    record(f"{where}.lists[{index}].page", printed.get("page"))
                    record(f"{where}.lists[{index}].rows", printed.get("rows"))
                    record(f"{where}.lists[{index}].read", printed.get("read"))
                # The row and the page the answer stands on: recorded so that a
                # moved answer can be checked at the source and rejected.
                for row in statement.get("evidence") or []:
                    record(f"{where}.evidence[{row.get('no')}]",
                           f"page {row.get('page')}: {row.get('provision')}")
        checks = payload.get("checks") or []
        record(".checks.count", len(checks))
        record(".checks.disproved",
               sum(1 for check in checks if check.get("result") == "MISMATCH"))
        return out

    if question["tool"] == "sources":
        checks = payload.get("checks") or []
        record(".checks.count", len(checks))
        # By kind and by result, not one fact per file: the corpus legitimately
        # gains a position document, and a fixture that turned every upstream
        # addition into a red run would stop being read. A *kind* appearing or
        # disappearing is still reported, and a disproved check is named below.
        kinds: dict[str, dict[str, int]] = {}
        for check in checks:
            bucket = kinds.setdefault(str(check.get("kind")), {})
            result = str(check.get("result"))
            bucket[result] = bucket.get(result, 0) + 1
        for kind, bucket in sorted(kinds.items()):
            record(f".checks.kind[{kind}].count", sum(bucket.values()))
            for result, count in sorted(bucket.items()):
                record(f".checks.kind[{kind}].{result}", count)
        disproved = [check for check in checks
                     if check.get("result") == "MISMATCH"]
        record(".checks.disproved", len(disproved))
        for check in disproved:
            record(f".checks.disproved[{check.get('artefact')}]",
                   f"declared {check.get('declared')} but computed "
                   f"{check.get('actual')}")
        return out

    if "verdict" in payload:
        record(".verdict", payload.get("verdict"))
        record(".reasoning.count", len(payload.get("reasoning") or []))
        record(".silences.count", len(payload.get("silences") or []))
        record(".assumptions.count", len(payload.get("assumptions") or []))
        record(".constructed_links.count",
               len(payload.get("constructed_links") or []))
        # Every sentence of this answer on its own, not only by count: a
        # silence, a step, an assumption or a constructed link that is reworded
        # is a movement of an answer this server gives, and a count cannot name
        # which one moved. Each family is keyed by the species the verdict
        # itself declares -- the kind of limit a silence is, the kind and
        # subject a step holds, the rule an assumption imports, the entry a
        # link joins -- so a reworded sentence moves one fact and a kind
        # appearing or disappearing is a fact appearing or disappearing,
        # rather than every later sentence shifting under an index.
        for family in ("silences", "reasoning", "assumptions",
                       "constructed_links"):
            for sentence in payload.get(f"{family}_with_species") or []:
                record(f".{family}[{sentence.get('species')}]",
                       sentence.get("reason"))
        record(".provenance.status_as_of",
               (payload.get("provenance") or {}).get("status_as_of"))
        checks = (payload.get("provenance") or {}).get("checks") or []
        kinds: dict[str, int] = {}
        for check in checks:
            kinds[check["kind"]] = kinds.get(check["kind"], 0) + 1
        record(".provenance.checks.count", len(checks))
        for kind, count in sorted(kinds.items()):
            record(f".provenance.checks.kind[{kind}]", count)
        record(".provenance.checks.disproved",
               sum(1 for check in checks if check["result"] == "MISMATCH"))
        for status in payload.get("mli_status") or []:
            party = status["party"]
            record(f".mli_status[{party}].in_force_since",
                   status.get("in_force_since"))
            record(f".mli_status[{party}].found_in_table",
                   status.get("found_in_table"))
        for lookup in payload.get("covered_agreement_lookups") or []:
            key = (f"[{lookup['position_document_of']}"
                   f"-for-{lookup['searched_for_state']}]")
            record(f".covered_agreement_lookups{key}.listed",
                   lookup.get("treaty_listed_as_covered"))
            entry = lookup.get("entry") or {}
            if entry:
                record(f".covered_agreement_lookups{key}.entry.no",
                       entry.get("no"))
                record(f".covered_agreement_lookups{key}.entry.page",
                       entry.get("page"))
        articles = payload.get("mli_articles") or []
        record(".mli_articles.count", len(articles))
        record(".mli_articles.numbers",
               ",".join(str(a.get("mli_article")) for a in articles))
        for article in articles:
            number = article.get("mli_article")
            reserved = article.get("reservations_of_the_entirety") or []
            if reserved:
                record(f".mli_articles[{number}].reservations_of_the_entirety",
                       len(reserved))
                record(f".mli_articles[{number}].qualified",
                       sum(1 for r in reserved if r.get("qualified_by")))
                record(f".mli_articles[{number}].announces_a_list_not_captured",
                       sum(1 for r in reserved
                           if r.get("announces_a_list_not_captured")))
                # The lists the statements print within their scope, and the
                # answer each one gives about this treaty. A statement whose
                # list the corpus does not hold records no answer at all, which
                # is a fact of its own and not a "no".
                record(f".mli_articles[{number}].reservation_scope_lists",
                       sum(len(r.get("scope_lists") or []) for r in reserved))
                for r in reserved:
                    answer = r.get("in_the_reservation_scope")
                    if answer is None:
                        continue
                    fact = (f".mli_articles[{number}].in_the_reservation_scope"
                            f"[{r.get('party')}]")
                    record(fact, answer)
                    for row in r.get("scope_evidence") or []:
                        record(f"{fact}.row[{row.get('no')}]",
                               f"page {row.get('page')}: {row.get('provision')}")
            if article.get("recorded"):
                record(f".mli_articles[{number}].recorded_by",
                       ",".join(sorted(article["recorded"])))
        return out

    if "declared_sha256" in payload:
        record(".declared_sha256", payload.get("declared_sha256"))
        record(".verified", payload.get("verified"))
        record(".chars", payload.get("chars"))
        # The page's own declaration of what it could not yield. A gap is a
        # page the library itself could not read, and its flag travels with the
        # reason, so a page that gained or lost one is a named movement rather
        # than a field nobody recorded.
        gap = payload.get("gap")
        record(".declared_gap",
               f"{gap}: {payload.get('gap_reason')}" if gap else None)
        return out

    if "present_in" in payload:
        present = payload.get("present_in") or {}
        units = payload.get("units") or {}
        for edition in payload.get("editions") or []:
            record(f".present_in[{edition}]", present.get(edition))
            cited = units.get(edition) or []
            record(f".units[{edition}].count", len(cited))
            record(f".units[{edition}].eIds",
                   ",".join(str(unit.get("eId")) for unit in cited))
        record(".in_the_corpus_diff", payload.get("in_the_corpus_diff"))
        # The comparison's own sentence, in words: which edition prints the
        # Article, the silence of the one that does not, and how the corpus's
        # diff classifies it. Recorded so a reworded reading is a named
        # movement and not only the fields beneath it.
        record(".reading", payload.get("reading"))
        checks = payload.get("checks") or []
        record(".checks.count", len(checks))
        record(".checks.disproved",
               sum(1 for check in checks if check.get("result") == "MISMATCH"))
        return out

    # mli_status
    record(".status_as_of", payload.get("status_as_of"))
    record(".found", payload.get("found"))
    record(".table_spelling", payload.get("table_spelling"))
    record(".in_force_since", payload.get("in_force_since"))
    # The method says whether the row was found exactly, by leading words, as
    # an ambiguity, or not at all -- the difference between a name the table
    # spells differently and a jurisdiction it does not hold. Recorded so a
    # change in how the lookup was made is a named movement, not a silent one.
    record(".match_method", payload.get("match_method"))
    return out


def live(roots, questions: tuple[dict, ...] = QUESTIONS) -> dict:
    """Every recorded fact, read from the checkouts as they are now."""
    recorded: dict[str, object] = {}
    for question in questions:
        payload = answer(roots, question["tool"], dict(question["arguments"]))
        recorded.update(facts(question, payload))
    return recorded


@dataclass(frozen=True)
class Move:
    """One recorded fact that is not what it was, and what that implies."""

    fact: str
    expected: object
    actual: object
    why: str

    def as_line(self) -> str:
        return (f"  {self.fact}\n"
                f"      was: {self.expected!r}\n"
                f"      now: {self.actual!r}\n"
                f"      that means: {self.why}")


def explain(fact: str) -> str:
    """What a move of this fact implies, from the declared map.

    A fact's name is a question followed by the fields it recorded, so a prefix
    matching *later* in the name speaks about a field while one matching at the
    start speaks about the tool: the later match is the sharper one and wins.
    Length cannot decide it, because a tool's own name is sometimes longer than
    the field's -- `compare_model_editions` against `.present_in[` -- and the
    earlier rule read a specific fact with its family's explanation. Ties go to
    the longer prefix, so `.mli_articles.count` still beats `.mli_articles[`.
    """
    matches = [(fact.find(prefix), len(prefix), why)
               for prefix, why in MEANING if prefix in fact]
    if not matches:
        return MEANING[-1][1]
    return max(matches, key=lambda found: (found[0], found[1]))[2]


def compare(recorded: dict, current: dict) -> list[Move]:
    """Every recorded fact that moved, in name order.

    A fact that has appeared is reported too, and one that has gone: a fixture
    that only noticed changed values would miss an answer quietly disappearing,
    which is the same class of event as an answer changing.
    """
    moves: list[Move] = []
    for fact in sorted(set(recorded) | set(current)):
        was = recorded.get(fact, "<not recorded>")
        now = current.get(fact, "<gone>")
        if was != now:
            moves.append(Move(fact, was, now, explain(fact)))
    return moves


def load_fixture(path: Path = FIXTURE) -> dict:
    if not path.is_file():
        raise SystemExit(
            f"{path.name} is absent: generate it against the checkouts with "
            f"`python -m itl_mcp.drift --write`")
    return json.loads(path.read_text(encoding="utf-8"))


def write_fixture(roots, path: Path = FIXTURE) -> dict:
    payload = {
        "note": ("Generated by `python -m itl_mcp.drift --write` against the "
                 "corpus and library checkouts. Do not edit by hand: a hand-"
                 "written value can only be compared with what was hand-"
                 "written, and stops being a check the moment it is copied."),
        "questions": [{"tool": q["tool"], "arguments": q["arguments"]}
                      for q in QUESTIONS],
        "facts": live(roots),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m itl_mcp.drift",
        description="Record, or compare, the answers this server promises.")
    parser.add_argument(
        "--write", action="store_true",
        help="record the live answers into the fixture (this is the only way "
             "the fixture is ever written)")
    parser.add_argument(
        "--fixture", default=str(FIXTURE),
        help="the fixture to read or write (default: the committed one)")
    args = parser.parse_args(argv)

    roots = load_roots()
    path = Path(args.fixture)

    if args.write:
        payload = write_fixture(roots, path)
        print(f"wrote {path}: {len(payload['facts'])} facts from "
              f"{len(payload['questions'])} questions")
        return 0

    moves = compare(load_fixture(path)["facts"], live(roots))
    if not moves:
        print(f"no answer moved: every recorded fact still holds "
              f"({len(load_fixture(path)['facts'])} facts)")
        return 0
    print(f"{len(moves)} answer(s) moved:", file=sys.stderr)
    for move in moves:
        print(move.as_line(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
