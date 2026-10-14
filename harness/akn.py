"""Write the span ledger out as an Akoma Ntoso 3.0 document.

The vocabulary is the AKN4UN guidelines' (part 1, "AKN4UN: Modelling Content"),
which are the authority for modelling a UN document, and the mapping from this
project's nodes to its elements is one table:

    projection node       AKN 3.0                          why
    --------------------  -------------------------------  --------------------
    document              <akomaNtoso>/<act>               the instrument
    convention            <preface> + <docTitle>           "TITLE OF THE
                                                           CONVENTION"
    preamble              <preamble> + <p>                 AKN4UN container by
                                                           blocks
    chapter               <chapter> + <num> <heading>      hierarchy
    article               <article> + <num> <heading>      hierarchy
    alternative           <hcontainer name="alternative-A"> a named container,
                                                           not free text
    paragraph (depth 1)   <paragraph> + <content>          a numbered "1."; the
    point (depth 2..n)    <list>/<point> + <content>       introducing words go in
                                                           an <intro> when a lower
                                                           structure follows,
                                                           per AKN4UN's "lists
                                                           inside points or
                                                           indents"
    alinea                <alinea> + <content>             unnumbered text in a
                                                           numbered hierarchy
    note                  <authorialNote placement="bottom"> AKN4UN: "authorial
                                                           footnotes ... are
                                                           marked-up using the
                                                           <authorialNote>
                                                           element", inside the
                                                           block it annotates
    document_boundary     <hcontainer name=...>            "Part Two": where the
                                                           other document starts

Two rules of the standard shape the code below. Elements that exist to *hold*
text hold elements, not text: a hierarchical element carries `<num>` and
`<heading>`, and its words live in a block - `<content>` when the element is a
leaf, `<intro>` when a lower structure follows, because the schema admits the two
only as alternatives (`harness/akn.py::_block`). And nothing in `<meta>` is text
- attributes only - so that stripping the tags leaves exactly the source's words
and nothing else, which is what invariant F2 measures.

Nothing here decides anything. Every number, title, eId and text comes from the
projection of the span ledger; this module only says which element names the
nodes get. If it wanted to invent a title, it would have to write it, and the
document would no longer be a projection of anything.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import ledger
from harness.corpus import AKN_NS, ROOT

# The tags the manifest counts, in the order a reader meets them. Every one of
# them is also a tag `corpus.node_tags` sees, which is what makes invariant F1 a
# comparison rather than a claim.
AKN_UNITS = ("preface", "preamble", "chapter", "article", "hcontainer",
             "paragraph", "list", "point", "alinea", "authorialNote")


def _el(tag: str, **attrs) -> ET.Element:
    """An element with its attributes in a fixed order.

    The tags are plain names and the namespace is declared once, on the root,
    because that is what the standard's documents look like: `xmlns` on
    `<akomaNtoso>` and bare tag names below it. `ElementTree` cannot do that for
    a tree built from `{uri}tag` names - `register_namespace("", ...)` writes the
    URI where the tag should be and `default_namespace` refuses a document that
    has any unqualified attribute, which is all of them - so the declaration is
    made here and the parser resolves it back.
    """
    element = ET.Element(tag)
    for key, value in attrs.items():
        if value is None or value == "":
            continue
        element.set(key, str(value))
    return element


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #

def register_entry(source: str) -> dict:
    """The source's own register entry, or an empty dict if it is not there."""
    import yaml

    path = ROOT / "provenance" / "sources.yaml"
    if not path.exists():
        return {}
    for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        if entry.get("id") == source:
            return dict(entry)
    return {}


def _meta(source: str, edition: str) -> ET.Element:
    """Metadata, all of it read from the register rather than composed.

    The URI of the expression is the URL of the exact bytes this corpus was
    built from, and the date is the register's retrieval date. A made-up URI
    would be a claim about the source that no artefact supports.
    """
    entry = register_entry(source)
    url = str(entry.get("url") or "").strip()
    publisher = str(entry.get("publisher") or "United Nations")
    family_slug = "".join(c if c.isalnum() else "-"
                          for c in publisher.lower()).strip("-") or "publisher"
    retrieved = str(entry.get("retrieved") or "").strip()

    meta = _el("meta")
    identification = _el("identification", source="#itld")
    for name, expression, language in (("FRBRWork", False, False),
                                       ("FRBRExpression", True, True),
                                       ("FRBRManifestation", True, False)):
        group = _el(name)
        group.append(_el("FRBRthis", value=f"/akn/{family_slug}/{source}"
                                          f"{'/eng@' if expression else ''}"))
        group.append(_el("FRBRuri", value=url))
        if retrieved:
            group.append(_el("FRBRdate", date=retrieved, name="retrieval"))
        group.append(_el("FRBRauthor", href="#itld"))
        if name == "FRBRWork":
            # The Work level requires a country, and the standard reserves one
            # value for this publisher: AKN4UN's naming convention fixes the
            # jurisdiction of a United Nations document as `un` (/akn/un/...).
            # Without it the Work is incomplete - the one thing the schema said
            # about the metadata this corpus had not modelled.
            group.append(_el("FRBRcountry", value="un"))
        if language:
            # A language belongs to the Expression, and only to it: the
            # Manifestation describes a carrier, and the schema refuses an
            # FRBRlanguage there. The projection has one language, so the
            # Expression carries one element and the Manifestation none.
            group.append(_el("FRBRlanguage", language="en"))
        identification.append(group)
    meta.append(identification)
    references = _el("references", source="#itld")
    references.append(_el("TLCOrganization", eId=family_slug, href=url,
                          showAs=publisher))
    references.append(_el("TLCOrganization", eId="itld",
                          href=f"#{source}", showAs="International Tax Law Data"))
    meta.append(references)
    return meta


# --------------------------------------------------------------------------- #
# the tree
# --------------------------------------------------------------------------- #

def build(projection: ledger.Node, source: str, edition: str,
          book: ledger.Ledger | None = None) -> ET.Element:
    """The AKN 3.0 document of a projection: `<akomaNtoso><act>...`."""
    root = _el("akomaNtoso")
    root.set("xmlns", AKN_NS)
    # A `hierarchicalStructure` requires @name and admits no @eId: the document
    # is identified by its FRBR metadata, and the act's name is the family this
    # corpus publishes (`un-model`), the only name the projection carries.
    act = _el("act", name=source.rpartition("-")[0] or source)
    act.append(_meta(source, edition))
    body = _el("body", eId=f"{source}__body")
    preface: ET.Element | None = None
    preamble: ET.Element | None = None

    # The `<act>` child order is the standard's (meta, preface, preamble, body),
    # and the projection's is not: its `preamble` is a child of the `convention`
    # node, because that is where the document puts it - the title, the naming
    # sentence, then the preamble. So the preamble is lifted out wherever it
    # sits and the three slots are filled in the order the standard wants.
    preamble = next((node for node in projection.walk()
                     if node.tag == "preamble"), None)
    for child in projection.children:
        if child.tag == "front_matter":
            # The book's own matter: every span of it was dropped by rule, so
            # the node has no text and nothing to emit. It is not silently
            # absent - the manifest's `missing` list names it and counts it.
            continue
        if child.tag == "preamble":
            continue
        if child.tag == "convention":
            preface = _preface(child, book)
            continue
        body.append(_element(child, book))

    if preface is not None:
        act.append(preface)
    if preamble is not None:
        act.append(preamble_element(preamble, book))
    act.append(body)
    root.append(act)
    return root


def _preface(convention: ledger.Node, book) -> ET.Element:
    """The instrument's own heading matter, before the preamble."""
    preface = _el("preface", eId=convention.eId)
    title = convention.text(book) or convention.title
    if title:
        line = _el("p")
        line.append(_text("docTitle", convention.title or title))
        preface.append(line)
    for child in convention.children:
        if child.tag == "preamble":
            continue
        preface.append(_element(child, book, container_text=True))
    return preface


def preamble_element(node: ledger.Node, book) -> ET.Element:
    """`<preamble>`, whose unnumbered sentences are blocks, not alineas.

    AKN4UN puts a preamble's text in blocks; this projection's `alinea` nodes
    are the same idea (text with no marker of its own), and the writer is where
    the difference between "a container's block" and "a hierarchy's alinea"
    lives. The `<heading>` is the line the source prints above them.
    """
    element = _el("preamble", eId=node.eId)
    if node.title:
        # A preamble is a container of blocks, not a hierarchy, so it admits no
        # `heading`: the line the source prints above the recitals is one of its
        # blocks. The words are unchanged; the element is the one the standard
        # allows them in.
        element.append(_text("p", node.title))
    for child in node.children:
        element.append(_element(child, book, container_text=True))
    return element


def _element(node: ledger.Node, book, container_text: bool = False) -> ET.Element:
    """One element for one projection node, with its children inside it."""
    tag = node.tag
    if tag == "chapter" or tag == "article":
        element = _el(tag, eId=node.eId)
        if node.number:
            element.append(_text("num", node.number))
        if node.title:
            element.append(_text("heading", node.title))
        _children(element, node, book)
        return element
    if tag == "alternative":
        element = _el("hcontainer", eId=node.eId, name=_name(node))
        label = node.text(book) or node.number
        if label:
            element.append(_text("num", label))
        _children(element, node, book)
        return element
    if tag == "paragraph" or tag == "point":
        element = _el(tag, eId=node.eId)
        if node.number:
            element.append(_text("num", node.number))
        _block(element, node, book)
        return element
    if tag == "alinea":
        element = _el("p" if container_text else "alinea", eId=node.eId)
        if container_text:
            element.text = node.text(book)
            return element
        element.append(_content(node, book))
        return element
    if tag == "note":
        note = _element_note(node, book)
        if not container_text:
            return note
        # A note is a subFlow: the standard admits it inside a block, never as a
        # child of a container. In a preface or a preamble it therefore stands
        # in the block that carries it, which is where a reader meets it anyway.
        holder = _el("p")
        holder.append(note)
        return holder
    if tag == "document_boundary":
        # "Part Two" is not part of the Convention: it is where a different
        # document begins. It is kept as a named container so that the boundary
        # is a node in the corpus rather than an absence, and so its words are
        # still in the text (invariant F3 counts a dropped span, and this one is
        # kept).
        element = _el("hcontainer", eId=node.eId, name="document-boundary")
        element.append(_text("num", node.text(book)))
        return element
    raise ledger.RuleError(
        f"the projection holds a node of kind {tag!r} and the AKN writer has no "
        f"element for it: a node the corpus cannot express is a modelling "
        f"decision somebody has to make, not a tag to guess at")


def _element_note(node: ledger.Node, book) -> ET.Element:
    """A note as the standard models it: a subFlow inside the block it annotates."""
    element = _el("authorialNote", eId=node.eId, marker=node.number,
                  placement="bottom")
    element.append(_text("p", _note_text(node, book)))
    return element


def _children(parent: ET.Element, node: ledger.Node, book) -> None:
    _append_children(parent, node.children, book)


def _block(parent: ET.Element, node: ledger.Node, book) -> None:
    """A hierarchy's own words and its children, in the shape the schema admits.

    A `hierarchy` element may hold *either* its own blocks or the lower
    hierarchical elements below it, never both: a paragraph that introduced a
    list carried a `<content>` and the `<list>` beside it, which is exactly what
    the schema refused. The standard's own answer for the introducing words is
    `<intro>` - the block a lower structure hangs from - so a node that has
    children keeps its words in an `<intro>` and its children follow it. A node
    with nothing under it keeps its words in `<content>`, the final container a
    hierarchy ends in.

    A note is a subFlow and not a hierarchical element (`ANsubFlow` is reached
    through the inline content model, not through `hierElements`), so it lives
    inside the block that carries the words rather than beside it. That is also
    where a footnote is read.
    """
    notes = [child for child in node.children if child.tag == "note"]
    below = [child for child in node.children if child.tag != "note"]
    text = node.text(book)
    if below:
        if text or notes:
            intro = _el("intro")
            block = _text("p", text)
            for note in notes:
                block.append(_element_note(note, book))
            intro.append(block)
            parent.append(intro)
        _append_children(parent, below, book)
        return
    content = _el("content")
    block = _text("p", text)
    for note in notes:
        block.append(_element_note(note, book))
    content.append(block)
    parent.append(content)


def _append_children(parent: ET.Element, children: list, book) -> None:
    """Children in order, with the runs of points wrapped in their lists.

    AKN4UN's rule is that a list is a list and an item is a point of one:
    "Lists inside points or indents". A point is therefore never a bare child of
    a paragraph here - it stands inside a `<list>` - and a run of points is one
    list. Two runs stay two lists, which is how the definitions of article 29
    keep (a)..(j) separate from the (i)(ii) that item (i) carries.
    """
    pending: list = []

    def flush() -> None:
        if not pending:
            return
        element = _el("list")
        for point in pending:
            element.append(_element(point, book))
        parent.append(element)
        pending.clear()

    for child in children:
        if child.tag == "point":
            pending.append(child)
            continue
        flush()
        parent.append(_element(child, book))
    flush()


def _content(node: ledger.Node, book) -> ET.Element:
    """This node's own words, in the block AKN4UN requires them in."""
    content = _el("content")
    content.append(_text("p", node.text(book)))
    return content


def _name(node: ledger.Node) -> str:
    """The `@name` of an hcontainer, from the label the rule matched."""
    title = (node.title or "").strip()
    if not title:
        raise ledger.RuleError(
            f"{node.eId}: an alternative branch with no label cannot be named; "
            f"R-ALTERNATIVE-LABEL declares the names it may take")
    # The letter keeps its case: the two branches are `alternative-A` and
    # `alternative-B`, exactly as the rule's `name_pattern` declares, and a
    # lowercased name is a name no check written against the rule would find.
    return title.replace(" ", "-")


def _note_text(node: ledger.Node, book) -> str:
    """A note's words, without the marker it is cited by."""
    text = node.text(book).lstrip("\u2009\u2004 \t")
    number = node.number
    if number and text.startswith(number):
        text = text[len(number):].lstrip("\u2009\u2004 \t")
    return text


def _text(tag: str, value: str) -> ET.Element:
    element = _el(tag)
    element.text = value or ""
    return element


# --------------------------------------------------------------------------- #
# artefacts
# --------------------------------------------------------------------------- #

def serialize(root: ET.Element) -> bytes:
    """The document as bytes: fixed indentation, no timestamp, no host name.

    `indent` and a fixed declaration are all the formatting there is: no
    timestamp, no host name, no dictionary order in an output path, so two runs
    on one input produce one file (F7).
    """
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def units(root: ET.Element) -> dict:
    """How many of each unit the document contains, counted as written."""
    counts: dict = {}
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag in AKN_UNITS:
            counts[tag] = counts.get(tag, 0) + 1
    return {tag: counts[tag] for tag in AKN_UNITS if tag in counts}


def counts_of(book: ledger.Ledger, rule: str) -> int:
    """How many spans a rule decided, for the manifest's account of losses."""
    return sum(1 for _span, decided in book.kept if decided == rule) \
        + sum(1 for _span, decided, _why in book.dropped if decided == rule)


def missing(projection: ledger.Node, source: str, book: ledger.Ledger) -> list:
    """What the corpus does not carry, named and given a reason.

    Invariant F1: "every unit that is not extracted appears in an explicit
    `missing` list with a reason. Silence is never a valid outcome." The two
    entries are the two declared drops that are whole documents: the book's own
    matter, and the Commentaries. Neither is an accident - both are rules with
    an id, and this is where the corpus says so in one place.
    """
    front = sum(1 for _span, rule in book.kept if rule == "R-FRONT-MATTER") \
        + sum(1 for _span, rule, _why in book.dropped if rule == "R-FRONT-MATTER")
    commentary = sum(1 for _span, rule, _why in book.dropped
                     if rule == "R-COMMENTARY")
    boundary = next((node for node in projection.walk()
                     if node.tag == "document_boundary"), None)
    return [
        {"id": f"{source}__front_matter",
         "reason": (f"the book's own matter (cover, contents, foreword, "
                    f"introduction): {front} span(s) dropped by R-FRONT-MATTER, "
                    f"before the instrument begins")},
        {"id": f"{source}__commentaries",
         "reason": (f"Part Two, the Commentaries: {commentary} span(s) dropped "
                    f"by R-COMMENTARY as a separate document, after the boundary "
                    f"on page {boundary.spans[0].page if boundary else '?'}")},
    ]


def manifest(root: ET.Element, projection: ledger.Node, source: str, family: str,
             edition: str, book: ledger.Ledger, akn_sha: str,
             ledger_sha: str) -> dict:
    """The counts, the losses and the digests of one edition's corpus."""
    entry = register_entry(source)
    data = {
        "format": "akn manifest v1",
        "source": source,
        "family": family,
        "edition": edition,
        "akn": f"model-{edition}.akn.xml",
        "ledger": f"model-{edition}.spans.jsonl",
        "nodes": f"model-{edition}.nodes.jsonl",
        "source_file": entry.get("file") or "",
        "source_url": str(entry.get("url") or "").strip(),
        "source_sha256": entry.get("sha256") or "",
        "source_pages": entry.get("pages"),
        "akn_sha256": akn_sha,
        "ledger_sha256": ledger_sha,
        "units": units(root),
        "missing": missing(projection, source, book),
    }
    return data


def write(target: Path, source: str, family: str, edition: str,
          projection: ledger.Node, book: ledger.Ledger) -> tuple:
    """Write `model-<edition>.akn.xml` and `model-<edition>.manifest.json`.

    The counts in the manifest are checked against the file that was just
    written, not against the tree that produced it: a comparison of a number
    with itself proves nothing, and a writer that emitted a different tree from
    the one it counted would otherwise be green for ever.
    """
    root = build(projection, source, edition, book)
    akn_path = target / f"model-{edition}.akn.xml"
    akn_path.write_bytes(serialize(root))

    from harness import corpus as corpus_mod

    observed = corpus_mod.node_tags(akn_path)
    declared = units(root)
    for tag, count in declared.items():
        if observed.get(tag, 0) != count:
            raise ledger.RuleError(
                f"{source}: the writer counted {count} {tag} and the file it "
                f"wrote holds {observed.get(tag, 0)}: the manifest would be a "
                f"claim about a document that does not exist")
    ledger_path = target / f"model-{edition}.spans.jsonl"
    ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest() \
        if ledger_path.exists() else ""
    data = manifest(root, projection, source, family, edition, book,
                    hashlib.sha256(akn_path.read_bytes()).hexdigest(), ledger_sha)
    manifest_path = target / f"model-{edition}.manifest.json"
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True,
                                       ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return akn_path, manifest_path


def describe(root: ET.Element) -> str:
    """A one-line account of an AKN document, for a report or a console."""
    counted = units(root)
    return " · ".join(f"{count} {tag}" for tag, count in counted.items())
