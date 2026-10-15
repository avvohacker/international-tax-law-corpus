# The verdict, committed: a study

Written 2026-10-15. A study, not a plan: what it would take for an as-modified
verdict to exist as a committed, regenerable artefact, measured on this corpus
and the library as they stand, so the choice can be made with the numbers.

## The question

Today a verdict is an **event**: the answer is computed from the artefacts at the
moment somebody asks, and nothing about it survives the process. That is strong —
nothing can be stale — and it has one cost that matters: an answer exists only
where the server runs, so a reader who installs nothing has the inputs and not
the answer.

The alternative is an artefact: one file per treaty, committed, regenerated from
the data, readable by anything that can read a file.

## What it would be, in bytes

Measured on the two treaties the library holds, from the payload the tool
returns:

| treaty | whole payload | provenance checks | the chain | of which prose | of which excerpts | a citable skeleton |
| --- | --- | --- | --- | --- | --- | --- |
| `no-uk-2013` | **75.8 KB** | 12.6 KB | 52.0 KB | 4.0 KB | 29.6 KB | **8.4 KB** |
| `uk-us-2001` | **23.9 KB** | 15.6 KB | none (not modified) | — | — | **2.3 KB** |

Two shapes are therefore available and they are not the same decision:

* **the whole payload** (24–76 KB per treaty) — everything the tool answers,
  committed. Self-contained, and it duplicates, verbatim, excerpts of the
  positions documents that are already committed in the corpus.
* **a citable skeleton** (2–9 KB per treaty) — the verdict, the Articles that act
  with their mode and the pages they were read from, the lookups, the silences
  and the input hashes, and *not* the prose and *not* the quoted excerpts. What
  it drops is exactly what a reader can already fetch from the position document
  it came from.

## Where it would live, and the constraint that decides it

The verdict is not computable in the corpus alone. `as_modified_verdict` refuses
a treaty the library does not hold, because the treaty's own side — its parties,
its signature date — is the library's, not the corpus'. So a table of verdicts is
a table **about the library's treaties**, and there are two honest homes:

* **the library**, one file beside each treaty: the artefact travels with the
  thing it is about, and the corpus keeps the rules that decide it. The cost is
  that the regeneration command lives in the corpus while the file is here;
* **the corpus**, under `derived/`: the precedent exists — the corpus already
  commits derived views it regenerates and compares byte for byte — but those are
  derived from *this repository's* sources, and this one would be derived from
  another repository's holdings, which the corpus has refused so far.

Either way the artefact must carry the two commits it was computed against, the
same way every other artefact here carries the hash of what it was read from. An
artefact without them is an answer that cannot say which data it is an answer
about.

## What it gains

1. **The plus becomes readable without installing anything.** GitHub's own MCP
   server returns a file's content in full up to 1 MB, and a skeleton is 2–9 KB:
   a reader who installs nothing could read the verdict, the Articles behind it
   and the rows, instead of having to reconstruct them. This is the only route to
   that, and it is the strongest argument for the artefact.
2. **An answer becomes an object with an identity.** Today two readers asking the
   same question get the same answer and no way to name it. Committed, an answer
   has a commit, a blob hash and a diff against the previous corpus version — the
   verdict becomes citable the way a page already is.
3. **Asking gets cheaper.** The two verdicts and a refusal read seven artefacts,
   441.5 KB, on every call. Against a committed artefact the tool reads a few
   kilobytes and verifies the input hashes, which is the difference between
   recomputing an answer and checking one.

## What it costs

1. **It can be stale, and that is a new failure mode.** A computed answer cannot
   be yesterday's; a committed one can. The remedy is not optional: the artefact
   carries the corpus and library commits and the hashes of every input, the tool
   **refuses** when any of them has moved, and the regeneration is part of the
   corpus's own build. Paid that price, the artefact is never wrong — but the
   failure appears as a refusal where the answer used to be, in the window
   between a data change and a regeneration.
2. **Two places to keep in step.** The corpus already runs one anti-drift control
   and this repository fought, twice, to keep two copies of a rule from drifting
   apart (the vendored `discipline`, pinned by hash). A table derived from another
   repository's holdings adds a third thing that can lag.
3. **It breaks the property this suite was built around.** `mcp/docs/drift.md`
   states it: every recorded answer is read by the tool and by the control
   through the *same function*, so the control cannot check itself. With an
   artefact, the tool reads the artefact and the control recomputes: two readings
   again. The property can be kept, but only in one direction — the control
   regenerates and requires the file to be byte-identical, so the recomputation
   never leaves CI, and the tool becomes a verifier of a claim rather than the
   maker of one.
4. **A table for everything would be large and would not answer more.** The
   positions documents name 367 distinct counterparties across 2176 rows in 127
   announced lists. A verdict per pair is not computable today — most of those
   treaties are not in the library — and the corpus already publishes the inputs
   (39 mapping Articles, 107 signatory rows, 103 positions). Committing the join
   for everything would add megabytes of derived prose while the answers depend
   on treaties nobody has contributed yet.

## What the control would be

Two controls, and they are different:

* **the one that exists**: `python -m itl_mcp.drift` compares live answers with
  `fixtures/expected-answers.json` and names the fact that moved. Unchanged.
* **the one the artefact needs**: regenerate and compare byte for byte, the way
  the corpus's own `test_f07_build_is_byte_identical` treats every derived
  artefact — a reading, a comparison, and a failure naming the file. Plus one
  test that the tool **refuses** when an input hash has moved, because a
  verification that cannot fail is not one.

## What I would do

Commit the **skeleton**, not the payload, and only for treaties the library
holds; put it in the library beside each treaty; keep the corpus as the place the
rules live and the place that regenerates it; carry both commits and every input
hash; make the tool verify-and-refuse, never answer from the artefact when a hash
has moved; and keep the drift control as the maker of the answer.

The line to hold: the artefact exists for **reach**, not for knowledge. It
answers no question the server cannot; it makes the answer readable where the
server cannot run. The moment it becomes the source of truth the tool answers
from without a check, this project's own argument — recompute rather than trust a
derived file — has been given away for a convenience.

## What is not measured here

* **Who regenerates it, and when.** The corpus's CI cannot see a treaty the
  library has not contributed yet, so the regeneration either runs in the
  library's CI (which would need the corpus as a checkout) or waits for a corpus
  push after a library push. Neither was tried.
* **The artefact's own drift.** How often a corpus push would change a skeleton —
  a mapping edit changes every verdict; a position document changes one
  jurisdiction's. The corpus's commit history would answer it; it was not read.
* **Whether a reader actually prefers it.** The gain in (1) above is an argument,
  not a measurement: no reader was asked, and no model was pointed at a committed
  skeleton to see whether it answers better than it reads.
