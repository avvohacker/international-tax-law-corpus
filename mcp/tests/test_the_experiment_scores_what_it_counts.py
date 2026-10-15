"""The experiment's counters, and the baseline this repository has recorded.

Two things are asserted here, and they are different.

The **counters** are asserted against hand-built transcripts, because a scorer
that cannot be made to count the three failures is a scorer nobody can trust to
count them in a model's answers. Each test makes one failure and asserts that
exactly that counter moved: a wrong verdict, a citation that does not carry the
fact, and a gap filled where the data is silent.

The **baseline** is asserted against the reader in `experiments/plain_reader.py`,
which reads the real checkouts and applies the plainest rule each question
suggests. The numbers below are the ones `mcp/README.md` publishes, so this test
is what keeps that claim from becoming a memory: if a change in the corpus or the
library closes one of these traps, the trap is reported here rather than quietly
disappearing from a table in a README.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import plain_reader                                                 # noqa: E402
import score_answers                                                # noqa: E402

# A key small enough to score by hand, with one answer that carries evidence and
# one that is silent.
ENTRIES = [
    {"question": "verdict", "expected": "modified", "silent": False,
     "evidence": [["norway", 4, 28]], "why": "both parties are covered"},
    {"question": "scope", "expected": None, "silent": True, "evidence": [],
     "why": "the Article files no reservation"},
]


def transcript(**answers) -> dict:
    return {"reader": "test", "answers": [
        {"question": question, "verdict": verdict, "citations": citations}
        for question, (verdict, citations) in answers.items()]}


def counts(given: dict) -> dict:
    return score_answers.score(given, ENTRIES)["counts"]


def test_a_transcript_that_is_right_is_counted_as_nothing():
    found = counts(transcript(verdict=("modified", [["norway", 4, 28]]),
                              scope=(None, [])))
    assert found == {"wrong_verdict": 0, "filled_gap": 0,
                     "unsupported_citation": 0, "unanswered": 0}


def test_a_verdict_the_data_does_not_support_is_a_wrong_verdict():
    found = counts(transcript(verdict=("not-modified", []), scope=(None, [])))
    assert found["wrong_verdict"] == 1
    assert found["filled_gap"] == 0 and found["unsupported_citation"] == 0


def test_answering_a_silent_question_is_a_gap_filled_not_a_wrong_verdict():
    """The distinction matters: one is an opinion, the other is an invention."""
    found = counts(transcript(verdict=("modified", [["norway", 4, 28]]),
                              scope=(False, [])))
    assert found["filled_gap"] == 1
    assert found["wrong_verdict"] == 0


def test_a_citation_the_answer_does_not_carry_is_counted():
    found = counts(transcript(verdict=("modified", [["norway", 9, 99]]),
                              scope=(None, [])))
    assert found["unsupported_citation"] == 1
    assert found["wrong_verdict"] == 0


def test_a_wrong_row_on_the_right_page_is_counted():
    """The page is the strong half of a citation, and the row is checked too."""
    found = counts(transcript(verdict=("modified", [["norway", 4, 99]]),
                              scope=(None, [])))
    assert found["unsupported_citation"] == 1


def test_a_citation_may_name_a_page_without_a_row():
    """An answer that names a page and no row is checkable at that page."""
    found = counts(transcript(verdict=("modified", [["norway", 4, None]]),
                              scope=(None, [])))
    assert found["unsupported_citation"] == 0


def test_an_answer_that_is_missing_is_reported_as_unanswered():
    found = counts(transcript(verdict=("modified", [["norway", 4, 28]])))
    assert found["unanswered"] == 1
    assert found["wrong_verdict"] == 0 and found["filled_gap"] == 0


def test_a_token_spelled_as_a_string_is_read_as_the_token_it_means():
    """A model writes `"null"` in JSON about half the time; that is a null."""
    assert score_answers._token("null") is None
    assert score_answers._token("true") is True
    assert score_answers._token("False") is False


# --------------------------------------------------------------------------
# the baseline this repository publishes
# --------------------------------------------------------------------------

def baseline(roots) -> list[dict]:
    return [score_answers.score(transcript_of, score_answers.key(roots))
            for transcript_of in plain_reader.transcripts(roots.corpus, roots.library)]


def test_the_reader_without_the_marker_gets_the_second_verdict_wrong(roots):
    """Strict names: the UK's row is printed `United Kingdom*`, and is not found."""
    strict = baseline(roots)[0]
    assert strict["counts"]["wrong_verdict"] == 1
    wrong = [row for row in strict["rows"] if row["verdict"] == "WRONG"]
    assert wrong and wrong[0]["question"] == plain_reader.NO_UK
    assert wrong[0]["answered"] == "not-modified"
    # And the first verdict came out right without any evidence behind it: the
    # token is not the answer.
    first = strict["rows"][0]
    assert first["verdict"] == "ok" and first["citations"] == "none offered"


def test_normalising_the_marker_is_what_saves_the_second_verdict(roots):
    helpful = baseline(roots)[1]
    assert helpful["counts"]["wrong_verdict"] == 0
    assert helpful["counts"]["unsupported_citation"] == 0


def test_no_plain_reader_escapes_the_announced_list(roots):
    """The trap that is not a habit but a missing rule: a list never captured."""
    for scored in baseline(roots):
        assert scored["counts"]["filled_gap"] >= 1
        gap = [row for row in scored["rows"] if row["verdict"] == "gap filled"]
        assert gap, scored
        assert any(row["question"] == plain_reader.ARTICLE_7 for row in gap), scored


def test_answering_what_it_cannot_find_costs_the_fourth_question(roots):
    analogy = baseline(roots)[2]
    assert analogy["counts"]["filled_gap"] == 2
    gaps = {row["question"] for row in analogy["rows"]
            if row["verdict"] == "gap filled"}
    assert gaps == {plain_reader.ARTICLE_7, plain_reader.UNKNOWN_TREATY}


def test_the_key_carries_the_two_silences_and_the_refusal(roots):
    """The key is the server's answer, and it must contain a gap as a gap."""
    entries = {entry["question"]: entry for entry in score_answers.key(roots)}
    assert set(entries) == set(plain_reader.QUESTIONS)
    for question in (plain_reader.ARTICLE_7, plain_reader.UNKNOWN_TREATY):
        assert entries[question]["silent"] is True, question
        assert entries[question]["evidence"] == [], question
    assert entries[plain_reader.NO_UK]["expected"] == "modified"
    assert entries[plain_reader.NO_UK]["evidence"], \
        "a verdict that can be checked must carry the places it can be checked at"


def test_the_material_the_prompt_names_is_really_there(roots):
    """A prompt that sends a reader to a file that does not exist measures nothing."""
    for label, path in score_answers._material(roots):
        assert path.is_file(), f"{label} is named and missing: {path}"
        assert path.stat().st_size < (1 << 20), \
            f"{label} is over the 1 MB a reader returns in full: {label}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
