"""The MLI projection: from the reading to the documents the corpus holds.

`rules/20-mli.yaml` decides what is the page's text and what is its apparatus.
This module decides what that text *is*: a signatory row, with a jurisdiction and
six columns. They are separate on purpose. A reading that can see a table's cells
is not a model of the table, and the difference matters: 100 rows came from reading lines and hoping,
not from a model that could say which jurisdiction a date belongs to.

A row of the OECD signatories table is where the model earns its keep:

* **The columns are x ranges, and they are measurable** because the table's own
  cells stand in them (COLUMNS, below). No cell text is ever sliced to fit a
  column: the geometry decides which column a cell is in, and the cell keeps all
  of its text.
* **A row is opened by its number and closed by the next number**, because a
  jurisdiction's name wraps onto a second line and a cell may be printed well
  below the line its row's number stands on.
* **Where a cell falls between two rows** - three cells of this document do - the
  rules are stated rather than left to the code: `ROW_ATTACH_PT` is how near the
  next number a line is captured by it, and `ROW_PITCH_TOL` is how far below its
  own number a line may sit, which the reader measures from the table's own line
  step and row pitch instead of declaring (`_row_pitch_tol`). The cells those
  rules decided are listed in the artefact's own `qa` block, because a reading
  that was a judgement call should be reviewable rather than invisible.

The footnote markers are not dealt with here. `R-MLI-NOTE-MARK` takes them out
of the text in the reading, as a declared transform, which is why
"Hong Kong (China)6" reaches this module as "Hong Kong (China)" - the digit was
never a character of the name, and the projection is not the place to decide
that.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from harness import ledger

# The signatories table's columns, as the x ranges its cells stand in. Measured
# from the table's own pages: the number cell is right-aligned at x = 82.3-86.2
# ("1 ", "10 "), the jurisdiction at x = 113.0, the signature date at 251.0, the
# deposit at 346.7, the entry into force at 445.9, the later notifications at
# 623.2 and the arbitration profile at 708.1. Each boundary is placed between two
# columns and never through one - the widest cell text, "Democratic Republic of
# the", reaches x = 223.7, and the closest pair of columns is 94pt apart.
COLUMNS = (("no", 100.0), ("jurisdiction", 240.0), ("signature", 340.0),
           ("deposit", 440.0), ("entry_into_force", 620.0),
           ("notifications", 700.0), ("arbitration_profile", float("inf")))
# The window a line is captured up to the next number within. Its value is not
# derived, because it is *published*: it travels inside the artefact as
# `row_attach_pt`, so re-deriving it per table would republish the corpus. What
# the reader does measure for it is the interval the table's own printed lines
# leave it (`_row_attach_band`): the furthest a line captured up stands above its
# number, and the nearest a line left with the number above stands above the next
# one. On the signatories table that interval is 5.1600 pt to 8.1600 pt - three
# points the page prints nothing in - so the declared window is a whole point
# inside a gap the page leaves rather than a length the page pins, and
# `tests/test_invariants.py` holds both halves of that claim against the source.
ROW_ATTACH_PT = 6.0
# How a line further from its number than the attach window is placed is not a
# declared number at all: the reader measures the table's own row pitch and the
# step it sets its lines at, and allows one row plus half of one of those lines
# (`_row_pitch_tol`). Nothing in that threshold is chosen by hand. `ROW_PITCH_TOL`
# is what is used when the table's step or pitch cannot be measured, and it is
# the multiple the derivation reports here - 1.5 row pitches - so an unmeasurable
# page reads as this table does.
ROW_PITCH_TOL = 1.5
STATUS_RE = re.compile(r"^Status as of (.+?)\s*$")
MONTHS = {"January": "01", "February": "02", "March": "03", "April": "04",
          "May": "05", "June": "06", "July": "07", "August": "08",
          "September": "09", "October": "10", "November": "11",
          "December": "12"}


def column_of(x0: float) -> str:
    for name, limit in COLUMNS:
        if x0 < limit:
            return name
    return COLUMNS[-1][0]


def _body_lines(book: ledger.Ledger) -> list:
    kept = [span for span, _rule in book.kept]
    out = []
    for line in ledger.regroup_lines(kept, book.line_policy):
        if book.geometry is not None \
                and book.geometry.band(line.page, line.y, line.size) in ("footer", "note"):
            continue
        if line.match_text:
            out.append(line)
    return out


def _cell_text(lines: list, book: ledger.Ledger) -> str:
    pieces = [ledger._join_spans(line.spans, book) for line in lines]
    return " ".join(piece.strip() for piece in pieces if piece.strip()).strip()


def _owner(line, anchors: list, attach_pt: float, pitch: float = 0.0,
           tol: float = ROW_PITCH_TOL):
    for anchor in anchors:
        if line is anchor:
            return anchor, "number"
    below = next((anchor for anchor in anchors if anchor.y > line.y), None)
    if below is not None and below.y - line.y <= attach_pt:
        return below, "attached-up"
    above = None
    for anchor in anchors:
        if anchor.y <= line.y:
            above = anchor
        else:
            break
    if above is None or (pitch and line.y - above.y > pitch * tol):
        return None, "stray"
    return above, "slot"


def _nearest(line, anchors: list):
    return min(anchors, key=lambda anchor: abs(anchor.y - line.y)) if anchors else None


def _pitch(anchors: list) -> float:
    gaps = sorted(anchors[i + 1].y - anchors[i].y for i in range(len(anchors) - 1))
    return gaps[len(gaps) // 2] if gaps else 0.0


def _line_step(lines: list) -> float:
    """The step this table sets its own lines at: its modal column gap.

    The row-pitch tolerance is a multiple of the row pitch, and what settles the
    multiple is how tall a row is in the table's own lines. That is measured
    here the way `_page_pitch` measures a layout's line: lines are keyed by the
    x their leftmost word starts at - the column the table prints them in - and
    only the gaps between two lines of the *same* key are counted, because a
    printed line arrives as several baselines a fraction of a point apart and a
    gap between two unrelated baselines is not a step of the page. The step that
    repeats most is the table's, since one line per row is printed over a
    hundred times and the page break, the header and the footnotes are not
    repeated at all.

    Measured over the signatories table: 17.5pt, taken 80 times, against a row
    pitch of 17.52pt. A page whose lines share no column key holds no step this
    can read and returns 0.0.
    """
    by_column: dict = defaultdict(list)
    for line in lines:
        starts = [round(span.x, 1) for span in line.spans
                  if any(character.isalpha() for character in span.text)]
        if starts:
            by_column[(line.page, min(starts))].append(round(line.y, 2))
    gaps: Counter = Counter()
    for keys in by_column.values():
        ordered = sorted(keys)
        for earlier, later in zip(ordered, ordered[1:]):
            if later > earlier:
                gaps[round(later - earlier, 1)] += 1
    return float(gaps.most_common(1)[0][0]) if gaps else 0.0


def _table_pitch(pitches: list) -> float:
    """The step the table repeats its rows at: the median of its pages' pitches."""
    values = sorted(pitch for pitch in pitches if pitch > 0.0)
    return values[len(values) // 2] if values else 0.0


def _row_pitch_tol(lines: list, pitches: list) -> float:
    """How far below its number a line may sit, in row pitches: measured, not chosen.

    A row's cells may print on more than one line, and the table sets those lines
    at its own step. So the depth a row's own text reaches is fixed by the table:
    a row is one of its own lines tall - 17.52pt of row pitch against a 17.5pt
    line step - and its last line therefore stands one row pitch below its
    number, with half of one of those lines of slack allowed on top of it. Both
    terms are measured (`_table_pitch`, `_line_step`) and the half is a half, so
    the threshold is a length the table fixes rather than a number chosen here.

    Measured over the signatories table (`.verify/probe_row_pitch_depths.py`),
    the two populations this separates are far apart. The deepest line a row
    owns, a notification date the table prints under its number and just too far
    above the next number to be attached to it, stands 0.808 of a pitch below
    that number; the first line that belongs to a later block - the intent-to-
    sign note under the last row - stands 2.017 pitches below the number above
    it, and the line whose absorption would actually move a row, "Lebanon",
    stands 3.376. One line and a half sits between them, and this could only
    leave that interval by falling under one pitch - which it cannot, since the
    threshold always carries a whole row of the table.

    A table whose step or pitch cannot be measured falls back on
    `ROW_PITCH_TOL`, the multiple this reports here.
    """
    step = _line_step(lines)
    pitch = _table_pitch(pitches)
    if step <= 0.0 or pitch <= 0.0:
        return ROW_PITCH_TOL
    return (pitch + step / 2.0) / pitch


def _row_pitch_report(tol: float) -> float:
    """The derived threshold as the multiple of the row pitch the artefact records.

    The reader decides with a length - one row pitch of the table plus half of one
    of its own lines - and the artefact records it as a multiple of the row pitch,
    rounded to the tenth the printed geometry is read at: 1.4994 is recorded as
    1.5, a difference of 0.01pt of threshold that moves no line, since the nearest
    lines the threshold separates stand 14pt and 59pt from their numbers. Rounding
    the report rather than the decision keeps the threshold the measured length it
    was derived as, while the artefact keeps saying what a reader of the artefact
    can rebuild the threshold from.
    """
    return round(tol, 1)


def _pages(lines: list) -> list:
    """The table's pages, each with its lines, its number anchors and its pitch.

    Gathered before anything is placed, because the tolerance the placement uses
    is measured from the whole table rather than from one page: how tall a row is
    in the table's own lines is a property of the table, and a page whose pitch
    differs still reads under the same multiple of it. The band the attach window
    is measured against (`_row_attach_band`) is read off the same structure, so
    the two cannot be measured over different anchors.
    """
    pages = []
    for page in sorted({line.page for line in lines}):
        page_lines = [line for line in lines if line.page == page]
        anchors = sorted((line for line in page_lines
                          if column_of(line.x0) == "no"
                          and re.fullmatch(r"\d{1,3}", line.match_text)),
                         key=lambda line: line.y)
        pages.append((page, page_lines, anchors, _pitch(anchors)))
    return pages


def _row_attach_band(pages: list, tol: float) -> tuple:
    """The interval the table's own printed lines leave for the attach window.

    The window decides which of two numbers a line printed between them belongs
    to, and the page prints both sides of that decision. The furthest a line the
    placement captures up to the next number stands above that number is the
    deepest the window may be smaller than: below it the next row's own first
    line would be refused. The nearest a line the placement leaves with the
    number above stands above the next number is the shallowest the window may be
    larger than: above it a line would be taken out of the row the page prints it
    in. Every window in the interval places every line as the reading does, and
    the interval itself is measured from the page rather than chosen - on the
    signatories table it is (5.1600, 8.1600), a three-point gap the table prints
    nothing in.

    Which lines are on which side of the boundary is what the placement says and
    not a mark the page prints, so this is the interval the reading is *consistent
    with*; what makes it a measurement rather than a restatement is that both of
    its edges are distances the table prints, which
    `tests/test_invariants.py` pins from the other side.

    The interval is half-open, and not by convention: a line printed exactly at
    the lower edge is captured up, because `_owner` compares with `<=`, while one
    printed exactly at the upper edge would be too, and would then be read as a
    line of the row the page prints it above of. So the declared window has to
    lie in `[low, high)` for the reading to be the one the pages give.

    A table whose placement leaves one side empty has no band this can report,
    and returns `()` rather than an open interval nothing bounds.
    """
    captured = []
    left = []
    for _page, page_lines, anchors, pitch in pages:
        for line in page_lines:
            _anchor, how = _owner(line, anchors, ROW_ATTACH_PT, pitch, tol)
            if how not in ("attached-up", "slot"):
                continue
            below = next((anchor for anchor in anchors if anchor.y > line.y),
                         None)
            if below is None:
                continue
            gap = below.y - line.y
            (captured if how == "attached-up" else left).append(gap)
    if not captured or not left:
        return ()
    return max(captured), min(left)


def signatories(book: ledger.Ledger, source: str, pdf_sha: str = "") -> dict:
    lines = _body_lines(book)
    rows: dict = {}
    order: list = []
    decided: list = []
    outside: list = []
    pages = _pages(lines)
    tol = _row_pitch_tol(lines, [pitch for _page, _lines, _anchors, pitch
                                 in pages])
    band = _row_attach_band(pages, tol)
    for page, page_lines, anchors, pitch in pages:
        for line in page_lines:
            owner, how = _owner(line, anchors, ROW_ATTACH_PT, pitch, tol)
            if owner is None:
                outside.append({"page": page, "y": round(line.y, 2),
                                "column": column_of(line.x0),
                                "text": line.match_text[:80]})
                continue
            number = int(owner.match_text)
            record = rows.get(number)
            if record is None:
                record = {"no": number, "page": page,
                          "cells": {name: [] for name, _limit in COLUMNS}}
                rows[number] = record
                order.append(number)
            record["cells"][column_of(line.x0)].append(line)
            nearest = _nearest(line, anchors)
            if how == "attached-up" or (nearest is not None and nearest is not owner):
                decided.append({"no": number, "page": page,
                                "column": column_of(line.x0), "decided_by": how,
                                "y": round(line.y, 2),
                                "distance_to_number_pt": round(line.y - owner.y, 2),
                                "nearest_number": int(nearest.match_text),
                                "nearest_distance_pt": round(abs(line.y - nearest.y), 2),
                                "text": line.match_text[:60]})
    out = []
    for number in order:
        record = rows[number]
        row = {"no": number, "page": record["page"]}
        for name, _limit in COLUMNS:
            if name != "no":
                value = _cell_text(sorted(record["cells"][name], key=lambda line: line.y),
                                   book)
                if value:
                    row[name] = value
        out.append(row)
    return {
        "source": source, "sha256": pdf_sha,
        "status_as_of": _status_as_of(lines, book),
        "columns": {name: limit for name, limit in COLUMNS if limit != float("inf")},
        "rows": out,
        "qa": {"row_attach_pt": ROW_ATTACH_PT,
               "row_pitch_tol": _row_pitch_report(tol),
               # The interval `row_attach_pt` sits in: the furthest a line the
               # placement captured up stands above its number, and the nearest a
               # line it left with the number above stands above the next one.
               # Published so a reader of the artefact can see how much room the
               # page leaves the window, in the same 0.01pt the printed
               # distances in `cells_where_the_two_placements_disagree` use - and
               # empty when the placement left one side of it unmeasured.
               "row_attach_band_pt": ([round(band[0], 2), round(band[1], 2)]
                                      if band else []),
               "lines_outside_the_table": outside,
               "cells_where_the_two_placements_disagree": decided,
               "note": ("A cell within row_attach_pt above a row's number belongs to "
                        "that row; otherwise it belongs to the row whose number is "
                        "the last one above it. The two placements disagree about "
                        "the cells listed above, and each is given with both "
                        "distances and the row it went to, so these can be checked "
                        "against the page instead of trusted. "
                        "`row_attach_band_pt` is the interval the table's own "
                        "printed lines leave that window: the declared "
                        "row_attach_pt lies in it, a line printed at its lower "
                        "edge is captured up, and one printed at its upper edge "
                        "would be taken out of the row the page prints it in.")},
    }


def _status_as_of(lines: list, book: ledger.Ledger) -> dict:
    for line in lines:
        found = STATUS_RE.match(_cell_text([line], book).strip())
        if found:
            printed = found.group(1)
            return {"printed": printed, "date": _parse_date(printed)}
    return {"printed": "", "date": ""}


def _parse_date(text: str) -> str:
    found = re.match(r"^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$", text.strip())
    if not found or found.group(2) not in MONTHS:
        return ""
    return f"{found.group(3)}-{MONTHS[found.group(2)]}-{int(found.group(1)):02d}"


# --------------------------------------------------------------------------- #
# a country's position
# --------------------------------------------------------------------------- #

SECTION_RE = re.compile(r"^Article\s+(\d+)\s*[\u2013\u2014-]\s*(.+?)\s*$")
OPTION_KINDS = ("Reservation", "Notification", "Choice", "Declaration")
CELL_TOL_PT = 6.0
# The attach window of the number-first reader: a span printed within this
# distance above a row's number belongs to that row - the lead-in a number
# printed at the foot of the cell it names needs (`_row_of`, and `_pos_attach_
# band` for the interval the pages leave for it). It is declared and published -
# it travels inside the position artefacts as `row_attach_pt` - so it stays a
# number rather than a derivation, and the layouts that decide with it are the
# ones the block reader does not read.
POS_ATTACH_PT = 6.0
# The block reader's own reach, and a tolerance of its own rather than that
# window plus a slack: a run of lines printed above a number is absorbed as that
# row's own prefix only within this distance of the number (`_absorbs_prefix`,
# and `_pos_attach_reach_band` for the interval the pages leave for it). The two
# are different decisions taken by different readers on different pages - the
# window places one span among the numbers around it, the reach moves a whole
# run into the row that opens below it - and each is measured off the pages that
# ask it. Declaring the reach as the window plus a slack made them share one
# walk and one band, so neither could be measured alone; the block-read
# artefacts publish this one as `row_attach_pt`, because it is the tolerance
# their rows were decided with.
POS_ATTACH_REACH_PT = 8.0
JUSTIFY_SLACK_PT = 10.0
# How far apart two x starts may stand and still be one column. A column's
# words do not all begin at the same x - a name set one word longer starts a
# little further right - and a right-aligned number column smokes across
# tenths. The same distance decides four clusters of different columns (the
# number run, a title's starts, the promoted layouts' cell model, and the
# band `_measured_column_after` reads as one column), so it is declared once
# and named at every use: a literal 4.0 at one of those sites would keep its
# own value while the others moved, which is the shape that made the attach
# window's band have to be intersected with the reach's.
RAGGED_COLUMN_TOL_PT = 4.0
# A day may be the French ordinal `1er` (cote-d-ivoire prints `1er-03-1985`),
# which the publisher keeps in the table and the reading keeps as printed.
DATE_RE = re.compile(
    r"^\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{2,4}\s*$")
# A date as the publisher prints it inside a packed cell: the run may carry a
# space where the extraction saw a gap ("07-03- 1997"), and a cell can hold
# more than one of them in a single span.
PACKED_DATE_RE = re.compile(
    r"\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\s*\d{2,4}")
DATED_CELL_RE = re.compile(
    r"^\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{2,4}"
    r"(?:\s+\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{2,4})?\s*$")
INT_RE = re.compile(r"^\d{1,3}\s*$")
NUMBER_RE = re.compile(r"^(\d{1,3})(?:\.?(?:\s|$))")
# A date printed in a narrow cell can wrap between its second separator and its
# year: the extractor returns the two pieces as separate spans (`03-07-` on the
# row's own line, `1979` on the line below, the pair printed as `03-07- 1979`).
# A date that wrapped is invisible to a column measured from whole dates, and a
# table that wraps every signature date loses its signature column entirely, so
# the wrapped pieces are rejoined before the columns are measured. The day may
# be the French ordinal `1er`.
DATE_FRAGMENT_RE = re.compile(
    r"^\d{1,2}(?:er)?[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\s*$")
DATE_YEAR_RE = re.compile(r"^\d{2,4}\s*$")
# How far below its fragment a wrapped date's year may stand: one line of the
# table's own leading, no more.
DATE_WRAP_PT = 25.0
# An instrument column's own words. Used only to decide whether words printed
# right of the measured instrument column are an instrument label that was
# merged into the counterparty's span, or one cell's own text crossing the
# column's edge (georgia's "Grand Duchy of Luxembourg", a title run).
INSTRUMENT_LABEL_RE = re.compile(
    r"^\s*(?:original|amending|instrument|protocol|avenant)\b", re.I)
# The same vocabulary, found anywhere in a span: the instrument column's own
# label can carry a word before it (pakistan's `First Protocol`), so measuring
# the column asks whether the span names an instrument at all rather than
# whether it opens on the name.
INSTRUMENT_WORD_RE = re.compile(
    r"\b(?:original|amending|instrument|protocol|avenant)\b", re.I)
# The Arabic block, used to tell a table's Arabic title lines from its Latin
# ones: a bilingual table prints the two headings as separate paragraphs even
# when it sets them at the same leading (see `_block_groups`).
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def _left_edge(item) -> float:
    return item.x0 if hasattr(item, "x0") else item.x


def _full_text(item) -> str:
    return item.match_text if hasattr(item, "match_text") else item.text


def _text(line, book) -> str:
    return _cell_text([line], book)


def _modal_x(lines: list, low: float, high: float, letters: bool = False):
    counts = Counter(round(_left_edge(line), 1) for line in lines
                     if low <= _left_edge(line) < high
                     and (not letters or re.search(r"[A-Za-z]", _full_text(line))))
    return counts.most_common(1)[0][0] if counts else None


def _right_edge(lines: list, cluster: list) -> float:
    edges = [line.x1 for line in lines if _in_column(_left_edge(line), cluster)]
    return max(edges) if edges else _centre(cluster)


def _counterparty_right_edge(table: list, counterpart_x: float,
                             band_right: float) -> float:
    """The counterparty column's own printed right edge.

    It is the widest span whose text begins inside the counterparty's band -
    from the column's measured left edge up to the instrument column - and is
    not an instrument label. The table-level cluster the caller measures can
    land on the instrument label rather than the counterparty when a table's
    counterparty names repeat no more than once each while its labels repeat
    (peru's `Instrument (a)`, `Amending`), and a right edge taken from there
    swallows every label back into the counterparty.
    """
    return max((span.x1 for span in table
                if counterpart_x - 0.5 <= span.x < band_right
                and any(character.isalpha() for character in span.text)
                and not INSTRUMENT_LABEL_RE.match(span.text.strip())),
               default=counterpart_x)


def _counterparty_left_edge(table: list, counterpart_left: float,
                            title_right: float) -> float:
    """The counterparty column's left edge, a name set left of the shared start included.

    The column's names share one start, but one of them can be set a few points
    left of it - peru's `Switzerland` stands 7pt left of the start the other
    names share - the same way a title's first line can begin left of the title
    column. Such a name is not measured by its start alone, and by its start
    alone it falls out of the column and into the title, splitting the printed
    title in two (`Convention between the Swiss Switzerland Confederation`).

    A name is told from the text on its left by its width: the title's own
    words begin in the title column and end at the title's printed right edge,
    while a name set left of the column still reaches across the column's
    shared start. So the column's left edge is the leftmost start between the
    title's right edge and the shared start whose span reaches the shared start
    and is not an instrument label - the label sits in its own column, further
    right again.
    """
    reaching = [span.x for span in table
                if title_right <= span.x < counterpart_left
                and span.x1 >= counterpart_left
                and any(character.isalpha() for character in span.text)
                and not INSTRUMENT_LABEL_RE.match(span.text.strip())]
    return min(reaching, default=counterpart_left)


def sections(lines: list, spans: list) -> list:
    found = []
    for position, line in enumerate(lines):
        match = SECTION_RE.match(line.match_text.strip())
        if match:
            found.append((position, int(match.group(1)), match.group(2),
                          round(line.x0, 1)))
    if not found:
        return []
    margin = Counter(entry[3] for entry in found).most_common(1)[0][0]
    marks = [entry for entry in found if entry[3] == margin]
    order = sorted(spans, key=lambda span: (span.page, span.y))
    out = []
    for index, (position, number, title, _x) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(lines)
        body = lines[position + 1:end]
        first = (lines[position].page, lines[position].y)
        last = ((lines[end].page, lines[end].y) if end < len(lines)
                else (order[-1].page, order[-1].y) if order else first)
        out.append({"no": number, "title": title, "page": lines[position].page,
                    "lines": body,
                    "spans": [span for span in order
                              if first <= (span.page, span.y) < last]})
    return out


def _options(section: dict, book) -> list:
    body = section["lines"]
    left = _modal_x([line for line in body if re.search(r"[A-Za-z]", line.match_text)],
                    0.0, 200.0)
    if left is None:
        return []
    found = []
    for position, line in enumerate(body):
        if round(line.x0, 1) != left:
            continue
        text = _text(line, book).strip()
        kind = next((word for word in OPTION_KINDS if text.startswith(word)), "")
        if kind:
            found.append((position, kind, text))
    out = []
    for index, (position, kind, text) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(body)
        prose = [_text(line, book) for line in body[position + 1:end]
                 if round(line.x0, 1) == left]
        out.append({"kind": kind, "title": _option_title(kind, text),
                    "page": body[position].page,
                    "excerpt": " ".join(part.strip() for part in prose if part.strip()),
                    "body": body[position + 1:end]})
    return out


def _option_title(kind: str, text: str) -> str:
    rest = text[len(kind):].strip()
    return re.sub(r"^[-\u2013\u2014:]\s*", "", rest).strip()


def _join_wrapped_dates(spans: list) -> list:
    """Join a date the printer wrapped across two lines onto one span.

    A narrow date cell can hold only part of its date, and the extractor
    returns the pieces as two spans: the fragment on the row's own line
    (`03-07-`) and the year on the line below (`1979`). Rejoined, the span is
    the date the table prints. The year has to be the bare number printed under
    the fragment and inside the fragment's own x band, so a title's line below
    is never taken for it.
    """
    joined: dict = {}
    consumed: set = set()
    for span in spans:
        if not DATE_FRAGMENT_RE.match(span.text):
            continue
        below = [candidate for candidate in spans
                 if candidate is not span and candidate.page == span.page
                 and 0.0 < candidate.y - span.y <= DATE_WRAP_PT
                 and DATE_YEAR_RE.match(candidate.text)
                 and span.x - 2.0 <= candidate.x <= span.x1 + 2.0]
        if not below:
            continue
        year = min(below, key=lambda candidate: candidate.y)
        joined[id(span)] = replace(span, text=span.text.rstrip() + year.text.strip())
        consumed.add(id(year))
    if not joined:
        return spans
    return [joined.get(id(span), span) for span in spans
            if id(span) not in consumed]


def covered_agreements(spans: list, book, reader_source: str = "") -> tuple:
    """Read the covered-agreements table, measuring its number run first.

    `reader_source` is the PDF's registered stem when a family read supplied a
    common source id to the classifier; it keeps per-document layout dispatch
    available without changing the rules that admitted the spans.
    """
    # The wrapped-date recovery belongs to the block reader, the reading whose
    # columns are measured from the table's own date evidence: it is what keeps
    # a table that wraps every signature date from losing the signature column
    # (cote-d-ivoire). The legacy reader's readings are published as they are,
    # so a layout it still serves is left with the reading it has.
    if reader_source in BLOCK_READER_SOURCES:
        spans = _join_wrapped_dates(spans)
    dates = [span for span in spans if DATED_CELL_RE.match(span.text.strip())]
    if not dates or len(spans) < 10:
        return [], {"read": False, "reason": "no dated table in this section"}
    date_xs = sorted({round(span.x, 1) for span in dates})
    split_dates_by_text = len(date_xs) < 2
    if split_dates_by_text:
        signature_x = force_x = date_xs[0]
    else:
        split = max(range(len(date_xs) - 1),
                    key=lambda index: date_xs[index + 1] - date_xs[index])
        signature_x = min(span.x for span in dates if span.x < date_xs[split] + 0.5)
        force_x = min(span.x for span in dates if span.x >= date_xs[split] + 0.5)

    margin = min((span.x for span in spans), default=0.0)
    modal_x = _modal_x([span for span in spans if any(c.isalpha() for c in span.text)],
                       margin + 5.0, signature_x - 1.0)
    modal_table = ([span for span in spans
                    if (span.page, span.y) >= _table_start(spans, modal_x)]
                   if modal_x is not None else [])
    modal_right = _right_edge(modal_table, [modal_x]) if modal_table else 0.0
    modal_anchors, modal_run = (_number_column(modal_table, modal_x + 0.5)
                                if modal_table else ([], 0))
    dispatch_source = reader_source or (spans[0].source if spans else "")
    if dispatch_source == "mli-position-china":
        modal_anchors = _china_footer_row_anchors(
            modal_table, modal_anchors, dates, signature_x, force_x)
        modal_run = _consecutive_number_run(modal_anchors)
    modal_counterparty = (_leftmost_column(
        modal_table, modal_right, signature_x - 1.0) if modal_table else None)
    if modal_anchors and modal_run >= 2 and modal_counterparty is not None:
        if (dispatch_source in BLOCK_READER_SOURCES
                and (dispatch_source == "mli-position-china"
                     or _cells_disagree(modal_table, modal_anchors, modal_x,
                                        modal_counterparty))):
            if dispatch_source == "mli-position-china":
                blocked, block_qa = _read_china_covered(
                    book, modal_table, modal_anchors, modal_x,
                    modal_counterparty, dates, signature_x, force_x,
                    split_dates_by_text)
            else:
                blocked, block_qa = _read_block_covered(
                    book, modal_table, modal_anchors, modal_x,
                    modal_counterparty, dates, signature_x, force_x,
                    split_dates_by_text)
            if _block_read_complete(blocked, block_qa, modal_anchors):
                return blocked, block_qa
        return _read_legacy_covered(
            spans, book, dates, signature_x, force_x, split_dates_by_text,
            modal_x, modal_table, modal_anchors, modal_run, modal_counterparty)

    from harness.covered import _read as read_number_first
    number_anchors, number_run = _number_column(spans, signature_x - 1.0)
    title_x = _title_column_after_numbers(spans, number_anchors, signature_x - 1.0)
    return read_number_first(spans, book, dates, signature_x, force_x,
                             split_dates_by_text, number_anchors, number_run, title_x)


def _measured_columns(table: list, anchors: list, title_x: float,
                      counterpart_column: list, dates: list, signature_x: float,
                      force_x: float) -> list:
    """The table's measured columns, shared by both readers of this shape.

    The number and title columns come from the anchors and the modal title x,
    the counterparty column from the measured band beside the title, the
    instrument column from the alphabetic labels printed on dated lines between
    the counterparties and the dates, and the two date columns from where the
    table itself prints them. Both the title-cell reader and the block reader
    fill their cells through these names.
    """
    columns = [("no", min(span.x for span in anchors)),
               ("title", title_x),
               ("other_jurisdiction", counterpart_column[0])]
    counterpart_right = _right_edge(table, counterpart_column)
    dated = {(span.page, round(span.y, 1)) for span in dates}
    labels = [span for span in table
              if counterpart_right <= span.x < signature_x - 1.0
              and any(char.isalpha() for char in span.text)
              and (span.page, round(span.y, 1)) in dated]
    instrument_x = min((span.x for span in labels), default=None)
    if instrument_x is not None:
        columns.append(("instrument", instrument_x))
    columns += [("signature", signature_x), ("entry_into_force", force_x)]
    return columns


def _read_legacy_covered(spans: list, book, dates: list,
                          signature_x: float, force_x: float,
                          split_dates_by_text: bool, title_x: float,
                          table: list, anchors: list, numbered: int,
                          counterpart_column: list) -> tuple:
    """Keep the established title-cell reader for already-readable positions."""
    columns = _measured_columns(table, anchors, title_x, counterpart_column,
                                dates, signature_x, force_x)
    title_right = _right_edge(table, [title_x])

    anchors = sorted(anchors, key=lambda span: (span.page, span.y))
    anchor_ids = {id(span) for span in anchors}
    starts, justified = _title_cells(table, title_x, counterpart_column[0], title_right)
    use_cells = justified >= 0.5 and len(starts) >= numbered
    rows: dict = {}
    order: list = []
    unplaced: list = []
    numbered_rows: list = []
    # The placements this reading asks about, kept so that the interval the
    # table's own spans leave for the window travels with the rows it decided
    # (`_pos_attach_band`). The title-cell branch below never asks the window,
    # and then this stays empty and the artefact says so.
    placements: list = []
    if use_cells:
        for index, start in enumerate(starts):
            end = (starts[index + 1] if index + 1 < len(starts)
                   else (max(span.page for span in table) + 1, 0.0))
            cell = [span for span in table
                    if (start[0], start[1] - 0.5) <= (span.page, span.y) < end]
            number_spans = [span for span in cell if id(span) in anchor_ids]
            if not number_spans:
                if order:
                    previous = rows[order[-1]]
                    for span in cell:
                        for name, printed in _dated_cells(span, columns,
                                                          split_dates_by_text):
                            previous["cells"].setdefault(name, []).append(printed)
                numbered_rows.append({"page": start[0], "y": round(start[1], 2),
                                      "text": _words(cell, book)[:80]})
                continue
            record = _row(rows, order,
                          int(NUMBER_RE.match(number_spans[0].text.strip()).group(1)),
                          number_spans[0])
            for span in cell:
                if id(span) in anchor_ids:
                    rest = NUMBER_RE.sub("", span.text.strip(), count=1).strip()
                    if rest:
                        record["cells"].setdefault("title", []).append(
                            replace(span, text=rest))
                    continue
                for name, printed in _dated_cells(span, columns, split_dates_by_text):
                    record["cells"].setdefault(name, []).append(printed)
    else:
        for span in table:
            placements.append((span, anchors))
            anchor = _row_of(span, anchors)
            if anchor is None:
                unplaced.append({"page": span.page, "y": round(span.y, 2),
                                 "x": round(span.x, 1), "text": span.text.strip()[:80]})
                continue
            number = int(NUMBER_RE.match(anchor.text.strip()).group(1))
            record = _row(rows, order, number, anchor)
            if id(span) in anchor_ids:
                rest = NUMBER_RE.sub("", span.text.strip(), count=1).strip()
                if rest:
                    record["cells"].setdefault("title", []).append(
                        replace(span, text=rest))
                continue
            for name, printed in _dated_cells(span, columns, split_dates_by_text):
                record["cells"].setdefault(name, []).append(printed)

    out = []
    for number in order:
        record = rows[number]
        row = {"no": number, "page": record["page"]}
        for name, _x in columns:
            if name == "no":
                continue
            value = _words(sorted(record["cells"].get(name, []),
                                  key=lambda span: (span.page, round(span.y, 1), span.x)), book)
            if value:
                row[name] = value
        row["instruments"] = _instruments(record["cells"], book)
        out.append(row)
    qa = {
        "read": True, "columns": {name: round(x, 1) for name, x in columns},
        "numbering": {"first": min(order) if order else None,
                      "last": max(order) if order else None, "rows": len(order),
                      "runs_from_one_without_a_gap":
                          sorted(order) == list(range(1, len(order) + 1))},
        "rows_delimited_by": ("the first line of each title cell" if use_cells
                              else "the row numbers (this table's title column is "
                                   "not justified, so its cells cannot be told apart)"),
        "title_cells_match_printed_numbers": (
            "yes" if not _cells_disagree(table, anchors, title_x,
                                         counterpart_column) else
            "no: title cells hold more than one printed number, or a printed "
            "number opened no row; the row model is declared misaligned in the "
            "artefact's own qa"),
        "numbered_rows_without_a_number": numbered_rows,
        "numbers_with_no_row": [n for n in range(1, max(order, default=0) + 1)
                                if n not in rows],
        "row_attach_pt": POS_ATTACH_PT, "span_tol_pt": CELL_TOL_PT,
        # The interval this table's own printed spans leave for that window:
        # the furthest a lead-in this reading captured stands above its number
        # and the nearest a span it left with the number above stands above the
        # next one (`_pos_attach_band`). A reading that places its spans by
        # title cells never asks the window and carries `[]`.
        "row_attach_band_pt": _rounded_band(_pos_attach_band(placements)),
        "date_columns": (
            "one x: the two date columns are printed close enough that their "
            "cells arrive as one span, and a cell with two dates is split by "
            "the table's own column order" if split_dates_by_text else
            "two x: the signature and the entry into force are separated by "
            "where the table prints them"),
        "dated_cells_split_by_text": (
            sum(len(record["cells"].get("entry_into_force", []))
                for record in rows.values()) if split_dates_by_text else 0),
        "spans_that_fitted_no_column": unplaced,
        "note": (
            "The table's columns are measured from the table itself and not "
            "declared, because two positions do not print them at the same x. "
            "A row is opened by its own number; a span within row_attach_pt "
            "above a number belongs to that number, and whatever the table "
            "prints above its first number belongs to the first row - which is "
            "a row whose number the printer centred, so its cells stand over "
            "it. The measured geometry is above, and a span that fitted no "
            "column is listed rather than silently attached to one. Every "
            "number the table prints inside its own run and this projection "
            "found no row for is in `numbers_with_no_row`: the run is published "
            "with the gap it has, rather than renumbered, because a renumbered "
            "table cannot be checked against the page it came from. "
            "`row_attach_band_pt` is the interval this table's own printed "
            "spans leave the window: the declared value lies in it, a span "
            "printed at its lower edge is captured up and one printed at its "
            "upper edge would be, and a reading that places its spans by title "
            "cells carries an empty interval because it never asks the "
            "window."),
    }
    return out, qa


CHINA_COVERED_FOOTER_ANCHORS = {
    2: 20, 5: 43, 9: 74, 11: 89,
}

# The promotions are limited to table layouts whose block boundaries and
# recovered rows have been checked against their PDFs. China additionally needs
# its four tiny footer row numbers restored by the narrowly scoped classifier rule.
# The family shares code, not necessarily geometry: Algeria's long bilingual
# legal-decree titles and Sweden's bilingual French/English titles are read by
# the same block grouping as the rest, and their boundaries were measured
# against the source row by row (tests/mli_row_audit.py). Egypt and Peru come off
# the legacy reader last: Egypt prints each row's number inside its heading, so
# the row boundary inside the paragraph is found from the heading's own mirror
# about the number, and Peru prints one counterparty (row 7's `Switzerland`) 7pt
# left of the start the column's other names share.
BLOCK_READER_SOURCES = frozenset({
    "mli-position-czech-republic", "mli-position-nigeria",
    "mli-position-south-africa", "mli-position-tunisia",
    "mli-position-ukraine", "mli-position-mexico", "mli-position-spain",
    "mli-position-panama", "mli-position-viet-nam",
    "mli-position-china", "mli-position-chile", "mli-position-colombia",
    "mli-position-isle-of-man", "mli-position-gabon",
    "mli-position-burkina-faso", "mli-position-georgia",
    "mli-position-latvia", "mli-position-pakistan",
    "mli-position-norway", "mli-position-senegal",
    "mli-position-lithuania", "mli-position-indonesia",
    "mli-position-new-zealand", "mli-position-slovenia",
    "mli-position-algeria", "mli-position-brazil",
    "mli-position-israel", "mli-position-sweden",
    "mli-position-cote-divoire", "mli-position-egypt",
    "mli-position-peru",
})


def _china_footer_row_anchors(table: list, anchors: list,
                              dates: list, signature_x: float,
                              force_x: float) -> list:
    """Add the four under-sized China row numbers, proven by their dated rows.

    The source rule admits only four page/position-specific footer row lines.
    Here we require the number, counterparty, Original label and both date cells
    at the same y before treating that number as a table anchor.
    """
    known = {id(anchor) for anchor in anchors}
    page_lines = _block_page_lines(table)
    signature_xs = {round(span.x, 1) for span in dates
                    if abs(span.x - signature_x) <= 0.6}
    force_xs = {round(span.x, 1) for span in dates
                if abs(span.x - force_x) <= 0.6}
    extra = []
    for page, number in CHINA_COVERED_FOOTER_ANCHORS.items():
        y = next((y for candidate_page, y in page_lines
                  if candidate_page == page and abs(y - 754.2) <= 0.6), None)
        if y is None:
            continue
        line = page_lines[(page, y)]
        number_span = next((span for span in line
                            if NUMBER_RE.fullmatch(span.text.strip())
                            and int(span.text.strip()) == number), None)
        has_counterparty = any(span.x < signature_x - 1.0
                               and span.x > min(anchor.x for anchor in anchors)
                               and any(char.isalpha() for char in span.text)
                               for span in line if span is not number_span)
        has_original = any("original" in span.text.strip().casefold()
                           for span in line if span.x < signature_x - 1.0)
        has_signature = any(round(span.x, 1) in signature_xs
                            and DATED_CELL_RE.match(span.text.strip())
                            for span in line)
        has_force = any(round(span.x, 1) in force_xs
                        and DATED_CELL_RE.match(span.text.strip())
                        for span in line)
        if (number_span is not None and id(number_span) not in known
                and has_counterparty and has_original
                and has_signature and has_force):
            extra.append(number_span)
    unique: dict[int, object] = {}
    for anchor in sorted([*anchors, *extra],
                         key=lambda span: (span.page, span.y, span.x)):
        number = int(NUMBER_RE.match(anchor.text.strip()).group(1))
        unique.setdefault(number, anchor)
    return sorted(unique.values(), key=lambda span: (span.page, span.y, span.x))


def _read_china_covered(book, table: list, anchors: list, title_x: float,
                        counterpart_column: list, dates: list,
                        signature_x: float, force_x: float,
                        split_dates_by_text: bool) -> tuple:
    """Read China's table while excluding its repeated top-of-page headers.

    China's title continuations and recurring column headings share the first
    105pt of each page. Its dense table has five exact header lines at the same
    y positions; remove those from row grouping, then delegate row attribution
    to the block reader.
    """
    lines = _block_page_lines(table)
    headers = {key for key in lines if key[1] < 105.0}
    data = [span for span in table
            if (span.page, round(span.y, 1)) not in headers]
    return _read_block_covered(
        book, data, anchors, title_x, counterpart_column, dates,
        signature_x, force_x, split_dates_by_text)


def _consecutive_number_run(anchors: list) -> int:
    values = {int(NUMBER_RE.match(span.text.strip()).group(1))
              for span in anchors}
    run = 0
    while run + 1 in values:
        run += 1
    return run


def _cells_disagree(table: list, anchors: list, title_x: float,
                    counterpart_column: list) -> bool:
    """Do the title cells hold more than one number, or lose one?

    The legacy reader's cells are bounded by justified edges: when a row's last
    title line is nearly full the boundary hides, two printed numbers fall into
    one cell and the second is dropped silently. This asks the cells themselves
    - the same segmentation `_title_cells` measures - whether each printed
    number is the only one in its cell and every number opened a row. True
    means the cell model does not agree with the page and the block reader has
    to be asked first.
    """
    title_right = _right_edge(table, [title_x])
    counterpart_x = counterpart_column[0]
    starts, _justified = _title_cells(table, title_x, counterpart_x, title_right)
    assignments: dict[int, int] = {id(anchor): 0 for anchor in anchors}
    for index, start in enumerate(starts):
        end = (starts[index + 1] if index + 1 < len(starts)
               else (max(span.page for span in table) + 1, 0.0))
        cell = [anchor for anchor in anchors
                if (start[0], start[1] - 0.5)
                <= (anchor.page, anchor.y) < end]
        if len(cell) > 1:
            return True
        for anchor in cell:
            assignments[id(anchor)] += 1
    if any(count != 1 for count in assignments.values()):
        return True
    # A number printed fused with its title's first line ("18 Convention
    # entre...") starts at the number column's x, left of the title column the
    # cells are measured in: no cell can open at its line, and the cell model
    # is blind to the row it belongs to (viet-nam's row 1). Some tables print
    # every row that way and the cell model still holds (argentina, thailand),
    # so the tell is not the fusion itself but the anchor standing outside the
    # x cluster the table's own numbers share - with the column's own
    # tolerance, since a right-aligned column still smokes across tenths.
    clusters = _x_clusters(sorted(round(anchor.x, 1) for anchor in anchors),
                           tol=RAGGED_COLUMN_TOL_PT)
    column = max(clusters, key=len) if clusters else []
    return any(" " in anchor.text.strip()
               and NUMBER_RE.match(anchor.text.strip())
               and not _in_column(round(anchor.x, 1), column)
               for anchor in anchors)


def _block_page_lines(table: list) -> dict:
    lines: dict = {}
    for span in table:
        lines.setdefault((span.page, round(span.y, 1)), []).append(span)
    return lines


def _block_header_lines(table: list, anchors: list) -> set[tuple[int, float]]:
    """Find obvious column-heading lines above the first row on each page.

    Some publishers place repeated column labels in the header band, before the
    first covered row. Ignore that band for tables with dense, recurring table
    furniture; on a sparse page, a title continuation may precede its first
    number, so require four distinct labels in the 50pt window as additional
    evidence before excluding a partial in-body heading.
    """
    labels = {"no", "title", "contracting", "jurisdiction", "instrument",
              "amending", "signature", "into", "force"}
    lines = _block_page_lines(table)
    by_page: dict[int, list] = {}
    for anchor in anchors:
        by_page.setdefault(anchor.page, []).append(anchor)
    headers: set[tuple[int, float]] = set()
    header_band_pages = {page for page, _y in lines if _y < 105.0}
    dense_table = len(anchors) >= 80
    for page, page_anchors in by_page.items():
        # Round the first anchor the same way the line keys are rounded: a raw
        # y of 92.44 over its own line's key 92.4 would otherwise put the row's
        # own line inside the window, and excluding it would drop that row's
        # number (south-africa lost rows 6, 11, 16, ... this way).
        first = round(min(anchor.y for anchor in page_anchors), 1)
        window = [(page, y) for p, y in lines
                  if p == page and first - 50.0 <= y < first]
        if dense_table and page in header_band_pages:
            headers.update(key for key in lines
                           if key[0] == page and key[1] < 105.0)
        hits = {span.text.strip().casefold()
                for key in window for span in lines[key]
                if span.text.strip().casefold() in labels}
        if len(hits) < 4:
            continue
        # Four or more column labels in the window mean the window is the
        # heading band, so every line in it is printer's furniture - including
        # the two lines whose own words ("Other", "Date of") are not labels.
        # Excluding only the label lines left those two behind, and they then
        # landed in a row as a counterparty and as dates (south-africa's rows
        # 6, 11, ... and panama's row 9).
        headers.update(window)
    return headers


def _line_title_x1(line: list, counterpart_x: float) -> float | None:
    """Where the line's title text ends - the edge the justification test uses."""
    text = [span for span in line
            if span.x < counterpart_x - 1.0
            and any(char.isalpha() for char in span.text)]
    return max((span.x1 for span in text), default=None)


def _block_full_edge(lines: dict, counterpart_x: float) -> float:
    """The modal rounded title right edge: the width a full (justified) line runs to."""
    values = [_line_title_x1(line, counterpart_x)
              for _key, line in sorted(lines.items())]
    rounded = Counter(round(value) for value in values if value is not None)
    return float(rounded.most_common(1)[0][0]) if rounded else 0.0


def _page_pitch(lines: dict, counterpart_x: float) -> float:
    """The step this layout prints its own lines at: its modal column gap.

    The block reader's two tolerances are fractions of this layout's own line,
    and the line is not a shared constant: egypt sets its titles at 13.4pt and
    israel at 10.3pt. It is measured from the page's own baselines, and the
    measurement has to survive two ways a page is not a single column.

    A printed line arrives as several baselines a fraction of a point apart -
    an italic letter is set a little higher than the roman text around it - so
    a gap between adjacent baselines is not a step of the page. The signature
    that separates them without a threshold is the column: lines carrying title
    text are keyed by the x their leftmost word starts at, which is the column
    the page prints them in, and only steps between two lines of the *same* key
    are counted. The pitch is the step that repeats most, because a page sets
    the lines of a paragraph at one step and the page break, the running head
    and the row boundaries are not repeated. That is why the median of all
    baselines is unusable - on algeria's bilingual page it reads 3.8pt, on
    israel's 7.7pt - while this measure reads 13.8 and 10.3, the steps their
    pages actually repeat.

    A page whose lines share no column key holds no step this can read and
    returns 0.0; the caller then has no short line to measure and refuses the
    break rather than inventing a line.
    """
    by_column: dict = defaultdict(list)
    for key in lines:
        starts = [round(span.x, 1) for span in lines[key]
                  if span.x < counterpart_x - 1.0
                  and any(character.isalpha() for character in span.text)]
        if starts:
            by_column[min(starts)].append(key)
    gaps: list = []
    for keys in by_column.values():
        ordered = sorted(keys)
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier[0] == later[0] and later[1] > earlier[1]:
                gaps.append(round(later[1] - earlier[1], 1))
    if not gaps:
        return 0.0
    return Counter(gaps).most_common(1)[0][0]


def _block_ragged_slack(lines: dict, counterpart_x: float) -> float:
    """A quarter of this layout's own line: how short a title line must fall.

    A title line whose right edge falls short of the block's modal edge is the
    printer's ragged break, and the question is how far short it must fall. The
    shortfall of a full (justified) line is the extractor's own rounding -
    algeria's Arabic decree lines measure 263.96 and 264.05 against a modal edge
    of 267.0, a third of a point - while a line the printer broke short falls
    short by a word, and no line of these tables falls short by less than two
    and a half points. A quarter of the layout's own line lies between the two
    on every promoted layout: 2.58pt on israel's 10.3pt page, 3.70pt on
    tunisia's 14.8pt one, against roundings below 0.5pt and breaks above 2.5pt.

    The measure that made this derivable is the page's own step between its
    columns' lines (`_page_pitch`), and the window it may occupy is not narrow:
    `.verify/probe_tolerance_windows.py slack` re-reads every promoted layout
    under a grid of slacks and finds the reading identical from 2.0pt to 4.5pt
    on all 31, so
    a quarter of the line is not a value that had to be hand-fitted. A layout
    whose line cannot be measured allows no break at all: nothing is then known
    to be short of anything, and a tolerance invented on top is the failure the
    measurement exists to avoid.
    """
    return _page_pitch(lines, counterpart_x) / 4.0


def _line_script(line: list, counterpart_x: float) -> str | None:
    """The script of a title line's own words: `arabic`, `latin`, or none.

    Only the line's title-column words count: the counterparty and the dates
    stand right of that column and never decide which language a title is
    written in. A line with no letters at all (a printed number) has no script
    of its own and does not break a run.
    """
    text = "".join(span.text for span in line
                   if span.x < counterpart_x - 1.0)
    if not any(character.isalpha() for character in text):
        return None
    return "arabic" if ARABIC_RE.search(text) else "latin"


def _keys_script(keys: list, lines: dict, counterpart_x: float) -> str | None:
    """The one script a run of title lines is written in, or none if mixed."""
    found = {_line_script(lines[key], counterpart_x) for key in keys}
    found.discard(None)
    return found.pop() if len(found) == 1 else None


def _block_groups(lines: dict, counterpart_x: float,
                  anchor_lines: dict) -> list[list]:
    """Runs of lines: a ragged line ends its block, the next line starts one.

    A ragged line that carries a printed number is a row of its own (the
    one-line rows of the French positions), so it both closes the block before
    it and opens its own; a ragged line without a number is the last line of
    the block it is in.

    A change of script ends a block too. Egypt's bilingual table prints the
    Arabic heading of an Arab counterparty and the English heading of the next
    agreement as two paragraphs set at the same leading, and no vertical gap
    marks the join: the Arabic heading of one agreement was read as the head of
    the row above it, whose own heading is English, and the two languages
    interleaved. The two headings are different paragraphs, and a block never
    holds both, so the script change is what separates them.
    """
    full = _block_full_edge(lines, counterpart_x)
    slack = _block_ragged_slack(lines, counterpart_x)
    out: list[list] = []
    current: list = []
    script: str | None = None
    for key in sorted(lines):
        line_script = _line_script(lines[key], counterpart_x)
        if (line_script is not None and script is not None
                and line_script != script and current):
            out.append(current)
            current = []
        x1 = _line_title_x1(lines[key], counterpart_x)
        ragged = (slack > 0.0 and x1 is not None
                  and x1 < full - slack)
        if ragged and key in anchor_lines:
            if current:
                out.append(current)
            current = [key]
            script = line_script or script
            continue
        current.append(key)
        if ragged:
            out.append(current)
            current = []
        if line_script is not None:
            script = line_script
    if current:
        out.append(current)
    return out


def _block_split(lines: dict, block: list, earlier, later,
                 counterpart_x: float) -> tuple:
    """Where one block holding two numbers is cut: the line whose right edge
    drops most below its predecessor - the printer's own ragged boundary,
    which the modal edge missed because another row's lines are wider."""
    if earlier.page != later.page:
        return (later.page, -1.0)
    candidates = [key for key in block
                  if (earlier.page, round(earlier.y, 1))
                  < (key[0], key[1])
                  < (later.page, round(later.y, 1))]
    best, score = None, 0.0
    for index, key in enumerate(candidates):
        value = _line_title_x1(lines[key], counterpart_x)
        previous_key = (candidates[index - 1] if index
                        else (earlier.page, round(earlier.y, 1)))
        previous = _line_title_x1(lines.get(previous_key, []), counterpart_x)
        if value is None or previous is None:
            continue
        if previous - value > score:
            best, score = key, previous - value
    slack = _block_ragged_slack(lines, counterpart_x)
    if best is None or slack <= 0.0 or score < slack:
        # A long final title line can reach the same right edge as a full line
        # without the row separator becoming visible. When there is no genuine
        # ragged drop, the next printed number is the only reliable boundary;
        # do not start the next row at the previous row's last line.
        return (later.page, round(later.y, 1))
    return (best[0], best[1] + 0.1)


def _block_split_mirror(lines: dict, block: list, earlier, later,
                        counterpart_x: float, start) -> tuple:
    """Where a block holding two numbers is cut when the number is in its heading.

    On a table whose rows print their number inside the heading, the heading is
    centred on that number, so the row's own first line mirrors about it onto
    its last. The lines a block holds between two numbers are therefore cut at
    the earlier number's mirror: everything up to it belongs to the row above,
    and the first line below it opens the next row's heading - the heading
    printed above its own number. On these tables the largest ragged drop that
    `_block_split` looks for is the number line itself, which is ragged whatever
    the heading is: cutting there hands the next row's opening lines to the row
    above, and the whole block slides down one row (egypt's rows 28, 29 and 30,
    and 49 and 50).

    `start` is where the earlier row's own block opens, so the earlier row's
    first line is the first title line from there. The cut falls back to
    `_block_split` when the two numbers stand on different pages (the page break
    is the boundary), when the block holds no title line to measure the mirror
    with, when nothing stands below the mirror, and when the mirror would cut at
    or past the next number itself.
    """
    if earlier.page != later.page:
        return _block_split(lines, block, earlier, later, counterpart_x)
    firsts = [key for key in block
              if key >= start and key[0] == earlier.page
              and _line_title_x1(lines[key], counterpart_x) is not None]
    if not firsts:
        return _block_split(lines, block, earlier, later, counterpart_x)
    first = min(firsts)
    mirror = 2.0 * earlier.y - first[1]
    own = (earlier.page, round(earlier.y, 1))
    after = [key for key in block
             if key[0] == earlier.page and key >= own
             and key[1] > mirror + _mirror_tol(lines, counterpart_x)]
    if not after:
        return _block_split(lines, block, earlier, later, counterpart_x)
    cut = min(after)
    if cut >= (later.page, round(later.y, 1)):
        return _block_split(lines, block, earlier, later, counterpart_x)
    # The cut is the next row's own first line, and a start is inclusive, so it
    # is set a tenth of a point above that line's baseline to take the line
    # itself (the same tenth `_block_split` uses on the other side).
    return (cut[0], cut[1] - 0.1)


def _block_columns(table: list, anchors: list, title_x: float,
                   counterpart_column: list, dates: list, signature_x: float,
                   force_x: float) -> list:
    """Measure block-reader columns from the row-number lines.

    In these layouts the first line of a title can begin a couple of points
    left of the modal x (South Africa), and a long counterparty's right edge
    can run into the instrument column (Mexico). The anchor lines show the
    printer's actual x starts for the title, counterparty, and instrument on
    the same rows; use those starts rather than the distant right edge of the
    widest counterparty string.
    """
    anchor_ids = {id(anchor) for anchor in anchors}
    number_right = max(anchor.x for anchor in anchors)
    title_starts = [round(span.x, 1) for span in table
                    if id(span) not in anchor_ids
                    and number_right + 5.0 < span.x < counterpart_column[0] - 1.0
                    and any(char.isalpha() for char in span.text)]
    title_clusters = _x_clusters(title_starts, tol=RAGGED_COLUMN_TOL_PT)
    title_band = next((cluster for cluster in title_clusters if len(cluster) >= 2), [])
    title_left = title_band[0] if title_band else title_x
    title_right = _right_edge(table, [title_left])

    # The counterparty's own column starts where the title's column ends, and
    # on a table that prints them almost touching (brazil: the title's widest
    # first line runs to 244.66 and the counterparty stands at 245.0) even a
    # half-point offset steps over the counterparty and lands on the
    # instrument label instead. The title's own lines all start at the title
    # column, far to the left of this edge, so the bound can be the edge
    # itself without admitting any of them.
    counterpart_starts = _measured_column_after(
        table, title_right, signature_x - 1.0)
    counterpart_left = (counterpart_starts[0] if counterpart_starts
                        else counterpart_column[0])
    counterpart_left = _counterparty_left_edge(
        table, counterpart_left, title_right)

    dated = {(span.page, round(span.y, 1)) for span in dates}
    dated_ys: dict[int, list[float]] = {}
    for span in dates:
        dated_ys.setdefault(span.page, []).append(span.y)
    window = [span for span in table
              if counterpart_left + 30.0 <= span.x < signature_x - 1.0
              and any(char.isalpha() for char in span.text)]

    def _on_a_dated_line(span) -> bool:
        # A table can print the instrument label on its own line a point or two
        # above the dated line it belongs to (israel's `Original` at 375.2
        # against its dates at 376.8), so the label's line is accepted when it
        # shares the dated line's baseline within the printer's own leading.
        if (span.page, round(span.y, 1)) in dated:
            return True
        return any(abs(span.y - y) <= 2.5 for y in dated_ys.get(span.page, ()))

    # Only a word the instrument column itself prints names the column. A
    # counterparty printed with its own `de`/`du` set apart from the name
    # (cote-d-ivoire's `Royaume de Belgique`: `Royaume` and `de` arrive as two
    # spans, `de` standing 27pt right of `Royaume`) would otherwise measure the
    # column and then be handed to it, taking the name's own word away.
    labels = [span for span in window if _on_a_dated_line(span)
              and INSTRUMENT_WORD_RE.search(span.text)]
    instrument_x = min((span.x for span in labels), default=None)
    columns = [("no", min(anchor.x for anchor in anchors)),
               ("title", title_left),
               ("other_jurisdiction", counterpart_left)]
    if instrument_x is not None:
        columns.append(("instrument", instrument_x))
    columns += [("signature", signature_x), ("entry_into_force", force_x)]
    return columns


def _heading_line_counts(record: dict, lines: dict,
                         counterpart_x: float) -> tuple[int, int]:
    """The title lines above and below the row's number, in the row's own keys.

    A line counts as a title line of the row when it carries a word in the
    title column; the counterparty, the instrument label and the dates stand in
    their own columns and are not part of the heading.
    """
    anchor = record["anchor"]
    key = (anchor.page, round(anchor.y, 1))
    above = below = 0
    for line_key in record["keys"]:
        if line_key == key or _line_title_x1(lines[line_key],
                                             counterpart_x) is None:
            continue
        if line_key < key:
            above += 1
        else:
            below += 1
    return above, below


def _mirror_tol(lines: dict, counterpart_x: float) -> float:
    """An eighth of this layout's own line: how near a mirror must land.

    A heading the table centres on its own number mirrors about that number, so
    the mirror of the line a row owns is a line the table prints. The residual
    of a genuine mirror is the printer's rounding - every row measured on
    egypt's table is within a fifth of a point - while a mirror off by a line is
    a whole line out, which is the failure this tolerance exists to refuse. The
    tolerance is therefore an eighth of the layout's own line (`_page_pitch`),
    and no table needs a hand-measured number: egypt's 13.4pt line allows
    1.68pt, israel's 10.3pt allows 1.29pt, and both are far nearer the rounding
    than the line they must not mistake it for - and both stay below half a
    line, where a mirror would begin to see the neighbouring line.

    A page whose line cannot be measured allows no mirror at all: nothing is
    then nearer the mirror than a whole line, and a tolerance invented on top of
    an unmeasured layout is the failure the measurement is there to avoid.
    """
    return _page_pitch(lines, counterpart_x) / 8.0


def _mirrored_line(lines: dict, page: int, y: float, counterpart_x: float,
                   tol: float) -> tuple | None:
    """The printed heading line nearest the mirrored y, when one is close.

    A heading the table centres on its number mirrors about that number: the
    line a row owns at one end has a printed line at the other, the same
    distance away. The mirror is only trusted when a printed line stands within
    `tol` of it (`_mirror_tol`: an eighth of this layout's own line), because
    a mirror off by a line is a whole line out.
    """
    if tol <= 0.0:
        return None
    best = None
    for key in lines:
        if key[0] != page or _line_title_x1(lines[key], counterpart_x) is None:
            continue
        distance = abs(key[1] - y)
        if best is None or distance < best[0]:
            best = (distance, key)
    if best is None or best[0] > tol:
        return None
    return best[1]


def _first_title_key(record: dict, lines: dict,
                     counterpart_x: float) -> tuple | None:
    """The row's own first heading line: its highest line in the title column."""
    keys = [key for key in record["keys"]
            if _line_title_x1(lines[key], counterpart_x) is not None]
    return min(keys) if keys else None


def _page_cut(record: dict, run: list, lines: dict) -> bool:
    """Did the page break this row's cell in two?

    A row whose heading runs to the last line of its page continues on the next
    page, so nothing the table prints stands below the last line the row has on
    its own page - counting the run of unread lines above the next number,
    which holds that row's own tail when the run began before the break. Such a
    row is measured from the other side - see `_heading_run_split` - because
    its own mirror falls on the page before and cannot see the rest of the run.
    """
    page = record["anchor"].page
    own = [key for key in list(record["keys"]) + list(run) if key[0] == page]
    if not own:
        return False
    last = max(own)[1]
    return not any(key[0] == page and key[1] > last + 0.5 for key in lines)


def _heading_run_split(record: dict, run: list, block: list, lines: dict,
                       counterpart_x: float, anchor) -> int | None:
    """How many of a run's leading lines still belong to the row above.

    Egypt prints each row's heading centred on its own number, so a row's first
    heading line mirrors about the number onto its last: the run of lines above
    the next number is cut at that mirror, the row above keeps its own tail,
    and what is left of the run is the head of the next row's heading - the
    heading printed above its own number, which reading as the row above's tail
    opened Egypt's rows mid-sentence.

    A row the page break cut in two has no mirror on this page to measure the
    run with (its own first and last lines are on the page before), so the run
    is measured from the other side: the lines still unread are offered to the
    next number in turn, starting with the run's own, and the first that mirrors
    a printed line about that number is the next row's own first line. That
    line can already sit in the next row's own block rather than in the run, in
    which case none of the run is the row above's tail. `None` is returned when
    neither side can measure the run, and the caller then reads it as it did
    before.
    """
    first = _first_title_key(record, lines, counterpart_x)
    if first is None or not run or run[0][0] < first[0]:
        return None
    if run[0][0] > first[0] and not _page_cut(record, run, lines):
        # The row above finished its heading on the page its number is on, so
        # none of the run is its tail.
        return 0
    mirror = 2.0 * record["anchor"].y - first[1]
    tol = _mirror_tol(lines, counterpart_x)
    keeps = 0
    while (keeps < len(run) and run[keeps][0] == first[0]
           and run[keeps][1] <= mirror + tol):
        keeps += 1
    rest = run[keeps:]
    if (not rest or rest[0][0] == first[0]
            or not _page_cut(record, run, lines)):
        # Nothing of the run stands on a later page than the row above's own
        # lines, or the row above's own page holds lines below its last one:
        # the run ends where the row above's mirror leaves it.
        return keeps
    # The row above's cell ran to the page break and went on over it: what it
    # owns of the new page cannot be measured from its own page, so the run is
    # measured from this number instead, at the first line that mirrors a
    # printed line about it. That line can already stand in this number's own
    # block rather than in the run, and then none of the run is the row above's
    # tail.
    own = (anchor.page, round(anchor.y, 1))
    for offset, key in enumerate(rest):
        if key[0] != anchor.page or key >= own:
            break
        if _mirrored_line(lines, anchor.page, 2.0 * anchor.y - key[1],
                          counterpart_x, tol) is not None:
            return keeps + offset
    for key in sorted(block):
        if key[0] < anchor.page:
            continue
        if key[0] != anchor.page or key >= own:
            break
        if _mirrored_line(lines, anchor.page, 2.0 * anchor.y - key[1],
                          counterpart_x, tol) is not None:
            return keeps
    # Neither the run nor the next row's own block names that row's first line.
    # What the row above owns of its own page is still measured - its mirror is
    # on that page - so that much is kept; when the run gave it nothing of its
    # own page, neither side has measured the run and the caller reads it as it
    # did before.
    return keeps or None


def _heading_lead(blocks: list) -> float:
    """Half of this layout's own line spacing, measured from its own lines.

    The habit test below asks whether a row's block opens a whole heading line
    above its number, and    the line it counts is the layout's own, not a shared
    constant: every table sets its lines at its own spacing - 13.4pt on egypt's
    page, 12.8 on indonesia's, 10.3 on israel's - and half a line is what tells a
    heading line from the baseline the number is printed on. So the lead is
    measured from the gaps between consecutive lines of the anchored groups
    themselves, the same groups the vote is taken over, and no promotion has to
    be measured by hand when a table with a different leading arrives. The two
    tolerances the reader takes on the same quantity (`_block_ragged_slack`,
    `_mirror_tol`) read it from the page's columns instead (`_page_pitch`),
    because they are about the whitespace between printed lines rather than
    about the groups this vote is taken over.


    A grouping whose lines never share a page holds no spacing this can read and
    returns 0.0. No line then stands above a number, and the vote reads the
    layout as opening on its numbers' own lines rather than pretending a
    leading it cannot see.
    """
    gaps = sorted(later[1] - earlier[1]
                  for group in blocks
                  for earlier, later in zip(group, group[1:])
                  if earlier[0] == later[0] and later[1] > earlier[1])
    return gaps[len(gaps) // 2] / 2.0 if gaps else 0.0


def _numbers_inside_their_heading(blocks: list, anchors: list) -> bool:
    """Does this table print its numbers inside their heading?

    A table whose number stands at the head of its row opens each row's block
    on the number line itself, so a row's first printed line is its number
    (israel, algeria, sweden: their groups open a tenth of a point above the
    number - one baseline, rounded). A table that prints the number in the
    middle of the heading starts the block a whole heading line above it (egypt,
    indonesia, ukraine). The habit is read from the anchored groups the grouping
    produced, and it decides one thing only: whether the run of lines above a
    number is that number's own heading rather than the row above's tail. Only a
    group that opens more than half its layout's own line (`_heading_lead`) above
    its number is opening above the number's own line, and a layout whose leading
    cannot be measured is read as opening on the number's own line.
    """
    anchor_keys = {(anchor.page, round(anchor.y, 1)) for anchor in anchors}
    lead = _heading_lead(blocks)
    starts = []
    for group in blocks:
        holder = next((key for key in group if key in anchor_keys), None)
        if holder is None:
            continue
        starts.append(lead > 0.0 and holder[1] - group[0][1] > lead)
    return bool(starts) and sum(starts) * 2 > len(starts)


def _rehome_page_cut_heads(row_blocks: list[dict], lines: dict,
                           counterpart_x: float) -> None:
    """Give back the head of a row the page cut in two.

    A row whose heading runs to the last line of its page continues on the
    next one, and the lines that continue it stand above the following row's
    number. That continuation is not centred on its own number - the number is
    on the page before - so the centring rule cannot measure it, and it is
    measured from the other side instead: the following row's own heading is
    centred on its number, so the lines it owns above the number are as many as
    the lines it owns below the number. What the row owns below is known by
    now (its own group's lines and the run that followed it), so the lines it
    owns above are known too, and any further line above the number is the
    previous row's continuation.
    """
    last_on_page: dict[int, float] = {}
    for page, y in lines:
        last_on_page[page] = max(last_on_page.get(page, y), y)
    for index in range(1, len(row_blocks)):
        previous, record = row_blocks[index - 1], row_blocks[index]
        anchor = record["anchor"]
        cut = (previous["keys"] and previous["keys"][-1][0] != previous["anchor"].page)
        if not cut:
            continue
        above, below = _heading_line_counts(record, lines, counterpart_x)
        head = [key for key in record["keys"]
                if key < (anchor.page, round(anchor.y, 1))]
        own_above = above - len(head)
        want_head = below - own_above
        if want_head < 0 or want_head >= len(head):
            continue
        moved = set(head[:len(head) - want_head])
        record["keys"] = [key for key in record["keys"] if key not in moved]
        previous["keys"].extend(sorted(moved))


def _read_block_covered(book, table: list, anchors: list, title_x: float,
                        counterpart_column: list, dates: list,
                        signature_x: float, force_x: float,
                        split_dates_by_text: bool) -> tuple:
    """Read the table as title blocks keyed by the number printed inside them.

    On the tables whose numbering has a gap both established readers miss: a
    title cell whose last line is nearly full hides the next row's start, and a
    number printed inside its row's title block is not at the block's top. This
    reader groups the table's lines into blocks separated by ragged (short)
    lines - the one thing every printer of these tables does - keys each block
    by the number printed inside it, and cuts a block that holds two numbers at
    the line whose right edge drops most. The caller accepts the reading only
    if it accounts for every printed number; otherwise the caller falls back to
    the legacy reader, whose account is published as it stands.
    """
    columns = _block_columns(table, anchors, title_x, counterpart_column,
                             dates, signature_x, force_x)
    counterpart_x = columns[2][1]
    instrument_x = next((x for name, x in columns if name == "instrument"), None)
    counterpart_band_right = (instrument_x if instrument_x is not None
                              else signature_x)
    counterpart_right = _counterparty_right_edge(
        table, counterpart_x, counterpart_band_right)
    lines = _block_page_lines(table)
    header_lines = _block_header_lines(table, anchors)
    anchor_lines = {(anchor.page, round(anchor.y, 1)): anchor
                    for anchor in anchors}
    data_lines = {key: value for key, value in lines.items()
                  if key not in header_lines}
    groups = _block_groups(data_lines, counterpart_x, anchor_lines)
    # The reach decisions this reading makes, kept so that the interval the
    # table's own runs leave for the reach can be published with the rows it
    # decided (`_pos_attach_reach_band`). The module function is called directly
    # inside, not captured, so an audit that replaces it still sees every call.
    reach_pairs: list = []

    def _reaches(pending_last, next_anchor) -> bool:
        took = _absorbs_prefix(pending_last, next_anchor)
        if pending_last[0] == next_anchor.page:
            reach_pairs.append((next_anchor.y - pending_last[1], bool(took)))
        return took

    row_blocks: list[dict] = []
    pending: list[tuple[int, float]] = []
    inside_heading = _numbers_inside_their_heading(groups, anchors)
    for block in groups:
        first, last = block[0], block[-1]
        inside = sorted(
            (anchor for (page, y), anchor in anchor_lines.items()
             if (first[0], first[1] - 0.6) <= (page, y)
             <= (last[0], last[1] + 0.6)),
            key=lambda anchor: (anchor.page, anchor.y))
        if not inside:
            pending.extend(block)
            continue
        # A cell-only prefix well above a number normally continues the prior
        # row: Senegal's (c) Avenant is 51pt above row 3, whose title starts on
        # the number line. But when a title begins immediately after a prefix,
        # that cell lead-in belongs to the new row (Indonesia's Canada Original
        # dates precede its title by 7pt). Keep an adjacent lead-in together;
        # move a more distant prefix to the preceding row.
        title_leads = [key for key in block
                       if block[0] < key
                       < (inside[0].page,
                          inside[0].y - (POS_ATTACH_REACH_PT))
                       and any(columns[1][1] - 2.0 <= span.x < counterpart_x - 1.0
                               and any(char.isalpha() for char in span.text)
                               for span in lines[key])]
        title_lead = min(title_leads) if title_leads else None
        cell_prefix: list[tuple[int, float]] = []
        while (block and row_blocks
               and block[0] < (inside[0].page,
                               inside[0].y - (POS_ATTACH_REACH_PT))
               and not any(span.x < counterpart_x - 1.0
                           and any(char.isalpha() for char in span.text)
                           for span in lines[block[0]])
               and not (title_lead is not None
                        and title_lead[0] == block[0][0]
                        and title_lead[1] - block[0][1] <= POS_ATTACH_REACH_PT)):
            cell_prefix.append(block.pop(0))
        if cell_prefix:
            row_blocks[-1]["keys"].extend(cell_prefix)
        prefix: list[tuple[int, float]] = []
        if pending:
            next_anchor = inside[0]
            pending_last = pending[-1]
            distance = next_anchor.y - pending_last[1]
            # A bilingual table clings a run of the row's own language to the
            # number even when it stands well above it: Egypt's English heading
            # opens four lines over its number while the row above is Arabic,
            # and reading the run as the Arabic row's tail mixed the two
            # languages in one title. A run whose script is this block's and
            # not the row above's belongs to this row, far above or not.
            pending_script = _keys_script(pending, lines, counterpart_x)
            block_script = _keys_script(block, lines, counterpart_x)
            previous_script = (_keys_script(row_blocks[-1]["keys"], lines,
                                            counterpart_x)
                               if row_blocks else None)
            opens_here = (pending_script is not None
                          and pending_script == block_script
                          and previous_script is not None
                          and pending_script != previous_script)
            keeps = (_heading_run_split(row_blocks[-1], pending, block, lines,
                                        counterpart_x, next_anchor)
                     if inside_heading and row_blocks else None)
            if _reaches(pending_last, next_anchor):
                prefix, pending = pending, []
            elif opens_here:
                prefix, pending = pending, []
            elif keeps is not None:
                # The row above prints its number inside its heading, and its
                # own heading mirrors about that number. The run is cut at the
                # mirror: what the row above still owns is its tail, and the
                # rest of the run is the heading of this number.
                row_blocks[-1]["keys"].extend(pending[:keeps])
                prefix, pending = pending[keeps:], []
            elif inside_heading:
                prefix, pending = pending, []
            elif row_blocks:
                row_blocks[-1]["keys"].extend(pending)
                pending = []
            else:
                pending = []
        if len(inside) == 1:
            anchor_key = (inside[0].page, round(inside[0].y, 1))
            own = [key for key in block
                   if _line_title_x1(lines[key], counterpart_x) is not None]
            row_blocks.append({"anchor": inside[0],
                               "own_above": sum(1 for key in own
                                                if key < anchor_key),
                               "own_below": sum(1 for key in own
                                                if key > anchor_key),
                               "keys": prefix + list(block)})
            continue
        starts = [block[0]]
        for earlier, later in zip(inside, inside[1:]):
            starts.append(
                _block_split_mirror(lines, block, earlier, later,
                                    counterpart_x, starts[-1])
                if inside_heading
                else _block_split(lines, block, earlier, later,
                                  counterpart_x))
        for index, anchor in enumerate(inside):
            end = starts[index + 1] if index + 1 < len(starts) else None
            body = [key for key in block
                    if (key[0], key[1]) >= starts[index]
                    and (end is None or (key[0], key[1]) < end)]
            anchor_key = (anchor.page, round(anchor.y, 1))
            row_blocks.append({
                "anchor": anchor,
                "own_above": sum(1 for key in body
                                 if key < anchor_key
                                 and _line_title_x1(lines[key],
                                                    counterpart_x) is not None),
                "own_below": sum(1 for key in body
                                 if key > anchor_key
                                 and _line_title_x1(lines[key],
                                                    counterpart_x) is not None),
                "keys": prefix + body if index == 0 else body})
    if pending and row_blocks:
        row_blocks[-1]["keys"].extend(pending)

    _rehome_page_cut_heads(row_blocks, lines, counterpart_x)
    _rehome_block_leads(row_blocks, lines, counterpart_x, counterpart_band_right)
    rows: dict = {}
    order: list = []
    anchor_ids = {id(anchor) for anchor in anchors}
    for record in row_blocks:
        anchor = record["anchor"]
        number = int(NUMBER_RE.match(anchor.text.strip()).group(1))
        existing = _row(rows, order, number, anchor)
        spans = [span for key in record["keys"] for span in lines[key]]
        for span in sorted(spans, key=lambda s: (s.page, s.y, s.x)):
            if span is anchor:
                rest = NUMBER_RE.sub("", span.text.strip(), count=1).strip()
                if rest:
                    cut = _split_span_at(span, rest, counterpart_x)
                    if cut is None:
                        existing["cells"].setdefault("title", []).append(
                            replace(span, text=rest))
                    else:
                        left, right, right_x = cut
                        existing["cells"].setdefault("title", []).append(
                            replace(span, text=left))
                        for name, printed in _dated_cells(
                                replace(span, text=right, x=right_x),
                                columns, split_dates_by_text):
                            existing["cells"].setdefault(name, []).append(
                                printed)
                continue
            if id(span) in anchor_ids:
                continue
            if (span.page, round(span.y, 1)) in header_lines:
                continue
            if (span.page, round(span.y, 1)) == (anchor.page,
                                                 round(anchor.y, 1)) \
                    and NUMBER_RE.match(span.text.strip()) \
                    and span.x < anchor.x:
                continue
            pieces = [span]
            if columns[1][1] - 2.0 <= span.x < counterpart_x - 0.75 \
                    <= span.x1:
                # A title run whose words cross into the counterparty column:
                # the counterparty printed on the title's first line and
                # merged into the same span. Cut at the column edge so the
                # counterparty cell keeps its own word (norway's row 24,
                # viet-nam's row 21). Footnote runs left of the title column
                # do not qualify: their x starts before the title's.
                cut = _split_span_at(span, span.text, counterpart_x)
                if cut is not None:
                    left, right, right_x = cut
                    pieces = [replace(span, text=left),
                              replace(span, text=right, x=right_x)]
            if instrument_x is not None and span.x <= counterpart_right:
                # A counterparty and its instrument label printed close enough
                # to arrive as one span (mexico's row 39 `New Zealand
                # Original`, viet-nam's rows 36, 42, ...): cut at the measured
                # instrument column, the same way the title|counterparty cut
                # above does, so the label lands in the instrument cell rather
                # than in the counterparty's.
                split_pieces = []
                for piece in pieces:
                    cut = (_split_span_at(piece, piece.text, instrument_x)
                           if piece.x1 >= instrument_x else None)
                    if cut is None:
                        split_pieces.append(piece)
                        continue
                    left, right, right_x = cut
                    if not INSTRUMENT_LABEL_RE.match(right):
                        # The words right of the instrument column are not an
                        # instrument label: this is one cell's own text
                        # crossing the column's edge (georgia's "Grand Duchy
                        # of Luxembourg", norway's title run), and cutting it
                        # there would invent a label the source does not print.
                        split_pieces.append(piece)
                        continue
                    split_pieces.append(replace(piece, text=left))
                    split_pieces.append(replace(piece, text=right, x=right_x))
                pieces = split_pieces
            for piece in pieces:
                for name, printed in _dated_cells(
                        piece, columns, split_dates_by_text,
                        chooser=lambda candidate: _block_column_of(
                            candidate, columns, counterpart_right)):
                    existing["cells"].setdefault(name, []).append(printed)

    out = []
    for number in order:
        record = rows[number]
        row = {"no": number, "page": record["page"]}
        for name, _x in columns:
            if name == "no":
                continue
            value = _words(sorted(record["cells"].get(name, []),
                                  key=lambda span: (span.page, round(span.y, 1),
                                                    span.x)), book)
            if value:
                row[name] = value
        row["instruments"] = _instruments(record["cells"], book)
        out.append(row)
    numbers = sorted(rows)
    qa = {
        "read": True,
        "columns": {name: round(x, 1) for name, x in columns},
        "numbering": {"first": numbers[0] if numbers else None,
                      "last": numbers[-1] if numbers else None,
                      "rows": len(order),
                      "runs_from_one_without_a_gap":
                          numbers == list(range(1, len(numbers) + 1))},
        "rows_delimited_by": ("title blocks separated by ragged lines, each "
                              "keyed by the number printed inside it"),
        "numbered_rows_without_a_number": [],
        "numbers_with_no_row": [n for n in range(1, numbers[-1] + 1)
                                if n not in rows] if numbers else [],
        "printed_number_anchors": [
            int(NUMBER_RE.match(anchor.text.strip()).group(1))
            for anchor in sorted(anchors, key=lambda item: (item.page, item.y))],
        # The block reader's own reach, not the number-first window: this reader
        # places a run of lines by how far above a number it may stand, and that
        # is the tolerance its rows were decided with. The window is a different
        # decision on different layouts, and the artefacts those layouts publish
        # record it - see `_read_legacy_covered`'s `qa`.
        "row_attach_pt": POS_ATTACH_REACH_PT, "span_tol_pt": CELL_TOL_PT,
        # The interval this table's own printed runs leave for the reach above -
        # the deepest run this reading absorbed and the shallowest it refused -
        # so the room the tolerance has on this layout travels with the rows it
        # decided, and a repair that moves one of those runs is named by the
        # drift control instead of only by the invariant's own measurement. A
        # reading that leaves one side of the decision empty carries `[]`.
        "row_attach_band_pt": _rounded_band(
            _pos_attach_reach_band(reach_pairs)),
        "date_columns": (
            "one x: the two date columns are printed close enough that their "
            "cells arrive as one span, and a cell with two dates is split by "
            "the table's own column order" if split_dates_by_text else
            "two x: the signature and the entry into force are separated by "
            "where the table prints them"),
        "dated_cells_split_by_text": (
            sum(len(record["cells"].get("entry_into_force", []))
                for record in rows.values()) if split_dates_by_text else 0),
        "spans_that_fitted_no_column": [],
        "note": (
            "The title-cell reader cannot see this table's row boundaries: its "
            "cells hold more than one printed number, or a printed number opens "
            "no cell. This reading groups the table's lines into blocks "
            "separated by ragged (short) lines and keys each block by the "
            "number printed inside it, so every printed number opens its own "
            "row. A run of lines printed above a number is absorbed as that "
            "row's own prefix within `row_attach_pt` of the number it opens, "
            "which is this reader's own reach and the tolerance its rows were "
            "decided with, and `row_attach_band_pt` is the interval this "
            "table's own printed runs leave that reach: the declared value lies "
            "in it, a run printed at its lower edge is absorbed up and one "
            "printed at its upper edge would be, and a reading that leaves one "
            "side of that decision empty carries an empty interval. This "
            "reading was accepted only because it accounts for every number "
            "the table prints."),
    }
    return out, qa


def _rehome_block_leads(row_blocks: list, lines: dict, counterpart_x: float,
                        counterpart_right: float) -> None:
    """Give a block's far-above lead-in back to the row it belongs to.

    A layout whose rows print their number at the head of the row - the number
    line opens the block, as algeria, israel and sweden do - can still print
    the last line of one row's wrapped title without the ragged drop that
    would separate it. The extractor's own line widths fall a tenth of a point
    on either side of the modal edge (algeria's Arabic decree lines measure
    263.96 and 264.05 against a modal edge of 267.0, far inside the quarter of a
    line `_block_ragged_slack` allows), so the row boundary hides; the block
    then opens above its own number and carries the neighbouring row's last
    line as the head of its title.

    The row's own summary line is the boundary, and every row prints one: the
    line that names the counterparty. Everything above it in the same block
    belongs to the row before - which is why the lead-in is handed back only
    while it sits at or below the previous row's own number, so the two printed
    numbers still bound the move and no line is taken from a page the previous
    row never reached. The counterparty can be printed on a line of its own
    just above the number (israel's rows name it one line up), so the start
    steps back over the tightly-set lines that share the summary line's own
    baseline. A layout that prints its numbers inside the title (indonesia,
    czechia and ukraine: every block opens above its number) is rejected by
    its habit test before the move runs, and a block whose own counterparty
    entry is not on a line of its own falls back to handing back only the
    title text above the attach window.
    """
    if not row_blocks:
        return
    gaps = [record["anchor"].y - record["keys"][0][1]
            for record in row_blocks if record["keys"]]
    at_head = sum(1 for gap in gaps if gap <= POS_ATTACH_REACH_PT)
    if not gaps or at_head * 2 <= len(gaps):
        return

    def carries_counterparty(key) -> bool:
        return any(counterpart_x - 1.0 <= span.x < counterpart_right - 1.0
                   and any(character.isalpha() for character in span.text)
                   for span in lines[key])

    def is_title_only(key) -> bool:
        return not any(span.x >= counterpart_x - 1.0
                       or DATED_CELL_RE.match(span.text.strip())
                       for span in lines[key])

    def beyond_attach(key, anchor) -> bool:
        # A line on a page before the anchor's is never part of the anchor's
        # row head: the row's own first line is printed on its own page (sweden
        # row 32's last line closes page 5 over row 33's number on page 6).
        if key[0] != anchor.page:
            return key[0] < anchor.page
        return anchor.y - key[1] > POS_ATTACH_REACH_PT

    for index in range(1, len(row_blocks)):
        record = row_blocks[index]
        previous = row_blocks[index - 1]
        anchor = record["anchor"]
        floor = (previous["anchor"].page, previous["anchor"].y)
        keys = record["keys"]
        start = None
        for position, key in enumerate(keys):
            if carries_counterparty(key):
                start = position
                # Step back over the lines that share the summary line's own
                # baseline: a counterparty is printed on its own line a point
                # above the title's first line (israel's `Romania`), and both
                # open the row.
                while (start > 0 and keys[start][0] == keys[start - 1][0]
                       and 0.0 <= keys[start][1] - keys[start - 1][1] <= 2.5):
                    start -= 1
                break
        if start is None:
            moved = []
            while (keys and beyond_attach(keys[0], anchor)
                   and keys[0] >= floor and is_title_only(keys[0])):
                moved.append(keys.pop(0))
        else:
            # The row's own first line can sit within the attach window just
            # above its number (israel's `Convention between the Government
            # of`), so the move stops at the window: only the title lines
            # beyond it are the previous row's.
            count = 0
            while (count < start and beyond_attach(keys[count], anchor)
                   and keys[count] >= floor):
                count += 1
            moved = keys[:count]
            del keys[:count]
        if moved:
            previous["keys"].extend(moved)


def _block_read_complete(rows: list, qa: dict, anchors: list) -> bool:
    """The block reading emits exactly one row per printed number anchor.

    A genuine number absent from the printed run (papua-new-guinea's row 5)
    remains missing from both the anchor list and the emitted rows, and the QA
    declaration lists it as a gap; this reader must not invent it or reject an
    otherwise faithful row set merely because the source itself has a gap.
    """
    emitted = [row["no"] for row in rows]
    printed = [int(NUMBER_RE.match(anchor.text.strip()).group(1))
               for anchor in anchors]
    return bool(rows) and len(emitted) == len(set(emitted)) \
        and sorted(emitted) == sorted(printed)


def _title_cells(table: list, title_x: float, counterpart_x: float,
                 title_right: float) -> tuple:
    title = [span for span in table if title_x - 1.0 <= span.x < counterpart_x - 1.0]
    lines: dict = {}
    for span in title:
        lines.setdefault((span.page, round(span.y, 1)), []).append(span)
    order = sorted(lines)
    if not order:
        return [], 0.0
    reaching = sum(1 for key in order
                   if max(span.x1 for span in lines[key]) >= title_right - JUSTIFY_SLACK_PT)
    starts = [key for position, key in enumerate(order)
              if position == 0
              or max(span.x1 for span in lines[order[position - 1]])
              < title_right - JUSTIFY_SLACK_PT]
    return starts, reaching / len(order)


def _row(rows: dict, order: list, number: int, anchor) -> dict:
    record = rows.get(number)
    if record is None:
        record = {"no": number, "page": anchor.page, "cells": {}}
        rows[number] = record
        order.append(number)
    return record


def _centre(cluster: list) -> float:
    return round(sum(cluster) / len(cluster), 1)


def _in_column(x: float, cluster: list) -> bool:
    return cluster[0] - 0.5 <= x <= cluster[-1] + 0.5


def _x_clusters(values: list, tol: float = 1.5) -> list:
    out: list = []
    for value in sorted(values):
        if out and value - out[-1][-1] <= tol:
            out[-1].append(value)
        else:
            out.append([value])
    return out


def _number_column(table: list, title_x: float) -> tuple:
    """Find the right-aligned number column and its consecutive 1,2,3... run."""
    candidates = [span for span in table
                  if span.x < title_x and NUMBER_RE.match(span.text.strip())
                  and int(NUMBER_RE.match(span.text.strip()).group(1)) > 0]
    best: tuple = ([], 0)
    for cluster in _x_clusters([round(span.x, 1) for span in candidates],
                               tol=RAGGED_COLUMN_TOL_PT):
        members = [span for span in candidates if _in_column(span.x, cluster)]
        values = {int(NUMBER_RE.match(span.text.strip()).group(1)) for span in members}
        run = 0
        while run + 1 in values:
            run += 1
        if run > best[1]:
            best = (members, run)
    return best


def _title_column_after_numbers(spans: list, anchors: list, high: float):
    """Measure the first repeated title x strictly to the right of the number run."""
    if len(anchors) < 2:
        return None
    number_right = max(span.x for span in anchors)
    anchor_ids = {id(span) for span in anchors}
    by_x: dict[float, set[tuple[int, float]]] = defaultdict(set)
    for span in spans:
        if id(span) in anchor_ids or not number_right + 5.0 < span.x < high:
            continue
        if not any(character.isalpha() for character in span.text):
            continue
        by_x[round(span.x, 1)].add((span.page, round(span.y, 1)))
    repeated = [x for x, rows in by_x.items() if len(rows) >= 2]
    return min(repeated) if repeated else None


def _leftmost_column(table: list, low: float, high: float):
    counts = Counter(round(span.x, 1) for span in table
                     if low <= span.x < high
                     and any(character.isalpha() for character in span.text))
    clusters = _x_clusters([x for x, hits in counts.items() if hits >= 3])
    return clusters[0] if clusters else None


def _measured_column_after(spans: list, low: float, high: float):
    """The x band a text column occupies between `low` and `high`.

    A column's words do not all start at the same x: a name set one word longer
    begins a little further right, and the column is still one column. The band
    is measured with the number column's own tolerance, so a ragged start stays
    one cluster, and the first and last printed x are returned - the two edges
    the table prints, rather than an average of them. `None` when no column of
    words stands in the range.
    """
    starts = sorted(round(span.x, 1) for span in spans
                    if low <= span.x < high
                    and any(character.isalpha() for character in span.text))
    for cluster in _x_clusters(starts, tol=RAGGED_COLUMN_TOL_PT):
        if len(cluster) >= 2:
            return cluster
    return None


def _table_start(spans: list, title_x: float) -> tuple:
    """Start at the first row number, keeping the repeated headings out of data."""
    first_title = min((span for span in spans if abs(span.x - title_x) <= 1.0),
                      key=lambda span: (span.page, span.y), default=None)
    numbered = [span for span in spans
                if span.x < title_x and NUMBER_RE.match(span.text.strip())]
    first_number = min(numbered, key=lambda span: (span.page, span.y), default=None)
    if first_title is None and first_number is None:
        return (0, 0.0)
    if first_title is None:
        return first_number.page, first_number.y
    if first_number is None:
        return first_title.page, first_title.y
    return min((first_title.page, first_title.y), (first_number.page, first_number.y))


def _row_of(span, anchors: list):
    """Place a span with the row whose number is the last one above it.

    A cell within POS_ATTACH_PT above a row's number belongs to that row - the
    lead-in a number printed at the foot of the cell it names needs. Otherwise
    the span belongs to the last number above it on the same page, and that is
    where the two edge cases are decided rather than guessed:

    * a span above the first number of a later page has no number above it on
      that page, and belongs to no row of it - reading it as the page's first
      row makes that row swallow the tail of the row before it;
    * the document's own first row is the exception, because nothing precedes
      it and its title is printed above its number.
    """
    return _row_of_placement(span, anchors)[0]


def _row_of_placement(span, anchors: list) -> tuple:
    """The same placement, with the rule that made it named.

    `_row_of` answers where a span goes; this answers *why*, which is what lets
    the window's own band be measured (`_pos_attach_band`). The names are the
    rules of `_row_of`'s docstring: "lead-in" for a span within `POS_ATTACH_PT`
    above the number below it, "tail" for one left with the number above,
    "first-row" for the document's own first row, whose title the printer
    centred over its number, "outside" for a span above a page's first number
    with no row of that page to belong to, and "off-page" for a span on a page
    the table prints no number on. The placement itself is unchanged, and
    `_row_of` returns its first half.
    """
    page_anchors = [anchor for anchor in anchors if anchor.page == span.page]
    if not page_anchors:
        return None, "off-page"
    previous = None
    for anchor in page_anchors:
        if span.y < anchor.y:
            if anchor.y - span.y <= POS_ATTACH_PT:
                return anchor, "lead-in"
            if previous is not None:
                return previous, "tail"
            if anchor is anchors[0]:
                return anchor, "first-row"
            return None, "outside"
        previous = anchor
    return previous, "tail"


def _pos_attach_band(placements: list) -> tuple:
    """The interval one table's own printed spans leave for `POS_ATTACH_PT`.

    `placements` are the `(span, anchors)` pairs the reader's placement was asked
    about (`_row_of`), so both populations are read off the reading and not
    guessed at: the lead-ins the window captured up to the number below them,
    and the tails it left with the number above. The furthest a lead-in stands
    above its number is the deepest the window may be smaller than, or the row it
    names would lose the lead-in a number printed at the foot of its cell needs;
    and the nearest a tail stands above the number below it is the shallowest the
    window may be larger than, or that tail would be taken out of the row the
    page prints it in. Every window between the two places every span as the
    reading does, and both edges are distances the table prints.

    The interval is half-open for the same reason it is in the signatories
    reader: the comparison is `<=`, so a span printed exactly at the lower edge
    is captured up and one printed exactly at the upper edge would be too.

    A layout whose placement leaves one side empty has no band, and `()` is
    returned rather than an interval nothing bounds.
    """
    lead_ins = []
    tails = []
    for span, anchors in placements:
        anchor, how = _row_of_placement(span, anchors)
        if anchor is None or how not in ("lead-in", "tail"):
            continue
        below = next((item for item in anchors
                      if item.page == span.page and item.y > span.y), None)
        if below is None:
            continue
        gap = below.y - span.y
        (lead_ins if how == "lead-in" else tails).append(gap)
    if not lead_ins or not tails:
        return ()
    return max(lead_ins), min(tails)


def _absorbs_prefix(pending_last, next_anchor) -> bool:
    """Does a run of lines printed above a number reach that number?

    The block reader absorbs such a run as the row's own prefix only within
    `POS_ATTACH_REACH_PT` of the number it opens - the reach, which is this
    reader's own tolerance and not the number-first window, because what it
    decides is how far a whole run may stand above the number that opens below
    it. The run has to be on the number's own page: a run left over from the
    page before is not near it whatever the distance says. Factored out as the
    comparison it is, so that the reach is named once and the band the page
    leaves for it can be measured off the reader's own answers
    (`_pos_attach_reach_band`).
    """
    return (pending_last[0] == next_anchor.page
            and 0.0 <= next_anchor.y - pending_last[1]
            <= POS_ATTACH_REACH_PT)


def _rounded_band(band: tuple) -> list:
    """A measured interval as the artefacts publish it: two rounded points.

    The artefacts record their printed distances to the hundredth of a point,
    and a band is a pair of such distances, so it is published the same way. The
    exact edges are the invariant's - `.verify/probe_number_first_band.py` and
    `.verify/probe_attach_reach_band.py` print them - and what the data carries
    is what a reader of the data can rebuild the tolerance from and what the
    drift control compares, path by path, against a fresh reading. An interval
    with no measured side is published as `[]` rather than as a pair of zeros,
    which would be a band no page printed.
    """
    if not band:
        return []
    return [round(band[0], 2), round(band[1], 2)]


def _pos_attach_reach_band(pairs: list) -> tuple:
    """The interval one layout's printed runs leave for the reach.

    `pairs` are the `(distance, absorbed)` the reader's own reach decision was
    asked about (`_absorbs_prefix`), the distance being from the last line of a
    run above a number to that number. The deepest run the reader absorbed is
    the deepest the reach may be smaller than, or a row would lose the prefix the
    table prints above its number; the shallowest run it refused is the shallowest
    the reach may be larger than, or a run the page prints above the number would
    be taken into it. Both are distances the table prints, and the band returned
    is the one `POS_ATTACH_REACH_PT` itself has to sit in: the reader compares
    the distance with that constant and nothing else, so the number the band
    holds is the declared one and no slack is taken off here.

    A run whose last line is *below* the number is refused by the reader for a
    reason the distance does not express, so only runs printed above it count
    towards the upper edge. The interval is half-open, as the signatories
    window's is: the comparison is `<=`, so a run printed exactly at the lower
    edge is absorbed and one printed exactly at the upper edge would be too.
    """
    absorbed = [distance for distance, took in pairs if took]
    refused = [distance for distance, took in pairs
               if not took and distance > 0.0]
    if not absorbed or not refused:
        return ()
    return max(absorbed), min(refused)


def _split_span_at(span, text: str, edge: float) -> tuple | None:
    """Cut `text` at the word nearest `edge`: (left, right, right_x).

    The extractor merges words that sit closer than its gap tolerance, so a
    counterparty printed on the same line as its title's first line arrives as
    one span whose x says "title" while its words cross into the counterparty
    column. The span carries no word coordinates, so the cut is estimated by
    proportion along the span's width and snapped to the nearest space - which
    for a column boundary is the space the printer left before the next
    column's text. None means the edge does not fall inside the span, or there
    is no word boundary to cut at.
    """
    width = span.x1 - span.x
    cut = (edge - span.x) / width if width > 0.0 else -1.0
    if not 0.0 < cut < 1.0:
        return None
    index = min(max(round(cut * len(text)), 0), len(text))
    before = text.rfind(" ", 0, index + 1)
    after = text.find(" ", index)
    candidates = [position for position in (before, after)
                  if 0 < position < len(text) - 1]
    if not candidates:
        return None
    position = min(candidates, key=lambda candidate: abs(candidate - index))
    # The right piece is the text that crosses the edge: it starts at the
    # edge's own column, which is where the printer put it.
    right_x = edge
    return text[:position], text[position + 1:], right_x


def _dated_cells(span, columns: list, merged: bool, chooser=None) -> list:
    names = [name for name, _x in columns if name in ("signature", "entry_into_force")]
    parts = span.text.strip().split()
    if len(parts) == 2 and all(DATE_RE.match(part) for part in parts):
        return [(names[0], replace(span, text=parts[0])),
                (names[1], replace(span, text=parts[1]))]
    if merged and DATED_CELL_RE.match(span.text.strip()):
        return [(names[0], span)]
    # A run that carries a date in one date column and a word in the other is
    # one span to the extractor but two cells on the page: Nigeria's
    # entry-into-force column prints `N/A` beside the signature date and the
    # two arrive as one span whose text is `06-11-2006 N/A`. Without this cut
    # the whole run lands in the signature cell and the force cell is left
    # empty - a word smeared into the cell beside the one it belongs to, and a
    # printed entry-into-force value dropped. The cut is at the measured
    # boundary between the two date columns, so the same shape reads a
    # signature `N/A` beside a force date correctly too.
    #
    # The word has to carry no digit at all. A run of two printed dates can
    # still hold one that DATE_RE does not match - italy's entry-into-force
    # `-19-11-2012` and seychelles' four-letter month `28-Sept-12` - and a
    # looser test would read those as the value word and split a date pair the
    # publisher meant to keep together.
    named = dict(columns)
    if (len(names) == 2 and set(names) <= set(named)
            and named[names[1]] - named[names[0]] > 1.0
            and len(parts) > 1
            and any(DATE_RE.match(part) for part in parts)
            and any(not any(character.isdigit() for character in part)
                    for part in parts)
            and named[names[0]] - 1.0 <= span.x < named[names[1]]
            and span.x1 >= named[names[1]] - 1.0):
        cut = _split_span_at(span, span.text.strip(), named[names[1]])
        if cut is not None and cut[0] and cut[1]:
            before, after, edge = cut
            return [(names[0], replace(span, text=before)),
                    (names[1], replace(span, text=after, x=edge))]
    column = _column_of(span.x, columns)
    found = [match.group(0).replace(" ", "")
             for match in PACKED_DATE_RE.finditer(span.text)]
    if found and PACKED_DATE_RE.sub("", span.text).strip() == "":
        # A cell whose text is nothing but dates belongs to the date columns
        # by its dates, not to whatever column its left edge falls in: a
        # packed cell renders a point or two left of the column the table
        # measures, and without this its dates land in the instrument or in
        # the wrong date column (lithuania's rows 3, 25, 34, 42, 51).
        starts = {name: abs(span.x - dict(columns)[name]) for name in names}
        if len(found) == 1:
            if column in names and starts[column] <= min(starts.values()):
                return [(column, replace(span, text=found[0]))]
            best = min(starts, key=starts.get)
            return [(best, replace(span, text=found[0]))]
        if len(found) == 2 and column not in names:
            # Two dates and no date column claimed the span: they were printed
            # in the table's own column order - signature first, force second.
            return [(names[0], replace(span, text=found[0])),
                    (names[1], replace(span, text=found[1]))]
        # More dates, or a date column already holds the span (two dates
        # printed as one run in the signature column): leave it as printed.
    return [((chooser(span) if chooser is not None else column), span)]


def _column_of(x: float, columns: list) -> str:
    ordered = sorted(columns, key=lambda column: column[1])
    chosen = ordered[0][0]
    for name, start in ordered:
        if x >= start - 0.75:
            chosen = name
    return chosen


def _block_column_of(span, columns: list, counterpart_right: float) -> str:
    """Assign a block-reader span, correcting the counterparty|instrument edge.

    The instrument labels are centre-aligned, so a longer label starts a few
    points left of the column's measured left edge and by its left edge alone
    would read as part of the counterparty (china's `Instrument (a)` starts
    8.5pt left of the instrument column, spain's `Instrument` 2pt left). A span
    printed to the right of the counterparty column's own printed right edge
    and centred inside the instrument column is the instrument's text. A span
    that starts inside the counterparty band is left alone here; if it carries
    an instrument label it is cut at the column edge before it reaches this
    function.
    """
    column = _column_of(span.x, columns)
    if column != "other_jurisdiction":
        return column
    instrument_x = next((x for name, x in columns if name == "instrument"), None)
    if instrument_x is None or span.x <= counterpart_right:
        return column
    if (span.x + span.x1) / 2.0 >= instrument_x:
        return "instrument"
    return column


def _words(parts: list, book) -> str:
    return " ".join(piece for piece in
                    (ledger._join_spans([part], book).strip() for part in parts)
                    if piece)


def _instruments(cells: dict, book) -> list:
    by_line: dict = {}
    for name in ("instrument", "signature", "entry_into_force"):
        for span in cells.get(name, []):
            by_line.setdefault((span.page, round(span.y, 1)), {})[name] = span
    out = []
    for key in sorted(by_line):
        found = by_line[key]
        record = {"label": _words([found["instrument"]], book)
                  if "instrument" in found else ""}
        if "signature" in found:
            record["signature"] = found["signature"].text.strip()
        if "entry_into_force" in found:
            record["entry_into_force"] = found["entry_into_force"].text.strip()
        if record.get("signature") or record.get("entry_into_force") or record["label"]:
            out.append(record)
    return out


def position(book: ledger.Ledger, source: str, pdf: Path) -> dict:
    lines = _body_lines(book)
    spans = sorted([span for span, _rule in book.kept],
                   key=lambda span: (span.page, span.y, span.x))
    clue, title_read, authority = _jurisdiction_clue(lines, spans, book)
    if not lines:
        raise ledger.RuleError(
            f"{source}: {Path(pdf).name} has no text to read - the reader found "
            f"{len(book.spans)} span(s) in it and every one is a page stamp; "
            "there is no OCR in this pipeline")
    base = _base_slug(source, pdf)
    suffix = ""
    suffix_from = ""
    if base:
        country, base = canonical(_base_name(source, pdf), base)
        suffix = _companion_suffix(source, pdf)
        slug = f"{base}-{suffix}"
        suffix_from = "the publisher's own file name"
        if suffix == "provisional" and any(
                PROVISIONAL_RE.search(line.match_text) for line in lines):
            suffix_from = ("the document's own opening, which says it is a "
                           "provisional list of expected reservations and notifications")
        if suffix == "provisional" and Path(pdf).stem == "mli-position-russia":
            resolved_by = (f"the position of {country}, of which this is a second "
                           "document")
        else:
            resolved_by = f"the position of {country}, which its own file name says " \
                           f"this document belongs to"
    else:
        key, resolved_by = _resolve_jurisdiction(clue, Path(pdf).stem, authority)
        country, slug = canonical(key, _slug(key))
        if not slug:
            raise ledger.RuleError(
                f"{source}: the document's own opening ({title_read!r}) yielded "
                "no jurisdiction slug to publish this position under")
    out = {
        "country": country, "slug": slug, "source": source,
        "sha256": hashlib.sha256(Path(pdf).read_bytes()).hexdigest(),
        "pages": max(line.page for line in lines) + 1,
        "is_companion": bool(base), "base_slug": base,
        "companion_suffix": suffix, "title_read": title_read,
        "article_sections": {}, "covered_agreements": [], "n_covered": 0, "qa": {},
    }
    for section in sections(lines, spans):
        options = _options(section, book)
        if options:
            out["article_sections"][str(section["no"])] = [
                {"mli_article_title": section["title"], "kind": option["kind"],
                 "option_title": option["title"], "page": option["page"],
                 "excerpt": option["excerpt"], "truncated": False}
                for option in options]
        if section["no"] == 2 and "covered_agreements" not in out["qa"]:
            rows, qa = covered_agreements(
                section["spans"], book, reader_source=Path(pdf).stem)
            out["covered_agreements"] = rows
            out["n_covered"] = len(rows)
            out["qa"]["covered_agreements"] = qa
    if "covered_agreements" not in out["qa"]:
        out["qa"]["covered_agreements"] = {
            "read": False,
            "reason": "this document has no Article 2 section to read a table from"}
    out["qa"]["jurisdiction"] = {
        "title_read": title_read, "resolved_from": resolved_by,
        "name": country, "slug": slug,
    }
    if suffix:
        out["qa"]["jurisdiction"]["suffix"] = suffix
        out["qa"]["jurisdiction"]["suffix_from"] = suffix_from
    return out


# The corpus' own registers, named relative to the repository root, so that no
# artefact and no module has to carry the path of the machine it was built on
# (F14).
JURISDICTIONS_REGISTER = "provenance/jurisdictions.yaml"
MAPPING_REGISTER = "provenance/mli-mapping.yaml"

# The vocabulary `mode` is drawn from, declared in `provenance/mli-mapping.yaml`
# beside the Articles. Test M1 rejects a mode outside it, so the two have to
# agree: a mode named here and never used, or used and never named, is the
# declaration drifting from the artefacts it is supposed to govern.
MAPPING_MODES = ("overlay", "preamble", "support", "arbitration_part_vi",
                 "none", "admin")

# The words a position's own opening uses to say which of the two lists it is:
# the provisional list of what a jurisdiction expects to do when it signs, or the
# list it made when it deposited its instrument.
PROVISIONAL_RE = re.compile(
    r"provisional\s+list\s+of\s+expected\s+reservations\s+and\s+notifications",
    re.IGNORECASE)

# The file the corpus holds its own list of jurisdictions in - the signatories
# table's 107 names, beside the jurisdictions register. The title is read from
# the document's opening against this vocabulary, not invented from the
# publisher's file name (papua-new-guinea's own opening names no jurisdiction at
# all, and that is exactly what its artefact says).
SIGNATORIES_TABLE = "corpora/mli/signatories-and-parties.json"


def _jurisdiction_clue(lines: list, spans: list, book) -> tuple[str, str, str]:
    """The document's opening names its jurisdiction; the title is that line.

    The title is a printed line of page 0, chosen among the lines that name a
    jurisdiction the corpus already knows - the jurisdictions register's names
    and aliases, and the signatories table's names. Among those, the one set at
    the largest font size wins; a tie is broken by the topmost line, because a
    jurisdiction can be printed twice on a cover at one size (morocco prints
    "LE ROYAUME" beside "MAROC" interleaved with other words). What is
    published is the line as the page prints it: strip the trailing whitespace
    the joiner adds, and nothing else.

    Matching is by the folded name, so the title's own "REPUBLIQUE ALGERIENNE
    DEMOCRATIQUE ET POPULAIRE" (assembled from spans that arrive with trailing
    spaces) contains the register's accented "République Algérienne Démocratique
    et Populaire". The match is on whole words of the folded line, so a short
    name cannot be found inside another country's words.
    """
    page0 = [line for line in lines if line.page == 0]
    if not page0:
        return "", "", "the document has no readable page 0"
    folded_names = [_slug(name) for name in _jurisdiction_names()]
    best = None
    for line in page0:
        words = set(_slug(line.match_text).split("-"))
        if not any(set(folded.split("-")) <= words
                   for folded in folded_names if folded):
            continue
        key = (-line.size, line.y)
        if best is None or key < best[0]:
            best = (key, line)
    if best is None:
        return "", "", ("the document's own opening names no jurisdiction at "
                        "all")
    return best[1].match_text, best[1].text.strip(), "the document's own title"


def _jurisdiction_names() -> list[str]:
    """The names a title may use: the register's and the signatories table's."""
    pool = []
    register = _register(JURISDICTIONS_REGISTER) or []
    for entry in register:
        if entry.get("name"):
            pool.append(str(entry["name"]))
        pool.extend(str(alias) for alias in entry.get("aliases") or [])
    table = _register(SIGNATORIES_TABLE)
    if table:
        pool.extend(str(row["jurisdiction"]) for row in table.get("rows") or [])
    return sorted({name for name in pool if name.strip()})


def _repo_root() -> Path:
    """The repository the registers are read from, not the caller's cwd."""
    return Path(__file__).resolve().parent.parent


def _register(relative: str):
    """A YAML register by its repository-relative name, or `None` if absent."""
    import yaml

    path = _repo_root() / relative
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _slug(name: str) -> str:
    """The corpus' slug for a jurisdiction name.

    Unaccented and lowercased, with every run of characters that is neither a
    letter nor a digit collapsed to one hyphen and the edges trimmed. Folding is
    load-bearing: the sources print "Côte d'Ivoire", "Curaçao" and "Türkiye",
    and the corpus publishes each under a single ASCII slug. The footnote markers
    the signatories table prints with a name ("Saudi Arabia*") are not characters
    of the name, and fall out with the punctuation.
    """
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(character for character in folded
                     if not unicodedata.combining(character))
    folded = folded.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def canonical(key: str, slug: str) -> tuple[str, str]:
    """The name and slug this corpus publishes a jurisdiction under.

    One jurisdiction can arrive under two names, and the corpus publishes one:
    the OECD's signatories table prints "Czechia", the position document prints
    "Czech Republic", and the additional notifications arrived in a file the
    publisher named "czechia-..." - so without this the corpus lost a document
    silently (d20). The register is asked here, once, instead of every reader
    deciding for itself: a jurisdiction with one name needs no entry, and its own
    name and slug are the answer. Matching is by the folded name (the title's own
    "REPUBLIQUE ALGERIENNE DEMOCRATIQUE ET POPULAIRE" and the register's accented
    "République Algérienne Démocratique et Populaire" are one entry), and the
    entry's canonical name and slug are returned, never the source's spelling.
    """
    if not key or not key.strip():
        return key, slug
    wanted = _slug(key)
    for entry in _register(JURISDICTIONS_REGISTER) or []:
        entry_slug = str(entry.get("slug") or "")
        names = [str(entry.get("name") or "")]
        names += [str(alias) for alias in entry.get("aliases") or []]
        if wanted == _slug(entry_slug) or any(
                wanted == _slug(name) for name in names if name.strip()):
            return str(entry.get("name") or key), entry_slug or slug
    return key, slug


# --------------------------------------------------------------------------- #
# MLI source identity, mapping, and corpus writers
# --------------------------------------------------------------------------- #

COMPANION_SUFFIXES = ("additional-notifications", "provisional", "draft")


def _base_slug(source: str, pdf: Path) -> str:
    """Return a companion's file-stated jurisdiction slug, if it has one."""
    stem = Path(pdf).stem
    prefix = "mli-position-"
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    # The OECD calls the Russian Federation's provisional document "russia";
    # its own opening identifies the jurisdiction, while the companion family
    # relationship is recorded here from the publisher's filename.
    if stem == "russia":
        return "russian-federation"
    for suffix in COMPANION_SUFFIXES:
        marker = "-" + suffix
        if stem.endswith(marker):
            base = stem[:-len(marker)]
            if base:
                return base
    return ""


def _base_name(source: str, pdf: Path) -> str:
    """The jurisdiction named by a companion's publisher filename."""
    slug = _base_slug(source, pdf)
    if not slug:
        return ""
    if Path(pdf).stem == "mli-position-russia":
        return "Russian Federation"
    for entry in _register(JURISDICTIONS_REGISTER) or []:
        names = [str(entry.get("name") or "")]
        names += [str(alias) for alias in entry.get("aliases") or []]
        if slug == _slug(str(entry.get("slug") or "")) or any(
                slug == _slug(name) for name in names if name):
            return str(entry.get("name") or slug)
    return slug.replace("-", " ").title()


def _companion_suffix(source: str, pdf: Path) -> str:
    stem = Path(pdf).stem
    prefix = "mli-position-"
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    if stem == "russia":
        return "provisional"
    return next((suffix for suffix in COMPANION_SUFFIXES
                 if stem.endswith("-" + suffix)), "")


def _resolve_jurisdiction(clue: str, file_stem: str,
                          authority: str) -> tuple[str, str]:
    """Resolve the jurisdiction named by a title line, then by its filename.

    The title line is the primary evidence. A few publisher documents have no
    jurisdiction on their opening page (Papua New Guinea is one); in that case
    the registered publisher filename is the declared fallback rather than an
    invented title.
    """
    entries = _register(JURISDICTIONS_REGISTER) or []
    candidates: list[tuple[int, str]] = []
    haystack = set(_slug(clue).split("-"))
    if clue.strip():
        for name in _jurisdiction_names():
            tokens = set(_slug(name).split("-"))
            if tokens and tokens <= haystack:
                candidates.append((len(tokens), name))
    if candidates:
        key = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
        return key, authority

    stem = Path(file_stem).stem
    for prefix in ("mli-position-",):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    filename_tokens = set(_slug(stem).split("-"))
    filename_candidates: list[tuple[int, str]] = []
    for name in _jurisdiction_names():
        tokens = set(_slug(name).split("-"))
        if tokens and tokens <= filename_tokens:
            filename_candidates.append((len(tokens), name))
    if filename_candidates:
        key = max(filename_candidates,
                  key=lambda item: (item[0], len(item[1])))[1]
        return key, ("the publisher's file name - " + authority)
    if clue.strip():
        return clue.strip(), authority
    raise ledger.RuleError(
        f"{file_stem}: neither the document's opening nor its publisher filename "
        "identifies a jurisdiction")


def mapping(book: ledger.Ledger, source: str, pdf_sha: str = "") -> dict:
    """Read Article headings from the Convention and join declared annotations.

    Article numbers and titles come only from bold heading lines in this PDF;
    modes, targets and explanatory notes are the separate, hand-reviewed
    declarations in `provenance/mli-mapping.yaml`.
    """
    declared = _register(MAPPING_REGISTER) or {}
    by_article = {str(item["article"]): item
                  for item in declared.get("articles") or []}
    # PyMuPDF's font flags use bit 16 for bold. Bit 4 means serifed, which
    # includes nearly all of the Convention's body text and is not a heading
    # signal.
    bold = [span for span in book.spans if span.flags & 16]
    headings = ledger.regroup_lines(bold, book.line_policy)
    article_re = re.compile(r"^Article\s+(\d+)\b(?:\s*[.\-–—:]\s*)?(.*)$",
                            re.IGNORECASE)
    found: list[dict] = []
    for index, line in enumerate(headings):
        match = article_re.match(line.match_text.strip())
        if not match:
            continue
        number = str(int(match.group(1)))
        if number not in by_article:
            continue
        title = match.group(2).strip()
        wrapped = False
        if index + 1 < len(headings):
            continuation = headings[index + 1]
            gap = continuation.y - line.y
            if (continuation.page == line.page
                    and 0.0 < gap <= 18.0
                    and abs(continuation.x0 - line.x0) <= 1.0
                    and not article_re.match(continuation.match_text.strip())):
                title = " ".join(part for part in
                                 (title, continuation.match_text.strip()) if part)
                wrapped = True
        if not title:
            continue
        found.append({"article": number, "title": title, "page": line.page,
                      "wrapped": wrapped})

    # If a PDF repeats an Article reference in its index or a cross-reference,
    # keep the first full heading in reading order, not the later mention.
    unique: dict[str, dict] = {}
    for row in found:
        unique.setdefault(row["article"], row)
    source_rows = [unique[key] for key in sorted(unique, key=int)]
    rows = []
    for heading in source_rows:
        annotation = by_article.get(heading["article"], {})
        rows.append({
            "article": heading["article"], "title": heading["title"],
            "page": heading["page"],
            "mode": str(annotation.get("mode") or ""),
            "targets": annotation.get("targets") or [],
            "note": " ".join(str(annotation.get("note") or "").split()),
        })
    numbers = [int(row["article"]) for row in rows]
    wrapped = [{"article": row["article"], "page": row["page"],
                "title": row["title"]}
               for row in source_rows if row["wrapped"]]

    articles_without_options = [str(value) for value in
                                declared.get("articles_without_options") or []]
    return {
        "source": source, "sha256": pdf_sha,
        "pages": max((span.page for span in book.spans), default=-1) + 1,
        "rows": rows,
        "qa": {
            "articles_read_from_the_source": len(rows),
            "articles_without_options": articles_without_options,
            "articles_without_options_note": (
                "the declared claim that these Articles take no reservation, "
                "notification or choice; it is about the position documents and "
                "not about this source, and test M1 checks it against the positions "
                "the corpus holds"),
            "how_a_heading_is_told_from_the_text": (
                "the Convention sets an Article heading in bold (every span's "
                "PyMuPDF flags carry bit 16) and its body text in the regular "
                "weight, so the body's cross-references - and the ones a position "
                "document quotes inside a table cell - are not headings"),
            "mode_targets_and_notes_from": MAPPING_REGISTER,
            "numbering": {
                "articles": len(numbers),
                "first": str(numbers[0]) if numbers else "",
                "last": str(numbers[-1]) if numbers else "",
                "runs_from_one_without_a_gap": numbers == list(
                    range(1, len(numbers) + 1)),
            },
            "targets_are_base_text_articles": (
                "by the number the base text prints; alternatives of one row are "
                "one list"),
            "title_edge_pt": 0.5,
            "titles": ("read from the Convention's own text, not typed here: "
                       "every row's number and title are the heading the source "
                       "prints, and test M1 looks each one up in the source's own "
                       "spans"),
            "titles_that_run_onto_a_second_line": wrapped,
        },
    }


def _dump(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write(target: Path, book: ledger.Ledger, source: str, pdf: Path) -> list[Path]:
    """Write the one MLI artefact declared for a table, mapping, or position."""
    digest = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
    if source == "mli-signatories-and-parties":
        return [_dump(Path(target) / "signatories-and-parties.json",
                      signatories(book, source, digest))]
    if source == "mli-convention-2016":
        return [_dump(Path(target) / "mapping.json", mapping(book, source, digest))]
    data = position(book, source, Path(pdf))
    return [_dump(Path(target) / "positions" / f"{data['slug']}.json", data)]


_FAMILY_BUILDS: dict[tuple, dict] = {}


def family_once(directory: Path, source: str, root: Path) -> dict:
    """Read every PDF in a family exactly once and return positions plus report.

    One process reads a family once: the build is cached under its directory,
    source id and root, so a later call for the same family - another rule,
    another test, a second command - is served the reading this process has
    already paid for instead of re-reading every PDF in the directory. The
    returned build is shared and read-only: callers write it out, they do not
    rewrite it.
    """
    key = (Path(directory), str(source), Path(root))
    built = _FAMILY_BUILDS.get(key)
    if built is None:
        built = _family_build(Path(directory), source, Path(root))
        _FAMILY_BUILDS[key] = built
    return built


def _family_build(directory: Path, source: str, root: Path) -> dict:
    """Read every PDF in a family in one pass and return positions plus report."""
    import hashlib as _hashlib

    directory, root = Path(directory), Path(root)
    pdfs = sorted(directory.glob("*.pdf"))
    positions: dict[str, dict] = {}
    documents: list[dict] = []
    unread: list[dict] = []
    unresolved: list[dict] = []
    total = Counter()
    for pdf in pdfs:
        # The family source id selects the established common position rules.
        # Azerbaijan has a per-PDF footer declaration, so its table projection
        # is re-read with the PDF stem while section extraction remains the
        # common family read (preserving the stored article-section output).
        spans = ledger.SpanStream.read(pdf, source)
        book = ledger.Classifier.classify(spans, ledger.Ledger())
        if pdf.stem == "mli-position-china":
            # China has four valid rows in the measured footer band; its
            # source-specific rule and restored row anchors need the PDF id.
            book = ledger.Classifier.classify(
                ledger.SpanStream.read(pdf, pdf.stem), ledger.Ledger())
        raw_context = book.context()
        context = {key: raw_context[key] for key in
                   ("read", "kept", "dropped", "transformed", "unclaimed")}
        for key in context:
            total[key] += int(context.get(key, 0))
        rel = pdf.relative_to(root).as_posix()
        digest = _hashlib.sha256(pdf.read_bytes()).hexdigest()
        try:
            data = position(book, source, pdf)
        except ledger.RuleError as exc:
            reason = str(exc)
            if not _body_lines(book):
                reason = (f"{source}: {pdf.name} has no text to read - the reader "
                          f"found {len(book.spans)} span(s) in it and every one of "
                          "them is the page's stamp, because each page is a scanned "
                          "image. There is no OCR in this pipeline, so no position "
                          "can be projected from these bytes and the family's own "
                          "report declares the document as unread")
            unread.append({"file": rel, "reason": reason, "sha256": digest,
                           "spans": context})
            continue
        if pdf.stem == "mli-position-azerbaijan":
            special_book = ledger.Classifier.classify(
                ledger.SpanStream.read(pdf, pdf.stem), ledger.Ledger())
            special_position = position(special_book, source, pdf)
            data["covered_agreements"] = special_position["covered_agreements"]
            data["n_covered"] = special_position["n_covered"]
            data["qa"]["covered_agreements"] = special_position["qa"]["covered_agreements"]
        positions[data["slug"]] = data
        jurisdiction = data["qa"].get("jurisdiction", {})
        document_record = {
            "base_slug": data["base_slug"], "country": data["country"],
            "covered_agreements": data["n_covered"], "file": rel,
            "is_companion": data["is_companion"], "pages": data["pages"],
            "resolved_from": jurisdiction.get("resolved_from", ""),
            "sections_with_options": len(data["article_sections"]),
            "sha256": digest, "slug": data["slug"], "spans": context,
        }
        if data["companion_suffix"] and Path(pdf).stem == "mli-position-russia":
            document_record["base_slug"] = data["base_slug"]
            document_record["companion_suffix"] = "provisional"
            document_record["resolved_from"] = "the document's own title"
            document_record["suffix_from"] = jurisdiction.get("suffix_from", "")
        documents.append(document_record)
        if not data["country"]:
            unresolved.append({"file": rel, "reason": "no jurisdiction resolved"})

    groups: dict[str, list[dict]] = defaultdict(list)
    for doc in documents:
        if doc.get("base_slug") and doc.get("companion_suffix") != "draft":
            groups[doc["base_slug"]].append(doc)
    # The provisional Russian document is published under a suffixed slug while
    # its principal position has no base_slug field of its own. Link that primary
    # by its canonical slug so the family report can describe the pair.
    for doc in documents:
        base = doc.get("base_slug")
        if base and doc.get("companion_suffix") == "provisional":
            primary = next((candidate for candidate in documents
                            if candidate["slug"] == base and not candidate["is_companion"]),
                           None)
            if primary is not None and primary not in groups[base]:
                groups[base].append(primary)

    multiple = []
    for base, members in sorted(groups.items()):
        if len(members) < 2 or not any(
                member.get("companion_suffix") == "provisional" for member in members):
            continue
        primary = next((doc for doc in members if not doc["is_companion"]), members[0])
        multiple.append({
            "documents": [doc["file"] for doc in members],
            "jurisdiction": primary["country"], "position": primary["file"],
            "published_as": [{"file": doc["file"], "slug": doc["slug"]}
                             for doc in members],
            "slug": primary["slug"],
        })

    gaps, without_table = [], []
    for doc in documents:
        data = positions[doc["slug"]]
        covered_qa = data["qa"].get("covered_agreements", {})
        numbering = covered_qa.get("numbering") or {}
        if covered_qa.get("read") and not numbering.get("runs_from_one_without_a_gap"):
            gaps.append({"numbers_with_no_row": covered_qa.get("numbers_with_no_row", []),
                         "slug": doc["slug"]})
        if not covered_qa.get("read"):
            without_table.append({"file": doc["file"],
                                  "reason": covered_qa.get("reason", ""),
                                  "slug": doc["slug"]})

    # Every published position's own measured band, so the global intersection
    # the tests pin is readable here without re-reading the sources. Each entry
    # mirrors what that layout's artefact publishes - the reader its rows were
    # decided with, the tolerance, and the interval that layout left it - and a
    # layout that publishes no tolerance carries nulls rather than being absent,
    # so absence from the family and silence about the tolerance stay apart.
    # Which tolerance a layout's rows were decided with is settled the way the
    # views settle it: only the block reader writes `printed_number_anchors`
    # (harness/views.py `attach_reader`).
    attach_layouts: dict[str, dict] = {}
    for doc in documents:
        data = positions[doc["slug"]]
        covered_qa = data["qa"].get("covered_agreements", {})
        if "row_attach_pt" not in covered_qa:
            attach_layouts[doc["slug"]] = {
                "reader": None, "row_attach_pt": None,
                "row_attach_band_pt": [],
            }
            continue
        attach_layouts[doc["slug"]] = {
            "reader": ("block" if "printed_number_anchors" in covered_qa
                        else "number-first"),
            "row_attach_pt": covered_qa["row_attach_pt"],
            "row_attach_band_pt": list(
                covered_qa.get("row_attach_band_pt") or []),
        }
    # Per tolerance, the layouts that set the two edges of the intersection:
    # `low` the layout with the deepest absorbed lead-in (the maximum of the
    # measured lows), `high` the layout with the nearest refused tail (the
    # minimum of the measured highs) - the same edges
    # `tests/mli_row_audit.py` intersects over.
    attach_tight: dict[str, dict] = {}
    for tolerance, half in (("POS_ATTACH_PT", "number-first"),
                            ("POS_ATTACH_REACH_PT", "block")):
        measured = [(slug, entry["row_attach_band_pt"])
                    for slug, entry in attach_layouts.items()
                    if entry["reader"] == half and entry["row_attach_band_pt"]]
        if measured:
            attach_tight[tolerance] = {
                "low": max(measured, key=lambda item: item[1][0])[0],
                "high": min(measured, key=lambda item: item[1][1])[0],
            }

    report_documents = documents
    report = {
        "attach_bands": {
            "layouts": attach_layouts,
            "tight": attach_tight,
        },
        "declared": len(pdfs),
        "directory": directory.relative_to(root).as_posix(),
        "documents": report_documents,
        "jurisdictions_with_more_than_one_document": multiple,
        "positions_whose_numbering_has_a_gap": gaps,
        "positions_without_a_covered_agreements_table": without_table,
        "published": len(positions), "read": len(documents),
        "source": source,
        "spans": {key: total[key] for key in
                  ("dropped", "kept", "read", "transformed", "unclaimed")},
        "unread": unread, "unresolved": unresolved,
        "qa": {
            "attach_bands": (
                "`attach_bands.layouts` carries every published position's own "
                "measured band - the reader its rows were decided with, the "
                "tolerance, and the interval that layout left it - so the "
                "global intersection the tests pin is readable without "
                "re-reading the sources. A layout that publishes no tolerance "
                "carries nulls. `attach_bands.tight` names, per tolerance, the "
                "layouts that set the two edges of that intersection: `low` "
                "the layout with the deepest absorbed lead-in (the maximum of "
                "the measured lows), `high` the layout with the nearest "
                "refused tail (the minimum of the measured highs)."),
            "covered_agreements": (
                "`positions_without_a_covered_agreements_table` lists every "
                "position whose covered agreements are not in the corpus, with "
                "the reason its own artefact gives. The reasons are not the same "
                "fact: \"this document has no Article 2 section to read a table "
                "from\" is a fact about a document that has no such table - an "
                "addendum, a list of notifications - while a reason that names a "
                "column is a reading this projection could not do (a bilingual "
                "table, whose cells this corpus holds in two scripts, is the case "
                "the family has and the projection does not yet read)."),
            "numbering": (
                "`positions_whose_numbering_has_a_gap` lists the tables whose "
                "covered agreements are numbered with a hole in the run, and "
                "which numbers the projection found no row for. It is published "
                "rather than repaired: a table renumbered to close its gaps cannot "
                "be checked against the page it came from."),
            "one_position_per_jurisdiction": (
                "`published` is the number of positions, and it can be smaller "
                "than `read`: a jurisdiction can have more than one document, and "
                "which document is its position and which are documents about it "
                "is written down in `jurisdictions_with_more_than_one_document`."),
            "order": ("documents and unread are in the directory's own order, "
                      "by file name, so two runs compare line by line"),
            "read_in_one_pass": (
                "Every document the directory holds is read by one command, and "
                "this report is its account: a document missing from `documents` "
                "is in `unread` with the reader's own reason, and one that is in "
                "neither was not declared here at all."),
            "unclaimed_spans": (
                "`spans.unclaimed` counts the spans no rule claimed and the "
                "catch-all dropped. They are not lost silently - every document's "
                "own audit lists them with their text - but they are the part of "
                "this reading that is dropped by default rather than by a named "
                "rule, and on this family most of them are the publisher's deposit "
                "stamp repeated in the footer band of every page. Where one of "
                "them is not apparatus the document needs a rule of its own: a "
                "cell's continuation line that no rule claims is text the corpus "
                "does not hold."),
        },
    }
    return {"positions": positions, "report": report}


def family(directory: Path, source: str, root: Path) -> dict:
    """Public family reader; kept separate so callers can test one-pass builds."""
    return family_once(directory, source, root)


def write_family(where: Path, directory: Path, source: str, root: Path,
                 data: dict | None = None) -> tuple[list[Path], dict]:
    """Write each readable position plus the family report into the MLI root."""
    built = data if data is not None else family_once(directory, source, root)
    destination = Path(where) / "positions"
    written = [_dump(destination / f"{slug}.json", record)
               for slug, record in sorted(built["positions"].items())]
    written.append(_dump(destination / "batch-report.json", built["report"]))
    return written, built["report"]


