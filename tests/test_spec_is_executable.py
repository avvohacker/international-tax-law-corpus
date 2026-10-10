"""Meta-tests: the specification must be executable, not decorative.

These pass today. They are the guarantee that fixtures/invariants.yaml and
fixtures/known_defects.yaml cannot rot: if someone adds an invariant with no
test, renames a test, or points a defect at a non-existent invariant, this file
goes red before anything else does.
"""
import ast
import re

import pytest

from harness import load_defects, load_invariants
from harness.checks import CHECKS, RULES
from harness.defects import STATUSES
from support import ROOT

SPEC = ROOT / "SPEC.md"
TESTS_DIR = ROOT / "tests"

INVARIANTS = load_invariants()
DEFECTS = load_defects()


def _test_functions() -> set[str]:
    names: set[str] = set()
    for path in TESTS_DIR.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def _spec_headings() -> dict[str, str]:
    """{invariant id: heading line} for every invariant heading in SPEC.md."""
    text = SPEC.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^#+\s*(\S+) (.*)$", line)
        if match and match.group(1).strip() in {i.id for i in INVARIANTS}:
            found[match.group(1).strip()] = match.group(2).strip()
    return found


def test_every_invariant_is_declared_in_spec():
    headings = _spec_headings()
    missing = [i.id for i in INVARIANTS if i.id not in headings]
    assert not missing, (
        "these invariants exist in fixtures/invariants.yaml but have no heading "
        f"in SPEC.md: {missing}")


def test_every_spec_heading_carries_the_invariant_name():
    """A heading that names the wrong invariant is worse than no heading."""
    headings = _spec_headings()
    wrong = [f"{i.id}: SPEC.md says {headings.get(i.id)!r}, the catalogue says "
             f"{i.name!r}" for i in INVARIANTS
             if i.id in headings and i.name not in headings[i.id]]
    assert not wrong, "\n".join(wrong)


def _spec_sections() -> dict[str, str]:
    """{invariant id: its section body}, the heading line excluded."""
    ids = {i.id for i in INVARIANTS}
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    starts = []
    for n, line in enumerate(lines):
        match = re.match(r"^#+\s*(\S+) ", line)
        if match and match.group(1).strip() in ids:
            starts.append((match.group(1).strip(), n))
    out: dict[str, str] = {}
    for pos, (ident, n) in enumerate(starts):
        end = starts[pos + 1][1] if pos + 1 < len(starts) else len(lines)
        out[ident] = "\n".join(lines[n + 1:end])
    return out


def test_every_spec_section_states_and_proves_its_invariant():
    """A section is useful only if it says what must hold and what decides it."""
    sections = _spec_sections()
    problems = []
    for inv in INVARIANTS:
        body = sections.get(inv.id, "")
        if "**Statement.**" not in body:
            problems.append(f"{inv.id}: no statement")
        if "**Proof.**" not in body:
            problems.append(f"{inv.id}: no proof")
        if len(body) < 200:
            problems.append(f"{inv.id}: {len(body)} characters of explanation "
                            f"- too thin to be worth a reader's time")
    assert not problems, "\n".join(problems)


def test_every_invariant_has_a_real_enforcer():
    names = _test_functions()
    broken = []
    for inv in INVARIANTS:
        if not inv.enforced_by:
            broken.append(f"{inv.id}: no enforcer declared")
        for enforcer in inv.enforced_by:
            if enforcer == "known_defects":
                continue
            if enforcer not in names:
                broken.append(f"{inv.id}: unknown test {enforcer!r}")
    assert not broken, "\n".join(broken)


def test_statuses_are_known():
    bad = [f"{d.id}: status {d.status!r}" for d in DEFECTS
           if d.status not in STATUSES]
    assert not bad, f"unknown status; expected one of {STATUSES}: {bad}"


def test_every_defect_points_to_a_known_invariant():
    known = {i.id for i in INVARIANTS}
    bad = [f"{d.id} -> {d.invariant}" for d in DEFECTS
           if d.invariant not in known]
    assert not bad, f"defects referencing unknown invariants: {bad}"


def test_every_invariant_claimed_by_a_defect_exists():
    """The reverse direction: no invariant is left with only prose."""
    claimed = {d.invariant for d in DEFECTS}
    unproven = [i.id for i in INVARIANTS
                if i.id in claimed and not i.enforced_by]
    assert not unproven, f"invariants referenced by defects but not enforced: {unproven}"


def test_defect_ids_are_unique():
    ids = [d.id for d in DEFECTS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate defect ids: {dupes}"


def test_each_defect_is_documented_and_testable():
    """A defect with no evidence or no probe is a rumour, not a regression test."""
    problems = []
    for d in DEFECTS:
        if not d.why.strip():
            problems.append(f"{d.id}: missing `why`")
        if not d.evidence.strip():
            problems.append(f"{d.id}: missing `evidence`")
        if d.check == "forbidden_text" and not d.probe:
            problems.append(f"{d.id}: forbidden_text without a probe")
        if d.check == "forbidden_text" and not (d.targets or d.target):
            problems.append(f"{d.id}: forbidden_text without a target")
        if d.check == "forbidden_text" and d.probe_kind not in ("literal", "regex"):
            problems.append(f"{d.id}: probe_kind must be literal|regex")
        if d.check == "count_equals" and (not d.target or not d.selector
                                         or d.expected is None):
            problems.append(f"{d.id}: count_equals needs target, selector, expected")
        if d.check == "field_rule" and d.rule not in RULES:
            problems.append(f"{d.id}: unknown field_rule {d.rule!r}")
        if d.check == "absent_tracked_path" and not d.pattern:
            problems.append(f"{d.id}: absent_tracked_path without a pattern")
    assert not problems, "\n".join(problems)


def test_every_check_kind_is_implemented():
    used = {d.check for d in DEFECTS}
    unknown = sorted(used - set(CHECKS))
    assert not unknown, f"defects use unimplemented checks: {unknown}"


@pytest.mark.parametrize("inv", INVARIANTS, ids=[i.id for i in INVARIANTS])
def test_invariant_statement_is_not_empty(inv):
    assert len(inv.statement) > 40, f"{inv.id} statement is too short to be useful"
    assert inv.scope in ("project", "corpus", "sources"), \
        f"{inv.id}: unknown scope {inv.scope!r}"
