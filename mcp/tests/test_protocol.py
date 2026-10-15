"""The server, spoken to over the wire -- the only test that proves it is one.

The other tests import ``itl_mcp`` and call functions in-process. This one
does what an MCP host does: it starts the server as a subprocess with the two
roots named, completes the initialize handshake, lists the tools, and reads the
answers off stdio. A package whose functions are green but which cannot finish
a handshake, or whose tool registry is empty, is not a server -- and nothing in
the in-process suite above would show it.

The calls here are chosen so each one proves a different promise of the README:
a real answer (the UK is an MLI party), the citation chain (a page verified
against its own hash), and a refusal (a treaty the library does not hold comes
back undecidable, not invented).
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parents[1]

# The tools the server promises. Naming them exactly means a tool that is
# silently dropped, or one that appears without a test, fails right here.
EXPECTED_TOOLS = {
    "as_modified_verdict",
    "compare_model_editions",
    "read_treaty_page",
    "mli_status",
    "reservation_scope",
    "sources",
}


def _text(result) -> str:
    """The text a tool returned, which is always this server's JSON payload."""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


async def _speak(corpus: str, library: str, calls: list[tuple[str, dict]]):
    """Start the server, handshake, make each call, return the answers."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "itl_mcp.server"],
        cwd=str(REPO),
        env={
            "ITL_CORPUS_ROOT": corpus,
            "ITL_LIBRARY_ROOT": library,
            "PYTHONPATH": str(REPO),
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            # Answers in call order, so the same tool may be called twice
            # without one answer overwriting the other.
            answers = []
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                answers.append(json.loads(_text(result)))
            return session.server_info, listed, answers


def _run(roots, calls):
    return asyncio.run(_speak(str(roots.corpus), str(roots.library), calls))


def test_the_reservation_question_travels_with_its_row_and_page(roots):
    """The reservation question, asked over the wire, with its evidence.

    An answer that says "yes, it is inside the reservation" and stops is a claim
    the caller cannot check. This one carries the printed row and the page: the
    answer for Article 4 is Norway's row 28 on page 6, quoting the provision the
    reservation reaches in this treaty. A question the data cannot frame comes
    back as a refusal with a reason, not as a guessed verdict.
    """
    _, _, answers = _run(roots, [
        ("reservation_scope", {"treaty_id": "no-uk-2013",
                               "mli_article": "Article 4"}),
        ("reservation_scope", {"treaty_id": "no-uk-2013",
                               "mli_article": "8"}),
        ("reservation_scope", {"treaty_id": "not-in-the-library",
                               "mli_article": "4"}),
    ])
    inside, open_question, missing = answers

    assert inside["answer"] is True
    assert inside["mli_article"] == "4"
    norway = [entry for entry in inside["parties"]
              if entry["party"] == "Norway"][0]
    row = norway["statements"][0]["evidence"][0]
    assert (row["no"], row["page"]) == (28, 6)
    assert row["other_jurisdiction"] == "United Kingdom"
    assert row["provision"] == "Article 4(4)"

    # One party's list was read and does not name the treaty; the other prints
    # no list at all. The wire answer is null, never a "no".
    assert open_question["answer"] is None
    assert open_question["answered_by"] == []

    assert missing["verdict"] == "undecidable"
    assert "not-in-the-library" in missing["reason"]
    assert "does not guess" in missing["note"]


def test_the_server_handshakes_and_answers_from_the_data(roots):
    info, listed, answers = _run(roots, [
        ("mli_status", {"jurisdiction": "Italy"}),
        ("mli_status", {"jurisdiction": "United"}),
        ("read_treaty_page", {"treaty_id": "uk-us-2001", "page": 1}),
    ])

    assert info.name == "international-tax-law", info
    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS

    italy, ambiguous, page = answers

    # Italy signed the MLI but has not deposited an instrument, so a real
    # answer names the row and leaves the in-force date empty -- it does not
    # promote a signatory to a party.
    assert italy["found"] is True
    assert italy["in_force_since"] is None

    # "United" matches more than one row. The tool reports that instead of
    # resolving the name to whichever row it happened to see first.
    assert ambiguous["found"] is False
    assert "AMBIGUOUS" in ambiguous["match_method"]

    assert page["verified"] is True
    assert page["declared_sha256"] == page["recomputed_sha256"]
    assert page["chars"] > 0


def test_the_editions_tool_names_the_silent_edition_over_the_wire(roots):
    """Article 12B over the wire: cited by 2021, and 2017 called silent.

    A comparison that answered from whichever edition had the provision would
    present an addition as if it had always been there, so the silence is the
    part worth reading off the wire.
    """
    _, listed, answers = _run(roots, [
        ("compare_model_editions", {"article": "12B"}),
        ("compare_model_editions", {"article": "Article 5"}),
    ])
    assert "compare_model_editions" in {tool.name for tool in listed.tools}

    added, in_both = answers
    assert added["present_in"] == {"2017": False, "2021": True}
    assert added["units"]["2017"] == []
    assert added["units"]["2021"][0]["eId"] == "art_12B"
    assert "silent" in added["reading"]
    assert added["in_the_corpus_diff"] == "added"

    assert in_both["present_in"] == {"2017": True, "2021": True}
    assert "silent" not in in_both["reading"]
    assert all(check["result"] != "MISMATCH" for check in in_both["checks"])


def test_a_treaty_between_two_mli_parties_comes_back_modified_with_its_chain(roots):
    """The whole answer, read off the wire: verdict, chain, and the caveat."""
    _, _, answers = _run(roots, [
        ("as_modified_verdict", {"treaty_id": "no-uk-2013"}),
    ])
    verdict = answers[0]
    assert verdict["verdict"] == "modified"

    chain = {a["mli_article"]: a for a in verdict["mli_articles"]}
    assert chain, "a modified verdict must carry the chain it rests on"

    # Article 8 (dividend transfer) targets the treaty's own Article 10, and
    # both parties reserved it -- one unconditionally, one to the extent the
    # treaty already has a minimum holding period. The qualifier must survive
    # the trip over the wire, or the two would read alike.
    eight = chain["8"]
    assert eight["targets_treaty_articles"] == ["10"]
    withheld = {r["party"]: r for r in eight["reservations_of_the_entirety"]}
    assert len(withheld) == 2
    qualified = [r for r in withheld.values() if r["qualified_by"]]
    assert len(qualified) == 1
    # Norway's Article 8 statement prints the agreements whose provisions are
    # within its reservation's scope, the corpus keeps that list, and the
    # UK-Norway convention is not on it. The answer has to survive the wire:
    # the list, and the lookup made with it.
    assert any(r["scope_lists"] for r in withheld.values())
    assert any(r["in_the_reservation_scope"] is False
               for r in withheld.values())
    assert "this treaty is not among them" in eight["reading"]

    assert any("compatibility clauses" in s for s in verdict["silences"])
    assert not any(c["result"] == "MISMATCH" for c in verdict["provenance"]["checks"])

    # The silences and the reasoning steps travel with the species the verdict
    # declares for them, not as prose alone: the drift control records each
    # sentence by name, and it can only do that if the wire carries the names.
    # The reasons must still be the sentences a reader is promised.
    silence_species = {s["species"] for s in verdict["silences_with_species"]}
    assert "compatibility_clauses_not_held" in silence_species
    assert all(s["reason"] for s in verdict["silences_with_species"])

    step_species = {s["species"] for s in verdict["reasoning_with_species"]}
    assert {"verdict", "mli_standing[Norway]",
            "covered_agreement[Norway]"} <= step_species
    assert [s["reason"] for s in verdict["reasoning_with_species"]] == \
        verdict["reasoning"]


def test_a_held_treaty_gets_a_verdict_and_an_unknown_one_is_refused(roots):
    _, _, answers = _run(roots, [
        ("as_modified_verdict", {"treaty_id": "uk-us-2001"}),
        ("as_modified_verdict", {"treaty_id": "atlantis-1999"}),
    ])

    verdict, refused = answers
    assert verdict["verdict"] == "not-modified"
    assert verdict["assumptions"], "the rule behind the verdict must be declared"
    assert verdict["silences"], "what the data cannot say must be listed"

    # The verdict carries the checks it rested on, and no check may have been
    # disproved. A verdict with a MISMATCH behind it is not an answer.
    provenance = verdict["provenance"]
    assert provenance["status_as_of"], "a verdict about status is only true as of a date"
    assert provenance["checks"], "the verdict must carry the checks it rested on"
    assert all(c["result"] != "MISMATCH" for c in provenance["checks"])

    # A treaty the library does not hold is refused, not invented.
    assert refused["verdict"] == "undecidable"
    assert "no treaty" in refused["reason"]
