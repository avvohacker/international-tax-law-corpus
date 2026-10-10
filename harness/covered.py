"""Number-first reader for covered-agreements tables with displaced x modes."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace

DATE_TOKEN_RE = re.compile(
    r"(?<!\d)\d{1,2}[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{2,4}(?!\d)")
DATE_WITH_NA_RE = re.compile(
    r"^\d{1,2}[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{2,4}"
    r"\s+(?:N\s*/\s*A|NA)$", re.IGNORECASE)


def _has_letters(span) -> bool:
    return any(character.isalpha() for character in span.text)


def _row_baselines(spans: list) -> list:
    """Marked row lines: an explicit Original label and a printed date."""
    lines: dict[tuple[int, float], list] = defaultdict(list)
    for span in spans:
        lines[(span.page, round(span.y, 1))].append(span)
    return [(key, line) for key, line in sorted(lines.items())
            if any(span.text.strip().rstrip("/").casefold() == "original"
                   for span in line)
            and any(DATE_TOKEN_RE.search(span.text) for span in line)]


def _number_run(spans: list, high: float) -> tuple[float | None, int, list]:
    """Find the number column as the x-cluster with a 1, 2, 3... run."""
    from harness import mli

    candidates = [span for span in spans if span.x < high
                  and mli.NUMBER_RE.fullmatch(span.text.strip())]
    clusters: list[list] = []
    for span in sorted(candidates, key=lambda item: item.x):
        if clusters and span.x - clusters[-1][-1].x <= mli.RAGGED_COLUMN_TOL_PT:
            clusters[-1].append(span)
        else:
            clusters.append([span])
    best: tuple[float | None, int, list] = (None, 0, [])
    for cluster in clusters:
        values = {int(span.text.strip()) for span in cluster}
        run = 0
        while run + 1 in values:
            run += 1
        if run > best[1]:
            best = (round(min(span.x for span in cluster), 1), run, cluster)
    return best


def _date_cells(span, columns: list, merged: bool) -> list:
    """Split two dates or a date/N/A pair packed in one text span."""
    from harness import mli

    names = [name for name, _x in columns
             if name in ("signature", "entry_into_force")]
    value = span.text.strip()
    dates = DATE_TOKEN_RE.findall(value)
    if DATE_WITH_NA_RE.fullmatch(value) and dates:
        return [(names[0], replace(span, text=dates[0])),
                (names[1], replace(span, text="N/A"))]
    if len(dates) == 2:
        return [(names[0], replace(span, text=dates[0])),
                (names[1], replace(span, text=dates[1]))]
    return mli._dated_cells(span, columns, merged)


def _read(spans: list, book, dates: list | None = None,
          signature_x: float | None = None, force_x: float | None = None,
          split_dates_by_text: bool | None = None,
          number_anchors: list | None = None, number_run: int | None = None,
          measured_title_x: float | None = None) -> tuple:
    """Measure left-hand columns from numbers; use row markers only for grouping."""
    from harness import mli

    markers = _row_baselines(spans)
    if len(markers) < 2:
        return [], {"read": False, "reason": "fewer than two Original/date row markers"}
    # The height a marker was printed at, beside the rounded height that
    # identifies its line. A row range drawn at the rounded height is wrong in
    # both directions: a line 0.02pt above the rounded key is dropped from its
    # own row (Kuwait's row 1) and one 0.02pt below it is taken into the row
    # before (Kuwait's row 2 takes row 3's first line); rounding to two places
    # still moves the bound above the span it was measured from (Azerbaijan's
    # row 1 loses its own "Austria" cell). The bound is the printed height.
    marker_starts = {index: (key[0], min(span.y for span in line))
                     for index, (key, line) in enumerate(markers)}

    # `covered_agreements` already separates these date columns from the table's
    # date spans (including ragged x starts). Keep that measured result here.
    if signature_x is None or force_x is None or split_dates_by_text is None:
        date_spans = [span for _key, line in markers for span in line
                      if DATE_TOKEN_RE.search(span.text)]
        xs = sorted({round(span.x, 1) for span in date_spans})
        if not xs:
            return [], {"read": False, "reason": "no date-column measurement"}
        if len(xs) == 1:
            signature_x = force_x = xs[0]
            split_dates_by_text = True
        else:
            gap = max(range(len(xs) - 1), key=lambda index: xs[index + 1] - xs[index])
            signature_x, force_x = xs[0], xs[gap + 1]
            split_dates_by_text = False

    first_page, first_y = marker_starts[0]
    table = [span for span in spans
             if (span.page, span.y) >= (first_page, max(0.0, first_y - 30.0))]
    number_x, run, anchors = _number_run(table, signature_x - 1.0)
    if number_x is None or run < 2 or not anchors:
        return [], {"read": False, "reason": "the consecutive 1, 2, 3 row-number run was not found"}

    # Identify the left-hand title start from title/counterparty text on the
    # date-marker baseline. This is deliberately downstream of measuring x from
    # the number run: an often-repeated Original label never defines the title.
    originals = [span for _key, line in markers for span in line
                 if span.text.strip().rstrip("/").casefold() == "original"]
    instrument_x = round(min(span.x for span in originals), 1)
    title_starts: list[float] = []
    counterpart_samples: list = []
    title_cp_gaps: list[float] = []
    cp_original_gaps: list[float] = []
    for _key, line in markers:
        original = next((span for span in line
                         if span.text.strip().rstrip("/").casefold() == "original"), None)
        if original is None:
            continue
        candidates = [span for span in line
                      if span.x > number_x + 5.0 and span.x < original.x - 5.0
                      and _has_letters(span) and not DATE_TOKEN_RE.search(span.text)]
        if not candidates:
            continue
        counterpart = max(candidates, key=lambda span: span.x)
        title_cells = [span for span in candidates if span is not counterpart]
        title_starts.extend(span.x for span in title_cells)
        title_edge = max((span.x1 for span in title_cells), default=counterpart.x)
        title_cp_gaps.append((title_edge + counterpart.x) / 2.0)
        cp_original_gaps.append((counterpart.x1 + original.x) / 2.0)
        counterpart_samples.append(counterpart.x)
    if not title_starts or not counterpart_samples:
        return [], {"read": False, "reason": "title/counterparty columns were not found after the number column"}
    title_x = round(min(title_starts), 1)
    counterpart_x = round(sorted(counterpart_samples)[len(counterpart_samples) // 2], 1)
    title_boundary = sorted(title_cp_gaps)[len(title_cp_gaps) // 2]
    instrument_boundary = sorted(cp_original_gaps)[len(cp_original_gaps) // 2]
    if not number_x < title_x < title_boundary < counterpart_x:
        return [], {"read": False, "reason": "measured title and counterparty columns overlap"}
    if not counterpart_x < instrument_boundary < instrument_x < signature_x:
        return [], {"read": False, "reason": "measured counterparty and instrument columns overlap"}

    # Each Original/date baseline begins one row. The printed number can sit
    # later in that row, on the wrapped title line, so the row a number opens is
    # the last marker at or above it - never nearest-x or nearest-y frequency,
    # and never a half-open window between two rounded marker heights, where a
    # number 0.02pt above the next marker's rounded y falls into the row before
    # its own (Kuwait's row 3 does exactly that).
    marker_for_number: dict[int, int] = {}
    ordered_anchors = sorted(anchors, key=lambda span: (span.page, span.y, span.x))
    markers_by_page: dict[int, list[int]] = defaultdict(list)
    for marker_index, (key, _line) in enumerate(markers):
        markers_by_page[key[0]].append(marker_index)
    for anchor in ordered_anchors:
        above = [(marker_index, marker_starts[marker_index][1])
                 for marker_index in markers_by_page.get(anchor.page, [])
                 if marker_starts[marker_index][1] <= anchor.y + 1.0]
        if not above:
            # A number above the first row marker of its page names no row the
            # page's markers can name; the numbering reconciliation below
            # reports it instead of attaching it to a neighbouring row.
            continue
        marker_index = above[-1][0]
        if marker_index in marker_for_number.values():
            return [], {"read": False,
                        "reason": f"more than one printed number falls in row marker {marker_index + 1}"}
        number = int(mli.NUMBER_RE.fullmatch(anchor.text.strip()).group(0))
        if number in marker_for_number:
            return [], {"read": False, "reason": f"printed number {number} was assigned twice"}
        marker_for_number[number] = marker_index
    unused_markers = [marker_index for marker_index, _key in enumerate(markers)
                      if marker_index not in marker_for_number.values()]

    present_numbers = set(marker_for_number)
    missing_numbers = [number for number in range(1, max(present_numbers, default=0) + 1)
                       if number not in present_numbers]
    if len(unused_markers) != len(missing_numbers):
        return [], {"read": False,
                    "reason": "unmatched row markers do not correspond to printed number gaps"}
    number_for_marker = {marker: number for number, marker in marker_for_number.items()}
    for marker_index, missing in zip(unused_markers, missing_numbers):
        number_for_marker[marker_index] = None

    columns = [("no", number_x), ("title", title_x),
               ("other_jurisdiction", counterpart_x), ("instrument", instrument_x),
               ("signature", signature_x), ("entry_into_force", force_x)]
    rows = []
    unplaced = []
    for marker_index, marker in enumerate(markers):
        page = marker[0][0]
        start = marker_starts[marker_index]
        next_index = next((index for index in range(marker_index + 1, len(markers))
                           if markers[index][0] > marker[0]), None)
        end = marker_starts[next_index] if next_index is not None else None
        row_spans = [span for span in table
                     if (span.page, span.y) >= start
                     and (end is None or (span.page, span.y) < end)]
        cells: dict[str, list] = defaultdict(list)
        for span in row_spans:
            # The number column's own band, measured with the column tolerance:
            # a span standing that near the number column's x is the row's
            # number and not a cell of it.
            if (abs(span.x - number_x) <= mli.RAGGED_COLUMN_TOL_PT
                    and mli.NUMBER_RE.fullmatch(span.text.strip())):
                continue
            if DATE_TOKEN_RE.search(span.text) or DATE_WITH_NA_RE.fullmatch(span.text.strip()):
                for name, value in _date_cells(span, columns, split_dates_by_text):
                    cells[name].append(value)
            elif instrument_boundary <= span.x < signature_x - 1.0 and _has_letters(span):
                cells["instrument"].append(span)
            elif title_boundary <= span.x < instrument_boundary and _has_letters(span):
                cells["other_jurisdiction"].append(span)
            elif (max(number_x + 5.0, title_x - 45.0) <= span.x < title_boundary
                  and _has_letters(span)):
                cells["title"].append(span)
            elif span.text.strip() and span.x >= number_x + 5.0:
                unplaced.append({"page": page, "y": round(span.y, 2),
                                 "x": round(span.x, 1), "text": span.text.strip()[:80]})

        number = number_for_marker.get(marker_index)
        row = {"no": number, "page": page}
        for name, _x in columns:
            if name == "no":
                continue
            text = mli._words(sorted(cells.get(name, []),
                                     key=lambda span: (span.page, round(span.y, 1), span.x)), book)
            if text:
                row[name] = text
        row["instruments"] = mli._instruments(cells, book)
        rows.append(row)

    numbered = [row["no"] for row in rows if row["no"] is not None]
    qa = {
        "read": True,
        "columns": {name: round(x, 1) for name, x in columns},
        "columns_measured_from": "the consecutive row-number run (1, 2, 3, ...)",
        "numbering": {"first": min(numbered) if numbered else None,
                      "last": max(numbered) if numbered else None,
                      "rows": len(rows), "printed_numbers": len(numbered),
                      "runs_from_one_without_a_gap": sorted(numbered)
                          == list(range(1, len(numbered) + 1))},
        "rows_delimited_by": "the printed number run aligned to Original/date row markers",
        "numbered_rows_without_a_number": [
            {"page": row["page"], "y": marker_starts[index][1],
             "number_slot": missing_numbers[slot], "text": row.get("title", "")[:100]}
            for slot, index in enumerate(unused_markers) for row in [rows[index]]],
        "numbers_with_no_row": missing_numbers,
        "row_attach_pt": mli.POS_ATTACH_PT,
        # The window is declared and published - it travels in this artefact as
        # `row_attach_pt` - but this reading places its spans by the row markers
        # the page prints (`marker_starts` above) and never asks the distance to
        # a number, so the interval the page leaves for it is empty: the same
        # encoding the readings that place by title cells use. The field is
        # published rather than left out so that every covered-agreements reading
        # carries the band its own tolerance was measured over, and the drift
        # control names that band for the artefact it decided.
        "row_attach_band_pt": [],
        "span_tol_pt": mli.CELL_TOL_PT,
        "date_columns": ("one x: date columns share a span" if split_dates_by_text
                         else "two x: signature and force-date columns are separated"),
        "dated_cells_split_by_text": sum(bool(row.get("entry_into_force")) for row in rows),
        "spans_that_fitted_no_column": unplaced,
        "note": ("The number run measures the left-hand columns and is aligned "
                 "to Original/date row markers. A source row without a number is "
                 "kept with no = null; printed numbers are not invented or shifted."),
    }
    return rows, qa
