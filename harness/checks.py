"""Evaluate a defect probe against the repository.

Every check answers one question: "is this defect absent?". The answer is a
`Result` with three states:

  evaluated=False  the inputs do not exist yet (no corpus built) - the check
                   cannot speak, and the test must say so instead of passing
  ok=True          the invariant holds for this probe
  ok=False         the probe fired: the defect is present (or the target property
                   is still unmet), with file and line where available
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness import corpus
from harness.defects import Defect

ROOT = Path(__file__).resolve().parent.parent
EXCERPT_LIMIT = 1200  # the previous pipeline's silent slice; see d19

# Assembled from fragments on purpose: this file is itself scanned by the F14
# check, so it must not contain the token it looks for.
_LOCAL_ROOTS = ("/" + "Users/", "/" + "home/", "/" + "private/var/",
                r"[A-Za-z]:\\\\" + "Users\\\\")
LOCAL_PATH_RE = re.compile("(" + "|".join(_LOCAL_ROOTS) + ")")


@dataclass(frozen=True)
class Result:
    ok: bool
    detail: str
    evaluated: bool = True


def _not_evaluated(what: str) -> Result:
    return Result(ok=False, detail=f"not evaluated: {what}", evaluated=False)


def _files(root: Path, patterns) -> list[Path]:
    got: list[Path] = []
    for pat in patterns:
        got.extend(sorted(root.glob(pat)))
    return [p for p in dict.fromkeys(got) if p.is_file()]


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #

def check_forbidden_text(d: Defect, root: Path) -> Result:
    patterns = d.targets if d.targets else ((d.target,) if d.target else ())
    if not patterns:
        return Result(False, "no target declared", evaluated=False)
    files = _files(root, patterns)
    if not files:
        return _not_evaluated(f"no file matches {list(patterns)}")
    rx = re.compile(d.probe if d.probe_kind == "regex" else re.escape(d.probe),
                    re.M)
    hits = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        m = rx.search(text)
        if m:
            line = text[:m.start()].count("\n") + 1
            hits.append(f"{_rel(root, f)}:{line} → {m.group(0)[:70]!r}")
    if hits:
        return Result(False, "probe found:\n      " + "\n      ".join(hits[:6]))
    return Result(True, f"absent from {len(files)} file(s)")


def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _report_summary(text: str) -> dict:
    """The numbers a diff report prints, and the Articles it says it modified.

    Read loosely on purpose, because the check has to run against the previous
    pipeline's report as well - that is the report whose defect this probe exists
    for - and the two do not agree on punctuation. What is read is the summary
    numbers under their own names, and the `### Article N` headings of the
    modified section: everything else in a report is prose.
    """
    numbers: dict = {}
    for key in ("added", "removed", "modified", "unchanged"):
        found = re.search(rf"{key}\W{{0,4}}(\d+)", text, re.I)
        if found:
            numbers[key] = int(found.group(1))
    claimed: list = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = bool(re.search(r"\bmodified\b", line, re.I))
            continue
        if not inside or not line.startswith("### "):
            continue
        found = re.match(r"###\s+Article\s+([0-9]+\s*[A-Za-z]?)", line)
        if found:
            claimed.append(_fold(found.group(1)))
    return {"numbers": numbers, "modified": claimed}


def _fold(number: str) -> str:
    """An Article number compared the way a reader compares two of them.

    The sources print "Article 23 A" and "Article 23A" in different places, and
    that difference is typography; whether the Article is there at all is not.
    """
    return re.sub(r"\s+", "", number or "").upper()


def check_report_matches_corpus(d: Defect, root: Path) -> Result:
    """The report's claims are the corpus' claims, recomputed from the corpus.

    This is F9 applied to the one view that describes two editions at once. The
    previous report (defect d24) was built from a second reading of the two PDFs,
    and a second reading is where the artefacts came from: it reported the 2017
    text as gaining "Articles 8 and 9" in the middle of a sentence - a page's
    running head - and it left out Articles 5, 22 and 25, whose text the corpus
    holds as changed. A report that disagrees with the corpus in either direction
    is a report about something other than the corpus, and the changes it does
    show cannot be trusted to be changes.

    The comparison is one-directional and stated: every Article the corpus holds
    as modified must be in the report's modified list, every Article the report
    lists must be one the corpus holds as modified, and the summary numbers must
    be the recomputed ones.
    """
    patterns = d.targets if d.targets else ((d.target,) if d.target else ())
    files = _files(root, patterns)
    if not files:
        return _not_evaluated(f"no file matches {list(patterns)}")
    family = str(d.extra.get("family") or "")
    editions = [str(e) for e in (d.extra.get("editions") or [])]
    if not family or len(editions) != 2:
        return _not_evaluated("the catalogue declares no family/editions to "
                              "compare this report with")
    from harness import diff

    try:
        data = diff.compare(family, editions[0], editions[1], root)
    except (ValueError, FileNotFoundError, KeyError):
        return _not_evaluated(f"{family} {editions[0]}→{editions[1]} is not built "
                              f"here, so the report cannot be checked against it")
    expected = {_fold(a["number"]) for a in data["modified"]}
    claims = _report_summary(files[0].read_text(encoding="utf-8", errors="replace"))
    if not claims["numbers"] and not claims["modified"]:
        return _not_evaluated("the report declares no summary and no modified list")
    claimed = {_fold(n) for n in claims["modified"]}
    problems: list = []
    omitted = sorted(expected - claimed)
    if omitted:
        problems.append(f"the corpus holds Article(s) {', '.join(omitted)} as "
                        f"modified and the report does not")
    invented = sorted(claimed - expected)
    if invented:
        problems.append(f"the report lists Article(s) {', '.join(invented)} as "
                        f"modified and the corpus holds them as unchanged")
    for key, value in sorted((data["counts"]).items()):
        if key in claims["numbers"] and claims["numbers"][key] != value:
            problems.append(f"the report says {key} {claims['numbers'][key]} and "
                            f"the corpus says {value}")
    if problems:
        return Result(False, "the report and the corpus disagree:\n      "
                      + "\n      ".join(problems))
    return Result(True, f"{data['counts']['modified']} modified, "
                        f"{data['counts']['added']} added, "
                        f"{data['counts']['unchanged']} unchanged - the corpus' "
                        f"own numbers, in {_rel(root, files[0])}")


def check_count_equals(d: Defect, root: Path) -> Result:
    p = root / d.target
    if not p.is_file():
        return _not_evaluated(f"{d.target} missing")
    data = _load_json(p)
    m = re.fullmatch(r"len\((\w+)\)", d.selector.strip())
    if m:
        value = len(data.get(m.group(1), []))
    else:
        value = data.get(d.selector)
    if value == d.expected:
        return Result(True, f"{d.selector} == {value}")
    return Result(False, f"{d.selector} is {value}, expected {d.expected}")


RULES = {}


def rule(fn):
    RULES[fn.__name__] = fn
    return fn


@rule
def numbering_contiguous(d: Defect, target: Path, files: list[Path]) -> Result:
    bad = []
    for f in files:
        rows = _load_json(f)
        rows = rows.get("rows", []) if isinstance(rows, dict) else rows
        nums = [r.get("no") for r in rows if isinstance(r, dict)]
        if not nums:
            continue
        expected = list(range(min(nums), max(nums) + 1))
        if nums != expected or min(nums) != 1:
            gap = sorted(set(expected) - set(nums))
            bad.append(f"{f.name}: min={min(nums)} max={max(nums)} "
                       f"missing={gap}")
    if bad:
        return Result(False, "row numbering has gaps:\n      " + "\n      ".join(bad))
    return Result(True, "numbering contiguous")


@rule
def no_date_in_jurisdiction(d: Defect, target: Path, files: list[Path]) -> Result:
    bad = []
    for f in files:
        for r in _load_json(f).get("rows", []):
            name = str(r.get("jurisdiction", ""))
            if re.search(r"\d", name):
                bad.append(f"{f.name}: {name!r}")
    if bad:
        return Result(False, "digits inside jurisdiction names:\n      "
                      + "\n      ".join(bad[:8]))
    return Result(True, "jurisdiction names clean")


def _source_pdf(entry: dict | None):
    """The PDF an artefact was read from, when its source declares one file."""
    return entry.get("pdf") if entry else None


@rule
def no_silent_truncation(d: Defect, target: Path, files: list[Path]) -> Result:
    """The excerpt is the whole text of the option, or the artefact says it is not.

    The defect was a slice - `[:1200]` in the previous pipeline, 491 excerpts
    ending at exactly the limit, cut mid-word, none of them flagged - so the
    property to test is that nothing was cut. Testing it by *length* is a proxy
    that misfires in both directions: a complete excerpt can be longer than any
    limit, and a short one can still be cut. So the excerpt is compared with the
    text the pipeline reads for the same option, from the same source, and the
    comparison is only made when the source's bytes are here - a probe with
    nothing to compare against reports that it cannot speak, rather than
    approving what it did not check.
    """
    from harness import ledger, mli

    sources = {entry["id"]: entry for entry in corpus.declared_sources(ROOT)}
    compared = 0
    measured = 0
    bad = []
    for f in files:
        data = _load_json(f)
        entry = sources.get(str(data.get("source") or ""))
        pdf = _source_pdf(entry)
        fresh = None
        if pdf is not None:
            book = ledger.Classifier.classify(
                ledger.SpanStream.read(pdf, data["source"]), ledger.Ledger())
            fresh = mli.position(book, data["source"], pdf)
        elif entry is not None and entry.get("dir"):
            # A source that is a whole family of documents declares a directory
            # rather than one file, and the document behind this artefact is the
            # one it was read from: its own slug is the name of that document in
            # the family, so `fresh` is the same projection the corpus published,
            # read from the same bytes, without hashing 110 PDFs to find it.
            built = mli.family_once(corpus.ROOT / entry["dir"], data["source"],
                                    corpus.ROOT)
            fresh = built["positions"].get(Path(f).stem)
        for art, opts in (data.get("article_sections") or {}).items():
            read = (fresh or {}).get("article_sections", {}).get(str(art)) or []
            for position, option in enumerate(opts):
                if option.get("truncated") is True:
                    continue
                text = option.get("excerpt") or ""
                if fresh is None:
                    # No source to compare with, so the historical signature of
                    # the defect is used: an excerpt at the old slice's length is
                    # the cut that filled the previous corpus, and it is reported
                    # as one rather than waved through.
                    measured += 1
                    if len(text) >= EXCERPT_LIMIT - 5:
                        bad.append(f"{f.name}: art.{art} excerpt {len(text)} chars, "
                                   f"no `truncated` flag")
                    continue
                whole = read[position]["excerpt"] if position < len(read) else ""
                compared += 1
                if text != whole:
                    bad.append(f"{f.name}: art.{art} option {position}, "
                               f"{len(text)} chars against {len(whole)} read "
                               f"from the source - the excerpt is cut")
    if bad:
        return Result(False, "excerpts cut short of their source:\n      "
                      + "\n      ".join(bad[:6]))
    if compared:
        return Result(True, f"{compared} excerpt(s) equal to their source, "
                            f"where the previous pipeline applied a "
                            f"{EXCERPT_LIMIT}-character limit")
    if measured:
        return Result(True, f"{measured} excerpt(s) below the {EXCERPT_LIMIT}"
                            f"-character limit the previous pipeline sliced at "
                            f"(the sources are not here to compare against)")
    return _not_evaluated("no excerpts to inspect")


@rule
def one_file_per_jurisdiction(d: Defect, target: Path, files: list[Path]) -> Result:
    bad = []
    for f in files:
        if f.name == "batch-report.json":
            continue
        d_ = _load_json(f)
        country = (d_.get("country") or "").strip()
        if not country:
            bad.append(f"{f.name}: empty country")
        if d_.get("is_companion"):
            stems = {p.stem for p in files if p.name != "batch-report.json"}
            base = d_.get("base_slug")
            if not base or base not in stems:
                bad.append(f"{f.name}: a second document about a jurisdiction that "
                           f"is not linked to the position it belongs to "
                           f"(base_slug={base!r})")
    if bad:
        return Result(False, "slug/identity problems:\n      " + "\n      ".join(bad[:8]))
    return Result(True, "one canonical file per jurisdiction")


@rule
def covered_table_present_or_declared(d: Defect, target: Path, files: list[Path]) -> Result:
    bad = []
    for f in files:
        if f.name == "batch-report.json":
            continue
        d_ = _load_json(f)
        text = " ".join(o.get("excerpt") or ""
                        for opts in (d_.get("article_sections") or {}).values()
                        for o in opts)
        looks_tabular = ("Disposition" in text and
                         ("Convention couverte" in text
                          or "Covered Tax Agreement" in text
                          or "Numéro de la Convention" in text))
        if looks_tabular and not d_.get("n_covered"):
            declared = json.dumps(d_.get("qa") or {}).lower()
            if "covered" not in declared:
                bad.append(f"{f.name}: table visible in excerpts, "
                           f"n_covered={d_.get('n_covered')}, no QA note")
    if bad:
        return Result(False, "silently empty covered-agreements:\n      "
                      + "\n      ".join(bad[:8]))
    return Result(True, "no silently empty covered-agreements field")


def check_field_rule(d: Defect, root: Path) -> Result:
    if d.rule not in RULES:
        return Result(False, f"unknown rule {d.rule!r}", evaluated=False)
    files = _files(root, [d.target])
    if not files:
        return _not_evaluated(f"no file matches {d.target!r}")
    return RULES[d.rule](d, d.target, files)


def check_no_local_paths(d: Defect, root: Path) -> Result:
    files = _files(root, d.targets)
    if not files:
        return _not_evaluated("no artefact to inspect")
    hits = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        m = LOCAL_PATH_RE.search(text)
        if m:
            line = text[:m.start()].count("\n") + 1
            hits.append(f"{_rel(root, f)}:{line}")
    if hits:
        return Result(False, "local paths found:\n      " + "\n      ".join(hits[:6]))
    return Result(True, f"clean across {len(files)} file(s)")


def check_path_exists(d: Defect, root: Path) -> Result:
    """ok=True means "the artefact this defect is about really was there".
    """
    files = _files(root, [d.pattern] if d.pattern else list(d.targets))
    if files:
        return Result(True, f"present: {[_rel(root, f) for f in files[:4]]}")
    return Result(False, f"nothing matches {d.pattern!r}")


def check_file_contains(d: Defect, root: Path) -> Result:
    """ok=True means "the text this defect is about is really in that file".
    """
    patterns = d.targets if d.targets else ((d.target,) if d.target else ())
    files = _files(root, patterns)
    if not files:
        return Result(False, f"no file matches {list(patterns)}")
    rx = re.compile(d.probe if d.probe_kind == "regex" else re.escape(d.probe), re.M)
    for f in files:
        if rx.search(f.read_text(encoding="utf-8", errors="replace")):
            # The matched text is deliberately not echoed: this detail ends up in
            # a committed report, and the probe may be a local path (F14).
            return Result(True, f"evidence found in {_rel(root, f)}")
    return Result(False, f"probe absent from {len(files)} file(s)")


def _git_toplevel(root: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out.strip())


def check_absent_tracked_path(d: Defect, root: Path) -> Result:
    """No path matching the pattern may be *tracked* by git.

    "Tracked" only means something if git resolves to this very directory. A
    project sitting inside somebody else's repository would otherwise be judged
    against that repository's index and come out clean for the wrong reason.
    """
    top = _git_toplevel(root)
    if top is None:
        return _not_evaluated("not a git repository")
    if top.resolve() != Path(root).resolve():
        return _not_evaluated("git resolves to a different repository root, so "
                              "what is tracked here cannot be decided")
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _not_evaluated("not a git repository")
    tracked = out.split()
    hits = [p for p in tracked if fnmatch.fnmatch(p, d.pattern)]
    if hits:
        return Result(False, f"tracked generated artefact(s): {hits}")
    return Result(True, f"{d.pattern} not tracked ({len(tracked)} files tracked)")


def check_control_holds_its_own(d: Defect, root: Path) -> Result:
    """The job that runs the control holds the checkouts this repository holds.

    The rule itself is `harness/discipline/holds.py`, read here rather than
    restated: which checkouts a run of the shared control is handed is whose red
    that run reports, and a repository cannot repair a copy that lives in another
    repository. The probe exists because that is a fact about a workflow - visible
    only to a reader who opens the job, and invisible to every test in this
    repository that passes while a sibling sits in the run.
    """
    from harness.discipline import holds

    found = holds.problems(root)
    if found:
        return Result(False, "a run reads a copy this repository cannot write:"
                      "\n      " + "\n      ".join(found))
    out = []
    for run in holds.runs(root):
        held = ", ".join(f"`{layer}`" for layer in run["hands_in"]) or "nothing"
        left = ", ".join(f"`{layer}`" for layer in run["leaves"]) or "nothing"
        out.append(f"{run['file'].name} `{run['job']}` holds {held} and leaves "
                   f"{left} to their own runs")
    return Result(True, "; ".join(out))


CHECKS = {
    # assertions: ok=True means "the invariant holds here"
    "forbidden_text": check_forbidden_text,
    "control_holds_its_own": check_control_holds_its_own,
    "report_matches_corpus": check_report_matches_corpus,
    "count_equals": check_count_equals,
    "field_rule": check_field_rule,
    "no_local_paths": check_no_local_paths,
    "absent_tracked_path": check_absent_tracked_path,
    # evidence: ok=True means "the defect substance is really there"
    "path_exists": check_path_exists,
    "file_contains": check_file_contains,
}

def evaluate(d: Defect, root: Path | None = None) -> Result:
    fn = CHECKS.get(d.check)
    if fn is None:
        return Result(False, f"unknown check {d.check!r}", evaluated=False)
    return fn(d, Path(root or ROOT))


