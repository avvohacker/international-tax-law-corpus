"""Compare the published corpus with a fresh reading, artefact by artefact.

The corpus is the answer this project publishes; the reader is the thing that
produces it. A repair to the reader that nobody rebuilt the corpus for leaves
the two disagreeing, and a corpus nobody can tell is stale is worse than one
that says it is missing. This module rebuilds every artefact the register
declares - the UN Model editions, the MLI mapping, the signatories table and the
MLI positions family - with the writers the corpus itself uses, and compares
what it wrote with what is published, unit by unit: a JSON path
(`covered_agreements[11].instrument`), a ledger line, an XML line.

The artefacts a reading *derives* are part of the same answer, so they are
rebuilt here too rather than assumed to follow: every markdown view
(`derived/markdown/...`) and the edition diff report (`derived/reports/...`),
written from the live projections by the same `views` and `diff` writers the
build uses. The register's own claim about its inputs - each `sha256` in
`provenance/sources.yaml` and each line of a declared manifest - is recomputed
from the bytes on disk as well, and reported through the same difference list,
so a stale manifest is a drift the control names instead of a fact nobody
re-checks.

`compare_corpus` returns the differences. `harness/__main__.py`'s `drift`
command prints them and, with `--write`, republishes only the artefacts that
diverged; the row-by-row comparison below is what makes that a repair rather
than a byte overwrite. `pr_body` renders the same differences as the body of a
pull request that carries only the regenerated artefacts and the row-by-row
diff, which is what the automated control opens (`drift --body`).
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Optional

from harness import akn, corpus, diff, ledger, mli, views


def live_artifacts(root: Path, destination: Path) -> dict[str, Path]:
    """Write every artefact the register declares, into `destination`.

    The returned keys are the paths the artefacts take in the corpus (relative
    to `root`), and the values are the files just written. Every writer here is
    the writer the corpus uses, so the comparison is against the pipeline and
    not against a second implementation of it. Each edition's markdown views
    are written from the same live projection as its AKN document, and each
    family's edition report from the live corpus in `destination`, exactly as
    `harness/__main__.py::_write_corpus` and its `diff` command write them.
    """
    root, destination = Path(root), Path(destination)
    live: dict[str, Path] = {}
    families: dict[str, list[str]] = {}
    for entry in corpus.declared_sources(root):
        produces, artefact = entry["produces"], entry["artefact"]
        if not artefact or produces in (None, "none"):
            continue
        # A vendored schema is an *input*, not an artefact this pipeline
        # rebuilds. `provenance_differences` recomputes its digest against
        # `provenance/akn-xsd.sha256` and reports a changed byte there, which is
        # the right control for a file nobody regenerates; asked to rebuild it,
        # this function could only ever answer "not written", and a drift report
        # that names a file no command can fix is a report a reader learns to
        # skip. So it is left to the manifest, which does check it.
        if produces == "schema":
            continue
        if produces == "akn":
            if entry["pdf"] is None:
                continue
            family, _, edition = entry["id"].rpartition("-")
            target = destination / "corpora" / family / edition
            target.mkdir(parents=True, exist_ok=True)
            spans = ledger.SpanStream.read(entry["pdf"], entry["id"])
            book = ledger.Classifier.classify(spans, ledger.Ledger())
            projection = ledger.Projection.build(book.kept, entry["id"], book)
            dump = lambda record: json.dumps(record, sort_keys=True,  # noqa: E731
                                             ensure_ascii=False)
            header, rows = ledger.ledger_records(book.spans, book)
            (target / f"model-{edition}.spans.jsonl").write_text(
                dump(header) + "\n" + "".join(dump(row) + "\n" for row in rows),
                encoding="utf-8")
            (target / f"model-{edition}.nodes.jsonl").write_text(
                "".join(dump(record) + "\n"
                        for record in ledger.node_records(projection, book.spans)),
                encoding="utf-8")
            akn_path, manifest_path = akn.write(target, entry["id"], family,
                                                edition, projection, book)
            for path in (target / f"model-{edition}.spans.jsonl",
                         target / f"model-{edition}.nodes.jsonl",
                         akn_path, manifest_path):
                live[f"{artefact}{path.name}"] = path
            for path in views.write(destination / corpus.DERIVED, entry["id"],
                                    family, edition, projection, book):
                live[path.relative_to(destination).as_posix()] = path
            families.setdefault(family, []).append(edition)
            continue
        if produces == "positions":
            directory = root / entry["dir"]
            if not directory.is_dir():
                continue
            files, _report = mli.write_family(destination / "corpora" / "mli",
                                              directory, entry["id"], root)
            for path in files:
                live[f"{artefact}{path.name}"] = path
            # Each position's markdown view, rendered from the artefact just
            # written, so a published view of a position the reader has moved on
            # from is compared like any other derived artefact and republished
            # by `drift --write` beside the artefact it summarises.
            for path in views.write_positions(
                    destination / corpus.DERIVED,
                    destination / "corpora" / "mli" / "positions"):
                live[path.relative_to(destination).as_posix()] = path
            continue
        if produces in ("table", "mapping"):
            if entry["pdf"] is None:
                continue
            spans = ledger.SpanStream.read(entry["pdf"], entry["id"])
            book = ledger.Classifier.classify(spans, ledger.Ledger())
            for path in mli.write(destination / Path(artefact).parent, book,
                                  entry["id"], entry["pdf"]):
                live[artefact] = path
            # The signatories table's markdown view, rendered from the artefact
            # just written, so a published view of a table the reader has moved
            # on from is compared like any other derived artefact and
            # republished by `drift --write` beside the artefact it summarises.
            if entry["id"] == "mli-signatories-and-parties":
                for path in views.write_signatories(
                        destination / corpus.DERIVED, live[artefact]):
                    live[path.relative_to(destination).as_posix()] = path
    # The edition report is a view of the two editions the *corpus* holds, so it
    # is rebuilt from the live corpus in `destination` and not from the stored
    # one: a report that agreed with a reading the corpus no longer holds would
    # be exactly the drift this control exists to catch.
    for family, editions in families.items():
        ordered = sorted(editions)
        if len(ordered) < 2:
            continue
        for path in diff.write(destination / corpus.DERIVED, family,
                               ordered[0], ordered[-1], root=destination):
            live[path.relative_to(destination).as_posix()] = path
    return live


def _declared_artifacts(root: Path) -> list[Path]:
    """Every file the register says the corpus holds, whether or not it is here.

    Plus every file under `derived/`: the views and reports are not named one by
    one in the register, but all of them are generated, so a derived file the
    live build does not write is as much a published-but-unbuilt artefact as a
    ledger the register declares and nothing rebuilds.
    """
    root = Path(root)
    found: list[Path] = []
    for entry in corpus.declared_sources(root):
        artefact = entry["artefact"]
        if not artefact or entry["produces"] in (None, "none"):
            continue
        # Same reason as in `live_artifacts`: a vendored schema is pinned in a
        # manifest and checked by digest, not by rebuilding it.
        if entry["produces"] == "schema":
            continue
        target = root / artefact
        if artefact.endswith("/"):
            found.extend(path for path in sorted(target.glob("*"))
                         if path.is_file())
        else:
            found.append(target)
    derived = root / corpus.DERIVED
    if derived.is_dir():
        found.extend(path for path in sorted(derived.rglob("*")) if path.is_file())
    return found


def _manifest_lines(path: Path) -> list[tuple[str, str]]:
    """A `sha256  relative/path` manifest as (digest, path) pairs."""
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        out.append((digest.strip(), relative.strip()))
    return out


def provenance_differences(root: Path) -> list[dict]:
    """Recompute the register's hashes and its manifests from the bytes on disk.

    These files are the corpus' claim about the inputs it was built from, and
    they are not a reading: the live value here is the digest of the bytes that
    are actually here. A register `sha256` that no longer matches its file, or a
    manifest line whose digest is not the file's, is reported as a difference
    the same way a divergent artefact is, so `drift` answers "is everything the
    corpus publishes still true of the sources it names" and not only "is every
    document still what a fresh reading writes".
    """
    root = Path(root)
    out: list[dict] = []
    for entry in corpus.register_entries(root):
        ident = str(entry.get("id") or "")
        relative = str(entry.get("file") or "")
        declared = str(entry.get("sha256") or "")
        if declared and relative:
            path = root / relative
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != declared:
                    out.append({
                        "path": f"provenance/sources.yaml ({ident})",
                        "kind": "provenance",
                        "units": [{"unit": relative, "stored": declared,
                                   "live": digest}],
                    })
        manifest = str(entry.get("manifest") or "")
        if not manifest:
            continue
        manifest_path = root / manifest
        if not manifest_path.is_file():
            continue
        units: list[dict] = []
        for digest, listed in _manifest_lines(manifest_path):
            path = root / listed
            if not path.is_file():
                units.append({"unit": listed, "stored": digest, "live": None})
                continue
            live_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if live_digest != digest:
                units.append({"unit": listed, "stored": digest,
                              "live": live_digest})
        if units:
            out.append({"path": manifest, "kind": "provenance", "units": units})
    return out


def _walk(stored, live, path: str, out: list[dict]) -> None:
    """Collect the JSON paths at which two decoded documents disagree."""
    if type(stored) is not type(live):
        out.append({"unit": path or "$", "stored": stored, "live": live})
        return
    if isinstance(stored, dict):
        for key in sorted(set(stored) | set(live)):
            child = f"{path}.{key}" if path else key
            if key not in stored or key not in live:
                out.append({"unit": child, "stored": stored.get(key),
                            "live": live.get(key)})
            else:
                _walk(stored[key], live[key], child, out)
        return
    if isinstance(stored, list):
        for index in range(max(len(stored), len(live))):
            child = f"{path}[{index}]"
            if index >= len(stored) or index >= len(live):
                out.append({"unit": child,
                            "stored": stored[index] if index < len(stored) else None,
                            "live": live[index] if index < len(live) else None})
            else:
                _walk(stored[index], live[index], child, out)
        return
    if stored != live:
        out.append({"unit": path or "$", "stored": stored, "live": live})


def _line_difference(stored_text: str, live_text: str) -> list[dict]:
    stored, live = stored_text.splitlines(), live_text.splitlines()
    out = []
    for index in range(max(len(stored), len(live))):
        left = stored[index] if index < len(stored) else None
        right = live[index] if index < len(live) else None
        if left != right:
            out.append({"unit": f"line {index + 1}", "stored": left, "live": right})
    return out


def describe_difference(name: str, stored_text: str, live_text: str) -> list[dict]:
    """The smallest units at which two texts of one artefact disagree.

    A JSON document is compared by path (so the unit is the field, and a
    `covered_agreements` list is reported row by row); a JSONL ledger, an XML
    document or a markdown view by line; anything else by size. The units are
    what a repair needs to see: which row moved, not which byte.
    """
    if name.endswith((".jsonl", ".xml", ".md")):
        return _line_difference(stored_text, live_text)
    if name.endswith(".json"):
        try:
            stored, live = json.loads(stored_text), json.loads(live_text)
        except json.JSONDecodeError:
            return _line_difference(stored_text, live_text)
        out: list[dict] = []
        _walk(stored, live, "", out)
        return out
    return [{"unit": "bytes", "stored": len(stored_text),
             "live": len(live_text)}]


# A line unit is `line <n>` and nothing else (1-based); a size unit is the
# fallback `describe_difference` reaches for when a format's lines are not
# compared, spelled in the few ways a counter can be named.
_LINE_UNIT_RE = re.compile(r"^line [1-9]\d*$")
_SIZE_UNITS = frozenset({"bytes", "size", "length", "chars", "digits"})


def schema_violations(result: dict) -> list[str]:
    """Every difference unit that names a size instead of a place in the file.

    The material `pr_body` publishes reports a divergence by the smallest unit
    that moved: a JSON path (the field, with its row index -
    `covered_agreements[6].signature`) or a line (`line 3`, a ledger or XML
    line, a markdown view line). `describe_difference` falls back to a byte
    count for a format whose lines nothing compares, and a byte count cannot be
    reviewed: it says the file changed size, not what moved. This is the
    detector for that fallback, run over exactly the differences the automated
    control would put in a pull request - the corpus artefacts and the
    register's own hashes - so a difference the body could not name is a check
    failure and not a diff nobody can read.

    A provenance difference names a file (the register's own claim about a
    source), never a position inside one, so its unit is checked as a file name
    rather than as a line.
    """
    problems: list[str] = []
    for item in result["differences"]:
        path, kind = str(item["path"]), item.get("kind")
        for unit in item["units"]:
            label = str(unit.get("unit") or "")
            if kind == "provenance":
                if not label or label in _SIZE_UNITS:
                    problems.append(f"{path}: {label!r} names no file")
                continue
            if path.endswith((".jsonl", ".xml", ".md")):
                if not _LINE_UNIT_RE.match(label):
                    problems.append(f"{path}: {label!r} names no line")
                continue
            if path.endswith(".json"):
                if not label or label in _SIZE_UNITS:
                    problems.append(f"{path}: {label!r} names no field")
                continue
            problems.append(f"{path}: {label!r} names no line")
    return problems


def compare_corpus(root: Path, destination: Optional[Path] = None) -> dict:
    """Rebuild the declared artefacts and compare them with the published ones.

    Returns `differences` (per artefact: whether it is missing from the corpus,
    and the units that disagree, plus the provenance differences that no live
    file can be copied for), `compared`, `provenance` and the `workdir` the
    fresh artefacts were written into, so a caller that wants to republish the
    divergent ones does not have to read them again.
    """
    root = Path(root)
    if destination is None:
        destination = Path(tempfile.mkdtemp(prefix="itld-drift-"))
    live = live_artifacts(root, Path(destination))
    differences = []
    for relative in sorted(live):
        stored = root / relative
        if not stored.is_file():
            differences.append({"path": relative, "kind": "unpublished",
                                "units": []})
            continue
        stored_bytes = stored.read_bytes()
        if stored_bytes == live[relative].read_bytes():
            continue
        differences.append({
            "path": relative, "kind": "differs",
            "units": describe_difference(
                relative, stored_bytes.decode("utf-8", "replace"),
                live[relative].read_bytes().decode("utf-8", "replace")),
        })
    unbuilt = [path.relative_to(root).as_posix()
               for path in _declared_artifacts(root)
               if path.relative_to(root).as_posix() not in live and path.is_file()]
    provenance = provenance_differences(root)
    differences.extend(provenance)
    return {"workdir": Path(destination), "live": live, "compared": len(live),
            "differences": differences, "provenance": len(provenance),
            "published_but_unbuilt": unbuilt}


def format_difference(item: dict, limit: int = 40) -> list[str]:
    """The lines one artefact's difference is reported in."""
    lines = [f"{item['kind']}: {item['path']}"]
    for unit in item["units"][:limit]:
        lines.append(f"  {unit['unit']}: corpus {unit['stored']!r} "
                     f"-> reading {unit['live']!r}")
    if len(item["units"]) > limit:
        lines.append(f"  ... and {len(item['units']) - limit} more unit(s)")
    return lines


def divergent_artifacts(result: dict) -> list[dict]:
    """The differences a fresh reading can republish, in corpus order.

    A provenance difference has no live file to copy - it is the register's own
    claim about the bytes, not a document the pipeline writes - so it is never
    one of these. Everything else is: the artefact that diverged, and the file
    the live reading just wrote for it.
    """
    return [item for item in result["differences"]
            if item["path"] in result["live"]]


def pr_title(result: dict) -> str:
    """The pull request's subject: which artefacts the reading moved on."""
    artifacts = divergent_artifacts(result)
    if len(artifacts) == 1:
        where = f"{artifacts[0]['path']}"
    else:
        where = f"{len(artifacts)} artefacts"
    return f"drift: rebuild {where} from the live reading"


def pr_body(result: dict) -> str:
    """The pull request's body: only the regenerated artefacts, row by row.

    The body is the drift control's own output - the artefact paths it would
    republish and, for each, the units that disagree - so a reviewer sees the
    rewrite the reading asks for without opening the diff hunks. It is a
    function of the comparison alone, which is what lets the automated check
    open the request without inventing prose about the repair.
    """
    artifacts = divergent_artifacts(result)
    lines = ["## Corpus drift", "",
             f"`python -m harness drift` compared {result['compared']} artefact(s) "
             f"with a fresh reading and found {len(artifacts)} that no longer "
             f"match it. This pull request contains only those regenerated "
             f"artefacts.", ""]
    if artifacts:
        lines += ["### Artefacts", ""]
        lines += [f"- `{item['path']}`" for item in artifacts]
        lines += [""]
    lines += ["### Row by row", ""]
    if not artifacts:
        lines.append("_No document diverged._")
    for item in artifacts:
        lines += ["```", *format_difference(item), "```", ""]
    provenance = [item for item in result["differences"]
                  if item["path"] not in result["live"]]
    if provenance:
        lines += ["### Provenance", "",
                  "The register's own hashes no longer match the bytes on disk; "
                  "these are not republished by this pull request and need a "
                  "deliberate edit:", ""]
        for item in provenance:
            lines += ["```", *format_difference(item), "```", ""]
    if result["published_but_unbuilt"]:
        lines += ["### Published but unbuilt", "",
                  "The register declares these and nothing in the pipeline "
                  "builds them; they are named here and never deleted:", ""]
        lines += [f"- `{relative}`" for relative in result["published_but_unbuilt"]]
        lines += [""]
    lines += ["---", "",
              "Generated by `python -m harness drift`. The units above are the "
              "comparison's own (a JSON path, a ledger line, an XML line); the "
              "artefacts were rewritten by the corpus' own writers.", ""]
    return "\n".join(lines)
