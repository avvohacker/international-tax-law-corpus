"""The workflow reader, re-exported from the shared discipline.

`harness/discipline/ci.py` is the one implementation, vendored verbatim into
`international-tax-law-library` and `international-tax-law-mcp`; this module
stays because the floor test and the board read the reader as `harness.ci`, and a
second import path is much cheaper than a second copy of the rules. A second copy
is what this used to be, and it had already drifted from the other two.
"""
from harness.discipline.ci import (  # noqa: F401 - re-exported on purpose
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

__all__ = [
    "EXPRESSION",
    "NAME",
    "VERSION",
    "checked_out_repositories",
    "floor",
    "interpreters",
    "matrix_interpreters",
    "order",
    "runs_pytest",
    "suspect",
    "values_for",
    "workflows",
]
