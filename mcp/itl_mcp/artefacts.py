"""Read an artefact of the two checkouts once per run, not once per question.

This server owns no data: every answer is read out of the artefacts committed in
``international-tax-law-corpus`` and ``international-tax-law-library``, and every
check that stands behind an answer recomputes its hash from those same bytes. So
the same file is read and hashed again for each question that touches it, and the
cost of that is measurable with the corpus' own ``scripts/read-audit.py``: the
suite has to have 116 files and 14 MB present, and it opened them 640 times,
moving 240 MB - 94% of it the same two edition ledgers, hashed again for the next
tool call and the one after.

A run answers from read-only checkouts, so one path is one set of bytes, and this
module remembers what it read:

    text(path)      the decoded text
    document(path)  the parsed JSON document
    sha256(path)    the digest of the bytes, streamed

What it remembers is keyed on the file's size and its ``mtime``, so an artefact
edited under a running process is read again. That is the one case a run has to
get right, and it is why the key is not the path alone. What the key cannot see
is an in-place write that leaves both size and mtime exactly as they were - a
same-length edit inside one clock tick. Nothing in this family's checkouts does
that, and ``forget()`` is there for a caller that knows it has.

Two boundaries, both on purpose:

  * **the two checkouts only**. This repository's own files - the recorded
    answers in ``fixtures/``, the board in ``docs/`` - are written by its own
    tools in the same process, and a memo over those would be a way to read what
    you just wrote rather than what is there;
  * **documents are handed out, not copied**. ``document()`` gives back the object
    it parsed; the second caller gets the same object, which is what makes the
    second call free. A caller that means to change what it read must copy it
    first. Every reader in this package treats what it read as the record.

``counters()`` reports what the memo cost - one miss per file read, one hit per
file served from memory - which is the number the read-audit prints as bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

# The cache, keyed by (path, size, mtime_ns). A key is what a file *is*, so a
# file that changes gains a new key and is read again; the stale entry is left
# where it is, to be collected by `forget` or by the process ending.
_READ: dict[tuple[str, int, int], Any] = {}
_MISSES = 0
_HITS = 0


def _key(path: Path) -> tuple[str, int, int]:
    """What is being remembered: which file, how big, and as of when.

    ``stat()`` raises ``FileNotFoundError`` for a path that is not there, which
    is what ``open()`` did here before: a caller asking for a file that is
    absent is told, not answered from nothing.
    """
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def _remember(path: Path, produce: Callable[[], Any]) -> Any:
    global _MISSES, _HITS
    key = _key(path)
    if key in _READ:
        _HITS += 1
        return _READ[key]
    _MISSES += 1
    _READ[key] = produce()
    return _READ[key]


def text(path: Path) -> str:
    """The file's text, decoded, read once."""
    return _remember(path, lambda: path.read_text(encoding="utf-8"))


def document(path: Path) -> Any:
    """The file's parsed JSON document, read once.

    Returned as it was parsed, so the next caller for the same bytes gets the
    same object and no second parse. Read it; do not change it.
    """
    return _remember(path, lambda: json.loads(path.read_text(encoding="utf-8")))


def sha256(path: Path) -> str:
    """The digest of the file's bytes, streamed, computed once.

    Streamed rather than read whole: the two edition ledgers are 4.7 MB and
    3.9 MB, and a digest is the answer to a question about bytes that are
    already on disk.
    """
    return _remember(path, lambda: _digest(path))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def forget(path: Path | None = None) -> None:
    """Drop what was remembered about one file, or about everything.

    For a caller that has changed a file in a way the key cannot see, or that
    wants a run to start from nothing.
    """
    global _MISSES, _HITS
    if path is None:
        _READ.clear()
        _MISSES, _HITS = 0, 0
        return
    prefix = str(path)
    for key in [key for key in _READ if key[0] == prefix]:
        del _READ[key]


def counters() -> dict[str, int]:
    """How many files were read, and how many times one was served from memory."""
    return {"files": len(_READ), "misses": _MISSES, "hits": _HITS}
