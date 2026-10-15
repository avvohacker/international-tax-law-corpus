"""The recorded answers, and the promise that a moved one is named.

The suite elsewhere asserts what this server answers. This file asserts
something different: that the answers *have not moved* since they were recorded,
and that when one does, the failure says which one, from what to what, and what
kind of upstream change could have moved it.

That distinction is the whole reason the fixture exists. An assertion that
fails says "the verdict is no longer modified"; it does not say whether the
cause was a new MLI row, a re-read position document, or a library page whose
text shifted. Those want different repairs, and the run is the only place the
difference can be reported while it is still fresh.
"""

import json
from pathlib import Path

import pytest

from itl_mcp import drift


def test_no_recorded_answer_has_moved(roots):
    """The control itself: any moved fact fails here, named.

    Re-recording is a decision, not a repair: `python -m itl_mcp.drift
    --write` overwrites the fixture with whatever the checkouts now say, so it
    belongs after somebody has read the move and decided it is right.
    """
    recorded = drift.load_fixture()["facts"]
    moves = drift.compare(recorded, drift.live(roots))
    assert not moves, (
        "these answers moved since the fixture was recorded. Re-record with "
        "`python -m itl_mcp.drift --write` only once the move has been read "
        "and judged correct:\n" + "\n".join(m.as_line() for m in moves))


def test_the_fixture_records_the_answers_a_reader_was_promised():
    """A verdict, an MLI standing and a page hash -- the three the README names."""
    facts = drift.load_fixture()["facts"]

    assert facts["as_modified_verdict(treaty_id='uk-us-2001').verdict"] == \
        "not-modified"
    assert facts["as_modified_verdict(treaty_id='no-uk-2013').verdict"] == \
        "modified"

    standing = {fact: value for fact, value in facts.items()
                if ".in_force_since" in fact}
    assert standing, "the MLI standing must be recorded, not only the verdicts"
    assert "01-10-2018" in standing.values()

    pages = {fact: value for fact, value in facts.items()
             if ".declared_sha256" in fact}
    assert len(pages) >= 2, "a page hash per treaty must be recorded"
    assert all(len(str(value)) == 64 for value in pages.values())
    assert facts["read_treaty_page(page=1, treaty_id='uk-us-2001').verified"] is True

    # And the fourth answer this server now gives: whether this treaty falls
    # inside a reservation that prints a list of agreements. Both directions
    # are recorded, from real data: Norway's Article 4 list names the UK, and
    # its Article 8 list does not.
    scope = {fact: value for fact, value in facts.items()
             if ".in_the_reservation_scope[" in fact}
    assert scope, "the reservation-scope lookup must be recorded"
    assert any(value is True for value in scope.values())
    assert any(value is False for value in scope.values())


def test_a_moved_fact_is_named_with_what_it_implies(roots):
    """The fixture is tampered with on purpose; the report must name the fact."""
    recorded = dict(drift.load_fixture()["facts"])
    fact = "as_modified_verdict(treaty_id='uk-us-2001').verdict"
    recorded[fact] = "undecidable"                  # the wrong answer, on purpose

    moves = drift.compare(recorded, drift.live(roots))
    assert [m.fact for m in moves] == [fact], (
        "tampering with one fact must report one move, not a diff of the file")

    move = moves[0]
    assert move.expected == "undecidable"
    assert move.actual == "not-modified"
    assert "verdict moved" in move.why, move.why

    rendered = move.as_line()
    for part in (fact, "was:", "now:", "that means:"):
        assert part in rendered, rendered


def test_a_moved_page_hash_is_explained_as_a_library_change():
    """The explanation must fit the fact, not be one sentence for everything."""
    why = drift.explain(
        "read_treaty_page(page=1, treaty_id='uk-us-2001').declared_sha256")
    assert "library" in why

    chain = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013').mli_articles.count")
    assert "mapping" in chain, chain

    assert why != chain, "two different facts must not read the same"


def test_an_answer_that_disappears_is_reported_too(roots):
    """A fact silently gone is the same class of event as a fact changed."""
    current = drift.live(roots)
    dropped = current.popitem()[0]

    moves = drift.compare(current, drift.live(roots))
    assert any(m.fact == dropped and m.expected == "<not recorded>"
               for m in moves), dropped


def test_the_fixture_records_which_edition_is_silent():
    """The silence is the answer, so it is a recorded fact and not a footnote.

    A fixture that recorded only the edition holding the Article would go on
    agreeing with a server that had stopped reporting the other edition's
    silence -- which is the one thing this tool exists to say.
    """
    facts = drift.load_fixture()["facts"]

    assert facts["compare_model_editions(article='12B').present_in[2021]"] is True
    assert facts["compare_model_editions(article='12B').present_in[2017]"] is False
    assert facts["compare_model_editions(article='12B').units[2017].count"] == 0
    assert facts["compare_model_editions(article='12B').units[2021].count"] > 0

    # And the ordinary Article pins the other half of the answer: no silence.
    assert facts["compare_model_editions(article='5').present_in[2017]"] is True
    assert facts["compare_model_editions(article='5').present_in[2021]"] is True


def test_a_moved_edition_fact_names_the_edition_it_happened_in():
    """The explanation must fit the fact: an edition's silence is not a verdict."""
    why = drift.explain(
        "compare_model_editions(article='12B').present_in[2017]")
    assert "silence" in why, why

    units = drift.explain(
        "compare_model_editions(article='12B').units[2021].count")
    assert "units" in units, units
    assert units != why, "two different facts must not read the same"

    # A fact with no field of its own keeps its tool's explanation. That is the
    # half the ordering fix must not break: the field prefixes win where they
    # occur, and the tool's own name is still the answer where none does.
    whole = drift.explain("compare_model_editions(article='5').in_the_corpus_diff")
    assert "diff" in whole, whole
    assert whole not in (why, units), \
        "the tool-level fallback must be its own explanation"


def test_the_answers_recorded_last_are_recorded_whole():
    """The reservation question, the inventory, and the library's own page.

    Each of these was answerable and tested before it was recorded, which is
    exactly the state this file exists to end: an answer a test asserts is an
    answer that can move without anyone being told which fact moved. What is
    asserted here is that the recorded facts carry the substance of each answer
    and not a summary of it -- the row and page a reservation is answered from,
    the lists a `false` was read out of, and the library's own declared hash for
    a page, which is how a change in the library reaches a recorded answer at
    all now that listing what it holds is not this server's job.
    """
    facts = drift.load_fixture()["facts"]

    page = "read_treaty_page(page=1, treaty_id='uk-us-2001')"
    assert len(facts[f"{page}.declared_sha256"]) == 64
    assert facts[f"{page}.verified"] is True
    assert facts[f"{page}.chars"] > 0

    # Inside the reservation, with the printed row as the evidence.
    inside = "reservation_scope(mli_article='4', treaty_id='no-uk-2013')"
    assert facts[f"{inside}.answer"] is True
    assert facts[f"{inside}.answered_by"] == "Norway"
    assert facts[f"{inside}.parties[Norway].statements[0].page"] == 6
    assert facts[f"{inside}.parties[Norway].statements[0].evidence[28]"] == \
        "page 6: Article 4(4)"

    # And the case where the question stays open: one party's list was read and
    # does not name the treaty while the other prints a list that was not read,
    # so the treaty's answer is null -- recorded as a fact, not as a "no".
    open_question = "reservation_scope(mli_article='8', treaty_id='no-uk-2013')"
    assert facts[f"{open_question}.answer"] is None
    assert facts[f"{open_question}.answered_by"] == ""
    assert facts[f"{open_question}.parties[Norway].answer"] is False
    assert facts[f"{open_question}.parties[Norway].statements[0].lists[0].rows"] == 5
    assert facts[f"{open_question}.parties[Norway].statements[0].lists[0].page"] == 14

    # The inventory: checks that were made, by the strength of each, and that
    # none of them disproved the declaration it was made against.
    assert facts["sources().checks.count"] > 100
    assert facts["sources().checks.disproved"] == 0
    assert facts["sources().checks.kind[bytes].match"] == \
        facts["sources().checks.kind[bytes].count"] > 0
    assert facts["sources().checks.kind[register].match"] > 0


def test_the_new_facts_are_explained_by_their_own_kind_of_change():
    """A moved page, a moved row and a moved check are different repairs."""
    moved_page = drift.explain(
        "read_treaty_page(page=1, treaty_id='uk-us-2001').declared_sha256")
    moved_row = drift.explain(
        "reservation_scope(mli_article='4', treaty_id='no-uk-2013')"
        ".parties[Norway].statements[0].evidence[28]")
    moved_check = drift.explain("sources().checks.kind[bytes].match")
    moved_inventory = drift.explain("sources().checks.count")
    moved_verdict = drift.explain("as_modified_verdict(treaty_id='no-uk-2013').verdict")

    assert "library" in moved_page, moved_page
    assert "list" in moved_row, moved_row
    assert "verification" in moved_check, moved_check
    assert "inventory" in moved_inventory, moved_inventory
    assert "verdict" in moved_verdict, moved_verdict
    assert len({moved_page, moved_row, moved_check, moved_inventory,
                moved_verdict}) == 5, \
        "five different facts must not read the same"

    # The verdict's own checks count is a fact about that answer's provenance,
    # and it keeps the explanation it had: the new prefixes are written with the
    # tool that owns them, so they do not capture another tool's fact.
    verdict_checks = drift.explain(
        "as_modified_verdict(treaty_id='uk-us-2001')"
        ".provenance.checks.disproved")
    assert verdict_checks not in (moved_check, moved_inventory), verdict_checks
    assert "verification" in verdict_checks, verdict_checks


def test_the_verdicts_silences_and_reasoning_are_recorded_whole():
    """A count cannot name a silence that was reworded, or a step that changed.

    The verdict's `silences` and `reasoning` are the two halves a reader is
    promised beside the answer itself: what the data cannot say, and the steps
    the answer was reached by. Both were recorded as counts alone, so a
    reworded silence or a changed step moved nothing anybody could name. Each
    silence now travels with the species of admission the verdict declares for
    it, and each reasoning step is recorded where it stands.
    """
    facts = drift.load_fixture()["facts"]

    # The species the UK-Norway answer admits, each with its sentence.
    modified = "as_modified_verdict(treaty_id='no-uk-2013')"
    assert "compatibility clauses" in \
        facts[f"{modified}.silences[compatibility_clauses_not_held]"]
    assert "other modes" in \
        facts[f"{modified}.silences[articles_outside_the_chain]"]
    assert "does not hold the MLI convention's own text" in \
        facts[f"{modified}.silences[convention_text_not_held]"]
    assert "by page, not by article" in \
        facts[f"{modified}.silences[treaty_held_by_page_not_article]"]

    # And the not-modified answer's own species: a party's missing document.
    unlisted = "as_modified_verdict(treaty_id='uk-us-2001')"
    assert "no MLI position document filed by United States of America" in \
        facts[f"{unlisted}.silences[no_position_document]"]

    # Every step is recorded, not only counted, and by the species the verdict
    # declares for it rather than by its place: a reworded step moves one name.
    uk = "United Kingdom of Great Britain and Northern Ireland"
    assert facts[f"{unlisted}.reasoning[mli_standing[{uk}]]"].startswith(
        "United Kingdom")
    assert "no position document" in facts[
        f"{unlisted}.reasoning[covered_agreement[United States of America]]"]
    assert len([fact for fact in facts
                if fact.startswith(modified + ".reasoning[")]) == 6
    assert len([fact for fact in facts
                if fact.startswith(modified + ".silences[")]) == 4


def test_a_species_of_silence_is_named_across_answers_not_by_position():
    """The same admission in two answers shares its species, not its index.

    The US-UK answer's silences begin with a missing party document; the
    UK-Norway answer's begin with the compatibility clauses. Keyed by place the
    two would collide, and one limit both answers carry would be two facts;
    keyed by the species the verdict declares, each shared limit is one name.
    """
    facts = drift.load_fixture()["facts"]

    for species, phrase in (
        ("convention_text_not_held",
         "does not hold the MLI convention's own text"),
        ("treaty_held_by_page_not_article", "by page, not by article"),
    ):
        unlisted = facts[
            f"as_modified_verdict(treaty_id='uk-us-2001').silences[{species}]"]
        modified = facts[
            f"as_modified_verdict(treaty_id='no-uk-2013').silences[{species}]"]
        assert phrase in unlisted and phrase in modified, species


def test_a_moved_silence_or_reasoning_step_is_explained_by_its_own_kind():
    """A reworded silence and a changed step are two different repairs."""
    silence = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013')"
        ".silences[compatibility_clauses_not_held]")
    step = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013').reasoning[verdict]")
    counted = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013').silences.count")

    assert "silence" in silence, silence
    assert "reasoning" in step, step
    assert silence != step, "two different facts must not read the same"
    assert counted not in (silence, step), counted


def test_a_reworded_silence_is_named_as_one_move(roots):
    """The failure this recording exists for: the words moved and it is named."""
    recorded = dict(drift.load_fixture()["facts"])
    fact = ("as_modified_verdict(treaty_id='no-uk-2013')"
            ".silences[compatibility_clauses_not_held]")
    recorded[fact] = "the corpus holds the compatibility clauses"

    moves = drift.compare(recorded, drift.live(roots))
    assert [m.fact for m in moves] == [fact], (
        "a reworded silence must report the one silence that moved")
    assert "silence" in moves[0].why, moves[0].why


def test_the_verdicts_assumptions_and_constructed_links_are_recorded_whole():
    """The two other lists a reader is promised, by their own substance.

    `assumptions` is the rule the verdict imports from outside the data and
    `constructed_links` are the joins this server built because no key exists.
    The assumptions were counted and the links not recorded at all, so a
    reworded rule or a changed join moved nothing anybody could name.
    """
    facts = drift.load_fixture()["facts"]

    unlisted = "as_modified_verdict(treaty_id='uk-us-2001')"
    assert "NOT held in this project's data" in \
        facts[f"{unlisted}.assumptions[mli_in_force_for_both_parties]"]

    # The join is attributed to the party whose table was read: the UK filed
    # the covered-agreements entry this treaty was matched to.
    uk = "United Kingdom of Great Britain and Northern Ireland"
    join = facts[f"{unlisted}.constructed_links[covered_agreement[{uk}]]"]
    assert "built by counterparty name plus signature date" in join

    # And the modified answer carries both joins, one per filing party.
    modified = "as_modified_verdict(treaty_id='no-uk-2013')"
    assert len([fact for fact in facts
                if fact.startswith(modified + ".constructed_links[")]) == 2
    assert len([fact for fact in facts
                if fact.startswith(modified + ".assumptions[")]) == 1


def test_a_moved_assumption_or_constructed_link_is_explained_by_its_own_kind():
    """A moved rule and a moved join are two more repairs, each named."""
    assumption = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013')"
        ".assumptions[mli_in_force_for_both_parties]")
    link = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013')"
        ".constructed_links[covered_agreement[Norway]]")
    step = drift.explain(
        "as_modified_verdict(treaty_id='no-uk-2013').reasoning[verdict]")

    assert "assumption" in assumption, assumption
    assert "link" in link, link
    assert len({assumption, link, step}) == 3, \
        "three different facts must not read the same"


def test_every_named_family_names_a_move_of_one_of_its_own(roots):
    """A reworded sentence of any family is one named move, with its own why.

    The silences have their own tamper test above; the other families this
    server now records by name are checked here, so a family that stopped being
    recorded as a named fact would be red rather than silently absent.
    """
    recorded = dict(drift.load_fixture()["facts"])
    tampered = {
        "as_modified_verdict(treaty_id='no-uk-2013')"
        ".assumptions[mli_in_force_for_both_parties]": "assumption",
        "as_modified_verdict(treaty_id='no-uk-2013')"
        ".constructed_links[covered_agreement[Norway]]": "link",
        "as_modified_verdict(treaty_id='no-uk-2013').reasoning[verdict]":
            "reasoning",
        "read_treaty_page(page=1, treaty_id='uk-us-2001').declared_gap":
            "library",
        "compare_model_editions(article='12B').reading": "edition",
        "mli_status(jurisdiction='Norway').match_method": "match",
    }
    for fact, word in tampered.items():
        assert fact in recorded, fact
        probe = dict(recorded, **{fact: "a reworded sentence"})
        moves = drift.compare(probe, drift.live(roots))
        assert [m.fact for m in moves] == [fact], \
            (fact, [m.fact for m in moves])
        assert word in moves[0].why, (fact, moves[0].why)


def test_the_page_gap_and_edition_reading_are_recorded_whole():
    """A page that declares no gap says so, and a reading is kept in words.

    `read_treaty_page` recorded the hash and the size but not the page's own
    declaration of what it could not yield; `compare_model_editions` recorded
    the fields under its reading but not the reading. Both are the substance a
    reader is promised, so both are facts now.
    """
    facts = drift.load_fixture()["facts"]

    # Neither held treaty declares a gap on page 1, and that is recorded: a
    # page that later declares one moves this fact from null to the reason.
    assert facts[
        "read_treaty_page(page=1, treaty_id='uk-us-2001').declared_gap"] is None
    assert facts[
        "read_treaty_page(page=1, treaty_id='no-uk-2013').declared_gap"] is None

    assert "silent" in facts["compare_model_editions(article='12B').reading"]
    assert "silent" not in facts["compare_model_editions(article='5').reading"]


def test_the_match_method_is_recorded_and_named():
    """How a name was matched is the answer's provenance, not a detail.

    Exact spelling, leading words, an ambiguity and "not found" are four
    different answers, and the tool and the control had stopped agreeing on
    this field entirely because the control built the payload its own way. It
    is recorded now, and explained by its own sentence.
    """
    facts = drift.load_fixture()["facts"]
    assert "exact match" in facts[
        "mli_status(jurisdiction='Norway').match_method"]
    assert "not found" in facts[
        "mli_status(jurisdiction='United States of America').match_method"]

    method = drift.explain("mli_status(jurisdiction='Norway').match_method")
    standing = drift.explain("mli_status(jurisdiction='Norway').in_force_since")
    assert "match" in method, method
    assert method != standing


def test_every_named_family_records_a_unique_non_empty_species(roots):
    """A species that is empty or shared would collapse two facts into one.

    The families are keyed by the species the verdict declares, so two
    sentences under the same species in one answer would be one fact and the
    second would vanish without a word. An empty species names nothing. The
    flattened fixture is a mapping and could never show a duplicate, so the
    check is made where the species live -- on the payload the tool returns,
    before it is flattened -- and the count is compared with the fixture so a
    collapse is red even there.
    """
    families = ("silences", "reasoning", "assumptions", "constructed_links")
    recorded = drift.load_fixture()["facts"]
    seen: set[str] = set()

    for question in drift.QUESTIONS:
        if question["tool"] != "as_modified_verdict":
            continue
        name = drift.question_name(question)
        payload = drift.answer(roots, question["tool"], dict(question["arguments"]))
        for family in families:
            entries = payload.get(f"{family}_with_species") or []
            seen.add(family)
            species = [entry["species"] for entry in entries]
            assert species and all(species), (family, species)
            assert len(species) == len(set(species)), (
                f"{family} shares a species, so one sentence would swallow "
                f"another: {species}")
            # One recorded fact per sentence: a duplicate in the payload is a
            # fact missing from the fixture, which this catches.
            facts = [fact for fact in recorded
                     if fact.startswith(f"{name}.{family}[")]
            assert len(facts) == len(entries), (name, family, facts)

    assert seen == set(families), seen


def test_the_control_reads_each_tool_the_way_the_tool_does(roots):
    """The tool and the control return the same payload, for every question.

    Sharing the facts is not the same as sharing the reading: a control could
    select the same facts from a payload the tool no longer returns, and the day
    the two drifted apart the fixture would go on agreeing with itself. This
    compares the payloads, so a second copy of a reading is red the day it
    diverges -- which is how `read_treaty_page` and `mli_status` were found to
    have already stopped agreeing.

    `sources` is the one deliberate exception: the tool's payload carries the
    two checkouts' paths, which are where this process read from, and the
    control never records a path. Everything else is compared whole.

    The refusals are compared here too, and they have to be named here rather
    than recorded: none of the recorded questions reaches a refusal, so without
    these the three tools' refusals would drift unread -- and all three had.
    """
    import json

    from itl_mcp import server

    answers = [(str(q["tool"]), dict(q["arguments"]))
               for q in drift.QUESTIONS]
    answers += [
        ("as_modified_verdict", {"treaty_id": "atlantis-1999"}),
        ("compare_model_editions", {"article": ""}),
        ("reservation_scope",
         {"treaty_id": "atlantis-1999", "mli_article": "4"}),
    ]

    for tool, arguments in answers:
        from_tool = json.loads(getattr(server, tool)(**arguments))
        from_control = drift.answer(roots, tool, arguments)
        if tool == "sources":
            from_tool = {key: value for key, value in from_tool.items()
                         if key not in ("corpus_root", "library_root")}
        differing = sorted(
            key for key in set(from_control) | set(from_tool)
            if from_control.get(key) != from_tool.get(key))
        assert not differing, (
            f"the drift control reads {tool} differently from the tool itself; "
            f"differing fields: {differing}")


def test_every_recorded_fact_is_a_fact_about_the_payload_the_tool_returns(roots):
    """The fixture records the tool's answer, not the control's second reading.

    This is the one failure a recorded answer must not have: a control that
    selects its facts from a payload the tool no longer produces would go on
    comparing itself with itself, and every recorded fact would be reassurance
    about nothing. The three readers behind the last three tools are shared with
    those tools for this reason; here the sharing is checked rather than
    assumed, for every recorded question, against the tool the server exposes.
    """
    import json

    from itl_mcp import server

    for question in drift.QUESTIONS:
        tool = str(question["tool"])
        arguments = dict(question["arguments"])
        from_tool = drift.facts(question,
                                json.loads(getattr(server, tool)(**arguments)))
        from_control = drift.facts(question,
                                   drift.answer(roots, tool, arguments))
        assert from_control == from_tool, (
            f"the drift control reads {tool} differently from the tool "
            f"itself:\n"
            + "\n".join(
                f"  {fact}: control {from_control.get(fact)!r} vs tool "
                f"{from_tool.get(fact)!r}"
                for fact in sorted(set(from_control) | set(from_tool))
                if from_control.get(fact) != from_tool.get(fact)))


def test_the_fixture_is_generated_and_says_so():
    payload = drift.load_fixture()
    assert "Generated by" in payload["note"]
    assert payload["questions"], "the fixture must name the questions it answers"
    assert len(payload["facts"]) > 20, \
        "a fixture this thin would not notice an answer moving"


def test_a_missing_fixture_is_a_stated_failure_not_a_pass(tmp_path):
    """No fixture is not the same as no drift."""
    with pytest.raises(SystemExit) as excinfo:
        drift.load_fixture(tmp_path / "absent.json")
    assert "--write" in str(excinfo.value)


def test_every_documented_tool_is_recorded_and_nothing_else_is():
    """Both directions of the same promise: no covered answer without a tool,
    no documented tool without a recorded answer.

    The list of documented tools is read out of the README's own table rather
    than kept here as a second copy: a hand-written set had already been left
    behind by the README once (`reservation_scope` was documented and not in
    it), and the check that was meant to catch a fixture recording an
    undocumented answer went on passing while covering all but one of them.

    That every one of these names is really exposed over the wire -- and under
    that name -- is `test_protocol.py`'s half of it, read off a real MCP
    session. What is asserted here is that every answer this server promises is
    under the control: a tool that is documented and not recorded is an answer
    that can move without anyone being told which fact moved, which is the
    state this fixture exists to make impossible.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8")
    lines = readme.splitlines()
    header = next((index for index, line in enumerate(lines)
                   if line.strip().lower().startswith("| tool ")), None)
    assert header is not None, "the README has no tool table to read"
    documented: set[str] = set()
    for line in lines[header + 1:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0].startswith("---") or not cells[0]:
            continue
        documented.add(cells[0].strip("`"))
    assert len(documented) >= 6, (
        "the README's tool table could not be read, so this check would pass "
        "against nothing: " + repr(sorted(documented)))

    tools = {question["tool"] for question in drift.QUESTIONS}
    assert tools, "the fixture must name the questions it answers"
    assert tools <= documented, (
        "the fixture records an answer nobody was promised: "
        + repr(sorted(tools - documented)))
    assert documented <= tools, (
        "these tools are documented and not recorded, so a movement in any of "
        "them would be reported by nothing: "
        + repr(sorted(documented - tools)))
    assert "as_modified_verdict" in tools, \
        "the verdict is the answer this layer exists for"

    # A tool may take no arguments at all -- `sources()` is the one that does --
    # so the question that produced a fact is named by an arguments mapping that
    # may be empty, never by arguments that must be there. What has to hold is
    # that every fact can be attributed to one of the questions: an orphan fact
    # is one nobody can say the meaning of.
    for question in drift.QUESTIONS:
        assert isinstance(question.get("arguments"), dict), question
        assert question["tool"] in tools, question

    names = tuple(drift.question_name(question) for question in drift.QUESTIONS)
    recorded = drift.load_fixture()["facts"]
    assert recorded, "a fixture with no facts would report no movement at all"
    orphans = [fact for fact in recorded
               if not fact.startswith(names)]
    assert not orphans, (
        "these recorded facts belong to no question in QUESTIONS, so nothing "
        "can say which question they answer: " + repr(sorted(orphans)[:5]))
