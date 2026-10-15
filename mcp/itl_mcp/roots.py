"""Locate the corpus and library checkouts this server answers from.

This server owns no data. It reads the artefacts committed in two sibling
repositories and refuses to answer from anything else. A checkout is found by
environment variable, never by guessing a path, so an answer always comes from
a place the operator named and can point at.

    ITL_CORPUS_ROOT    the international-tax-law-corpus checkout
    ITL_LIBRARY_ROOT   the international-tax-law-library checkout

Both must exist and must look like the repository they claim to be; a path
that exists but holds the wrong artefacts is an error, not a near miss, so a
misconfiguration surfaces at startup instead of as a subtly wrong answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CORPUS_ENV = "ITL_CORPUS_ROOT"
LIBRARY_ENV = "ITL_LIBRARY_ROOT"


class RootsError(RuntimeError):
    """A checkout is missing, or is not the repository it claims to be."""


@dataclass(frozen=True)
class Roots:
    corpus: Path
    library: Path


def _require(env: str) -> Path:
    raw = os.environ.get(env, "").strip()
    if not raw:
        raise RootsError(
            f"{env} is not set. This server reads the corpus and library from "
            f"local checkouts; name them before asking anything, e.g.\n"
            f"  export {env}=/path/to/international-tax-law-{'corpus' if 'CORPUS' in env else 'library'}"
        )
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise RootsError(f"{env}={path} is not a directory")
    return path


def _looks_like_corpus(root: Path) -> bool:
    return (root / "corpora").is_dir() and (root / "provenance" / "sources.yaml").is_file()


def _looks_like_library(root: Path) -> bool:
    return (root / "treaties").is_dir() and (root / "provenance" / "treaties.yaml").is_file()


def load_roots(
    corpus: str | Path | None = None,
    library: str | Path | None = None,
) -> Roots:
    """Resolve and validate both checkouts.

    Explicit arguments win over the environment, which lets the tests point at
    fixtures without mutating the process environment.
    """
    corpus_path = Path(corpus).expanduser() if corpus else _require(CORPUS_ENV)
    library_path = Path(library).expanduser() if library else _require(LIBRARY_ENV)

    if not corpus_path.is_dir():
        raise RootsError(f"corpus root {corpus_path} is not a directory")
    if not _looks_like_corpus(corpus_path):
        raise RootsError(
            f"{corpus_path} does not look like the corpus: expected a corpora/ "
            f"directory and provenance/sources.yaml inside it"
        )
    if not library_path.is_dir():
        raise RootsError(f"library root {library_path} is not a directory")
    if not _looks_like_library(library_path):
        raise RootsError(
            f"{library_path} does not look like the library: expected a treaties/ "
            f"directory and provenance/treaties.yaml inside it"
        )
    return Roots(corpus=corpus_path, library=library_path)
