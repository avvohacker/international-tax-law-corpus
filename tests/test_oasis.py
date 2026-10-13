"""The vendored schema, the validator, and the state the corpus declares.

Invariant F7 at its strongest: the document the pipeline writes is the document
the standard describes. Three things are worth a test here, and they are not the
same thing.

**The check can fail.** A validator that never fires proves nothing, so the
schema is handed a document it must refuse and the refusal has to name the
element. **The check can pass.** A check that always fires is a permanent red,
and a permanent red stops being read - which is why the same validator is handed
a document that conforms and has to stay quiet about it. **What it says today is
what this repository says it says.** The committed documents do not all conform
yet, and that finding is written down in `fixtures/oasis-conformance.yaml`
rather than left in a run nobody keeps; the file is compared with the live
schema here, so a class that gets fixed and an entry that is left behind are
both red, and neither can quietly become the truth.

The schema itself is part of the subject: vendored under `vendor/akn/`, pinned
file by file in `provenance/akn-xsd.sha256`, and read through a resolver that
refuses any location but a sibling of the schema. A validation that fetched
`xml.xsd` from the web would depend on what the network served that day, which
is exactly the machine-dependence this repository exists to refuse.
"""
import hashlib
from pathlib import Path

import pytest

from harness import oasis
from support import ROOT

# A document the schema accepts: the smallest act this vocabulary admits, with
# the metadata the standard requires (a work needs its country, an expression
# needs its language) and one section of text. It is here because the positive
# control cannot be the corpus' own documents - those do not conform yet, and a
# validator asserted only against failing input is a validator that could be
# replaced by the constant `[violation]` without any test noticing.
CONFORMING = """<?xml version="1.0" encoding="utf-8"?>
<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">
  <act name="un-model">
    <meta>
      <identification source="#src">
        <FRBRWork>
          <FRBRthis value="/akn/zz/minimal"/>
          <FRBRuri value="/akn/zz/minimal"/>
          <FRBRdate date="2026-10-13" name="generation"/>
          <FRBRauthor href="#src"/>
          <FRBRcountry value="zz"/>
        </FRBRWork>
        <FRBRExpression>
          <FRBRthis value="/akn/zz/minimal/eng@"/>
          <FRBRuri value="/akn/zz/minimal/eng@"/>
          <FRBRdate date="2026-10-13" name="generation"/>
          <FRBRauthor href="#src"/>
          <FRBRlanguage language="eng"/>
        </FRBRExpression>
        <FRBRManifestation>
          <FRBRthis value="/akn/zz/minimal/eng@"/>
          <FRBRuri value="/akn/zz/minimal/eng@"/>
          <FRBRdate date="2026-10-13" name="generation"/>
          <FRBRauthor href="#src"/>
        </FRBRManifestation>
      </identification>
    </meta>
    <body>
      <section eId="sec_1">
        <num>1.</num>
        <content>
          <p>Text.</p>
        </content>
      </section>
    </body>
  </act>
</akomaNtoso>
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "document.akn.xml"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# the check fires, and it stays quiet
# --------------------------------------------------------------------------- #

def test_the_schema_accepts_a_document_that_conforms(tmp_path):
    """The positive control: a check that can only say no is not a check."""
    document = _write(tmp_path, CONFORMING)
    assert oasis.violations(document, oasis.load_schema()) == []


def test_the_validator_names_what_the_schema_refuses(tmp_path):
    """The negative control: the refusal has to name the element to be usable."""
    # Two faults, one of them the class the corpus itself has: a `list` used
    # where the standard allows only sub-hierarchies, and a work with no country.
    broken = CONFORMING.replace(
        '        <content>\n          <p>Text.</p>\n        </content>\n',
        '        <content>\n          <p>Text.</p>\n        </content>\n'
        '        <list><point><content><p>x</p></content></point></list>\n'
    ).replace('          <FRBRcountry value="zz"/>\n', "")
    found = oasis.violations(_write(tmp_path, broken), oasis.load_schema())

    assert found, "the validator accepted a document the schema refuses"
    keys = {item["class"] for item in oasis.classes(found)}
    assert any("'list'" in key for key in keys), keys
    assert any("FRBRWork" in key for key in keys), keys
    assert all(key.endswith(".") for key in keys), (
        "a class key still carries the list of what the schema expected, so it "
        "would change with every instance of the same defect: " + repr(keys))


def test_the_class_of_a_violation_is_stable_across_documents():
    """The declaration is keyed by class, so the key must not carry the document.

    The two UN Model editions hit the same class of defect a different number of
    times; the key has to be the same string in both, or the declaration could
    not be written against it.
    """
    message = ("Element '{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}list': "
               "This element is not expected. Expected is one of ( {akn}intro, "
               "{akn}content, {akn}paragraph ).")
    assert oasis.violation_class(message) == \
        "Element 'list': This element is not expected."


# --------------------------------------------------------------------------- #
# the schema is the vendored one, and nothing else
# --------------------------------------------------------------------------- #

def test_the_vendored_pair_is_the_registered_one():
    """F11 for the schema: what validated the corpus is in the commit that says so."""
    entry = next(e for e in oasis.corpus.register_entries(ROOT)
                 if e.get("id") == "akn-xsd")
    named = list(entry.get("files") or [])
    assert named == ["vendor/akn/akomantoso30.xsd", "vendor/akn/xml.xsd"], named
    assert entry.get("produces") == "schema", entry.get("produces")

    manifest = ROOT / str(entry["manifest"])
    lines = [line.split(None, 1) for line in
             manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert sorted(rel.strip() for _, rel in lines) == sorted(named), (
        "the manifest and the register name different files")
    for digest, relative in lines:
        path = ROOT / relative.strip()
        assert path.is_file(), f"{relative} is registered and not here"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest.strip(), (
            f"{relative} is not the file the manifest pins")

    assert oasis.schema_path(ROOT).is_file(), (
        "the schema the register names is not the path the validator loads")


def test_a_schema_that_would_reach_outside_the_vendored_pair_is_refused(tmp_path):
    """No fetch, ever: a validator that downloads a schema checks nothing.

    The AKN schema imports the XML namespace schema as `./xml.xsd`. Point that
    import somewhere else - the file it would find in the world - and the loader
    has to refuse instead of going to get it.
    """
    schema = tmp_path / "reaching.xsd"
    schema.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"\n'
        '            targetNamespace="urn:example" '
        'xmlns="urn:example" elementFormDefault="qualified">\n'
        '  <xsd:import namespace="http://www.w3.org/XML/1998/namespace"\n'
        '              schemaLocation="https://example.invalid/xml.xsd"/>\n'
        '  <xsd:element name="thing" type="xsd:string"/>\n'
        '</xsd:schema>\n',
        encoding="utf-8")

    with pytest.raises(oasis.SchemaNotVendored) as excinfo:
        oasis.load_schema(schema)
    assert "example.invalid" in str(excinfo.value), str(excinfo.value)


def test_an_import_that_was_never_vendored_is_a_stated_failure(tmp_path):
    """A sibling import that is not in the tree fails before the compiler sees it.

    This is the other half of the previous test, and the one that matters more:
    a schema compiler handed a relative `schemaLocation` it cannot find does not
    stop, it fetches. Requiring the closure to be vendored is what makes the
    check answerable with the network unplugged - and the message names the file
    by its name, not by the path of the machine the run happened on (F14).
    """
    schema = tmp_path / "importing.xsd"
    schema.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"\n'
        '            targetNamespace="urn:example" '
        'xmlns="urn:example" elementFormDefault="qualified">\n'
        '  <xsd:import namespace="urn:example" '
        'schemaLocation="./elsewhere.xsd"/>\n'
        '  <xsd:element name="thing" type="xsd:string"/>\n'
        '</xsd:schema>\n',
        encoding="utf-8")

    with pytest.raises(oasis.SchemaNotVendored) as excinfo:
        oasis.load_schema(schema)
    message = str(excinfo.value)
    assert "elsewhere.xsd" in message, message
    assert str(tmp_path) not in message, (
        "the reason the check could not run names the machine it did not run on: "
        + message)


def test_a_missing_schema_is_a_stated_failure_not_a_pass(tmp_path):
    """Absent is a state, and it is never rendered as a corpus that conforms."""
    with pytest.raises(oasis.SchemaNotVendored) as excinfo:
        oasis.report(tmp_path)
    assert "akomantoso30.xsd" in str(excinfo.value), str(excinfo.value)


# --------------------------------------------------------------------------- #
# the state the corpus declares
# --------------------------------------------------------------------------- #

def test_the_declaration_says_what_the_schema_says():
    """The live run and `fixtures/oasis-conformance.yaml`, held together.

    This is the test that makes the declaration a worklist rather than a place a
    defect goes to be forgotten: fixing a class leaves the entry behind and this
    fails until it is deleted, and reading a document that produces a new class
    fails until that class is written down.
    """
    moves = oasis.drift(ROOT)
    assert not moves, (
        "the schema and the declared conformance have moved apart. Read "
        "`python -m harness oasis`, then either fix what it names or record the "
        "state deliberately with `--record`:\n  " + "\n  ".join(moves))


def test_the_board_prints_the_verdict_it_is_asked_for():
    """A number a reader cannot see is a claim this repository does not make."""
    from harness import report

    live = oasis.report(ROOT)
    line = (f"- AKN conformance: {live['conforming']} of "
            f"{len(live['documents'])} committed document(s) valid")
    assert line in report.render(ROOT), (
        "the board no longer prints what the vendored schema says")
