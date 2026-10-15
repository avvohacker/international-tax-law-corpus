"""The workflow reader, re-exported from the shared discipline.

`vendor/discipline/ci.py` is the one implementation - the corpus' own, copied
verbatim and pinned in `provenance/vendored-discipline.yaml`. This module stays
because the board and the floor test import the reader as `itl_mcp.ci`, and a
second import path is much cheaper than a second copy of the rules. A second copy
is what this used to be: this one had learned to read the `repository:` keys a
workflow checks out, the other two could not, and nothing compared them.

The extra path entry is this repository's root, because `vendor/` sits beside the
package rather than inside it, and the package is imported both from a checkout
and from an installed console script.

`repository` is the one thing here that is not a re-export, and it exists because
of where the package now lives. See its docstring.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vendor.discipline.ci import (  # noqa: E402,F401 - re-exported on purpose
    EXPRESSION,
    NAME,
    VERSION,
    checked_out_repositories,
    floor,
    interpreters,
    matrix_interpreters,
    order,
    runs_pytest,
    suspect,
    values_for,
    workflows,
)


def repository(root: Path) -> Path:
    """The checkout whose workflows run the tests committed under ``root``.

    This package used to be a repository of its own, with its workflows at its own
    root, and every reading of them was a reading of ``ROOT``. It is now committed
    inside the corpus, under `mcp/`: GitHub reads the workflows of a repository
    from its root and from nowhere else, so the control that asks this package's
    questions and runs its tests is
    `.github/workflows/mcp-drift.yml` of the repository that holds the package, and
    a workflow under `mcp/.github/` would look like a control and never be run.

    So the readings walk up to the first checkout that has workflows at all. A
    standalone checkout of the server answers with itself, and the board and the
    floor test read the same answer from here - which is the point: two of them
    guessing differently is the drift the shared discipline exists to refuse.

    The floor itself is not read from here. It is the claim `pyproject.toml` of
    *this* package makes about the interpreter a user may install it on, and it
    stays that package's own sentence wherever the package is committed.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".github" / "workflows").is_dir():
            return candidate
    return root


__all__ = [
    "EXPRESSION",
    "NAME",
    "VERSION",
    "checked_out_repositories",
    "floor",
    "interpreters",
    "matrix_interpreters",
    "order",
    "repository",
    "runs_pytest",
    "suspect",
    "values_for",
    "workflows",
]
