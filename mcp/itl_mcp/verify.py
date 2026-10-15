"""Verify the artefacts before answering from them.

Everything this server says is a claim about bytes somebody committed. So the
first thing it does with an artefact is check it against the hash the project
itself declares, and refuse to answer when the check fails. The check is not a
courtesy: it is what makes "the answer came from this data" true rather than
assumed.

Three kinds of check are available, and they are NOT equally strong. Each one
reports which kind it performed, so a reader can tell what was proven:

* ``bytes``  -- the hash was recomputed from the committed file and matched.
                Strong: the file on disk is the file the project pinned.
* ``register`` -- the hash a file declares about its SOURCE was found in the
                corpus's own provenance register. The source bytes are not
                committed (the PDFs never are), so this proves the artefact
                still claims the registered source, not that the source is
                unchanged. Honest about its own reach.
* ``self``   -- a file's declared hash was compared with the same file's
                declared hash elsewhere. Weakest: agreement between two
                declarations, useful as a cross-check and nothing more.

A check that cannot run at all -- the source file is absent, the register is
missing -- is reported as ``absent`` with the reason, never as a pass.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from . import artefacts
from .roots import Roots

# The kinds a check can report, weakest last.
BYTES = "bytes"
REGISTER = "register"
SELF = "self"
ABSENT = "absent"


@dataclass(frozen=True)
class Check:
    """One verification, with its honest strength."""

    artefact: str          # what was checked, as a path relative to its root
    declared: str | None   # the hash the project declares, if one was found
    actual: str | None     # the hash this process computed, if it could
    kind: str              # bytes | register | self | absent
    note: str              # what this particular check does and does not prove

    @property
    def ok(self) -> bool | None:
        """True proven, False disproven, None unprovable from here."""
        if self.kind == ABSENT:
            return None
        if self.declared is None or self.actual is None:
            return None
        return self.declared == self.actual

    def as_dict(self) -> dict:
        return {
            "artefact": self.artefact,
            "kind": self.kind,
            "declared": self.declared,
            "actual": self.actual,
            "result": {True: "match", False: "MISMATCH", None: "unprovable"}[self.ok],
            "note": self.note,
        }


class VerificationError(RuntimeError):
    """An artefact was checked and the bytes did not match the declaration."""

    def __init__(self, failures: Iterable[Check]):
        self.failures = list(failures)
        lines = [f"  {c.artefact}: declared {c.declared} but computed {c.actual}"
                 for c in self.failures]
        super().__init__(
            "refusing to answer: these artefacts do not match the hash the "
            "project declares for them\n" + "\n".join(lines)
        )


def sha256_of(path: Path) -> str:
    """The digest of a committed file, computed once per run.

    Memoised on purpose: the same ledger is hashed again for every question
    that touches its edition, and a digest is a pure function of bytes this
    process never writes. See `itl_mcp.artefacts`.
    """
    return artefacts.sha256(path)


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------

def verify_manifest_edition(corpus: Path, edition: str) -> list[Check]:
    """Check a UN Model edition's ledger and AKN against its own manifest.

    Both hashes are recomputed from committed files, so both are ``bytes``:
    this proves the ledger and the AKN in the checkout are the ones the
    corpus built. The source PDF's hash is declared too but its bytes are not
    committed, so it is reported as ``absent`` rather than silently skipped.
    """
    base = corpus / "corpora" / "un-model" / edition
    manifest_path = base / f"model-{edition}.manifest.json"
    checks: list[Check] = []

    if not manifest_path.is_file():
        return [Check(
            artefact=f"corpora/un-model/{edition}/model-{edition}.manifest.json",
            declared=None, actual=None, kind=ABSENT,
            note="the manifest is not in this checkout; nothing can be verified",
        )]
    manifest = _load_json(manifest_path)

    for key, filename, label in (
        ("ledger_sha256", f"model-{edition}.spans.jsonl", "span ledger"),
        ("akn_sha256", f"model-{edition}.akn.xml", "AKN document"),
    ):
        declared = manifest.get(key)
        target = base / filename
        rel = f"corpora/un-model/{edition}/{filename}"
        if not target.is_file():
            checks.append(Check(rel, declared, None, ABSENT,
                                f"the {label} is declared by the manifest but absent "
                                f"from the checkout"))
            continue
        checks.append(Check(
            rel, declared, sha256_of(target), BYTES,
            f"recomputed from the committed {label}; proves the checkout holds "
            f"the {label} the corpus built",
        ))

    checks.append(Check(
        f"corpora/un-model/{edition}/sources/{Path(manifest.get('source_file','')).name}",
        manifest.get("source_sha256"), None, ABSENT,
        "the source PDF is never committed (the hash, not the file, is the "
        "contract), so its bytes cannot be rechecked here",
    ))
    return checks


def verify_position(corpus: Path, slug: str) -> list[Check]:
    """Check a country's MLI position against the corpus's own register.

    The position file declares the SHA-256 of the PDF it was read from. That
    PDF is not committed, but the corpus pins every position PDF's hash in
    ``provenance/mli-positions.sha256``. So the check is: does the hash this
    artefact claims appear in the register? That is a ``register`` check -- it
    proves the artefact still names a source the corpus pinned, and it does not
    prove the source PDF is unchanged.

    The lookup goes by the declared hash, deliberately not by a filename
    derived from the slug. Six of the register's files are named the way the
    publisher spells the country (``mli-position-czech-republic.pdf``,
    ``-turkey.pdf``, ``-china.pdf``, ``-hong-kong.pdf``, ``-russia.pdf``,
    ``-cote-divoire.pdf``) while the published positions use the slug form
    (``czechia``, ``turkiye``, ``china-people-s-republic-of``,
    ``hong-kong-china``, ``russian-federation-provisional``,
    ``cote-d-ivoire``). Deriving the filename from the slug reported those six
    as unprovable when they are provable -- a false silence, which is as wrong
    as a false claim. Where the register's spelling differs from the slug's,
    the note names the file the register actually holds, so the divergence is
    reported rather than hidden.
    """
    path = corpus / "corpora" / "mli" / "positions" / f"{slug}.json"
    rel = f"corpora/mli/positions/{slug}.json"
    register_path = corpus / "provenance" / "mli-positions.sha256"

    if not path.is_file():
        return [Check(rel, None, None, ABSENT,
                      f"the corpus holds no MLI position for {slug!r}")]
    declared = _load_json(path).get("sha256")

    if not register_path.is_file():
        return [Check(rel, declared, None, ABSENT,
                      "provenance/mli-positions.sha256 is missing from this "
                      "checkout, so the declared source hash cannot be cross-checked")]

    carriers = sorted(_register_entries(register_path).get(declared or "", []))
    if not carriers:
        return [Check(rel, declared, None, ABSENT,
                      "the register pins no PDF with the source hash this "
                      "artefact declares, so there is nothing to cross-check it "
                      "against")]
    if f"mli-position-{slug}.pdf" in carriers:
        note = ("compares the source hash this artefact declares with the hash "
                "the corpus register pins for the same PDF. The PDF's bytes are "
                "not committed, so this proves the artefact still names the "
                "registered source, not that the source is unchanged")
    else:
        note = ("compares the source hash this artefact declares with the hash "
                "the corpus register pins, and the register spells the file "
                f"{', '.join(carriers)} rather than mli-position-{slug}.pdf: the "
                "slug and the register's filename differ, and the hash is what "
                "was matched. The PDF's bytes are not committed, so this proves "
                "the artefact still names a registered source, not that the "
                "source is unchanged")
    return [Check(rel, declared, declared, REGISTER, note)]


def verify_mapping(corpus: Path) -> list[Check]:
    """Check the MLI-to-treaty mapping against the corpus's own register.

    ``corpora/mli/mapping.json`` declares the SHA-256 of the MLI convention
    text its Article rows were read from. That text is not committed, but the
    corpus pins it in ``provenance/sources.yaml`` under
    ``mli-convention-2016``. So this is a ``register`` check: it proves the
    mapping still names the registered convention, and it does not prove the
    convention is unchanged.
    """
    path = corpus / "corpora" / "mli" / "mapping.json"
    rel = "corpora/mli/mapping.json"
    register_path = corpus / "provenance" / "sources.yaml"

    if not path.is_file():
        return [Check(rel, None, None, ABSENT,
                      "the MLI mapping is not in this checkout, so no "
                      "Article-to-provision chain can be read from it")]
    payload = _load_json(path)
    declared = payload.get("sha256")

    if not register_path.is_file():
        return [Check(rel, declared, None, ABSENT,
                      "provenance/sources.yaml is missing from this checkout, "
                      "so the mapping's declared source hash cannot be "
                      "cross-checked against the corpus register")]

    pinned = _pinned_source(register_path, str(payload.get("source") or ""))
    if pinned is None:
        return [Check(rel, declared, None, ABSENT,
                      "the corpus register pins no hash for the source the "
                      "mapping names, so there is nothing to cross-check the "
                      "declared hash against")]
    return [Check(
        rel, declared, pinned, REGISTER,
        "compares the source hash the mapping declares with the hash the "
        "corpus register pins for the MLI convention text. That text is not "
        "committed, so this proves the mapping still names the registered "
        "convention, not that the convention is unchanged",
    )]


def verify_signatories(corpus: Path) -> list[Check]:
    """Report the signatories table honestly.

    The file declares the SHA-256 of the table as printed in the source
    document, not of the committed JSON, so no ``bytes`` check exists for it.
    The check records that fact instead of pretending one ran.
    """
    path = corpus / "corpora" / "mli" / "signatories-and-parties.json"
    rel = "corpora/mli/signatories-and-parties.json"
    if not path.is_file():
        return [Check(rel, None, None, ABSENT, "absent from this checkout")]
    declared = _load_json(path).get("sha256")
    return [Check(
        rel, declared, None, ABSENT,
        "this file's declared hash is of the table as printed in the source "
        "document, not of the committed JSON, so no committed bytes exist to "
        "recompute it from; the rows themselves are read directly below",
    )]


# --------------------------------------------------------------------------
# library
# --------------------------------------------------------------------------

def verify_treaty(library: Path, treaty_id: str) -> list[Check]:
    """Check a treaty's pages against the hashes each page declares.

    Every unit carries the SHA-256 of its own committed text, so each one is
    recomputed: a ``bytes`` check per page. The source PDF's hash is declared
    at the top but its bytes are not committed, and is reported as absent.
    """
    path = library / "treaties" / treaty_id / "treaty.json"
    rel = f"treaties/{treaty_id}/treaty.json"
    if not path.is_file():
        return [Check(rel, None, None, ABSENT, f"no treaty {treaty_id!r} in the library")]

    payload = _load_json(path)
    units = payload.get("units", [])
    checks = [
        Check(
            artefact=rel,
            declared=str(payload.get("page_count")),
            actual=str(len(units)),
            kind=SELF,
            note="the declared page_count against the number of units actually "
                 "present; agreement between two declarations in one file",
        )
    ]

    # One check per page, so a single bad page is named rather than averaged
    # into an aggregate that hides which one failed.
    for unit in units:
        text = unit.get("text", "")
        checks.append(Check(
            artefact=f"treaties/{treaty_id}/treaty.json#page-{unit.get('page')}",
            declared=unit.get("sha256"),
            actual=sha256_of_text(text),
            kind=BYTES,
            note="recomputed from the committed text of this page; proves the "
                 "page is byte-identical to what the library built",
        ))

    checks.append(Check(
        f"treaties/{treaty_id}/sources/",
        payload.get("source", {}).get("sha256"), None, ABSENT,
        "the treaty PDF is never committed (the hash, not the file, is the "
        "contract), so its bytes cannot be rechecked here",
    ))
    return checks


# --------------------------------------------------------------------------
# everything, at once
# --------------------------------------------------------------------------

def inventory(roots: Roots) -> list[Check]:
    """Every check this server can run, over both checkouts.

    The ``sources`` tool exists to say what was read and how strongly each
    artefact was verified, and the drift control records that answer as named
    facts, so the walk is here and both take it. A second copy of the list in
    the control would go on reporting what the tool used to check, which is the
    one failure a recorded answer must not have.

    The order is the tool's own -- the two editions, the signatories table, the
    mapping, then one check per position document and one per treaty -- and it
    is the number of checks, by kind and by result, that says whether the
    answers above were proven against anything at all.
    """
    checks: list[Check] = []
    for edition in ("2017", "2021"):
        checks += verify_manifest_edition(roots.corpus, edition)
    checks += verify_signatories(roots.corpus)
    checks += verify_mapping(roots.corpus)
    positions = roots.corpus / "corpora" / "mli" / "positions"
    for path in sorted(positions.glob("*.json")):
        if path.name == "batch-report.json":
            continue
        checks += verify_position(roots.corpus, path.stem)
    for path in sorted((roots.library / "treaties").glob("*/treaty.json")):
        checks += verify_treaty(roots.library, path.parent.name)
    return checks


def sources(roots: Roots) -> dict:
    """The ``sources`` payload without the machine-local roots.

    One reading, taken by the tool and by the drift control that records its
    answer: the walk over what was read, and the guide to reading each kind of
    check. The two checkouts' paths are the tool's own to add -- they are where
    this process read from, which is never what a committed fixture holds -- so
    they are not part of this reading and the control never sees them.
    """
    return {
        "checks": [check.as_dict() for check in inventory(roots)],
        "reading_the_checks": {
            "bytes": "recomputed from the committed file; the strongest check",
            "register": "the declared source hash was found in the corpus "
                        "register; proves the artefact still names the "
                        "registered source, not that the source is unchanged",
            "self": "a file's declaration compared with another of its own "
                    "declarations; a cross-check only",
            "absent": "the check could not be run; the reason is given, and "
                      "it is never counted as a pass",
        },
    }


def verify_all(checks: Iterable[Check]) -> None:
    """Raise VerificationError if any check disproved its declaration."""
    failures = [c for c in checks if c.ok is False]
    if failures:
        raise VerificationError(failures)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return artefacts.document(path)


def _pinned_source(register: Path, source_id: str) -> str | None:
    """The hash the corpus's YAML register pins for one source id.

    ``provenance/sources.yaml`` is a list of entries, each naming an ``id``
    and the ``sha256`` of the bytes it was read from. Only those two fields
    are read. A register that cannot be parsed, an entry with no hash, or a
    hash that is not a SHA-256, all return no pin -- this reports the absence
    of a pin rather than inventing a match.
    """
    if not source_id:
        return None
    try:
        entries = yaml.safe_load(artefacts.text(register)) or []
    except yaml.YAMLError:
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") != source_id:
            continue
        digest = str(entry.get("sha256") or "").strip().lower()
        return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None
    return None


def _register_entries(register: Path) -> dict[str, list[str]]:
    """Map every hash the register pins to the filenames it pins it under.

    Lines are ``<sha256>  sources/mli-positions/mli-position-<name>.pdf``. A
    hash may be carried by more than one filename, so the value is a list, and
    the caller matches by the hash it holds rather than by a filename it would
    have to derive.
    """
    entries: dict[str, list[str]] = {}
    for line in artefacts.text(register).splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, listed = line.partition(" ")
        digest = digest.strip()
        if digest:
            entries.setdefault(digest, []).append(Path(listed.strip()).name)
    return entries
