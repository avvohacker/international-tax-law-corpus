# international-tax-law-mcp

[![mcp-drift](https://github.com/avvohacker/international-tax-law-corpus/actions/workflows/mcp-drift.yml/badge.svg)](https://github.com/avvohacker/international-tax-law-corpus/actions/workflows/mcp-drift.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![license: all rights reserved](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)](../LICENSE)

Third layer of the corpus-library-MCP trilogy: the query mind over corpus plus
library.

## Where this lives now

The server is committed in the corpus repository, under `mcp/`, and it is the
repository that runs it: `.github/workflows/mcp-drift.yml` stands at that
repository's root, because GitHub reads the workflows of a repository from its
root and from nowhere else, and the answers below are checked there on every push
and every week. This folder is the addendum — the package, its tests, its
fixtures and the copy of the shared discipline it holds - and how far it travels
was measured rather than assumed: exported with `git archive` into a temporary
directory and run there against the two roots, **the server answers** (both
verdicts below, and its refusals) while **8 of its 156 tests fail**, because
those tests read this repository's workflows, its board and its machine-trace
rule, and a folder sitting by itself has no `.github` above it. So the portable
part is the server; the suite is the part that holds the seat, and it is to be
run where the server is committed. The standalone
[international-tax-law-mcp](https://github.com/avvohacker/international-tax-law-mcp)
repository it was built in is where the whole thing was also run alone.

Two consequences for a reader, and both are stated rather than discovered:

* `ITL_CORPUS_ROOT` points at the corpus checkout, which is the repository that
  holds this folder — `..`, if you are reading from here;
* the rest of this document describes the server and reads as if it stood alone.
  Where it says "this repository", read "this folder, and the workflows and the
  rights declaration of the repository that holds it": the terms are the corpus'
  own ([LICENSE](../LICENSE), [TDM.md](../TDM.md)), and there is no second copy
  of them in here.

## Where this fits: corpus, library, mcp

Three layers, one contract of fidelity:

* **corpus** ([international-tax-law-corpus](https://github.com/avvohacker/international-tax-law-corpus)) — the citable base: UN Model 2017 and 2021 plus the OECD MLI framework (mapping, signatories and parties, country positions). Closed scope, byte-reproducible, every unit traceable to its page. **State**: both editions and every view built, anti-drift control in CI; it also holds this server, under `mcp/`.
* **library** ([international-tax-law-library](https://github.com/avvohacker/international-tax-law-library)) — the bilateral treaties people work on, contributed as they go, under the same fidelity contract (source hash, page-anchored units, declared gaps, no invention). Invitation: as you work a treaty, put it here. **State**: contract walking — two treaties in (`uk-us-2001` US–UK 2001, `no-uk-2013` UK–Norway 2013).
* **mcp** ([this folder](.), in the corpus) — the query mind over corpus plus library: treaty questions answered from the data (as-modified verdicts, with the chain of MLI Articles behind each one), never from guesses. **State**: server — seven tools answering from the two checkouts and refusing when they cannot; tested over the protocol in CI.

## Current state: the server answers, and refuses

This layer owns no data. It reads the artefacts the corpus and the library
commit, and it must be told where they are — never left to guess a path:

```
ITL_CORPUS_ROOT    the international-tax-law-corpus checkout
ITL_LIBRARY_ROOT   the international-tax-law-library checkout
```

Both are validated at startup against what the repository they claim to be
actually looks like, so a wrong path fails immediately with a message rather
than quietly becoming a wrong answer later. The server reaches for no network
and reads no PDF: the corpus and the library already publish their text as
committed JSON with a hash per unit, and their own registers pin those units'
sources, so that is what it answers from and what it checks against.

## The tools

Seven tools, each with a defined answer and a defined refusal.

| Tool | Answers | Refuses |
|---|---|---|
| `list_treaties` | the treaties the library holds, with parties, pages and declared gaps | to pretend a treaty is held by article: the library publishes page-anchored units, so no article-level statement is possible from it |
| `read_treaty_page` | one page, with the hash it was built from recomputed and compared | a page number the treaty does not have |
| `mli_status` | one jurisdiction's MLI standing: signed, deposited, in force since — with the spelling the table prints and the match method | to promote a signatory to a party; to pick between two plausible rows (an ambiguous name is reported as ambiguous, not silently resolved) |
| `as_modified_verdict` | what the MLI does to one treaty, and the chain of Articles behind that verdict: each Article beside what the corpus says it changes and the words each party's own position files on it, with the page | a treaty the library does not hold; a verdict the data cannot support |
| `compare_model_editions` | one UN Model Article in the 2017 and the 2021 editions, with each edition's own units cited and the edition that does not print the Article named as silent | to answer from the edition that happens to hold the provision; to summarise the corpus's own edition diff rather than quote it |
| `reservation_scope` | whether one treaty falls inside the reservation each party filed on one MLI Article, with the row, the page and the provision the statement prints as the evidence, and the list it read for a `false` | to answer "not on the list" from a table the corpus could not read (that answer is `null` with the reader's own reason); to close a treaty's question when a party whose document the corpus holds leaves it open |
| `sources` | every artefact the server read, and how each was verified | to call a check a pass when it could not run |

### The reservation question, on its own

A reservation that prints the agreements within its scope settles, for one
treaty, whether it reaches it — and that is a question an agent usually has by
itself, without wanting the whole as-modified chain. `reservation_scope` asks it
for one MLI Article at a time and answers three-valued, per party:

```
reservation_scope(treaty_id="no-uk-2013", mli_article="Article 4")
→ answer: true, answered_by: [Norway]
  Norway: row 28 on page 6 of norway.json — "United Kingdom", "Article 4(4)"
```

The row and the page travel with the answer, so the match can be checked at the
source and rejected; the treaty's own answer is `true` when any party's list
names it, `false` only when every party whose document the corpus holds answered
false, and `null` otherwise — a party that filed nothing, or a list the corpus
could not read, leaves the question open rather than turning a gap in the data
into a finding about the treaty.

## When the answer is `not-modified`

The library holds the **US–UK convention of 2001**. Asked what the
MLI does to it, the server answers `not-modified`, and it says why: the United
States is not a signatory or party to the MLI at all, so no MLI provision
modifies a treaty it is party to. That rests on a row *absent* from the
signatories table, not on a favourable reading of one — and the reasoning
prints the absence as the reason.

The chain is shown beside it. The UK's own MLI position document carries a
covered-agreements table that names the United States of America, at entry 113
of page 18, and the server reports it as **the UK's** table, naming the USA —
not the other way round. That attribution is asserted by a test, because an
earlier build of this server said the opposite: it read the filed table as the
other state's document. Two facts that look alike are kept apart on purpose:

* the **UK** filed a position document that lists this treaty as covered;
* the **US** has filed no position document in the corpus at all.

## When the answer is `modified`

The second treaty is the **UK–Norway convention of 2013** (`no-uk-2013`), and
it is the case the verdict was built for and could not previously exercise:
both parties are MLI parties with the MLI in force for each (Norway since
1 November 2019, the UK since 1 October 2018), and *both* position documents
list the treaty as a Covered Tax Agreement — Norway at entry 28, the UK at
entry 78, each printing the same signature date, 14 March 2013.

The chain comes back with it: **23 Articles**, because that is how many the
corpus maps as acting on a Covered Tax Agreement. It is deliberately not
shorter than that. An Article nobody spoke about is still an Article that
changes treaties, so it is listed with a reading that says plainly that neither
party's document records a reservation, notification or choice on it — leaving
those out would let the chain read as less than it is.

Each link carries the corpus's own statement of what the Article does and which
of the treaty's articles it targets, beside the words each party filed, with
the page. Two of those links are worth quoting, because reporting them flat
would have produced the wrong answer twice over:

* **Article 8 (dividend transfer transactions)**, which targets the treaty's own
  Article 10, is reserved by **both** parties. The UK's reservation is
  unqualified; Norway's runs "*to the extent that the provisions described in
  Article 8(1) already include a minimum holding period*". Flattened, the two
  would read identically. The qualifier is kept, quoted, and named in the
  reading, so a conditional reservation is never presented as an absolute one.
  Both statements then continue "*the following agreement(s) contain(s)
  provisions that are within the scope of this reservation*", and the corpus
  reads those tables, so the chain answers the question the list was printed
  for — with the row and the page it read from. For this treaty that cuts both
  ways: on **Article 4** Norway's list (9 rows, page 6) names the UK at row 28,
  provision *Article 4(4)*, so the reservation reaches it by that party's own
  list; on **Article 8** Norway's list (5 rows, page 14) does not name it, so by
  that party's own list it does not. Where a statement announces a list whose
  table this corpus could not read, the answer is reported as what it is — the
  position **cannot be read from this data** — because a gap never answers "no".
* **Article 9 (capital gains)** records a reservation on each side that takes out
  *Article 9(1)*, not the whole Article. It is not reported as an entirety
  reservation, because the documents do not say that.

And one thing the chain does not do, stated as a silence rather than a guess:
the corpus holds each party's position and the MLI's Article-to-provision
mapping, but not the Convention's own **compatibility clauses**. Where the two
parties chose differently, or reserved on one side only, or reserved with a
qualifier, the server sets out each party's own words and does not decide which
modification ends up applying. That decision is not in this data.

Every answer also carries what the data cannot say (`silences`) and every rule
the verdict needed that the data itself does not hold (`assumptions`), so the
part a reader has to decide for themselves is labelled rather than smuggled in.

## One Article, two editions

The corpus holds two editions of the UN Model, and they are two documents: the
2021 edition added **Article 12B** (income from automated digital services),
which the 2017 edition does not print at all. `compare_model_editions` puts the
same Article from both editions side by side and cites each edition's own units
— their eIds, numbers and pages, read from that edition's node index.

The half that matters is the silence. An answer that quoted only the edition
holding a provision would present an addition as if it had always been there, so
an edition with no node for the Article is named as **silent**, together with the
eId that was searched for. Where the corpus's own edition diff
(`derived/reports/diff-un-model-2017-2021`) classifies the Article, that entry
travels with the answer unparaphrased — it quotes the whole old and new text of
every unit it calls changed — so the reader sees which half of the answer came
from where.

What the tool does not do is decide what a difference means for any treaty. It
reports what the two editions print, and leaves the reading to the reader.

## Verification: three kinds of check, and they are not equally strong

Every answer is a claim about bytes somebody committed, so the server re-checks
them before answering. `sources()` returns the whole ledger, and each check
names which kind it is:

* **bytes** — the hash was recomputed from the committed file and matched. The
  strongest: the file on disk is the file the project pinned.
* **register** — the hash a file declares about its *source* was found in the
  corpus's own provenance register. The source PDFs are never committed (the
  hash, not the file, is the contract), so this proves the artefact still names
  the registered source, and not that the source is unchanged.
* **self** — a declaration compared with another declaration in the same file.
  A cross-check, and nothing more.
* **absent** — the check could not run at all; the reason is given, and it is
  never counted as a pass.

The chain rests on the corpus's **MLI mapping**, and that the mapping's declared
source hash is the one the corpus register pins for the MLI convention text is
a `register` check like every other: read, not assumed. (That register is
`provenance/sources.yaml`, which is why PyYAML is the one non-`mcp` dependency
here. The PDFs still are not read.)

Against the current checkouts that ledger is **182 checks: 177 matched, 5
unprovable with a stated reason, 0 disproved**. All five are the same limit,
honestly named: a source whose bytes are deliberately not committed (the two
Model PDFs and the two treaty PDFs), and one declaration that is about the table
as printed in the source rather than about the committed JSON.

Getting to that took a repair worth recording, because it is the same
failure in the other direction. The register names six of its files the way the
publisher spells the country (`mli-position-czech-republic.pdf`, `-turkey.pdf`,
`-china.pdf`, `-hong-kong.pdf`, `-russia.pdf`, `-cote-divoire.pdf`) while the
published positions use slug form (`czechia`, `turkiye`,
`china-people-s-republic-of`, `hong-kong-china`,
`russian-federation-provisional`, `cote-d-ivoire`). Deriving the filename from
the slug reported those six as *unprovable* when the data could prove them — a
false silence, which is as wrong as a false claim about bytes. The check now
matches the hash the artefact declares, and names the file the register
actually holds, so a spelling divergence is reported instead of mistaken for
missing evidence. The whole family of 103 positions is asserted in one test, so
the next one cannot slip through as a sample.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # the pinned versions CI runs
.venv/bin/pip install -e . --no-deps          # the `itl-mcp` command itself

export ITL_CORPUS_ROOT=/path/to/international-tax-law-corpus
export ITL_LIBRARY_ROOT=/path/to/international-tax-law-library
.venv/bin/itl-mcp
```

`requirements.txt` installs the pinned dependencies but not this package, so the
`itl-mcp` command comes from the second line. Running
`.venv/bin/python -m itl_mcp.server` from **this folder** needs no install at
all: `-m` reads a package from the working directory, and the working directory
is `mcp/`. From the corpus root above it, name the folder instead
(`PYTHONPATH=mcp .venv/bin/python -m itl_mcp.server`) — what does not work is
standing at the root and expecting `itl_mcp` to be importable, because that
package is here and not there.

Both roots are required: with either missing the server exits naming the one it
wants instead of starting half-configured. It speaks MCP over stdio, so an MCP
host starts it as a subprocess and has to pass those two variables itself,
because the server does not read them out of an environment the host never set:

```json
{
  "mcpServers": {
    "international-tax-law": {
      "command": "/path/to/.venv/bin/itl-mcp",
      "env": {
        "ITL_CORPUS_ROOT": "/path/to/international-tax-law-corpus",
        "ITL_LIBRARY_ROOT": "/path/to/international-tax-law-library"
      }
    }
  }
}
```

## Testing

```bash
ITL_CORPUS_ROOT=... ITL_LIBRARY_ROOT=... .venv/bin/python -m pytest -q
```

The suite reads the real checkouts, because the point of this server is that it
answers from those artefacts and not from fixtures that could agree with a bug
(`docs/status.md` is the generated board: how many questions are recorded, how
many facts, and what the control reads). Six of them are worth naming:

* it tampered with a page on purpose — one word swapped for another of the same
  length — and asserts that verification then **fails**. A check that cannot
  fail is not a check.
* it starts the server as a subprocess and speaks MCP to it over stdio: the
  handshake, the tool list, and calls whose answers are read off the wire. The
  in-process tests would stay green for a package that cannot finish a
  handshake, and that would not be a server.
* it verifies **every** published MLI position, not a sample, and asserts that
  each one names a source the register actually pins. That guard is what would
  have caught the six false silences above before a reader did.
* it asserts the chain for the UK–Norway convention: that it covers every
  Article the corpus maps and not only the ones a party spoke about, that
  Norway's Article 8 reservation keeps its qualifier while the UK's has none,
  and that the agreements each statement prints inside its reservation are
  looked up for this treaty — on the list with its row and page, or not on it —
  while a list the corpus could not read leaves the question open instead of
  answering "no".
* it asserts the comparison of the two Model editions: that the 2017 edition is
  reported **silent** on Article 12B rather than answered from the edition that
  holds it, that a modified Article names all four of the diff's buckets so an
  empty `renumbered` cannot read as a bucket never looked at, and that the diff
  really does carry the text of every unit the answer then summarises by count.
* it compares every answer the README promises with the same answer recorded
  earlier, and names the fact that moved, from what to what, and what kind of
  upstream change could have moved it. See below.

The CI control (`mcp-drift`) reads the corpus where it stands and checks out the
library at its default branch, refuses to let a missing checkout turn into a
skip, and runs this suite against them. This layer owns no data to rebuild, so
the drift it can see is the one only it can see: an answer moving because the
corpus or the library moved underneath it. A legitimate upstream edit turning
the run red is the intended behaviour — the claim has to be re-earned here.

What that control costs is measured rather than assumed, with the corpus'
`scripts/read-audit.py` — the tool that records every file a command really
opens, however many times it opens it:

| command | corpus | library |
| --- | --- | --- |
| `python -m itl_mcp.drift` | 15 files, 9.5 MB | 2 files, 183 KB |
| `python -m pytest -q` | 116 files, 14.3 MB | 2 files, 183 KB |

The drift job's corpus bytes are nine tenths two files, the two UN Model
editions' span files, because a verdict about their pages has to be re-read from
those pages. The suite's 14.3 MB is essentially all of `corpora/`: one
jurisdiction file per assertion. There is no honest way to read *less* — the
bytes are the evidence, and reading the corpus' `derived/index.json` (207 KB)
instead would replace a verification with trust in a summary of it. What these
jobs do not pay is the corpus' own billed cost: they fetch no PDF, so the 135.7
MB the corpus' control downloads is not here, and the whole control reads about
what the checkout weighs.

What there *was* an honest way to read less is the same bytes again. The table
above is what has to be present; what the commands actually moved was 19.5 MB and
240 MB, because the second question about an edition hashed the same two ledgers a
second time — 94% of the suite's I/O was re-reading 116 files. `itl_mcp/artefacts.py`
now reads each artefact once per run, keyed on its size and its mtime: an
artefact edited under a running process gains a new key and is read again, and one
that is not is served from memory. A digest is a pure function of bytes this
process never writes, and the documents are handed out as they were parsed, so no
answer can change:

| command | corpus, before | corpus, now | library, before | library, now |
| --- | --- | --- | --- | --- |
| `python -m itl_mcp.drift` | 19.5 MB | 9.5 MB | 550 KB | 183 KB |
| `python -m pytest -q` | 240 MB | 14.5 MB | 5.7 MB | 183 KB |

`tests/test_artefacts.py` holds the other half of the claim: a ledger that grew,
and a ledger edited to the same length, both fail their bytes check on the second
read through `verify_manifest_edition`, so the memo is not a place a tampered
artefact hides. The one thing the key cannot see is an in-place write that leaves
both the size and the mtime exactly as they were; nothing in these checkouts does
that, and `forget()` is there for a caller that has.

```bash
# read from the corpus this folder is committed in, and about its own checkout
ITL_CORPUS_ROOT=.. READ_AUDIT_ROOT=$PWD/.. \
  .venv/bin/python ../scripts/read-audit.py module itl_mcp.drift
```

The rules this layer holds about itself are not its own either. What may not be
committed about a machine, how a workflow is read, and what the status board owes
a reader are vendored from the corpus in `vendor/discipline/` and pinned in
`provenance/vendored-discipline.yaml`; the `discipline` job of the corpus'
workflow refuses a copy that has drifted from that pin or from the corpus' own
current rules, because the three layers once had three copies of them and nothing
compared them. The workflows that run *these* tests, and the repositories they
check out, are read by `itl_mcp.ci.repository`: the corpus' root when the server
is committed inside it, this folder when it is a checkout of its own.

The same control runs on three interpreters: the pinned 3.13, and - because
`requires-python = ">=3.11"` is a claim and this is the layer a user installs -
the floor (3.11) and the newest release (3.14). The floor job also installs the
package and speaks MCP to the installed `itl-mcp` command, which is the entry
point the suite does not otherwise touch: it drives `python -m itl_mcp.server`.

## The answers are recorded, so a move is named

An assertion that fails says *that* a claim broke. It does not say which answer
moved, from what, or what kind of upstream change could have moved it — and a
verdict moving is a different event from a page hash moving, wanting a different
repair. So the answers the README promises are recorded as named facts in
`fixtures/expected-answers.json` — all seven tools, from the verdict and the MLI
standing to the treaty held, the reservation question, the silent edition and the
inventory of what was read — and compared field by field:

```bash
export ITL_CORPUS_ROOT=... ITL_LIBRARY_ROOT=...
python -m itl_mcp.drift            # compare; non-zero when anything moved
python -m itl_mcp.drift --write    # record the answers the checkouts give now
python -m itl_mcp.status --write   # regenerate docs/status.md
```

A move prints the fact, what it was, what it is, and what a move of that fact
implies — declared per fact in `itl_mcp/drift.py`, so a page whose text shifted
is not explained in the same sentence as a verdict that flipped. The CI control
runs this before the suite, so a red run leads with the fact rather than with an
assertion line.

The fixture is **generated**, never hand-written. A value somebody typed can
only ever be compared with what somebody typed, and stops being a check the
moment it is copied: `--write` is what records an answer, and running it is a
decision taken after reading the move, not a way to make a red run green.

How a fact is named, and how a report is read, is written down in
[`docs/drift.md`](docs/drift.md).

## Roadmap

1. **Corpus walks** (done) — both Model editions and the MLI layer,
   byte-reproducible, anti-drift control in CI.
2. **Library walks** (done, still filling) — bilateral treaties enter one by
   one under the same fidelity contract; the first is in (`uk-us-2001`) as the
   proof, with fetch + rebuild + contract tests in CI.
3. **MCP walks** (now) — this server: as-modified verdicts, citations to units,
   and silence where the data is silent.
4. **OECD Model** (later) — a corpus extension once 1–3 walk; excluded today
   on scope grounds only.

## Rights

The terms are the corpus repository's own, and there is no second copy of them in
this folder: see [LICENSE](../LICENSE) and [TDM.md](../TDM.md). All rights
reserved; the repository is public and source-visible. Contact
avvohacker@gmail.com before any reuse beyond reading. Text-and-data mining and
AI/ML training rights, including generative training, are expressly reserved.
Third-party rights in the source documents remain with their holders and are not
affected by it.
