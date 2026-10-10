"""Command line: `python -m harness [status|probes|report|ledger|drift]`.

Exit codes matter (they are read by CI and by humans in a hurry):

  0  nothing is wrong in what could be evaluated
  1  a probe fired in this repository
  2  the invocation itself was wrong

Note what is *not* an error: `NOT-EVALUATED`. An artefact that does not exist
yet is not a failure of the artefact; it is a statement that the harness cannot
speak. Only `tests/` decides what a missing artefact means, and it says so
loudly rather than passing quietly.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import (akn, corpus, diff, drift, ledger, mli, report, views)


def _cmd_status(args) -> int:
    print(corpus.summary(Path(args.root) if args.root else None))
    rows = report.probe_rows(Path(args.root) if args.root else None)
    c = report.counts(rows)
    print(f"probes: {len(rows)} — {c[report.ABSENT]} absent, "
          f"{c[report.PRESENT]} present, {c[report.NOT_EVALUATED]} not evaluated")
    return 1 if c[report.PRESENT] else 0


def _cmd_probes(args) -> int:
    rows = report.probe_rows(Path(args.root) if args.root else None)
    present = 0
    for r in rows:
        flag = report.VERDICT_ICON[r["verdict"]]
        print(f"[{flag:>7}] {r['id']}  ({r['invariant']})")
        if r["verdict"] != report.NOT_EVALUATED:
            print(f"          {r['detail']}")
        present += r["verdict"] == report.PRESENT
    return 1 if present else 0


def _pdf_for(source: str):
    """The PDF of a source, looked up in the register rather than guessed."""
    import yaml

    register = corpus.register()
    if not register.exists():
        return None
    for entry in yaml.safe_load(register.read_text(encoding="utf-8")) or []:
        if entry.get("id") == source and entry.get("file"):
            path = corpus.ROOT / entry["file"]
            return path if path.is_file() else None
    return None


def _declaration(source: str) -> dict:
    """What the register says is built from a source. `{}` if it says nothing."""
    return next((entry for entry in corpus.declared_sources()
                 if entry["id"] == source), {})


def _cmd_ledger(args) -> int:
    source = args.source or "un-model-2017"
    declaration = _declaration(source)
    if declaration.get("dir"):
        return _ledger_family(args, source, declaration)
    pdf = _pdf_for(source)
    if pdf is None:
        print(f"no PDF in sources/ for {source!r}: fetch it first, then this "
              f"command reads and classifies it", file=sys.stderr)
        return 2
    what = declaration.get("produces")
    try:
        spans = ledger.SpanStream.read(pdf, source)
        book = ledger.Classifier.classify(spans, ledger.Ledger())
    except ledger.RuleError as exc:
        print(f"cannot classify {source}: {exc}", file=sys.stderr)
        return 2
    print(ledger.audit_report(book), end="")

    if what == "table":
        return _ledger_table(args, source, pdf, book)
    if what == "positions":
        return _ledger_positions(args, source, pdf, book)
    if what == "mapping":
        return _ledger_mapping(args, source, pdf, book)

    try:
        projection = ledger.Projection.build(book.kept, source, book)
    except ledger.RuleError as exc:
        # Not every source is a marked-up document, and the register says which
        # are. A source that is read but has no projection is reported as read.
        print(f"projection: none declared for {source} "
              f"(produces={what or 'undeclared'}) - {exc}")
        return 2 if (what != "none" or args.write) else 0
    ok, detail = ledger.verify_roundtrip(projection, book, source)
    print(f"round-trip: {'exact' if ok else 'FAILED'} - {detail}")
    if args.write:
        target, akn_path, _manifest, documents = _write_corpus(
            source, book.spans, book, projection)
        print(f"written: {target}")
        print(f"         {akn_path.name}: {akn.describe(ET.parse(akn_path).getroot())}")
        print(f"         views: {len(documents)} document(s) in derived/markdown")
    return 0 if ok else 1


def _ledger_table(args, source: str, pdf, book) -> int:
    """The account of a source whose corpus artefact is a table.

    A table has no round-trip through a projection, so it is checked by its own
    accounts instead: how many rows the source printed, whether their numbers run
    without a gap, and whether the column headings were left out of the data (a
    heading is furniture; a jurisdiction is not). Those are the S1 and S2
    invariants, and printing them here is what lets a reader see the table's
    three judgement calls from the artefact's own `qa` block.
    """
    data = mli.signatories(book, source, "")
    numbers = [row["no"] for row in data["rows"]]
    contiguous = numbers == list(range(1, len(numbers) + 1))
    print(f"table: {len(numbers)} rows, numbering "
          f"{'contiguous 1..%d' % len(numbers) if contiguous else 'HAS GAPS'}")
    print(f"status as of: {data['status_as_of']['printed']!r} "
          f"-> {data['status_as_of']['date']!r}")
    decided = data["qa"]["cells_where_the_two_placements_disagree"]
    print(f"cells the two placements disagree about: {len(decided)}")
    for cell in decided:
        print(f"  row {cell['no']:>3} page {cell['page']} {cell['column']:<20} "
              f"{cell['distance_to_number_pt']:>6.2f}pt from its number, "
              f"{cell['nearest_distance_pt']:>6.2f}pt from {cell['nearest_number']}"
              f"  ({cell['decided_by']})  {cell['text']!r}")
    if not args.write:
        return 0 if contiguous else 1
    artefact = _declaration(source).get("artefact") or ""
    target = (corpus.ROOT / artefact).parent if artefact else corpus.corpus_root() / "mli"
    written = mli.write(target, book, source, pdf)
    print(f"written: {written[0]}")
    if source == "mli-signatories-and-parties":
        # The signatories view is written from the artefact just published, so
        # the view and the corpus are one answer and not two readings.
        for view in views.write_signatories(corpus.ROOT / corpus.DERIVED,
                                            written[0]):
            print(f"         view: {view.relative_to(corpus.ROOT).as_posix()}")
    return 0 if contiguous else 1


def _ledger_mapping(args, source: str, pdf, book) -> int:
    """The account of a source whose corpus artefact is the mapping.

    The account is the mapping's own claims: how many Articles were read from the
    source, whether their numbering runs without a gap, which titles the source
    runs onto a second line, and what the rows are made of - because the way this
    artefact can be wrong is not by misreading a table but by asserting a mode or
    a target the sources do not support, and those are counted here.
    """
    from collections import Counter

    data = mli.mapping(book, source, "")
    rows = data["rows"]
    numbering = data["qa"]["numbering"]
    contiguous = numbering["runs_from_one_without_a_gap"]
    print(f"mapping: {len(rows)} Articles, numbering "
          f"{numbering['first']}..{numbering['last']} "
          f"{'contiguous' if contiguous else 'HAS GAPS'}")
    modes = Counter(row["mode"] for row in rows)
    print("modes: " + ", ".join(f"{mode}={count}"
                                 for mode, count in sorted(modes.items())))
    with_targets = [row for row in rows if row["targets"]]
    print(f"rows naming a base-text Article: {len(with_targets)} of {len(rows)}"
          f" (the rest act on the treaty as a whole or on the Convention itself)")
    for row in rows:
        if row["targets"]:
            alternatives = " or ".join(", ".join(group) for group in row["targets"])
            print(f"  art. {row['article']:>2} {row['mode']:<19} -> {alternatives}")
    for wrapped in data["qa"]["titles_that_run_onto_a_second_line"]:
        print(f"  art. {wrapped['article']:>2} title runs onto a second line "
              f"(page {wrapped['page']}): {wrapped['title']!r}")
    print(f"declared without options: "
          f"{', '.join(data['qa']['articles_without_options'])}")
    if not args.write:
        return 0 if contiguous else 1
    artefact = _declaration(source).get("artefact") or ""
    target = (corpus.ROOT / artefact).parent if artefact else corpus.corpus_root() / "mli"
    written = mli.write(target, book, source, pdf)
    print(f"written: {written[0]}")
    return 0 if contiguous else 1


def _ledger_family(args, source: str, declaration: dict) -> int:
    """The account of a source that is a directory of documents, read in one pass.

    The family's account is its own: how many documents the register declares,
    how many were read, which were not and why, and which documents claimed one
    jurisdiction. What it prints is that account rather than a line per document,
    because the documents are 110 and the interesting question is the four
    numbers at the top.
    """
    directory = corpus.ROOT / declaration["dir"]
    if not directory.is_dir():
        print(f"{declaration['dir']} is not here: fetch the family first",
              file=sys.stderr)
        return 2
    # The writer takes the corpus' MLI root and puts the positions under it, the
    # same convention the single-document writer uses: where the family's files go
    # is the corpus' layout decision, and `corpus.POSITION_REPORT` is its declared
    # name for the family's own account.
    target = corpus.corpus_root() / "mli"
    if args.write:
        written, report = mli.write_family(target, directory, source, corpus.ROOT)
        # The position views are written from the artefacts `write_family` has
        # just published, so the view and the corpus are one answer and not two
        # readings of the same PDFs.
        views_written = views.write_positions(corpus.ROOT / corpus.DERIVED,
                                              target / "positions")
    else:
        data = mli.family(directory, source, corpus.ROOT)
        written, report, views_written = [], data["report"], []
    print(f"family: {report['declared']} document(s) declared in "
          f"{report['directory']}")
    print(f"read:   {report['read']}")
    print(f"unread: {len(report['unread'])}")
    for item in report["unread"]:
        print(f"  {item['file']}: {item['reason']}")
    shared = report["jurisdictions_with_more_than_one_document"]
    print(f"published: {report['published']} position(s) for "
          f"{len(shared)} jurisdiction(s) with more than one document")
    for item in shared:
        others = [p for p in item["published_as"] if p["slug"] != item["slug"]]
        print(f"  {item['slug']}: {item['position']} is the position"
              + ("".join(f", {p['file']} published as {p['slug']}" for p in others)
                 or ", and no other document could be published"))
    for item in report["unresolved"]:
        print(f"  UNRESOLVED {item['file']}: {item['reason']}")
    resolved: dict = {}
    for document in report["documents"]:
        resolved[document["resolved_from"]] = \
            resolved.get(document["resolved_from"], 0) + 1
    for how, count in sorted(resolved.items()):
        print(f"  resolved by {how}: {count}")
    if written:
        print(f"written: {len(written) - 1} position(s) and "
              f"{written[-1].relative_to(corpus.ROOT)}")
        if views_written:
            print(f"         views: {len(views_written)} document(s) in "
                  f"{views_written[0].parent.relative_to(corpus.ROOT).as_posix()}")
    return 0


def _ledger_positions(args, source: str, pdf, book) -> int:
    """The account of a source whose corpus artefact is a country's position.

    A position is prose and a table together, so it is checked by both of its own
    accounts: how many options it holds with what kinds, how long its longest
    excerpt is, and whether the covered agreements' numbering runs without a gap
    in the artefact that was built from it. The last is the one that has to hold:
    a numbering with a hole in it is a jurisdiction the corpus cannot answer a
    question about.
    """
    data = mli.position(book, source, pdf)
    options = [option for section in data["article_sections"].values()
               for option in section]
    kinds = sorted({option["kind"] for option in options})
    longest = max((len(option["excerpt"]) for option in options), default=0)
    print(f"position: {data['country']!r} -> {data['slug']} "
          f"({'a second document about ' + data['base_slug'] if data['is_companion'] else 'a jurisdiction'})")
    print(f"sections: {len(data['article_sections'])}, options: {len(options)}, "
          f"kinds: {', '.join(kinds)}")
    print(f"excerpts: longest {longest} characters, none truncated "
          f"({sum(1 for option in options if option['excerpt'])} with text)")
    covered = data["qa"].get("covered_agreements") or {}
    if covered.get("read"):
        numbering = covered.get("numbering") or {}
        print(f"covered agreements: {data['n_covered']} rows, "
              f"numbering {numbering.get('first')}..{numbering.get('last')}, "
              f"{'contiguous' if numbering.get('runs_from_one_without_a_gap') else 'HAS GAPS'}")
        print(f"rows delimited by {covered.get('rows_delimited_by')}")
        for row in covered.get("numbered_rows_without_a_number") or []:
            print(f"  a cell with no number, kept with the row above: {row['text']!r}")
    else:
        print(f"covered agreements: not read - {covered.get('reason', 'no table')}")
    if not args.write:
        return 0
    # Every position is written under `corpora/mli/positions/`, under the slug the
    # projection measured, so the writer is given the corpus' MLI root and not the
    # declared path of one file.
    written = mli.write(corpus.corpus_root() / "mli", book, source, pdf)
    print(f"written: {written[0]}")
    return 0


def _write_corpus(source: str, spans: list, book, projection) -> tuple:
    """Write everything one edition's corpus is made of, from one projection.

    The ledger, the node index, the AKN document, its manifest and the markdown
    view are all functions of the same projection, written in one pass. The
    views are not written from the PDF a second time: two readings of one source
    are two answers to a question the ledger has already answered once (F9).
    """
    import json

    family, _, edition = source.rpartition("-")
    target = corpus.corpus_root() / family / edition
    target.mkdir(parents=True, exist_ok=True)
    header, rows = ledger.ledger_records(spans, book)
    dump = lambda record: json.dumps(record, sort_keys=True, ensure_ascii=False)
    (target / f"model-{edition}.spans.jsonl").write_text(
        dump(header) + "\n" + "".join(dump(row) + "\n" for row in rows),
        encoding="utf-8")
    (target / f"model-{edition}.nodes.jsonl").write_text(
        "".join(dump(record) + "\n"
                for record in ledger.node_records(projection, spans)),
        encoding="utf-8")
    akn_path, manifest_path = akn.write(target, source, family, edition,
                                       projection, book)
    documents = views.write(corpus.ROOT / corpus.DERIVED, source, family,
                            edition, projection, book)
    return target, akn_path, manifest_path, documents


def _cmd_diff(args) -> int:
    """The edition diff: a view of two editions of one family.

    Its inputs are the two editions the corpus holds, never the two PDFs. The
    default pair is the family's oldest and newest declared edition, which is
    what "what changed between the editions" means for a family that has two.
    """
    family = args.family or "un-model"
    declared = [edition for name, edition in corpus.editions() if name == family]
    old = args.old or (declared[0] if declared else "")
    new = args.new or (declared[-1] if len(declared) > 1 else "")
    if not family or not old or not new or old == new:
        print(f"cannot diff: {family} declares {declared or 'no editions'}",
              file=sys.stderr)
        return 2
    try:
        data = diff.compare(family, old, new)
    except (ValueError, FileNotFoundError) as exc:
        print(f"cannot diff {family} {old}→{new}: {exc}", file=sys.stderr)
        return 2
    counts, units = data["counts"], data["units"]
    print(f"{family} {old} → {new}: {counts['articles']} Articles · "
          f"added {counts['added']} · removed {counts['removed']} · "
          f"modified {counts['modified']} · unchanged {counts['unchanged']}")
    print(f"units: {units['changed']} changed, {units['added']} added, "
          f"{units['removed']} removed · notes {units['notes_changed']} changed, "
          f"{units['notes_added']} added, {units['notes_renumbered']} renumbered")
    for article in data["added"]:
        print(f"  added    Article {article['number']} — {article['heading']}")
    for article in data["removed"]:
        print(f"  removed  Article {article['number']} — {article['heading']}")
    if not args.write:
        return 0
    for path in diff.write(corpus.ROOT / corpus.DERIVED, family, old, new):
        print(f"written: {path}")
    return 0


def _cmd_drift(args) -> int:
    """Compare the published corpus with a fresh reading, unit by unit.

    Exit 1 when the corpus and the reader disagree, so this is a control and not
    a report. With `--write` the divergent artefacts are republished from the
    fresh reading - only those, and only after their differences have been
    printed - so the repair is the smallest one the drift allows. With `--body`
    the same differences are printed as a pull request body, which is the shape
    the automated control (`.github/workflows/corpus-drift.yml`) opens its
    request from; `--body` writes nothing. With `--check-schema` the differences
    are not printed at all: every unit is checked to name a line or a field and
    never a byte count, so the material the request would carry is legible
    before it is opened. An artefact the register declares but nothing builds is
    printed and never quietly deleted, and a provenance hash that no longer
    matches the bytes on disk is reported and never rewritten by `--write` - it
    is a deliberate edit, not a regeneration.
    """
    import shutil

    root = Path(args.root) if args.root else corpus.ROOT
    result = drift.compare_corpus(root)
    if args.check_schema:
        violations = drift.schema_violations(result)
        for line in violations:
            print(line)
        print(f"{len(violations)} unit(s) name a size instead of a line in "
              f"{result['compared']} artefact(s) compared")
        shutil.rmtree(result["workdir"], ignore_errors=True)
        return 1 if violations else 0
    if args.title:
        print(drift.pr_title(result))
    elif args.body:
        print(drift.pr_body(result), end="")
    else:
        for item in result["differences"]:
            for line in drift.format_difference(item):
                print(line)
        for relative in result["published_but_unbuilt"]:
            print(f"published but nothing in the register builds it: {relative}")
        print(f"{result['compared']} artefact(s) compared, "
              f"{len(drift.divergent_artifacts(result))} divergent, "
              f"{result['provenance']} provenance difference(s)")
    if not args.write:
        shutil.rmtree(result["workdir"], ignore_errors=True)
        return 1 if (result["differences"] or result["published_but_unbuilt"]) else 0
    for item in drift.divergent_artifacts(result):
        target = root / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result["live"][item["path"]].read_bytes())
        print(f"republished: {item['path']}")
    shutil.rmtree(result["workdir"], ignore_errors=True)
    return 1 if (result["published_but_unbuilt"] or result["provenance"]) else 0


def _cmd_report(args) -> int:
    root = Path(args.root) if args.root else None
    if args.write:
        path = report.write(root)
        print(f"written: {path}")
    else:
        print(report.render(root), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness",
        description="Fidelity harness for international-tax-law-corpus.")
    parser.add_argument("command", nargs="?",
                        choices=("status", "probes", "report", "ledger",
                                 "diff", "drift"),
                        default=None)
    parser.add_argument("--source",
                        help="ledger: which source to read, by register id")
    parser.add_argument("--family", help="diff: which corpus family to compare")
    parser.add_argument("--from-edition", dest="old",
                        help="diff: the earlier edition (default: the oldest)")
    parser.add_argument("--to-edition", dest="new",
                        help="diff: the later edition (default: the newest)")
    parser.add_argument("--root", help="evaluate against another project root")
    parser.add_argument("--write", action="store_true",
                        help="report: write docs/harness-status.md; "
                             "drift: republish only the divergent artefacts")
    parser.add_argument("--body", action="store_true",
                        help="drift: print the differences as a pull request "
                             "body instead of the plain report; writes nothing")
    parser.add_argument("--title", action="store_true",
                        help="drift: print the pull request title the automated "
                             "control would use; writes nothing")
    parser.add_argument("--check-schema", dest="check_schema",
                        action="store_true",
                        help="drift: fail if any difference unit names a size "
                             "instead of a line or a field; writes nothing")
    args = parser.parse_args(argv)
    # `--write` only makes sense for the report and `--body`/`--title`/
    # `--check-schema` only for the drift control, so any of them selects its
    # command.
    command = args.command or (
        "drift" if (args.body or args.title or args.check_schema)
        else "report" if args.write else "status")
    return {"status": _cmd_status, "probes": _cmd_probes,
            "report": _cmd_report, "ledger": _cmd_ledger,
            "diff": _cmd_diff, "drift": _cmd_drift}[command](args)


if __name__ == "__main__":
    raise SystemExit(main())
