"""Vendor the shared discipline into the repositories that run it.

`harness/discipline/` is the one implementation of the rules this family shares -
what may not be committed about a machine, how a workflow is read, what a status
board owes a reader, what a pin says about the copy it holds, and where a document
sends a reader who wants the server (its own docstring states them). It travels:
this script copies it *verbatim* into each layer that is not the one it lives in,
and rewrites the pin that says where the copy came from and which bytes it is.

    python scripts/vendor-discipline.py --into ../international-tax-law-library \\
                                        --into mcp
    python scripts/vendor-discipline.py --check --into ../international-tax-law-library

The server is the second `--into`, and it is a directory of this checkout rather
than a sibling: it is committed here, under `mcp/`. The library is a repository
of its own, and stays a sibling.

`--check` writes nothing and exits non-zero naming the file that differs, so the
corpus' own control can refuse a copy that has drifted from the source without
touching it. That is the whole idiom, and it is the one these repositories
already use for the bytes they do not own: the copy travels, the hash of the
copy is the contract, and the register says where it came from. The difference is
that here the bytes are our own rules, which is why the pin matters more, not
less: a copy of a rule is a rule, and three copies of a rule that nothing
compares are three rules.

The pin is `provenance/vendored-discipline.yaml` in the repository that receives
the copy. The vendored files go to `vendor/discipline/`, because a repository
that carries somebody else's rules should be able to say, from the path alone,
which of the two things in front of it is the one it did not write.

The pin is read by `harness/discipline/pin.py`, from here rather than restated:
that rule used to sit in each copy's own test and in this script, and the three
had drifted - one of them refused a pin whose `source_commit` named a branch or a
tag, the others accepted it. What this script adds to that rule is the half only
it can see: which files the *source* has, against which files the pin names.

The source is named by URL, and not by the short `owner/repo` slug: a URL is how
every other register in this family names the bytes it did not write, and the
machine-trace rule of this very package recognises an owner only where it is a
URL or an owner line. A slug is a bare word - the account that owns these
repositories read as a machine trace on the desk of the person most likely to be
re-vendoring, red in all three layers at once, and green on CI, where the
account is `runner`. Which form to write here is not a matter of taste: one of
them is a name the rule already exempts, and the other is a name it must not.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

SOURCE = Path(__file__).resolve().parent.parent / "harness" / "discipline"
PIN = Path("provenance") / "vendored-discipline.yaml"
VENDORED = Path("vendor") / "discipline"


@lru_cache(maxsize=1)
def rule():
    """The rule about a pin, loaded from the package it belongs to.

    Loaded by path for the same reason `scripts/discipline-drift.py` loads the
    discipline that way: this script is run from the corpus and from a desk that
    keeps its checkouts wherever it likes, and the rule it must apply is the
    corpus' own rather than whichever one happens to be installed. `pin.py`
    imports nothing from its package, so one file is enough to load.
    """
    spec = importlib.util.spec_from_file_location("discipline_pin",
                                                  SOURCE / "pin.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["discipline_pin"] = module
    spec.loader.exec_module(module)
    return module

HEADER = """\
# The shared discipline, vendored from the corpus and pinned by hash.
#
# Written by `scripts/vendor-discipline.py` in the corpus, at
# {repository}.
#
# That package is the one implementation of the rules this family shares: what
# may not be committed about a machine, how a workflow is read, what a status
# board owes a reader, what a pin says about the copy it holds, and where a
# document sends a reader who wants the server. The copy under `vendor/discipline/`
# must be these bytes: a copy that has drifted from the pin is a red test
# (`tests/test_the_vendored_discipline_is_pinned.py`) rather than a surprise,
# and `scripts/discipline-drift.py`, run against the corpus' own checkout, is
# what refuses a copy that has gone back to inventing its own rule.
#
# Do not edit either half by hand: re-vendor.
"""


def digest(path: Path) -> str:
    return rule().digest(path.read_bytes())


def sources() -> list[Path]:
    return sorted(path for path in SOURCE.glob("*.py"))


def head(root: Path) -> str:
    """The corpus' own commit, or `unknown` when it is not in a working copy."""
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def pin_text(root: Path) -> str:
    files = {path.name: digest(path) for path in sources()}
    body = yaml.safe_dump({
        "source": rule().REPOSITORY,
        "source_path": rule().SOURCE_PATH,
        "source_commit": head(SOURCE.parent.parent),
        "vendored_on": date.today().isoformat(),
        "files": files,
    }, sort_keys=True)
    return HEADER.format(repository=rule().REPOSITORY) + body


def vendor(into: Path) -> list[str]:
    """Write the copy and its pin, and say what changed."""
    changed: list[str] = []
    target = into / VENDORED
    target.mkdir(parents=True, exist_ok=True)
    for path in sources():
        destination = target / path.name
        if not destination.exists() or destination.read_bytes() != path.read_bytes():
            destination.write_bytes(path.read_bytes())
            changed.append(str(destination))
    pin = into / PIN
    pin.parent.mkdir(parents=True, exist_ok=True)
    if not pin.exists() or pin.read_text(encoding="utf-8") != pin_text(into):
        pin.write_text(pin_text(into), encoding="utf-8")
        changed.append(str(pin))
    return changed


def drifted(into: Path) -> list[str]:
    """Every way the copy in ``into`` is not this source, named.

    The rule about the pin is read from `harness/discipline/pin.py`; what is
    added here is the half only this side can see - the source's own file list,
    which the pin is a copy of and the copy has to be too.
    """
    target = into / VENDORED
    problems: list[str] = []
    if not target.is_dir():
        problems.append(f"{target}: absent, and the discipline is vendored there")
    pin = into / PIN
    if not pin.exists():
        problems.append(f"{pin}: absent, so the copy says nothing about where it "
                        f"came from")
        return problems
    recorded = yaml.safe_load(pin.read_text(encoding="utf-8")) or {}
    copies = {path.name: path.read_bytes() for path in sorted(target.glob("*.py"))}
    problems += [f"{pin}: {problem}" for problem in rule().problems(recorded, copies)]
    current = {path.name: digest(path) for path in sources()}
    if set(recorded.get("files") or {}) != set(current):
        problems.append(f"{pin}: pins {sorted(recorded.get('files') or {})} while "
                        f"the source has {sorted(current)}")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/vendor-discipline.py")
    parser.add_argument("--into", action="append", required=True, metavar="REPO",
                        help="a repository that runs the discipline")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit non-zero when a copy differs")
    arguments = parser.parse_args(argv)

    code = 0
    for name in arguments.into:
        into = Path(name).resolve()
        if arguments.check:
            problems = drifted(into)
            if problems:
                code = 1
                print(f"{into} has drifted from {SOURCE}:", file=sys.stderr)
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                print("  re-vendor with: python scripts/vendor-discipline.py "
                      f"--into {name}", file=sys.stderr)
            else:
                print(f"{into}: the copy matches the source, and the pin matches the copy")
        else:
            changed = vendor(into)
            print(f"{into}: " + ("wrote " + ", ".join(changed) if changed
                                 else "already carried this exact copy"))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
