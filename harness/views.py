"""The views: generated from the projection, never from the PDF again.

`derived/markdown/<family>/<edition>/article-<n>.md` is one document per
article, and it is the form most people read. It is produced from the same
projection the AKN writer walks, in the same build, so the two cannot drift:
invariant F9 says the views and the XML are one structure, and the cheap way to
keep that promise is to have one structure and two renderings of it.

What the view must *not* do is invent structure out of typography. The audit's
d14 was exactly that - an "Article 8 (alternative B)" label printed as a numbered
paragraph, so that the two branches of an article read as one list of paragraphs
and could not be told apart. Here an alternative is a heading, and only a node
the projection called a paragraph is numbered.

The MLI positions have a second, smaller view here: one markdown table per
position, `derived/markdown/<family>/positions/<slug>.md`, rendered from the
position artefact. It names the counterparty and the dates each row holds, which
is what a reader wants from a covered-agreements table, and it is the artefact
and not the PDF that it renders, so a reader repair that is not republished
leaves the view visibly behind.

That view also carries the interval the reading left for its own attach
tolerance, beside the rows it decided (`attach_line`): the tolerance and the
band both travel inside the artefact already, and printing them in the view is
what makes the room the reading had readable where the rows are read, rather
than only in the JSON.

The signatories table has the same kind of view
(`derived/markdown/<family>/signatories-and-parties.md`, `signatories_view`):
its rows, and the window and band its own reading publishes, in the same
`attach_line` format with that table's own reader named.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness import ledger
from harness.akn import _note_text


def slug(article: ledger.Node) -> str:
    """The article's own number, as a file name: "Article 12B" -> "12B"."""
    number = (article.number or article.eId).strip()
    if number.lower().startswith("article"):
        number = number[len("article"):].strip()
    return number.replace(" ", "") or article.eId


def _render_article(article: ledger.Node, book, source: str) -> str:
    lines = [f"# {article.number} — {article.title}".rstrip(" —"), ""]
    lines.append(f"*{source} · {article.eId} · page {article.spans[0].page}*"
                 if article.spans else f"*{source} · {article.eId}*")
    _render_children(article, book, lines, 0)
    return "\n".join(lines).rstrip() + "\n"


def _render_children(node: ledger.Node, book, lines: list, depth: int) -> None:
    for child in node.children:
        if child.tag == "paragraph":
            lines.extend(["", f"**{child.number}** {child.text(book)}"])
            _render_children(child, book, lines, depth + 1)
        elif child.tag == "point":
            indent = "  " * (depth + 1)
            lines.append(f"{indent}- **{child.number}** {child.text(book)}")
            _render_children(child, book, lines, depth + 1)
        elif child.tag == "alinea":
            lines.extend(["", f"{'  ' * depth}{child.text(book)}"])
        elif child.tag == "alternative":
            lines.extend(["", f"## {child.text(book)}"])
            _render_children(child, book, lines, 0)
        elif child.tag == "note":
            lines.extend(["", f"> **{child.number}** {_note_text(child, book)}"])
        else:
            raise ledger.RuleError(
                f"{child.eId}: the markdown view has no rendering for a node of "
                f"kind {child.tag!r}; a view that skipped it would be a silent "
                f"deletion (F3)")


def _render_preamble(preamble: ledger.Node, book, source: str) -> str:
    lines = [f"# {preamble.title or 'Preamble'}", ""]
    lines.append(f"*{source} · {preamble.eId}*")
    _render_children(preamble, book, lines, 0)
    return "\n".join(lines).rstrip() + "\n"


def documents(projection: ledger.Node, book, source: str) -> dict:
    """{file name: markdown} for one edition, in document order."""
    out: dict = {}
    for node in projection.walk():
        if node.tag == "article":
            out[f"article-{slug(node)}.md"] = _render_article(node, book, source)
        elif node.tag == "preamble":
            out["preamble.md"] = _render_preamble(node, book, source)
    return out


def write(root: Path, source: str, family: str, edition: str,
          projection: ledger.Node, book) -> list:
    """Write the markdown view of one edition under `derived/markdown/...`.

    Existing documents of this edition are removed first, so that a build is a
    function of its input and not of what an earlier build left behind: a stale
    `article-30.md` is a view of a corpus that no longer exists.
    """
    directory = Path(root) / "markdown" / family / edition
    directory.mkdir(parents=True, exist_ok=True)
    for stale in sorted(directory.glob("*.md")):
        stale.unlink()
    written: list = []
    for name, text in documents(projection, book, source).items():
        path = directory / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


# The covered-agreements position view: one markdown file per jurisdiction,
# `derived/markdown/<family>/positions/<slug>.md`. It is a table of the rows the
# position artefact holds - the number the page prints, the counterparty the row
# names, its instrument, the two dates the table prints and the page they stand
# on. It is rendered from the artefact, never from the PDF again, so the view and
# the corpus are one answer (F9); the row's printed title is not repeated, because
# the artefact carries it and `tests/mli_row_audit.py` checks it against the
# source row by row, and a view that copied every field would be a second copy of
# the artefact rather than a view of it.
POSITION_VIEW_COLUMNS = (
    ("#", None),
    ("Counterparty", "other_jurisdiction"),
    ("Instrument", "instrument"),
    ("Signature", "signature"),
    ("Entry into force", "entry_into_force"),
    ("Page", "page"),
)


def _view_cell(value) -> str:
    """One table cell: a missing field is empty, and a pipe cannot split a cell."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def attach_reader(qa: dict) -> str | None:
    """Which reader decided this table's rows, from the artefact's own account.

    Both covered-agreements readers publish the same field for their tolerance
    (`row_attach_pt`), so which one an artefact means is settled by the
    artefact's own description of the reading: only the block reader writes
    `printed_number_anchors`, and a position whose artefact publishes no
    tolerance at all is read by neither.
    """
    if "row_attach_pt" not in qa:
        return None
    return ("the block reader's prefix reach" if "printed_number_anchors" in qa
            else "the number-first window")


def attach_line(qa: dict, reader: str | None = None) -> str | None:
    """The interval the reading left for its own attach tolerance, as one line.

    A reading publishes the tolerance it decided with and the interval its own
    layout left it; the view prints both in the reader's own terms - a run of
    lines absorbed above a number for the block reader, a span placed among the
    numbers around it for the number-first reader, a line captured up to the
    next number for the signatories reader - so the band is read next to the
    rows it decided. An empty interval is named as such rather than shown
    as `[]`: it says the reading asks that placement nowhere on this layout, or
    leaves one side of the decision empty, which is a fact about the reading and
    not an absent one. `None` when the artefact publishes no tolerance.

    Which reader decided is the artefact's own account by default
    (`attach_reader`); a caller passes `reader` when the tolerance belongs to a
    reader the artefact cannot name that way - the signatories table's own
    window lives in top-level `qa`, beside neither reader's anchors. The
    numbers always come from the artefact.
    """
    if reader is None:
        reader = attach_reader(qa)
    if reader is None:
        return None
    tolerance = str(qa["row_attach_pt"])
    if reader == "the block reader's prefix reach":
        decided = (f"a run of lines printed above a number is absorbed as that "
                   f"row's own prefix within {tolerance} pt of the number it "
                   "opens")
        noun = "printed runs"
    elif reader == "the signatories window":
        decided = (f"a line printed within {tolerance} pt above the next "
                   "number is captured up to that number's row")
        noun = "printed lines"
    elif reader == "the number-first window":
        decided = (f"a span printed within {tolerance} pt above a number's "
                   "line belongs to that row")
        noun = "printed spans"
    else:
        raise ValueError(f"unknown attach reader {reader!r}")
    band = qa.get("row_attach_band_pt") or []
    if band:
        interval = "[" + ", ".join(str(value) for value in band) + "]"
    else:
        interval = ("empty - this reading asks that placement nowhere on this "
                    "layout, or leaves one side of the decision empty")
    return (f"*Attach: {decided} ({reader}); the interval this table's own "
            f"{noun} leave it is {interval}.*")


def position_view(record: dict) -> str:
    """One position's covered agreements, as the markdown view reads."""
    slug = str(record.get("slug") or "")
    country = str(record.get("country") or slug)
    rows = record.get("covered_agreements") or []
    lines = [f"# {country} — covered agreements", "",
             f"*corpora/mli/positions/{slug}.json · {len(rows)} row(s)*", ""]
    attach = attach_line((record.get("qa") or {}).get("covered_agreements") or {})
    if attach:
        lines += [attach, ""]
    lines.append("| " + " | ".join(header
                                   for header, _field in POSITION_VIEW_COLUMNS) + " |")
    lines.append("|" + "|".join("---:" if header == "#" else "---"
                                 for header, _field in POSITION_VIEW_COLUMNS) + "|")
    for row in rows:
        cells = [_view_cell(row.get("no")) if field is None
                 else _view_cell(row.get(field))
                 for _header, field in POSITION_VIEW_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines).rstrip() + "\n"


# The columns the signatories markdown view renders, and the artefact field
# each one holds. `#` is the row's own number, which keys both sides of the
# comparison; the rest are compared by value. The audit repeats this map
# rather than importing it, so the comparison stays a comparison.
SIGNATORIES_VIEW_COLUMNS = (
    ("#", None),
    ("Jurisdiction", "jurisdiction"),
    ("Signature", "signature"),
    ("Deposit", "deposit"),
    ("Entry into force", "entry_into_force"),
    ("Page", "page"),
)

# The reader the signatories view names for the tolerance its table was
# decided with. The artefact cannot name it the way positions do - there are
# no `printed_number_anchors` beside it - so the renderer declares it and the
# audit holds the view to the same name.
SIGNATORIES_READER = "the signatories window"


def signatories_view(record: dict) -> str:
    """The signatories table, as the markdown view reads."""
    rows = record.get("rows") or []
    lines = ["# MLI signatories and parties", "",
             "*corpora/mli/signatories-and-parties.json "
             f"· {len(rows)} row(s)*", ""]
    attach = attach_line(record.get("qa") or {}, reader=SIGNATORIES_READER)
    if attach:
        lines += [attach, ""]
    lines.append("| " + " | ".join(header
                                   for header, _field in SIGNATORIES_VIEW_COLUMNS)
                 + " |")
    lines.append("|" + "|".join("---:" if header == "#" else "---"
                                 for header, _field in SIGNATORIES_VIEW_COLUMNS)
                 + "|")
    for row in rows:
        cells = [_view_cell(row.get("no")) if field is None
                 else _view_cell(row.get(field))
                 for _header, field in SIGNATORIES_VIEW_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines).rstrip() + "\n"


def write_signatories(root: Path, signatories_path: Path,
                      family: str = "mli") -> list:
    """Write the signatories table's markdown view under `derived/markdown/...`.

    The view is rendered from the artefact just written, beside the one it
    summarises, so a reader repair that is not republished leaves the view
    visibly behind. The file takes the artefact's own stem: a view whose
    artefact is gone is a view of a table the corpus no longer publishes.
    """
    record = json.loads(Path(signatories_path).read_text(encoding="utf-8"))
    directory = Path(root) / "markdown" / family
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{Path(signatories_path).stem}.md"
    path.write_text(signatories_view(record), encoding="utf-8")
    return [path]


def position_documents(positions_dir: Path) -> dict:
    """{file name: markdown} for every position artefact in `positions_dir`.

    The family's own report (`batch-report.json`) is not a position and has no
    view: it is an account of the family, not one jurisdiction's table.
    """
    out: dict = {}
    for path in sorted(Path(positions_dir).glob("*.json")):
        if path.stem == "batch-report":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        out[f"{path.stem}.md"] = position_view(record)
    return out


def write_positions(root: Path, positions_dir: Path, family: str = "mli") -> list:
    """Write every position's markdown view under `derived/markdown/...`.

    Existing views are removed first, exactly as an edition's views are: a
    `slug.md` whose artefact is gone is a view of a position the family no
    longer publishes, and leaving it behind is the drift this directory exists
    to make visible.
    """
    directory = Path(root) / "markdown" / family / "positions"
    directory.mkdir(parents=True, exist_ok=True)
    for stale in sorted(directory.glob("*.md")):
        stale.unlink()
    written: list = []
    for name, text in position_documents(positions_dir).items():
        path = directory / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
