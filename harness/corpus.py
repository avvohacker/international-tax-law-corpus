"""Read the corpus - or report honestly that it does not exist yet.

This module is the single place that knows the *layout* of the artefacts, so
that the invariant tests can be written against a stable interface and the
extractor can move files around without rewriting the whole suite.

Declared layout (DESIGN.md §2)::

    provenance/sources.yaml                     the input register (hand-authored)
    sources/<source-id>.pdf                     the input, matching its register hash
    corpora/<family>/<edition>/
        model-<edition>.akn.xml                 the AKN 3.0 body projection
        model-<edition>.manifest.json           counts, missing[], source ref, ledger digest
        model-<edition>.spans.jsonl             the ledger: one span per line, with its rule
    corpora/mli/signatories-and-parties.json
    corpora/mli/positions/<slug>.json
    rules/<nn>-<scope>.yaml                     classification rules, referenced by id
    derived/                                    every generated view and report
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
AKN = "{%s}" % AKN_NS

CORPORA = "corpora"
DERIVED = "derived"
SOURCES = "sources"
RULES = "rules"
PROVENANCE = "provenance"

# The position family's own account of itself, written beside the positions it
# accounts for and excluded from them by name: it is about the family, and a
# jurisdiction is not a family.
POSITION_REPORT = "batch-report.json"


# --------------------------------------------------------------------------- #
# roots and discovery
# --------------------------------------------------------------------------- #

def corpus_root(root: Path | None = None) -> Path:
    return Path(root or ROOT) / CORPORA


def corpus_present(root: Path | None = None) -> bool:
    """True when at least one AKN corpus exists."""
    return any(corpus_root(root).glob("**/*.akn.xml"))


def editions(root: Path | None = None) -> list[tuple[str, str]]:
    """[(family, edition)] for every AKN edition the register declares.

    Declared rather than discovered, and the reason is the OECD material. The
    corpus has two shapes of artefact: an edition (`corpora/<family>/<edition>/`:
    ledger, node index, AKN document, manifest, views) and a document of its own
    kind (`corpora/mli/signatories-and-parties.json`, `corpora/mli/positions/
    <slug>.json`). Scanning for directories cannot tell them apart, and the cost
    of guessing is not cosmetic: `corpora/mli/positions/` is a directory, so a
    scan called it an edition and every invariant that iterates editions - F1,
    F2, F4, F6 - demanded an AKN document inside the country positions and
    failed on a corpus that is exactly right.

    The register already says what is built from each source, so an edition is
    the corpus artefact of a source that declares `produces: akn`, named
    `corpora/<family>/<edition>/` after the source id. An edition that is
    declared and absent is still returned, deliberately: F1 must be able to
    report the AKN it is missing, and a missing directory that made itself
    invisible would be the silent loss this project exists to prevent.
    """
    found: list[tuple[str, str]] = []
    for entry in declared_sources(root):
        if entry["produces"] != "akn":
            continue
        family, _, edition = entry["id"].rpartition("-")
        if family and edition:
            found.append((family, edition))
    return sorted(found)


def edition_dir(root: Path | None, family: str, edition: str) -> Path:
    return corpus_root(root) / family / edition


def _one(directory: Path, suffix: str) -> Path | None:
    hits = sorted(directory.glob(f"*{suffix}"))
    return hits[0] if len(hits) == 1 else None


def akn(root: Path | None = None, family: str | None = None,
        edition: str | None = None) -> list[Path]:
    if family is None:
        return sorted(corpus_root(root).glob("**/*.akn.xml"))
    return sorted(edition_dir(root, family, edition).glob("*.akn.xml"))


def manifests(root: Path | None = None) -> list[Path]:
    return sorted(corpus_root(root).glob("**/*.manifest.json"))


def manifest(root: Path | None = None, family: str | None = None,
             edition: str | None = None) -> Path | None:
    if family is None:
        return None
    return _one(edition_dir(root, family, edition), ".manifest.json")


def ledgers(root: Path | None = None) -> list[Path]:
    """The span ledgers - the audit trail of every kept/dropped span."""
    return sorted(corpus_root(root).glob("**/*.spans.jsonl"))


def node_files(root: Path | None = None) -> list[Path]:
    """Structural node index: eId, tag, page and span range, per node."""
    return sorted(corpus_root(root).glob("**/*.nodes.jsonl"))


def signatories(root: Path | None = None) -> Path:
    return corpus_root(root) / "mli" / "signatories-and-parties.json"


def position_files(root: Path | None = None) -> list[Path]:
    """One position per jurisdiction - not the family's own report about them."""
    return sorted(p for p in (corpus_root(root) / "mli" / "positions").glob("*.json")
                  if p.name not in (POSITION_REPORT,))


def mapping_file(root: Path | None = None) -> Path:
    """The MLI-to-treaty mapping: one row per Article of the Convention."""
    return corpus_root(root) / "mli" / "mapping.json"


def markdown_articles(root: Path | None = None) -> list[Path]:
    return sorted(Path(root or ROOT).glob("derived/markdown/**/article-*.md"))


def derived_index(root: Path | None = None) -> Path:
    return Path(root or ROOT) / DERIVED / "index.json"


def rule_files(root: Path | None = None) -> list[Path]:
    return sorted((Path(root or ROOT) / RULES).glob("*.yaml"))


def source_pdfs(root: Path | None = None) -> list[Path]:
    return sorted((Path(root or ROOT) / SOURCES).glob("*.pdf"))


def register(root: Path | None = None) -> Path:
    return Path(root or ROOT) / PROVENANCE / "sources.yaml"


# What the pipeline builds from a source, declared in the register next to the
# hash of the bytes it is built from. `none` is a declaration and not an
# omission: the entry carries a reason, the status report counts it, and F7
# compares the one artefact a `none` source does produce - its reading.
#
#   akn       the full edition: ledger, node index, AKN document, manifest, views
#   table     the source is a table, and its document is a table's data
#   positions one JSON document per jurisdiction the source covers - the
#             country positions, which are a mix of prose and table and are
#             neither of the two above
#   mapping   the source is the Convention, and its document is the index of
#             what each of its Articles does to a treaty
#   none      nothing is built yet, and the register says why
#   schema    a standard the corpus is validated against rather than read from:
#             the artefact is the vendored copy (vendor/akn/), pinned in a
#             manifest, and `harness/oasis.py` is what checks the corpus
#             against it
PRODUCES = ("akn", "table", "positions", "mapping", "none", "schema")


def register_entries(root: Path | None = None) -> list[dict]:
    """The source register as data: one dictionary per source.

    Every reader of the register comes here, so that "what does the corpus say
    about its inputs" has one answer rather than one per module that happens to
    parse YAML.
    """
    import yaml

    path = register(root)
    if not path.is_file():
        return []
    return list(yaml.safe_load(path.read_text(encoding="utf-8")) or [])


def declared_sources(root: Path | None = None) -> list[dict]:
    """The register, ready for a builder: id, what it produces, and the PDF.

    An entry whose `file` is not here locally keeps its declaration and gets
    `pdf: None`: a source that has not been fetched is still a source, and the
    register says what it is for whether or not the bytes are present.
    """
    base = Path(root or ROOT)
    out: list[dict] = []
    for entry in register_entries(root):
        relative = entry.get("file")
        pdf = (base / relative) if relative else None
        if pdf is not None and not pdf.is_file():
            pdf = None
        out.append({
            "id": str(entry.get("id") or ""),
            "produces": entry.get("produces"),
            "artefact": str(entry.get("artefact") or ""),
            "pending": " ".join(str(entry.get("produces_pending") or "").split()),
            "pdf": pdf,
            "dir": str(entry.get("dir") or ""),
            "manifest": str(entry.get("manifest") or ""),
            # What a vendored source declares it puts in the tree, named one by
            # one: a `schema` entry's artefact is a copy of files that are not
            # this project's, and "is it built" a reader can only ask if the
            # register says which files it means.
            "files": [str(name) for name in (entry.get("files") or [])],
            "rules": bool(entry.get("file") or entry.get("dir")),
        })
    return out


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_spans(path: Path) -> list[dict]:
    """Records as dictionaries, from either shape this corpus writes.

    Both shapes are in use and both are read here, because both are records and
    a reader that could see only one of them would make the other unreadable
    through the seam the tests use:

    * the ledger (`*.spans.jsonl`) is compact - a header object declaring its
      `fields` and rule ids, then one array per span (`ledger.ledger_records`);
    * the node index (`*.nodes.jsonl`) is one self-describing object per line.

    A line that declares `fields` or `format` is a header; every other object is
    a record. Nothing else distinguishes them, and `test_f06` reads the node
    index through this function, so an object silently swallowed as a header is
    a corpus with no provenance.
    """
    out: list = []
    fields = None
    rules: list = []
    decisions: list = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            if "fields" not in value and "format" not in value:
                out.append(value)
                continue
            fields = value.get("fields") or fields
            rules = value.get("rules") or rules
            decisions = value.get("decisions") or decisions
            continue
        if fields is None:
            raise ValueError(f"{path}: a record before the header")
        record = dict(zip(fields, value))
        index = record.get("rule", -1)
        record["rule"] = rules[index] if isinstance(index, int) and index >= 0 else ""
        index = record.get("transform", -1)
        record["transform"] = (rules[index]
                              if isinstance(index, int) and index >= 0 else "")
        which = record.get("decision")
        if isinstance(which, int) and 0 <= which < len(decisions):
            record["decision"] = decisions[which]
        out.append(record)
    return out


def ledger_header(path: Path) -> dict:
    """The header of a span ledger: its fields, rules and measurements.

    A ledger is self-describing on purpose - `fields` says what a row's numbers
    mean, `rules` says what its rule indexes point at, and `line_policy` and
    `hyphen_mark` are the measurements the text in it was read with. A reader
    that does not have to be handed a second document to understand the first is
    what makes the file checkable years later, and `ledger.reading_of` uses them
    to rebuild the text the file records.
    """
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict) and ("fields" in value or "format" in value):
            return value
        return {}
    return {}


def count_nodes(path: Path, tag: str) -> int:
    """Number of Akoma Ntoso elements with this tag name (namespace-aware)."""
    tree = ET.parse(path)
    return sum(1 for _ in tree.getroot().iter(AKN + tag))


def node_tags(path: Path) -> dict:
    """{tag: count} for every element in an AKN file."""
    counts: dict = {}
    for el in ET.parse(path).getroot().iter():
        tag = el.tag.split("}")[-1]
        counts[tag] = counts.get(tag, 0) + 1
    return counts


def eids(path: Path, tags=("paragraph", "subparagraph", "point")) -> dict:
    """{eId: tag} for the leaf elements the corpus has to trace back."""
    found: dict = {}
    for el in ET.parse(path).getroot().iter():
        tag = el.tag.split("}")[-1]
        if tag in tags and el.get("eId"):
            found[el.get("eId")] = tag
    return found


def hcontainer_names(path: Path) -> list[str]:
    """The `@name` of every informal container, in document order."""
    return [el.get("name") or "" for el in ET.parse(path).getroot().iter(AKN + "hcontainer")]


def akn_text(path: Path) -> str:
    """All text content of an AKN file, whitespace-normalised."""
    return " ".join(" ".join(ET.parse(path).getroot().itertext()).split())


def words(text: str) -> list[str]:
    return [w for w in text.replace("\u2019", "'").split() if w]


def summary(root: Path | None = None) -> str:
    r = Path(root or ROOT)
    return (f"akn={'yes' if corpus_present(r) else 'no'}"
            f" · editions={len(editions(r))}"
            f" · ledgers={len(ledgers(r))}"
            f" · nodes={len(node_files(r))}"
            f" · articles={len(markdown_articles(r))}"
            f" · positions={len(position_files(r))}"
            f" · mapping={'yes' if mapping_file(r).is_file() else 'no'}")
