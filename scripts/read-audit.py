"""What a command really reads here, in files and in bytes.

The compatibility jobs spend most of their wall clock on the fetch and then read
what they fetched, so "can a job be given less" is a question about bytes, not
about impressions. This script answers it: it runs a command with the reads
recorded and prints the distinct files and their bytes, by top-level directory.

    python scripts/read-audit.py module harness drift
    python scripts/read-audit.py pytest -q

Three hooks, because three things read: `builtins.open` and `pathlib.Path.open`
for the JSON, YAML and markdown, and `fitz.open` for the PDFs - PyMuPDF opens a
file in C, where the Python hooks never see it, and the PDFs are 129 of the 151
MB this repository's control reads.

The number it prints is the bytes that had to be *there*, counted once per file
however many times the file is opened: a job cannot be given less than the files
it reads, and 116 source files read by both the drift control and the suite is
the reason the fetchers in `.github/workflows/corpus-drift.yml` cache the public
bytes across jobs instead of downloading them again.
"""

from __future__ import annotations

import builtins
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(os.environ.get("READ_AUDIT_ROOT") or Path(__file__).resolve().parent.parent)
READ: dict[str, dict] = {}
OPENS = 0


def _note(source, path) -> None:
    """Record one file read under ROOT, once, with the size it had to have."""
    global OPENS
    try:
        raw = os.fspath(path)
    except TypeError:
        return
    if not isinstance(raw, str) or (raw.startswith("<") and raw.endswith(">")):
        return
    absolute = os.path.realpath(os.path.join(ROOT, raw))
    if not absolute.startswith(str(ROOT) + os.sep):
        return
    entry = READ.setdefault(absolute, {"opens": 0, "bytes": 0, "via": set()})
    entry["opens"] += 1
    entry["via"].add(source)
    OPENS += 1
    try:
        entry["bytes"] = os.path.getsize(absolute)
    except OSError:
        entry["bytes"] = 0


def _is_read(mode) -> bool:
    """Whether a mode reads: `r`, `r+`, and nothing that truncates."""
    return isinstance(mode, str) and ("r" in mode or "+" in mode) \
        and not any(letter in mode for letter in "wax")


_open = builtins.open
_path_open = Path.open


def audited_open(file, mode="r", *args, **kwargs):
    if _is_read(mode):
        _note("open", file)
    return _open(file, mode, *args, **kwargs)


def audited_path_open(self, mode="r", *args, **kwargs):
    if _is_read(mode):
        _note("Path.open", self)
    return _path_open(self, mode, *args, **kwargs)


builtins.open = audited_open
Path.open = audited_path_open

try:  # imported here as well as by the reader, so the hook is in place first
    import fitz

    _fitz_open = fitz.open

    def audited_fitz_open(*args, **kwargs):
        if args:
            _note("fitz.open", args[0])
        return _fitz_open(*args, **kwargs)

    fitz.open = audited_fitz_open
except ImportError:  # pragma: no cover - commands that never touch a PDF
    pass


def report() -> None:
    rows = sorted(READ.items())
    total = sum(row["bytes"] for _, row in rows)
    print(f"\nread by this command under {ROOT}:")
    print(f"  {len(rows)} files, {OPENS} opens, {total} bytes")
    buckets: dict[str, list[int]] = {}
    for path, row in rows:
        top = os.path.relpath(path, ROOT).split(os.sep)[0]
        bucket = buckets.setdefault(top, [0, 0])
        bucket[0] += 1
        bucket[1] += row["bytes"]
    for top in sorted(buckets):
        count, size = buckets[top]
        print(f"  {top:<14} {count:>5} files {size:>12} bytes")
    sources = [(path, row) for path, row in rows
               if os.path.relpath(path, ROOT).startswith("sources" + os.sep)]
    if sources:
        print(f"  sources: {len(sources)} of them, "
              f"{sum(row['bytes'] for _, row in sources)} bytes")
        for path, row in sources:
            print(f"    {os.path.relpath(path, ROOT):<58} "
                  f"{row['opens']:>3} opens {row['bytes']:>10} bytes")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    kind, rest = argv[1], argv[2:]
    if kind == "module":
        sys.argv = rest
        sys.path.insert(0, str(ROOT))
        try:
            runpy.run_module(sys.argv[0], run_name="__main__", alter_sys=True)
            code = 0
        except SystemExit as exit_:
            code = int(exit_.code or 0)
        report()
        return code
    if kind == "pytest":
        import pytest

        code = int(pytest.main(rest))
        report()
        return code
    print(f"unknown command {kind!r}: expected `module` or `pytest`", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
