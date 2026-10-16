# AGENTS.md — how to work in this repository

Repo-level instructions for any coding agent working here. They are the rules
that are easy to break by being helpful; the READMEs say what the project is.

## What this is

A citable corpus of the UN Model Double Taxation Convention (2017 and 2021) and
the OECD material on the Multilateral Instrument, plus the server that answers
questions about them under `mcp/`. Three layers, one contract of fidelity:
`corpus` (this repository), [`library`](https://github.com/avvohacker/international-tax-law-library)
(the bilateral treaties), and the folder `mcp/`, which reads both.

## The two rules that decide almost everything

**A gap is an answer.** Where the data does not hold something — a list a
document announces but never prints, a page the library declares it could not
read, a jurisdiction absent from the signatories table — the answer *is* the
gap, named, with the reader's own reason. Do not fill it by analogy with a
document that does hold it, do not read a `null` as a "no", and do not report a
table that could not be read as a finding about the treaty. `null`,
`undecidable`, `NOT-EVALUATED` and `announces_a_list_not_captured` are outputs of
this project, not defects in it.

**No claim without the bytes.** Every answer that cites a provision must name
the artefact, the page and, where the project has one, the hash it was verified
against. A citation to a page that does not carry the fact is worse than no
citation: it is the failure mode this repository exists to make impossible.
Where the corpus and the library disagree, report both.

## Ask the server, or read the file

Both are correct, for different questions, and the line between them is worth
holding:

* **Reading is right** for what the files say: what a treaty's text is, what a
  position document prints, what a rule in `rules/` declares, what a page
  contains. Here GitHub's own MCP server is a fine reader — it returns a file in
  full up to 1 MB, and every committed file of `mcp/` is far below that.
* **The server is right** where the answer needs a rule the files do not state:
  whether one treaty falls inside a reservation, which edition is silent on an
  Article, what the MLI does to a treaty and by which chain, whether a name in
  the table matches the one a document prints, and what any of it was verified
  against. Those are the six tools of `mcp/`, and
  [`mcp/README.md`](mcp/README.md) names the rule each one applies — together
  with the cases where those same files, read plainly, yield a different answer.

A refusal from the server is an answer: relay it with its reason rather than
answering around it.

## Starting the server

```bash
pip install "git+https://github.com/avvohacker/international-tax-law-corpus.git@main#subdirectory=mcp"
export ITL_CORPUS_ROOT=/path/to/this/checkout
export ITL_LIBRARY_ROOT=/path/to/international-tax-law-library
itl-mcp                      # speaks MCP over stdio
```

It owns no data and answers only from those two checkouts; with either missing
it exits naming the one it wants. An MCP host is configured with the command and
the two variables — the snippet is in [`mcp/README.md`](mcp/README.md).

## House rules

* **Generated files are not edited by hand.** `docs/harness-status.md`,
  `mcp/docs/status.md`, `mcp/fixtures/expected-answers.json` and
  `mcp/fixtures/verdicts/*.json` are written by commands, and a test compares
  each with what its command writes: `python -m harness --write` (corpus),
  `python -m itl_mcp.status --write`, `python -m itl_mcp.drift --write` and
  `python -m itl_mcp.skeleton --write` (in `mcp/`, with the two roots exported).
  Hand-editing one turns a check into a copy of itself.
* **A committed verdict is a claim with a date.** `mcp/fixtures/verdicts/` holds
  the citable half of each verdict, with the digest of every input it was
  computed from. Edit the corpus or the library and the tool answers `stale`
  until `python -m itl_mcp.skeleton --write` runs: do not silence it by editing
  the file, and do not answer past it.
* **Vendored copies are never edited either.** `harness/discipline/` is the one
  implementation of what may not be committed about a machine, how a workflow is
  read, what a status board owes a reader, what a pin says about the copy it
  holds and where a document sends a reader who wants the server; it is copied
  into the library and into `mcp/vendor/discipline/` by
  `python scripts/vendor-discipline.py`, and
  each copy carries the pin that says which bytes travelled. Re-vendor, never
  patch a copy — and when the corpus changes, the copies need a release:
  `python scripts/vendor-discipline.py --into ../international-tax-law-library`
  then `--into mcp`, with `--check` after it.
* **No machine traces.** No absolute path of the machine that built anything, no
  user name, no host name, in code, comments, documents, fixtures or commit
  messages (invariant F14). The rule is implemented once, in
  `harness/discipline/machine_traces.py`, and the tests run it under the CI
  account as well.
* **Prose here is dense on purpose.** It states what is known, by what check,
  and what is not: do not soften a limitation into a promise, and do not delete
  a stated defect. `SPEC.md` holds the invariants, one per section.

## Checking your work

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                # the invariants
.venv/bin/python scripts/discipline-drift.py --corpus . --mcp mcp   # one discipline
      # this repository's half: itself and the server it holds. The library reads
      # its own half over this corpus; add --library ../international-tax-law-library
      # here to compare that copy as well.

cd mcp && ITL_CORPUS_ROOT=.. ITL_LIBRARY_ROOT=../../international-tax-law-library \
      python -m pytest -q                                     # the server
# and, after moving any data either checkout holds:
      python -m itl_mcp.skeleton --check                      # is a verdict stale
```

A red check is a finding, not an obstacle: say which fact moved and why, or say
that the check could not run. Both are better than a green run that checked
nothing.
