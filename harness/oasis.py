"""Validate every committed AKN document against the vendored OASIS schema.

The strongest form of invariant F7 is not "the same bytes come out twice": it is
that the document the pipeline writes is the document the standard describes.
Every artefact this corpus publishes says "AKN 3.0", and until this module
existed that claim rested on the vocabulary of `harness/akn.py` and on nothing
that could say no - the register said so in as many words ("vendored and
validated against, not yet possible: the vendor/ directory and lxml are both
absent").

Two rules make this a check rather than a decoration.

**The schema is vendored, and the validator reaches nothing else.** The pair
under `vendor/akn/` is committed, pinned file by file in
`provenance/akn-xsd.sha256`, and read through a resolver that refuses any
location but a sibling of the schema. The AKN schema imports the XML namespace
schema as `./xml.xsd`; the other copy of that file in the world is a W3C URL, and
a validator that fetched it would check this corpus against bytes that are in
nobody's commit. A run that would reach outside `vendor/` fails here instead.

**What the schema says is reported as it is, and the state is declared.** The
committed documents do not all conform today. That is a finding, not a footnote:
the board prints it, `python -m harness oasis` names it class by class and
document by document, and the classes known to be there are written in
`fixtures/oasis-conformance.yaml`. A class that gets fixed has to be taken out of
that file, and a new one has to be added: the command is red in both directions,
which is what keeps the declaration from becoming the place a defect goes to be
forgotten.

What is deliberately *not* here: a third copy of a linter. The schema is the
authority on shape, and this module only asks it. What the corpus promises about
its *content* - completeness, no insertion, traceability - is F1 to F6, and a
schema cannot answer any of them.
"""
from __future__ import annotations

import re
from pathlib import Path

from harness import corpus

SCHEMA = Path("vendor") / "akn" / "akomantoso30.xsd"
MANIFEST = Path("provenance") / "akn-xsd.sha256"
DECLARATION = Path("fixtures") / "oasis-conformance.yaml"

_NAMESPACE = re.compile(r"\{[^}]*\}")
_EXPECTED = re.compile(r"\s+Expected is one of \(.*", re.S)


class SchemaNotVendored(RuntimeError):
    """The schema, or the library that reads it, is not here.

    Raised instead of validating against something else: a check that falls back
    to a downloaded schema, or to no schema at all, is a check that cannot say
    no, and "not possible" would go back to being unstated.
    """


def schema_path(root: Path | None = None) -> Path:
    """Where the vendored schema is, relative to the repository it belongs to."""
    return Path(root or corpus.ROOT) / SCHEMA


def manifest_path(root: Path | None = None) -> Path:
    """The file that pins the vendored bytes, one `hash  path` line per file."""
    return Path(root or corpus.ROOT) / MANIFEST


def declaration_path(root: Path | None = None) -> Path:
    """The violations this repository declares it still has."""
    return Path(root or corpus.ROOT) / DECLARATION


def documents(root: Path | None = None) -> list[Path]:
    """Every AKN document the corpus holds, in path order."""
    return corpus.akn(root)


def violation_class(message: str) -> str:
    """One violation's class: the schema's own words, minus what is not the class.

    Two parts of a libxml message are not about the class and are taken out: the
    namespace URI (the local name is what a reader has to fix) and the list of
    what the schema did expect, which names a dozen elements and reads identically
    for every instance of the class. What is left - ``Element 'list': This element
    is not expected.`` - is stable across documents, which is what makes it a key
    a declaration can be written against and compared run after run.
    """
    collapsed = " ".join(str(message).split())
    return _EXPECTED.sub("", _NAMESPACE.sub("", collapsed)).strip()


def shown(path: Path) -> str:
    """How this module names a file: what it is inside the repository, or its name.

    The board prints the reason a check could not run, and a document this
    project generates must not describe the machine it was generated on
    (invariant F14). A clone lives at a different absolute path on every desk,
    so the path that goes into a message is the part that is about the
    repository - `vendor/akn/akomantoso30.xsd` - and a file from outside it is
    named by its own name, which is enough to find and not enough to locate.
    """
    try:
        return path.relative_to(corpus.ROOT).as_posix()
    except ValueError:
        return path.name


def _lxml():
    """lxml, or a stated failure - never a silent pass.

    Imported here and not at module import time, the way `harness/ledger.py`
    imports PyMuPDF: everything in this repository except the schema validation
    and the PDF reader works without either library, and a board that refused to
    render because a validator could not run would be a worse failure than the
    one it reports.
    """
    try:
        from lxml import etree
    except ImportError as error:                      # pragma: no cover - env
        raise SchemaNotVendored(
            "lxml is not installed, and the OASIS validation is not something "
            "this module will answer by guessing: install the pinned set "
            "(`pip install -r requirements.txt`)"
        ) from error
    return etree


def _schema_locations(path: Path) -> list[str]:
    """Every ``schemaLocation`` the schema at ``path`` names, in document order.

    Read with the standard library and not with lxml: this is a look at what the
    file asks for, not a validation, and it has to work before any schema
    compiler has been handed anything.
    """
    from xml.etree import ElementTree as ET

    root = ET.parse(str(path)).getroot()
    out: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] not in ("import", "include"):
            continue
        location = element.get("schemaLocation")
        if location:
            out.append(location)
    return out


def _vendored_or_absent(path: Path) -> Path:
    """The schema file, or the stated failure that says why nothing can be asked."""
    path = Path(path)
    if not path.is_file():
        raise SchemaNotVendored(
            f"{shown(path)} is not here: the AKN 3.0 schema is vendored "
            f"(`vendor/akn/`) and pinned in `{MANIFEST.as_posix()}`")
    return path


def vendored_closure(path: Path) -> list[Path]:
    """The schema and every schema it imports, each of which must be vendored.

    Run *before* anything is compiled, and that order is the whole point. The
    vendored AKN schema imports the XML namespace schema, and a schema compiler
    handed a location it cannot find goes and gets it: a validation that fetched
    `xml.xsd` from the W3C would be checking this corpus against bytes that are
    in nobody's commit, and it would do it silently, on whichever machine had a
    network that day. Requiring every import to be a sibling turns that into a
    stated failure, and it is also what makes the check answerable with no
    network at all.
    """
    path = _vendored_or_absent(Path(path))
    found = [path]
    for location in _schema_locations(path):
        sibling = path.parent / str(location).rsplit("/", 1)[-1]
        if not sibling.is_file():
            raise SchemaNotVendored(
                f"{shown(path)} imports {location}, which is not vendored "
                f"beside it: a validation that fetched it would check this "
                f"corpus against bytes no commit holds")
        found.extend(vendored_closure(sibling))
    return found


def _tree(path: Path):
    """A schema document, read with a resolver that never leaves its directory."""
    etree = _lxml()
    path = _vendored_or_absent(Path(path))
    vendored = path.parent

    class VendoredOnly(etree.Resolver):
        """Every ``schemaLocation`` resolves inside the schema's own directory.

        The vendored `akomantoso30.xsd` imports the XML namespace schema as
        `./xml.xsd`, so the pair is self-contained. Anything else - a URL, an
        absolute path, a file that was never vendored - is refused rather than
        fetched: a validation that reached the network would depend on what the
        network served that day, which is exactly the machine-dependence F7
        exists to forbid.
        """

        def resolve(self, url, public_id, context):
            candidate = vendored / str(url).rsplit("/", 1)[-1]
            if candidate.is_file():
                return self.resolve_filename(str(candidate), context)
            raise SchemaNotVendored(
                f"the schema asks for {url}, which is not vendored: "
                f"{candidate.name} does not exist. A validation that fetched it "
                f"would check this corpus against bytes no commit holds")

    parser = etree.XMLParser()
    parser.resolvers.add(VendoredOnly())
    return etree.parse(str(path), parser)


def load_schema(path: Path | None = None):
    """The compiled schema, built from the vendored pair and from nothing else.

    The closure is checked first and the compiled schema second, and a compiler
    that refuses the vendored bytes is reported as :class:`SchemaNotVendored`
    rather than as an lxml error: in both cases the answer to "does this corpus
    conform" is "this question cannot be asked here", which is a different
    answer from "no", and the board prints the difference.
    """
    etree = _lxml()
    target = Path(path) if path else schema_path()
    vendored_closure(target)
    try:
        return etree.XMLSchema(_tree(target))
    except SchemaNotVendored:
        raise
    except etree.Error as error:
        raise SchemaNotVendored(
            f"the vendored schema could not be compiled: {error}") from error


def violations(document: Path, schema=None) -> list[str]:
    """Every violation the schema reports for one document, as ``line N: ...``.

    An empty list means the schema accepted the document, and nothing else does:
    a document that cannot be parsed raises rather than returning no violations,
    because "could not be read" printed as "conforms" is the one output this
    module must never produce.
    """
    etree = _lxml()
    compiled = schema if schema is not None else load_schema()
    tree = etree.parse(str(document))
    if compiled.validate(tree):
        return []
    return [f"line {entry.line}: {entry.message}" for entry in compiled.error_log]


def classes(found: list[str], ordered: bool = True) -> list[dict]:
    """``[{'class': ..., 'count': N}]`` for one document's violations.

    Counted rather than listed once per instance: a reader wants to know that
    the ``list`` placement class occurs 27 times in one document and 31 in the
    other, and the count is also what the declaration pins, so a reading that
    produces one more instance of a known class is a red run rather than a
    number nobody compared.
    """
    counts: dict[str, int] = {}
    for line in found:
        message = line.split(": ", 1)[1] if line.startswith("line ") else line
        key = violation_class(message)
        counts[key] = counts.get(key, 0) + 1
    items = [{"class": key, "count": count} for key, count in counts.items()]
    return sorted(items, key=lambda item: item["class"]) if ordered else items


def _document(path: Path, base: Path, schema) -> dict:
    found = violations(path, schema)
    return {
        "path": path.relative_to(base).as_posix(),
        "conforms": not found,
        "violations": found,
        "classes": classes(found),
    }


def report(root: Path | None = None, schema=None) -> dict:
    """What the vendored schema says about every committed AKN document.

    Raises :class:`SchemaNotVendored` when the schema is not here. That is
    deliberate: an empty report would be indistinguishable from a corpus whose
    documents all conform, and the board prints the difference as a sentence.
    """
    base = Path(root or corpus.ROOT)
    compiled = schema if schema is not None else load_schema(schema_path(base))
    found = [_document(path, base, compiled) for path in documents(base)]
    total = sum(len(doc["violations"]) for doc in found)
    keys = {item["class"] for doc in found for item in doc["classes"]}
    return {
        "schema": SCHEMA.as_posix(),
        "manifest": MANIFEST.as_posix(),
        "documents": found,
        "conforming": sum(1 for doc in found if doc["conforms"]),
        "declared": declared(base),
        "violations": total,
        "classes": len(keys),
    }


# --------------------------------------------------------------------------- #
# the declared state
# --------------------------------------------------------------------------- #

def declared(root: Path | None = None) -> dict:
    """The declared violations, as ``{document: {class: count}}``.

    Absent is a state and not a crash: a repository that has not declared
    anything yet gets an empty mapping, and every violation the run finds is then
    reported as undeclared, which is the honest reading of a file that is not
    there.
    """
    import yaml

    path = declaration_path(root) if root is not None else Path(corpus.ROOT) / DECLARATION
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, int]] = {}
    for document, entries in (raw.get("documents") or {}).items():
        out[str(document)] = {str(e["class"]): int(e["count"]) for e in (entries or [])}
    return out


def write_declaration(root: Path | None = None, schema=None) -> Path:
    """Record what the run finds as the declaration. A decision, not a repair.

    Same shape and same warning as `python -m itl_mcp.drift --write` in the
    third repository: this overwrites the file with whatever the schema says
    now, so it belongs *after* somebody has read the violations and decided they
    are the ones to carry. Recording them without reading them is how the
    declaration would stop being a worklist.
    """
    base = Path(root or corpus.ROOT)
    live = report(base, schema)
    lines = [
        "# The OASIS conformance this repository declares it does not have yet.",
        "#",
        "# `python -m harness oasis` validates every committed AKN document against",
        "# the vendored AKN 3.0 schema (vendor/akn/, pinned in",
        "# provenance/akn-xsd.sha256) and prints what the schema says. That run is",
        "# live; this file is its second half - the violations that are known and",
        "# named - so that a reader of the board sees a declared state rather than",
        "# an unstated one, and so that a change in either direction is a red run",
        "# instead of a silent drift.",
        "#",
        "# One entry per document and per class the report gives it; `count` is how",
        "# many times the class occurs in that document. Fixing a class is a",
        "# rebuild *and* an edit here: the count goes with it, and an entry whose",
        "# class the schema no longer reports has to be removed, which",
        "# tests/test_oasis.py refuses to let anyone forget.",
        "#",
        "# Written by `python -m harness oasis --record`. Read the run first:",
        "# recording what is here without reading it is how a declaration stops",
        "# being a worklist.",
        "documents:",
    ]
    for doc in live["documents"]:
        if not doc["classes"]:
            continue
        lines.append(f"  {doc['path']}:")
        for item in doc["classes"]:
            lines.append(f"    - class: \"{item['class']}\"")
            lines.append(f"      count: {item['count']}")
    target = declaration_path(base)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def drift(root: Path | None = None, schema=None) -> list[str]:
    """What the run says that the declaration does not, and the other way round.

    Four ways for the two to disagree, and every one of them is a line: a class
    the schema reports that was never declared, a count that moved, a class the
    declaration still carries that the schema no longer reports, and a document
    the declaration names that no longer holds any violation at all. The last two
    are the reason this file is a worklist rather than a suppression: fixing the
    corpus makes the command red until the entry is deleted.
    """
    base = Path(root or corpus.ROOT)
    live = report(base, schema)
    said: dict[str, dict[str, int]] = {
        doc["path"]: {item["class"]: item["count"] for item in doc["classes"]}
        for doc in live["documents"]
    }
    promised = live["declared"]
    out: list[str] = []
    for document in sorted(set(said) | set(promised)):
        here, there = said.get(document, {}), promised.get(document, {})
        for key in sorted(set(here) | set(there)):
            if key not in there:
                out.append(f"{document}: undeclared — {here[key]}x {key}")
            elif key not in here:
                out.append(f"{document}: declared {there[key]}x, the schema no "
                           f"longer reports it — {key}")
            elif here[key] != there[key]:
                out.append(f"{document}: declared {there[key]}x, the run says "
                           f"{here[key]}x — {key}")
    return out
