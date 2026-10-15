"""Nothing this folder commits is too large for its largest reader.

The server is meant to be read where it stands: by a person, by a clone, and by
GitHub's own MCP server, which is the reader most likely to be pointed at this
repository *before* anybody installs anything. That reader returns a file's full
content up to 1 MB; between 1 MB and 100 MB it hands back the bytes only on
request, as `raw`; above 100 MB it refuses. As of this writing the folder's
largest committed file is 47 KB - `itl_mcp/verdict.py` - so the whole layer is
readable in full, and this file is what keeps that true.

The failure it exists for is quiet. Prose grows, a fixture gains answers, a
module doubles: no test in this suite would notice, because nothing here cares
how many bytes a file has, and the first thing to break would be the one reader
nobody can run from a desk. So the limit is stated once, with the number, and a
file over it is a failure that names the file and its size.

The neighbour it deliberately does not police: the corpus and the library commit
three files over 1 MB on purpose - the sealed 2021 PDF, and the two span ledgers
that prove every sentence's page. Those are read as `raw` and no context holds
them; naming them here would be a check on another repository's design decisions.
"""
import subprocess
from pathlib import Path

from itl_mcp import ci

ROOT = Path(__file__).resolve().parents[1]

# The full-content limit of the GitHub contents API, in bytes.
LIMIT = 1 << 20


def committed(folder: Path) -> dict[str, int]:
    """Every file the holding repository commits under ``folder``, with its size.

    Read from the working tree: what this checks is what a clone carries.
    """
    holder = Path(ci.repository(folder))
    listed = subprocess.run(
        ["git", "-C", str(holder), "ls-files", "-z", str(folder.relative_to(holder))],
        capture_output=True, text=True, check=True)
    sizes: dict[str, int] = {}
    for name in listed.stdout.split("\0"):
        if name:
            path = holder / name
            sizes[str(path.relative_to(folder.parent))] = path.stat().st_size
    return sizes


def oversized(sizes: dict[str, int], limit: int = LIMIT) -> list[str]:
    """The files a reader would not get in full, named with their size."""
    return [f"{name}: {size} bytes, over the {limit}-byte limit"
            for name, size in sorted(sizes.items()) if size > limit]


def test_no_committed_file_here_is_too_large_to_read_in_full():
    """The whole committed folder, read the way its largest reader reads it."""
    sizes = committed(ROOT)
    assert sizes, "no committed file was read, so this check is about nothing"
    problems = oversized(sizes)
    assert not problems, (
        "a committed file is larger than a reader that returns content up to "
        f"{LIMIT} bytes, so this layer is no longer readable in full everywhere it "
        "is meant to be read; split it, or say in the README why it must be raw:\n  "
        + "\n  ".join(problems))


def test_the_checker_fails_on_a_file_over_the_limit():
    """The positive control: a check that only sees passing files proves nothing.

    The boundary itself is asserted too - a file exactly at the limit is
    returned in full by the reader this limit is copied from, so it passes, and a
    check that failed on it would be stricter than the thing it stands for.
    """
    assert oversized({"mcp/itl_mcp/verdict.py": LIMIT + 1}), \
        "a file one byte over the limit was accepted"
    assert oversized({"mcp/a": 4 * LIMIT}), "a file far over the limit was accepted"
    assert not oversized({"mcp/a": LIMIT}), "the limit itself is allowed to pass"
    found = oversized({"mcp/big": LIMIT + 1, "mcp/small": 10})
    assert len(found) == 1 and "mcp/big" in found[0] and "mcp/small" not in found[0]
