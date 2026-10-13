"""The invariants of SPEC.md, as tests.

Every test here fails - loudly, with a message that names the artefact it is
waiting for - until the extractor produces that artefact. That is the intended
state of this repository: the specification is written first, so the failures
are the specification talking.

The tests that *can* run today are the ones about this repository's own
artefacts: the source register (F11), the working language (F13) and the absence
of environment traces (F14). They are genuinely green, not green by emptiness:
each carries a self-test that proves its detector still detects.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from harness import corpus, drift, ledger
from harness import akn as akn_writer
from harness import diff as diff_writer
from harness import mli as mli_writer
from harness import views as view_writer
from harness.checks import LOCAL_PATH_RE
from harness.ledger import ledger_records
from harness.language import violations
from mli_row_audit import (ARTIFACT_SLUGS, DEFECT_INVENTORY,
                           LEGACY_DEFECT_INVENTORY, ROW_FIELDS,
                           audit_block_rows, audit_published_artifacts,
                           audit_scope_lists,
                           block_reading, block_rows_at, block_tolerances,
                           compare_published_rows, derived_tolerances,
                           covered_attach_band, format_row_divergences,
                           heading_habit, legacy_reading,
                           number_first_attach_band, number_first_rows_at,
                           position_view_divergences, scope_view_divergences,
                           signatories_geometry,
                           signatories_rows_at,
                           signatories_view_divergences, tolerance_audit)
from support import ROOT, UNBUILT

# The UN Model prints three of its articles in two variants each, in both
# editions: articles 8, 18 and 25. Two alternatives times three articles.
ALTERNATIVE_ARTICLES = ("8", "18", "25")
ALTERNATIVE_NAME = re.compile(r"^alternative-[AB]$")


def _need(condition, what):
    if not condition:
        pytest.fail(UNBUILT.format(what=what))


def _git_root() -> Path | str | None:
    """The repository root git resolves to here, or None if there is none."""
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _edition_files(family: str, edition: str, suffix: str) -> list[Path]:
    return sorted(corpus.edition_dir(ROOT, family, edition).glob(f"*{suffix}"))


# --------------------------------------------------------------------------- #
# F1 - completeness
# --------------------------------------------------------------------------- #

def test_f01_completeness_counts():
    editions = corpus.editions(ROOT)
    _need(editions, "the corpus (corpora/<family>/<edition>/)")
    problems: list[str] = []
    for family, edition in editions:
        manifest = corpus.manifest(ROOT, family, edition)
        akn = corpus.akn(ROOT, family, edition)
        where = f"{family}/{edition}"
        if manifest is None or len(akn) != 1:
            problems.append(f"{where}: exactly one manifest and one AKN file required, "
                            f"found {manifest is not None} / {len(akn)}")
            continue
        data = corpus.load_json(manifest)
        declared = data.get("units") or {}
        observed = corpus.node_tags(akn[0])
        if not declared:
            problems.append(f"{where}: manifest declares no unit counts, so nothing "
                            f"can be compared with the source")
        for kind, expected in declared.items():
            if observed.get(kind, 0) != expected:
                problems.append(f"{where}: manifest says {expected} {kind}, the AKN "
                                f"has {observed.get(kind, 0)}")
        for entry in data.get("missing") or []:
            if not isinstance(entry, dict) or not entry.get("id") \
                    or not str(entry.get("reason") or "").strip():
                problems.append(f"{where}: a `missing` entry without an id and a "
                                f"reason: {entry!r}")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# F2 - no insertion
# --------------------------------------------------------------------------- #

def test_f02_no_insertion():
    editions = corpus.editions(ROOT)
    _need(editions, "the corpus")
    problems: list[str] = []
    for family, edition in editions:
        where = f"{family}/{edition}"
        akn = corpus.akn(ROOT, family, edition)
        ledgers = _edition_files(family, edition, ".spans.jsonl")
        _need(akn and ledgers, f"the AKN and the span ledger of {where}")
        spans = corpus.load_spans(ledgers[0])
        if not spans:
            problems.append(f"{where}: the ledger is empty")
            continue
        body = corpus.akn_text(akn[0])
        body_words = set(corpus.words(body))
        # The kept text as the *ledger itself* reads it: each span's text with
        # the rewrites that span's record declares, spans of one printed line
        # glued the way the printer printed them, lines separated by the space
        # the break stands for. Reading the records and not "the kept spans'
        # texts joined with spaces" is the difference between a comparison and a
        # puzzle: joining every span with a space injects a space inside words
        # that touch across a font-run boundary, so "(e)," in the corpus and
        # "(e)" + "," in the spans were 30-odd false alarms, while the real
        # defects of the day - "(2)with", "()", "day-today", "establishb c
        # ment" - hid among them.
        policy = ledger.LinePolicy.from_params(
            "test_f02", corpus.ledger_header(ledgers[0]).get("line_policy"))
        # `cut_markers=False`: the AKN's own text includes the paragraph numbers,
        # because the writer puts them in `<num>`, so the reading they are
        # compared with must include them as well.
        kept = ledger.reading_of(spans, policy, cut_markers=False)

        # (a) text that a rule dropped must not be in the corpus, anywhere -
        #     unless a kept span also carries those words.
        problems += [f"{where}: {line}" for line in _insertions(spans, body, kept)]

        # (b) every word of the corpus must come from a span that was kept.
        kept_words = set(corpus.words(kept))
        stray = sorted(body_words - kept_words)[:6]
        if stray:
            problems.append(f"{where}: {len(body_words - kept_words)} word(s) in the "
                            f"corpus are in no kept span, e.g. {stray}")
    assert not problems, "\n".join(problems)


def _insertions(spans: list, body: str, kept_text: str) -> list[str]:
    """Corpus text that a dropped span carried and no kept span does.

    The guard is not a loophole; it is what the invariant means. "A dropped
    span's text never appears in the corpus" is false of this source as a matter
    of fact: the Commentaries quote the articles verbatim, so "PERSONS COVERED"
    is dropped as a commentary heading and kept as the heading of article 1, and
    "Articles 1 and 2" is a running header and also a cross-reference inside
    article 26(1). A check that fired on those would be a check that fires on a
    correct corpus - which is how a harness stops being believed. An *insertion*
    is narrower and is what this tests: corpus text that no kept span put there.

    It is a real check, not a restatement: text the corpus has and the kept
    spans do not is text something invented, and the self-test below makes sure
    the guard has not turned it into a check that can only pass.
    """
    body, kept_text = _canonical(body), _canonical(kept_text)
    found: list[str] = []
    for span in spans:
        if span.get("decision") != "drop":
            continue
        text = _canonical(str(span.get("text") or ""))
        if len(text) < 12 or text not in body or text in kept_text:
            continue
        found.append(f"dropped by {span.get('rule') or '<no rule>'} yet present "
                     f"in the corpus: {text[:70]!r}")
    return found


# A hyphen or a soft hyphen followed by a break is one word broken across two
# lines, not two words. The projection puts such a word back together (the
# ledger declares the join) and a *dropped* span keeps the mark, because nothing
# rewrote it - so a comparison of words has to be made on both sides of that
# mark. Otherwise "pur<soft hyphen> pose" and "purpose" never meet, and the
# check reports the Commentaries' habit of quoting the articles as an insertion.
_LINE_BREAK_MARK = re.compile(r"[-\u00ad]\s+")


def _canonical(text: str) -> str:
    return " ".join(corpus.words(_LINE_BREAK_MARK.sub("", text)))


def test_f02_detector_still_catches_an_insertion():
    """The recurrence guard must not have made the check vacuous."""
    dropped = [{"decision": "drop", "rule": "R-RUNNING-HEADER",
                "text": "Articles 24 and 25"}]
    kept = [{"decision": "keep", "rule": "R-BODY-TEXT",
             "text": "Taxes covered by this Convention are taxes on income."}]
    inserted = ("in that other State, be deductible Articles 24 and 25 under "
                "the same conditions")
    assert _insertions(dropped, inserted, kept[0]["text"]), \
        "the insertion check no longer sees apparatus inside a sentence"
    legitimately_quoted = ("... is not restricted by Articles 24 and 25. The "
                           "competent authorities of the Contracting States")
    assert not _insertions(dropped, legitimately_quoted,
                           "not restricted by Articles 24 and 25"), \
        "the recurrence guard does not recognise words a kept span already has"


# --------------------------------------------------------------------------- #
# F4 - faithful structure
# --------------------------------------------------------------------------- #

FAKE_PARAGRAPH_LABEL = re.compile(
    r"^\*\*\d{1,2}\.\*\*\s+Article \d{1,2}[A-Z]?\s+\([Aa]lternative [AB]\)\s*$", re.M)


def test_f04_structure_is_nodes_not_text():
    articles = corpus.markdown_articles(ROOT)
    _need(articles, "the markdown view (derived/markdown/**/article-*.md)")
    problems: list[str] = []
    for path in articles:
        match = FAKE_PARAGRAPH_LABEL.search(path.read_text(encoding="utf-8"))
        if match:
            problems.append(f"{path.relative_to(ROOT)}: an alternative printed as a "
                            f"numbered paragraph: {match.group(0)!r}")

    editions = corpus.editions(ROOT)
    _need(editions, "the corpus")
    for family, edition in editions:
        akn = corpus.akn(ROOT, family, edition)
        _need(akn, f"the AKN of {family}/{edition}")
        names = corpus.hcontainer_names(akn[0])
        found = [n for n in names if ALTERNATIVE_NAME.match(n)]
        expected = 2 * len(ALTERNATIVE_ARTICLES)
        if len(found) != expected:
            problems.append(
                f"{family}/{edition}: {len(found)} alternative branch node(s) in "
                f"the AKN, expected {expected} (articles "
                f"{', '.join(ALTERNATIVE_ARTICLES)} - each printed as "
                f"<hcontainer name=\"alternative-A|B\">)")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# F6 - traceability
# --------------------------------------------------------------------------- #

def test_f06_every_leaf_has_provenance():
    """Every leaf the AKN holds can be followed back into the span ledger.

    A range that is merely well-formed proves nothing: `[3, 9]` is in order and
    resolves to nothing. So each leaf is resolved - the records between the two
    numbers are read out of the ledger beside the AKN, and they must exist, must
    be on the page the node index records, and must be a contiguous run in
    document order, which is what a leaf of one document is.
    """
    editions = corpus.editions(ROOT)
    _need(editions, "the corpus")
    problems: list[str] = []
    for family, edition in editions:
        where = f"{family}/{edition}"
        akn = corpus.akn(ROOT, family, edition)
        nodes = _edition_files(family, edition, ".nodes.jsonl")
        ledgers = _edition_files(family, edition, ".spans.jsonl")
        _need(akn and nodes and ledgers,
              f"the AKN, the node index and the span ledger of {where}")
        leaves = corpus.eids(akn[0])
        index = {n.get("eId"): n for n in corpus.load_spans(nodes[0])}
        spans = corpus.load_spans(ledgers[0])
        if not leaves:
            problems.append(f"{where}: the AKN has no leaf to trace")
        for eid, tag in leaves.items():
            entry = index.get(eid)
            if entry is None:
                problems.append(f"{where}: leaf {tag} {eid} has no provenance entry")
                continue
            where_it_lives = entry.get("spans") or []
            if not entry.get("page") and entry.get("page") != 0:
                problems.append(f"{where}: {eid} has no page")
            if len(where_it_lives) != 2 or where_it_lives[0] > where_it_lives[1]:
                problems.append(f"{where}: {eid} has a malformed span range "
                                f"{where_it_lives!r}")
                continue
            low, high = where_it_lives
            if low < 0 or high >= len(spans):
                problems.append(f"{where}: {eid} points at spans {low}..{high} of "
                                f"a ledger with {len(spans)} records")
                continue
            pages = {spans[i].get("page") for i in range(low, high + 1)}
            if entry.get("page") not in pages:
                problems.append(f"{where}: {eid} says page {entry.get('page')} and "
                                f"its spans lie on {sorted(pages)}")
            if any(not str(spans[i].get("text") or "") for i in range(low, high + 1)):
                problems.append(f"{where}: {eid} resolves to a span with no text")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# F7 - determinism
# --------------------------------------------------------------------------- #

GENERATED_PATTERNS = ("derived/fts/*", "*.db", "*.sqlite", "*.sqlite3",
                      "*__pycache__*", "*.pyc")


def test_f07_no_generated_artifacts_tracked():
    root = _git_root()
    if root is None or Path(root) != ROOT.resolve():
        pytest.skip("this project is not yet a git repository of its own, so "
                    "'tracked' has no meaning here")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    bad = sorted({p for p in tracked
                  for pattern in GENERATED_PATTERNS if fnmatch.fnmatch(p, pattern)})
    assert not bad, ("generated, non-reproducible artefacts are tracked; they "
                     f"belong in .gitignore: {bad}")


def test_f07_every_source_declares_what_is_built_from_it():
    """The register says what each source is for, and says when it is not built.

    This is the test that keeps the green in `test_f07_build_is_byte_identical`
    from meaning "the ones we could build are": every source declares what is
    produced from it, and a source that declares no corpus artefact has to say
    why. Silence is what the audit of 2026-09-27 found twice - a hash file whose
    name did not describe its contents (F11's anti-pattern) and a corpus whose
    source register covered two of six inputs - so a source with no declaration
    is a failure here, not a source that was quietly left out.
    """
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    problems: list[str] = []
    for entry in sources:
        what = entry["produces"]
        if what not in corpus.PRODUCES:
            problems.append(f"{entry['id']}: does not declare what is built from "
                            f"it (`produces`), or declares {what!r}; declared "
                            f"values are {', '.join(corpus.PRODUCES)}")
            continue
        if what == "none" and not entry["pending"]:
            problems.append(f"{entry['id']}: declares that no corpus artefact is "
                            f"built from it and gives no reason "
                            f"(`produces_pending`)")
        if what == "schema":
            # A vendored standard is the one artefact this pipeline does not
            # write: it is copied in and then checked against, so the register
            # has to say which files, and every one of them has to be here. A
            # declared-and-absent schema would be a validation that cannot run,
            # which is the state this entry replaced.
            if not entry["files"]:
                problems.append(f"{entry['id']}: declares a vendored standard "
                                f"and names no file (`files`)")
            for name in entry["files"]:
                if not (ROOT / name).is_file():
                    problems.append(f"{entry['id']}: {name} is declared and is "
                                    f"not here")
            if not entry["manifest"]:
                problems.append(f"{entry['id']}: a vendored copy is what the "
                                f"validation runs against, and it is pinned in "
                                f"a manifest: this entry declares none")
    assert not problems, "\n".join(problems)


def test_f07_build_is_byte_identical(tmp_path):
    """Build twice into two directories, then compare every byte.

    The comparison is the artefacts the register declares, built for every
    source whose bytes are here: the span ledger, the node index, the AKN
    document, its manifest and the markdown view where the register says `akn`,
    and the span ledger alone where it says `none` - because a source whose
    corpus artefact is not built yet still has a reading, and a reading that is
    not reproducible is a corpus nobody can check.

    It fails on the first byte that differs, naming it, and it fails when a
    source that could not be built is simply missing from the comparison. Two
    things are therefore deliberately *not* failures here, because they are
    declarations rather than omissions, and both are counted in the status
    report: a source declared `none` (its corpus artefact is the next artefact),
    and a source whose PDF has not been fetched.

    One source is compared differently, and it is the one that is not one
    document: the MLI positions are one register entry for 110 documents, and
    reading them takes a minute. So the family is read *once* here and every
    artefact it produces is compared byte for byte with the corpus this
    repository holds - which was written by an earlier process, and a corpus that
    depended on the process that wrote it (a set's order, a machine's paths, a
    clock) would differ. Building it twice, in this process, would cost another
    minute to compare a reading with itself.
    """
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    problems: list[str] = []
    pending: list[str] = []
    compared: list[str] = []
    for entry in sources:
        if entry["produces"] not in corpus.PRODUCES:
            continue
        if entry["dir"]:
            source = entry["id"]
            directory = ROOT / entry["dir"]
            if not directory.is_dir():
                pending.append(f"{source}: {entry['dir']} is not here")
                continue
            try:
                data = mli_writer.family_once(directory, source, ROOT)
                where = tmp_path / "run1" / source / "mli"
                written, _report = mli_writer.write_family(
                    where, directory, source, ROOT, data=data)
            except ledger.RuleError as exc:
                pending.append(f"{source}: {exc}")
                continue
            stored = corpus.corpus_root(ROOT) / "mli" / "positions"
            for path in written:
                kept = stored / path.name
                if not kept.is_file():
                    problems.append(f"{source}/{path.name}: the corpus this "
                                    f"repository holds does not have it")
                elif kept.read_bytes() != path.read_bytes():
                    problems.append(f"{source}/{path.name}: the corpus this "
                                    f"repository holds differs from what the "
                                    f"code builds")
            compared.append(source)
            continue
        if entry["pdf"] is None:
            continue
        source = entry["id"]
        written: list = []
        for run in (1, 2):
            where = tmp_path / f"run{run}" / source
            where.mkdir(parents=True)
            try:
                spans = ledger.SpanStream.read(entry["pdf"], source)
                book = ledger.Classifier.classify(spans, ledger.Ledger())
                if entry["produces"] == "akn":
                    projection = ledger.Projection.build(book.kept, source, book)
                    written.append(_write_edition(where, source, book, projection))
                elif entry["produces"] == "table":
                    written.append(_write_table(where, source, book, entry["pdf"]))
                elif entry["produces"] == "positions":
                    written.append(_write_positions(where, source, book, entry["pdf"]))
                elif entry["produces"] == "mapping":
                    written.append(_write_mapping(where, source, book, entry["pdf"]))
                else:
                    written.append(_write_reading(where, source, book))
            except ledger.RuleError as exc:
                # The reading, the projection or the writer refused. Reported
                # rather than skipped: a source that cannot be built - because no
                # rule claims a span, because a rule names a condition nobody
                # implemented, because the projection has no place for a node -
                # is not a source that passed.
                pending.append(f"{source}: {exc}")
                break
        if len(written) == 2:
            compared.append(source)
            for name in sorted(written[0]):
                first, second = written[0][name], written[1][name]
                if first.read_bytes() != second.read_bytes():
                    problems.append(f"{source}/{name}: the two runs differ")
    assert not problems, (
        "the same input produced different artefacts:\n" + "\n".join(problems))
    assert compared, "no source could be classified, so nothing was compared"

    _need(not pending,
          "the determinism claim over every artefact: it covers {n} source(s) "
          "today and not the rest of the corpus - {pending}".format(
              n=len(compared), pending="; ".join(pending) or "nothing"))


def test_f07_a_family_is_built_once_per_process(monkeypatch):
    """One build of a family serves every call for it in the same process.

    Reading a family is the most expensive act this suite performs - the MLI
    positions are 104 PDFs and about a minute of work - and every caller asks
    for the same reading: a rule comparing artefacts with their source, a test
    rebuilding the corpus, a later command in one process. The build is cached
    under its (directory, source, root) and this pins that claim: a second call
    is served the first build, not a second reading of the directory.
    """
    calls: list[tuple] = []

    def counted_build(directory: Path, source: str, root: Path) -> dict:
        calls.append((directory, source, root))
        return {"positions": {}, "report": {}}

    directory = Path("/family-cache-probe")
    root = Path("/family-cache-root")
    mli_writer._FAMILY_BUILDS.pop((directory, "probe-family", root), None)
    monkeypatch.setattr(mli_writer, "_family_build", counted_build)

    first = mli_writer.family_once(directory, "probe-family", root)
    second = mli_writer.family_once(directory, "probe-family", root)

    assert calls == [(directory, "probe-family", root)], (
        "the family was read again in the same process - one build must serve "
        "every call for the same (directory, source, root)")
    assert first is second, "the second call was served a different build"


def test_f07_every_published_artefact_matches_a_fresh_reading(tmp_path):
    """Every published artefact is compared with the reading that produces it.

    The determinism test above builds each source twice and compares the two
    runs, and for the positions family it compares one build with the corpus -
    but for every other artefact (the UN Model editions, the MLI mapping, the
    signatories table) it compares the runs with each other, never with what is
    published. So a writer that changed and a corpus nobody rebuilt could both
    stand, and did: the published `corpora/mli/mapping.json` still carried the
    register's earlier note prose and its `bit 4` sentence while the reader had
    been corrected to `bit 16`. This control rebuilds every artefact the
    register declares with the corpus' own writers and compares it with the
    published file, unit by unit - a JSON path
    (`covered_agreements[11].instrument`), a ledger line, an XML line - so a
    divergence names the row and the field rather than the file.

    The comparator carries its own detector test: `describe_difference` is
    asked about two documents that differ in exactly one field and must name
    that field, so the green cannot be green by emptiness.
    """
    probe = drift.describe_difference(
        "position.json",
        json.dumps({"covered_agreements": [{"no": 1, "title": "Canada"}]}),
        json.dumps({"covered_agreements": [{"no": 1, "title": "Chile"}]}))
    assert probe == [{"unit": "covered_agreements[0].title",
                      "stored": "Canada", "live": "Chile"}], probe

    report = drift.compare_corpus(ROOT, tmp_path)
    _need(report["compared"],
          "a declared corpus artefact compared with a fresh reading")
    # Every unit a divergence is reported in must name a place in its file - a
    # JSON path, a ledger line, an XML line, a view line - and never a byte
    # count: the material the automated control would put in a pull request has
    # to be legible, for the derived artefacts as much as for the corpus.
    assert not drift.schema_violations(report), (
        "a difference names a size instead of a line:\n" +
        "\n".join(drift.schema_violations(report)))
    problems: list[str] = []
    for item in report["differences"]:
        problems.extend(drift.format_difference(item))
    for relative in report["published_but_unbuilt"]:
        problems.append(f"{relative}: published, and no source in the register "
                        f"builds it")
    assert not problems, (
        "the corpus lags the reader - rebuild the artefacts so every field the "
        "reader measures is the field the corpus holds, or say why they "
        "differ:\n" + "\n".join(problems))


def _write_edition(directory: Path, source: str, book, projection) -> dict:
    """Every artefact of one AKN edition, written into `directory`.

    The names are the corpus' own (`model-<edition>.spans.jsonl`, ...), and for a
    reason: the manifest records the digest of the ledger beside it, so a fixture
    that renamed the ledger would produce an artefact the corpus never produces -
    and a determinism test over files nobody ships proves nothing.
    """
    import json

    header, rows = ledger_records(book.spans, book)
    dump = lambda record: json.dumps(record, sort_keys=True, ensure_ascii=False)
    ledger_text = dump(header) + "\n" + "".join(dump(row) + "\n" for row in rows)
    family, _, edition = source.rpartition("-")
    spans_path = directory / f"model-{edition}.spans.jsonl"
    spans_path.write_text(ledger_text, encoding="utf-8")
    nodes_path = directory / f"model-{edition}.nodes.jsonl"
    nodes_path.write_text(
        "".join(dump(record) + "\n"
                for record in ledger.node_records(projection, book.spans)),
        encoding="utf-8")
    written = {spans_path.name: spans_path, nodes_path.name: nodes_path}
    akn_path, manifest_path = akn_writer.write(directory, source, family, edition,
                                               projection, book)
    written[akn_path.name] = akn_path
    written[manifest_path.name] = manifest_path
    for name, text in view_writer.documents(projection, book, source).items():
        view = directory / f"view-{name}"
        view.write_text(text, encoding="utf-8")
        written[view.name] = view
    return written


def _write_table(directory: Path, source: str, book, pdf: Path) -> dict:
    """The source's own document, written by the writer the corpus uses.

    The corpus' name for it (`signatories-and-parties.json`), written into a
    temporary directory: the point is not where it goes but that the thing
    compared is the thing the corpus holds, produced by the same code path.
    """
    return {path.name: path
            for path in mli_writer.write(directory, book, source, pdf)}


def _write_positions(directory: Path, source: str, book, pdf: Path) -> dict:
    """A country's position, written by the writer the corpus uses.

    The name is the slug the projection measured off the document's own title, so
    the thing compared is the thing the corpus holds, produced by the same code
    path and under the same name.
    """
    return {path.name: path
            for path in mli_writer.write(directory, book, source, pdf)}


def _write_mapping(directory: Path, source: str, book, pdf: Path) -> dict:
    """The MLI-to-treaty mapping, written by the writer the corpus uses."""
    return {path.name: path
            for path in mli_writer.write(directory, book, source, pdf)}


def _write_reading(directory: Path, source: str, book) -> dict:
    """The reading of a source whose corpus artefact is declared `none`.

    It has no corpus name to borrow, so it is written as `reading.spans.jsonl` -
    a name that says what the file is, and cannot be mistaken for one of the
    corpus' own. That is the honest form of the claim: this source is read, and
    what is read from it is reproducible, while the document the corpus will
    hold from it does not exist yet.
    """
    import json

    header, rows = ledger_records(book.spans, book)
    dump = lambda record: json.dumps(record, sort_keys=True, ensure_ascii=False)
    reading = directory / "reading.spans.jsonl"
    reading.write_text(dump(header) + "\n"
                       + "".join(dump(row) + "\n" for row in rows),
                       encoding="utf-8")
    return {reading.name: reading}


# --------------------------------------------------------------------------- #
# F11 - source provenance
# --------------------------------------------------------------------------- #

REGISTER_REQUIRED = ("id", "title", "retrieved", "rights")

# Built at runtime rather than written out, so that this test file stays free of
# the very token it tests for: invariant F14 applies to the tests as well.
FAKE_LOCAL_PATH = "/" + "Users" + "/someone/corpus.xml"


def _register() -> list[dict]:
    path = corpus.register(ROOT)
    _need(path.exists(), "the source register (provenance/sources.yaml)")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def test_f11_manifest_is_complete():
    entries = _register()
    assert entries, "the source register is empty"
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        ident = entry.get("id", "<no id>")
        for key in REGISTER_REQUIRED:
            if not entry.get(key):
                problems.append(f"{ident}: missing {key}")
        if ident in seen:
            problems.append(f"{ident}: duplicate id")
        seen.add(ident)
        rights = entry.get("rights") or {}
        for key in ("status", "basis", "verified_on"):
            if not rights.get(key):
                problems.append(f"{ident}: rights.{key} is empty")
        if not entry.get("url") and not entry.get("url_pattern"):
            problems.append(f"{ident}: no url and no url_pattern")
        if not entry.get("sha256") and not entry.get("files") \
                and not entry.get("url_pattern"):
            problems.append(f"{ident}: no sha256, no files and no url_pattern")

    # completeness: nothing may sit in sources/ without being registered.
    local = [p for p in (ROOT / "sources").rglob("*") if p.is_file()]
    registered_files = {e["file"] for e in entries if e.get("file")}
    registered_dirs = {e["dir"] for e in entries if e.get("dir")}
    for path in local:
        rel = path.relative_to(ROOT).as_posix()
        covered = (rel in registered_files
                   or any(rel.startswith(d.rstrip("/") + "/") for d in registered_dirs))
        if not covered and not rel.startswith("."):
            problems.append(f"sources/{path.relative_to(ROOT / 'sources')} is not "
                            f"in the register")
    for directory in sorted(registered_dirs):
        manifest = next((e.get("manifest") for e in entries
                         if e.get("dir") == directory), None)
        if manifest and (ROOT / directory).is_dir() and not (ROOT / manifest).exists():
            problems.append(f"{directory}: files present but {manifest} is missing")
    assert not problems, "\n".join(problems)


def test_f11_hashes_match_if_present():
    entries = _register()
    local = [p for p in (ROOT / "sources").rglob("*") if p.is_file()]
    if not local:
        pytest.skip("no source PDF is present locally, so there is no byte to "
                    "verify - run the fetch step, then this test speaks")
    problems: list[str] = []
    for entry in entries:
        file = entry.get("file")
        expected = entry.get("sha256")
        if not file or not expected or not (ROOT / file).is_file():
            continue
        digest = hashlib.sha256((ROOT / file).read_bytes()).hexdigest()
        if digest != expected:
            problems.append(f"{entry['id']}: {file} hashes to {digest}, the register "
                            f"says {expected}")

    # A batch entry delegates its per-file hashes to a manifest; the manifest is
    # exactly as binding as an inline hash, so it is verified the same way.
    for entry in entries:
        manifest = entry.get("manifest")
        if not manifest or not (ROOT / manifest).is_file():
            continue
        for lineno, line in enumerate(
                (ROOT / manifest).read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split(None, 1)
            if len(parts) != 2:
                problems.append(f"{manifest}:{lineno}: not a `hash  path` line")
                continue
            digest, rel = parts[0], parts[1].strip()
            path = ROOT / rel
            if not path.is_file():
                problems.append(f"{manifest}:{lineno}: {rel} is not here")
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                problems.append(f"{manifest}:{lineno}: {rel} does not match its hash")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# F13 - single language
# --------------------------------------------------------------------------- #

def test_f13_no_italian_in_project_artifacts():
    found = violations(ROOT)
    assert not found, "\n".join(
        f"{path.relative_to(ROOT)}:{lineno}: {word!r}" for path, lineno, word in found[:40])


def test_f13_detector_still_catches_italian(tmp_path):
    """The detector is exempt from itself; this proves it still bites.

    The sample lives in `fixtures/` (an exempt directory) and is copied into a
    temporary project, so that the detector's own test data cannot trip the
    detector on the real tree.
    """
    sample = tmp_path / "docs" / "sample.md"
    sample.parent.mkdir(parents=True)
    sample.write_text((ROOT / "fixtures" / "language-sample.txt").read_text(
        encoding="utf-8"), encoding="utf-8")
    assert violations(tmp_path), ("the Italian detector found nothing in a "
                                 "deliberately Italian sample, so the check "
                                 "would be worthless")


# --------------------------------------------------------------------------- #
# F9 - view consistency
# --------------------------------------------------------------------------- #

DIFF_REPORT = ROOT / "derived/reports/diff-un-model-2017-2021.md"


def test_f09_diff_report_is_a_view_of_the_corpus():
    """The diff is rendered again from the corpus and compared, byte for byte.

    A view is a function of the corpus, and the way to say that in a test is to
    produce it once more and compare. A report that differs from what the corpus
    renders now is a report of another corpus - an earlier build, or (defect d24)
    a second reading of the two PDFs, which is where its changes came from.

    The comparison is byte for byte over both forms of the report, and the
    summary line is checked against the corpus as well, so that a stale file
    reports which number moved rather than just that it moved.
    """
    _need(DIFF_REPORT.exists(),
          "the edition diff (derived/reports/diff-un-model-2017-2021.md), built "
          "with `python -m harness diff --write`")
    editions = [edition for family, edition in corpus.editions(ROOT)
                if family == "un-model"]
    _need(len(editions) >= 2, "two editions of un-model to diff")
    fresh = diff_writer.documents("un-model", editions[0], editions[-1], ROOT)
    problems: list = []
    for name, text in sorted(fresh.items()):
        path = DIFF_REPORT.parent / name
        if not path.exists():
            problems.append(f"{name}: not built")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{name}: not what the corpus renders now")
    assert not problems, (
        "the diff report is not the view of the corpus: " + ", ".join(problems)
        + " - rebuild it with `python -m harness diff --write`")

    data = diff_writer.compare("un-model", editions[0], editions[-1], ROOT)
    text = DIFF_REPORT.read_text(encoding="utf-8")
    for key, value in sorted(data["counts"].items()):
        assert re.search(rf"{key}\W{{0,4}}{value}\b", text, re.I), (
            f"the report does not print {key} {value}, which is what the corpus "
            f"holds")
    assert data["counts"]["modified"] >= 1, (
        "the two editions hold the same text, so the diff proves nothing about "
        "reporting differences")


# --------------------------------------------------------------------------- #
# F14 - no environment leakage
# --------------------------------------------------------------------------- #

# `fixtures/` is not scanned: it is the evidence catalogue, and evidence about a
# local path has to be able to say where the local path was. Its entries use a
# placeholder, and the defect they describe is checked by d22 against real
# artefacts.
ARTEFACT_GLOBS = ("docs/**/*.md", "corpora/**/*.json", "corpora/**/*.xml",
                  "corpora/**/*.jsonl", "derived/**/*.json", "derived/**/*.md",
                  "provenance/**/*.yaml", "rules/**/*.yaml",
                  "*.md", "*.yaml", "*.toml", "*.txt",
                  "harness/**/*.py", "tests/**/*.py")


def test_f14_no_local_paths_in_artifacts():
    problems: list[str] = []
    seen: set[Path] = set()
    for pattern in ARTEFACT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            match = LOCAL_PATH_RE.search(path.read_text(encoding="utf-8",
                                                        errors="replace"))
            if match:
                problems.append(f"{path.relative_to(ROOT)}: {match.group(0)!r}")
    assert not problems, ("an artefact describes the machine it was built on: "
                          + ", ".join(problems))


def test_f14_detector_still_catches_a_local_path(tmp_path):
    sample = tmp_path / "derived" / "index.json"
    sample.parent.mkdir(parents=True)
    sample.write_text(json.dumps({"file": FAKE_LOCAL_PATH}), encoding="utf-8")
    assert LOCAL_PATH_RE.search(sample.read_text(encoding="utf-8")), \
        "the local-path detector no longer detects a local path"


# --------------------------------------------------------------------------- #
# M1 - mapping verified against the source
# --------------------------------------------------------------------------- #

MAPPING = ROOT / "corpora" / "mli" / "mapping.json"


def _mapping() -> dict:
    _need(MAPPING.exists(), "the MLI mapping (corpora/mli/mapping.json)")
    data = corpus.load_json(MAPPING)
    assert data.get("rows"), "the mapping has no rows"
    return data


def _mapping_register() -> dict:
    path = ROOT / mli_writer.MAPPING_REGISTER
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _mapping_source() -> dict:
    """The register's entry for the source the mapping is built from, with its PDF."""
    _need(corpus.register(ROOT).exists(), "the source register")
    found = next((entry for entry in corpus.declared_sources(ROOT)
                  if entry["produces"] == "mapping"), None)
    _need(found is not None, "a source that declares `produces: mapping`")
    assert found["pdf"] is not None, (
        f"{found['id']}: the mapping is built from this source and its bytes are "
        f"not here, so the titles it carries cannot be checked against it")
    return found


@lru_cache(maxsize=2)
def _source_words(pdf: str, source: str):
    """The source's own text, as printed: {page: words in reading order}.

    Everything that was read is joined, because the question is not what the
    classifier kept but whether the words the artefact claims the Convention
    prints are on the page: a title is verified against the page, not against the
    code that produced it. Newlines and runs of spaces are collapsed, and nothing
    else is normalised - an apostrophe the source prints as a right single quote
    stays one, so the check cannot pass on a title somebody retyped with an
    ASCII apostrophe.
    """
    spans = ledger.SpanStream.read(Path(pdf), source)
    pages: dict = {}
    for span in sorted(spans, key=lambda s: (s.page, span_order(s))):
        pages.setdefault(span.page, []).append(span.text)
    return {page: re.sub(r"\s+", " ", " ".join(parts)).strip()
            for page, parts in pages.items()}


def span_order(span) -> tuple:
    """Where a span was printed: down the page, then across it."""
    return (round(span.y, 1), span.x)


def test_p02_measures_position_columns_from_consecutive_row_numbers():
    """A table's number run locates the title before frequent later columns."""
    spans = []
    for number, y in enumerate((100.0, 120.0, 140.0), 1):
        spans.append(ledger.Span("test", 0, y, 63.0, 10.0,
                                 f"{number}.", 70.0))
        spans.append(ledger.Span("test", 0, y, 117.5, 10.0,
                                 f"Agreement {number}", 205.0))
        spans.append(ledger.Span("test", 0, y, 270.0, 10.0,
                                 f"Jurisdiction {number}", 340.0))
        # A later column has several spans per row, so frequency alone picks it.
        for label in ("Original", "Instrument", "reference"):
            spans.append(ledger.Span("test", 0, y, 382.0, 10.0,
                                     label, 430.0))

    lettered = [span for span in spans if re.search(r"[A-Za-z]", span.text)]
    assert mli_writer._modal_x(lettered, 68.0, 450.0) == 382.0

    anchors, run = mli_writer._number_column(spans, 450.0)
    assert run == 3
    assert [int(mli_writer.NUMBER_RE.match(span.text).group(1))
            for span in anchors] == [1, 2, 3]
    assert mli_writer._title_column_after_numbers(
        spans, anchors, 450.0) == 117.5

    # Titles can be ragged while the counterparty column still occupies one
    # measured band. Its words spread out by more than the exact-edge tolerance.
    ragged = [ledger.Span("test", 0, y, x, 10.0, "Jurisdiction", x + 40)
              for y, x in ((100.0, 270.0), (120.0, 274.0), (140.0, 277.0))]
    ragged.extend(ledger.Span("test", 0, y, 10.0, 10.0, "1", 18.0)
                  for y in (100.0, 120.0, 140.0))
    ragged.extend(ledger.Span("test", 0, y, 20.0, 10.0, "1 January 2000", 80.0)
                  for y in (100.0, 120.0, 140.0))
    measured = mli_writer._measured_column_after(ragged, 250.0, 350.0)
    assert measured is not None and measured[0] == 270.0
    assert measured[-1] == 277.0


def _covered_table(pdf: Path):
    """The covered-agreements table `mli.position` would read from the PDF."""
    source = pdf.stem
    book = ledger.Classifier.classify(ledger.SpanStream.read(pdf, source),
                                      ledger.Ledger())
    admitted = sorted([span for span, _rule in book.kept],
                      key=lambda span: (span.page, span.y, span.x))
    section = next((section for section in
                    mli_writer.sections(mli_writer._body_lines(book), admitted)
                    if section["no"] == 2), None)
    assert section is not None, f"{pdf.name}: no Article 2 section to read"
    return mli_writer.covered_agreements(
        section["spans"], book, reader_source=pdf.stem)


# The two positions whose table the modal column cannot read: the number column
# they share with every other position is not the column that repeats most, so
# the columns are measured from the printed 1, 2, 3 run instead. Pinning the
# measured x band - not just the row count - is the point: a later change that
# goes back to the frequent column moves these numbers even when the rows do not.
@pytest.mark.parametrize("slug,last,columns", [
    ("azerbaijan", 54,
     {"no": 64.0, "title": 90.2, "other_jurisdiction": 302.3,
      "instrument": 380.8, "signature": 454.0, "entry_into_force": 525.0}),
    ("kuwait", 45,
     {"no": 97.9, "title": 124.2, "other_jurisdiction": 331.1,
      "instrument": 388.1, "signature": 446.6, "entry_into_force": 509.6}),
])
def test_p02_a_displaced_number_run_measures_the_two_target_positions(
        slug: str, last: int, columns: dict):
    """Azerbaijan and Kuwait: columns from the number run, numbering whole."""
    pdf = ROOT / "sources" / "mli-positions" / f"mli-position-{slug}.pdf"
    if not pdf.is_file():
        pytest.skip(f"{pdf.name} is not in sources/, so there is nothing to read")
    rows, qa = _covered_table(pdf)
    assert [row["no"] for row in rows] == list(range(1, last + 1))
    assert qa["numbering"]["last"] == last
    assert qa["numbering"]["runs_from_one_without_a_gap"] is True
    assert qa["columns"] == columns
    assert qa["columns_measured_from"].startswith(
        "the consecutive row-number run")
    assert qa["numbers_with_no_row"] == []


def test_p04_the_positions_cover_every_jurisdiction():
    """Every jurisdiction of the signatories table is a position, or is unread.

    This is the coverage claim made checkable, and it is the claim a family of 110
    documents exists for: the signatories table names the jurisdictions this
    corpus publishes, so every one of them has to be somewhere - as a position, or
    as a document the family declares it could not read, with the reader's own
    reason. A jurisdiction in neither place has gone missing between two artefacts
    that are supposed to be about the same countries, and a directory of JSON
    files cannot tell anyone that by itself.

    The jurisdiction of an *unread* document is known from its file name and not
    from its text, which is what being unread means: the publisher's file name is
    the name this corpus has for the bytes it could not read.
    """
    table_path = corpus.signatories(ROOT)
    report_path = corpus.corpus_root(ROOT) / "mli" / "positions" / corpus.POSITION_REPORT
    if not table_path.is_file() or not report_path.is_file():
        pytest.skip("the signatories table or the family's own report is not here "
                    "yet, so there is no coverage to check")
    published = {path.stem for path in corpus.position_files(ROOT)}
    report = corpus.load_json(report_path)
    unread = {Path(str(item.get("file"))).stem[len("mli-position-"):]
              for item in report.get("unread") or []}
    problems: list[str] = []
    for row in corpus.load_json(table_path).get("rows") or []:
        name = str(row.get("jurisdiction") or "")
        slug = mli_writer.canonical(name, mli_writer._slug(name))[1]
        if slug not in published and slug not in unread:
            problems.append(f"row {row.get('no')}: {name!r} ({slug}) is neither a "
                            f"published position nor a document the family "
                            f"declares unread")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------- #
# P5 - title cells match printed numbers
# --------------------------------------------------------------------------- #

# The initial audit found 31 positions with legacy title-cell mismatches. Nine
# were first promoted, three more (Chile, Colombia and Isle of Man) passed
# row-content validation, and China uses its targeted classifier rule. Gabon,
# Burkina Faso, Georgia, Latvia and Pakistan passed source-row validation, and
# Norway, Senegal and Lithuania passed it after the reader repairs (a
# counterparty/title span cut at the column edge, cell content above a number
# kept inside the attach window, heading-band furniture excluded as a band,
# packed dates read by their own dates, a merged date run split at the measured
# date-column boundary). The two exceptions that were left on the legacy reader
# after that work were both promoted on 2026-10-07, so the list is now empty:
#   egypt  handed back 2026-10-07 - a heading printed above its own number was
#          read as the row above's tail; the row boundary inside the paragraph is
#          now found from the heading's own mirror about the number
#   peru   handed back 2026-10-07 - the counterparty column was measured on the
#          start its names share, so row 7's `Switzerland`, printed 7pt left of
#          it, landed in the title with no counterparty at all
# New Zealand and Slovenia left this list with the merged-date-run split. Their
# forced block readings had only ever been rejected because a printed `N/A` sat
# beside a date in the force column, and the split shows that `N/A` to be the
# publisher's own value in its own cell: the reading matches the source band by
# band. The legacy readings they were kept on are the defective ones - they drop
# every title (New Zealand) and smear the `Original` label into counterparties
# (both) - so both are now promoted.
# Algeria, Brazil, Israel and Sweden left the list in the 2026-10-06 reader
# repair. A block that opened above its own number could carry the neighbouring
# row's last title line (Algeria's Arabic decree sentences, Israel's titles,
# Sweden's cross-page tail); the block reader now hands such a lead-in back to
# the row it belongs to, measured by the layout's own habit of printing each
# number at the head of its row. A counterparty column printed almost touching
# the title's right edge (Brazil, at 245.0 against 244.66) had been measured on
# the instrument label instead, and an instrument label printed on its own line
# (Israel's `Original`) had not been measured at all; both columns are measured
# now, so the labels land in the instrument cell and the names in the
# counterparty cell. Their block readings now reproduce the published legacy
# reading or improve on it row by row. Cote-d'ivoire left the list next: the
# table prints each date with a space (`03-07- 1979`), the extractor returning
# the day and the year as two spans, so the signature column was invisible and
# every signature was read as an entry into force. The block reader now rejoins
# a wrapped date before it measures the columns, and reads `1er` as the ordinal
# day the publisher prints, so both date columns are measured and rows 1-11
# carry the two dates the page prints. Egypt's block reading is faithful now too:
# the reader ends a block at a change of script, so the Arabic heading of one
# agreement and the English heading of the next no longer interleave, and a
# heading printed above its own number is measured from the heading's mirror
# about the number rather than read as the row above's tail. No layout is left on
# the legacy reader for a title-cell mismatch, so this list is empty. It stays a
# declaration rather than a shelf in both directions: a mismatch the reader
# produces without a declaration fails, and a declared slug whose cells now match
# fails too. A future exception carries a row-level DEFECT_INVENTORY record and a
# LEGACY_DEFECT_INVENTORY record of a row the legacy read gets wrong, re-read
# live, so it compares the two readers instead of resting on the block reading's
# own defect alone.
P5_CELL_MODEL_EXCEPTIONS = frozenset()
P5_BLOCK_AUDIT_EXCEPTIONS = P5_CELL_MODEL_EXCEPTIONS

# Source-verified evidence pins for promoted and repaired block-reader rows.
# Pinning counterparty, title phrase and dates catches complete numbering whose
# row attribution is nevertheless shifted. The concatenated date pins
# (burkina-faso 1, georgia 19/23/34, pakistan 20/22) hold the reader's join of
# the source's own multi-instrument line cells, cell for cell.
P5_BLOCK_ROW_PINS = {
    "czechia": {84: ("United States", "United States of America")},
    "nigeria": {10: ("Pakistan", "Islamic Republic of Pakistan")},
    "south-africa": {
        1: ("Algeria", "Democratic People’s Republic of Algeria"),
        3: ("Austria", "Republic of Austria"),
        24: ("Greece", "Hellenic Republic"),
    },
    "tunisia": {
        4: ("Cameroun", "République du Cameroun"),
        9: ("Égypte", "République Arabe d'Égypte"),
        15: ("Koweït", "Koweït"),
    },
    "ukraine": {
        8: ("Brazil", "Federative Republic of Brazil"),
        13: ("Cuba", "Government of Cuba"),
        33: ("Jordan", "Hashemite Kingdom of Jordan"),
        45: ("Malaysia", "Government of Malaysia"),
        51: ("Morocco", "Kingdom of Morocco"),
        61: ("Singapore", "Republic of Singapore"),
    },
    "mexico": {
        18: ("France", "République française"),
        20: ("Greece", "Hellenic Republic"),
        27: ("Ireland", "Ireland"),
        31: ("Japan", "Japan"),
        36: ("Luxembourg", "Grand Duchy of Luxembourg"),
        45: ("Portugal", "Portuguese Republic"),
        51: ("Slovakia", "Slovak Republic"),
        53: ("Spain", "Reino de España"),
        58: ("United Arab Emirates", "United Arab Emirates"),
        61: ("Uruguay", "República Oriental del Uruguay"),
    },
    "spain": {
        2: ("Germany", "República Federal de Alemania"),
        11: ("Barbados", "Barbados"),
        19: ("Czech Republic (ex Czechoslovakia)", "República Socialista de Checoslovaquia"),
        35: ("Philippines", "República de Filipinas"),
        40: ("Hong Kong (China)", "Región Administrativa Especial de Hong Kong"),
        44: ("Ireland", "Irlanda"),
        47: ("Italy", "Italia"),
        53: ("Lithuania", "Republic of Lithuania"),
        81: ("Turkey", "Republic of Turkey"),
    },
    "panama": {
        1: ("Barbados", "and Barbados"),
        4: ("Ireland", "and Ireland"),
        10: ("Netherlands", "The Netherlands"),
    },
    "viet-nam": {1: ("Australia", "Government of Australia")},
    "china-people-s-republic-of": {
        20: ("Australia", "Government of Australia"),
        43: ("Slovenia", "Government of the Republic of Slovenia"),
        74: ("Oman", "Government of the Sultanate of Oman"),
        89: ("Saudi Arabia", "Government of the Kingdom of Saudi Arabia"),
    },
    "chile": {
        5: ("Canada", "Government of Canada"),
        12: ("France", "Gouvernement de la République Française"),
        23: ("Russia", "Government of the Russian Federation"),
        31: ("Italy", "Government of the Italian Republic"),
    },
    "colombia": {
        5: ("France", "Government of the French Republic"),
    },
    "isle-of-man": {
        3: ("The Republic of Estonia", "Isle of Man and The Republic of Estonia"),
        4: ("The Government of the Grand Duchy of Luxembourg",
            "Grand Duchy of Luxembourg"),
        5: ("The Government of Malta", "Isle of Man and Malta"),
        6: ("The Government of the State of Qatar", "Government of the State of Qatar"),
        7: ("The Government of the Republic of Seychelles", "Republic of Seychelles"),
        8: ("The Government of the Republic of Singapore", "Republic of Singapore"),
    },
    "gabon": {
        1: ("Belgique", "Convention fiscale entre le Royaume de la Belgique et la République Gabonaise"),
        2: ("Canada", "Convention fiscale entre le gouvernement de la République Gabonaise et le gouvernement du Canada"),
        3: ("France", "Convention entre le gouvernement de la République Gabonaise et le gouvernement de la République Française"),
        4: ("Maroc", "Convention entre le gouvernement de la République Gabonaise et le gouvernement du Royaume du Maroc"),
    },
    "burkina-faso": {
        1: ("France", "République de Haute-Volta"),
        2: ("Maroc", "Royaume du Maroc"),
        3: ("Tunisie", "République Tunisienne"),
    },
    "georgia": {
        1: ("Czech Republic", "Executive Authority of Georgia"),
        2: ("French Republic", "REPUBLIQUE FRANÇAISE"),
        9: ("Kingdom of Belgium", "Kingdom of Belgium and Georgia"),
        12: ("Kingdom of the Netherlands", "Kingdom of the Netherlands"),
        19: ("Republic of Estonia", "Republic of Estonia and Georgia"),
        23: ("Republic of Latvia", "Republic of Latvia and Georgia"),
        34: ("United Kingdom of Great Britain and Northern Ireland",
             "United Kingdom of Great Britain and Northern Ireland"),
    },
    "latvia": {
        1: ("AUSTRIA", "REPUBLIC OF AUSTRIA"),
        10: ("GEORGIA", "REPUBLIC OF LATVIA AND GEORGIA"),
        23: ("CHINA",
             "REPUBLIC OF LATVIA AND THE GOVERNMENT OF THE PEOPLE"),
        30: ("MONTENEGR O", "COUNCIL OF MINISTERS OF SERBIA AND MONTENEGRO"),
        36: ("SERBIA", "COUNCIL OF MINISTERS OF SERBIA AND MONTENEGRO"),
        46: ("THE HONG KONG SPECIAL ADMINISTRAT IVE REGION OF THE PEOPLE’S REPUBLIC OF CHINA",
             "HONG KONG SPECIAL ADMINISTRATIVE REGION"),
        47: ("CYPRUS", "REPUBLIC OF CYPRUS"),
    },
    "pakistan": {
        1: ("USA", "United States of America"),
        3: ("Poland", "polish peoples Republic"),
        6: ("Canada", "Canada and the Islamic Republic of Pakistan"),
        7: ("Belgium", "Kingdom of Belgium and the Islamic Republic of Pakistan"),
        20: ("Denmark", "kingdom of Denmark"),
        22: ("China", "People's Republic of China"),
        44: ("Nepal", "His Majesty's Government of Nepal"),
        63: ("Czech Republic", "The Czech Republic"),
    },
    # Norway's pins cover the repairs: row 18 keeps the source's bilingual
    # Norwegian/Spanish title (with its footnote marker excluded), row 24's
    # title breaks across the page and its counterparty shares the number's
    # own line, and row 26 keeps the publisher's own printed line order.
    "norway": {
        1: ("Argentina", "Republic of Argentina"),
        18: ("Mexico", "Mexicos Forente Stater"),
        24: ("Serbia", "Republic of Serbia"),
        26: ("South Africa", "Africa for the Avoidance of Double"),
    },
    # Senegal's row 2 holds the three Avenants the legacy read split across
    # its neighbours; row 3 is the row the (c) Avenant used to leak into.
    "senegal": {
        2: ("France", "République Française"),
        3: ("Tunisie", "République Tunisienne"),
        15: ("Royaume Uni de Grande Bretagne et de l’Irlande du Nord",
             "Royaume Uni de Grande Bretagne et de l’Irlande du Nord"),
    },
    # Indonesia row 3's first instrument is printed above number 3; row 4 must
    # begin with its own Original entry, never Canada's pre-anchor dates.
    "indonesia": {
        2: ("Brunei Darussalam", "Government of Brunei Darussalam"),
        3: ("Canada", "Convention between the Republic of Indonesia and Canada"),
        4: ("China (People’s Republic of)", "People’s Republic of China"),
        11: ("Malaysia", "Government of Malaysia"),
        12: ("Netherlands", "Government of the Kingdom of Netherlands"),
        22: ("United States of America", "Government of the United States"),
    },
    # Lithuania's rows 30 and 53 carry an amending instrument whose dates
    # print on the far side of a page break; the legacy read dropped them.
    "lithuania": {
        3: ("Azerbaijan", "Republic of Azerbaijan"),
        30: ("Luxembourg", "Grand Duchy of Luxembourg"),
        42: ("Serbia", "Republic of Serbia"),
        51: ("Ukraine", "Government of Ukraine"),
        53: ("United Kingdom", "United Kingdom of Great Britain And Northern Ireland"),
    },
    # New Zealand and Slovenia come off the legacy reader, which drops every
    # title on one and leaks `Original` into the counterparties of the other.
    # These pins are the printed counterparties with the title phrase that
    # names each one, read from the rows the source-band audit measures; each
    # phrase appears in the printed title in the row's own title band.
    "new-zealand": {
        1: ("Australia", "Convention between Australia and New Zealand"),
        3: ("Belgium", "Government of Belgium"),
        12: ("India", "Government of the Republic of India"),
        24: ("Singapore", "Government Of The Republic Of Singapore"),
        32: ("Viet Nam", "Socialist Republic of Viet Nam"),
        36: ("United Arab Emirates", "Government of the United Arab Emirates"),
    },
    "slovenia": {
        1: ("Republic of Albania",
            "Council of Ministers of the Republic of Albania"),
        7: ("Bosnia and Herzegovina",
            "Republic of Slovenia and Bosnia and Herzegovina"),
        15: ("Arab Republic of Egypt", "Arab Republic of Egypt"),
        25: ("Islamic Republic of Iran", "Islamic Republic of Iran"),
        42: ("Republic of Poland",
            "Republic of Slovenia and the Republic of Poland"),
        58: ("Republic of Uzbekistan",
            "Government of the Republic of Uzbekistan"),
    },
    # Algeria, Brazil, Israel and Sweden come off the legacy reader in the
    # 2026-10-06 repair. Algeria's and Sweden's rows were bleeding one row's
    # last title line into the next row's head; Brazil's counterparty column had
    # been measured on the instrument label; Israel's label was printed on its
    # own line. These pins are the printed counterparties with the title phrase
    # that names each one, read from the rows the source-band audit measures.
    "algeria": {
        1: ("Afrique du sud",
            "Convention entre le Gouvernement de la République Algérienne Démocratique"),
        6: ("Belgique", "Royaume de Belgique"),
        7: ("Bosnie- Herzégovine",
            "Conseil des Ministres de la Bosnie-Herzégovine"),
        15: ("Espagne", "Royaume d’Espagne en vue"),
        25: ("Roumanie", "Gouvernement de la Roumanie"),
        34: ("UMA", "les doubles impositions et"),
    },
    "brazil": {
        1: ("Austria", "República da Áustria"),
        3: ("Canada", "Government of Canada"),
        4: ("Czechoslovakia (Czech Republic)",
            "Czechoslovak Socialist Republic"),
        7: ("Finland", "Republic of Finland"),
        12: ("Japan", "Convention between United States of Brazil and Japan"),
        25: ("Ukraine", "Government of Ukraine"),
    },
    "israel": {
        1: ("Armenia", "Government of the Republic of Armenia"),
        40: ("Romania", "Government of Romania"),
        49: ("Taiwan", "Economic and Cultural Office in Tel-Aviv"),
        54: ("United States", "United States of America"),
        56: ("Vietnam", "Socialist Republic of Vietnam"),
    },
    "sweden": {
        1: ("Albania", "Government of the Republic of Albania"),
        10: ("Botswana", "Government of the Republic of Botswana"),
        11: ("Bulgaria", "People's Republic of Bulgaria"),
        33: ("Latvia", "Republic of Latvia"),
        64: ("Zimbabwe", "Republic of Zimbabwe"),
    },
    "cote-d-ivoire": {
        1: ("République Fédérale d’Allemagne (Allemagne)",
            "Convention fiscale entre la République de Côte d’Ivoire"),
        2: ("Royaume de Belgique", "et le Royaume de Belgique tendant"),
        4: ("France", "et le Gouvernement de la République française"),
        7: ("Royaume de Norvège", "et le Royaume de Norvège tendant"),
        10: ("Portugal", "et la République portugaise en vue"),
        11: ("Turquie", "et le Gouvernement de la République de Turquie"),
    },
    # Egypt and Peru come off the legacy reader last, on 2026-10-07. Egypt's pins
    # are the rows the mirror model governs: row 13 was the counted defect (the
    # heading printed above its own number), rows 11 and 36 are headings whose
    # tail runs over the page break, and rows 28/29/30 and 49/50 sit in blocks
    # that hold two numbers each, where the largest ragged drop the block split
    # looked for is the row's own number line. Peru's row 7 is the counterparty
    # printed left of the start the column's other names share.
    "egypt": {
        11: ("Czech Republic",
             "PREVENTION OF FISCAL EVASION WITH RESPECT TO TAXES ON INCOME AND CAPITAL"),
        13: ("Ethiopia",
             "FEDERAL DEMOCRATIC REPUBLIC OF ETHIOPIA FOR THE AVOIDANCE"),
        28: ("Kuwait", "الكويت لتجنب دولة وحكومة"),
        29: ("Lebanon", "والجمهورية اللبنانية لتفادى االزدواج"),
        30: ("Libya", "والجماهيرية العربية الليبية الشعبية"),
        36: ("Norway", "WITH RESPECT TO TAXES ON INCOME"),
        49: ("Syria", "والجمهورية العربية السورية بشأن تجنب"),
        50: ("Tunisia", "وحكومة  الجمهورية التونسية بشأن"),
    },
    "peru": {
        1: ("Brazil", "República Federativa de Brasil"),
        3: ("Chile",
            "Convenio entre la República del Perú y la República de Chile"),
        5: ("Mexico", "Estados Unidos Mexicanos"),
        6: ("Portugal", "Portuguese Republic"),
        7: ("Switzerland",
            "Convention between the Swiss Confederation and the Republic of Peru"),
    },
}
P5_BLOCK_DATE_PINS = {
    "algeria": {
        5: ("11-06-2000", "24-09-2003"),
        6: ("15-12-1991", "10-01-2003"),
        15: ("07-10-2002", "01-07-2006"),
    },
    "brazil": {
        12: ("24-01-1967 23-03-1976", "31-12-1967 29-12-1977"),
    },
    "israel": {
        3: ("28-11-2016", "N/A"),
    },
    "sweden": {
        10: ("19-10-1992 20-02-2013", "23-12-1992 14-05-2015"),
    },
    "indonesia": {
        2: ("27-02-2000", "7-11-2001"),
        3: ("16-01-1979 01-04-1998", "23-12-1980 31-12-1998"),
        4: ("07-11-2001 26-03-2015", "25-08-2003 16-03-2016"),
        11: ("12-09-1991 12-01-2006", "11-08-1992 01-7-2010"),
        12: ("29-01-2002 30-07-2015", "31-12-2003 NA"),
        22: ("11-07-1988 24-07-1996", "01-02-1991 23-12-1996"),
    },
    "chile": {
        5: ("21-01-1998", "28-10-1999"),
        12: ("07-06-2004", "10-07-2006"),
        23: ("19-11-2004", "23-03-2012"),
        31: ("23-10-2015", "N/A"),
    },
    "colombia": {5: ("25-06-2015", "N/A")},
    "isle-of-man": {
        3: ("08-05-2009", "21-12-2009"),
        4: ("08-04-2013", "05-08-2014"),
        5: ("23-10-2009", "26-02-2010"),
        6: ("06-05-2012", "15-11-2012"),
        7: ("28-03-2013", "16-12-2013"),
        8: ("21-09-2012", "02-05-2013"),
    },
    "gabon": {
        1: ("14-01-1993", "13-05-2005"),
        2: ("14-11-2002", "22-12-2008"),
        3: ("20-09-1995", "01-03-2008"),
        4: ("03-06-1999", "01-02-2008"),
    },
    "burkina-faso": {
        1: ("11-08-1965 03-06-1971", "01-01-1963 / 15-02- 1967 01-01-1971"),
        2: ("18-05-2012", "n/a"),
        3: ("15-04-2003", "01-01-2014"),
    },
    "georgia": {
        1: ("23-05-2006", "04-05-2007"),
        2: ("07-03-2007", "01-06-2010"),
        9: ("14-12-2000", "04-05-2004"),
        12: ("21-03-2002", "21-02-2003"),
        19: ("18-12-2006 17-07-2010", "27-12-2007 11-03-2011"),
        23: ("13-10-2004 29-05-2012", "04-04-2005 27-11-2012"),
        34: ("13-07-2004 03-02-2010", "11-10-2005 17-12-2010"),
    },
    "latvia": {
        1: ("14-12-2005", "16-05-2007"),
        10: ("13-10-2004 29-05-2012", "04-04-2005 27-11-2012"),
        23: ("07-06-1996 24-08-2011", "27-01-1997 19-05-2012"),
        36: ("22-11-2005", "19-05-2006"),
        46: ("13-04-2016", "N/A"),
        47: ("24-05-2016", "27-10-2016"),
    },
    "pakistan": {
        1: ("01-07-1958", "01-01-1959"),
        3: ("25-10-1974", "24-11-1975"),
        6: ("24-02-1976", "15-12-1977"),
        7: ("17-03-1980", "02-09-1983"),
        20: ("22-10-1987 02-05-2002", "22-10-1987 28-12-2002"),
        22: ("15-11-1989 19-06-2000 17-04-2007 08-12-2016",
             "27-12-1989 11-10-2000 17-04-2007 N/A"),
        44: ("25-01-2001", "13-07-2010"),
        63: ("02-05-2014", "30-10-2015"),
    },
    "china-people-s-republic-of": {
        20: ("17-11-1988", "28-12-1990"),
        43: ("13-02-1995", "27-12-1995"),
        74: ("25-03-2002", "20-07-2002"),
        89: ("23-01-2006", "01-09-2006"),
    },
    "norway": {
        1: ("08-10-1997", "30-11-2001"),
        19: ("12-01-1990 23-04-2013", "31-12-1990 30-11-2013"),
        24: ("17-06-2015", "18-12-2015"),
        26: ("12-02-1996 16-07-2012", "12-09-1996 20-11-2015"),
    },
    "senegal": {
        1: ("09-01-1971", "06-03-1976"),
        2: ("29-03-1974 16-07-1984 10-01-1991",
            "24-04-1976 05-02-1986 27-02-1993"),
        3: ("17-05-1984", "25-05-1985"),
    },
    "lithuania": {
        3: ("02-04-2004", "13-11-2004"),
        25: ("07-03-1997", "11-12-1997"),
        30: ("22-11-2004 20-06-2014", "14-04-2006 11-12-2015"),
        42: ("28-08-2007", "12-06-2009"),
        51: ("23-09-1996", "25-12-1997"),
    },
    # New Zealand's rows 3 and 12 keep a printed `N/A` in the force cell beside
    # the date of another instrument: the merged date run is what made the old
    # reading wrong, and these pins hold the split the repair produces.
    "new-zealand": {
        1: ("26-6-2009", "19-03-2010"),
        3: ("15-09-1981 07-12-2009", "08-12-1983 N/A"),
        24: ("21-08-2009", "12-08-2010"),
        36: ("22-09-2003", "29-07-2004"),
    },
    "slovenia": {
        7: ("16-05-2006", "20-11-2006"),
        15: ("15-12-2009", "N/A"),
        39: ("05-04-2016", "N/A"),
    },
    # Cote-d'ivoire's dates are the wrapped, spaced ones: row 4's second
    # instrument wraps `19-10-` onto its own line and its year to the next page,
    # and the two `1er` ordinals are kept as the table prints them.
    "cote-d-ivoire": {
        1: ("03-07-1979", "08-07-1982"),
        4: ("06-04-1966 25-02-1985 19-10- 1993",
            "01-10-1968 1er-03-1985 1er-11-1993"),
        10: ("17-03-2015", "1er-01-2018"),
        11: ("29-02-2016", "N/A"),
    },
}


def _position_table_audit(pdf: Path) -> dict | None:
    """Measure the row model the live dispatch actually selected.

    Legacy reads return doubled title cells and printed numbers that opened no
    row. Block reads return the anchor list they promised to account for and
    the emitted row numbers. Number-first layouts have no title-cell model and
    are outside P5. The functions are intercepted only to observe the reader's
    own measured anchors/cells; the PDF and published artefact remain untouched.
    """
    classifier_source = (pdf.stem if pdf.stem == "mli-position-china"
                         else "mli-positions-batch")
    book = ledger.Classifier.classify(
        ledger.SpanStream.read(pdf, classifier_source), ledger.Ledger())
    admitted = sorted([span for span, _rule in book.kept],
                      key=lambda span: (span.page, span.y, span.x))
    section = next((section for section in
                    mli_writer.sections(mli_writer._body_lines(book), admitted)
                    if section["no"] == 2), None)
    if section is None:
        return None
    captured: dict = {}
    original_legacy = mli_writer._read_legacy_covered
    original_block = mli_writer._read_block_covered
    original_china = mli_writer._read_china_covered

    def capture_legacy(*args, **kwargs):
        captured["legacy"] = args
        return original_legacy(*args, **kwargs)

    def capture_block(*args, **kwargs):
        captured["block"] = args
        return original_block(*args, **kwargs)

    def capture_china(*args, **kwargs):
        captured["block"] = args
        return original_china(*args, **kwargs)

    mli_writer._read_legacy_covered = capture_legacy
    mli_writer._read_block_covered = capture_block
    mli_writer._read_china_covered = capture_china
    try:
        rows, qa = mli_writer.covered_agreements(
            section["spans"], book, reader_source=pdf.stem)
    finally:
        mli_writer._read_legacy_covered = original_legacy
        mli_writer._read_block_covered = original_block
        mli_writer._read_china_covered = original_china

    selected = str(qa.get("rows_delimited_by", ""))
    if selected.startswith("title blocks"):
        if "block" not in captured:
            raise AssertionError("block qa returned without invoking the block reader")
        anchors = captured["block"][2]
        printed = sorted(int(mli_writer.NUMBER_RE.match(span.text.strip()).group(1))
                         for span in anchors)
        emitted = [row["no"] for row in rows]
        return {"reader": "blocks", "doubled": 0,
                "lost": sorted(set(printed) - set(emitted)),
                "unexpected": sorted(set(emitted) - set(printed)),
                "duplicates": sorted({number for number in emitted
                                       if emitted.count(number) > 1}),
                "rows": {row["no"]: row for row in rows}}
    if selected.startswith("the row numbers") or selected.startswith(
            "the first line of each title cell"):
        if "legacy" not in captured:
            raise AssertionError("legacy qa returned without invoking the legacy reader")
    else:
        return {"reader": "number-first", "doubled": 0, "lost": [],
                "unexpected": [], "duplicates": []}

    args = captured["legacy"]
    table, anchors, title_x, counterpart_column = \
        args[7], args[8], args[6], args[10]
    title_right = mli_writer._right_edge(table, [title_x])
    starts, _justified = mli_writer._title_cells(
        table, title_x, counterpart_column[0], title_right)
    anchor_ids = {id(span) for span in anchors}
    doubled = 0
    for index, start in enumerate(starts):
        end = (starts[index + 1] if index + 1 < len(starts)
               else (max(span.page for span in table) + 1, 0.0))
        cell = [span for span in table
                if (start[0], start[1] - 0.5) <= (span.page, span.y) < end]
        if len([span for span in cell if id(span) in anchor_ids]) > 1:
            doubled += 1
    opened = {row["no"] for row in rows}
    numbers = {int(mli_writer.NUMBER_RE.match(span.text.strip()).group(1))
               for span in anchors}
    return {"reader": "legacy", "doubled": doubled,
            "lost": sorted(numbers - opened), "unexpected": [],
            "duplicates": []}


def test_p05_source_band_rows_are_checked_for_promotions_and_exceptions():
    """Promotions satisfy source-band pins; forced defects remain observable.

    The verifier compares reviewed row pins against the measured PDF columns and
    dates. Every promoted layout must pass those pins and account for each printed
    number exactly once. Every declared exception - none today - is forced through
    the same block reader, remains rejected by its known content defect, and is
    re-read with the legacy reader so the record also names the rows the legacy
    read itself gets wrong; matching number anchors alone can never promote a
    layout.
    """
    promoted: list[str] = []
    for source in sorted(mli_writer.BLOCK_READER_SOURCES):
        pdf_slug = source.removeprefix("mli-position-")
        slug = ARTIFACT_SLUGS.get(pdf_slug, pdf_slug)
        result = audit_block_rows(
            ROOT, slug, row_pins=P5_BLOCK_ROW_PINS,
            date_pins=P5_BLOCK_DATE_PINS.get(slug))
        assert result["rows"] == result["anchors"], (
            f"{slug}: {result['rows']} block rows for {result['anchors']} printed anchors")
        assert not result["issues"], f"{slug}: {result['issues']}"
        assert not result["row_issues"], (
            f"{slug}: source-band findings: {result['row_issues']}")
        promoted.append(slug)

    assert "indonesia" in promoted, "Indonesia must be a promoted block-reader layout"
    assert set(promoted).isdisjoint(P5_BLOCK_AUDIT_EXCEPTIONS), (
        "a slug is both promoted and declared an exception")
    # Every position the legacy reader got wrong is promoted now, so the exception
    # list is empty and this gate holds nothing back. The two layouts that were
    # the last two exceptions are named here so the declaration and the comment
    # above it cannot drift apart: if either fell back to the legacy reader it
    # would have to be declared again, with its own row-level records.
    assert not P5_BLOCK_AUDIT_EXCEPTIONS, (
        "no layout is left on the legacy reader for a title-cell mismatch")
    assert {"egypt", "peru"} <= set(promoted), (
        "Egypt and Peru are promoted block-reader layouts")
    assert "new-zealand" in promoted and "slovenia" in promoted, (
        "New Zealand and Slovenia are promoted block-reader layouts")
    assert {"algeria", "brazil", "israel", "sweden",
            "cote-d-ivoire"} <= set(promoted), (
        "Algeria, Brazil, Israel, Sweden and Cote d'Ivoire are promoted "
        "block-reader layouts")
    for slug in sorted(P5_BLOCK_AUDIT_EXCEPTIONS):
        # Each exception carries a reviewed, source-verified defect on a named
        # row, not only a predicate that fires somewhere: the row-level record
        # is what makes the exception a record instead of a shelf, and the
        # audit re-checks the pinned row against the forced block reading. It
        # also re-reads the same PDF with the legacy reader and checks the
        # rows the legacy read gets wrong, so keeping the layout on the legacy
        # reader is justified by the block reading being better where it is.
        assert DEFECT_INVENTORY.get(slug), (
            f"{slug}: an exception needs a pinned row-level defect in "
            "DEFECT_INVENTORY, reviewed row by row against the source")
        assert LEGACY_DEFECT_INVENTORY.get(slug), (
            f"{slug}: an exception needs a pinned row-level defect in "
            "LEGACY_DEFECT_INVENTORY, naming a row the legacy reader gets wrong")
        result = audit_block_rows(
            ROOT, slug, force_block=True, row_pins={slug: {}}, date_pins={},
            legacy_pins=LEGACY_DEFECT_INVENTORY.get(slug))
        assert result["rows"] == result["anchors"], (
            f"{slug}: forced block rows/anchors differ")
        assert not result["issues"], f"{slug}: {result['issues']}"
        assert not result["row_issues"], (
            f"{slug}: source-band audit failures: {result['row_issues']}")
        assert result["findings"], (
            f"{slug}: the documented P5 defect is no longer visible; "
            "re-review the layout and remove or update its exception")

    assert set(promoted) <= set(P5_BLOCK_ROW_PINS), (
        "every promoted source needs at least one reviewed row attribution pin")
    for source in mli_writer.BLOCK_READER_SOURCES:
        slug = ARTIFACT_SLUGS.get(source.removeprefix("mli-position-"),
                                  source.removeprefix("mli-position-"))
        assert P5_BLOCK_ROW_PINS.get(slug), f"{slug}: no reviewed row pin for promotion"


def test_p05_a_legacy_layout_must_have_a_row_the_block_reader_gets_right():
    """Every layout kept on the legacy reader wins a row against it.

    Keeping a layout on the legacy reader claims two things: the block reading
    is not yet faithful (`DEFECT_INVENTORY`), and where the two differ the
    legacy reading is the worse one (`LEGACY_DEFECT_INVENTORY`). A layout whose
    readings agree row for row makes the second claim empty, and a layout whose
    only differences are rows the block reader also gets wrong makes it false.
    This gate re-reads every exception with both readers and fails unless at
    least one row differs on a row the block reader gets right - one that
    carries no source-band finding of its own - and unless the rows the
    `LEGACY_DEFECT_INVENTORY` record names are among them. An exception can
    then only be kept on evidence of a comparison that actually happens.
    """
    for slug in sorted(P5_BLOCK_AUDIT_EXCEPTIONS):
        block = {row["no"]: row for row in block_reading(ROOT, slug)}
        legacy = {row["no"]: row for row in legacy_reading(ROOT, slug)}
        audit = audit_block_rows(
            ROOT, slug, force_block=True, row_pins={slug: {}}, date_pins={},
            legacy_pins=LEGACY_DEFECT_INVENTORY.get(slug))
        flawed = {issue.get("row") for issue in audit["row_issues"]}
        wins: list[int] = []
        for number in sorted(set(block) & set(legacy)):
            if number in flawed:
                continue
            if any(block[number].get(field) != legacy[number].get(field)
                   for field in ROW_FIELDS):
                wins.append(number)
        assert wins, (
            f"{slug}: no row differs between the block reading and the legacy "
            "reading on a row the block reader gets right, so nothing justifies "
            "keeping the layout on the legacy reader")
        declared = {number for number, _field, *_rest in
                    LEGACY_DEFECT_INVENTORY.get(slug, ())}
        assert declared <= set(wins), (
            f"{slug}: the rows the legacy-defect record names ({sorted(declared)})"
            f" are not rows the block reader wins ({sorted(wins)})")


# Egypt's covered-agreements table prints every agreement twice at one leading,
# an Arabic heading and an English one, and prints the row's number inside the
# paragraph rather than at the head of a line. The legacy title-cell reader
# lets one agreement's Arabic heading and its neighbour's English heading fall
# into the same cell, so a row carries both scripts at once; the block reader
# ends a row at a change of script instead.
P5_BILINGUAL_LAYOUTS = ("egypt",)
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def _title_scripts(row: dict) -> set:
    """The scripts a row's title is written in: `arabic`, `latin`, both or none."""
    title = str(row.get("title") or "")
    found = set()
    if mli_writer.ARABIC_RE.search(title):
        found.add("arabic")
    if LATIN_LETTER_RE.search(title):
        found.add("latin")
    return found


def test_p05_every_position_view_names_the_rows_of_its_artefact():
    """A view cannot name a counterparty, a date or a band its artefact does not.

    Each position has a derived markdown view
    (`derived/markdown/mli/positions/<slug>.md`) rendered from the artefact it
    summarises, and the two can fall apart exactly the way a reader repair makes
    the corpus stale: the artefact is regenerated and the view that quoted its
    counterparties and dates is left behind. So this control reads each view
    back and compares it with its artefact row by row and field by field, naming
    the row and the field that disagree - and the attach line the view carries,
    whose tolerance and two band edges are read back and held against
    `row_attach_pt` and `row_attach_band_pt`, because the interval the reading
    left is as much the artefact's own answer as a counterparty is
    (`mli_row_audit.attach_divergences`). A position with no view at all fails
    too, because a missing view is the same defect with nothing to compare.
    """
    stored = corpus.corpus_root(ROOT) / "mli" / "positions"
    artifacts = [path for path in sorted(stored.glob("*.json"))
                 if path.stem != "batch-report"]
    _need(artifacts, "the MLI position artefacts (corpora/mli/positions/*.json)")
    views_dir = ROOT / "derived" / "markdown" / "mli" / "positions"
    problems: list[str] = []
    for path in artifacts:
        record = json.loads(path.read_text(encoding="utf-8"))
        view = views_dir / f"{path.stem}.md"
        if not view.is_file():
            problems.append(f"{path.name}: no derived view at "
                            f"{view.relative_to(ROOT).as_posix()}")
            continue
        problems.extend(f"{path.name} {line}" for line in
                        position_view_divergences(
                            record, view.read_text(encoding="utf-8")))
    assert not problems, "\n".join(problems[:40])


def test_p05_the_position_view_control_catches_a_stale_view():
    """The control bites: a view the artefact has moved on from fails.

    `test_p05_every_position_view_names_the_rows_of_its_artefact` is only a
    control if a wrong view fails it, so this is the negative control beside it.
    The sample positions are built in memory and rendered by the same renderer
    the corpus uses - the real renderer on invented content, never invented
    markdown - and then corrupted in each way a stale view goes stale: a
    counterparty the artefact no longer holds, a date it does, and the attach
    line by each of its parts - the tolerance, the band the page left it, and
    the reader the artefact says decided the rows.
    """
    record = {"slug": "probe", "country": "Probe", "covered_agreements": [
        {"no": 1, "other_jurisdiction": "Belgium", "instrument": "Original",
         "signature": "01-02-2003", "entry_into_force": "04-05-2006",
         "page": 1},
        {"no": 2, "other_jurisdiction": "Chile", "instrument": "Original",
         "signature": "03-04-2005", "entry_into_force": "06-07-2008",
         "page": 2}],
        "qa": {"covered_agreements": {"read": True, "printed_number_anchors": [1, 2],
                                     "row_attach_pt": 8.0,
                                     "row_attach_band_pt": [2.5, 11.25]}}}
    fresh = view_writer.position_view(record)
    assert position_view_divergences(record, fresh) == []
    assert position_view_divergences(
        record, fresh.replace("Belgium", "Belgique")) == [
            "row 1 other_jurisdiction: the view names 'Belgique', the artefact "
            "holds 'Belgium'"]
    assert position_view_divergences(
        record, fresh.replace("06-07-2008", "")) == [
            "row 2 entry_into_force: the view names '', the artefact holds "
            "'06-07-2008'"]
    # A view that drops a whole row is a disagreement too, not a shorter view.
    dropped = "\n".join(line for line in fresh.splitlines()
                        if not line.startswith("| 2 ")) + "\n"
    assert position_view_divergences(record, dropped) == [
        "rows [] named by the view are not in the artefact and [2] are missing"]
    # The attach line is the artefact's own answer about the room the reading
    # had, so a view that moved an edge, moved the tolerance, emptied the band
    # or named the other reader is caught by the part that moved.
    assert "[2.5, 11.25]" in fresh
    assert position_view_divergences(
        record, fresh.replace("[2.5, 11.25]", "[2.5, 12.25]")) == [
            "attach band: the view names [2.5, 12.25], the artefact holds "
            "[2.5, 11.25]"]
    assert position_view_divergences(
        record, fresh.replace("within 8.0 pt", "within 8.5 pt")) == [
            "attach tolerance: the view names '8.5', the artefact holds 8.0"]
    wrong_reader = fresh.replace("the block reader's prefix reach",
                                 "the number-first window")
    assert position_view_divergences(record, wrong_reader) == [
        "attach reader: the artefact says \"the block reader's prefix reach\" "
        "decided these rows, which the view does not name: "
        + repr(wrong_reader.splitlines()[4])]
    # The band is a pair and an empty one is a fact about the reading, so a view
    # that drew `[]` instead of saying so is stale too.
    empty = json.loads(json.dumps(record))
    empty["qa"]["covered_agreements"]["row_attach_band_pt"] = []
    with_empty = view_writer.position_view(empty)
    assert position_view_divergences(empty, with_empty) == []
    assert position_view_divergences(
        empty, with_empty.replace("leave it is empty", "leave it is []")) == [
            "attach band: the artefact publishes no interval on this layout "
            "and the view does not say so"]
    # A view of a reading that publishes no tolerance carries no attach line,
    # and one that invents it is named as well.
    without = json.loads(json.dumps(record))
    del without["qa"]["covered_agreements"]["row_attach_pt"]
    bare = view_writer.position_view(without)
    assert position_view_divergences(without, bare) == []
    invented = bare.replace("# Probe", fresh.splitlines()[4] + "\n\n# Probe")
    assert position_view_divergences(without, invented) == [
        "attach: the view names an attach tolerance the artefact does not "
        f"publish: {fresh.splitlines()[4]!r}"]
    assert position_view_divergences(record, bare) == [
        "attach: the artefact publishes row_attach_pt = 8.0 over [2.5, 11.25] "
        "and the view carries no attach line"]


def test_p05_bilingual_headings_are_not_interleaved_across_rows():
    """A bilingual table's rows hold one script each, not the neighbour's.

    The blocked defect on Egypt is that the two headings of one table
    interleave: an Arabic heading ends a row while the English heading of the
    agreement below it opens the same cell, so a row is written in both scripts
    and the reading attributes half a heading to the wrong agreement. Fixing it
    is only complete if it is watched, and a fixed defect is exactly the kind
    that regresses silently, so this control re-reads the table with both
    readers: the legacy reading must still interleave the two scripts (that is
    the defect the block reader exists to repair) and the block reading must
    not, on any row. If a future repair makes both readings script-pure, the
    first assertion fails and the layout can be promoted and this control
    retired - it cannot pass by never watching anything.
    """
    for slug in P5_BILINGUAL_LAYOUTS:
        legacy_mixed = [row["no"] for row in legacy_reading(ROOT, slug)
                        if len(_title_scripts(row)) > 1]
        assert legacy_mixed, (
            f"{slug}: the legacy reading no longer puts two scripts in one "
            "title cell, so this control no longer watches the defect it was "
            "written for; re-review the layout and update or retire it")
        block_mixed = [row["no"] for row in block_reading(ROOT, slug)
                       if len(_title_scripts(row)) > 1]
        assert not block_mixed, (
            f"{slug}: rows {block_mixed} carry both an Arabic and a Latin "
            "heading, so the two scripts interleave across the row boundary "
            "again")


# The block-reader layouts whose rows print their number *inside* the heading
# paragraph, so a row's block opens a whole heading line above that number. Every
# other layout prints the number at the head of its row, and a row's block opens
# on the number's own line.
P5_NUMBER_INSIDE_THE_HEADING = frozenset({
    "czechia", "egypt", "indonesia", "ukraine",
})


def test_p05_a_number_inside_the_heading_is_justified_by_the_page():
    """A layout is read as number-inside-the-heading only when its page shows it.

    `mli._numbers_inside_their_heading` decides whether the run of lines above a
    number is that number's own heading or the row above's tail, and it decides
    it by a vote over the anchored groups: does a row's block open above its
    number? That vote is only meaningful when it is taken over openings that are
    a whole heading line deep, and the line is the layout's own, measured from
    its own lines (`mli._heading_lead`), so no table's leading has to be pinned
    by hand for its titles to survive. Israel is the case that proves it: its
    blocks open 0.1pt above their numbers - one baseline, rounded - on all but
    seven rows, so a vote over openings at all called it an inside-the-heading
    table and every one of its titles was truncated at the block boundary
    (`...and the Government of` for `...and the Government of the Republic of
    Armenia`).

    So the habit is pinned twice. The verdict is pinned per slug as the reviewed
    record of which layouts print the number inside the paragraph, so a change to
    the classifier that flips a layout fails here naming it; and the verdict must
    agree with the depth measured on the same groups, so a classifier that
    decides from rounded baselines fails whichever way it votes. Both sides come
    from a live reading of every promoted layout, through the classifier the
    reading itself calls, so the assertion is about the decision the reader
    actually makes and not about a copy of its arithmetic. The line itself is
    asserted to have been measured: a layout whose spacing the vote could not
    read has no row opening above its number, and would otherwise read as a
    head-of-row table for want of a measurement rather than for the page it
    prints.
    """
    inside: set[str] = set()
    for source in sorted(mli_writer.BLOCK_READER_SOURCES):
        pdf_slug = source.removeprefix("mli-position-")
        slug = ARTIFACT_SLUGS.get(pdf_slug, pdf_slug)
        habit = heading_habit(ROOT, slug)
        groups = habit["groups"]
        assert groups, f"{slug}: no anchored group to measure the habit over"
        assert habit["lead"] > 0.0, (
            f"{slug}: the vote's line could not be measured from the layout's own "
            "lines, so no row can be said to open a heading line above its number")
        if habit["inside_heading"]:
            inside.add(slug)
            assert habit["deep"] * 2 > groups, (
                f"{slug}: the reader calls this layout number-inside-the-heading, "
                f"but only {habit['deep']} of its {groups} anchored rows open more "
                f"than half its own {habit['lead']:.2f}pt line above their number "
                f"({habit['opens']} open at all), so the verdict rests on rounded "
                "baselines")
        else:
            assert habit["deep"] * 2 <= groups, (
                f"{slug}: the reader does not call this layout "
                f"number-inside-the-heading, but {habit['deep']} of its {groups} "
                f"anchored rows open more than half its own {habit['lead']:.2f}pt "
                "line above their number")
    assert inside == P5_NUMBER_INSIDE_THE_HEADING, (
        "the layouts read as number-inside-the-heading moved: measured "
        f"{sorted(inside)}, pinned {sorted(P5_NUMBER_INSIDE_THE_HEADING)}")


# The band each promoted page allows the block reader's two tolerances. The
# reader takes both from the layout's own page pitch (`mli._page_pitch`, the step
# a page repeats between the lines of one column): a quarter of a line for the
# shortfall that makes a title line ragged (`mli._block_ragged_slack`) and an
# eighth of a line for how near a mirror must land to count as a printed line
# (`mli._mirror_tol`). These are the widest intervals over which every promoted
# layout's reading is unchanged, measured by `.verify/probe_tolerance_windows.py`
# - each PDF is classified once and re-read under a grid of fixed tolerances,
# and what is pinned is the contiguous run of that grid containing the reader's
# own value on which no row moves. The bands are the pages' own answer to "how
# far may this tolerance go?", and they are wide where the decisions are robust
# (0.1pt to 6pt on two thirds of the layouts) and narrow where they are not
# (israel's ragged slack may move only between 1.75pt and 4.5pt, egypt's only
# between 1.5pt and 5pt), so a change that pushes a tolerance off the page's own
# band is named here rather than surfacing as one row that quietly moved.
P5_BLOCK_TOLERANCE_BANDS = {
    "algeria": {"slack": (0.2, 6.0), "mirror": (0.05, 4.0)},
    "brazil": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "burkina-faso": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "chile": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "china-people-s-republic-of": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "colombia": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "cote-d-ivoire": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "czechia": {"slack": (0.3, 6.0), "mirror": (0.05, 4.0)},
    "egypt": {"slack": (1.5, 5.0), "mirror": (0.2, 4.0)},
    "gabon": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "georgia": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "indonesia": {"slack": (0.3, 6.0), "mirror": (0.05, 4.0)},
    "isle-of-man": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "israel": {"slack": (1.75, 4.5), "mirror": (0.05, 4.0)},
    "latvia": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "lithuania": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "mexico": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "new-zealand": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "nigeria": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "norway": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "pakistan": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "panama": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "peru": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "senegal": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "slovenia": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "south-africa": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "spain": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "sweden": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "tunisia": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
    "ukraine": {"slack": (0.2, 6.0), "mirror": (0.2, 4.0)},
    "viet-nam": {"slack": (0.1, 6.0), "mirror": (0.05, 4.0)},
}


def test_p05_the_block_reader_tolerances_stay_inside_the_band_the_pages_allow():
    """Every tolerance the block reader takes is inside the band its page allows.

    The reader has no shared tolerance left: the shortfall that makes a title
    line ragged and the distance within which a mirror counts as a printed line
    are both fractions of the layout's own page pitch (`mli._page_pitch`), so no
    promotion carries a hand-measured number and a table set at a different
    leading needs no new constant. What a derivation can still get wrong is the
    fraction: a quarter of a line is right only while it lands where the page
    separates a full line's rounding from a printer's break, and an eighth of a
    line only while it stays nearer a genuine mirror than the neighbouring line.

    So the bands are pinned, per slug, from the measurement in
    `P5_BLOCK_TOLERANCE_BANDS` (`.verify/probe_tolerance_windows.py` re-reads every
    promoted layout under a grid of fixed tolerances, so a band is the interval
    over which the rows do not move, not an analysis of one). The two claims are
    checked against a live reading of every promoted layout: that the reader's
    tolerances are still a quarter and an eighth of the pitch it measured from
    that page, and that each value lies inside its pinned band. A band pinned
    for a layout no longer promoted fails too, so the table cannot grow stale.
    """
    moved = []
    promoted = set()
    for source in sorted(mli_writer.BLOCK_READER_SOURCES):
        pdf_slug = source.removeprefix("mli-position-")
        slug = ARTIFACT_SLUGS.get(pdf_slug, pdf_slug)
        promoted.add(slug)
        assert slug in P5_BLOCK_TOLERANCE_BANDS, (
            f"{slug}: promoted onto the block reader with no pinned tolerance "
            "band, so a tolerance leaving the band its page allows could not be "
            "reported")
        band = P5_BLOCK_TOLERANCE_BANDS[slug]
        measured = block_tolerances(ROOT, slug)
        pitch = measured["pitch"]
        assert pitch > 0.0, (
            f"{slug}: the page pitch could not be measured, so neither "
            "tolerance could be taken from the layout - and the measurement, "
            "not a fallback, is what makes a tolerance the layout's own")
        assert (measured["slack"] == pitch / 4.0
                and measured["mirror"] == pitch / 8.0), (
            f"{slug}: the reader's tolerances ({measured['slack']:.3f}pt, "
            f"{measured['mirror']:.3f}pt) are not the layout's own "
            f"{pitch:.2f}pt line: a quarter and an eighth of it")
        for name in ("slack", "mirror"):
            low, high = band[name]
            value = measured[name]
            if not low <= value <= high:
                moved.append(
                    f"{slug}: the {name} tolerance is {value:.3f}pt, outside "
                    f"the ({low}, {high}) band its page allows")
    assert not moved, "\n".join(moved)
    stale = set(P5_BLOCK_TOLERANCE_BANDS) - promoted
    assert not stale, (
        "tolerance bands pinned for layouts the block reader no longer reads: "
        f"{sorted(stale)}")


# The band each remaining declared tolerance of the MLI readers may occupy
# without moving a row, measured by `.verify/probe_constant_windows.py bisect`:
# every source is read with the module attribute replaced, away from the
# declared value until the reading changes, and the interval halved until it is
# 5e-3pt wide - so each endpoint below is a value the sources were *asked about*
# and accepted, not a grid point that happened to be tried. What is pinned is the
# reader's *rows*, not its `qa` block, because several of these numbers travel
# inside the artefact as their own measurement (see `P5_PUBLISHED_TOLERANCES`)
# and a change to one republishes the corpus whether or not a row moves.
#
# Not all of them are declared any more. `POS_ATTACH_REACH_PT`, `POS_ATTACH_PT`,
# `ROW_ATTACH_PT` and `JUSTIFY_SLACK_PT` are *published measurements*: each
# travels inside its artefact as `row_attach_pt` or `span_tol_pt`, so their value
# is part of the data and re-deriving it per layout would republish the corpus.
# `JUSTIFY_SLACK_PT` sits at 10pt inside a band that never closes above it -
# 320pt, thirty-two times the declared value, still reads the same corpus, which
# is what a slack that only ever grows means - and no fraction of any layout's
# line lands inside that band. Pinning the band is what can be honestly claimed
# for those: a tolerance inside its band decides what the corpus already
# publishes, and one that leaves it has changed a reading - or an artefact - and
# is named here.
#
# The two attach tolerances are each walked on their own half of the corpus, as
# their own constant, since the two roles of the old `POS_ATTACH_PT` were
# declared apart: `bisect blockrows` for the block reader's reach (the walk that
# forces every source through the block reader) and `bisect numberrows` for the
# number-first window (the walk that reads the sources that reader does not).
# The window has no band from the block walk at all - the block reader never asks
# that placement, so a band there would be about a reading that never ran - and
# `test_p05_the_attach_tolerances_sit_inside_the_bands_their_pages_leave` says
# which band comes from which half, and why the two cannot be about each other.
#
# `ROW_PITCH_TOL` is the one that stopped being declared. The signatories reader
# derives its threshold from the table's own geometry - `mli._line_step` for the
# step it sets its lines at, `mli._table_pitch` for the step it repeats its rows
# at, one row plus half a line for the threshold - so the constant left in the
# module is only the fallback for a table whose step or pitch cannot be measured.
# The band here contains the *decision* multiple, asked for through
# `derived_tolerances` below so the pin cannot be satisfied by editing the
# fallback; the artefact records the same threshold rounded to a tenth, which
# `P5_PUBLISHED_TOLERANCES` compares. The fallback is checked too, because a page
# that cannot be measured reads at it and would otherwise be an unchecked path
# into the reading.
#
# The two signatories bands are not merely measured: each edge is a distance the
# page prints. `ROW_ATTACH_PT` sits between a line printed 5.16pt above the next
# number that must be captured up to it ("Democratic Republic of the", the first
# line of the jurisdiction below) and a line printed 8.16pt above it that must
# stay with the number above (a notification date) - `.verify/probe_row_pitch_
# depths.py` prints both populations. `ROW_PITCH_TOL` sits between the deepest
# line a row owns, 0.808 of a pitch below its number, and the first line that
# belongs to a later block, 2.017 below the number above it.
#
# Both signatories bands are read off the signatories source under its own id -
# read as a position batch it yields a single row and the walk would report bands
# for a reading nobody publishes, which is how the first, too-wide upper edges
# here were produced.
P5_DECLARED_TOLERANCE_BANDS = {
    # The number-first window, walked over the 70 sources the block reader does
    # not read: both endpoints are values the reading was asked about and
    # accepted, 0.005 pt from the edge. The upper one is well below the interval
    # the pages print (6.6000 pt), and honestly so: that interval is intersected
    # over the layouts that left both sides of the decision open, while the walk
    # asks every layout that decides with the window, and the layout that sets
    # this side - poland - left one side of the decision empty and reports no
    # band. `.verify/probe_number_first_edges.py` names it and prints its rows
    # moving at 6.3632. The lower side is the same edge as the page's deepest
    # lead-in to the 0.005 pt the walk bisects at.
    "POS_ATTACH_PT": (5.7626953125, 6.357421875),
    "POS_ATTACH_REACH_PT": (7.0, 11.6875),
    # The distance within which a wrapped date fragment takes the year printed
    # under it (`mli._join_wrapped_dates`), which feeds both covered-agreements
    # readers. Below 14.04pt some wrapped date's year is left as a line of its
    # own; above it the walk found no edge over four hundred points, which is
    # what a join that is only ever too small looks like.
    "DATE_WRAP_PT": (14.0411376953125, float("inf")),
    "JUSTIFY_SLACK_PT": (7.0361328125, float("inf")),
    "RAGGED_COLUMN_TOL_PT": (0.400146484375, float("inf")),
    "ROW_ATTACH_PT": (5.162109375, 8.1591796875),
    "ROW_PITCH_TOL": (0.80859375, 3.3720703125),
}

# How wide the walk halves each interval before it stops, in points: an endpoint
# above is a value the sources were asked about and accepted, and the true edge
# lies somewhere in the last interval that was split, so agreeing with a
# measured edge means agreeing to this much.
P5_WALK_PRECISION_PT = 5e-3

# The band the reader measures for itself, as a difference of two of the page's
# own baselines and therefore exact: `mli._row_attach_band` reads off the
# signatories reading the furthest a line it captures up to the next number
# stands above that number and the nearest a line it leaves with the number above
# stands above the next one. Those are the two printed distances
# `P5_DECLARED_TOLERANCE_BANDS["ROW_ATTACH_PT"]` is the walk's record of, and
# `test_p05_the_attach_window_sits_inside_the_band_the_page_prints` holds the
# declared window inside them and the walk's endpoints against them.
P5_MEASURED_BANDS = {
    "ROW_ATTACH_PT": (5.160003662109375, 8.160003662109375),
    # The block reader's reach, measured on the promoted layouts that ask it.
    # Four of them do - egypt, israel, sweden and ukraine - and egypt is tight on
    # both edges.
    "POS_ATTACH_REACH_PT": (6.769989013671875, 11.689978027343727),
    # The number-first window, measured on the other half of the corpus - the
    # layouts the block reader does not read, which are the ones that place a
    # span by the numbers around it. Twenty-one of them leave both sides open,
    # and mauritius (the deepest lead-in) and croatia (the nearest tail) set the
    # edges. The promoted layouts are not measured for it and report `None`: no
    # promoted layout's title column is unjustified, so that placement never runs
    # there, and the two bands are therefore about two disjoint readings.
    "POS_ATTACH_PT": (5.760009765625, 6.5999755859375),
}

# The tolerances the readers derive instead of declaring. Pinned by name, in
# both directions: a name here that the reader no longer derives fails as a stale
# pin, and a derived tolerance absent from here would be a value nothing holds.
# A name here is two numbers - what the reader decides with and what it reports -
# and the two are checked by the band test and the published test respectively.
P5_DERIVED_TOLERANCES = {"ROW_PITCH_TOL"}

# The one declared tolerance that decides nothing, and the range over which that
# was established. `CELL_TOL_PT` is the number-first reader's joined-words
# tolerance: it is written into the artefact as `span_tol_pt` and read by no
# decision - the quantity that decides anything is `RAGGED_COLUMN_TOL_PT`, which
# `mli._measured_column_after` uses to find the column edge - so no value of it
# can move a row and the walk finds no edge on either side. What holds it is its
# published value, checked in
# `test_p05_a_tolerance_the_sources_never_read_is_held_by_its_published_value`;
# this pin records the range the walk reached, so a repair that starts to route a
# row through it fails here instead of passing on an unmeasured claim.
P5_UNEXERCISED_TOLERANCES = {
    "CELL_TOL_PT": ("covered_agreements", 1.3969838619232178e-09, 384.0),
}

# The tolerances the artefacts publish as their own measurement, by artefact and
# by the field each travels as. A reader and the data it produced cannot
# disagree about the number that built the data: the artefact says how it was
# measured, and the check is that the reader still says the same.
#
# The covered-agreements artefacts publish the tolerance their own reader decided
# with, and there are two readers: the block reader absorbs a run within
# `POS_ATTACH_REACH_PT`, the number-first reader places a span within
# `POS_ATTACH_PT`, so the one field names a different tolerance in each. Which
# one an artefact means is settled by the artefact's own account of its reader -
# `printed_number_anchors`, which only the block reader writes - and both halves
# are required to be present, so the check cannot come out green on one of them.
P5_PUBLISHED_TOLERANCES = {
    "covered_agreements": {
        "blocks": {"POS_ATTACH_REACH_PT": "row_attach_pt",
                   "CELL_TOL_PT": "span_tol_pt"},
        "number_first": {"POS_ATTACH_PT": "row_attach_pt",
                         "CELL_TOL_PT": "span_tol_pt"},
    },
    "signatories": {"ROW_ATTACH_PT": "row_attach_pt",
                    "ROW_PITCH_TOL": "row_pitch_tol"},
}


# The naming every declared tolerance of the readers follows, so the sweep below
# can find them without a list to be kept in step by hand.
TOLERANCE_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*_(?:PT|TOL)")


def test_p05_every_declared_tolerance_is_pinned_somewhere():
    """No declared tolerance of the MLI readers is left unpinned.

    The pins above are only a sweep if a tolerance cannot slip past them: a
    constant that decides rows and is named in none of them would be the one
    number nobody measures. So this enumerates the reader's declared tolerances -
    every module constant of `harness.mli` whose name ends in `_PT` or `_TOL`,
    the convention each of them follows - and requires each to be pinned at least
    once: by a walked band (`P5_DECLARED_TOLERANCE_BANDS`), by a band the reader
    measures for itself in printed distances (`P5_MEASURED_BANDS`, the attach
    tolerances), or by the range over which it decides nothing
    (`P5_UNEXERCISED_TOLERANCES`). A name in none of the three is unpinned and is
    reported by name, and a pin left for a tolerance the reader no longer
    declares is reported too.

    The three are not exclusive, and are not meant to be: a walked band and a
    reader-measured band are two records of the *same* interval - the reading
    asked at moved values, and the printed distances read off the placement - and
    the band tests hold one against the other. What may not overlap is a band and
    "the range over which it decides nothing": those two contradict each other,
    so a name in both is reported here as one stale claim.

    This says nothing about whether a pin is right - the band tests do that, each
    against the pages - only that no declared tolerance stands outside all of
    them. A number the reader derives rather than declares (the signatories row
    pitch, the block reader's ragged slack and mirror tolerance) is pinned by name
    in `P5_DERIVED_TOLERANCES` and held against the band of the multiple it
    yields, which is checked in
    `test_p05_the_declared_tolerances_stay_inside_the_band_the_sources_allow`.
    """
    declared = sorted(
        name for name in dir(mli_writer)
        if TOLERANCE_NAME_RE.fullmatch(name)
        and isinstance(getattr(mli_writer, name), float))
    assert declared, (
        "no constant of the reader matches the naming convention, so this sweep "
        "would pass on nothing")
    pinned = {"a walked band": set(P5_DECLARED_TOLERANCE_BANDS),
              "a band the reader measures": set(P5_MEASURED_BANDS),
              "a range it decides nothing over": set(P5_UNEXERCISED_TOLERANCES)}
    problems = []
    for name in declared:
        where = sorted(where for where, names in pinned.items() if name in names)
        if not where:
            problems.append(
                f"{name}: declared by the reader and pinned nowhere - a walked "
                "band from `.verify/probe_constant_windows.py`, a band the "
                "reader measures for itself, or the range over which it decides "
                "nothing has to say which it is")
        elif ("a walked band" in where
              and "a range it decides nothing over" in where):
            problems.append(
                f"{name}: pinned both as a band and as a range over which it "
                "decides nothing, so one of the two claims is stale")
    stale = sorted(set().union(*pinned.values()) - set(declared))
    assert not stale, (
        f"{stale}: pinned as tolerances the reader no longer declares, so the "
        "pins are stale")
    assert not problems, "\n".join(problems)


def test_p05_the_declared_tolerances_stay_inside_the_band_the_sources_allow():
    """Every declared tolerance that decides a row is inside its measured band.

    The block reader's own two tolerances are derived from the layout
    (`_block_ragged_slack`, `_mirror_tol`). The rest of the MLI readers' numbers
    are still declared, and each of those that decides something is pinned here
    with the band its sources allow: how far above its number a row's lead-in may
    sit (`POS_ATTACH_PT`), how far short of the title edge a line may fall and
    still count as full (`JUSTIFY_SLACK_PT`), how wide a text column's ragged
    start may be (`RAGGED_COLUMN_TOL_PT`), and the two that place a span in the
    signatories table - the attach window and the row-pitch multiplier that
    decides how far below its anchor a line may sit (`ROW_ATTACH_PT`,
    `ROW_PITCH_TOL`).

    The claim is the one the measurement supports: the value the reader declares
    lies inside the band its sources allow, so a change that pushes it out of
    that band - where it would read a different corpus - fails here naming the
    constant. A band is reported as bounded above by `inf` where the walk found
    no upper edge within its range, which for `JUSTIFY_SLACK_PT` and
    `RAGGED_COLUMN_TOL_PT` is a measured result and not a missing one: a looser
    tolerance there still reads the same pages.

    `ROW_PITCH_TOL` is in the same table for a different reason. The signatories
    reader derives its threshold from the table's own step and pitch, so the
    number that has to be inside the band is the derived one; it is asked for
    through `derived_tolerances`, which calls the reader's own functions on the
    source, and `P5_DERIVED_TOLERANCES` names what must come back. What is checked
    is the *decision* half of that measurement - the threshold in row pitches that
    the reading actually compares distances against - because that is the number
    whose leaving the band changes a reading; the *reported* half is what the
    artefact carries and is checked against the corpus by
    `test_p05_the_published_tolerances_are_the_ones_the_reader_uses`. The module
    constant is still checked here as well, because it is the fallback a page
    whose geometry cannot be measured reads at - an unchecked way into the
    reading otherwise.

    `CELL_TOL_PT` is not pinned here, because it has no band to lie inside: it
    moves no row at any value the walk tried, so a band for it would be a claim
    the measurement does not make. Its own check is
    `test_p05_a_tolerance_the_sources_never_read_is_held_by_its_published_value`,
    and it is pinned in `P5_UNEXERCISED_TOLERANCES` so that a reader that starts
    to depend on it fails there rather than passing here on a bound nobody could
    measure. The two dicts are checked not to overlap, since a constant in both
    would carry one stale claim whichever way the reader went.
    """
    problems = []
    unchecked = set(P5_UNEXERCISED_TOLERANCES) & set(
        P5_DECLARED_TOLERANCE_BANDS)
    assert not unchecked, (
        f"{sorted(unchecked)}: pinned both as a band and as unexercised, so "
        "one of the two claims is stale")

    def inside(name: str, value: float, where: str, low: float,
               high: float) -> None:
        if not low <= value <= high:
            problems.append(
                f"{where} is {value:g}, outside the ({low:g}, {high:g}) band "
                "its sources allow")
        if low >= high:
            problems.append(
                f"{name}: the pinned band ({low:g}, {high:g}) is empty")
        if high == float("inf") and low <= 0.0:
            problems.append(
                f"{name}: a band open on both sides pins nothing")

    for name, (low, high) in P5_DECLARED_TOLERANCE_BANDS.items():
        assert hasattr(mli_writer, name), (
            f"{name}: a tolerance pinned here is no longer declared by the "
            "reader, so the band is stale")
        inside(name, getattr(mli_writer, name), name, low, high)

    source = ROOT / "sources" / "mli-signatories-and-parties.pdf"
    _need(source.is_file(),
          "the signatories source (sources/mli-signatories-and-parties.pdf)")
    derived = derived_tolerances(ROOT)
    stale = P5_DERIVED_TOLERANCES - set(derived)
    assert not stale, (
        f"{sorted(stale)}: pinned as derived, but the reader does not derive "
        "it any more, so the pin is stale")
    unheld = set(derived) - P5_DERIVED_TOLERANCES
    assert not unheld, (
        f"{sorted(unheld)}: the reader derives a tolerance nothing pins, so "
        "nothing would notice it leaving the band its sources allow")
    for name, numbers in sorted(derived.items()):
        low, high = P5_DECLARED_TOLERANCE_BANDS[name]
        inside(name, numbers["decision"], f"the derived {name}", low, high)

    assert not problems, "\n".join(problems)


def test_p05_the_published_tolerances_are_the_ones_the_reader_uses():
    """A published artefact and its reader agree on the numbers that built it.

    Several of the MLI readers' tolerances are not merely used, they are
    *published*: each covered-agreements reader writes the attachment it decides
    with and the tolerance it joins words with into `qa.covered_agreements` - the
    block reader its prefix reach, the number-first one its window - and the
    signatories reader writes the row pitch tolerance and attach window into its
    own `qa`. Those numbers travel with the data on purpose - a reader of the
    artefact can rebuild the reading it records without this program - and the
    price is that they cannot be re-derived per layout without republishing the
    corpus.

    So they are checked in the other direction: every published artefact's own
    account of how it was measured is compared with what the reader uses
    now. A reader that changes one of these numbers and does not rebuild the
    corpus fails here, which is the honest statement of what pinning them means
    - the artefact is the measurement, and the code must agree with it.

    For `ROW_PITCH_TOL` that account is of a derived number: the reader measures
    the threshold from the table's own step and pitch, and the artefact carries
    that threshold as a multiple of the row pitch. The comparison is therefore
    against the *reported* half of `derived_tolerances` - the reader's own
    derivation, run on the source, rounded as the reader rounds it - and not
    against the fallback constant, which the corpus does not record. The
    decision half of the same measurement is what the band pins.
    """
    positions = corpus.position_files(ROOT)
    _need(positions, "the MLI position artefacts (corpora/mli/positions/*.json)")
    signatories = corpus.signatories(ROOT)
    _need(signatories.exists(),
          "the signatories artefact (corpora/mli/signatories-and-parties.json)")
    source = ROOT / "sources" / "mli-signatories-and-parties.pdf"
    _need(source.is_file(),
          "the signatories source (sources/mli-signatories-and-parties.pdf)")
    derived = derived_tolerances(ROOT)

    checked = []
    problems = []

    def compare(where: str, qa: dict, published: dict) -> None:
        for name, field in published.items():
            if field not in qa:
                continue
            checked.append(f"{where}.{field}")
            if name in derived:
                current = derived[name]["reported"]
            else:
                current = getattr(mli_writer, name, None)
            if current is None:
                problems.append(
                    f"{where}: the artefact publishes {field}, but the reader "
                    f"has no {name} left to compare it with")
                continue
            if qa[field] != current:
                problems.append(
                    f"{where}: the artefact publishes {field} = {qa[field]!r}, "
                    f"the reader now uses {name} = {current!r}")

    halves: dict[str, int] = {}
    for path in positions:
        record = json.loads(path.read_text(encoding="utf-8"))
        qa = (record.get("qa") or {}).get("covered_agreements") or {}
        # Which tolerance `row_attach_pt` names is the artefact's own account of
        # its reader: `printed_number_anchors` is written only by the block one.
        half = "blocks" if "printed_number_anchors" in qa else "number_first"
        halves[half] = halves.get(half, 0) + 1
        compare(f"{path.name}", qa,
                P5_PUBLISHED_TOLERANCES["covered_agreements"][half])
    record = json.loads(signatories.read_text(encoding="utf-8"))
    compare("signatories-and-parties.json", record.get("qa") or {},
            P5_PUBLISHED_TOLERANCES["signatories"])

    assert checked, (
        "no artefact publishes an MLI tolerance, so this check is green by "
        "emptiness")
    missing = sorted(set(P5_PUBLISHED_TOLERANCES["covered_agreements"])
                     - set(halves))
    assert not missing, (
        f"no position artefact publishes the {missing} half's tolerance, so the "
        "comparison against that reader is green by emptiness")
    assert not problems, "\n".join(problems)


def test_p05_the_attach_window_sits_inside_the_band_the_page_prints():
    """The signatories attach window is bounded by two printed distances.

    `ROW_ATTACH_PT` is a *published* measurement: its value travels inside the
    signatories artefact as `row_attach_pt`, so re-deriving it would republish
    the corpus and it stays declared. What the reader measures instead is the
    interval the page's own lines leave for it - the furthest a line it captures
    up to the next number stands above that number, and the nearest a line it
    leaves with the number above stands above the next one
    (`mli._row_attach_band`, through `signatories_geometry` as the reading's own
    functions rather than as a copy of its arithmetic). A line printed exactly at
    the lower edge is captured up - `_owner` compares with `<=` - so the window
    may sit there, while a line printed exactly at the upper edge would be
    captured too, and read out of the row the page prints it in, so the window has
    to stay strictly below it: the band is half-open.

    Which lines are on which side of the boundary is the placement's doing, so the
    measured interval is the one the window sits in *by construction*; what makes
    it a claim about the page is that it has to be the interval the sources print,
    which is pinned from the other side. The measured interval must be the one in
    `P5_MEASURED_BANDS`, a difference of two printed baselines and therefore
    exact; and the walk's own record of the same band, bisected in
    `.verify/probe_constant_windows.py` down to `P5_WALK_PRECISION_PT`, has to
    land on it - so the room the window has is established two ways, by
    re-reading the sources at moved values and by measuring the distances off the
    placement, and a repair that moves a line into that gap fails here rather than
    passing on a pin nobody re-measured.

    The window is then held against the walk's band rather than against the
    measured one, and half-open: a line printed exactly at the upper edge is
    captured up, so a window there would read it out of the row the page prints it
    in, and `P5_DECLARED_TOLERANCE_BANDS` alone - which accepts either edge - would
    not say so.

    The band is also what the artefact now carries, as `qa.row_attach_band_pt`:
    the reading publishes the interval it sits in, so a consumer of the data can
    see how much room the page leaves the window without rerunning the reader,
    and the comparison here is between the reader's measurement of that interval
    and the number the corpus publishes for it - the same direction the published
    tolerances are checked in, and a repair that moves a line into the gap fails
    on both sides at once.
    """
    source = ROOT / "sources" / "mli-signatories-and-parties.pdf"
    _need(source.is_file(),
          "the signatories source (sources/mli-signatories-and-parties.pdf)")
    geometry = signatories_geometry(ROOT)
    low, high = geometry["row_attach_band"]
    assert low < high, (
        f"the attach window's measured band ({low!r}, {high!r}) is empty, so "
        "the page leaves the window nowhere to sit")
    measured = P5_MEASURED_BANDS["ROW_ATTACH_PT"]
    assert (low, high) == measured, (
        f"the band the reader measures for the attach window moved: measured "
        f"({low!r}, {high!r}), pinned {measured!r}, so a line the page prints is "
        "now inside the gap the window sits in")
    signatories = corpus.signatories(ROOT)
    _need(signatories.exists(),
          "the signatories artefact (corpora/mli/signatories-and-parties.json)")
    record = json.loads(signatories.read_text(encoding="utf-8"))
    published = (record.get("qa") or {}).get("row_attach_band_pt")
    reading = [round(low, 2), round(high, 2)]
    assert published == reading, (
        f"the artefact publishes row_attach_band_pt = {published!r}, the reader "
        f"measures {reading!r} for the same interval; the data and the reader "
        "cannot disagree about the room the window has")
    walked_low, walked_high = P5_DECLARED_TOLERANCE_BANDS["ROW_ATTACH_PT"]
    declared = mli_writer.ROW_ATTACH_PT
    assert walked_low <= declared < walked_high, (
        f"the declared ROW_ATTACH_PT is {declared!r}, outside the "
        f"[{walked_low!r}, {walked_high!r}) band the page's own lines leave for "
        "it")
    for walked, edge, where in ((walked_low, low, "lower"),
                                (walked_high, high, "upper")):
        assert abs(walked - edge) <= P5_WALK_PRECISION_PT, (
            f"the walk's {where} edge for ROW_ATTACH_PT is {walked:g}, but the "
            f"distance the page prints there is {edge:g}; the two measurements "
            f"of the same band disagree by more than the {P5_WALK_PRECISION_PT:g}pt "
            "the walk bisects at")


def test_p05_the_signatories_view_names_the_rows_and_band_of_its_artefact():
    """A view cannot name a jurisdiction, a date or a band its artefact does not.

    The signatories table has the same kind of derived markdown view the
    positions have (`derived/markdown/mli/signatories-and-parties.md`),
    rendered from the artefact it summarises - its rows, and the window and
    band its own reading publishes - and the two can fall apart the same way a
    reader repair makes the corpus stale. So this control reads the view back
    and compares it with its artefact row by row and field by field, and the
    attach line whose tolerance and two band edges are read back and held
    against `row_attach_pt` and `row_attach_band_pt`
    (`mli_row_audit.signatories_view_divergences`), because the interval the
    reading left is as much the artefact's own answer as a jurisdiction is.
    """
    signatories = corpus.signatories(ROOT)
    _need(signatories.exists(),
          "the signatories artefact (corpora/mli/signatories-and-parties.json)")
    record = json.loads(signatories.read_text(encoding="utf-8"))
    view = ROOT / "derived" / "markdown" / "mli" / "signatories-and-parties.md"
    problems = []
    if not view.is_file():
        problems.append(f"no derived view at {view.relative_to(ROOT).as_posix()}")
    else:
        problems.extend(signatories_view_divergences(
            record, view.read_text(encoding="utf-8")))
    assert not problems, "\n".join(problems[:40])


def test_p05_the_signatories_view_control_catches_a_stale_view():
    """The control bites: a view the artefact has moved on from fails.

    `test_p05_the_signatories_view_names_the_rows_and_band_of_its_artefact` is
    only a control if a wrong view fails it, so this is the negative control
    beside it. The sample table is built in memory and rendered by the same
    renderer the corpus uses - the real renderer on invented content, never
    invented markdown - and then corrupted in each way a stale view goes stale:
    a jurisdiction the artefact no longer holds, a date it does, and the attach
    line by each of its parts - the band edge that moved, the tolerance, and
    the reader the view names.
    """
    record = {"rows": [
        {"no": 1, "jurisdiction": "Albania", "signature": "28-05-2019",
         "deposit": "22-09-2020", "entry_into_force": "01-01-2021",
         "page": 0},
        {"no": 2, "jurisdiction": "Andorra", "signature": "27-05-2019",
         "deposit": None, "entry_into_force": None, "page": 1}],
        "qa": {"row_attach_pt": 6.0, "row_attach_band_pt": [5.16, 8.16],
               "row_pitch_tol": 1.5}}
    fresh = view_writer.signatories_view(record)
    assert signatories_view_divergences(record, fresh) == []
    assert signatories_view_divergences(
        record, fresh.replace("Albania", "Albanie")) == [
            "row 1 jurisdiction: the view names 'Albanie', the artefact "
            "holds 'Albania'"]
    assert signatories_view_divergences(
        record, fresh.replace("01-01-2021", "")) == [
            "row 1 entry_into_force: the view names '', the artefact holds "
            "'01-01-2021'"]
    # A view that drops a whole row is a disagreement too, not a shorter view.
    dropped = "\n".join(line for line in fresh.splitlines()
                        if not line.startswith("| 2 ")) + "\n"
    assert signatories_view_divergences(record, dropped) == [
        "rows [] named by the view are not in the artefact and [2] are missing"]
    # The attach line is the artefact's own answer about the room the reading
    # had, so a view that moved an edge, moved the tolerance or named another
    # reader is caught by the part that moved.
    assert "[5.16, 8.16]" in fresh
    assert signatories_view_divergences(
        record, fresh.replace("[5.16, 8.16]", "[5.16, 8.66]")) == [
            "attach band: the view names [5.16, 8.66], the artefact holds "
            "[5.16, 8.16]"]
    assert signatories_view_divergences(
        record, fresh.replace("within 6.0 pt", "within 6.5 pt")) == [
            "attach tolerance: the view names '6.5', the artefact holds 6.0"]
    wrong = fresh.replace("(the signatories window)",
                          "(the number-first window)")
    line = next(text for text in wrong.splitlines()
                if text.startswith("*Attach:"))
    assert signatories_view_divergences(record, wrong) == [
        "attach reader: the artefact says 'the signatories window' decided "
        f"these rows, which the view does not name: {line!r}"]


def test_p05_the_attach_tolerances_sit_inside_the_bands_their_pages_leave():
    """Each covered-agreements attach tolerance is bounded by its own pages.

    The two readers of these tables attach in two ways, and the two are declared
    apart: the number-first reader places a span among the numbers around it
    within `POS_ATTACH_PT` (`mli._row_of`), and the block reader absorbs a run of
    lines printed above a number as that row's own prefix within
    `POS_ATTACH_REACH_PT` (`mli._absorbs_prefix`). Both are *published* - each
    travels inside the artefacts its own reader produces, as `row_attach_pt` - so
    neither can be re-derived per layout without republishing them, and what is
    measured instead is the interval the pages leave each one.

    The reach is measured on the promoted layouts (`covered_attach_band`), which
    are the ones that decide with it, and the window on the number-first layouts
    (`number_first_attach_band`), which are the ones the block reader does not
    read: two disjoint halves of the corpus, measured off the reader's own
    answers, so neither band can be about the other's reading. That the promoted
    half never asks the window is asserted rather than assumed - a layout that
    starts placing its spans by the numbers around it would be measured here too
    - and each edge is a distance its own pages print, so both bands are exact.

    The declared tolerance has to lie in its band half-open, because both readers
    compare with `<=`: a span (or a run) printed exactly at the lower edge is
    captured and one printed exactly at the upper edge would be too. Both bands
    are also walked in `.verify/probe_constant_windows.py` - the reading itself is
    asked, away from the declared value until the rows move: the reach on the
    block half (`bisect blockrows`) and the window on the number-first half
    (`bisect numberrows`), each over the layouts that decide with it, which is
    what the two halves are for.

    The walk and the band are two records of one interval, and for the window
    they are not equal: the walk is the tighter one on the upper side. The band
    is intersected over the layouts that left *both* sides of the decision open,
    while the walk asks every layout that decides with the window - and a layout
    whose placement left one side empty reports no band at all, so it is in no
    intersection while still bounding the window from the side it did measure.
    That layout is poland, named by `.verify/probe_number_first_edges.py`, whose
    rows move at 6.3632 pt while the pages that do leave both sides print
    6.6000 pt. The lower side is one edge in both records, to the 0.005 pt the
    walk bisects at. The window's two edges are also held against the reading
    directly (`number_first_rows_at`): the rows are the declared ones at each
    edge and at the declared value, and each tight layout moves just beyond the
    edge it sets.

    Each reading also publishes the interval it measured on its own layout, as
    `qa.covered_agreements.row_attach_band_pt`, so the room a tolerance has on a
    layout travels with the rows that layout's tolerance decided and the drift
    control names a moved run against the published band - the same direction the
    published tolerances are checked in, and a repair that moves a run into the
    gap fails in the control and here at once.
    """
    _need(all((ROOT / "sources" / "mli-positions" / f"{name}.pdf").is_file()
              for name in mli_writer.BLOCK_READER_SOURCES),
          "the MLI position sources (sources/mli-positions/*.pdf)")
    promoted = covered_attach_band(ROOT)
    assert promoted["POS_ATTACH_PT"] is None, (
        "a promoted layout now places its spans by the numbers around them, so "
        f"the window is exercised there and needs a band here too: "
        f"{promoted['POS_ATTACH_PT']}")
    reach = promoted["POS_ATTACH_REACH_PT"]
    assert reach is not None and reach["low"] < reach["high"], (
        "the pages leave the block reader's prefix reach nowhere to sit: "
        f"{reach}")
    window = number_first_attach_band(ROOT)
    assert window is not None and window["low"] < window["high"], (
        "the pages leave the number-first window nowhere to sit: "
        f"{window}")

    for name, band in (("POS_ATTACH_REACH_PT", reach),
                       ("POS_ATTACH_PT", window)):
        low, high = band["low"], band["high"]
        measured = P5_MEASURED_BANDS[name]
        assert (low, high) == measured, (
            f"the band the reader measures for {name} moved: measured "
            f"({low!r}, {high!r}) over {band['layouts']} layout(s), pinned "
            f"{measured!r}, so a distance the pages print is now inside the gap "
            "the tolerance sits in")
        declared = getattr(mli_writer, name)
        assert low <= declared < high, (
            f"the declared {name} is {declared!r}, outside the "
            f"[{low!r}, {high!r}) band its own pages leave for it")

    walked_low, walked_high = P5_DECLARED_TOLERANCE_BANDS[
        "POS_ATTACH_REACH_PT"]
    declared = mli_writer.POS_ATTACH_REACH_PT
    assert walked_low <= declared < walked_high, (
        f"the declared POS_ATTACH_REACH_PT is {declared!r}, outside the "
        f"[{walked_low!r}, {walked_high!r}) band the walk found for it")
    assert reach["low"] <= walked_low, (
        f"the walk's lower edge {walked_low:g} is below the measured band's "
        f"{reach['low']:g}, which cannot be: the walk's band is the tighter "
        "record of the same interval")
    assert abs(walked_high - reach["high"]) <= P5_WALK_PRECISION_PT, (
        f"the walk's upper edge {walked_high:g} and the distance the pages "
        f"print there, {reach['high']:g}, disagree by more than the "
        f"{P5_WALK_PRECISION_PT:g}pt the walk bisects at")

    # The window is walked on its own half of the corpus, and the two records of
    # it are not the same interval: the walk is the tighter one on the upper
    # side, because it asks every layout that decides with the window while the
    # band is an intersection over the layouts that left *both* sides of the
    # decision open. A layout whose placement left one side empty reports no band
    # and so is in no intersection, and still bounds the window from the side it
    # did measure - on the upper side that layout is poland, which
    # `.verify/probe_number_first_edges.py` names, and which moves at 6.3632
    # while the bandless half of the corpus leaves the pages printing 6.6000.
    walked_low, walked_high = P5_DECLARED_TOLERANCE_BANDS["POS_ATTACH_PT"]
    declared = mli_writer.POS_ATTACH_PT
    assert walked_low <= declared < walked_high, (
        f"the declared POS_ATTACH_PT is {declared!r}, outside the "
        f"[{walked_low!r}, {walked_high!r}) band the walk found for it")
    assert abs(walked_low - window["low"]) <= P5_WALK_PRECISION_PT, (
        f"the walk's lower edge {walked_low:g} and the deepest lead-in the "
        f"pages print, {window['low']:g}, disagree by more than the "
        f"{P5_WALK_PRECISION_PT:g}pt the walk bisects at: on this side the two "
        "records are the same edge")
    assert walked_high < window["high"], (
        f"the walk's upper edge {walked_high:g} is not below the band the pages "
        f"print, {window['high']:g}; that band is an intersection over the "
        "layouts that left both sides of the decision open, so a layout that "
        "left one side empty has to be the tighter record or the walk is not "
        "asking every layout that decides with the window")
    assert window["high"] - walked_high > P5_WALK_PRECISION_PT, (
        f"the walk's upper edge {walked_high:g} is inside the page's "
        f"{window['high']:g} by less than the {P5_WALK_PRECISION_PT:g}pt the "
        "walk bisects at, so the two records cannot be told apart here and the "
        "bandless layout that tightens this side is no longer named")

    # The window's two edges, held against the reading and not against the
    # placement that measured them: inside the band the rows are the declared
    # ones, and one step beyond each edge the layout that set it moves.
    low, high = window["low"], window["high"]
    below_low, nearly_high = low - P5_WALK_PRECISION_PT, high - P5_WALK_PRECISION_PT
    tight = [window["low_layout"], window["high_layout"]]
    readings = number_first_rows_at(
        ROOT, "POS_ATTACH_PT", tight,
        [mli_writer.POS_ATTACH_PT, low, nearly_high, below_low, high])
    declared = mli_writer.POS_ATTACH_PT
    for slug in tight:
        for value in (low, nearly_high):
            assert readings[value][slug] == readings[declared][slug], (
                f"{slug}: the window at {value!r} does not read as it does at "
                f"the declared {declared!r}, though {value!r} is inside the "
                f"[{low!r}, {high!r}) band its pages leave")
    for slug, value, where in ((window["low_layout"], below_low, "lower"),
                               (window["high_layout"], high, "upper")):
        assert readings[value][slug] != readings[declared][slug], (
            f"{slug} sets the {where} edge of the window's band and has to move "
            f"there: at {value!r} it reads as it does at the declared "
            f"{declared!r}, so the edge the placement reported is not where the "
            "reading changes")

    # Both tolerances also travel inside the data. Each reading publishes the
    # interval it measured for its own tolerance as
    # `qa.covered_agreements.row_attach_band_pt`, so the drift control compares
    # that field path by path against a fresh reading - a repair that moves a run
    # into the gap one of these tolerances sits in is named by the control that
    # guards the corpus, and not only by this measurement.
    carried: dict[str, list] = {"blocks": [], "number_first": []}
    silent = []
    for path in corpus.position_files(ROOT):
        record = json.loads(path.read_text(encoding="utf-8"))
        qa = (record.get("qa") or {}).get("covered_agreements") or {}
        if "row_attach_pt" not in qa:
            continue
        if "row_attach_band_pt" not in qa:
            silent.append(path.name)
            continue
        half = "blocks" if "printed_number_anchors" in qa else "number_first"
        bands = (reach if half == "blocks" else window)["per_layout"]
        expected = mli_writer._rounded_band(bands.get(record["slug"], ()))
        carried[half].append(record["slug"])
        assert qa["row_attach_band_pt"] == expected, (
            f"{path.name}: the artefact publishes row_attach_band_pt = "
            f"{qa['row_attach_band_pt']!r}, the same layout's own reading "
            f"measures {expected!r} now; the data and the reader cannot disagree "
            "about the room the tolerance has on this layout")
    assert not silent, (
        "these readings publish an attach tolerance but not the band it was "
        f"measured over, so the drift control cannot name it: {silent}")
    for half, slugs in sorted(carried.items()):
        assert slugs, (
            f"no {half} position artefact publishes the band its own reading "
            "measured, so the corpus carries that half's interval for nobody")


def test_p05_the_batch_report_carries_every_layouts_measured_band():
    """The family's own report names each layout's measured band.

    `batch-report.json` is the one place the family ties a source file to the
    slug it is published under, and it also carries every published position's
    own measured band - the reader its rows were decided with, the tolerance,
    and the interval that layout left it - plus, per tolerance, the layouts
    that set the two edges of the global intersection. The per-layout entries
    are held against what each artefact publishes, and the tight layouts
    against the intersection recomputed from those entries, so the intersection
    is readable from the report without re-reading the sources and a report
    that moved a band fails here rather than passing on a copy nobody
    re-checks.
    """
    stored = corpus.corpus_root(ROOT) / "mli" / "positions"
    report_path = stored / "batch-report.json"
    _need(report_path.is_file(),
          "the family report (corpora/mli/positions/batch-report.json)")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    bands = report.get("attach_bands") or {}
    layouts = bands.get("layouts") or {}
    problems = []
    seen = set()
    for path in corpus.position_files(ROOT):
        record = json.loads(path.read_text(encoding="utf-8"))
        slug = record["slug"]
        qa = (record.get("qa") or {}).get("covered_agreements") or {}
        if "row_attach_pt" not in qa:
            expected = {"reader": None, "row_attach_pt": None,
                        "row_attach_band_pt": []}
        else:
            expected = {
                "reader": ("block" if "printed_number_anchors" in qa
                           else "number-first"),
                "row_attach_pt": qa["row_attach_pt"],
                "row_attach_band_pt": list(
                    qa.get("row_attach_band_pt") or []),
            }
        seen.add(slug)
        if layouts.get(slug) != expected:
            problems.append(
                f"{slug}: the report carries {layouts.get(slug)!r}, the "
                f"artefact publishes {expected!r}")
    extra = sorted(set(layouts) - seen)
    assert not extra, (
        f"the report names bands for layouts the corpus does not publish: {extra}")
    assert not problems, "\n".join(problems)
    assert seen, (
        "no published position to compare the report against, so this check "
        "would pass on nothing")
    tight = bands.get("tight") or {}
    for tolerance, half in (("POS_ATTACH_PT", "number-first"),
                            ("POS_ATTACH_REACH_PT", "block")):
        measured = [(slug, entry["row_attach_band_pt"])
                    for slug, entry in layouts.items()
                    if entry.get("reader") == half
                    and entry.get("row_attach_band_pt")]
        assert measured, (
            f"no {half} layout in the report leaves a band, so the {tolerance} "
            "intersection would be empty")
        expected_tight = {
            "low": max(measured, key=lambda item: item[1][0])[0],
            "high": min(measured, key=lambda item: item[1][1])[0],
        }
        assert tight.get(tolerance) == expected_tight, (
            f"the report names {tight.get(tolerance)!r} as the layouts that set "
            f"the {tolerance} edges, recomputed from its own entries they are "
            f"{expected_tight!r}")


def test_p05_no_declared_tolerance_hides_a_second_role():
    """A declared tolerance is one value, named at every site that reads it.

    `POS_ATTACH_PT` was the case that showed why this matters: the block reader's
    reach was declared as that window plus a slack, so the two tolerances were
    one value in two names, the layouts that read one read the other, and the
    window's band could not be measured alone - it had to be intersected with the
    reach's uses. The shape is worth looking for in the tolerances that are left,
    and `mli_row_audit.tolerance_audit` reads the harness' own source for it: no
    module-level constant may be *computed from* a declared tolerance, and no call
    may pass a declared tolerance's number where the call takes a tolerance.

    Both are asserted, and both are about a name rather than a value: a constant
    derived from a tolerance makes two names one number, and a literal at a call
    site is a copy of one that nothing pins - the declared tolerance can move and
    that site will keep reading what it used to. Naming them is the whole repair,
    so the check needs no band and no measurement.

    What the same audit *reports* without asserting is a number repeated in a
    default, which can also be a coincidence of two roles: `mli._x_clusters`
    clusters x starts within 1.5pt, which is not the row-pitch multiple the
    signatories reader derives, and `ledger`'s line grouping allows a 25pt gap,
    which is not `DATE_WRAP_PT`. Those two are left as they are, and what holds
    them is the audit naming them for a reader rather than this test deciding
    which role a number has; the tolerances that *are* shared have to be declared
    apart, as the attach ones now are.
    """
    audit = tolerance_audit(ROOT)
    assert audit["tolerances"], (
        "no module-level declared tolerance was found in harness/, so this "
        "check is green by emptiness: it reads the names it audits off the "
        "sources")
    assert not audit["derived"], (
        "a module-level constant is computed from a declared tolerance, so two "
        "names hold one value and no band can be about either of them alone: "
        f"{audit['derived']}")
    assert not audit["literals"], (
        "a call passes a declared tolerance's number as a literal, so the site "
        "keeps its own copy of a value nothing pins and no band measures: "
        f"{audit['literals']}")


def test_p05_a_tolerance_the_sources_never_read_is_held_by_its_published_value():
    """A tolerance that decides nothing is held by the number the data carries.

    `CELL_TOL_PT` is the one declared tolerance no row depends on. It is the
    number-first reader's joined-words tolerance: it is *published* as
    `qa.covered_agreements.span_tol_pt` and read by no decision, because the
    quantity that decides a column edge is `RAGGED_COLUMN_TOL_PT` inside
    `mli._measured_column_after`. So there is no band to pin for it - the
    bisection in `.verify/probe_constant_windows.py` finds no edge on either
    side, because there is none to find - and the walk's silence is evidence
    rather than a gap.

    What holds it instead is the artefact.
    `test_p05_the_published_tolerances_are_the_ones_the_reader_uses` already
    makes the reader agree with the number the corpus publishes; here the other
    half is checked, that the number really is inert: every promoted layout is
    re-read at both ends of the range the walk tried, and each must come back
    with the rows the declared value produces. A value at which the read raises
    counts as the same failure - it decided too - so it is reported as a moved
    layout rather than escaping as an error. A repair that starts to route a row
    through `CELL_TOL_PT` therefore fails here naming the constant and the
    layouts that moved, and only then does it have to be given a band.

    The range is the one the walk reached and not a band: nothing is claimed
    about values outside it. That is why it is pinned apart from
    `P5_DECLARED_TOLERANCE_BANDS`, and why the two are checked not to overlap.
    """
    moved = []
    compared = 0
    for name, (reader, low, high) in sorted(P5_UNEXERCISED_TOLERANCES.items()):
        assert hasattr(mli_writer, name), (
            f"{name}: pinned as unexercised, but the reader no longer declares "
            "it, so the pin is stale")
        declared = getattr(mli_writer, name)
        assert low < declared < high, (
            f"{name}: the reader declares {declared:g}, outside the "
            f"({low:g}, {high:g}) range the sources were asked about")
        values = [declared, low, high]
        if reader == "signatories":
            readings = {
                value: {"signatories-and-parties.json": rows}
                for value, rows in signatories_rows_at(ROOT, name, values).items()}
        else:
            readings = block_rows_at(ROOT, name, values)
        for slug in sorted(readings[declared]):
            for value in (low, high):
                compared += 1
                if readings[value][slug] != readings[declared][slug]:
                    moved.append(
                        f"{name} = {value:g}: {slug} does not read as it does "
                        f"at the declared {declared:g}, so the tolerance decides "
                        "a row after all and needs a band -> "
                        f"{readings[value][slug][:120]}")
    assert compared, (
        "no source was re-read, so this check is green by emptiness")
    assert not moved, "\n".join(moved)


def test_p05_title_cells_hold_each_printed_number_once():
    """Every selected reader accounts for every printed number exactly once.

    `numbers_with_no_row` is the legacy reader's account of a numbering gap,
    and the audit of 2026-09-27 caught it under-reporting twice over: 21 of the
    31 positions whose title cells hold more than one printed number declared
    no gap at all, because the count stopped at the last number a published
    row carries (mexico published 51 rows numbered to 60 while the page prints
    61). A reader that drops printed numbers silently, without declaring them,
    is the one thing this invariant exists to prevent.

    The audit re-reads every readable position and asks the selected reader's
    own measured geometry the relevant question: how many legacy title cells
    hold more than one printed number and which numbers opened no row; or, for
    the block reader, whether emitted rows account for every printed number
    anchor exactly once. A mismatch in legacy is accepted only where declared,
    by slug, in `P5_CELL_MODEL_EXCEPTIONS`; a block reading is admitted only
    after its rows match its anchors and the recovered-row pins pass. The
    declaration runs in both directions: a mismatch without a declaration
    fails here, and a declared legacy slug whose cells now match fails too -
    the entry is stale and must be removed, so the exception list cannot grow
    into a shelf for defects nobody revisits. The genuine absence is not an exception: where
    the page itself prints no number (papua-new-guinea's row 5), the reader's
    gap declaration is the honest account, and this invariant says nothing.
    """
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    entry = next((item for item in sources
                  if item["id"] == "mli-positions-batch"), None)
    _need(entry is not None and entry.get("dir"),
          "the source register declares the positions family")
    directory = ROOT / entry["dir"]
    if not directory.is_dir():
        pytest.skip("the MLI positions family is not in sources/, so there "
                    "is nothing to read")
    stored_dir = corpus.corpus_root(ROOT) / "mli" / "positions"
    if not any(stored_dir.glob("*.json")):
        pytest.skip("no stored position artefacts to audit")

    sha_map = {}
    for pdf in sorted(directory.glob("*.pdf")):
        sha_map[hashlib.sha256(pdf.read_bytes()).hexdigest()] = pdf

    unexpected: list[str] = []
    unused = set(P5_CELL_MODEL_EXCEPTIONS)
    paired = audited = 0
    for stored_path in sorted(stored_dir.glob("*.json")):
        if stored_path.stem == "batch-report":
            continue
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        if not (stored.get("qa") or {}).get("covered_agreements", {}).get("read"):
            continue
        pdf = sha_map.get(stored.get("sha256", ""))
        if pdf is None:
            unexpected.append(f"{stored_path.stem}: no PDF with this artefact's "
                              f"sha256")
            continue
        paired += 1
        audit = _position_table_audit(pdf)
        if audit is None or audit["reader"] == "number-first":
            continue
        audited += 1
        if audit["reader"] == "blocks":
            if audit["lost"] or audit["unexpected"] or audit["duplicates"]:
                unexpected.append(
                    f"{stored_path.stem}: block reader anchors/rows disagree: "
                    f"lost={audit['lost']}, unexpected={audit['unexpected']}, "
                    f"duplicates={audit['duplicates']}")
            for number, (counterparty, title_fragment) in \
                    P5_BLOCK_ROW_PINS.get(stored_path.stem, {}).items():
                row = audit["rows"].get(number)
                if row is None:
                    unexpected.append(
                        f"{stored_path.stem} row {number}: block reader did not "
                        "emit the pinned recovered row")
                    continue
                if row.get("other_jurisdiction") != counterparty:
                    unexpected.append(
                        f"{stored_path.stem} row {number}: counterparty "
                        f"{row.get('other_jurisdiction')!r}, expected {counterparty!r}")
                if title_fragment.casefold() not in str(row.get("title") or "").casefold():
                    unexpected.append(
                        f"{stored_path.stem} row {number}: title does not contain "
                        f"the printed counterparty phrase {title_fragment!r}: "
                        f"{row.get('title')!r}")
                expected_dates = P5_BLOCK_DATE_PINS.get(
                    stored_path.stem, {}).get(number)
                if expected_dates is not None:
                    actual_dates = (row.get("signature"), row.get("entry_into_force"))
                    if actual_dates != expected_dates:
                        unexpected.append(
                            f"{stored_path.stem} row {number}: dates {actual_dates!r}, "
                            f"expected {expected_dates!r}")
            unused.discard(stored_path.stem)
            continue
        doubled, lost = audit["doubled"], audit["lost"]
        if doubled or lost:
            if stored_path.stem not in unused:
                unexpected.append(
                    f"{stored_path.stem}: {doubled} title cell(s) hold more than "
                    f"one printed number, and these printed numbers opened no "
                    f"row: {lost} - declare the slug in "
                    f"P5_CELL_MODEL_EXCEPTIONS or fix the reader")
            else:
                unused.discard(stored_path.stem)
    assert paired >= 1, "no stored artefact could be paired with a PDF"
    assert not unexpected, "\n".join(unexpected)
    _need(audited, "at least one legacy-read table to audit")
    assert not unused, (
        f"these slugs are declared in P5_CELL_MODEL_EXCEPTIONS but their title "
        f"cells now match the printed numbers: {sorted(unused)} - remove them "
        f"from the exception list")


def test_p05_published_positions_cannot_lag_the_reader(tmp_path):
    """Every published position is compared with the live reading, row by row.

    The determinism test beside this one already refuses a corpus that is not
    byte-identical to a fresh build, so a reader repair and a stale artefact
    cannot both stand - but a byte difference names only the file. This control
    asks the question a corpus cannot answer about itself: does each row the
    reader measures now still equal the row the artefact holds? It names every
    divergent row and field, so a repair that nobody rebuilt the corpus for
    fails here with the exact evidence of the drift.

    The comparator carries its own detector test. One real artefact is copied,
    its reading left alone (the control must be silent), its first title then
    mutated and its first row removed: the detector must report the mutated
    cell and the dropped row, so the green cannot be green by emptiness.
    """
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    entry = next((item for item in sources
                  if item["id"] == "mli-positions-batch"), None)
    _need(entry is not None and entry.get("dir"),
          "the source register declares the positions family")
    directory = ROOT / entry["dir"]
    if not directory.is_dir():
        pytest.skip("the MLI positions family is not in sources/, so there "
                    "is nothing to read")
    stored_dir = corpus.corpus_root(ROOT) / "mli" / "positions"
    if not any(stored_dir.glob("*.json")):
        pytest.skip("no stored position artefacts to audit")

    sample = None
    for path in sorted(stored_dir.glob("*.json")):
        if path.stem == "batch-report":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("covered_agreements"):
            sample = data
            break
    _need(sample is not None, "a published position with covered agreements")

    slug = sample["slug"]
    row = sample["covered_agreements"][0]
    probe = tmp_path / "stored"
    probe.mkdir()
    (probe / f"{slug}.json").write_text(json.dumps(sample, ensure_ascii=False),
                                        encoding="utf-8")
    clean = compare_published_rows(probe, {"positions": {slug: sample}})
    assert not (clean["changed"] or clean["only_in_artifact"]
                or clean["only_in_live"]), (
        "the drift detector reports a difference where the corpus and the "
        f"live reading are the same: {format_row_divergences(clean)}")
    mutated = json.loads(json.dumps(sample))
    mutated["covered_agreements"][0]["title"] = "a title the source does not print"
    detected = compare_published_rows(probe, {"positions": {slug: mutated}})
    assert detected["changed"] == [{
        "slug": slug, "row": row["no"], "field": "title",
        "stored": row["title"], "live": "a title the source does not print"}], (
        "the drift detector missed a mutated title cell: "
        f"{format_row_divergences(detected)}")
    del mutated["covered_agreements"][0]
    dropped = compare_published_rows(probe, {"positions": {slug: mutated}})
    assert dropped["only_in_artifact"] == [{"slug": slug, "row": row["no"]}], (
        "the drift detector did not notice a row the reader no longer measures: "
        f"{format_row_divergences(dropped)}")

    report = audit_published_artifacts(ROOT, directory, entry["id"])
    _need(report["published"],
          "the published positions compared with the live reading")
    divergences = format_row_divergences(report)
    assert not divergences, (
        "the corpus lags the reader - rebuild the positions so every row the "
        "reader measures is the row the corpus holds:\n"
        + "\n".join(divergences))


def _positions_family():
    """The declared MLI positions family: its register entry and its directory."""
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    entry = next((item for item in sources
                  if item["id"] == "mli-positions-batch"), None)
    _need(entry is not None and entry.get("dir"),
          "the source register declares the positions family")
    directory = ROOT / entry["dir"]
    if not directory.is_dir():
        pytest.skip("the MLI positions family is not in sources/, so there "
                    "is nothing to read")
    return entry, directory


def _stored_positions() -> list:
    """Every published position artefact, in the order the directory lists them."""
    stored = corpus.corpus_root(ROOT) / "mli" / "positions"
    return [path for path in sorted(stored.glob("*.json"))
            if path.stem != "batch-report"]


def test_p06_the_view_names_the_lists_the_artefact_holds():
    """A view cannot print a list row - or a whole list - its artefact does not.

    A reservation's own list of agreements is read from the page and kept in the
    artefact, and it is printed in the position's markdown view beside the rows
    it decides, because a list nobody can read where the rows are read is a list
    nobody checks. The two can fall apart the way every derived view can: the
    artefact is regenerated and the view stays behind. So this control reads each
    view back, list by list, statement by statement and row by row, and holds it
    against the artefact - including the second list of a statement that
    announces two, and an unread list, which the view has to say in the reader's
    own words rather than draw as an empty table.

    The register is checked with it, and not as a second count of the same
    number: `reservation_scope_lists` in the family's report must equal what the
    artefacts hold, and every announced list must be either read or named in
    `reservations_announcing_a_list_not_read`. An announcement in neither is the
    silent loss this invariant exists for.
    """
    artifacts = _stored_positions()
    _need(artifacts, "the MLI position artefacts (corpora/mli/positions/*.json)")
    views_dir = ROOT / "derived" / "markdown" / "mli" / "positions"
    problems: list[str] = []
    announced = read = 0
    multiple: list[tuple] = []
    for path in artifacts:
        record = json.loads(path.read_text(encoding="utf-8"))
        for article, entries in (record.get("article_sections") or {}).items():
            for statement, entry in enumerate(entries):
                lists = entry.get("scope_lists") or []
                announced += len(lists)
                read += sum(1 for one in lists if one.get("read"))
                if len(lists) > 1:
                    multiple.append((record.get("slug"), article,
                                     statement, len(lists)))
        view = views_dir / f"{path.stem}.md"
        if not view.is_file():
            problems.append(f"{path.name}: no derived view at "
                            f"{view.relative_to(ROOT).as_posix()}")
            continue
        problems.extend(f"{path.name} {line}" for line in
                        scope_view_divergences(
                            record, view.read_text(encoding="utf-8")))
    assert not problems, "\n".join(problems[:40])

    report = json.loads((corpus.corpus_root(ROOT) / "mli" / "positions"
                         / "batch-report.json").read_text(encoding="utf-8"))
    totals = report["reservation_scope_lists"]
    unread = report["reservations_announcing_a_list_not_read"]
    assert announced == totals["announced"], (
        f"the family's report counts {totals['announced']} announced list(s) "
        f"and the artefacts hold {announced}")
    assert read + len(unread) == announced, (
        f"{announced} list(s) are announced, {read} read and {len(unread)} "
        f"declared - the rest are announced and neither read nor named")
    assert totals["read"] == read, (
        f"the report says {totals['read']} list(s) were read, the artefacts "
        f"say {read}")
    named = {(item["slug"], str(item["article"]), item["lists"])
             for item in report["reservations_announcing_more_than_one_list"]}
    assert named == {(slug, article, count)
                     for slug, article, _statement, count in multiple}, (
        "the statements that announce more than one list are not the ones the "
        "family's report names")
    assert multiple, ("no statement in this corpus announces more than one "
                      "list, so the second-list case is not exercised anywhere")


def test_p06_a_row_the_page_leaves_empty_is_named_not_thinned():
    """A row whose cell came back empty is counted and named, never filled in.

    A list row is the page's own row, and a cell the reading could not attach to
    it is published empty - filled in from the row beside it would be a value the
    page does not print. A number alone would not be enough: a reading that lost
    a cell to a page break moves the count and nothing says which row it left, so
    the family's report names the row (its page, its number, and which cell) and
    this holds the names against the artefacts row by row, then holds their
    number against the counts the same report publishes.

    The family has one such row today - Chile's Article 3 list row 33, where the
    page prints a single `Article 1(2)` between rows 33 and 34 and the row the
    cell stands nearest keeps it - and the test does not require the number to be
    one: it requires the number and the names to be the same fact, so a corpus
    with none passes and a corpus with a new one fails until it is declared.
    """
    artifacts = _stored_positions()
    _need(artifacts, "the MLI position artefacts (corpora/mli/positions/*.json)")
    live: list[tuple] = []
    for path in artifacts:
        record = json.loads(path.read_text(encoding="utf-8"))
        for article, entries in (record.get("article_sections") or {}).items():
            for entry in entries:
                for one in entry.get("scope_lists") or []:
                    for row in one.get("rows") or []:
                        empty = tuple(field for field in ("other_jurisdiction",
                                                          "text")
                                      if not (row.get(field) or "").strip())
                        if empty:
                            live.append((record.get("slug"), str(article),
                                         row.get("page"), row.get("no"), empty))
    report = json.loads((corpus.corpus_root(ROOT) / "mli" / "positions"
                         / "batch-report.json").read_text(encoding="utf-8"))
    named = report.get("reservation_scope_rows_with_an_empty_cell")
    assert named is not None, (
        "the family's report says nothing about rows with an empty cell, so a "
        "row that lost a cell is only a smaller number")
    held = {(item.get("slug"), str(item.get("article")), item.get("page"),
             item.get("no"), tuple(item.get("fields") or []))
            for item in named}
    assert held == set(live), (
        f"the artefacts publish {len(live)} row(s) with an empty cell and the "
        f"family's report names {len(named)}: named and not published "
        f"{sorted(held - set(live))}, published and not named "
        f"{sorted(set(live) - held)}")
    totals = report["reservation_scope_lists"]
    assert len(live) == (totals["rows_without_a_counterparty"]
                         + totals["rows_without_a_text"]), (
        f"the report counts {totals['rows_without_a_counterparty']} row(s) "
        f"without a counterparty and {totals['rows_without_a_text']} without a "
        f"text, and the artefacts publish {len(live)} empty cell(s) in all")
    for _slug, _article, _page, _no, fields in live:
        assert fields and all(field in ("other_jurisdiction", "text")
                              for field in fields), (
            f"a named empty cell is not one of the list's own cells: {fields}")


def test_p06_the_view_control_catches_a_stale_list():
    """The control bites: a view with a list the artefact does not hold fails.

    The sample is rendered by the same renderer the corpus uses - the real
    renderer on invented content, never invented markdown - and then corrupted in
    each way a stale list view goes stale: a row the artefact does not hold, a
    row the view dropped, a cell the page did not print, a second list that the
    view lost, and a reason where the artefact read the table.
    """
    record = {"slug": "probe", "country": "Probe",
              "covered_agreements": [],
              "article_sections": {
                  "7": [{"kind": "Reservation", "page": 4, "scope_lists": [
                      {"read": True, "page": 4,
                       "headings": ["Listed Agreement Number"],
                       "split_x": 100.0,
                       "rows": [{"no": 1, "page": 4,
                                 "other_jurisdiction": "Chile",
                                 "text": "Article 24(6)"},
                                {"no": 2, "page": 4,
                                 "other_jurisdiction": "Mexico",
                                 "text": "Article 28(7)"}],
                       "rows_without_a_counterparty": 0,
                       "rows_without_a_text": 0},
                      {"read": True, "page": 4,
                       "headings": ["Listed Agreement Number"],
                       "split_x": 100.0,
                       "rows": [{"no": 2, "page": 4,
                                 "other_jurisdiction": "Mexico",
                                 "text": "Article 28(1) through (5)"}],
                       "rows_without_a_counterparty": 0,
                       "rows_without_a_text": 0}]}]},
              "qa": {"scope_lists": {"announced": 2, "read": 2, "rows": 3,
                                    "rows_without_a_counterparty": 0,
                                    "rows_without_a_text": 0,
                                    "options_announcing_more_than_one_list": 1,
                                    "not_read": []}}}
    fresh = view_writer.position_view(record)
    assert scope_view_divergences(record, fresh) == []
    assert "list 2 of 2" in fresh
    assert scope_view_divergences(
        record, fresh.replace("Article 24(6)", "Article 24(7)")) == [
            "Article 7 list 1 row 1 text: the view names 'Article 24(7)', "
            "the artefact holds 'Article 24(6)'"]
    dropped = "\n".join(line for line in fresh.splitlines()
                        if not line.startswith("| 1 ")) + "\n"
    assert scope_view_divergences(record, dropped) == [
        "Article 7 list 1: rows [] named by the view are not in the artefact "
        "and [1] are missing"]
    # A whole list going missing is the failure this invariant exists for, and
    # a view that loses the second one is caught by the list count.
    second = ("### Article 7 — the list under the reservation on page 4, "
              "list 2 of 2")
    assert second in fresh
    assert scope_view_divergences(record, fresh.split(second)[0]) == [
        "the view prints 1 announced list(s), the artefact holds 2"]
    # An unread list is a fact the view has to say in words, with the reader's
    # own reason; drawing a table there is a claim the artefact does not make.
    unread = json.loads(json.dumps(record))
    unread["article_sections"]["7"][0]["scope_lists"][1] = {
        "read": False, "page": 4,
        "reason": "the statement announces a list of agreements and no table "
                  "is printed under that sentence"}
    unread_view = view_writer.position_view(unread)
    assert scope_view_divergences(unread, unread_view) == []
    assert "was not read: the statement announces a list" in unread_view
    # And the inverse: an artefact that read the table read by a view that
    # declares it unread is a claim the artefact makes nowhere.
    assert scope_view_divergences(unread, fresh) == [
        "Article 7 list 2: the view gives the reason None, the artefact holds "
        "'the statement announces a list of agreements and no table is "
        "printed under that sentence'"]


def test_p06_the_lists_are_the_tables_the_page_prints():
    """Every announced list the corpus holds is held against its own page.

    Three things the reading cannot answer about itself: whether the statement's
    own published prose announces as many lists as the artefact holds (the second
    table of a two-list statement is exactly the one a reading loses in silence);
    whether every row number is printed on the row's own page as the number that
    opens its line; and whether every word of every published cell is on the page
    the row was read from, because a cell is assembled from the page's spans and a
    word that is nowhere on the page was not read but written.

    The control states what it does not ask as well: it does not hold the page
    for a row the corpus dropped, because that needs the table's extent and a page
    can carry two tables under the same headings (Argentina's page 15 prints its
    Article 13 reservation's table and, below it, a notification's). The counts it
    did check are asserted not to be empty, so a green cannot be green by having
    read nothing.
    """
    entry, directory = _positions_family()
    stored = _stored_positions()
    _need(stored, "the MLI position artefacts to audit")
    result = audit_scope_lists(ROOT, directory, entry["id"])
    assert result["checked"]["lists"] and result["checked"]["rows"], (
        f"the page control measured nothing: {result['checked']}")
    assert not result["divergences"], "\n".join(
        result["divergences"][:40])


def test_p06_the_page_control_catches_an_invented_row(tmp_path):
    """The page control bites: an invented row and cell are named with the page.

    Built from one real artefact, whose family report is copied to name that
    document alone, so the control reads one PDF and not the family: the reading
    of the other 102 documents is not what is under test here. Two things are
    corrupted - a counterparty no page prints and a whole row the page does not
    print - and both have to be reported, because a control that only caught the
    cell would pass a corpus that invented rows wholesale.
    """
    entry, directory = _positions_family()
    stored = corpus.corpus_root(ROOT) / "mli" / "positions"
    report = json.loads((stored / "batch-report.json").read_text(encoding="utf-8"))
    record = json.loads((stored / "andorra.json").read_text(encoding="utf-8"))
    document = next((item for item in report["documents"]
                     if item.get("slug") == "andorra"), None)
    _need(document is not None and document.get("file"),
          "the family's report names the Andorra document")
    entry_with_a_list = next(
        one for entries in record["article_sections"].values()
        for statement in entries for one in statement.get("scope_lists") or [])
    rows = entry_with_a_list["rows"]
    page = rows[0]["page"]
    rows[0]["other_jurisdiction"] = "Invention"
    rows.append({"no": 99, "page": page, "other_jurisdiction": "Invention",
                 "text": "Article 99"})
    fake = tmp_path / "root"
    positions = fake / "corpora" / "mli" / "positions"
    positions.mkdir(parents=True)
    (positions / "batch-report.json").write_text(
        json.dumps({"documents": [document]}), encoding="utf-8")
    (positions / "andorra.json").write_text(json.dumps(record),
                                            encoding="utf-8")
    result = audit_scope_lists(fake, directory, entry["id"])
    assert result["checked"]["positions"] == 1, (
        f"the control read {result['checked']['positions']} document(s), not "
        f"the one the report names")
    found = "\n".join(result["divergences"])
    assert "'Invention'" in found, (
        f"the control did not name the invented cell: {found}")
    assert "row 99" in found, (
        f"the control did not name the row the page does not print: {found}")


def test_m1_every_title_is_the_sources_title():
    """The row's number and title are on the page, and the register covers it.

    Three things are checked, and each of them is a way a mapping goes wrong:

    * the source is the source this mapping was built from (a changed hash is a
      changed document, and a mapping checked against the wrong document is
      worse than an unchecked one);
    * every title in the artefact appears in the source's own words on the page
      the row names - so no title was typed, however plausible it looks;
    * a declaration exists for every Article the source prints, and no
      declaration exists for an Article it does not, so the file that carries the
      modes and targets cannot be short one - or long one.
    """
    data = _mapping()
    entry = _mapping_source()
    digest = hashlib.sha256(Path(entry["pdf"]).read_bytes()).hexdigest()
    assert data["sha256"] == digest, (
        f"{entry['id']}: the source changed - the mapping was built from "
        f"{data['sha256'][:16]} and the bytes here are {digest[:16]}; rebuild the "
        f"mapping and re-read what it says about the new text")

    words = _source_words(str(entry["pdf"]), entry["id"])
    rows = data["rows"]
    numbers = [int(row["article"]) for row in rows]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the mapping's Articles are {numbers}, and the Convention numbers its "
        f"Articles 1..39 without a gap")
    absent = [row["article"] for row in rows
              if row["title"] not in words.get(row["page"], "")]
    assert not absent, (
        "these titles are not on the page the mapping names, so they were not "
        f"read from the source: {absent}")

    register = _mapping_register()
    declared = {str(row.get("article")) for row in register.get("articles") or []}
    missing = sorted(set(str(number) for number in numbers) - declared, key=int)
    extra = sorted(declared - {str(number) for number in numbers}, key=int)
    assert not missing and not extra, (
        f"{mli_writer.MAPPING_REGISTER} and the source do not cover the same "
        f"Articles: declared and not printed {extra}, printed and not declared "
        f"{missing}")

    unknown = sorted({str(row.get("mode")) for row in register.get("articles") or []}
                     - set(mli_writer.MAPPING_MODES))
    assert not unknown, (f"a mode outside the declared vocabulary: {unknown}; the "
                         f"vocabulary is {', '.join(mli_writer.MAPPING_MODES)}")


def test_m1_targets_are_articles_of_the_base_text():
    """Every target names an Article the base text this corpus holds prints.

    The mapping is a mapping *to this corpus*: a target that resolves to no
    Article of the Model is a reading of a different document. Each group of
    alternatives has to resolve in each edition, because the corpus holds both
    and a target that resolves in neither is a target nobody can follow.
    """
    data = _mapping()
    editions = corpus.editions(ROOT)
    _need(editions, "the base text (corpora/<family>/<edition>/)")
    articles = {}
    for family, edition in editions:
        found = corpus.akn(ROOT, family, edition)
        if not found:
            continue
        articles[f"{family}/{edition}"] = set(corpus.eids(found[0],
                                                          tags=("article",)))
    _need(articles, "an AKN document to read the base text's Articles from")

    problems: list[str] = []
    for row in data["rows"]:
        for group in row["targets"]:
            for edition, eids in articles.items():
                if not any(f"art_{target}" in eids for target in group):
                    problems.append(
                        f"art. {row['article']}: targets {group} name no Article of "
                        f"{edition}")
    assert not problems, (
        "the mapping names Articles the base text does not print:\n  "
        + "\n  ".join(problems))


def test_m1_articles_without_options_are_absent_from_the_positions():
    """The declared option-less Articles are checked against the positions built.

    This is the one claim in the mapping about the position documents rather than
    about the Convention, and it is checked the other way round from the numbers:
    the claim is that a reservation, notification or choice cannot appear on these
    Articles, so a position document that shows one has been read wrong. The test
    names how many documents it looked at, because a claim checked against none
    of them is not checked.
    """
    data = _mapping()
    declared = set(str(number) for number in data["qa"]["articles_without_options"])
    assert declared, "the mapping declares no option-less Article at all"
    positions = sorted((ROOT / "corpora/mli/positions").glob("*.json"))
    _need(positions, "a position document (corpora/mli/positions/<slug>.json)")
    sections = {}
    for path in positions:
        document = corpus.load_json(path)
        sections[path.stem] = {str(number) for number in
                               (document.get("article_sections") or {})}
    shown = sorted({number for found in sections.values() for number in found})
    assert shown, ("no position document shows an Article section, so the claim "
                   "that some Articles take no option is vacuous here")
    wrong = sorted(({number for found in sections.values() for number in found}
                    & declared), key=int)
    assert not wrong, (
        f"Articles {wrong} are declared to take no reservation, notification or "
        f"choice, and a position document shows one: "
        + ", ".join(f"{slug}: {sorted(sections[slug] & declared, key=int)}"
                    for slug in sections if sections[slug] & declared))
    # And the modes have to agree with the claim: an Article that replaces treaty
    # provisions is one a position can take an option on.
    modes = {str(row["article"]): row["mode"] for row in data["rows"]}
    contradiction = sorted((article for article in declared
                            if modes.get(article) not in ("none", "admin")), key=int)
    assert not contradiction, (
        f"Articles {contradiction} are declared option-less and are declared to "
        f"replace treaty provisions as well")
    assert len(positions) >= 1


def test_m6_the_title_is_the_documents_own_opening():
    """The title a position publishes is a printed line of the document.

    `mli._jurisdiction_clue` reads page 0's body lines and takes the one that
    names a jurisdiction the corpus knows - the jurisdictions register's names
    and aliases, and the signatories table's - at the largest font size (ties
    to the topmost). The corpus this repository holds was written by the same
    reading, so its 103 `title_read` fields must match byte for byte. A
    document whose own opening names no jurisdiction reads as empty and is
    published that way: the corpus states what the page says, it does not take
    the jurisdiction from the publisher's file name.
    """
    sources = corpus.declared_sources(ROOT)
    _need(sources, "the source register (provenance/sources.yaml)")
    entry = next((item for item in sources
                  if item["id"] == "mli-positions-batch"), None)
    _need(entry is not None and entry.get("dir"),
          "the source register declares the positions family")
    directory = ROOT / entry["dir"]
    if not directory.is_dir():
        pytest.skip("the MLI positions family is not in sources/, so there "
                    "is nothing to read")
    stored_dir = corpus.corpus_root(ROOT) / "mli" / "positions"
    if not any(stored_dir.glob("*.json")):
        pytest.skip("no stored position artefacts to compare the reading with")

    sha_map = {}
    for pdf in sorted(directory.glob("*.pdf")):
        sha_map[hashlib.sha256(pdf.read_bytes()).hexdigest()] = pdf

    mismatched, errors, compared = [], [], 0
    for stored_path in sorted(stored_dir.glob("*.json")):
        if stored_path.stem == "batch-report":
            continue
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        pdf = sha_map.get(stored.get("sha256", ""))
        if pdf is None:
            errors.append(f"{stored_path.stem}: no PDF with this artefact's sha256")
            continue
        book = ledger.Classifier.classify(
            ledger.SpanStream.read(pdf, "mli-positions-batch"), ledger.Ledger())
        clue, title_read, _authority = mli_writer._jurisdiction_clue(
            mli_writer._body_lines(book),
            sorted([span for span, _rule in book.kept],
                   key=lambda span: (span.page, span.y, span.x)), book)
        compared += 1
        if title_read != stored.get("title_read"):
            mismatched.append(
                f"{stored_path.stem}: stored {stored.get('title_read')!r}, "
                f"the line reader gives {title_read!r}")
    assert compared >= 1, "no stored artefact could be paired with a PDF"
    assert not errors, "; ".join(errors)
    assert not mismatched, (
        "the title reader and the stored corpus disagree:\n" + "\n".join(mismatched))
