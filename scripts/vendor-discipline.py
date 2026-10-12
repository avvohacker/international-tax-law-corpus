"""Vendor the shared discipline into the repositories that run it.

`harness/discipline/` is the one implementation of the rules the three
repositories of this family share - what may not be committed about a machine,
how a workflow is read, what a status board owes a reader (its own docstring
states them). It travels: this script copies it *verbatim* into each repository
that is not the one it lives in, and rewrites the pin that says where the copy
came from and which bytes it is.

    python scripts/vendor-discipline.py --into ../international-tax-law-library \\
                                        --into ../international-tax-law-mcp
    python scripts/vendor-discipline.py --check --into ../international-tax-law-library

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
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

SOURCE = Path(__file__).resolve().parent.parent / "harness" / "discipline"
REPOSITORY = "avvohacker/international-tax-law-corpus"
PIN = Path("provenance") / "vendored-discipline.yaml"
VENDORED = Path("vendor") / "discipline"

HEADER = """\
# The shared discipline, vendored from the corpus and pinned by hash.
#
# Written by `scripts/vendor-discipline.py` in
# {repository}, which is the one implementation of what may not be committed
# about a machine, how a workflow is read, and what a status board owes a
# reader. The copy under `vendor/discipline/` must be these bytes: a copy that
# has drifted from the pin is a red test
# (`tests/test_the_vendored_discipline_is_pinned.py`) rather than a surprise,
# and `scripts/discipline-drift.py`, run against the corpus' own checkout, is
# what refuses a copy that has gone back to inventing its own rule.
#
# Do not edit either half by hand: re-vendor.
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "source": REPOSITORY,
        "source_path": f"{SOURCE.parent.name}/{SOURCE.name}" if SOURCE.parent.name == "harness"
                       else f"{SOURCE.parent.name}/{SOURCE.name}",
        "source_commit": head(SOURCE.parent.parent),
        "vendored_on": date.today().isoformat(),
        "files": files,
    }, sort_keys=True)
    return HEADER.format(repository=REPOSITORY) + body


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
    """Every way the copy in ``into`` is not this source, named."""
    problems: list[str] = []
    target = into / VENDORED
    for path in sources():
        destination = target / path.name
        if not destination.exists():
            problems.append(f"{destination}: absent, and the source has it")
        elif destination.read_bytes() != path.read_bytes():
            problems.append(f"{destination}: differs from {path}")
    extra = sorted(candidate.name for candidate in target.glob("*.py")
                   if candidate.name not in {path.name for path in sources()})
    if extra:
        problems.append(f"{target}: names a file the source does not: {extra}")
    pin = into / PIN
    if not pin.exists():
        problems.append(f"{pin}: absent, so the copy says nothing about where it came from")
        return problems
    recorded = yaml.safe_load(pin.read_text(encoding="utf-8")) or {}
    if recorded.get("source") != REPOSITORY:
        problems.append(f"{pin}: names the source {recorded.get('source')!r}, "
                        f"and the discipline comes from {REPOSITORY}")
    stated = recorded.get("files") or {}
    current = {path.name: digest(path) for path in sources()}
    if set(stated) != set(current):
        problems.append(f"{pin}: pins {sorted(stated)} while the source has "
                        f"{sorted(current)}")
    for name in sorted(set(stated) & set(current)):
        if stated[name] != current[name]:
            problems.append(f"{pin}: the pin for {name} is {stated[name][:12]}, "
                            f"and the source is {current[name][:12]}")
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
