"""The discipline the three repositories share, in one implementation.

`international-tax-law-corpus`, `international-tax-law-library` and
`international-tax-law-mcp` are three repositories on purpose: the interface
between them is data, their life cycles differ, and a contributor to one treaty
should not have to clone a corpus. What they should *not* have three of is the
rules they hold themselves to - and until this package existed they did:

  * `machine_traces.py`, the rule that nothing committed may describe the machine
    it was built on (invariant F14 here), carried three wordings, three
    exemption lists, and three different answers to whether the checkout's own
    directory name is a trace;
  * `ci.py`, the reader that holds a declared floor against the workflow that
    runs, carried one function in the server that the other two could not call;
  * the rule of the generated status board was a paragraph of prose in each
    repository and a convention in each script, and nothing compared the three.

This package is where those rules live now, once. It is vendored verbatim into
the other two repositories by `scripts/vendor-discipline.py`, pinned there by
hash in `provenance/vendored-discipline.yaml` and held by a test, and
`scripts/discipline-drift.py` runs the same checks over all three checkouts as
CI sees them - so a copy that goes back to inventing its own version is a red
run in the repository that holds it, not a discovery made months later by hand.

The vendoring is the idiom these repositories already use for the bytes they do
not own (a source PDF, a published edition, a recorded answer): the copy travels,
the hash of the copy is the contract, and the register says where it came from.
"""
from . import board, ci, machine_traces

__all__ = ["board", "ci", "machine_traces"]
