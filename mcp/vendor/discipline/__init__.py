"""The discipline this family shares, in one implementation.

The corpus, the library, and the server committed inside the corpus are three
layers on purpose: the interface between them is data, their life cycles differ,
and a contributor to one treaty should not have to clone a corpus. What they
should *not* have three of is the rules they hold themselves to - and until this
package existed they did:

  * `machine_traces.py`, the rule that nothing committed may describe the machine
    it was built on (invariant F14 here), carried three wordings, three
    exemption lists, and three different answers to whether the checkout's own
    directory name is a trace;
  * `ci.py`, the reader that holds a declared floor against the workflow that
    runs, carried one function in the server that the other two could not call;
  * the rule of the generated status board was a paragraph of prose in each
    repository and a convention in each script, and nothing compared the three;
  * the rule about `provenance/vendored-discipline.yaml` - what the pin of a
    copy has to say, and what it may not say - was in each copy's own test and
    in the reader the control runs, and the three had drifted: one refused a pin
    whose `source_commit` named a branch or a tag, the others accepted it;
  * the rule about where the documents of a repository send a reader who wants
    the server was a test in each repository, and the two were two readings of
    one rule - one of them had found its own failure and the other had not;
  * the rule about what a run of the control holds, and what it leaves to another
    repository's run, was the comment on one job and a paragraph in one document,
    and nothing read either - so the corpus' job went on reporting a copy nobody
    in the corpus could write.

This package is where those rules live now, once. It is vendored verbatim into
the other two layers by `scripts/vendor-discipline.py` - the library, and the
server folder `mcp/` here - pinned there by hash in
`provenance/vendored-discipline.yaml` and held by a test, and
`scripts/discipline-drift.py` runs the same checks over the checkouts each run of
it is handed, as CI sees them - so a copy that goes back to inventing its own
version is a red run in whichever layer holds it, not a discovery made months
later by hand. Which checkouts a run is handed is the run's own business, and it
is built on the half a repository can repair: this repository's job reads the
corpus and the server committed inside it, and the library reads its own copy
against this corpus.

The vendoring is the idiom these repositories already use for the bytes they do
not own (a source PDF, a published edition, a recorded answer): the copy travels,
the hash of the copy is the contract, and the register says where it came from.
"""
from . import board, ci, documents, holds, machine_traces, pin

__all__ = ["board", "ci", "documents", "holds", "machine_traces", "pin"]
