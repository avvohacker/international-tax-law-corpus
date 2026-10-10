"""Source-band audit for MLI covered-agreement block readings.

The module holds three permanent controls over the published corpus. The first
walks one layout's measured PDF columns, row by row (`audit_block_rows`). The
second compares every published position artefact with the reading the live
reader produces now (`audit_published_artifacts`), so a repair to the reader and
a stale artefact cannot stand together. The third reads each position's derived
markdown view back (`parse_position_view`) so a view that names a counterparty
or a date the artefact does not hold is a failure by row and by field, not a
diff nobody opens.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from harness import corpus, ledger
from harness import mli as mli_writer
from harness import views as view_writer

WORD_RE = re.compile(r"[\w]+", re.UNICODE)
# The day may be the French ordinal `1er` (cote-d-ivoire prints 1er-03-1985),
# which the reader keeps as printed and the audit must still count as a date.
DATE_RE = re.compile(
    r"\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\s*\d{2,4}")
DATE_YMD_RE = re.compile(r"\d{1,2}(?:er)?[-./]\d{1,2}[-./]\s*\d{4}")
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
INSTRUMENT_RE = re.compile(r"\b(original|amending|instrument|protocol|avenant)\b", re.I)
PDF_SLUGS = {"cote-d-ivoire": "cote-divoire"}
ARTIFACT_PDF_SLUGS = {"czechia": "czech-republic",
                      "china-people-s-republic-of": "china"}
# The inverse, so a registered source's stem maps back to the slug the corpus
# publishes the position under.
ARTIFACT_SLUGS = {pdf: slug for slug, pdf in ARTIFACT_PDF_SLUGS.items()}
ARTIFACT_SLUGS.update({pdf: slug for slug, pdf in PDF_SLUGS.items()})


def _words(value: str) -> list[str]:
    return [word.casefold() for word in WORD_RE.findall(value or "")]


def _dates(value: str, pattern: re.Pattern = DATE_RE) -> Counter:
    return Counter(re.sub(r"\s+", "", match.group(0))
                   for match in pattern.finditer(value or ""))


# The columns a position's markdown view renders, and the artefact field each
# one holds. `#` is the row's own number, which keys both sides of the
# comparison; the rest are compared by value.
VIEW_COLUMNS = (("#", "no"), ("Counterparty", "other_jurisdiction"),
                ("Instrument", "instrument"), ("Signature", "signature"),
                ("Entry into force", "entry_into_force"), ("Page", "page"))
VIEW_FIELDS = tuple(field for _header, field in VIEW_COLUMNS if field != "no")
# A cell's own pipe is escaped by the renderer, so it cannot split a cell here.
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
# The line a view carries for its own reading's attach tolerance: the numbers are
# read back out of it rather than re-rendered, so a view that moved a band edge
# is reported by the edge that moved.
ATTACH_LINE_PREFIX = "*Attach:"
ATTACH_TOL_RE = re.compile(r"within ([0-9.]+) pt")
ATTACH_BAND_RE = re.compile(r"leave it is \[([-0-9.]+), ([-0-9.]+)\]")
ATTACH_EMPTY_RE = re.compile(r"leave it is empty")


def parse_position_view(text: str) -> dict:
    """{row number: {field: text}} read back from a rendered position view.

    The view is a markdown table; reading it back is what makes the control a
    comparison rather than a copy of the renderer. A data line is one whose
    first cell is the printed number - the header and its separator are not
    numbers and are skipped - and a line whose cell count disagrees with the
    view's own columns is left out, so a malformed view is reported as rows the
    artefact does not hold rather than silently parsed as something else.
    """
    rows: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in CELL_SPLIT_RE.split(line[1:-1])]
        if len(cells) != len(VIEW_COLUMNS) or not cells[0].isdigit():
            continue
        values: dict = {}
        for (_header, field), cell in zip(VIEW_COLUMNS, cells):
            if field == "no":
                continue
            values[field] = cell.replace("\\|", "|").strip()
        rows[int(cells[0])] = values
    return rows


def _attach_line_problems(qa: dict, line: str | None, reader: str | None) -> list[str]:
    """An attach line against the qa fields it renders, read back, not re-rendered.

    The tolerance and the two band edges are read back out of the view, so a
    view that moved an edge is named by the edge that moved. An artefact that
    publishes no tolerance has no line, and an empty interval has to be said in
    words rather than drawn as `[]`.
    """
    if "row_attach_pt" not in qa:
        if line is None:
            return []
        return [f"attach: the view names an attach tolerance the artefact "
                f"does not publish: {line!r}"]
    tolerance = float(qa["row_attach_pt"])
    band = [float(value) for value in qa.get("row_attach_band_pt") or []]
    if line is None:
        return [f"attach: the artefact publishes row_attach_pt = {tolerance!r} "
                f"over {band!r} and the view carries no attach line"]
    problems = []
    if reader not in line:
        problems.append(f"attach reader: the artefact says {reader!r} decided "
                        f"these rows, which the view does not name: {line!r}")
    found = ATTACH_TOL_RE.search(line)
    if found is None or float(found.group(1)) != tolerance:
        problems.append(f"attach tolerance: the view names "
                        f"{found.group(1) if found else None!r}, the artefact "
                        f"holds {tolerance!r}")
    if band:
        found_band = ATTACH_BAND_RE.search(line)
        named = (None if found_band is None
                 else [float(found_band.group(1)), float(found_band.group(2))])
        if named != band:
            problems.append(f"attach band: the view names {named!r}, the "
                            f"artefact holds {band!r}")
    elif not ATTACH_EMPTY_RE.search(line):
        problems.append("attach band: the artefact publishes no interval on "
                        "this layout and the view does not say so")
    return problems


def _attach_line(record: dict, view_text: str) -> str | None:
    """The view's attach line, if it carries one."""
    return next((text.strip() for text in view_text.splitlines()
                 if text.strip().startswith(ATTACH_LINE_PREFIX)), None)


def attach_divergences(record: dict, view_text: str) -> list[str]:
    """Every way a position view's attach line disagrees with the artefact's own qa.

    Which reader decided the rows is settled the way the renderer settles it,
    from the artefact's own account of the reading.
    """
    qa = (record.get("qa") or {}).get("covered_agreements") or {}
    return _attach_line_problems(qa, _attach_line(record, view_text),
                                 view_writer.attach_reader(qa))


# The columns the signatories markdown view renders, and the artefact field
# each one holds. Kept beside the renderer's own map rather than imported from
# it, so the comparison stays a comparison: `#` is the row's own number, which
# keys both sides, and the rest are compared by value.
SIGNATORIES_VIEW_COLUMNS = (("#", "no"), ("Jurisdiction", "jurisdiction"),
                            ("Signature", "signature"), ("Deposit", "deposit"),
                            ("Entry into force", "entry_into_force"),
                            ("Page", "page"))
SIGNATORIES_VIEW_FIELDS = tuple(field for _header, field in
                                SIGNATORIES_VIEW_COLUMNS if field != "no")


def parse_signatories_view(text: str) -> dict:
    """{row number: {field: text}} read back from a rendered signatories view.

    The view is a markdown table; reading it back is what makes the control a
    comparison rather than a copy of the renderer. A data line is one whose
    first cell is the printed number - the header and its separator are not
    numbers and are skipped - and a line whose cell count disagrees with the
    view's own columns is left out, so a malformed view is reported as rows the
    artefact does not hold rather than silently parsed as something else.
    """
    rows: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in CELL_SPLIT_RE.split(line[1:-1])]
        if len(cells) != len(SIGNATORIES_VIEW_COLUMNS) or not cells[0].isdigit():
            continue
        values: dict = {}
        for (_header, field), cell in zip(SIGNATORIES_VIEW_COLUMNS, cells):
            if field == "no":
                continue
            values[field] = cell.replace("\\|", "|").strip()
        rows[int(cells[0])] = values
    return rows


def signatories_attach_divergences(record: dict, view_text: str) -> list[str]:
    """Every way a signatories view's attach line disagrees with the artefact.

    The signatories tolerance belongs to that table's own reader, which the
    artefact cannot name the way positions do, so the view is held to the name
    the renderer declares (`views.SIGNATORIES_READER`) and to the two fields
    the artefact publishes - `row_attach_pt` and `row_attach_band_pt`.
    """
    qa = record.get("qa") or {}
    return _attach_line_problems(qa, _attach_line(record, view_text),
                                 view_writer.SIGNATORIES_READER)


def signatories_view_divergences(record: dict, view_text: str) -> list[str]:
    """Every row, field or attach line on which a signatories view disagrees.

    One line per disagreement, naming the row and the field, because the whole
    point of reading the view back is to name what moved rather than that the
    file changed. `record` is the signatories artefact's own JSON.
    """
    named = parse_signatories_view(view_text)
    expected = {row["no"]: row for row in record.get("rows") or []}
    if set(named) != set(expected):
        return [f"rows {sorted(set(named) - set(expected))} named by the view are "
                f"not in the artefact and {sorted(set(expected) - set(named))} "
                f"are missing"]
    problems = []
    for number in sorted(expected):
        for field in SIGNATORIES_VIEW_FIELDS:
            in_view = named[number].get(field) or ""
            value = expected[number].get(field)
            # A measured `page` is an integer and `0` is a real page, so only a
            # missing field is empty - never a falsy value.
            in_artifact = "" if value is None else str(value)
            if in_view != in_artifact:
                problems.append(f"row {number} {field}: the view names "
                                f"{in_view!r}, the artefact holds {in_artifact!r}")
    problems.extend(signatories_attach_divergences(record, view_text))
    return problems


def position_view_divergences(record: dict, view_text: str) -> list[str]:
    """Every row, field or attach line on which a view disagrees with its artefact.

    One line per disagreement, naming the row and the field, because the whole
    point of reading the view back is to name what moved rather than that the
    file changed. A view the reader cannot parse back, or one that names a
    different set of rows, is a disagreement too: a view that cannot be read
    back is not a comparison. `record` is the position artefact's own JSON.
    """
    named = parse_position_view(view_text)
    expected = {row["no"]: row for row in record.get("covered_agreements") or []}
    if set(named) != set(expected):
        return [f"rows {sorted(set(named) - set(expected))} named by the view are "
                f"not in the artefact and {sorted(set(expected) - set(named))} "
                f"are missing"]
    problems = []
    for number in sorted(expected):
        for field in VIEW_FIELDS:
            in_view = named[number].get(field) or ""
            value = expected[number].get(field)
            # A measured `page` is an integer and `0` is a real page, so only a
            # missing field is empty - never a falsy value.
            in_artifact = "" if value is None else str(value)
            if in_view != in_artifact:
                problems.append(f"row {number} {field}: the view names "
                                f"{in_view!r}, the artefact holds {in_artifact!r}")
    problems.extend(attach_divergences(record, view_text))
    return problems


def _capture_reading(pdf: Path, slug: str, *, force_block: bool = False):
    """Read one PDF with its production classification and block reader."""
    original_sources = mli_writer.BLOCK_READER_SOURCES
    try:
        # The family build reads every position with the family source and
        # re-classifies only china with its PDF id (harness/mli.py
        # `_family_build`); the audit must read the same bytes the pipeline
        # publishes, never a source-specific variant.
        classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                             else "mli-positions-batch")
        book = ledger.Classifier.classify(
            ledger.SpanStream.read(pdf, classifier_source), ledger.Ledger())
        if force_block:
            mli_writer.BLOCK_READER_SOURCES = frozenset(
                {*original_sources, pdf.stem})
        # The family build never re-stamps span sources, and the token join
        # consults the source (spain's line-break hyphen); re-stamping here
        # would audit a reading the pipeline never publishes.
        spans = sorted((span for span, _rule in book.kept),
                       key=lambda span: (span.page, span.y, span.x))
        section = next((entry for entry in
                        mli_writer.sections(mli_writer._body_lines(book), spans)
                        if entry["no"] == 2), None)
        if section is None:
            raise AssertionError(f"{slug}: Article 2 section was not found")

        captured: dict = {}
        original_block = mli_writer._read_block_covered
        original_china = mli_writer._read_china_covered

        def capture_block(*args, **kwargs):
            captured["args"] = args
            original_words = mli_writer._words
            original_instruments = mli_writer._instruments
            word_calls = []

            def capture_words(parts, current_book):
                parts = list(parts)
                value = original_words(parts, current_book)
                word_calls.append((parts, value))
                return value

            mli_writer._words = capture_words
            mli_writer._instruments = lambda _cells, _book: []
            try:
                rows, qa = original_block(*args, **kwargs)
            finally:
                mli_writer._words = original_words
                mli_writer._instruments = original_instruments
            names = [name for name, _x in qa.get("columns", {}).items()
                     if name != "no"]
            fields = {}
            index = 0
            for row in rows:
                fields[row["no"]] = {}
                for name in names:
                    parts, value = word_calls[index]
                    index += 1
                    fields[row["no"]][name] = (parts, value)
            captured["row_fields"] = fields
            return rows, qa

        def capture_china(*args, **kwargs):
            captured["args"] = args
            return original_china(*args, **kwargs)

        mli_writer._read_block_covered = capture_block
        mli_writer._read_china_covered = capture_china
        try:
            rows, qa = mli_writer.covered_agreements(
                section["spans"], book, reader_source=pdf.stem)
        finally:
            mli_writer._read_block_covered = original_block
            mli_writer._read_china_covered = original_china
        args = captured.get("args")
        if args is None:
            raise AssertionError(f"{slug}: block reader was not selected")
        return rows, qa, args[1], args[2], captured.get("row_fields", {})

    finally:
        mli_writer.BLOCK_READER_SOURCES = original_sources


def legacy_reading(root: Path, slug: str):
    """Read one PDF with the legacy reader, whatever dispatch would pick.

    The layout is temporarily taken out of the block-reader set, so a promoted
    slug is read the way it was read before its promotion and an exception the
    way it is still read. This is the reader a `LEGACY_DEFECT_INVENTORY` record
    is checked against.
    """
    pdf_slug = PDF_SLUGS.get(slug, ARTIFACT_PDF_SLUGS.get(slug, slug))
    pdf = root / "sources" / "mli-positions" / f"mli-position-{pdf_slug}.pdf"
    if not pdf.is_file():
        raise AssertionError(f"{slug}: source PDF not found: {pdf}")
    original_sources = mli_writer.BLOCK_READER_SOURCES
    try:
        classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                             else "mli-positions-batch")
        book = ledger.Classifier.classify(
            ledger.SpanStream.read(pdf, classifier_source), ledger.Ledger())
        mli_writer.BLOCK_READER_SOURCES = frozenset(
            source for source in original_sources if source != pdf.stem)
        spans = sorted((span for span, _rule in book.kept),
                       key=lambda span: (span.page, span.y, span.x))
        section = next((entry for entry in
                        mli_writer.sections(mli_writer._body_lines(book), spans)
                        if entry["no"] == 2), None)
        if section is None:
            raise AssertionError(f"{slug}: Article 2 section was not found")
        rows, _qa = mli_writer.covered_agreements(
            section["spans"], book, reader_source=pdf.stem)
        return rows
    finally:
        mli_writer.BLOCK_READER_SOURCES = original_sources


def block_reading(root: Path, slug: str):
    """Read one PDF with the block reader, whatever dispatch would pick.

    The mirror of `legacy_reading`: the layout is forced onto the block reader,
    so a record about what the block reader gets right is checked against the
    reading it would produce and never against the legacy fallback.
    """
    pdf_slug = PDF_SLUGS.get(slug, ARTIFACT_PDF_SLUGS.get(slug, slug))
    pdf = root / "sources" / "mli-positions" / f"mli-position-{pdf_slug}.pdf"
    if not pdf.is_file():
        raise AssertionError(f"{slug}: source PDF not found: {pdf}")
    original_sources = mli_writer.BLOCK_READER_SOURCES
    try:
        classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                             else "mli-positions-batch")
        book = ledger.Classifier.classify(
            ledger.SpanStream.read(pdf, classifier_source), ledger.Ledger())
        mli_writer.BLOCK_READER_SOURCES = frozenset(
            {*original_sources, pdf.stem})
        spans = sorted((span for span, _rule in book.kept),
                       key=lambda span: (span.page, span.y, span.x))
        section = next((entry for entry in
                        mli_writer.sections(mli_writer._body_lines(book), spans)
                        if entry["no"] == 2), None)
        if section is None:
            raise AssertionError(f"{slug}: Article 2 section was not found")
        rows, _qa = mli_writer.covered_agreements(
            section["spans"], book, reader_source=pdf.stem)
        return rows
    finally:
        mli_writer.BLOCK_READER_SOURCES = original_sources


def heading_habit(root: Path, slug: str) -> dict:
    """The verdict on where a layout prints its numbers, and the depth behind it.

    The reader decides whether the run of lines above a number is that number's
    own heading or the row above's tail from the anchored groups the grouping
    produced (`mli._numbers_inside_their_heading`), and the decision changes what
    a row's block means. This reads the layout the way the reader does - through
    the classifier the reading itself calls, so the verdict reported is the one
    the reading really made and not a re-derivation - and measures the opening
    each anchored group gives its number on the same groups:

    * `lead` - the line the vote counts, half the layout's own line spacing as
      `mli._heading_lead` measures it from these same groups, so a table with a
      different leading needs no hand-measured constant;
    * `groups` - anchored groups the grouping produced;
    * `opens` - groups whose block opens above their number at all;
    * `deep` - groups whose block opens more than that line above it, which is
      what a heading line above the number looks like rather than the rounding
      of one baseline.
    """
    pdf_slug = PDF_SLUGS.get(slug, ARTIFACT_PDF_SLUGS.get(slug, slug))
    pdf = root / "sources" / "mli-positions" / f"mli-position-{pdf_slug}.pdf"
    if not pdf.is_file():
        raise AssertionError(f"{slug}: source PDF not found: {pdf}")
    calls: list = []
    original = mli_writer._numbers_inside_their_heading

    def capture(blocks, anchors):
        verdict = original(blocks, anchors)
        lead = mli_writer._heading_lead(blocks)
        anchor_keys = {(holder.page, round(holder.y, 1)) for holder in anchors}
        depths = []
        for group in blocks:
            holder = next((key for key in group if key in anchor_keys), None)
            if holder is not None:
                depths.append(holder[1] - group[0][1])
        calls.append({
            "inside_heading": bool(verdict),
            "lead": lead,
            "groups": len(depths),
            "opens": sum(1 for depth in depths if depth > 0.0),
            "deep": sum(1 for depth in depths
                        if lead > 0.0 and depth > lead),
        })
        return verdict

    mli_writer._numbers_inside_their_heading = capture
    try:
        block_reading(root, slug)
    finally:
        mli_writer._numbers_inside_their_heading = original
    if len(calls) != 1:
        raise AssertionError(
            f"{slug}: the habit was measured {len(calls)} times, expected once")
    return calls[0]


def block_tolerances(root: Path, slug: str) -> dict:
    """The block reader's own tolerances for one layout, as it measured them.

    The block reader takes both of its tolerances from the layout's own page
    pitch (`mli._page_pitch`, the step the page repeats between the lines of one
    column): a quarter of a line for the shortfall that makes a title line
    ragged (`mli._block_ragged_slack`) and an eighth of a line for how near a
    mirror must land to count as a printed line (`mli._mirror_tol`). Neither is a
    shared constant any more, so this reads them off the live reading - from the
    exact `lines` and `counterpart_x` the grouping was handed - rather than
    re-deriving them, so the band is checked against the value the reader really
    used.
    """
    captured: list = []
    original_full = mli_writer._block_full_edge

    def capture(lines, counterpart_x):
        value = original_full(lines, counterpart_x)
        captured.append((lines, counterpart_x))
        return value

    mli_writer._block_full_edge = capture
    try:
        block_reading(root, slug)
    finally:
        mli_writer._block_full_edge = original_full
    if len(captured) != 1:
        raise AssertionError(
            f"{slug}: the page pitch was measured {len(captured)} times, "
            "expected once")
    lines, counterpart_x = captured[0]
    return {"pitch": mli_writer._page_pitch(lines, counterpart_x),
            "slack": mli_writer._block_ragged_slack(lines, counterpart_x),
            "mirror": mli_writer._mirror_tol(lines, counterpart_x)}


def block_rows_at(root: Path, name: str, values) -> dict:
    """How every promoted layout reads with one tolerance set to each value.

    One classification per layout and one `covered_agreements` call per value,
    so asking a tolerance about a whole range costs one reading of the sources
    rather than one per value. The rows are serialised, because the claim being
    checked is that they do not move and a comparison of live objects would not
    say that. `name` is a module attribute of `harness.mli`; it is restored.

    A layout whose read raises at some value is recorded with the exception
    instead of moving it out of the walk. The caller's claim is that the value is
    inert, so a value at which the reader cannot even finish is the strongest
    counterexample there is, and it must come back as a reading that differs -
    naming the layout and the constant - rather than as an error from a probe.
    """
    original = getattr(mli_writer, name)
    try:
        prepared = _prepared_layouts(root)
        readings: dict = {}
        for value in values:
            setattr(mli_writer, name, value)
            readings[value] = {}
            for slug, book, section, pdf_stem in prepared:
                try:
                    rows, _qa = mli_writer.covered_agreements(
                        section["spans"], book, reader_source=pdf_stem)
                    readings[value][slug] = json.dumps(rows, sort_keys=True,
                                                       default=str)
                except Exception as error:  # noqa: BLE001 - the value decided
                    readings[value][slug] = (
                        f"raised {type(error).__name__}: {error}")
        return readings
    finally:
        setattr(mli_writer, name, original)


def _prepared_layouts(root: Path) -> list:
    """Every promoted layout, classified once, with its Article 2 section.

    Shared by the walk that asks a tolerance about every layout in turn
    (`block_rows_at`) and the one that measures the interval a layout's own
    printed spans leave for its window (`covered_attach_band`), so both read the
    same layouts, through the same classifier and the same section, and a band
    one of them reports cannot be about a reading the other never made.
    """
    original_sources = mli_writer.BLOCK_READER_SOURCES
    published = published_slugs(root)
    prepared = []
    try:
        for source in sorted(mli_writer.BLOCK_READER_SOURCES):
            pdf_slug = source.removeprefix("mli-position-")
            slug = ARTIFACT_SLUGS.get(pdf_slug, pdf_slug)
            slug_pdf = PDF_SLUGS.get(slug, ARTIFACT_PDF_SLUGS.get(slug, slug))
            pdf = root / "sources" / "mli-positions" / f"mli-position-{slug_pdf}.pdf"
            if not pdf.is_file():
                raise AssertionError(f"{slug}: source PDF not found: {pdf}")
            classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                                 else "mli-positions-batch")
            book = ledger.Classifier.classify(
                ledger.SpanStream.read(pdf, classifier_source),
                ledger.Ledger())
            mli_writer.BLOCK_READER_SOURCES = frozenset(
                {*original_sources, pdf.stem})
            spans = sorted((span for span, _rule in book.kept),
                           key=lambda span: (span.page, span.y, span.x))
            section = next((entry for entry in
                            mli_writer.sections(mli_writer._body_lines(book),
                                                spans)
                            if entry["no"] == 2), None)
            if section is None:
                raise AssertionError(f"{slug}: Article 2 section was not found")
            # Keyed by the slug the artefact carries, read off the family's own
            # report: the band the tests compare against is the one inside that
            # artefact, and a companion's published slug is not its file name.
            prepared.append((published.get(source, slug), book, section, pdf.stem))
        return prepared
    finally:
        mli_writer.BLOCK_READER_SOURCES = original_sources


def covered_attach_band(root: Path) -> dict:
    """The interval the promoted layouts leave for each attach tolerance.

    The covered-agreements readers attach in two ways, and the two are declared
    apart: the number-first reader places a span with the numbers around it
    within `POS_ATTACH_PT`, and the block reader absorbs a run of lines printed
    above a number as that row's prefix within `POS_ATTACH_REACH_PT`. The pages
    print both sides of each decision, so each tolerance's interval is measured
    the way the signatories window's is - per layout, intersected over the
    layouts that ask it, because each tolerance is shared by the layouts its own
    reader reads.

    This measures the *block* reader's tolerance, off the reader's own answers
    (`mli._absorbs_prefix`, `mli._pos_attach_reach_band`), so the band is the
    placement's measurement and not a second implementation of it. The window's
    entry is reported as `None` on purpose rather than left out: every promoted
    layout's title column is justified, so `covered_agreements` reads them with
    title cells or with the displaced-x reader and never asks `_row_of` at all,
    and a band here would be about a placement that never ran. The layouts that
    do decide with the window are the ones the block reader does not read, and
    `number_first_attach_band` measures the interval they leave it.

    Each edge is reported with the layout that sets it - and with how many
    layouts were measured - because on an intersection over thirty-one pages the
    useful fact is which page is tight, and because a band over no layout at all
    would otherwise look like a band.
    """
    original_row_of = mli_writer._row_of
    original_reach = mli_writer._absorbs_prefix
    placements: list = []
    asked: list = []

    def capture_row_of(span, anchors):
        placements.append((span, anchors))
        return original_row_of(span, anchors)

    def capture_reach(pending_last, next_anchor):
        took = original_reach(pending_last, next_anchor)
        if pending_last[0] == next_anchor.page:
            asked.append((next_anchor.y - pending_last[1], bool(took)))
        return took

    placed: list = []
    measured: list = []
    for slug, book, section, pdf_stem in _prepared_layouts(root):
        placements.clear()
        asked.clear()
        mli_writer._row_of = capture_row_of
        mli_writer._absorbs_prefix = capture_reach
        try:
            mli_writer.covered_agreements(section["spans"], book,
                                          reader_source=pdf_stem)
        finally:
            mli_writer._row_of = original_row_of
            mli_writer._absorbs_prefix = original_reach
        band = mli_writer._pos_attach_band(list(placements))
        if band:
            placed.append((slug, band))
        band = mli_writer._pos_attach_reach_band(list(asked))
        if band:
            measured.append((slug, band))

    def intersect(entries: list):
        if not entries:
            return None
        low_layout, low = max(entries, key=lambda entry: entry[1][0])
        high_layout, high = min(entries, key=lambda entry: entry[1][1])
        return {"low": low[0], "high": high[1], "layouts": len(entries),
                "low_layout": low_layout, "high_layout": high_layout,
                "per_layout": dict(entries)}

    return {"POS_ATTACH_REACH_PT": intersect(measured),
            "POS_ATTACH_PT": intersect(placed)}


def number_first_attach_band(root: Path) -> dict:
    """The interval the number-first layouts leave for the attach window.

    `POS_ATTACH_PT` is the tolerance of the reader that places a span among the
    numbers around it, and the layouts that read with it are the ones the block
    reader does not read: `_prepared_layouts` forces every source through the
    block reader - which is what makes its band about the block reading - so the
    window's band has to be measured by walking the other half of the corpus.
    Every position source the register leaves out of `BLOCK_READER_SOURCES` is
    classified once and read through `covered_agreements` with its own source id,
    which is the dispatch the corpus itself makes, with `mli._row_of` captured.

    The sources are enumerated from the directory and not from the published
    slugs, because the slug an artefact is published under is read out of the
    document: `turkey.pdf` is published as Turkiye and `russia.pdf` as the
    provisional list, and only the directory knows which file an artefact came
    from.

    A layout that never asks the placement contributes nothing, and a layout
    whose placement leaves one side empty reports no band; the intersection is
    over the layouts that do. Both edges are distances the pages print, and the
    test holds the declared window inside the band, half-open, and asks the two
    tight layouts to move their rows at the edges - so the band is established by
    the pages and by the reading that sits in it, not by the placement's own
    bookkeeping alone.

    Layouts are keyed by the slug the corpus publishes them under, read off the
    family's own report, because that is the name the artefact carries and the
    band the test compares against is the one inside it.
    """
    published = published_slugs(root)
    original_row_of = mli_writer._row_of
    placements: list = []

    def capture_row_of(span, anchors):
        placements.append((span, anchors))
        return original_row_of(span, anchors)

    measured: list = []
    for pdf in sorted((root / "sources" / "mli-positions").glob("*.pdf")):
        if pdf.stem in mli_writer.BLOCK_READER_SOURCES:
            continue
        slug = published.get(pdf.stem,
                             pdf.stem.removeprefix("mli-position-"))
        book, section = _prepared_number_first(pdf)
        if section is None:
            continue
        placements.clear()
        mli_writer._row_of = capture_row_of
        try:
            mli_writer.covered_agreements(section["spans"], book,
                                          reader_source=pdf.stem)
        finally:
            mli_writer._row_of = original_row_of
        band = mli_writer._pos_attach_band(list(placements))
        if band:
            measured.append((slug, band))
    if not measured:
        return None
    low_layout, low = max(measured, key=lambda entry: entry[1][0])
    high_layout, high = min(measured, key=lambda entry: entry[1][1])
    return {"low": low[0], "high": high[1], "layouts": len(measured),
            "low_layout": low_layout, "high_layout": high_layout,
            "per_layout": dict(measured)}


def published_slugs(root: Path) -> dict:
    """Each position source's stem, mapped to the slug its artefact carries.

    The slug a document is published under is read out of the document, not out
    of the publisher's filename (`turkey.pdf` names Turkiye, `russia.pdf` the
    provisional list), so the family's own report - written by the same build
    that wrote the artefacts - is the one place the two names are tied together.
    A document the family could not read has no artefact and no entry.
    """
    report = root / "corpora" / "mli" / "positions" / "batch-report.json"
    if not report.is_file():
        return {}
    data = json.loads(report.read_text(encoding="utf-8"))
    return {Path(entry["file"]).stem: str(entry["slug"])
            for entry in data.get("documents") or []
            if entry.get("slug") and entry.get("file")}


# A declared tolerance, by its name: a module-level number of the harness whose
# name says what it is - a distance in points, or a tolerance.
TOLERANCE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(?:_PT|_TOL)$")


def declared_tolerances(root: Path) -> dict:
    """Every declared tolerance of the harness, read off its own source.

    Declared tolerances are the module-level numbers whose names say so, and they
    are read from the modules rather than from a list because the list is the
    thing that goes stale: a tolerance added to a reader is one this audit has to
    see. Returns `{name: {"file", "line", "value"}}`.
    """
    out: dict = {}
    for path in sorted((root / "harness").glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, float)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and TOLERANCE_NAME.match(target.id):
                    out[target.id] = {"file": path.name, "line": node.lineno,
                                      "value": node.value.value}
    return out


def tolerance_audit(root: Path) -> dict:
    """The declared tolerances, and every place one is written instead of named.

    One tolerance serving two roles is what made `POS_ATTACH_PT`'s band have to be
    intersected with the reach's: the reach was declared as the window plus a
    slack, so the two numbers were one value, the layouts that read the window
    were also the layouts that read the reach, and no band could be about either
    of them alone. The audit looks for the same shape in the rest of the readers,
    in the three ways a second role hides in a first one:

      * `derived`: a module-level constant whose value is *computed from* a
        declared tolerance - the `POS_ATTACH_PT + SLACK` shape. The two numbers
        are then one value, and moving either moves both readers.
      * `copies`: a class field or a parameter default that repeats the number of
        a declared tolerance instead of naming it (`marker_column_tol: float =
        6.0` beside `MARKER_COLUMN_TOL = 6.0`). The copy is a second declaration
        in all but name: a repair that moves the named one leaves the copy
        reading what the named one used to. Reported, because a default may also
        hold the same number for a genuinely different role - `_x_clusters`
        clusters x starts within 1.5pt, which is not the row-pitch multiple - and
        which of the two it is, is a reading the names have to carry.
      * `literals`: a call that passes a declared tolerance's number where the
        call takes a tolerance (`_x_clusters(..., tol=4.0)`). That site keeps its
        own value: the declared tolerance can move and the call will not, so the
        reader decides with a number no pin holds and no band measures.

    `derived` and `literals` are asserted empty by the invariants; `copies` is
    reported for the reader of this audit, because it is the one shape that can
    be a legitimate coincidence.
    """
    tolerances = declared_tolerances(root)
    values = {entry["value"] for entry in tolerances.values()}
    derived: list = []
    copies: list = []
    literals: list = []
    for path in sorted((root / "harness").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            # Only a *module-level* constant can hide a role: a local that reads
            # a tolerance in an expression is a use of it, which is what the
            # tolerance is for. What is reported is a constant whose own value
            # is computed from a declared one, so that two names share a value.
            if (isinstance(node, ast.Assign)
                    and not isinstance(node.value, ast.Constant)):
                names = {child.id for child in ast.walk(node.value)
                         if isinstance(child, ast.Name)}
                shared = sorted(names & set(tolerances))
                if shared:
                    derived.append({"file": path.name, "line": node.lineno,
                                    "name": ", ".join(
                                        getattr(target, "id", "?")
                                        for target in node.targets),
                                    "from": shared})
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Assign, ast.AnnAssign))
                    and node.value is not None
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, float)
                    and node.value.value in values):
                target = (node.targets[0] if isinstance(node, ast.Assign)
                          else node.target)
                name = getattr(target, "id", None)
                if name is not None and not TOLERANCE_NAME.match(name):
                    copies.append({"file": path.name, "line": node.lineno,
                                   "name": name, "value": node.value.value})
            if isinstance(node, ast.arguments) and node.defaults:
                for argument, default in zip(node.args[-len(node.defaults):],
                                             node.defaults):
                    if (not TOLERANCE_NAME.match(argument.arg)
                            and isinstance(default, ast.Constant)
                            and isinstance(default.value, float)
                            and default.value in values):
                        copies.append({"file": path.name, "line": default.lineno,
                                       "name": f"{argument.arg}=",
                                       "value": default.value})
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (keyword.arg == "tol"
                            and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, float)
                            and keyword.value.value in values):
                        literals.append({"file": path.name, "line": node.lineno,
                                         "value": keyword.value.value})
    return {"tolerances": tolerances, "derived": derived, "copies": copies,
            "literals": literals}


def _prepared_number_first(pdf: Path) -> tuple:
    """One number-first source, classified once, with its Article 2 section.

    The classifier is handed the source id the corpus reads it under - the
    position batch, or its own id for China - because the classification is what
    the reading is downstream of, and a source read as the wrong batch is a
    different document. Unlike `_prepared_layouts` this does not put the source
    into `BLOCK_READER_SOURCES`: staying out of it is what makes the reading the
    number-first one.
    """
    classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                         else "mli-positions-batch")
    book = ledger.Classifier.classify(
        ledger.SpanStream.read(pdf, classifier_source), ledger.Ledger())
    spans = sorted((span for span, _rule in book.kept),
                   key=lambda span: (span.page, span.y, span.x))
    section = next((entry for entry in
                    mli_writer.sections(mli_writer._body_lines(book), spans)
                    if entry["no"] == 2), None)
    return book, section


def number_first_rows_at(root: Path, name: str, slugs: list,
                         values: list) -> dict:
    """How named number-first layouts read with one tolerance moved.

    The control the window's band is held against: the layouts that set its two
    edges are re-read at the edges themselves, through `covered_agreements` -
    the reader's rows, and not the placement bookkeeping the band was measured
    from - so a window that sits outside the interval either changes those rows
    or the band is wrong about where they change. One classification per layout
    and one reading per value, so the cost is a few readings and not a walk.
    """
    sources = {slug: stem for stem, slug in published_slugs(root).items()}
    prepared = {}
    for slug in slugs:
        stem = sources.get(slug, slug)
        prepared[slug] = (stem, *_prepared_number_first(
            root / "sources" / "mli-positions" / f"{stem}.pdf"))
    original = getattr(mli_writer, name)
    readings: dict = {}
    try:
        for value in values:
            setattr(mli_writer, name, value)
            readings[value] = {}
            for slug in slugs:
                stem, book, section = prepared[slug]
                if section is None:
                    readings[value][slug] = "no Article 2 section"
                    continue
                try:
                    rows, _qa = mli_writer.covered_agreements(
                        section["spans"], book, reader_source=stem)
                    readings[value][slug] = json.dumps(rows, sort_keys=True,
                                                       default=str)
                except Exception as error:  # noqa: BLE001 - the value decided
                    readings[value][slug] = (
                        f"raised {type(error).__name__}: {error}")
        return readings
    finally:
        setattr(mli_writer, name, original)


def signatories_geometry(root: Path) -> dict:
    """The signatories table's own geometry, and what the reader derives from it.

    The reader's row-pitch tolerance is not a declared number any more: it is
    measured from the table (`mli._line_step` for the step the table sets its
    lines at, `mli._table_pitch` for the step it repeats its rows at, and
    `mli._row_pitch_tol` for the multiple of one by the other). So a test cannot
    compare it against a constant and a probe cannot move it by writing one.
    Both read it here, through the same functions the reader calls and on the
    same source, so what is pinned and what is measured cannot drift apart.

    The attach window is the other half of that geometry. Its *value* is declared
    and published, so it cannot be re-derived without republishing the corpus,
    but the interval the page's own printed lines leave for it can be measured:
    `mli._row_attach_band` reads off the placement the furthest a line captured
    up stands above its number and the nearest a line left with the number above
    stands above the next one, and reports both. That is what
    `test_p05_the_attach_window_sits_inside_the_band_the_page_prints` pins and
    holds the declared window inside - so the constant is a whole point inside an
    interval the page does not print in, and not a number nothing measures.
    """
    pdf = root / "sources" / "mli-signatories-and-parties.pdf"
    if not pdf.is_file():
        raise AssertionError(f"the signatories source is missing: {pdf}")
    book = ledger.Classifier.classify(
        ledger.SpanStream.read(pdf, pdf.stem), ledger.Ledger())
    lines = mli_writer._body_lines(book)
    pages = mli_writer._pages(lines)
    pitches = [pitch for _page, _page_lines, _anchors, pitch in pages]
    step = mli_writer._line_step(lines)
    pitch = mli_writer._table_pitch(pitches)
    tol = mli_writer._row_pitch_tol(lines, pitches)
    return {
        "line_step": step,
        "table_pitch": pitch,
        "row_pitch_tol": tol,
        "row_pitch_tol_reported": mli_writer._row_pitch_report(tol),
        "row_attach_band": mli_writer._row_attach_band(pages, tol),
    }


def derived_tolerances(root: Path) -> dict:
    """The tolerances the readers derive, as the number and as the report.

    A derived tolerance has no constant to compare it against - the number that
    has to lie inside the band a page allows is the one the reader computes now -
    and it is two numbers rather than one. The *decision* is the threshold the
    reader compares distances against, in row pitches: it is what leaving the band
    would change a reading. The *reported* is that threshold as the artefact
    records it, rounded to the tenth the printed geometry is read at, and it is
    what the corpus has to agree with. A repair that moves the first without the
    second reads differently, one that moves the second alone publishes a reader
    that no longer exists, and the two are checked by different invariants.
    """
    geometry = signatories_geometry(root)
    return {"ROW_PITCH_TOL": {"decision": geometry["row_pitch_tol"],
                              "reported": geometry["row_pitch_tol_reported"]}}


def signatories_rows_at(root: Path, name: str, values) -> dict:
    """How the signatories table reads with one tolerance set to each value.

    The same shape as `block_rows_at` for the one source that reader serves, so
    a tolerance of that reader can be asked about its range the same way.
    """
    pdf = root / "sources" / "mli-signatories-and-parties.pdf"
    if not pdf.is_file():
        raise AssertionError(f"the signatories source is missing: {pdf}")
    book = ledger.Classifier.classify(
        ledger.SpanStream.read(pdf, pdf.stem), ledger.Ledger())
    original = getattr(mli_writer, name)
    try:
        readings: dict = {}
        for value in values:
            setattr(mli_writer, name, value)
            try:
                rows = mli_writer.signatories(book, pdf.stem, "")["rows"]
                readings[value] = json.dumps(rows, sort_keys=True, default=str)
            except Exception as error:  # noqa: BLE001 - the value decided
                readings[value] = f"raised {type(error).__name__}: {error}"
        return readings
    finally:
        setattr(mli_writer, name, original)


def _bands(qa: dict, table: list) -> dict[str, str]:
    columns = qa.get("columns") or {}
    required = ("title", "other_jurisdiction", "signature", "entry_into_force")
    if any(name not in columns for name in required):
        return {}

    def text(left: float, right: Optional[float] = None) -> str:
        return " ".join(span.text for span in sorted(
            table, key=lambda item: (item.page, item.y, item.x))
            if span.x >= left - 1.0 and (right is None or span.x < right - 1.0))

    instrument = columns.get("instrument")
    return {
        "title": text(columns["title"], columns["other_jurisdiction"]),
        "other_jurisdiction": text(columns["other_jurisdiction"],
                                    instrument if instrument is not None
                                    else columns["signature"]),
        "instrument": text(instrument, columns["signature"]) if instrument else "",
    }


def _exception_findings(slug: str, rows: list[dict]) -> list[dict]:
    """Positive controls: each known defect must remain visible on its row(s)."""
    findings = []

    def record(label: str, predicate) -> None:
        numbers = [row["no"] for row in rows if predicate(row)]
        if numbers:
            findings.append({"defect": label, "rows": numbers})

    record("Arabic bilingual/decree text in title",
           lambda row: bool(ARABIC_RE.search(str(row.get("title") or ""))))
    record("instrument label in counterparty",
           lambda row: bool(INSTRUMENT_RE.search(
               str(row.get("other_jurisdiction") or ""))))
    record("empty counterparty", lambda row: not row.get("other_jurisdiction"))
    record("missing signature", lambda row: not row.get("signature"))
    record("missing entry into force", lambda row: not row.get("entry_into_force"))
    # A word in a date cell is no longer recorded as a defect. The publisher
    # prints `N/A` in the signature or force column wherever it has no date -
    # new-zealand's and slovenia's published artefacts carry it too - and after
    # the merged date run began splitting at the measured date-column boundary
    # (`mli._dated_cells`) such a word lands in the cell it was printed in. What
    # would be a defect is a word smeared in from the neighbouring date column,
    # and that is measured directly and per span by this module's band audit
    # (`audit_block_rows`), which no predicate over the emitted rows can do.
    return findings


def audit_block_rows(root: Path, slug: str, *, force_block: bool = False,
                     row_pins: Optional[dict] = None,
                     date_pins: Optional[dict] = None,
                     legacy_pins: Optional[tuple] = None) -> dict:
    """Verify row anchors, measured source bands, reviewed pins, and exceptions.

    Every emitted field must be supported by its measured PDF column: the text
    and the date tokens of each cell are checked against the spans the reader
    assigned to that row and column. Narrow printed columns wrap a date over two
    lines, so an assigned cell is joined before searching; fragments that belong
    to a neighboring cell are never merged. Exact row pins remain the
    independent test for row attribution. Every reviewed defect in
    DEFECT_INVENTORY is re-checked against its emitted row, so a repair must
    update the record instead of silently dropping the defect.
    """
    pdf_slug = PDF_SLUGS.get(slug, ARTIFACT_PDF_SLUGS.get(slug, slug))
    pdf = root / "sources" / "mli-positions" / f"mli-position-{pdf_slug}.pdf"
    if not pdf.is_file():
        raise AssertionError(f"{slug}: source PDF not found: {pdf}")
    rows, qa, table, anchors, row_fields = _capture_reading(
        pdf, slug, force_block=force_block)
    reader = str(qa.get("rows_delimited_by", ""))
    issues = []
    if not reader.startswith("title blocks"):
        issues.append(f"block dispatch fell back: {reader}")
    printed = [int(mli_writer.NUMBER_RE.match(a.text.strip()).group(1))
               for a in anchors]
    emitted = [row["no"] for row in rows]
    if len(emitted) != len(set(emitted)):
        issues.append("duplicate emitted row numbers")
    if Counter(printed) != Counter(emitted):
        issues.append(f"printed anchors differ from output rows: "
                      f"printed={sorted(printed)}, output={sorted(emitted)}")

    bands = _bands(qa, table)
    row_issues = []
    if not bands:
        row_issues.append({"row": 0, "field": "columns",
                           "detail": "reader did not expose required measured bands"})
        return {"slug": slug, "reader": reader, "rows": len(rows),
                "anchors": len(anchors), "issues": issues,
                "row_issues": row_issues, "findings": _exception_findings(slug, rows)}

    columns = qa.get("columns") or {}
    title_x = columns.get("title")
    number_x = columns.get("no")
    counterpart_x = columns.get("other_jurisdiction")
    instrument_x = columns.get("instrument")
    signature_x = columns.get("signature")
    force_x = columns.get("entry_into_force")
    # A title line that carries its printed number starts in the number column
    # (mexico 87.0 = its number column, latvia 81.0, norway 81.1); the number
    # is stripped before the title cell is measured, so the title band opens
    # at the leftmost of the two. A table can also print the two date fields
    # as one run (chile, viet-nam): then both fields share one measured x and
    # the force column cannot close the signature band.
    title_left = min(title_x, number_x) if number_x is not None else title_x
    one_date_column = (signature_x is not None and force_x is not None
                       and abs(force_x - signature_x) <= 1.0)
    bands = {
        "title": (title_left, counterpart_x, None),
        "other_jurisdiction": (counterpart_x,
                               instrument_x if instrument_x is not None
                               else signature_x, None),
        "instrument": ((instrument_x, signature_x, None)
                       if instrument_x is not None else None),
        "signature": (signature_x,
                      None if one_date_column else force_x, None),
        "entry_into_force": (signature_x if signature_x is not None else force_x,
                             None,
                             None if one_date_column else force_x),
    }
    for row in rows:
        number = row["no"]
        for field, band in bands.items():
            if (band is None or band[0] is None
                    or field not in row_fields.get(number, {})):
                continue
            left, right, reach = band
            spans, reconstructed = row_fields[number][field]
            output = str(row.get(field) or "")
            if reconstructed != output:
                row_issues.append({"row": number, "field": field,
                                   "detail": "output differs from its assigned PDF spans"})
            for span in spans:
                # Permit coordinate rounding at the measured edge, both ways:
                # a span within one tolerance of a boundary is still that
                # column's text (cote-d-ivoire's date columns measure 2.8pt
                # apart). Entry into force also arrives packed into the
                # signature column's span (georgia, indonesia, lithuania,
                # nigeria): its printed text must reach the measured force
                # column instead of starting in it. The span's printed start
                # is the attribution point.
                tolerance = 5.0 if field in {"signature", "entry_into_force"} else 1.5
                inside = not (span.x < left - tolerance
                              or (right is not None
                                  and span.x > right + tolerance))
                if (not inside and field == "instrument" and right is not None
                        and left <= (span.x + span.x1) / 2.0 <= right):
                    # The instrument labels are centre-aligned, so a longer
                    # label starts left of the column's measured edge while
                    # sitting inside it (china's `Instrument (a)` 8.5pt left,
                    # spain's `Instrument` 2pt left). The reader assigns such a
                    # span by its centre, and this check measures the same way.
                    inside = True
                if not inside:
                    detail = (f"source span x={span.x:.1f}..{span.x1:.1f} "
                              f"falls outside measured band {left:.1f}.."
                              f"{right if right is not None else 'end'}")
                elif reach is not None and span.x1 < reach - tolerance:
                    detail = (f"source span x={span.x:.1f}..{span.x1:.1f} "
                              f"does not reach measured band {reach:.1f}")
                else:
                    continue
                row_issues.append({"row": number, "field": field,
                                   "span_text": span.text, "detail": detail})

    for row in rows:
        number = row["no"]
        for date_field in ("signature", "entry_into_force"):
            spans, _reconstructed = row_fields.get(number, {}).get(
                date_field, ([], ""))
            assigned_text = " ".join(span.text for span in spans)
            source_dates = _dates(assigned_text, DATE_YMD_RE)
            output_dates = _dates(str(row.get(date_field) or ""), DATE_YMD_RE)
            missing_dates = output_dates - source_dates
            if missing_dates:
                label = ("signature" if date_field == "signature"
                         else "entry into force")
                row_issues.append({
                    "row": number, "field": date_field,
                    "detail": f"output dates absent from the assigned {label} "
                              f"spans: {list(missing_dates.elements())}",
                })

    row_by_no = {row["no"]: row for row in rows}
    pins = (row_pins or {}).get(slug, {})
    for number, (counterparty, title_fragment) in pins.items():
        row = row_by_no.get(number)
        if row is None:
            row_issues.append({"row": number, "field": "anchor",
                               "detail": "source-pinned row was not emitted"})
            continue
        actual_cp = str(row.get("other_jurisdiction") or "")
        actual_title = str(row.get("title") or "")
        if actual_cp != counterparty:
            row_issues.append({"row": number, "field": "counterparty_output",
                               "detail": f"expected {counterparty!r}, found {actual_cp!r}"})
        if title_fragment.casefold() not in actual_title.casefold():
            row_issues.append({"row": number, "field": "title_output",
                               "detail": f"output lacks pinned title phrase {title_fragment!r}"})
        expected_dates = (date_pins or {}).get(number)
        if expected_dates:
            for date_field, expected in zip(("signature", "entry_into_force"),
                                            expected_dates):
                expected_tokens = _dates(expected, DATE_YMD_RE)
                actual_tokens = _dates(str(row.get(date_field) or ""), DATE_YMD_RE)
                missing_pinned_dates = expected_tokens - actual_tokens
                if missing_pinned_dates:
                    row_issues.append({"row": number, "field": date_field,
                                       "detail": f"output missing pinned dates "
                                                 f"{sorted(missing_pinned_dates.elements())}"})

    findings = _exception_findings(slug, rows)
    for number, field, fragment in DEFECT_INVENTORY.get(slug, ()):
        row = row_by_no.get(number)
        value = str(row.get(field) or "") if row else ""
        matches = not value if not fragment else fragment.casefold() in value.casefold()
        if not matches:
            row_issues.append({"row": number, "field": field,
                               "detail": f"reviewed exception finding {fragment!r} not reproduced"})

    # The legacy reader's own wrong rows, re-read live. A record is satisfied
    # only when the legacy reading reproduces its defect and the block reading
    # does not: that is what makes the exception a comparison rather than two
    # independent complaints.
    if legacy_pins:
        legacy_by_no = {row["no"]: row for row in legacy_reading(root, slug)}
        for number, field, fragment, direction in legacy_pins:
            legacy_value = str(
                (legacy_by_no.get(number) or {}).get(field) or "")
            block_value = str(
                (row_by_no.get(number) or {}).get(field) or "")
            in_legacy = fragment.casefold() in legacy_value.casefold()
            in_block = fragment.casefold() in block_value.casefold()
            ok = ((in_legacy and not in_block) if direction == "added"
                  else (in_block and not in_legacy))
            if not ok:
                row_issues.append({
                    "row": number, "field": field,
                    "detail": f"legacy-reader defect {fragment!r} ({direction}) "
                              f"is not reproduced: legacy={legacy_value!r}, "
                              f"block={block_value!r}",
                })

    return {"slug": slug, "reader": "blocks", "rows": len(rows),
            "anchors": len(anchors), "issues": issues,
            "row_issues": row_issues, "findings": findings}


# The published row fields the drift control compares. `no` is the row's own key
# and is compared by membership; every other measured field is compared by
# value, `instruments` (a list) included.
ROW_FIELDS = ("title", "other_jurisdiction", "instrument", "instruments",
              "signature", "entry_into_force", "page")


def compare_published_rows(stored_dir: Path, built: dict) -> dict:
    """Compare every stored position artefact with one live family build.

    The comparison is per row and per field, not per byte: the corpus already
    has to be byte-identical to a fresh build (the determinism test beside this
    one), but a byte difference names only the file. This control asks the
    narrower question a corpus cannot answer about itself - does each row the
    reader measures now still equal the row the artefact holds? - and names the
    row and the field, so a reader repair that no one rebuilt the corpus for
    fails with the exact evidence of the drift.

    `built` is the live family reading (`mli_writer.family_once`), keyed by
    slug under `positions`. A row present on only one side is a divergence too,
    and so is a slug the live reading does not publish - silence must not read
    as agreement.
    """
    live = built.get("positions") or {}
    changed: list[dict] = []
    only_in_artifact: list[dict] = []
    only_in_live: list[dict] = []
    stored_slugs: set[str] = set()
    compared = rows = 0
    for path in sorted(Path(stored_dir).glob("*.json")):
        if path.stem == "batch-report":
            continue
        stored = json.loads(path.read_text(encoding="utf-8"))
        slug = stored.get("slug") or path.stem
        stored_slugs.add(slug)
        position = live.get(slug)
        if position is None:
            continue
        compared += 1
        stored_rows = {row["no"]: row
                       for row in stored.get("covered_agreements") or []}
        live_rows = {row["no"]: row
                     for row in position.get("covered_agreements") or []}
        rows += len(stored_rows)
        for number in sorted(set(stored_rows) | set(live_rows)):
            in_artifact, in_live = stored_rows.get(number), live_rows.get(number)
            if in_live is None:
                only_in_artifact.append({"slug": slug, "row": number})
            elif in_artifact is None:
                only_in_live.append({"slug": slug, "row": number})
            else:
                for field in ROW_FIELDS:
                    if in_artifact.get(field) != in_live.get(field):
                        changed.append({"slug": slug, "row": number,
                                        "field": field,
                                        "stored": in_artifact.get(field),
                                        "live": in_live.get(field)})
    return {
        "published": compared,
        "rows": rows,
        "changed": changed,
        "only_in_artifact": only_in_artifact,
        "only_in_live": only_in_live,
        "artifacts_without_a_live_position": sorted(stored_slugs - set(live)),
        "live_positions_without_an_artifact": sorted(set(live) - stored_slugs),
    }


def audit_published_artifacts(root: Path, directory: Path, source: str) -> dict:
    """Read a position family live and compare it with the corpus row by row."""
    built = mli_writer.family_once(Path(directory), source, Path(root))
    stored_dir = corpus.corpus_root(Path(root)) / "mli" / "positions"
    return compare_published_rows(stored_dir, built)


def format_row_divergences(report: dict) -> list[str]:
    """One line per divergent row, for a failure message that names it."""
    lines = []
    for item in report["changed"]:
        lines.append(f"{item['slug']} row {item['row']} {item['field']}: "
                     f"corpus {item['stored']!r}, reader {item['live']!r}")
    for item in report["only_in_artifact"]:
        lines.append(f"{item['slug']} row {item['row']}: in the corpus but not "
                     "among the rows the reader measures")
    for item in report["only_in_live"]:
        lines.append(f"{item['slug']} row {item['row']}: the reader measures it "
                     "but the corpus does not hold it")
    for slug in report["artifacts_without_a_live_position"]:
        lines.append(f"{slug}: the live reading publishes no such position")
    for slug in report["live_positions_without_an_artifact"]:
        lines.append(f"{slug}: the live reading publishes it and no artefact holds it")
    return lines


DEFECT_INVENTORY: dict = {
    # The row-by-row re-evaluation of 2026-10-06 left two exceptions on the
    # legacy reader, and both were promoted on 2026-10-07. Each entry was the
    # reviewed, source-verified row on which the *block* reading still failed,
    # measured the same way the promotions are: every emitted field's spans
    # against its measured source band (`audit_block_rows`).
    #
    #   algeria       promoted (the next-row title bleed is repaired)
    #   brazil        promoted (the counterparty column is measured, not the label)
    #   israel        promoted (the label sits on its own line, and is measured)
    #   sweden        promoted (the cross-page title bleed is repaired)
    #   cote-d-ivoire promoted (the wrapped dates are rejoined, so the signature
    #                 column is measured at all and the counterparty keeps its
    #                 own `de`/`du`)
    #   egypt         promoted (the row boundary inside a heading printed above
    #                 its own number is found from the heading's mirror about
    #                 the number: row 13 read `INCOME CONVENTION BETWEEN` when
    #                 the run above its number was read as the row above's tail)
    #   peru          promoted (the counterparty column measures a name printed
    #                 left of the shared start: row 7's `Switzerland`, 7pt left,
    #                 used to land in the title with no counterparty at all)
    #
    # No layout is left on the legacy reader for a title-cell mismatch, so this
    # record is empty. It stays as the mechanism an exception must be declared
    # in: a layout whose block reading is not yet faithful gets its failing row,
    # field and fragment here, reviewed row by row against the source.
}


# Where the *legacy* reading is itself wrong, on a named row and field. The
# entry is what the legacy reader emits that the source does not: `dropped`
# means the legacy value has lost the printed fragment the block value keeps,
# `added` means the legacy value carries a fragment (a counterparty fused into
# the title, say) that the block value does not. `audit_block_rows` re-reads
# the same PDF with the legacy reader and checks the record against both
# readings, so keeping a layout on the legacy reader is justified by the
# evidence that the block reading is strictly better where it is, not only by
# the block reading's own remaining defect.
LEGACY_DEFECT_INVENTORY: dict = {
    # The two records this held were retired with their layouts' promotions on
    # 2026-10-07: Egypt's legacy read dropped row 1's counterparty (`Albania`)
    # and Peru's fused row 1's counterparty into the title (`de la Brazil`),
    # and both layouts are now read by the block reader, which keeps each. A
    # slug that is left on the legacy reader records the row it gets wrong here
    # so keeping it on the legacy reader is justified by a comparison rather
    # than by the block reading's own remaining defect.
}
