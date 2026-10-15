"""The reservation-scope question, asked by itself.

``test_chain.py`` answers this question inside the whole verdict. This file
pins it where an agent meets it: as its own tool, for one MLI Article at a
time, with the row and the page travelling with the answer.

The facts asserted against the real corpus are the ones the 2013 UK-Norway
convention prints -- Norway's lists name the United Kingdom on Articles 4, 14
and 17, and on Article 8 Norway's list was read and does not name it while the
United Kingdom's own reservation on that Article prints no list at all -- and
the rest of the file is the discipline that makes those facts worth reporting: a
"no" always cites a list that was read, and a table the corpus could not read,
or a statement that prints none, answers null with the reader's own reason.
"""

import pytest

from itl_mcp.reservations import (
    CannotAnswer,
    _nothing_filed,
    _party_reading,
    _statements,
    article_key,
    scope,
)

TREATY = "no-uk-2013"
NORWAY = "Norway"
UNITED_KINGDOM = "United Kingdom of Great Britain and Northern Ireland"


@pytest.fixture(scope="module")
def four(roots):
    return scope(roots, TREATY, "4")


def _party(payload: dict, name: str) -> dict:
    found = [entry for entry in payload["parties"] if entry["party"] == name]
    assert found, f"{name} is not among the parties this payload reports"
    return found[0]


def _statement_naming(payload: dict, name: str) -> dict:
    """The statement whose list names this treaty, whatever order it comes in."""
    for statement in _party(payload, name)["statements"]:
        if statement["answer"] is True:
            return statement
    raise AssertionError(f"no statement of {name} names this treaty")


# --------------------------------------------------------------------------
# the question, and the party that answered it
# --------------------------------------------------------------------------

def test_the_question_names_the_treaty_and_the_article(four):
    assert four["treaty"]["id"] == TREATY
    assert sorted(four["treaty"]["parties"]) == sorted([NORWAY, UNITED_KINGDOM])
    assert four["mli_article"] == "4"
    assert "Article 4" in four["question"]


def test_the_list_that_names_the_treaty_answers_yes(four):
    assert four["answer"] is True
    assert four["answered_by"] == [NORWAY]
    norway = _party(four, NORWAY)
    assert norway["answer"] is True
    assert norway["position_document"] == "norway"
    assert norway["counterparty"] == UNITED_KINGDOM


def test_the_evidence_is_the_printed_row_and_its_page(four):
    """The answer is worth nothing without the row a reader can go and check.

    Row 28 of page 6 is where Norway's own list names the United Kingdom, and
    the provision quoted there is what the reservation reaches in this treaty.
    """
    statement = _statement_naming(four, NORWAY)
    row = statement["evidence"][0]
    assert (row["no"], row["page"]) == (28, 6)
    assert row["other_jurisdiction"] == "United Kingdom"
    assert row["provision"] == "Article 4(4)"
    assert row["list"] >= 1
    assert statement["lists"][0]["page"] == 6
    assert statement["lists"][0]["rows"] == 9
    assert "page 6" in statement["why"]
    assert "United Kingdom" in statement["why"]


def test_a_read_list_that_does_not_name_the_treaty_answers_no(roots):
    """A "no" is a finding about a list, and it cites the list it read.

    Norway's Article 8 list was read and does not name the United Kingdom, so
    Norway's own answer is false -- not null -- and the page and the row count
    are reported, because that is what makes it a finding about the source
    rather than a silence.

    The treaty's answer is still null, and that is the rule this tool exists to
    keep: the United Kingdom's Article 8 reservation prints no list at all
    ("reserves the right for the entirety of Article 8 not to apply to its
    Covered Tax Agreements"), so one party's finding cannot close a question
    the other party's document never framed. A false here would have called
    Norway's list the whole answer.
    """
    payload = scope(roots, TREATY, "8")
    assert payload["answer"] is None
    assert payload["answered_by"] == []
    statement = _party(payload, NORWAY)["statements"][0]
    assert statement["answer"] is False
    assert statement["evidence"] == []
    assert statement["announces_a_list_not_captured"] is False
    assert [one["page"] for one in statement["lists"]] == [14]
    assert [one["rows"] for one in statement["lists"]] == [5]
    assert all(one["read"] for one in statement["lists"])
    assert "none names" in statement["why"]
    other = _party(payload, UNITED_KINGDOM)
    assert other["answer"] is None
    assert other["statements"][0]["lists"] == []
    assert "prints no list of agreements" in other["statements"][0]["why"]


def test_the_other_lists_that_name_the_treaty_cite_their_own_rows(roots):
    """Each list carries the page and the provision of the row that names it."""
    for article, page, provision in (("14", 20, "Article 21(4)"),
                                     ("17", 25, "Article 9(2)")):
        payload = scope(roots, TREATY, article)
        assert payload["answer"] is True, article
        rows = [row for statement in _party(payload, NORWAY)["statements"]
                for row in statement["evidence"]]
        assert (28, page, provision) in [
            (row["no"], row["page"], row["provision"]) for row in rows
        ], (article, rows)


def test_the_party_that_filed_no_document_is_named_not_silent():
    """A party the corpus holds no position for is named, and is not a "no".

    "The United Kingdom's list does not name Norway" is not something this data
    could say if the corpus held no document filed by the United Kingdom: the
    absence of a document is a gap in the data, and the difference between
    reporting it in words and leaving it implicit is the difference between an
    answer and a guess.

    The case cannot be reached through the real corpus today -- both parties of
    the library's treaties filed a position, and the ones that filed scanned
    documents are declared unread rather than missing -- so the party reading is
    asked directly, the way ``test_chain.py`` asks its own no-document case.
    ``position=None`` is what a slug the corpus does not hold resolves to.
    """
    reading = _party_reading(None, "4", UNITED_KINGDOM, NORWAY)
    assert reading["position_document"] is None
    assert reading["statements"] == []
    assert reading["answer"] is None
    assert UNITED_KINGDOM in reading["why"]
    assert "no MLI position document" in reading["why"]
    assert reading["counterparty"] == NORWAY


# --------------------------------------------------------------------------
# null is not false: the rule the tool exists to keep
# --------------------------------------------------------------------------

def test_a_list_the_corpus_could_not_read_is_not_a_no():
    """An unread table leaves the question open, with the reader's own reason.

    This is the case the three-valued answer exists for. The alternative is a
    confident "not on the list" about a table nobody read, which is a finding
    about the treaty that the data does not support.
    """
    position = {
        "slug": "example",
        "article_sections": {"8": [{
            "kind": "Reservation", "page": 3,
            "excerpt": ("Norway reserves the right for the entirety of Article "
                        "8 not to apply to its Covered Tax Agreements. The "
                        "following agreements contain provisions that are "
                        "within the scope of this reservation."),
            "scope_lists": [{
                "read": False, "page": 4,
                "reason": ("the statement announces a list of agreements and "
                           "no table is printed under that sentence")}],
        }]},
    }
    found = _statements(position, "8", "United States of America")
    assert found[0]["answer"] is None
    assert found[0]["evidence"] == []
    assert found[0]["announces_a_list_not_captured"] is True
    assert "could not read its table" in found[0]["why"]
    assert found[0]["lists"][0]["reason"].startswith("the statement")


def test_a_reservation_that_prints_no_list_is_not_a_no():
    position = {
        "slug": "example",
        "article_sections": {"5": [{
            "kind": "Reservation", "page": 2,
            "excerpt": "Norway reserves the right for the entirety of Article 5.",
            "scope_lists": []}]},
    }
    found = _statements(position, "5", "Norway")
    assert found[0]["answer"] is None
    assert found[0]["evidence"] == []
    assert found[0]["announces_a_list_not_captured"] is False
    assert "prints no list" in found[0]["why"]


def test_a_notification_is_not_a_reservation():
    """The reader reads the kind as well as the words.

    A notification prints tables too, but it does not withhold an Article, so
    its rows must not be reported as a reservation's scope.
    """
    position = {
        "slug": "example",
        "article_sections": {"4": [{
            "kind": "Notification", "page": 2,
            "excerpt": ("considers that the following agreements are not "
                        "within the scope of a reservation under Article 4"),
            "scope_lists": [{"read": True, "page": 3, "rows": []}]}]},
    }
    assert _statements(position, "4", "Norway") == []


def test_the_three_ways_of_filing_nothing_are_told_apart():
    """No document at all, no section, and no reservation are different facts.

    Collapsing them into one sentence would hide which of the three an answer
    rests on, and a reader could not tell a jurisdiction that filed nothing
    from one whose document simply printed no reservation under this Article.
    """
    position = {"slug": "example", "article_sections": {
        "17": [{"kind": "Notification", "page": 1, "excerpt": "x"}]}}
    assert _statements(position, "7", NORWAY) == []

    absent = _nothing_filed(None, "7", NORWAY)
    assert "no MLI position document" in absent and NORWAY in absent

    unprinted = _nothing_filed(position, "7", NORWAY)
    assert "prints no Article 7 section" in unprinted
    assert "17" in unprinted

    no_reservation = _nothing_filed(position, "17", NORWAY)
    assert "files no reservation under Article 17" in no_reservation
    assert "Notification" in no_reservation


@pytest.mark.parametrize("number", ["7", "4"])
def test_every_answer_is_three_valued_and_carries_its_reason(roots, number):
    payload = scope(roots, TREATY, number)
    assert payload["answer"] in (True, False, None)
    for entry in payload["parties"]:
        assert entry["answer"] in (True, False, None)
        assert entry["why"]
        for statement in entry["statements"]:
            assert statement["answer"] in (True, False, None)
            assert statement["why"]
            assert isinstance(statement["lists"], list)
            if statement["answer"] is False:
                # A no is only ever given about lists that were read.
                assert statement["evidence"] == []
                assert statement["lists"]
                assert all(one["read"] for one in statement["lists"])
            if statement["answer"] is True:
                assert statement["evidence"]
                assert statement["evidence"][0]["page"] is not None
                assert statement["evidence"][0]["no"] is not None


# --------------------------------------------------------------------------
# what the answer carries, and what it refuses
# --------------------------------------------------------------------------

def test_the_article_may_be_named_the_way_a_document_prints_it(roots):
    assert article_key("4") == "4"
    assert article_key("Article 4") == "4"
    assert article_key(" article 17 ") == "17"
    assert scope(roots, TREATY, "Article 4")["answer"] is True


def test_an_unknown_treaty_is_refused_rather_than_guessed(roots):
    with pytest.raises(CannotAnswer) as raised:
        scope(roots, "no-such-treaty", "4")
    assert "no-such-treaty" in raised.value.reason
    # The refusal points at where the answer is, not at a tool of this server:
    # the catalogue of what the library holds is a directory listing, and this
    # server answers the questions that are not one.
    assert "treaties/" in raised.value.reason


def test_the_payload_carries_the_checks_it_was_verified_against(four):
    """The server's promise: an answer names the artefacts behind it."""
    assert four["checks"]
    assert all(check["result"] != "MISMATCH" for check in four["checks"])
    assert any(check["kind"] in ("bytes", "register", "self")
               for check in four["checks"])


def test_the_tool_is_exposed_over_the_protocol(roots):
    """The server must offer it: a module nobody can call is not a tool."""
    import json

    from itl_mcp.server import reservation_scope

    payload = json.loads(reservation_scope(TREATY, "4"))
    assert payload["answer"] is True
    assert payload["answered_by"] == [NORWAY]
