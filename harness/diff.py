"""The edition diff: what changed between two editions of one family.

A view, not a reading. A diff read from the
two PDFs a second time is where the artefacts come in: such a
report showed the 2017 edition gaining "Articles 8 and 9" in the middle of a
sentence, which is a page's running head, and it showed a fourth paragraph that
was a footnote fragment. Both were in the corpus as well, which is how a viewer
can be wrong *and* consistent.

So this module does not open a PDF. It compares the two editions the corpus
holds, node by node, and quotes the nodes' own text - `corpora/un-model/<edition>/
model-<edition>.akn.xml`, the product of the reading - so a difference here is a
difference the corpus has, and a change reported that the corpus does not have is
a failure of the *view*, not of the reading.

What the diff compares, and what it deliberately does not:

* **Units** are `paragraph`, `point` and `alinea` nodes with their own eId, and
  their text is the node's own words - a note nested inside a unit is *not* part
  of the unit's text, because it is a node of its own with its own eId, and a
  change in a footnote reported as a change in a paragraph is exactly how d11's
  fragment became a "paragraph added" in a report built from a second reading.
* **Notes** are compared separately, under `authorialNote`.
* **Alternatives** are compared by their `@name` - the branches the corpus holds
  as `hcontainer` (`alternative-A`, `alternative-B`).
* An article is **modified** when any of the three differs. Nothing is truncated:
  a quoted unit is the whole unit, because a view that cut a paragraph at 1200
  characters would be the defect P1 exists to prevent, one layer up.

The report is a markdown document (what a reader wants) and a JSON one (what the
harness compares), written under `derived/reports/`.
"""
from __future__ import annotations

import difflib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import corpus

UNIT_TAGS = ("paragraph", "point", "alinea")
NOTE_TAG = "authorialNote"
AKN = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"

# How a family's name is written in the report's title. Known families are named
# the way their publishers name them; anything else is written as it is stored,
# which is at least the corpus' own name for it.
FAMILIES = {"un-model": "UN Model", "mli": "MLI"}

# The gap difflib is allowed to close without calling it a change. Zero: a diff
# that decided two different paragraphs were "close enough" would be this
# project's own defect - an inference where a measurement was available.
MATCH_NOISE = 0


def _tag(el) -> str:
    return el.tag.split("}")[-1]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _own_text(el, skip=(NOTE_TAG,)) -> str:
    """An element's own words, excluding the subtrees named in `skip`.

    `itertext()` would do it in one line and would include a note's text inside
    the paragraph that carries it, which is the mixture this module exists to
    avoid.
    """
    pieces = [el.text or ""]

    def walk(node) -> None:
        for child in node:
            if _tag(child) in skip:
                continue
            pieces.append(child.text or "")
            walk(child)
            pieces.append(child.tail or "")

    walk(el)
    return _flat("".join(pieces))


def _label(tag: str, number: str) -> str:
    """How a unit is named in the report, from the number the source prints."""
    stripped = (number or "").strip()
    if stripped.endswith("."):
        stripped = stripped[:-1]
    return f"{tag} {stripped}".strip()


def _article_number(printed: str, eid: str) -> str:
    """The article's number as its own `num` prints it, without the word.

    "Article 12B" is the element's label and "12B" is the number; the report
    writes "Article 12B" once, from the number, so that a title read from the
    source cannot arrive as "Article Article 12B".
    """
    stripped = re.sub(r"^Article\s+", "", (printed or "").strip())
    return stripped or eid.replace("art_", "")


def edition(path: Path) -> dict:
    """One edition as the diff needs it: its articles, units, notes and branches.

    Everything comes from the AKN document the corpus holds, in document order,
    so the diff's notion of "the text of article 4" is the corpus' notion of it
    and not a third one assembled here.
    """
    root = ET.parse(path).getroot()
    articles: dict = {}
    order: list = []
    for el in root.iter():
        if _tag(el) != "article" or not el.get("eId"):
            continue
        eid = el.get("eId")
        number, heading = "", ""
        for child in el:
            if _tag(child) == "num" and not number:
                number = _flat("".join(child.itertext()))
            elif _tag(child) == "heading" and not heading:
                heading = _flat("".join(child.itertext()))
        units, notes, branches = [], [], []
        for node in el.iter():
            if node is el:
                continue
            tag = _tag(node)
            if tag in UNIT_TAGS and node.get("eId"):
                printed = ""
                for child in node:
                    if _tag(child) == "num":
                        printed = _flat("".join(child.itertext()))
                        break
                units.append({"eId": node.get("eId"), "tag": tag,
                              "number": printed,
                              "label": _label(tag, printed),
                              "text": _own_text(node)})
            elif tag == NOTE_TAG and node.get("eId"):
                # The marker is an attribute here, not a `num` child: the corpus'
                # notes are anchored where the source prints its marker, and the
                # marker is what a reader can find on the page.
                marker = _flat(node.get("marker") or "")
                notes.append({"eId": node.get("eId"), "tag": NOTE_TAG,
                              "number": marker,
                              "label": f"note {marker}".strip(),
                              "text": _flat("".join(node.itertext()))})
            elif tag == "hcontainer" and (node.get("name") or "").startswith("alternative"):
                branches.append(node.get("name"))
        articles[eid] = {"eId": eid, "number": _article_number(number, eid),
                         "heading": heading, "units": units, "notes": notes,
                         "alternatives": branches}
        order.append(eid)
    return {"file": path, "articles": articles, "order": order}


def _by_eid(items: list) -> dict:
    return {item["eId"]: item for item in items}


def _unit_changes(left: list, right: list, renumber: bool = False) -> dict:
    """What happened to one kind of node between the two editions.

    The identity of a node is its eId, and its text is its own words (a unit's
    text before the notes hanging from it; a note's text in full). Two nodes with
    the same eId and the same words are the same node, whatever else moved.

    Notes carry one more thing worth telling apart: their marker is numbered per
    document, so inserting one note renumbers the rest, and a note that only moved
    number would otherwise be reported twice - once as removed, once as added. The
    `renumber` switch matches those pairs by their text, which is the only thing
    that did not change about them.
    """
    old, new = _by_eid(left), _by_eid(right)
    added = [new[e] for e in new if e not in old]
    removed = [old[e] for e in old if e not in new]
    renumbered: list = []
    if renumber:
        by_text: dict = {}
        for item in removed:
            by_text.setdefault(item["text"], []).append(item)
        still_added: list = []
        for item in added:
            candidates = by_text.get(item["text"]) or []
            if candidates:
                was = candidates.pop(0)
                removed.remove(was)
                renumbered.append({"eId": item["eId"],
                                   "old_marker": was["number"],
                                   "new_marker": item["number"],
                                   "text": item["text"]})
            else:
                still_added.append(item)
        added = still_added
    changed = [{"eId": e, "label": new[e]["label"],
                "old": old[e]["text"], "new": new[e]["text"]}
               for e in new if e in old
               and (old[e].get("text") or "") != (new[e].get("text") or "")]
    return {"added": added, "removed": removed, "changed": changed,
            "renumbered": renumbered}


def compare(family: str, old: str, new: str, root: Path | None = None) -> dict:
    """The whole comparison: both editions' identity, and every difference.

    The identity is read from the two manifests, so the report says which corpus
    files and which source bytes it is a view of. A diff that does not name its
    two inputs cannot be checked against them, and this one exists to be checked.
    """
    base = Path(root or corpus.ROOT)
    sides = {}
    for edition_name in (old, new):
        found = corpus.akn(base, family, edition_name)
        if len(found) != 1:
            raise ValueError(
                f"{family}/{edition_name}: exactly one AKN document is needed to "
                f"diff this edition, found {len(found)}")
        manifest = corpus.manifest(base, family, edition_name)
        data = corpus.load_json(manifest) if manifest else {}
        read = edition(found[0])
        sides[edition_name] = {
            "edition": edition_name,
            "family": family,
            "akn": str(found[0].relative_to(base)),
            "akn_sha256": data.get("akn_sha256") or "",
            "ledger_sha256": data.get("ledger_sha256") or "",
            "source": data.get("source") or "",
            "source_sha256": data.get("source_sha256") or "",
            "source_url": data.get("source_url") or "",
            "source_pages": data.get("source_pages") or 0,
            "articles": read["articles"],
        }
    first, second = sides[old], sides[new]
    left, right = first["articles"], second["articles"]

    added = [right[e] for e in right if e not in left]
    removed = [left[e] for e in left if e not in right]
    modified, unchanged = [], []
    for eid in [e for e in right if e in left]:
        a, b = left[eid], right[eid]
        units = _unit_changes(a["units"], b["units"])
        notes = _unit_changes(a["notes"], b["notes"], renumber=True)
        branches_added = [n for n in b["alternatives"] if n not in a["alternatives"]]
        branches_removed = [n for n in a["alternatives"] if n not in b["alternatives"]]
        retitled = a["heading"] != b["heading"]
        if units["added"] or units["removed"] or units["changed"] or notes["added"] \
                or notes["removed"] or notes["changed"] or notes["renumbered"] \
                or branches_added or branches_removed or retitled:
            modified.append({
                "eId": eid, "number": b["number"], "heading": b["heading"],
                "old_heading": a["heading"], "retitled": retitled,
                "units": units, "notes": notes,
                "alternatives_added": branches_added,
                "alternatives_removed": branches_removed,
            })
        else:
            unchanged.append(b["number"])
    counts = {
        "articles": len(right),
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "unchanged": len(unchanged),
    }
    units = {
        "changed": sum(len(article["units"]["changed"]) for article in modified),
        "added": sum(len(article["units"]["added"]) for article in modified),
        "removed": sum(len(article["units"]["removed"]) for article in modified),
        "notes_changed": sum(len(article["notes"]["changed"]) for article in modified),
        "notes_added": sum(len(article["notes"]["added"]) for article in modified),
        "notes_removed": sum(len(article["notes"]["removed"]) for article in modified),
        "notes_renumbered": sum(len(article["notes"]["renumbered"])
                                for article in modified),
        "retitled": sum(1 for article in modified if article["retitled"]),
        "alternatives_added": sum(len(article["alternatives_added"])
                                  for article in modified),
        "alternatives_removed": sum(len(article["alternatives_removed"])
                                    for article in modified),
    }
    return {
        "family": family,
        "from": {k: v for k, v in first.items() if k != "articles"},
        "to": {k: v for k, v in second.items() if k != "articles"},
        "counts": counts,
        "units": units,
        "added": [{"eId": a["eId"], "number": a["number"],
                   "heading": a["heading"]} for a in added],
        "removed": [{"eId": a["eId"], "number": a["number"],
                     "heading": a["heading"]} for a in removed],
        "modified": modified,
        "unchanged": {"count": len(unchanged), "articles": unchanged},
        "qa": {
            "read_from": "the two editions' AKN documents, not from the PDFs",
            "unit_kinds": list(UNIT_TAGS),
            "notes": ("compared apart from the units that carry them: a note is "
                      "a node with its own eId, and a change in one is not a "
                      "change in the paragraph it hangs from"),
            "alternatives": "compared by hcontainer @name (alternative-A/B)",
            "truncation": "none: every quoted unit is the whole unit",
            "modified_means": ("a unit, a note, an alternative branch or a "
                               "heading differs between the two editions"),
        },
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def _inline(old: str, new: str) -> str:
    """The new text, with what it dropped struck through and what it added bold.

    Word by word, and with no tolerance (MATCH_NOISE): a diff that decided two
    different paragraphs were "close enough" to call equal would be an inference
    where a measurement was available, and this corpus does not do that.
    """
    left, right = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    pieces: list = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            pieces.append(" ".join(right[j1:j2]))
        elif op == "delete":
            pieces.append(f"~~{' '.join(left[i1:i2])}~~")
        elif op == "insert":
            pieces.append(f"**{' '.join(right[j1:j2])}**")
        else:
            pieces.append(f"~~{' '.join(left[i1:i2])}~~ "
                          f"**{' '.join(right[j1:j2])}**")
    return " ".join(piece for piece in pieces if piece.strip())


def _side(data: dict) -> str:
    """One edition's identity, as the report's header prints it."""
    pages = f", {data['source_pages']} pages" if data.get("source_pages") else ""
    return (f"`{data['source']}` · `{data['akn']}` (sha256 "
            f"{data['akn_sha256'][:16]}…, source sha256 "
            f"{data['source_sha256'][:16]}…{pages})")


def render(data: dict) -> str:
    """The report, in markdown, as a function of the comparison alone."""
    counts, units = data["counts"], data["units"]
    lines: list = []
    add = lines.append
    add(f"# {FAMILIES.get(data['family'], data['family'])} "
        f"{data['from']['edition']} → {data['to']['edition']}: structural diff")
    add("")
    add(f"From {_side(data['from'])}")
    add("")
    add(f"To {_side(data['to'])}")
    add("")
    add(f"Articles: {counts['articles']} · added {counts['added']} · "
        f"removed {counts['removed']} · modified {counts['modified']} · "
        f"unchanged {counts['unchanged']}")
    add(f"Units: {units['changed']} changed · {units['added']} added · "
        f"{units['removed']} removed · notes {units['notes_changed']} changed, "
        f"{units['notes_added']} added, {units['notes_renumbered']} renumbered · "
        f"headings retitled {units['retitled']} · alternative branches added "
        f"{units['alternatives_added']}")
    add("")
    add(f"*This is a view of the corpus, not a second reading of the two PDFs: "
        f"every quotation below is a node's own text, taken from "
        f"`{data['to']['akn']}` and `{data['from']['akn']}`. An article is "
        f"**modified** when a unit ({', '.join(data['qa']['unit_kinds'])}), a "
        f"note, an alternative branch or a heading differs. Nothing is "
        f"truncated.*")
    add("")

    if data["added"]:
        add(f"## Added ({len(data['added'])})")
        add("")
        for article in data["added"]:
            add(f"- **Article {article['number']} — {article['heading']}** "
                f"(`{article['eId']}`, new in {data['to']['edition']})")
        add("")
    if data["removed"]:
        add(f"## Removed ({len(data['removed'])})")
        add("")
        for article in data["removed"]:
            add(f"- **Article {article['number']} — {article['heading']}** "
                f"(`{article['eId']}`, not in {data['to']['edition']})")
        add("")

    add(f"## Modified ({len(data['modified'])})")
    add("")
    for article in data["modified"]:
        add(f"### Article {article['number']} — {article['heading']}")
        if article["retitled"]:
            add(f"- **heading** ~~{article['old_heading']}~~ → "
                f"**{article['heading']}**")
        for branch in article["alternatives_added"]:
            add(f"- **branch `{branch}`** added")
        for branch in article["alternatives_removed"]:
            add(f"- **branch `{branch}`** removed")
        for changed in article["units"]["changed"]:
            add(f"- **{changed['label']}** changed: "
                f"{_inline(changed['old'], changed['new'])}")
        for unit in article["units"]["added"]:
            add(f"- **{unit['label']}** added: {unit['text']}")
        for unit in article["units"]["removed"]:
            add(f"- **{unit['label']}** removed: {unit['text']}")
        for changed in article["notes"]["changed"]:
            add(f"- **{changed['label']}** changed: "
                f"{_inline(changed['old'], changed['new'])}")
        for moved in article["notes"]["renumbered"]:
            add(f"- **note {moved['old_marker']} → note {moved['new_marker']}** "
                f"renumbered, same text")
        for note in article["notes"]["added"]:
            add(f"- **{note['label']}** added: {note['text']}")
        for note in article["notes"]["removed"]:
            add(f"- **{note['label']}** removed: {note['text']}")
        add("")

    if data["unchanged"]["count"]:
        numbers = ", ".join(data["unchanged"]["articles"])
        add(f"## Unchanged ({data['unchanged']['count']})")
        add("")
        add(f"Articles {numbers} hold the same text, note for note and branch "
            f"for branch, in both editions.")
        add("")
    return "\n".join(lines).rstrip() + "\n"


def name(family: str, old: str, new: str) -> str:
    return f"diff-{family}-{old}-{new}"


def documents(family: str, old: str, new: str, root: Path | None = None) -> dict:
    """{file name: the report} for one pair of editions, as data and as markdown."""
    data = compare(family, old, new, root)
    return {f"{name(family, old, new)}.md": render(data),
            f"{name(family, old, new)}.json": json.dumps(
                data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"}


def write(derived: Path, family: str, old: str, new: str,
          root: Path | None = None) -> list:
    """Write both forms of the report under `<derived>/reports/`."""
    directory = Path(derived) / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    written: list = []
    for file_name, text in documents(family, old, new, root).items():
        path = directory / file_name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
