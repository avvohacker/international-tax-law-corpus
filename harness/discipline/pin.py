"""What a pin has to say about the copy it holds, and what it may not say.

A repository of this family that carries rules it did not write carries the pin
that says which bytes travelled and where from - `provenance/vendored-discipline.yaml`,
written by `scripts/vendor-discipline.py` in the corpus, read by the vendored
rule's own test in each repository that holds a copy, and read again by
`scripts/discipline-drift.py` where all three checkouts are.

Until this module existed the rule about that register was stated three times,
once per reader, and the three had drifted: one copy's test refused a pin whose
`source_commit` named a branch or a tag, the other accepted it, and the control
that visits both accepted it everywhere. A rule about a register that says where
bytes came from is worth what its strictest reader is worth, so it is stated once
here.

Five claims are read, and each is refused on its own:

  * every file the pin names is there, and the pin names every file that is;
  * each file's digest is the one the pin records;
  * the source is the corpus, named by URL - the form the machine-trace rule of
    this package recognises as an owner, rather than a bare slug;
  * the source path is `harness/discipline`, which is where the rules live in it;
  * the commit is a git object id. A branch or a tag moves under the checkout
    meant to reproduce the bytes, so a pin naming one describes that ref on the
    day it was read, and not the bytes it meant to pin.

Nothing here reads a repository: the pin and the copies arrive as data, because
the callers differ in where they get them - a test reads the copy beside it, the
control reads the copies of the checkouts it was handed, and one of them hands
this function a pin it has just edited to prove the rule can fail.
"""
from __future__ import annotations

import hashlib
import re
from typing import Mapping

# The repository the discipline comes from, and the path it lives at in it.
# Literal rather than derived from this file: in a copy, this module sits under
# `vendor/discipline/`, and the pin records where the bytes came from.
REPOSITORY = "https://github.com/avvohacker/international-tax-law-corpus"
SOURCE_PATH = "harness/discipline"

# What a pin may name as the commit it came from: a git object id, and nothing
# else. `main` is not one, and a tag is not one either.
COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

# How much of a digest a failure message prints: enough to compare by eye.
SHORT = 12


def digest(data: bytes) -> str:
    """The hash every register in this family records its bytes by."""
    return hashlib.sha256(data).hexdigest()


def problems(pin: Mapping[str, object],
             copies: Mapping[str, bytes]) -> list[str]:
    """Every way these copies are not what this pin declares, named.

    ``pin`` is the parsed register and ``copies`` the files it is about, keyed by
    name - the same two arguments whichever reader is asking.
    """
    stated = pin.get("files") or {}
    if not isinstance(stated, Mapping):
        return [f"the pin's `files` is {type(stated).__name__}, "
                f"and a pin keeps a mapping of name to digest"]

    found: list[str] = []
    for name in sorted(set(stated) | set(copies)):
        if name not in copies:
            found.append(f"{name}: the pin names it, and there is no such file "
                         f"in the copy")
        elif name not in stated:
            found.append(f"{name}: the copy has it, and the pin does not name it")
        elif stated[name] != digest(copies[name]):
            found.append(f"{name}: the pin declares {str(stated[name])[:SHORT]}, "
                         f"and the copy is {digest(copies[name])[:SHORT]}")

    if pin.get("source") != REPOSITORY:
        found.append(f"the pin names the source {pin.get('source')!r}, and the "
                     f"discipline comes from {REPOSITORY}")
    if pin.get("source_path") != SOURCE_PATH:
        found.append(f"the pin names the source path {pin.get('source_path')!r}, "
                     f"and the discipline lives at {SOURCE_PATH}")
    commit = str(pin.get("source_commit") or "")
    if not commit:
        found.append("the pin does not say which commit was vendored")
    elif not COMMIT.match(commit):
        found.append(f"the pin names {commit!r} as the commit it was vendored "
                     f"from, and that is a ref rather than a commit: a branch or "
                     f"a tag moves under the checkout meant to reproduce these "
                     f"bytes")
    return found
