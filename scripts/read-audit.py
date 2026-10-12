"""What a command really reads here, in files and in bytes.

The compatibility jobs spend most of their wall clock on the fetch and then read
what they fetched, so "can a job be given less" is a question about bytes, not
about impressions. This script answers it: it runs a command with the reads
recorded and prints the distinct files and their bytes, by top-level directory.

    python scripts/read-audit.py module harness drift
    python scripts/read-audit.py pytest -q
    python scripts/read-audit.py --top 12 pytest -q

`--top N` names the N largest files the command read, which is the half that
says *where* a job's cost is: a total is a number to argue about, and the
twelve files under it are a list to act on.

Three hooks, because three things read: `builtins.open` and `pathlib.Path.open`
for the JSON, YAML and markdown, and `fitz.open` for the PDFs - PyMuPDF opens a
file in C, where the Python hooks never see it, and the PDFs are 129 of the 151
MB this repository's control must have present.

Two numbers matter and they answer different questions. The files and the bytes
are what had to be *there*, counted once per file however many times it was
opened - a job cannot be given less than the files it reads. The `opened as it
was` line is what the job actually moved, and the difference between the two is
the cost of reading the same file again: `Path.read_text` and `json.load` read a
file whole, so for these files one open is one file's worth of bytes. A command
that reads 116 files and 14 MB, and opens them 640 times, moved 240 MB.

The second number is the one a reader can act on: reading a file again costs
what it costs, and only the reader can stop doing it. The first is the one that
cannot be argued down - a job cannot be given less than the files it reads,
which is why the fetchers in `.github/workflows/corpus-drift.yml` cache the
public bytes across jobs instead of downloading them again.
"""

from __future__ import annotations

import builtins
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(os.environ.get("READ_AUDIT_ROOT")
            or Path(__file__).resolve().parent.parent).resolve()
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


def report(top: int = 0) -> None:
    """What was read, how often, and what the repetitions cost."""
    rows = sorted(READ.items())
    total = sum(row["bytes"] for _, row in rows)
    print(f"\nread by this command under {ROOT}:")
    print(f"  {len(rows)} files, {OPENS} opens, {total} bytes")
    buckets: dict[str, list[int]] = {}
    for path, row in rows:
        top_level = os.path.relpath(path, ROOT).split(os.sep)[0]
        bucket = buckets.setdefault(top_level, [0, 0])
        bucket[0] += 1
        bucket[1] += row["bytes"]
    for top_level in sorted(buckets):
        count, size = buckets[top_level]
        print(f"  {top_level:<14} {count:>5} files {size:>12} bytes")
    again = sum((row["opens"] - 1) * row["bytes"] for _, row in rows)
    opened = sum(row["opens"] * row["bytes"] for _, row in rows)
    print(f"  opened as it was: {opened} bytes read, {total} of them once; "
          f"the {again} read again are {again / opened:.0%} of that"
          if opened else "  nothing was read")
    for path, row in sorted(rows, key=lambda pair: -pair[1]["bytes"])[:top]:
        print(f"  {os.path.relpath(path, ROOT):<58} "
              f"{row['opens']:>3} opens {row['bytes']:>10} bytes")
    sources = [(path, row) for path, row in rows
               if os.path.relpath(path, ROOT).startswith("sources" + os.sep)]
    if sources:
        print(f"  sources: {len(sources)} of them, "
              f"{sum(row['bytes'] for _, row in sources)} bytes")
        for path, row in sources:
            print(f"    {os.path.relpath(path, ROOT):<58} "
                  f"{row['opens']:>3} opens {row['bytes']:>10} bytes")


def split_top(argv: list[str]) -> tuple[int, list[str]]:
    """Pull `--top N` out of the arguments, which the rest also has to see."""
    rest, top, index = [], 0, 0
    while index < len(argv):
        if argv[index] == "--top" and index + 1 < len(argv):
            top, index = int(argv[index + 1]), index + 2
            continue
        rest.append(argv[index])
        index += 1
    return top, rest


def main(argv: list[str]) -> int:
    top, argv = split_top(argv)
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
        report(top)
        return code
    if kind == "pytest":
        import pytest

        code = int(pytest.main(rest))
        report(top)
        return code
    print(f"unknown command {kind!r}: expected `module` or `pytest`", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
