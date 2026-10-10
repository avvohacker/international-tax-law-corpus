"""The drift control's pull-request material, and what it covers.

`python -m harness drift` is the control (invariant in `test_invariants.py`);
when it fails, the automated check in `.github/workflows/corpus-drift.yml` opens
a pull request whose body is `harness.drift.pr_body`. That body has to carry the
regenerated artefacts and the row-by-row difference and nothing else, and it has
to be a function of the comparison alone - which is what lets the check open the
request without inventing prose about the repair. This module pins that
function, and pins the two comparisons the control gained: the derived markdown
views (compared line by line) and the register's own hashes. It also pins
`drift.schema_violations`, the check `drift --check-schema` runs, that every
unit of that material names a line or a field and never a byte count, and that
the attach band a covered-agreements reading measured travels into the corpus
as a field the control compares - so a repair that moves a run into the gap one
of those tolerances sits in is named by the control and not only by the tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import __main__ as cli
from harness import corpus, drift
from harness import ledger
from harness import mli as mli_writer
from harness import views as view_writer

ROOT = Path(__file__).resolve().parent.parent


def _divergent() -> dict:
    return {
        "compared": 185,
        "live": {"corpora/mli/positions/nigeria.json": "/tmp/live/nigeria.json"},
        "provenance": 0,
        "published_but_unbuilt": [],
        "differences": [{
            "path": "corpora/mli/positions/nigeria.json",
            "kind": "differs",
            "units": [
                {"unit": "covered_agreements[6].signature",
                 "stored": "06-11-2006 N/A", "live": "06-11-2006"},
                {"unit": "covered_agreements[6].entry_into_force",
                 "stored": None, "live": "N/A"},
            ],
        }],
    }


def test_pr_material_names_only_the_regenerated_artefacts_and_their_rows():
    result = _divergent()
    assert drift.pr_title(result) == (
        "drift: rebuild corpora/mli/positions/nigeria.json from the live reading")
    body = drift.pr_body(result)
    assert "corpora/mli/positions/nigeria.json" in body
    # The difference is quoted unit for unit, so a reviewer sees the rewrite
    # without opening a hunk.
    assert "covered_agreements[6].signature" in body
    assert "06-11-2006 N/A" in body
    assert "covered_agreements[6].entry_into_force" in body
    assert "'N/A'" in body
    assert "185 artefact(s)" in body
    # An artefact that diverged is never named as a document that did not.
    assert "_No document diverged._" not in body


def test_a_clean_corpus_asks_for_no_repair():
    result = {"compared": 185, "live": {}, "provenance": 0,
              "published_but_unbuilt": [], "differences": []}
    assert drift.divergent_artifacts(result) == []
    assert drift.pr_body(result).find("_No document diverged._") != -1


def test_provenance_is_reported_in_the_body_but_never_republished():
    result = _divergent()
    result["provenance"] = 1
    result["differences"].append({
        "path": "provenance/mli-positions.sha256", "kind": "provenance",
        "units": [{"unit": "sources/mli-positions/x.pdf",
                   "stored": "a" * 64, "live": "b" * 64}]})
    # A provenance difference has no live file to copy, so it is not one of the
    # artefacts the request republishes - it is named, and left for a deliberate
    # edit.
    assert [item["path"] for item in drift.divergent_artifacts(result)] == [
        "corpora/mli/positions/nigeria.json"]
    body = drift.pr_body(result)
    assert "### Provenance" in body
    assert "provenance/mli-positions.sha256" in body


def test_markdown_views_are_compared_line_by_line():
    """A derived view is compared by line, not by size.

    The size fallback (`bytes: corpus 857 -> reading 838`) names the file and
    not what moved; a line comparison names the line, which is what a reviewer
    of a regenerated view needs.
    """
    assert drift.describe_difference(
        "derived/markdown/un-model/2017/article-1.md",
        "# Article 1\n\ntext\n", "# Article 1\n\nother\n") == [
        {"unit": "line 3", "stored": "text", "live": "other"}]


def test_every_pr_unit_names_a_line_or_a_field_never_a_size():
    """The material the control would publish must be legible to a reviewer.

    A difference reported as a byte count says the file changed size and not
    what moved. The schema check refuses it, and the fallback it refuses is
    reachable - an artefact of a format nothing compares line by line is still
    compared, by size - so this is a detector and not a comment.
    """
    result = _divergent()
    assert drift.schema_violations(result) == []
    assert drift.describe_difference("artifact.bin", "abc", "abcd") == [
        {"unit": "bytes", "stored": 3, "live": 4}]
    result["differences"].append({
        "path": "artefacts/corpus.bin", "kind": "differs",
        "units": drift.describe_difference("artefacts/corpus.bin", "abc", "abcd"),
    })
    assert drift.schema_violations(result) == [
        "artefacts/corpus.bin: 'bytes' names no line"]


def _band_pair() -> tuple[str, str, str] | None:
    """A published position and the same reading with its band moved.

    Taken from the corpus rather than built, because the claim under test is
    about the artefacts the project publishes: a reader that measures an attach
    band and a data set that carries it.
    """
    for path in sorted(corpus.position_files(ROOT)):
        stored = path.read_text(encoding="utf-8")
        record = json.loads(stored)
        qa = (record.get("qa") or {}).get("covered_agreements") or {}
        band = qa.get("row_attach_band_pt")
        if not band:
            continue
        moved = json.loads(stored)
        moved["qa"]["covered_agreements"]["row_attach_band_pt"] = [
            band[0] - 0.5, band[1]]
        return path.name, stored, json.dumps(moved, ensure_ascii=False)
    return None


def test_a_repair_that_moves_a_measured_band_is_named_by_the_control():
    """The band a reading measured is compared like any other field.

    Each covered-agreements reader publishes the interval its own tolerance had
    on the layout that decided it, as `qa.covered_agreements.row_attach_band_pt`
    - the window one reader places a span with, the reach the other absorbs a run
    of lines with. A repair that moves the reading into that gap is therefore a
    difference the control reports, in the field that names the room the
    tolerance had, and not only in the tests that measure the band: the
    comparison is by JSON path like every other field, and this pins it - the
    band moved half a point is one unit, the edge that moved, and the printed
    material names it with both intervals.
    """
    pair = _band_pair()
    if pair is None:
        pytest.skip("no published position carries a measured attach band")
    name, stored, moved = pair
    assert drift.describe_difference(name, stored, stored) == [], (
        "the control reports a difference between a reading and itself")
    units = drift.describe_difference(name, stored, moved)
    # The band is a pair, so the comparison descends into it and the unit is the
    # edge that moved - the lower one here - rather than the whole pair.
    assert [unit["unit"] for unit in units] == [
        "qa.covered_agreements.row_attach_band_pt[0]"], units
    printed = "\n".join(drift.format_difference(
        {"path": name, "kind": "differs", "units": units}))
    assert "qa.covered_agreements.row_attach_band_pt[0]" in printed
    assert str(json.loads(stored)["qa"]["covered_agreements"]
               ["row_attach_band_pt"][0]) in printed


def test_a_moved_window_is_named_by_the_drift_control_in_the_view(monkeypatch):
    """The band line moves with the window, and the drift control names it.

    The JSON-level repair is pinned beside this one; this is the view-level
    half: one position - mauritius, which sets the window's lower edge - is
    rebuilt twice, once at the declared window and once below the band the
    page leaves it. At the declared value the fresh view is the published one,
    so the comparison is silent and the control cannot be green by emptiness;
    below the band the rows move and the measured band moves, and the drift
    control's own line comparison on the two view texts has to name the attach
    line's number among its units - the band is named where the rows are read,
    not only in the JSON diff.
    """
    pdf = ROOT / "sources" / "mli-positions" / "mli-position-mauritius.pdf"
    if not pdf.is_file():
        pytest.skip("the mauritius position source is not here")
    view_path = (ROOT / "derived" / "markdown" / "mli" / "positions"
                 / "mauritius.md")
    if not view_path.is_file():
        pytest.skip("no published mauritius view to compare against")
    stored = view_path.read_text(encoding="utf-8")
    source = "mli-positions-batch"
    spans = ledger.SpanStream.read(pdf, source)
    book = ledger.Classifier.classify(spans, ledger.Ledger())
    record = mli_writer.position(book, source, pdf)
    assert record["slug"] == "mauritius"
    assert drift.describe_difference(view_path.name, stored,
                                     view_writer.position_view(record)) == [], (
        "the control reports a difference between a reading and itself")
    monkeypatch.setattr(mli_writer, "POS_ATTACH_PT", 5.0)
    moved = mli_writer.position(book, source, pdf)
    live = view_writer.position_view(moved)
    assert live != stored, (
        "moving the window below the band the page leaves moved neither a row "
        "nor the band, so this repair would prove nothing")
    units = drift.describe_difference(view_path.name, stored, live)
    attach_no = next(index for index, line in enumerate(live.splitlines(), 1)
                     if line.startswith("*Attach:"))
    assert f"line {attach_no}" in [unit["unit"] for unit in units], (
        "the drift control names moved rows but not the attach line that "
        f"moved with them: {[unit['unit'] for unit in units]}")


def test_the_check_schema_command_fails_on_a_size_only_unit(monkeypatch, tmp_path):
    """`drift --check-schema` is the check, not only the function it calls."""
    result = {"workdir": tmp_path, "compared": 1, "provenance": 0,
              "live": {}, "published_but_unbuilt": [],
              "differences": [{"path": "corpora/x.json", "kind": "differs",
                               "units": [{"unit": "bytes", "stored": 1,
                                          "live": 2}]}]}
    monkeypatch.setattr(cli.drift, "compare_corpus", lambda root: result)
    assert cli.main(["drift", "--check-schema"]) == 1
    result["differences"][0]["units"] = [
        {"unit": "covered_agreements[0].title", "stored": "a", "live": "b"}]
    assert cli.main(["drift", "--check-schema"]) == 0


def test_a_field_path_a_line_and_a_source_file_all_pass_the_schema():
    """Each artefact kind names a real place in the file it belongs to.

    A corpus JSON by its field path, a derived view by its line, and a register
    hash by the source file it is about - the corpus and its derived artefacts
    alike, and the provenance beside them.
    """
    result = {
        "compared": 185, "live": {}, "provenance": 1,
        "published_but_unbuilt": [],
        "differences": [
            {"path": "corpora/mli/positions/nigeria.json", "kind": "differs",
             "units": [{"unit": "covered_agreements[6].signature",
                        "stored": "06-11-2006 N/A", "live": "06-11-2006"}]},
            {"path": "derived/markdown/un-model/2017/article-1.md",
             "kind": "differs",
             "units": [{"unit": "line 3", "stored": "text", "live": "other"}]},
            {"path": "provenance/mli-positions.sha256", "kind": "provenance",
             "units": [{"unit": "sources/mli-positions/x.pdf",
                        "stored": "a" * 64, "live": "b" * 64}]},
        ]}
    assert drift.schema_violations(result) == []
    # A provenance unit that names no file - a size - is refused too.
    result["differences"][2]["units"] = [
        {"unit": "bytes", "stored": 12, "live": 14}]
    assert drift.schema_violations(result) == [
        "provenance/mli-positions.sha256: 'bytes' names no file"]
