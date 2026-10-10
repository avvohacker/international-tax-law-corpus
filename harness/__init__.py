"""The fidelity harness.

Two halves, deliberately separated:

* what the corpus must satisfy      → fixtures/invariants.yaml   (green: meta-tests)
* what it must stop containing      → fixtures/known_defects.yaml (red: probes)

Nothing in here knows about the extractor. It only knows what "faithful" means.
"""
from harness.checks import Result, evaluate
from harness.defects import Defect, Invariant, load_defects, load_invariants

__all__ = [
    "Defect", "Invariant", "Result", "evaluate",
    "load_defects", "load_invariants",
]
