"""Regression checks for MLI covered-agreement tables."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness import ledger, mli
from harness.covered import _read as read_number_first
from harness.checks import evaluate
from harness.defects import load_defects
from support import ROOT

DEFECTS = {defect.id: defect for defect in load_defects()}
D25 = "d25-azerbaijan-footer-band-ate-table-rows"
D26 = "d26-kuwait-packed-date-cell"
PACKED_SIGNATURE_RE = re.compile(r'"signature": "[^"]*N\s*/\s*A')
AZERBAIJAN_BAND_Y = 666.0
CHINA_COVERED_ROW_PINS = {
    20: ("Australia", "17-11-1988", "28-12-1990", "Agreement between the Government"),
    43: ("Slovenia", "13-02-1995", "27-12-1995", "Agreement between the Government"),
    74: ("Oman", "25-03-2002", "20-07-2002", "Agreement between the Government"),
    89: ("Saudi Arabia", "23-01-2006", "01-09-2006", "Agreement between the Government"),
}


def _pdf(slug: str) -> Path:
    return ROOT / "sources" / "mli-positions" / f"mli-position-{slug}.pdf"


def _table(pdf: Path, band_y: float | None = None,
           classifier_source: str | None = None) -> tuple[list[dict], dict, ledger.Ledger]:
    """Read Article 2 rows, optionally simulating an internal footer band."""
    source = classifier_source or pdf.stem
    book = ledger.Classifier.classify(
        ledger.SpanStream.read(pdf, source), ledger.Ledger())
    kept = [span for span, _rule in book.kept
            if band_y is None or span.y < band_y]
    lines = [line for line in ledger.regroup_lines(kept, book.line_policy)
             if line.match_text
             and (book.geometry is None or book.geometry.band(
                 line.page, line.y, line.size) not in ("footer", "note"))]
    spans = sorted(kept, key=lambda span: (span.page, span.y, span.x))
    section = next((item for item in mli.sections(lines, spans)
                    if item["no"] == 2), None)
    assert section is not None, f"{pdf.name}: no Article 2 section to read"
    rows, qa = mli.covered_agreements(section["spans"], book)
    if not qa.get("read"):
        rows, qa = read_number_first(section["spans"], book)
    return rows, qa, book


def _artefact(root: Path, slug: str, rows: list[dict]) -> Path:
    path = root / "corpora" / "mli" / "positions" / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"covered_agreements": rows}, sort_keys=True,
                               indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def _defect(ident: str):
    defect = DEFECTS.get(ident)
    assert defect is not None, f"{ident} is not in the defect catalogue"
    return defect


def test_china_footer_row_rule_restores_four_covered_agreements():
    pdf = _pdf("china")
    if not pdf.is_file():
        pytest.skip(f"{pdf.name} is not in sources/, so there is nothing to regress")

    rows, qa, book = _table(pdf, classifier_source=pdf.stem)
    assert qa.get("read")
    assert qa.get("rows_delimited_by", "").startswith("title blocks")
    assert [row["no"] for row in rows] == list(range(1, 100))
    assert qa["numbering"]["runs_from_one_without_a_gap"]
    assert not qa["numbers_with_no_row"]

    claimed = [(span, rule) for span, rule in book.kept
               if rule == "R-MLI-CHINA-COVERED-ROWS"]
    claimed_pages = {span.page for span, _rule in claimed}
    assert claimed_pages == {2, 5, 9, 11}
    assert len(claimed) == 24, "the targeted rule must admit only the four printed rows"
    assert all(span.y == pytest.approx(754.17, abs=0.6)
               for span, _rule in claimed)

    by_number = {row["no"]: row for row in rows}
    for number, (counterparty, signature, entry_into_force,
                 title_fragment) in CHINA_COVERED_ROW_PINS.items():
        row = by_number[number]
        assert row.get("other_jurisdiction") == counterparty
        assert row.get("signature") == signature
        assert row.get("entry_into_force") == entry_into_force
        assert title_fragment in row.get("title", "")
        assert row.get("instrument") == "Original"

    dropped_footer = [span for span, rule, _reason in book.dropped
                      if rule == "R-MLI-UNCLAIMED"
                      and span.page in {2, 5, 9, 11}
                      and span.y == pytest.approx(754.17, abs=0.6)]
    assert not dropped_footer, "a target China table span still reaches UNCLAIMED"
    unrelated_footer = [span for span, rule, _reason in book.dropped
                        if rule == "R-MLI-PAGE-NUMBER"
                        and span.page == 2 and span.y > 755.0]
    assert unrelated_footer, "the targeted rule accidentally kept the page number"
    assert all(rule != "R-MLI-CHINA-COVERED-ROWS"
               for _span, rule in book.kept if _span.page == 2 and _span.y > 755.0)


def test_d25_azerbaijan_footer_band_probe_fires_on_lost_rows(tmp_path):
    defect = _defect(D25)
    pdf = _pdf("azerbaijan")
    if not pdf.is_file():
        pytest.skip(f"{pdf.name} is not in sources/, so there is nothing to regress")

    rows, qa, _book = _table(pdf)
    assert qa.get("read") and len(rows) == defect.expected
    band_rows, _band_qa, _band_book = _table(pdf, band_y=AZERBAIJAN_BAND_Y)
    lost = {row["no"] for row in rows} - {row["no"] for row in band_rows}
    assert lost, "the simulated footer band removed no numbered table rows"
    degraded = [row for row in rows if row.get("no") not in lost]
    _artefact(tmp_path / "degraded", "azerbaijan", degraded)
    verdict = evaluate(defect, tmp_path / "degraded")
    assert verdict.evaluated and not verdict.ok, verdict.detail

    _artefact(tmp_path / "fixed", "azerbaijan", rows)
    fixed = evaluate(defect, tmp_path / "fixed")
    assert fixed.evaluated and fixed.ok, fixed.detail


def test_d26_kuwait_packed_date_probe_fires_on_packed_signature(tmp_path):
    defect = _defect(D26)
    pdf = _pdf("kuwait")
    if not pdf.is_file():
        pytest.skip(f"{pdf.name} is not in sources/, so there is nothing to regress")

    rows, qa, _book = _table(pdf)
    assert qa.get("read") and len(rows) == 45
    assert not PACKED_SIGNATURE_RE.search(json.dumps(rows, ensure_ascii=False)), (
        "the reader published a packed date/N-A pair in a signature field")
    target = next((row for row in rows
                   if (row.get("signature") or "").startswith("28/10/2008")), None)
    assert target is not None, "Kuwait's 28/10/2008 row is absent"
    degraded = [dict(row) for row in rows]
    for row in degraded:
        if row.get("no") == target["no"]:
            row["signature"] = f"{row['signature']} N/A"
            row.pop("entry_into_force", None)
    _artefact(tmp_path / "degraded", "kuwait", degraded)
    verdict = evaluate(defect, tmp_path / "degraded")
    assert verdict.evaluated and not verdict.ok, verdict.detail

    _artefact(tmp_path / "fixed", "kuwait", rows)
    fixed = evaluate(defect, tmp_path / "fixed")
    assert fixed.evaluated and fixed.ok, fixed.detail
