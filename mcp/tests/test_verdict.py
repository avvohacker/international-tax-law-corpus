"""The verdict, and the refusals, as tests.

Four things are asserted here, and the second and third matter as much as the
first:

1. The verdict on the one treaty the library holds is ``not-modified``, for
   the reason the data supports: the United States is not an MLI party.
2. The server refuses instead of guessing when a lookup is ambiguous.
3. The verification actually fails on wrong bytes, rather than reporting a
   pass it did not earn.
4. A covered-agreements table is attributed to the party that FILED it, not
   to the state it names -- a bug that made this server say the opposite
   before these tests existed.
"""

import json

import pytest

from itl_mcp.roots import RootsError, load_roots
from itl_mcp.verify import (
    ABSENT,
    BYTES,
    REGISTER,
    SELF,
    VerificationError,
    sha256_of_text,
    verify_all,
    verify_position,
    verify_treaty,
)
from itl_mcp.verdict import (
    Undecidable,
    _same_jurisdiction,
    _shares_leading_words,
    as_modified,
    find_party,
    normalise,
)


# --------------------------------------------------------------------------
# the verdict itself
# --------------------------------------------------------------------------

def test_verdict_is_not_modified(roots):
    verdict = as_modified(roots, "uk-us-2001")
    assert verdict.verdict == "not-modified"


def test_the_reason_is_the_us_absence_not_a_lucky_guess(roots):
    """The verdict must rest on the US row being absent, and say so."""
    verdict = as_modified(roots, "uk-us-2001")
    joined = " ".join(verdict.reasoning)
    assert "not a signatory or party to the MLI at all" in joined
    us = [s for s in verdict.status if "United States" in s.party]
    assert len(us) == 1
    assert us[0].row is None
    assert us[0].ambiguous is False


def test_the_uk_is_found_as_an_mli_party(roots):
    """The UK must be found -- the earlier bug reported it absent."""
    verdict = as_modified(roots, "uk-us-2001")
    uk = [s for s in verdict.status if "United Kingdom" in s.party]
    assert len(uk) == 1
    assert uk[0].row is not None
    assert uk[0].matched == "United Kingdom*"
    assert uk[0].is_mli_party is True
    assert uk[0].in_force_since == "01-10-2018"


def test_every_artefact_the_verdict_read_verified(roots):
    """No check may fail, and the strong ones must actually be present."""
    verdict = as_modified(roots, "uk-us-2001")
    assert all(c.ok is not False for c in verdict.checks)
    kinds = {c.kind for c in verdict.checks}
    assert BYTES in kinds, "the page hashes must really be recomputed"
    # 39 pages are checked one by one, so a single bad page would be named.
    page_checks = [c for c in verdict.checks if c.artefact.endswith("treaty.json#page-1")]
    assert len(page_checks) == 1
    assert page_checks[0].ok is True


def test_the_assumption_is_declared_not_smuggled(roots):
    """The MLI-both-parties rule is not in the data; it must be labelled."""
    verdict = as_modified(roots, "uk-us-2001")
    assert verdict.assumptions, "the rule deciding the verdict must be declared"
    assert any("NOT held in this project's data" in a for a in verdict.assumptions)


def test_the_silences_are_reported(roots):
    verdict = as_modified(roots, "uk-us-2001")
    joined = " ".join(verdict.silences)
    assert "no MLI position document filed by United States of America" in joined
    assert "by page, not by article" in joined


def test_the_status_is_dated(roots):
    """A verdict about treaty status is only true as of a date."""
    verdict = as_modified(roots, "uk-us-2001")
    assert verdict.as_of == "15 September 2026"


# --------------------------------------------------------------------------
# attribution: whose document says what
# --------------------------------------------------------------------------

def test_covered_table_is_attributed_to_its_filer(roots):
    """The UK filed the table that names the USA -- not the other way round."""
    verdict = as_modified(roots, "uk-us-2001")
    listed = [c for c in verdict.covered if c.listed]
    assert len(listed) == 1
    found = listed[0]
    assert "United Kingdom" in found.filer
    assert "United States" in found.counterparty
    assert found.entry["no"] == 113
    assert found.entry["other_jurisdiction"] == "USA"
    assert found.entry["page"] == 18


def test_the_us_has_no_position_document(roots):
    verdict = as_modified(roots, "uk-us-2001")
    us = [c for c in verdict.covered if "United States" in c.filer]
    assert len(us) == 1
    assert us[0].has_position is False
    assert us[0].listed is False


# --------------------------------------------------------------------------
# refusing to guess
# --------------------------------------------------------------------------

def test_ambiguous_lookup_refuses_rather_than_picks(roots):
    """An ambiguous party lookup must raise, not silently answer."""
    signatories = json.loads(
        (roots.corpus / "corpora" / "mli" / "signatories-and-parties.json")
        .read_text(encoding="utf-8")
    )
    # 'United' alone matches both the UAE and the UK.
    status = find_party(signatories, "United")
    assert status.ambiguous is True
    assert status.row is None
    assert "AMBIGUOUS" in status.method


def test_absent_lookup_is_not_ambiguous(roots):
    """Absence and ambiguity are different facts and must not be merged."""
    signatories = json.loads(
        (roots.corpus / "corpora" / "mli" / "signatories-and-parties.json")
        .read_text(encoding="utf-8")
    )
    status = find_party(signatories, "United States of America")
    assert status.row is None
    assert status.ambiguous is False
    assert "not found" in status.method


def test_unknown_treaty_refuses(roots):
    with pytest.raises(Undecidable) as excinfo:
        as_modified(roots, "atlantis-1999")
    assert "no treaty" in str(excinfo.value)


# --------------------------------------------------------------------------
# the matcher, on its own
# --------------------------------------------------------------------------

@pytest.mark.parametrize("left,right,expected", [
    ("United Kingdom", "United Kingdom of Great Britain and Northern Ireland", True),
    ("United Arab Emirates", "United Kingdom of Great Britain and Northern Ireland", False),
    ("United", "United Kingdom", True),
    ("United Kingdom", "United States of America", False),
    ("Italy", "Italy", True),
    ("Italia", "Italy", False),
])
def test_leading_words_match_on_word_boundaries(left, right, expected):
    assert _shares_leading_words(left, right) is expected


@pytest.mark.parametrize("a,b,expected", [
    ("USA", "United States of America", True),
    ("United States of America", "USA", True),
    ("United Kingdom*", "United Kingdom of Great Britain and Northern Ireland", True),
    ("United Arab Emirates*", "United Kingdom", False),
])
def test_jurisdiction_aliases_and_markers(a, b, expected):
    assert _same_jurisdiction(a, b) is expected


def test_normalise_strips_footnote_markers():
    assert normalise("United Kingdom*") == "United Kingdom"
    assert normalise("  Curaçao* ") == "Curaçao"


# --------------------------------------------------------------------------
# verification that actually fails on wrong bytes
# --------------------------------------------------------------------------

def test_a_tampered_page_fails_verification(tmp_path):
    """Flip one byte of text and the check must fail, not quietly pass."""
    library = tmp_path / "library"
    treaty_dir = library / "treaties" / "fake-1900"
    treaty_dir.mkdir(parents=True)
    payload = {
        "id": "fake-1900",
        "page_count": 1,
        "parties": ["Atlantis", "Elfi"],
        "source": {"sha256": "0" * 64},
        "units": [{
            "page": 1,
            "chars": 5,
            "sha256": sha256_of_text("clean"),
            "gap": None,
            "gap_reason": None,
            "text": "clean",
        }],
    }
    (treaty_dir / "treaty.json").write_text(json.dumps(payload), encoding="utf-8")

    checks = verify_treaty(library, "fake-1900")
    assert all(c.ok is not False for c in checks), "the untampered fixture must pass"

    payload["units"][0]["text"] = "dirt"          # same length, different bytes
    (treaty_dir / "treaty.json").write_text(json.dumps(payload), encoding="utf-8")
    checks = verify_treaty(library, "fake-1900")
    failed = [c for c in checks if c.ok is False]
    assert failed, "a tampered page must fail its bytes check"
    with pytest.raises(VerificationError):
        verify_all(checks)


def test_a_position_whose_register_filename_differs_still_verifies(roots):
    """A check must not call a provable artefact unprovable over a spelling.

    Six register files are named the way the publisher spells the country, not
    the way the published slug reads: czechia's PDF is registered as
    ``mli-position-czech-republic.pdf`` and turkiye's as ``-turkey.pdf``. A
    check that derived the filename from the slug reported all six as
    unprovable. It goes by the declared hash instead, and names the file the
    register actually holds.
    """
    check = verify_position(roots.corpus, "czechia")[0]
    assert check.kind == REGISTER
    assert check.ok is True
    assert "czech-republic" in check.note

    for slug, registered in (
        ("turkiye", "turkey"),
        ("china-people-s-republic-of", "china"),
        ("hong-kong-china", "hong-kong"),
        ("russian-federation-provisional", "russia"),
        ("cote-d-ivoire", "cote-divoire"),
    ):
        found = verify_position(roots.corpus, slug)[0]
        assert found.ok is True, (slug, found.note)
        assert registered in found.note, (slug, found.note)


def test_every_published_position_names_a_registered_source(roots):
    """The whole family, not a sample: no published position is left unproven."""
    directory = roots.corpus / "corpora" / "mli" / "positions"
    slugs = sorted(p.stem for p in directory.glob("*.json")
                   if p.name != "batch-report.json")
    assert len(slugs) > 3, "the corpus should hold the whole position family"
    unproven = [
        (slug, check.note)
        for slug in slugs
        for check in verify_position(roots.corpus, slug)
        if check.ok is not True
    ]
    assert not unproven, unproven


def test_check_kinds_are_honest(roots):
    """No check may claim 'bytes' when it could not recompute anything."""
    verdict = as_modified(roots, "uk-us-2001")
    for check in verdict.checks:
        if check.kind == BYTES:
            assert check.actual is not None, f"{check.artefact} claims bytes without an actual"
            assert check.declared is not None
        if check.kind == ABSENT:
            assert check.ok is None, "an absent check must never read as a pass"
        if check.kind in (REGISTER, SELF):
            assert check.note, "the weaker checks must say what they prove"


# --------------------------------------------------------------------------
# roots refuse to guess a path
# --------------------------------------------------------------------------

def test_missing_env_vars_raise():
    import os
    saved = {k: os.environ.pop(k, None) for k in ("ITL_CORPUS_ROOT", "ITL_LIBRARY_ROOT")}
    try:
        with pytest.raises(RootsError) as excinfo:
            load_roots()
        assert "ITL_CORPUS_ROOT" in str(excinfo.value)
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def test_a_path_that_is_not_the_corpus_is_rejected(tmp_path):
    not_corpus = tmp_path / "empty"
    not_corpus.mkdir()
    with pytest.raises(RootsError) as excinfo:
        load_roots(corpus=not_corpus, library=tmp_path)
    assert "does not look like the corpus" in str(excinfo.value)
