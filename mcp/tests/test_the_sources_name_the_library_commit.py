"""The `sources` answer says which bytes answered, not only which files.

A reader who checks a citation needs two things: the page, and the revision the
page was read from. The page is in the answer already; this file holds the second
half, and the two ways it can be wrong:

  * the revision can be somebody else's - the corpus' instead of the library's,
    which looks right on a machine where both are checkouts of the same family
    and is a different repository entirely;
  * the revision can be invented. A tarball has no commit, and a directory copied
    out of one has none either: a server that printed the directory's name in
    that place would name a revision a reader could not fetch, which is exactly
    the invention the data rules refuse.

The commit is read from git on the machine and nothing else, so the test asks git
for the same thing and compares - the failure it exists for is the wiring, not
the reading: a payload that carried the corpus' commit would be well-formed,
plausible, and wrong.
"""
import json
import subprocess

import pytest

from itl_mcp import revision


def _git(path) -> str:
    asked = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True)
    return asked.stdout.strip()


def test_the_library_commit_is_the_library_s(library_root, corpus_root):
    assert revision.commit(library_root) == _git(library_root)
    # The two checkouts are different repositories; a payload that carried the
    # wrong one would be well-formed and would name bytes it never read.
    assert revision.commit(library_root) != _git(corpus_root)


def test_a_directory_that_is_not_a_checkout_has_no_commit_and_says_why(tmp_path):
    described = revision.described(tmp_path)
    assert described["commit"] is None, described
    assert described["reason"].strip(), (
        "a checkout with no revision said so with no reason: the gap has to be "
        "named, or a reader cannot tell a tarball from a bug")


def test_the_sources_answer_carries_the_library_revision(roots, library_root):
    from itl_mcp import server

    payload = json.loads(server.sources())
    assert payload["library_revision"]["commit"] == _git(library_root), (
        "the `sources` answer does not name the commit the library is on: a "
        "reader can check the page but not the revision, and the pin this "
        "repository answers from is exactly the fact that is missing")
    assert payload["corpus_root"] and payload["library_root"], (
        "the two roots are where this process read from, and the answer is "
        "about what it read")


def test_a_payload_built_without_a_checkout_states_the_absence(tmp_path):
    """The same reading the server takes, on bytes that never had a commit."""
    described = revision.described(tmp_path)
    assert set(described) == {"commit", "reason"}
    assert described["commit"] is None
