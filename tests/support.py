"""Shared helpers for the test suite."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNBUILT = (
    "RED by design: {what} does not exist yet. This test states the target of\n"
    "the rebuild (see SPEC.md), so a failure here is the specification talking,\n"
    "not a broken test. It turns green when the extractor produces the artefact."
)


def provenance(*parts: str) -> Path:
    return ROOT.joinpath("provenance", *parts)
