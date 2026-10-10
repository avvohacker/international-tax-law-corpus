"""Every probe in the catalogue, run against this repository.

One test per defect, so that a failure names the defect instead of the harness.

The three outcomes, and why a skip is not a pass:

  the probe ran and found nothing      -> the test passes
  the probe ran and found the defect   -> the test fails, with file and line
  the probe had nothing to inspect     -> the test skips, and says what is
                                          missing and which invariant is waiting

A skip here is the honest form of "not yet". It is also visible: run with
`-ra` (already the default, see pyproject.toml) and every skip prints its
reason. `tests/test_invariants.py` is where a missing artefact becomes a
failure; this file refuses to pretend it has evidence it does not have.
"""
import pytest

from harness import evaluate, load_defects
from support import ROOT

DEFECTS = load_defects()


@pytest.mark.parametrize("defect", DEFECTS, ids=[d.id for d in DEFECTS])
def test_defect_is_absent(defect):
    result = evaluate(defect, ROOT)
    if not result.evaluated:
        pytest.skip(
            f"cannot speak: {result.detail} - the artefact this probe inspects "
            f"does not exist yet ({defect.invariant}: {defect.title})")
    assert result.ok, (
        f"{defect.id} - {defect.title}\n"
        f"    invariant: {defect.invariant}\n"
        f"    expected:  {defect.evidence.strip()[:200]}\n"
        f"    found:     {result.detail}")


def test_the_catalogue_was_actually_run():
    """A catalogue that silently loads nothing would make this file vacuous."""
    assert DEFECTS, "no defects loaded from fixtures/known_defects.yaml"
