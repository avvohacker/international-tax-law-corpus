"""The status board: what the harness currently knows, and what it does not.

Two rules govern this module, both of them lessons about claim honesty
(invariant F12):

1. every number in a document is produced by a command, never copied by hand -
   so this file *is* the document generator, and `docs/harness-status.md` is
   written by `python -m harness --write`;
2. "not evaluated" is never printed as "passed". A probe whose target does not
   exist yet is reported as NOT-EVALUATED, and it fails its test by saying so.

The three verdicts a probe can have in this repository:

  ABSENT          the probe ran here and the defect is not present in the corpus
  PRESENT         the defect is here, with file and line
  NOT-EVALUATED   the artefact does not exist yet, so the probe cannot speak
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from harness import corpus
from harness.checks import Result, evaluate
from harness.defects import load_defects, load_invariants

ABSENT = "ABSENT"
PRESENT = "PRESENT"
NOT_EVALUATED = "NOT-EVALUATED"

VERDICT_ICON = {ABSENT: "ok", PRESENT: "DEFECT", NOT_EVALUATED: "·"}

# Printed when `pyproject.toml` cannot be read. The project's name is not a
# fact about the machine that built the board, and the directory the corpus was
# cloned into is (F14: an artefact must not describe the machine that built it).
PROJECT_NAME = "international-tax-law-corpus"


def project_name(root: Path) -> str:
    """The project's own name, read from the manifest at ``root``.

    Not ``root.name``: a clone called ``corpus`` in CI, ``my-corpus`` on one
    desk and ``corpus-2`` on another would print three different boards from one
    repository, and none of the three tells a reader which project the board is
    about. The name in `pyproject.toml` is the one that travels.
    """
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            return tomllib.load(handle)["project"]["name"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return PROJECT_NAME


def verdict(result: Result) -> str:
    if not result.evaluated:
        return NOT_EVALUATED
    return ABSENT if result.ok else PRESENT


def probe_rows(root: Path | None = None) -> list[dict]:
    rows = []
    for d in load_defects():
        result = evaluate(d, root)
        rows.append({
            "id": d.id,
            "invariant": d.invariant,
            "status": d.status,
            "check": d.check,
            "title": " ".join(d.title.split()),
            "verdict": verdict(result),
            "detail": " ".join(result.detail.split()),
        })
    # In catalogue-number order, not in the order the entries happen to sit in
    # the file: the ids carry an ordinal (`d07-...`) and the catalogue is
    # appended to as defects are found, so file order is not reading order and
    # the board would list `d25` above `d24`. Sorting here also makes the table
    # a function of the set of probes rather than of where each one was written.
    return sorted(rows, key=_probe_order)


def _probe_order(row: dict) -> tuple:
    head, _, _ = row["id"].partition("-")
    ordinal = head[1:] if head[:1] == "d" else ""
    return (int(ordinal) if ordinal.isdigit() else len(row["id"]), row["id"])


def counts(rows: list[dict]) -> dict:
    out = {v: 0 for v in (ABSENT, PRESENT, NOT_EVALUATED)}
    for r in rows:
        out[r["verdict"]] += 1
    return out


def source_rows(root: Path | None = None) -> list[dict]:
    """What each source is for, and whether the artefact it declares exists.

    The register declares what is built from every source, so the honest state of
    each one can be printed rather than remembered. A source that declares no
    corpus artefact is a line here with its reason - and it is the reason the
    determinism claim can be green while the MLI corpus does not exist, which is
    a sentence nobody should have to reconstruct from a passing test run.
    """
    base = Path(root or corpus.ROOT)
    present = {(family, edition)
               for family, edition in corpus.editions(base)}
    out: list[dict] = []
    for entry in corpus.declared_sources(base):
        what = entry["produces"]
        artefact = entry["artefact"]
        # "Built in part" is only ever true of a family that published some of
        # its documents: every other shape is either there or not.
        partial = False
        if what == "akn":
            family, _, edition = entry["id"].rpartition("-")
            state = ("built" if (family, edition) in present
                     and corpus.akn(base, family, edition) else "MISSING")
        elif what == "positions" and entry["dir"]:
            # A family: one register entry, one document per jurisdiction, and an
            # artefact per document plus the family's own account of itself. The
            # account is what is read here, because it is where the number of
            # documents that could *not* be read is written down - and a built
            # family that published 103 of 110 documents is not the same state as
            # one that published 110, which is why the count is printed.
            account = (base / artefact / corpus.POSITION_REPORT) \
                if artefact else None
            if account is not None and account.is_file():
                report = corpus.load_json(account)
                unread = len(report.get("unread") or [])
                state = (f"built ({report.get('published')} position(s) for "
                         f"{report.get('declared')} document(s): "
                         f"{unread} unread)")
                partial = bool(unread)
            else:
                state = "MISSING"
        elif what in ("table", "positions", "mapping"):
            # A shape whose corpus artefact is one declared file: "is it built"
            # is the file's existence, and nothing has to be reconstructed from
            # the source's id.
            state = ("built" if artefact and (base / artefact).is_file()
                     else "MISSING")
        elif what == "none":
            state = "declared not built"
        else:
            state = "UNDECLARED"
        out.append({"id": entry["id"], "produces": what or "-",
                    "artefact": artefact, "state": state,
                    "built": state.startswith("built"), "partial": partial,
                    "reason": entry["pending"]})
    return out


def render(root: Path | None = None) -> str:
    root = Path(root or corpus.ROOT)
    rows = probe_rows(root)
    by_verdict = counts(rows)
    invariants = load_invariants()
    defects = load_defects()

    lines: list[str] = []
    add = lines.append

    add("# Harness status")
    add("")
    add("Generated by `python -m harness --write`. Do not edit by hand: every "
        "number below is computed from the repository at the moment of writing.")
    add("")
    add(f"- project: `{project_name(root)}`")
    add(f"- corpus: {'present' if corpus.corpus_present(root) else 'no AKN yet'}"
        f" ({corpus.summary(root)})")
    add(f"- invariants: {len(invariants)}")
    add(f"- defects / regressions / declared targets: "
        f"{sum(1 for d in defects if d.status == 'defect')} / "
        f"{sum(1 for d in defects if d.status == 'regression')} / "
        f"{sum(1 for d in defects if d.status == 'target')} "
        f"(a target is a row the page pins: `d27-*`)")
    add(f"- probes: {len(rows)} — {by_verdict[ABSENT]} absent, "
        f"{by_verdict[PRESENT]} present, {by_verdict[NOT_EVALUATED]} not evaluated")
    sources = source_rows(root)
    if sources:
        # A built family that published 103 of 110 documents is not the same
        # state as one that published 110, so "in part" is counted separately
        # rather than rounded into "built": the number here has to be the one
        # the table below prints, or a reader has to reconcile them by hand.
        built = [s for s in sources if s["built"]]
        partial = [s for s in built if s["partial"]]
        in_part = (" (" + ", ".join(f"`{s['id']}` in part" for s in partial)
                   + ")" if partial else "")
        add(f"- sources: {len(sources)} — {len(built)} built{in_part}, "
            f"{len(sources) - len(built)} declared not built "
            f"(`provenance/sources.yaml` says which and why)")
    add("")

    if sources:
        add("## Sources, and what is built from each")
        add("")
        add("| source | produces | artefact | state |")
        add("| --- | --- | --- | --- |")
        for s in sources:
            add(f"| `{s['id']}` | `{s['produces']}` | "
                f"{'`' + s['artefact'] + '`' if s['artefact'] else '-'} | "
                f"{s['state']} |")
        add("")
        pending = [s for s in sources if s["reason"]]
        if pending:
            add("### Declared not built, with the reason")
            add("")
            for s in pending:
                add(f"- **`{s['id']}`** — {s['reason']}")
            add("")

    add("## Invariants")
    add("")
    add("| id | name | scope | enforced by |")
    add("| --- | --- | --- | --- |")
    for inv in invariants:
        add(f"| {inv.id} | {inv.name} | {inv.scope} | "
            f"`{', '.join(inv.enforced_by)}` |")
    add("")

    add("## Probes against this repository")
    add("")
    add("| verdict | defect | invariant | status | check |")
    add("| --- | --- | --- | --- | --- |")
    for r in rows:
        add(f"| {VERDICT_ICON[r['verdict']]} {r['verdict']} | `{r['id']}` | "
            f"{r['invariant']} | {r['status']} | `{r['check']}` |")
    add("")

    if by_verdict[PRESENT]:
        add("### Present defects, with evidence")
        add("")
        for r in rows:
            if r["verdict"] == PRESENT:
                add(f"- **{r['id']}** — {r['title']}")
                add(f"  - {r['detail']}")
        add("")

    if by_verdict[NOT_EVALUATED]:
        add("### Not evaluated")
        add("")
        add("These probes have no target here yet, so they neither pass nor fail. "
            "They will start speaking as soon as the extractor produces the "
            "artefact they inspect.")
        add("")
        for r in rows:
            if r["verdict"] == NOT_EVALUATED:
                add(f"- `{r['id']}` — {r['detail']}")
        add("")

    return "\n".join(lines) + "\n"


def write(root: Path | None = None, out: Path | None = None) -> Path:
    root = Path(root or corpus.ROOT)
    target = Path(out) if out else root / "docs" / "harness-status.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(root), encoding="utf-8")
    return target
