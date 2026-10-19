"""The question the pin cannot ask alone, and the three answers it can give.

`provenance/library.yaml` names the commit the server answers from, and a pin does
not move by itself: when the library gains a treaty, nothing in this checkout says
so. `python -m itl_mcp.library_pin` asks the remote and reports one of three
things, and the third is the one worth a test of its own - an unknown is an answer,
not a `no`, and a command that turned an unreachable remote into "the pin is the
head" would say the library never moves.

What is tested here is the reading and the verdict, not the network: the remote is
asked in one function, and these tests hand the verdict the two commits directly.
The CLI is exercised on a register that cannot be read, which is the branch that
must not reach the remote at all.
"""
import re
from pathlib import Path

import pytest

from itl_mcp import library_pin

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "provenance" / "library.yaml"


PINNED = "1fc9176de80f14cb7c4ef2192347b9171248b1bb"
LATER = "dd505f4969b4c475b0b7399f52e3991804c983b5"
REPOSITORY = "https://github.com/avvohacker/international-tax-law-library"


def test_no_module_the_server_answers_with_imports_the_command():
    """The board says so: the command reaches a remote, the tools must not."""
    importers = []
    for path in sorted((ROOT / "itl_mcp").glob("*.py")):
        if path.name == "library_pin.py":
            continue
        if re.search(r"^\s*(?:from|import)\s+.*\blibrary_pin\b",
                     path.read_text(encoding="utf-8"), re.M):
            importers.append(path.name)
    assert not importers, (
        f"{', '.join(importers)} import the library pin command, which runs the "
        f"`git` on the machine and asks a remote: the answering path is made of "
        f"committed bytes and refuses a dependency on the network")


def test_the_command_finds_the_register_of_the_checkout_it_runs_in():
    """The pin is beside the package, not inside it, and the command must know that."""
    assert library_pin.default_pin() == PIN, (
        "the command looked for the register somewhere other than the checkout "
        "it is part of: an installed copy carries no register, so the checkout "
        "is where this file has to be found")


def test_the_register_this_repository_ships_is_a_commit():
    """The command reads the real register, so the real register has to hold."""
    repository, commit, pinned_on = library_pin.pinned(PIN)
    assert repository == REPOSITORY
    assert len(commit) == 40 and set(commit) <= set("0123456789abcdef"), commit
    assert pinned_on != "undated", (
        "the pin does not say when it was taken: a reader cannot tell whether "
        "the library has moved since")


def test_a_pin_that_is_the_head_says_so():
    status, text = library_pin.verdict(REPOSITORY, PINNED, PINNED)
    assert status == library_pin.EXIT_SAME, text
    assert "the pin is the library's head" in text
    assert "has moved" not in text


def test_a_pin_the_library_moved_past_names_both_commits_and_the_link():
    status, text = library_pin.verdict(REPOSITORY, PINNED, LATER)
    assert status == library_pin.EXIT_MOVED, text
    assert PINNED in text and LATER in text
    assert f"{REPOSITORY}/compare/{PINNED}...{LATER}" in text
    # The command says what it verified and no more: two different commits are
    # not a proven ancestry, so the wording is "moved", not "ahead by N".
    assert "ahead" not in text


def test_an_unreadable_register_is_cannot_tell_and_never_asks_the_remote(
        tmp_path, capsys, monkeypatch):
    """An unknown is an answer, and it is not the answer 'the pin is the head'."""
    register = tmp_path / "library.yaml"
    register.write_text("repository: https://example.invalid/x\n", encoding="utf-8")

    def refuse(*args, **kwargs):  # pragma: no cover - reached only on a bug
        raise AssertionError("the remote was asked about a register with no commit")

    monkeypatch.setattr(library_pin, "remote_head", refuse)

    status = library_pin.main(["--pin", str(register)])
    printed = capsys.readouterr().out
    assert status == library_pin.EXIT_UNKNOWN, printed
    assert printed.startswith("cannot tell:"), printed
    assert "names no commit" in printed, printed
