"""A pin names a commit, and the reader that visits every copy says so.

`provenance/vendored-discipline.yaml` says which copy of the shared rules a
repository holds and where it came from. The library and `mcp/` each hold that
copy to the pin from the inside, in a file of this name; the *reader* that visits
every copy at once is `scripts/vendor-discipline.py`, run by CI as `--check` and
by `scripts/discipline-drift.py` over the library and this repository's `mcp/`.
It is the reader whoever reads the control believes, so its version of the rule
is held here instead of assumed there.

The rule is three claims and no more. A `source_commit` has to be a git object
id: a branch or a tag moves under the checkout meant to reproduce the bytes, so a
pin naming one says which bytes travelled only for the moment it was written.
The source and the source path are the other two, and they are refused for the
same reason - a register that names the wrong thing is a register nobody can
check against.

The tool is loaded by path, because `vendor-discipline.py` is not a module name,
and it is asked about two kinds of copy: one with a commit, and ones with a ref,
a tag, nothing, and a source path that is not where the discipline lives. The
copy that is in this repository is read as well, so the reader is exercised
against a real pin and not only against the ones built here. What cannot be held
here is the library's copy: the control that reads it runs where all three
checkouts are.

The bytes the copies are built from are the corpus' own, so a case below builds
the same arrangement the vendoring tool writes, and the reader is asked the
question CI asks it.
"""

from datetime import date
from functools import lru_cache
import hashlib
import importlib.util
from pathlib import Path

import pytest
import yaml

from support import ROOT

TOOL = ROOT / "scripts" / "vendor-discipline.py"
SOURCE = ROOT / "harness" / "discipline"
MCP = ROOT / "mcp"


@lru_cache(maxsize=1)
def reader():
    """The vendoring tool, loaded from its path: its name is not importable."""
    spec = importlib.util.spec_from_file_location("vendor_discipline", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def a_copy(where: Path, *, source_commit: str, source_path: str = "harness/discipline",
           source: str | None = None) -> Path:
    """A directory carrying the corpus' discipline bytes, and a pin that says so."""
    vendored = where / "vendor" / "discipline"
    vendored.mkdir(parents=True)
    files: dict[str, str] = {}
    for path in sorted(SOURCE.glob("*.py")):
        (vendored / path.name).write_bytes(path.read_bytes())
        files[path.name] = digest(path.read_bytes())
    pin = where / "provenance" / "vendored-discipline.yaml"
    pin.parent.mkdir(parents=True)
    pin.write_text(yaml.safe_dump({
        "source": source or reader().REPOSITORY,
        "source_path": source_path,
        "source_commit": source_commit,
        "vendored_on": date.today().isoformat(),
        "files": files,
    }, sort_keys=True), encoding="utf-8")
    return where


def test_a_pin_that_names_a_commit_is_accepted(tmp_path):
    """The case that keeps the rule from being a reader that refuses everything."""
    where = a_copy(tmp_path / "copy", source_commit="a" * 40)
    assert reader().drifted(where) == [], reader().drifted(where)


@pytest.mark.parametrize("ref", ["main", "v1.0.0", "HEAD", "unknown"])
def test_a_pin_that_names_a_ref_is_refused(tmp_path, ref: str):
    """A branch, a tag or anything that is not an object id is not a pin."""
    where = a_copy(tmp_path / "copy", source_commit=ref)
    problems = reader().drifted(where)
    assert problems and any(ref in problem for problem in problems), (
        f"a pin naming {ref!r} as the commit it was vendored from was accepted: "
        f"{problems}")


def test_a_pin_that_says_no_commit_at_all_is_refused(tmp_path):
    """Nothing is not an object id either, and the message says which nothing."""
    where = a_copy(tmp_path / "copy", source_commit="")
    problems = reader().drifted(where)
    assert problems and any("no commit" in problem for problem in problems), problems


def test_a_pin_that_names_another_source_path_is_refused(tmp_path):
    """The path is a claim too: a copy of the rules is a copy of *those* rules."""
    where = a_copy(tmp_path / "copy", source_commit="a" * 40,
                   source_path="harness/rules")
    problems = reader().drifted(where)
    assert problems and any("harness/rules" in problem for problem in problems), (
        f"a pin naming another source path was accepted: {problems}")


def test_a_pin_that_names_another_source_is_refused(tmp_path):
    """And the source: the bytes travelled from one repository and not another."""
    elsewhere = "https://example.invalid/another-corpus"
    where = a_copy(tmp_path / "copy", source_commit="a" * 40, source=elsewhere)
    problems = reader().drifted(where)
    assert problems and any(elsewhere in problem for problem in problems), (
        f"a pin naming another source was accepted: {problems}")


def test_the_copy_in_this_repository_is_one_the_reader_accepts():
    """The real pin, read by the tool the control runs, not a copy made here."""
    problems = reader().drifted(MCP)
    assert problems == [], (
        "the copy of the discipline in mcp/ is not what its pin declares:\n  "
        + "\n  ".join(problems))
