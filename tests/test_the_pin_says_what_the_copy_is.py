"""A pin says what the copy beside it is, and the rule for that is shared.

`provenance/vendored-discipline.yaml` says which bytes travelled and where from,
and the rule about that register now has one implementation,
`harness/discipline/pin.py`, read by each vendored copy's own test and by the
control, in whichever run holds the copy. It used to be three statements of one
rule, and the three had drifted - one of them refused a pin whose `source_commit`
named a branch or a tag, the others accepted it, and the control accepted it in
both copies.

This file holds the rule for the corpus. It asks it about a commit, a branch, a
tag, no commit at all, another source, another source path, a copy edited by
hand, a file the copy has that the pin does not name and a file the pin names
that the copy does not have; it reads the copy that is in this repository, `mcp/`,
as the control reads it; and it breaks a copy of that copy to show that the reader
applies this rule rather than a second one of its own. The library's copy is the
third repository's, and the rule reaches it in the library's own run of the
control, over this corpus - this repository's job holds the two checkouts this
repository holds.
"""
import hashlib
import importlib.util
from pathlib import Path
from functools import lru_cache

import pytest
import yaml

from harness.discipline import pin
from support import ROOT

TOOL = ROOT / "scripts" / "vendor-discipline.py"
SOURCE = ROOT / "harness" / "discipline"
MCP = ROOT / "mcp"
VENDORED = Path("vendor") / "discipline"
REGISTER = Path("provenance") / "vendored-discipline.yaml"


@lru_cache(maxsize=1)
def reader():
    """The vendoring tool, loaded from its path: its name is not importable."""
    spec = importlib.util.spec_from_file_location("vendor_discipline", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copies_of(root: Path) -> dict[str, bytes]:
    """The vendored files of a checkout, as bytes, keyed by name."""
    return {path.name: path.read_bytes()
            for path in sorted((root / VENDORED).glob("*.py"))}


def recorded_of(root: Path) -> dict:
    return yaml.safe_load((root / REGISTER).read_text(encoding="utf-8")) or {}


def a_copy(where: Path, *, commit: str = "a" * 40,
           source_path: str = "harness/discipline",
           source: str | None = None) -> Path:
    """A checkout carrying the corpus' discipline bytes, and a pin that says so."""
    vendored = where / VENDORED
    vendored.mkdir(parents=True)
    files: dict[str, str] = {}
    for path in sorted(SOURCE.glob("*.py")):
        (vendored / path.name).write_bytes(path.read_bytes())
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    register = where / REGISTER
    register.parent.mkdir(parents=True)
    register.write_text(yaml.safe_dump({
        "source": source or pin.REPOSITORY,
        "source_path": source_path,
        "source_commit": commit,
        "files": files,
    }, sort_keys=True), encoding="utf-8")
    return where


def test_a_copy_the_pin_describes_is_accepted(tmp_path):
    """The case that keeps the rule from being a reader that refuses everything."""
    checkout = a_copy(tmp_path / "copy")
    assert pin.problems(recorded_of(checkout), copies_of(checkout)) == []


@pytest.mark.parametrize("ref", ["main", "v1.0.0", "HEAD", "unknown"])
def test_a_pin_that_names_a_ref_is_refused(tmp_path, ref: str):
    """A branch, a tag or anything else that is not an object id is not a pin."""
    checkout = a_copy(tmp_path / "copy", commit=ref)
    problems = pin.problems(recorded_of(checkout), copies_of(checkout))
    assert problems and any(ref in problem for problem in problems), (
        f"a pin naming {ref!r} as the commit it was vendored from was accepted: "
        f"{problems}")


def test_a_pin_that_says_no_commit_at_all_is_refused(tmp_path):
    """Nothing is not an object id either, and the message says which nothing."""
    checkout = a_copy(tmp_path / "copy", commit="")
    problems = pin.problems(recorded_of(checkout), copies_of(checkout))
    assert problems and any("which commit" in problem for problem in problems), (
        f"a pin that names no commit was accepted: {problems}")


def test_a_pin_that_names_another_source_path_is_refused(tmp_path):
    """The path is a claim too: a copy of the rules is a copy of *those* rules."""
    checkout = a_copy(tmp_path / "copy", source_path="harness/rules")
    problems = pin.problems(recorded_of(checkout), copies_of(checkout))
    assert problems and any("harness/rules" in problem for problem in problems), (
        f"a pin naming another source path was accepted: {problems}")


def test_a_pin_that_names_another_source_is_refused(tmp_path):
    """And the source: these bytes travelled from one repository and not another."""
    elsewhere = "https://example.invalid/another-corpus"
    checkout = a_copy(tmp_path / "copy", source=elsewhere)
    problems = pin.problems(recorded_of(checkout), copies_of(checkout))
    assert problems and any(elsewhere in problem for problem in problems), (
        f"a pin naming another source was accepted: {problems}")


@pytest.mark.parametrize("change", ["edited", "unnamed", "absent"])
def test_a_copy_that_is_not_the_bytes_the_pin_records_is_refused(tmp_path, change):
    """The three ways the files themselves can stop matching, named per file."""
    checkout = a_copy(tmp_path / "copy")
    name = sorted(copies_of(checkout))[0]
    vendored = checkout / VENDORED
    if change == "edited":
        (vendored / name).write_bytes((vendored / name).read_bytes() + b"\n# nobody re-vendored this\n")
    elif change == "unnamed":
        (vendored / "a-rule-of-my-own.py").write_text("# invented here\n", encoding="utf-8")
        name = "a-rule-of-my-own.py"
    else:
        recorded = recorded_of(checkout)
        recorded["files"][name] = "0" * 64
        (checkout / REGISTER).write_text(yaml.safe_dump(recorded, sort_keys=True),
                                        encoding="utf-8")

    problems = pin.problems(recorded_of(checkout), copies_of(checkout))
    assert problems and any(name in problem for problem in problems), (
        f"a copy that is not what the pin records was accepted ({change}): {problems}")


def test_the_copy_in_this_repository_is_one_the_rule_accepts():
    """The real register in `mcp/`, read as the control reads it."""
    problems = pin.problems(recorded_of(MCP), copies_of(MCP))
    assert problems == [], (
        "the copy of the discipline in mcp/ is not what its pin declares:\n  "
        + "\n  ".join(problems))


def test_the_reader_applies_this_rule_and_not_a_second_one(tmp_path):
    """The reader the control runs has no rule of its own: break a copy, ask both.

    The copy is a copy on purpose - the pin in `mcp/` is the repository's own
    register, and a test that rewrote it to prove a point would leave the
    repository red for the next reader of it.
    """
    checkout = tmp_path / "copy"
    (checkout / VENDORED).parent.mkdir(parents=True)
    (checkout / VENDORED).symlink_to(MCP / VENDORED, target_is_directory=True)
    (checkout / REGISTER).parent.mkdir(parents=True)
    recorded = recorded_of(MCP)
    recorded["source_commit"] = "main"
    (checkout / REGISTER).write_text(yaml.safe_dump(recorded, sort_keys=True),
                                     encoding="utf-8")

    named = reader().drifted(checkout)
    assert any("main" in problem for problem in named), (
        f"the reader accepted a pin that names a branch: {named}")
