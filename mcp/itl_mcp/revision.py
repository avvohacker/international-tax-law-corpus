"""The commit a checkout is on, when the bytes came from a checkout.

The server answers from files, and a file has no commit: the same page can be
read from a clone, a tarball, or a directory somebody copied. What a commit adds
is the name of the bytes - the thing a reader can fetch to see the same page, and
the thing a pin is made of - so `sources` reports it beside the checkouts it read.

The absence is reported as an absence. A tarball has no commit, and a directory
copied out of one has none either; printing the directory's name in that place
would be inventing a revision, which is the failure this family refuses in data
and must refuse here too. `git` is asked on the machine and nothing else: this
module reaches no network, and the server still answers when git is not there.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def commit(path: Path) -> str | None:
    """The commit ``path`` is on, or ``None`` when it is not a git checkout."""
    try:
        asked = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False)
    except OSError:
        return None
    if asked.returncode != 0:
        return None
    value = asked.stdout.strip()
    return value or None


def described(path: Path) -> dict:
    """The revision as a payload says it: a commit, or the reason there is none."""
    value = commit(path)
    if value:
        return {"commit": value}
    return {
        "commit": None,
        "reason": "this checkout is not a git repository, so its bytes have no "
                  "commit to name",
    }
