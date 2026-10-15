"""Shared fixtures.

The tests read the real corpus and library checkouts, because the point of
this server is that it answers from those artefacts and not from fixtures that
could agree with a bug. When a checkout is not named, the tests that need it
skip with the reason rather than passing vacuously.
"""

import os
from pathlib import Path

import pytest

from itl_mcp.roots import load_roots

CORPUS_ENV = "ITL_CORPUS_ROOT"
LIBRARY_ENV = "ITL_LIBRARY_ROOT"


def _roots_or_skip():
    if not (os.environ.get(CORPUS_ENV) and os.environ.get(LIBRARY_ENV)):
        pytest.skip(f"set {CORPUS_ENV} and {LIBRARY_ENV} to run against the real data")
    try:
        return load_roots()
    except Exception as error:          # noqa: BLE001 - reported, not swallowed
        pytest.skip(f"the named checkouts are not usable: {error}")


@pytest.fixture(scope="session")
def roots():
    return _roots_or_skip()


@pytest.fixture(scope="session")
def corpus_root(roots):
    return roots.corpus


@pytest.fixture(scope="session")
def library_root(roots):
    return roots.library
