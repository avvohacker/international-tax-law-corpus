"""Has the library moved past the commit this server answers from?

The server answers from `provenance/library.yaml`, which names a commit of the
library. That pin is what makes the answers reproducible, and its price is that
nothing here notices by itself when the library gains a treaty: the checkout is
the commit, and the commit does not move.

This command asks the question the pin cannot answer alone. It reads the register,
asks the remote which commit its branch holds now, and says whether the two are
the same. It reads and writes nothing else - no clone, no checkout, no `git fetch`
into anything on this machine - so it is safe to run while a suite is running and
useful before deciding to move the pin.

Three answers, and the third is an answer too:

    exit 0   the pin is the library's head; the server answers from the newest bytes
    exit 1   the pin is not the head: the library has moved, and the server keeps
             answering from the pinned bytes until somebody moves the pin
    exit 2   cannot tell - the register is unreadable, or the remote could not be
             asked - named with the reason, because an unknown is not a no

A commit being different is not the same as this commit being an ancestor of that
one: a rewritten library would report `1` as well, and that is deliberate. The
command states what it asked and what came back, and the link it prints is where a
reader can see the direction the command did not verify.

    python -m itl_mcp.library_pin
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

# The register lives beside the package, in the folder that is `mcp/` when this
# server is committed in the corpus. It is *not* inside the package: an installed
# copy carries code and no register, which is why `default_pin` falls back to the
# corpus checkout the environment names.
PACKAGE = Path(__file__).resolve().parent.parent

EXIT_SAME = 0
EXIT_MOVED = 1
EXIT_UNKNOWN = 2


class PinError(RuntimeError):
    """The register cannot be read, or the remote could not be asked."""


def default_pin() -> Path:
    """The register of the checkout this package is part of, or is run against.

    A checkout has it beside the package. An installed console script does not -
    `pip install git+...#subdirectory=mcp` copies code, not registers - so the
    corpus checkout named by `ITL_CORPUS_ROOT` is asked, which is the same name
    the server itself reads its data by.
    """
    beside = PACKAGE / "provenance" / "library.yaml"
    if beside.is_file():
        return beside
    corpus = os.environ.get("ITL_CORPUS_ROOT", "").strip()
    if corpus:
        return Path(corpus).expanduser() / "mcp" / "provenance" / "library.yaml"
    return beside


def pinned(path: Path) -> tuple[str, str, str]:
    """The repository, the commit, and the day the pin was taken."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as error:
        raise PinError(f"{path} cannot be read: {error}") from error
    if not isinstance(data, dict):
        raise PinError(f"{path} is not a mapping")
    repository = str(data.get("repository") or "")
    commit = str(data.get("commit") or "")
    if not repository:
        raise PinError(f"{path} names no repository")
    if not commit:
        raise PinError(f"{path} names no commit")
    return repository, commit, str(data.get("pinned_on") or "undated")


def remote_head(repository: str, branch: str = "main") -> str:
    """The commit that branch holds now, asked of the remote and nowhere else."""
    try:
        asked = subprocess.run(
            ["git", "ls-remote", "--heads", repository, branch],
            capture_output=True, text=True, check=False)
    except OSError as error:
        raise PinError(f"git could not be run: {error}") from error
    if asked.returncode != 0:
        detail = asked.stderr.strip() or f"exit {asked.returncode}"
        raise PinError(f"git ls-remote {repository} failed: {detail}")
    line = asked.stdout.strip()
    if not line:
        raise PinError(f"{repository} has no {branch} branch")
    return line.split()[0]


def verdict(repository: str, commit: str, head: str) -> tuple[int, str]:
    """What the two commits mean, and the lines that say it."""
    if commit == head:
        return EXIT_SAME, "\n".join((
            f"pinned: {commit}",
            f"head:   {head}  (main)",
            "the pin is the library's head: the server answers from the newest bytes",
        ))
    return EXIT_MOVED, "\n".join((
        f"pinned: {commit}",
        f"head:   {head}  (main)",
        "the pin is not the library's head: the library has moved",
        f"  {repository.rstrip('/')}/compare/{commit}...{head}",
        "  the server keeps answering from the pinned bytes until the pin moves, "
        "and moving it is the edit that says it should answer from these",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m itl_mcp.library_pin",
        description="Ask whether the library has moved past the commit this "
                    "server answers from.")
    parser.add_argument("--pin", type=Path, default=None,
                        help="the register to read (default: the one beside this "
                             "package, or under ITL_CORPUS_ROOT)")
    parser.add_argument("--branch", default="main",
                        help="the branch to ask the remote for (default: main)")
    args = parser.parse_args(argv)

    try:
        repository, commit, pinned_on = pinned(args.pin or default_pin())
        head = remote_head(repository, args.branch)
    except PinError as error:
        print(f"cannot tell: {error}")
        return EXIT_UNKNOWN

    status, text = verdict(repository, commit, head)
    print(text.replace(f"pinned: {commit}", f"pinned: {commit}  (taken {pinned_on})"))
    return status


if __name__ == "__main__":
    sys.exit(main())
