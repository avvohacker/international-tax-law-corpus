"""The chain of MLI Articles, and what each party's own position says.

The library now holds a treaty between two states that are BOTH MLI parties
with the MLI in force for each: the 2013 UK-Norway convention. That is the
case the verdict existed for and could not previously exercise -- against the
US-UK convention the only answer available was ``not-modified`` for want of an
MLI party on one side.

What is asserted here is the shape of the chain and the honesty of its
sentences: that it covers every Article the corpus maps as changing a treaty
and not only the ones a party spoke about, that it attributes each statement
to the party that filed it, that it reports a reservation's qualifier instead
of flattening it, and that it looks this treaty up in the list of agreements a
statement prints within its reservation's scope - answering "on the list" or
"not on it" with the row, and saying the data cannot answer where the corpus
holds no reading of that list.
"""

import json

import pytest

from itl_mcp.verify import (
    REGISTER,
    VerificationError,
    verify_all,
    verify_mapping,
)
from itl_mcp.verdict import (
    MODIFYING_MODES,
    _read_articles,
    _reservations_in_full,
    as_modified,
)

TREATY = "no-uk-2013"
NORWAY = "Norway"
UNITED_KINGDOM = "United Kingdom of Great Britain and Northern Ireland"


@pytest.fixture(scope="module")
def verdict(roots):
    return as_modified(roots, TREATY)


@pytest.fixture(scope="module")
def by_article(verdict):
    return {a.number: a for a in verdict.articles}


# --------------------------------------------------------------------------
# the verdict itself
# --------------------------------------------------------------------------

def test_a_treaty_between_two_mli_parties_is_modified(verdict):
    assert verdict.verdict == "modified"


def test_both_parties_list_it_as_covered(verdict):
    """Mutual notification is what makes this a real case, not a lucky one."""
    listed = [c for c in verdict.covered if c.listed]
    assert len(listed) == 2
    assert {c.filer for c in listed} == {NORWAY, UNITED_KINGDOM}
    assert {c.counterparty for c in listed} == {NORWAY, UNITED_KINGDOM}


def test_the_verdict_still_carries_its_checks(verdict):
    assert all(c.ok is not False for c in verdict.checks)
    assert any(c.kind == REGISTER and "mli-convention-2016" not in c.artefact
               for c in verdict.checks), "the mapping must be checked too"


def test_the_chain_is_not_empty_and_is_ordered(verdict):
    numbers = [int(a.number) for a in verdict.articles]
    assert numbers, "a modified verdict must show its chain"
    assert numbers == sorted(numbers), "the chain is read in Article order"


# --------------------------------------------------------------------------
# the chain's completeness and attribution
# --------------------------------------------------------------------------

def test_the_chain_covers_every_modifying_article_not_only_the_recorded_ones(roots, by_article):
    """An Article nobody spoke about is still an Article that changes a treaty.

    Leaving those out would let the chain read as shorter than it is, so they
    are listed with a reading that says plainly that nothing was recorded.
    """
    mapping = json.loads(
        (roots.corpus / "corpora" / "mli" / "mapping.json").read_text(encoding="utf-8")
    )
    expected = {
        str(row["article"]) for row in mapping["rows"]
        if str(row.get("mode")) in MODIFYING_MODES
    }
    assert set(by_article) == expected

    silent = [a for a in by_article.values() if not a.recorded]
    assert silent, "this pair left some Articles unrecorded, which must be shown"
    for article in silent:
        assert "Neither party's position document records" in article.reading


def test_every_statement_is_attributed_to_the_party_that_filed_it(by_article):
    for article in by_article.values():
        for party, entries in article.recorded.items():
            assert party in (NORWAY, UNITED_KINGDOM), party
            assert entries, party
            for entry in entries:
                assert entry.get("kind") in {"Reservation", "Notification", "Choice"}, entry
                assert isinstance(entry.get("page"), int)


def test_the_chain_maps_articles_onto_the_treaty_s_own_articles(by_article):
    """The link to the treaty is the corpus's, and it is shown."""
    assert by_article["8"].targets == ["10"]     # dividends
    assert by_article["9"].targets == ["13"]     # capital gains
    assert by_article["17"].targets == ["9"]     # associated enterprises
    assert by_article["12"].targets == ["5"]     # permanent establishment
    assert by_article["16"].targets == ["25"]    # mutual agreement
    for article in by_article.values():
        if article.targets:
            assert "treaty's own Article" in article.reading


def test_article_six_is_marked_as_acting_on_the_preamble(by_article):
    six = by_article["6"]
    assert six.mode == "preamble"
    assert six.targets == []
    assert "preamble" in six.reading


# --------------------------------------------------------------------------
# reservations: the qualifier is the whole point
# --------------------------------------------------------------------------

def test_both_sides_reserve_article_eight_and_norway_s_qualifies(by_article):
    """Norway's reservation on Art. 8 is conditional; the UK's is not.

    Reported flat, these two would read identically, which is exactly the
    mistake that matters: Art. 8(3)(b)(i) withholds the Article only to the
    extent the treaty already has a minimum holding period, while Art. 8(3)(a)
    withholds it outright.
    """
    eight = by_article["8"]
    withheld = {r["party"]: r for r in eight.reservations_in_full}
    assert set(withheld) == {NORWAY, UNITED_KINGDOM}
    assert withheld[NORWAY]["qualified_by"] == "to the extent"
    assert withheld[UNITED_KINGDOM]["qualified_by"] is None
    assert "to the extent that the provisions described in Article 8(1)" in withheld[NORWAY]["continues"]
    assert withheld[UNITED_KINGDOM]["continues"] == "to its Covered Tax Agreements."
    assert "1 of them through a qualifier" in eight.reading


def test_a_statement_naming_the_agreements_is_answered_from_its_own_list(by_article):
    """The statement's list of agreements settles this treaty's position in it.

    Without this, a reader would take "reserves the right for the entirety of
    Article 8 not to apply to its Covered Tax Agreements" as settling this
    treaty's position, when the very next sentence is the list that would. The
    corpus reads that list, so the chain answers the question the list was
    printed for, in both directions: on Article 4 the UK-Norway convention is
    one of the agreements Norway names (row and provision quoted), and on
    Article 8 it is not, so by Norway's own list that reservation does not
    reach it.
    """
    four = by_article["4"].reservations_in_full[0]
    assert four["scope_lists"][0]["rows"] and four["scope_lists"][0]["page"]
    assert four["in_the_reservation_scope"] is True
    row = four["scope_evidence"][0]
    assert row["no"] and row["page"] and row["provision"]
    assert row["other_jurisdiction"].startswith("United Kingdom")
    assert "this treaty is one of them" in by_article["4"].reading
    assert f"row {row['no']}" in by_article["4"].reading

    eight = by_article["8"].reservations_in_full[0]
    assert eight["scope_lists"][0]["rows"]
    assert eight["in_the_reservation_scope"] is False
    assert eight["scope_evidence"] == []
    assert "this treaty is not among them" in by_article["8"].reading
    assert "cannot be read from this data" not in by_article["8"].reading


def test_a_list_the_corpus_could_not_read_leaves_the_question_open():
    """An unread list is not a "no": the chain says the data cannot answer.

    The distinction is the whole point of keeping the reader's reason: a
    statement whose table this corpus could not read leaves the treaty's
    position inside the reservation undecided, and the chain says so instead
    of reporting the treaty as outside it.
    """
    entry = {
        "kind": "Reservation", "page": 3,
        "excerpt": (
            "Pursuant to Article 8(3)(a) of the Convention, Norway reserves "
            "the right for the entirety of Article 8 not to apply to its "
            "Covered Tax Agreements. The following agreements contain "
            "provisions that are within the scope of this reservation."),
        "scope_lists": [{
            "read": False, "page": 4,
            "reason": "the statement announces a list of agreements and no "
                      "table is printed under that sentence"}],
    }
    found = _reservations_in_full("8", [entry], NORWAY)
    assert found[0]["in_the_reservation_scope"] is None
    assert found[0]["scope_evidence"] == []
    assert found[0]["announces_a_list_not_captured"] is True
    assert found[0]["scope_lists"][0]["reason"].startswith("the statement")


def test_a_list_names_a_state_however_each_document_spells_it():
    """The lookup matches the way the tables spell a state, not by spelling.

    The covered-agreements tables of these documents print short forms where
    the library prints a name in full, so a list is searched with the same
    jurisdiction matching the covered-agreements lookup uses.
    """
    def entry_for(name: str) -> dict:
        return {
            "kind": "Reservation", "page": 3,
            "excerpt": (
                "Pursuant to Article 8(3)(a) of the Convention, Norway "
                "reserves the right for the entirety of Article 8 not to "
                "apply to its Covered Tax Agreements. The following "
                "agreements contain provisions that are within the scope of "
                "this reservation."),
            "scope_lists": [{
                "read": True, "page": 4,
                "headings": ["Listed Agreement Number"], "rows": [
                    {"no": 7, "page": 4, "other_jurisdiction": name,
                     "text": "Article 8(1)"}],
                "rows_without_a_counterparty": 0, "rows_without_a_text": 0}],
        }
    found = _reservations_in_full("8", [entry_for("USA")],
                                  "United States of America")
    assert found[0]["in_the_reservation_scope"] is True
    assert found[0]["scope_evidence"][0]["no"] == 7
    # And a name the table does not print is not matched by guesswork.
    other = _reservations_in_full("8", [entry_for("Chile")], "Norway")
    assert other[0]["in_the_reservation_scope"] is False


def test_a_reservation_of_a_paragraph_is_not_reported_as_the_entirety(by_article):
    """Article 9's reservations take out Article 9(1), not all of Article 9."""
    nine = by_article["9"]
    assert nine.recorded[NORWAY] and nine.recorded[UNITED_KINGDOM]
    assert nine.reservations_in_full == []
    assert "entirety of Article 9" not in nine.reading


# --------------------------------------------------------------------------
# the reservations reader, on its own
# --------------------------------------------------------------------------

@pytest.mark.parametrize("number,excerpt,count,qualifier", [
    ("8", "Norway reserves the right for the entirety of Article 8 not to "
          "apply to its Covered Tax Agreements to the extent that x", 1, "to the extent"),
    ("8", "the United Kingdom reserves the right for the entirety of Article 8 "
          "not to apply to its Covered Tax Agreements.", 1, None),
    ("17", "Norway reserves the right for the entirety of Article 17 not to "
           "apply to its Covered Tax Agreements that already contain y",
     1, "that already contain"),
    # A different Article's name in the same excerpt must not match.
    ("7", "reserves the right for the entirety of Article 8 not to apply", 0, None),
    # A paragraph-level reservation is not an entirety reservation.
    ("9", "reserves the right for Article 9(1) not to apply", 0, None),
])
def test_only_the_entirety_reservations_of_this_article_are_read(
        number, excerpt, count, qualifier):
    entries = [{"kind": "Reservation", "excerpt": excerpt, "page": 1}]
    found = _reservations_in_full(number, entries)
    assert len(found) == count
    if found:
        assert found[0]["qualified_by"] == qualifier
        assert found[0]["page"] == 1


def test_a_notification_that_mentions_an_entirety_is_not_a_reservation():
    """The reader reads the kind as well as the words."""
    entries = [{"kind": "Notification", "page": 2,
                "excerpt": "reserves the right for the entirety of Article 8 not to apply"}]
    assert _reservations_in_full("8", entries) == []


# --------------------------------------------------------------------------
# what the chain leaves out, and why it says so
# --------------------------------------------------------------------------

def test_the_excluded_articles_are_named_not_implied(verdict):
    joined = " ".join(verdict.silences)
    assert "The chain leaves out the Articles the corpus maps under" in joined
    assert "support: 15" in joined          # Art. 15 defines a PE
    assert "none: 1, 2" in joined           # scope and definitions


def test_the_compatibility_caveat_is_declared(verdict):
    """The one thing the data cannot settle, said out loud."""
    joined = " ".join(verdict.silences)
    assert "compatibility clauses" in joined
    assert "does not decide which modification ends up applying" in joined


# --------------------------------------------------------------------------
# the mapping's own verification
# --------------------------------------------------------------------------

def test_the_mapping_is_verified_against_the_corpus_register(roots):
    checks = verify_mapping(roots.corpus)
    assert len(checks) == 1
    check = checks[0]
    assert check.kind == REGISTER
    assert check.ok is True
    assert "MLI convention" in check.note
    verify_all(checks)


def test_a_mapping_with_a_wrong_source_hash_fails(roots, tmp_path):
    """The check must be able to fail, or it proves nothing."""
    corpus = tmp_path / "corpus"
    (corpus / "corpora" / "mli").mkdir(parents=True)
    (corpus / "provenance").mkdir(parents=True)
    good = roots.corpus / "corpora" / "mli" / "mapping.json"
    (corpus / "corpora" / "mli" / "mapping.json").write_text(
        good.read_text(encoding="utf-8").replace(
            json.loads(good.read_text(encoding="utf-8"))["sha256"], "0" * 64
        ),
        encoding="utf-8",
    )
    (corpus / "provenance" / "sources.yaml").write_text(
        (roots.corpus / "provenance" / "sources.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    checks = verify_mapping(corpus)
    assert checks[0].ok is False
    with pytest.raises(VerificationError):
        verify_all(checks)


def test_the_chain_needs_no_position_document_it_does_not_have(roots):
    """_read_articles survives a party with no position file, without inventing."""
    mapping = json.loads(
        (roots.corpus / "corpora" / "mli" / "mapping.json").read_text(encoding="utf-8")
    )
    articles = _read_articles(mapping, {NORWAY: None, UNITED_KINGDOM: None},
                              [NORWAY, UNITED_KINGDOM])
    assert articles
    for article in articles:
        assert article.recorded == {}
        assert "Neither party's position document records" in article.reading
