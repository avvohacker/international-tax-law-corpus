"""The extractor's contract: the five properties the span ledger must hold.

`harness/ledger.py` is written as a seam before its implementation, and these
are the five tests that define it (DESIGN.md section 3):

  * the reader keeps every span, including apparatus - filtering is the
    classifier's job, and it has to be visible as a rule;
  * every span read gets exactly one decision;
  * the projection is built over kept spans and nothing else;
  * rebuilding the span sequence from the projection reproduces the kept stream;
  * the audit report names the rule behind every drop.

The input is fixed to the 2017 Model because that is what the rules in
`rules/10-un-model.yaml` are written for. A contract exercised on whichever PDF
happened to sort first would be a contract nobody could read.
"""
from __future__ import annotations

import re
from functools import lru_cache

import pytest

from harness import corpus, ledger
from support import ROOT, UNBUILT

PREFERRED = "un-model-2017"


def _a_source():
    """The 2017 Model if it is here, otherwise the first PDF in sources/."""
    pdfs = corpus.source_pdfs(ROOT)
    for path in pdfs:
        if path.stem == PREFERRED:
            return path
    return pdfs[0] if pdfs else None


needs_source = pytest.mark.skipif(
    _a_source() is None,
    reason=("no input PDF in sources/ - the ledger contract cannot be exercised "
            "against nothing"))


def _call(fn, *args, **kwargs):
    """Call the seam. NotImplementedError is a specification, not a crash."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        pytest.fail(f"{exc}\n\n"
                    f"    This test is the specification of the extractor: it "
                    f"fails until the seam in harness/ledger.py is implemented "
                    f"(DESIGN.md section 3).")


@lru_cache(maxsize=1)
def _read():
    pdf = _a_source()
    return pdf, _call(ledger.SpanStream.read, pdf, pdf.stem)


@lru_cache(maxsize=1)
def _classified():
    _pdf, spans = _read()
    book = _call(ledger.Classifier.classify, spans, ledger.Ledger())
    return spans, book


@lru_cache(maxsize=1)
def _projected():
    pdf, _spans = _read()
    _spans2, book = _classified()
    return _call(ledger.Projection.build, book.kept, pdf.stem, book)


@needs_source
def test_span_stream_reads_every_page_without_filtering():
    pdf, spans = _read()
    assert spans, "the span stream is empty"
    assert min(s.page for s in spans) == 0
    assert all(span.text.strip() for span in spans), \
        "the reader kept a blank span: filtering belongs to the classifier"

    # The reader must also hand over the apparatus, or the classifier would have
    # nothing to recognise: this stream is where the running header lives.
    apparatus = [s for s in spans
                 if re.fullmatch(r"Articles? \d{1,2}[A-Z]?", s.text.strip())]
    assert apparatus, ("the raw stream contains no running header, so the reader "
                       "is filtering what the classifier should be deciding")
    assert all(s.page < 828 for s in spans)  # a page number, not a page count


@needs_source
def test_classifier_accounts_for_every_span():
    spans, book = _classified()
    assert book.audited, "the ledger claims to be incomplete"
    assert book.decisions == len(spans), (
        f"{len(spans)} spans read, {book.decisions} decided: an undecided span is "
        f"exactly where apparatus gets into the body")
    assert all(rule for _span, rule in book.kept), "a kept span has no rule id"
    assert all(rule and reason for _span, rule, reason in book.dropped), \
        "a dropped span has no rule id or no reason"


@needs_source
def test_projection_builds_nodes_from_kept_spans_only():
    _spans, book = _classified()
    nodes = _projected()
    assert list(nodes.walk()), "the projection produced no nodes"
    dropped = {id(span) for span, _rule, _reason in book.dropped}
    for node in nodes.walk():
        for span in node.spans:
            assert id(span) not in dropped, (
                f"{node.eId} was built over a span the ledger had dropped: "
                f"p{span.page} {span.text[:40]!r}")


@needs_source
def test_roundtrip_reproduces_the_classified_stream():
    _spans, book = _classified()
    ok, detail = _call(ledger.verify_roundtrip, _projected(), book, "un-model-2017")
    assert ok, detail


@needs_source
def test_audit_report_names_every_dropped_span():
    _spans, book = _classified()
    report = _call(ledger.audit_report, book)
    assert report and str(report).strip(), "the audit report is empty"
    rules = {rule for _span, rule, _reason in book.dropped}
    assert rules, "nothing was dropped at all, so this check proves nothing"
    for rule in sorted(rules)[:8]:
        assert rule in str(report), \
            f"rule {rule!r} dropped text and the report does not mention it"


def test_the_seam_is_where_the_documentation_says_it_is():
    for name in ("Span", "Ledger", "SpanStream", "Classifier", "Projection",
                 "verify_roundtrip", "audit_report"):
        assert hasattr(ledger, name), (
            f"harness/ledger.py no longer declares {name}; DESIGN.md section 3 "
            f"and these tests point at it")
    assert UNBUILT  # the message the rest of the suite fails with
