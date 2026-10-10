# international-tax-law-corpus

A citable corpus of the UN Model Double Taxation Convention (2017 and 2021) and
of the OECD material on the Multilateral Instrument: text identical to the
source's, structure identical to the source's, every unit traceable to the page
and position it came from.

## Where this fits: corpus, library, mcp

Three layers, three repositories, one contract of fidelity:

* **corpus (this repository)** — the citable base: UN Model 2017 and 2021 plus
  the OECD MLI framework (mapping, signatories and parties, country positions).
  Closed scope, byte-reproducible, every unit traceable to its page.
* **library (next)** — the bilateral treaties people work on, contributed as
  they go: each treaty enters with the same fidelity contract (source hash,
  page-anchored units, declared gaps, no invention). Invitation: as you work a
  treaty, put it here.
* **mcp (after library)** — the query mind over corpus plus library: treaty
  questions answered from the data (as-modified verdicts), never from guesses.

Later corpus extension, after library and mcp are walking: the OECD Model,
which is excluded today on scope grounds only.

## Current state: both corpora and every view are built, and byte-reproducible

There is a working **span ledger** (DESIGN.md §3): it reads a PDF as positioned
spans, measures the page geometry, decides every span by a declared rule in
`rules/`, projects the kept spans into structural nodes, and proves by
round-trip that the projection reproduces the classified stream exactly.
`python -m harness ledger` prints the account, including the rule behind every
drop.

Built, and byte-identical when built twice: the AKN 3.0 document, the manifest,
the span ledger, the node index and the markdown views of both Model editions -
33 and 34 articles, with the alternatives of articles 8, 18 and 25 as named
branches, and 4 and 5 footnotes anchored as `note` nodes.

Built from the same reading layer: the MLI table of signatories and parties (107
contiguous rows), the MLI-to-treaty mapping (`corpora/mli/mapping.json`), whose 39
Article numbers and titles are read from the Convention's own text rather than
typed, and **the whole family of MLI positions**: one register entry for the 110
documents the publisher ships, read in one pass
(`python -m harness ledger --source mli-positions-batch --write`), which publishes
103 positions - `corpora/mli/positions/<slug>.json`, each with the options its
document prints for an Article and, where the document has one, its
covered-agreements table - and the family's own account of itself
(`corpora/mli/positions/batch-report.json`). What the family's one command knows
and prints, because it is what a corpus is for:

* **110 documents declared, 103 positions published, 7 documents unread** - the
  OECD's deposit notices, whose every page is a scanned image and whose only text
  is a rotated stamp. This pipeline has no OCR, so they are declared unread with
  the reader's reason rather than published as jurisdictions that notified
  nothing;
* **one jurisdiction with two documents**: the Russian Federation's position
  arrived as `russia` and as `russian-federation`. The document filed under the
  jurisdiction's own slug is the position; the earlier one is published beside it
  as `russian-federation-provisional`, its suffix taken from its own first
  paragraph, which says it is a provisional list of expected reservations. The
  Czech Republic's additional notifications and Mauritius' draft are resolved the
  same way, from the publisher's own file names;
* **98 documents' covered-agreements tables read**, with the 5 that are not in
  `positions_without_a_covered_agreements_table` and the reason each artefact
  gives: two documents have no such table, two tables' columns are not yet
  measured, and one has no dated table. The 11 tables whose numbering runs with a
  hole in it are in `positions_whose_numbering_has_a_gap`, with which numbers the
  projection found no row for - published rather than renumbered, because a table
  renumbered to close its gaps cannot be checked against the page it came from.

The family is checked byte for byte like the rest: `test_f07_build_is_byte_identical`
reads it once and compares every file it writes with the corpus this repository
holds, which was written by an earlier process - and reads it once rather than
twice because a second reading, in the same process, would compare a reading with
itself for another minute.

The projections name no jurisdiction and no document: they are one function of the
geometry, the only per-jurisdiction input is data in
`provenance/jurisdictions.yaml` (the canonical name and slug, and the other names
the sources publish - which is how a position published in French, or one whose
cover is a letterhead of the state it belongs to, is still read as itself), and
the mapping's modes and targets are declared once in `provenance/mli-mapping.yaml`,
with the tests pushing them against the base text and against the positions. Every
span of the family's 110 documents is claimed by a rule, with 0 unclaimed, and the
two Model editions' own readings are unchanged by any of it.

Built as well, and re-rendered byte for byte by its test: the edition diff
(`derived/reports/diff-un-model-2017-2021.{md,json}`), which compares the two
editions the corpus holds - not the two PDFs - node by node, so a change in it is
a change in the Convention and not a change in the reading. Nothing is left
declared but unbuilt: every source's artefact exists, and every probe speaks.
`provenance/sources.yaml` declares for every source what is built from it, so a
source whose artefact does not exist says so with a reason instead of being
absent from the count, and `docs/harness-status.md` prints that declaration next
to the probes.

`python -m pytest -q` is green in full, and not by emptiness: every probe runs
and reports `ABSENT`, and every invariant that can be
checked today is checked by a test that fails while its artefact is missing.

The probes below are written from the source documents, not from any earlier
output: a test written by diffing old output against new output proves the two
agree, not that either is right. See `SPEC.md`, "The provenance rule".

The order is deliberate (DESIGN.md §8): a pipeline built first and tested
afterwards can only ever be tested against its own assumptions.

What is here:

| path | what it is |
| --- | --- |
| `SPEC.md` | what faithful means, invariant by invariant |
| `DESIGN.md` | how the pipeline is built, and why it is built that way |
| `fixtures/invariants.yaml` | the invariants, machine-readable |
| `fixtures/known_defects.yaml` | the 2026-09-27 audit, as probes that assert a defect is absent |
| `provenance/sources.yaml` | every input with its URL, SHA-256, date, rights note, and what is built from it (`produces`) |
| `rules/*.yaml` | the classification rules the extractor will read |
| `harness/` | the probe engine and the status report |
| `tests/` | the invariants, as tests |
| `docs/harness-status.md` | generated. Do not edit. |
| `docs/guide-maps-and-tables.md` | what this project is, in plain language with maps and tables — the first file to read for a newcomer |

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m pytest -q          # the invariants and the probes
.venv/bin/python -m harness status     # one line: is there a corpus, and what does the harness see
.venv/bin/python -m harness probes     # every probe, with its verdict
.venv/bin/python -m harness report     # the full status board
.venv/bin/python -m harness --write    # regenerate docs/harness-status.md

# read a source as spans, decide every one of them by rule, and print the audit
.venv/bin/python -m harness ledger                 # defaults to un-model-2017
.venv/bin/python -m harness ledger --source un-model-2021
.venv/bin/python -m harness ledger --source mli-signatories-and-parties
.venv/bin/python -m harness ledger --write         # also write the corpus artefacts
.venv/bin/python -m harness ledger --source mli-positions-batch --write
                                                   # every MLI position, in one pass
                                                   # (about a minute: 110 documents)
.venv/bin/python -m harness ledger --source mli-convention-2016 --write
                                                   # the MLI-to-treaty mapping

# what changed between two editions, as a view of the corpus
.venv/bin/python -m harness diff                   # defaults to un-model 2017 → 2021
.venv/bin/python -m harness diff --write           # also write derived/reports/
```

Three verdicts, and the third is the point:

* `ABSENT` - the probe ran and the defect is not there;
* `PRESENT` - the probe ran and the defect is there, with file and line;
* `NOT-EVALUATED` - the artefact does not exist yet, so the probe cannot speak.
  It fails its test by saying so, rather than passing quietly.

`python -m harness status` exits non-zero if anything is `PRESENT`. It never
exits non-zero for `NOT-EVALUATED`: a corpus that does not exist yet is not a
defect in a corpus, and `tests/` is where "the corpus is missing" is reported
loudly.

## Probe discipline

A probe must be a check, not a signature: each one states the defect, the
target files, and the rule that decides it, and every probe runs against this
repository with file and line when it fires. A control that cannot speak about
a missing artefact reports `NOT-EVALUATED` instead of passing quietly — and it
never reports a pass it did not earn.

## Sources

The input PDFs are **not** committed. They are published documents with their own
terms; they are fetched, hashed and read locally, and what this repository
commits is the hash, not the file. `provenance/sources.yaml` records, for each
one, where it came from and what may be done with it. Every hash there was
verified with `shasum -a 256`.

The corpus itself stays multilingual. A country's MLI position is published in
one or more languages and is quoted as published; only this project's own text -
code, comments, tests, reports, documents - is English (invariant F13).

## Rights

See `LICENSE`. All rights reserved; this repository is public and source-visible.
Contact via GitHub before any reuse beyond reading. Text-and-data mining and
AI/ML training rights, including generative training, are expressly reserved;
see `TDM.md`. Third-party rights in the
source documents remain with their holders and are not affected by it.
