"""The same Article in two editions, and the edition that says nothing.

The point of this tool is not that it can show a provision twice. It is that it
names the edition which does not print the provision at all -- an answer that
quoted only the edition holding it would present an addition as if it had always
been there. These tests assert both halves: the citation of the units, and the
silence.
"""

import pytest

from itl_mcp.editions import (DIFF_BUCKETS, compare, diff_report,
                               normalise_article)


def test_an_article_added_by_the_later_edition_names_the_silent_one(roots):
    """Article 12B exists in 2021 and not in 2017; 2017 must be called silent."""
    answer = compare(roots.corpus, "12B")

    assert answer["present_in"] == {"2017": False, "2021": True}
    assert answer["units"]["2017"] == [], \
        "the silent edition must cite no unit rather than a nearby one"
    assert answer["units"]["2021"], "the edition that prints it must be cited"

    assert "2017" in answer["reading"] and "silent" in answer["reading"]
    assert "12B" in answer["reading"]
    assert answer["in_the_corpus_diff"] == "added"


def test_the_cited_units_are_the_corpus_s_own_nodes(roots):
    """A citation is an eId, a number and a page -- not a paraphrase."""
    answer = compare(roots.corpus, "12B")
    first = answer["units"]["2021"][0]

    assert first["eId"] == "art_12B"
    assert first["tag"] == "article"
    assert first["number"].startswith("Article")
    assert isinstance(first["page"], int)
    assert first["heading"] == "INCOME FROM AUTOMATED DIGITAL SERVICES"

    # every unit belongs to the Article that was asked about
    assert all(unit["eId"] == "art_12B" or unit["eId"].startswith("art_12B__")
               for unit in answer["units"]["2021"])


def test_an_article_in_both_editions_is_compared_not_just_quoted(roots):
    """Article 5 is in both; the answer must carry both editions' units."""
    answer = compare(roots.corpus, "5")

    assert answer["present_in"] == {"2017": True, "2021": True}
    assert answer["units"]["2017"] and answer["units"]["2021"]
    assert len(answer["units"]["2017"]) > 5
    assert answer["in_the_corpus_diff"] in {"modified", "unchanged"}
    assert "silent" not in answer["reading"]


def test_a_modified_article_carries_the_diff_s_own_entry(roots):
    """The changed units are quoted by the corpus's diff, not described here."""
    answer = compare(roots.corpus, "5")
    if answer["in_the_corpus_diff"] != "modified":
        pytest.skip("Article 5 is not recorded as modified in this corpus")

    entry = answer["corpus_diff_entry"]
    assert entry["number"].replace(" ", "") == "5"
    changed = (entry.get("units") or {}).get("changed") or []
    assert changed, "a modified Article must carry the units that changed"
    assert changed[0]["old"] and changed[0]["new"], \
        "the diff quotes both the old and the new text of a changed unit"


def test_a_modified_article_names_every_bucket_the_diff_reads(roots):
    """Three empty buckets must not read the same as a bucket never looked at.

    The corpus's diff reads units into four buckets and reads the Article's
    notes into the same four. `renumbered` is empty in the report as committed,
    and a summary that listed only the populated buckets would drop it on the
    day it stopped being empty without any run going red.
    """
    answer = compare(roots.corpus, "5")
    if answer["in_the_corpus_diff"] != "modified":
        pytest.skip("Article 5 is not recorded as modified in this corpus")

    for bucket in DIFF_BUCKETS:
        assert bucket in answer["reading"], bucket

    assert "notes" in answer["reading"], \
        "the diff records the Article's notes too, and the answer must say so"
    entry = answer["corpus_diff_entry"]
    assert sorted(entry.get("notes") or {}) == sorted(DIFF_BUCKETS), \
        "the notes are recorded in the same four buckets the units are"


def test_a_retitled_article_says_it_was_retitled(roots):
    """A heading change is a change; the answer may not omit it."""
    report = diff_report(roots.corpus)
    retitled = [entry for entry in report.get("modified") or []
                if entry.get("retitled")]
    if not retitled:
        pytest.skip("this corpus's diff records no retitling")

    number = str(retitled[0]["number"])
    answer = compare(roots.corpus, number)
    assert answer["in_the_corpus_diff"] == "modified"
    assert "retitled" in answer["reading"], answer["reading"]
    assert str(answer["corpus_diff_entry"].get("old_heading")) in answer["reading"]


def test_every_unit_the_diff_records_carries_its_text(roots):
    """The reading promises the entry carries the text of every recorded unit.

    That promise is what lets the answer summarise by count instead of quoting:
    the count points at the entry, and the entry is where the words are. If it
    stopped being true, the count would be pointing at nothing.
    """
    report = diff_report(roots.corpus)
    seen = 0
    for kind in ("added", "removed", "modified"):
        for entry in report.get(kind) or []:
            units = entry.get("units") or {}
            for unit in units.get("changed") or []:
                assert unit.get("old") and unit.get("new"), \
                    (kind, entry.get("number"), unit.get("eId"))
                seen += 1
            for bucket in ("added", "removed", "renumbered"):
                for unit in units.get(bucket) or []:
                    assert unit.get("text") or (unit.get("old") and unit.get("new")), \
                        (kind, entry.get("number"), bucket, unit.get("eId"))
                    seen += 1
    assert seen > 100, (
        f"only {seen} units were read: this check no longer covers the claim "
        f"the answer makes")


def test_an_added_article_says_the_diff_quotes_no_units_for_it(roots):
    """Article 12B's entry names the Article; the text lives in the index.

    The answer must not imply the diff quotes what it does not: for 12B the
    corpus records the addition by number and heading alone, and the units are
    the node index's business.
    """
    answer = compare(roots.corpus, "12B")
    assert answer["in_the_corpus_diff"] == "added"

    entry = answer["corpus_diff_entry"]
    assert not (entry.get("units") or {}), (
        "this test asserts what the answer says about an entry that carries no "
        "units; if the corpus starts quoting them, both must be updated")
    assert "does not quote units" in answer["reading"], answer["reading"]


def test_an_article_in_neither_edition_says_so(roots):
    """A number no edition prints is answered with a silence, not an empty list."""
    answer = compare(roots.corpus, "99")

    assert answer["present_in"] == {"2017": False, "2021": False}
    assert answer["units"] == {"2017": [], "2021": []}
    assert "neither edition" in answer["reading"]


@pytest.mark.parametrize("asked", ["12B", "12b", "12 B", "art_12B", "Article 12B",
                                   "  article 12 b "])
def test_the_same_article_however_it_is_spelled(roots, asked):
    """The corpus spells the same Article two ways; both must find it."""
    assert compare(roots.corpus, asked)["article"] == "12B"


def test_the_spacing_between_alternative_articles_does_not_matter():
    assert normalise_article("23 A") == normalise_article("art_23A") == "23A"
    assert normalise_article("Article 12 B") == "12B"


def test_the_answer_carries_its_own_verification(roots):
    """The citation rests on bytes somebody committed; they are re-checked."""
    answer = compare(roots.corpus, "5")

    assert answer["checks"], "the answer must carry what was verified"
    kinds = {check["kind"] for check in answer["checks"]}
    assert "bytes" in kinds, "the AKN documents must really be re-hashed"
    assert all(check["result"] != "MISMATCH" for check in answer["checks"])
    asserted = {check["artefact"] for check in answer["checks"]}
    assert any(a.endswith("model-2017.akn.xml") for a in asserted)
    assert any(a.endswith("model-2021.akn.xml") for a in asserted)


def test_the_tool_refuses_a_corpus_without_the_editions(tmp_path):
    """A checkout that cannot answer must say so, not answer anyway."""
    with pytest.raises(FileNotFoundError):
        compare(tmp_path, "5")


def test_the_tool_is_exposed_over_the_protocol(roots):
    """The server must offer it: a module nobody can call is not a tool."""
    import json as _json
    from itl_mcp.server import compare_model_editions

    payload = _json.loads(compare_model_editions("12B"))
    assert payload["present_in"]["2017"] is False
    assert payload["reading"]
