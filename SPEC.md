# Fidelity specification

What "faithful" means for this corpus, written so that a test can decide it.

This document is the human half. `fixtures/invariants.yaml` is the machine half,
and the two are tied together by the meta-tests in
`tests/test_spec_is_executable.py`: every invariant declared in the catalogue
must appear here as a heading carrying the same name, every `enforced_by` entry
must name a test function that exists, and every probe in
`fixtures/known_defects.yaml` must point at an invariant declared here.

**The governing rule: an invariant that no test enforces is not an invariant.**
It is a wish. The meta-tests exist so that this cannot quietly become untrue.

Two conventions:

* **scope** — where the invariant is evaluated. `corpus` (the extracted legal
  data), `sources` (the input PDFs and their register), `project` (this
  repository's own code, documents and reports).
* **proof** — the test or probe that decides it, named exactly. `known_defects`
  means: decided by the probe catalogue, run by `tests/test_known_defects.py`.

---

## F1 · Completeness

**Statement.** Every unit count in the corpus equals the count in the source, and
every unit that is not extracted appears in an explicit `missing` list with a
reason. Silence is never a valid outcome.

**Scope.** corpus. **Proof.** `test_f01_completeness_counts`, `known_defects`.

**Why it exists.** An earlier shape-gated build reported "100 jurisdictions, 0 problems"
while the source table had 107 numbered rows: rows 1 to 6 sat on a page the
parser never read, and row 29 was dropped because its name wrapped onto two
lines. Both losses were invisible because the count of what was extracted was
compared with nothing.

**Anti-pattern.** A count that is compared with itself. A `missing` list that is
always empty. A number in a README with no command behind it.

---

## F2 · No insertion

**Statement.** No character in the corpus is foreign to the source spans it
derives from. Apparatus - running headers, page numbers, chapter titles,
footnote marks - never enters the body.

**Scope.** corpus. **Proof.** `test_f02_no_insertion`, `known_defects`.

**Why it exists.** The 2017 corpus contained "be deductible Articles 24 and 25
under the same conditions". "Articles 24 and 25" is the running header at the top
of the page; it was read as the continuation of the line before it. The 2021
corpus had the same injury inside "situated Articles 12B and 13 in that other
State".

**Anti-pattern.** Checking that the text is *plausible*. Looking for a pattern
in the output after the fact. Any gate that inspects the shape of the result
instead of the origin of the span cannot see this class of defect.

---

## F3 · No deletion

**Statement.** No body token of the source is absent from the corpus, except
through a declared and logged typographic transform (dehyphenation, line
joining).

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** In the 2021 corpus, paragraph 4 of article 1 is not article 1;
it is the text of footnote 11, repeated. The paragraph it replaced is simply
gone, and the flagship 2017-to-2021 report then announced a change that never
happened.

**Anti-pattern.** Comparing counts of paragraphs between editions as evidence
that the text is right. Counting is not reading.

---

## F4 · Faithful structure

**Statement.** The corpus hierarchy reflects the source hierarchy. Structural
distinctions of the source (for example "Alternative A / B") are nodes with
labels, never free text inside a paragraph.

**Scope.** corpus. **Proof.** `test_f04_structure_is_nodes_not_text`,
`known_defects`.

**Why it exists.** The alternatives in articles 8, 18 and 25 were emitted as
fake numbered paragraphs (`**1.** Article 25 (alternative A)`), which corrupted
the paragraph count and made the two branches distinguishable only by an
internal id suffix. Where the label was not emitted as a paragraph, it was glued
to the tail of the previous branch.

**Anti-pattern.** Encoding structure in text and recovering it later with a
regular expression. If a distinction matters, it is a node.

---

## F5 · Apparatus separation

**Statement.** Body and apparatus never touch: footnotes are anchored `note`
nodes, and running headers, page numbers and chapter titles do not exist in the
body - not at the head, not at the tail, and not mid-sentence.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** This is the invariant with the most evidence against the old
pipeline, in both editions: chapter footers and the following chapter title
appended to the tail of article 5 (§9), article 21 (§3), article 23B (§2) and
article 29 (§9); a running header merged into article 12B (§10); and, worst,
footnote 12 printed in the middle of the sentence "at least 50 per cent" in
article 29 (2017), with footnote 14 doing the same in 2021.

**Anti-pattern.** A boilerplate filter that inspects the first line of each
paragraph. A footnote that passes the filter because its font size (10pt) is
close enough to the body size.

---

## F6 · Traceability

**Statement.** Every leaf unit carries provenance: source id and hash, page, and
the span range it was built from.

**Scope.** corpus. **Proof.** `test_f06_every_leaf_has_provenance`.

**Why it exists.** Without spans, "is this sentence in the source?" can only be
answered by trusting the extractor. With spans, it is answered by reading the
ledger.

**Anti-pattern.** Provenance attached to the file rather than to the unit. A
page number that is the page of the chapter, not of the sentence.

**What a page is, and is not.** The page is where a unit was *read from* and
nothing else: it is the provenance of the reading, which is what lets the text be
checked against the printing it came from. The address of a provision is its
structure - the article, the paragraph, the point, with the `eId` the standard
gives it - and that is what a citation names. This is why AKN 3.0 has no page
element (the only name in the vendored schema containing "page" is `coverPage`)
and why neither committed document carries one. A citation that named a page
would name the printing rather than the law, and a corpus that could not say
which provision a unit is would have traded address for provenance - the two are
not the same thing, and this corpus keeps them apart.

---

## F7 · Determinism

**Statement.** The same source with the same code produces the same bytes, for
every artefact. No non-reproducible artefact is tracked in git; a generated
artefact that *is* tracked must be byte-reproducible from the sources and the
code.

**Scope.** project. **Proof.** `test_f07_no_generated_artifacts_tracked`,
`test_f07_every_source_declares_what_is_built_from_it`,
`test_f07_build_is_byte_identical`, `test_the_vendored_pair_is_the_registered_one`,
`test_the_schema_accepts_a_document_that_conforms`,
`test_the_validator_names_what_the_schema_refuses`,
`test_the_declaration_says_what_the_schema_says`.

**What F7 does not mean.** "Deterministic" is a statement about an artefact, so
the test compares exactly the artefacts the register declares are built from
each source, and a source whose corpus artefact is not built yet is compared on
its reading and counted in the status report. Green therefore means "every
artefact this project claims to produce reproduces byte for byte", not "every
artefact the specification will eventually describe". The second claim is what
this invariant must reach, and the declaration in `provenance/sources.yaml` is
what keeps the difference visible instead of arguable: a source that produces
nothing says so, with a reason, and
`test_f07_every_source_declares_what_is_built_from_it` refuses silence.

**The strongest form of F7.** Determinism says the pipeline writes the same
document twice; it does not say the document is the one the standard describes.
Both claims are about the same artefact, and the second is checkable: the AKN 3.0
schema is vendored under `vendor/akn/` - the OASIS legaldocml TC release whose
target namespace is the one this corpus writes, pinned file by file in
`provenance/akn-xsd.sha256` - and `python -m harness oasis` validates every
committed AKN document against it. The validator reads nothing but those two
files: a resolver refuses every other `schemaLocation`, so a run cannot check the
corpus against whatever a URL served that day, and asking the question without
the schema here is a stated failure rather than a pass. The register entry
`akn-xsd` used to say the opposite in as many words ("not yet possible: the
vendor/ directory and lxml are both absent"); it now declares the vendored copy,
and a vendored source that is declared and absent fails
`test_f07_every_source_declares_what_is_built_from_it`.

**What it says today, and why that is written down.** The committed documents
conform: `python -m harness oasis` reports each one valid, the board prints that
count, and `fixtures/oasis-conformance.yaml` - the declaration of the violations
the corpus has not yet fixed - is empty. The declaration is a worklist and not a
suppression, and `python -m harness oasis` fails when the run and that file
disagree - in both directions: a class nobody declared, a count that moved, or an
entry still claimed after the class was fixed. It became empty by repairing the
projection and not by relaxing it: `harness/akn.py` writes the shape AKN4UN's
guidelines describe for a UN document, and AKN 3.0 is stricter about where a
`list`, an `alinea` and an authorial note may stand inside a hierarchy, about a
`preamble`'s heading, and about the metadata an act's FRBR block must carry. Each
repair is a change to the artefact, rebuilt from the sources and republished; the
words of the corpus and their traceability to the pages they were read from are
unchanged.

**What it does for a source that is not one document.** The MLI positions are one
register entry for 110 documents (§P4), and reading them takes about a minute. So
the family is read once and every file it writes is compared with the corpus this
repository holds - written by an earlier process, and therefore a comparison that
finds machine-dependence (a set's order, a path, a clock) exactly as a second read
in the same process would. A second read of the same 110 documents, in the same
run, would cost another minute to compare a reading with itself; that the test
does not do it is stated here rather than left to be inferred from its runtime.

**Why it exists.** `derived/fts/legal-tax-data.db` was committed and was not
byte-reproducible: a fresh build produced the same 67 rows in different bytes
and left the working tree dirty after every run, so "the tree is clean" stopped
meaning anything.

**Anti-pattern.** Tracking an index, a cache or a database. A build that is
deterministic "modulo timestamps".

---

## F8 · Never fake

**Statement.** When a datum is absent, unreadable or unclassifiable, the value
is `unknown` or `unclassified` with a reason - never a plausible invented value,
and never a silent truncation.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The old pipeline's excerpt field was a hard slice at 1200
characters with no flag anywhere: 491 excerpts end exactly at the limit, cut
mid-word, and every one of them looks like a complete sentence in a JSON
browser.

**Anti-pattern.** A default value that reads like a real one. A truncated string
that is not marked as truncated.

---

## F9 · View consistency

**Statement.** The XML, JSON, markdown and SQLite views are generated from one
structure and never diverge, in content or in counts. A report of two editions is
a view of the corpus and not a second reading of the sources: every change it
shows is one the corpus holds, and every change the corpus holds is one it shows.

**Scope.** corpus. **Proof.** `test_f09_diff_report_is_a_view_of_the_corpus`,
`known_defects` (`report_matches_corpus`, recomputed from the corpus).

**Why it exists.** The edition diff is a flagship output and it reported "Article
1 - paragraphs added: 4", where the fourth paragraph was the footnote fragment of
the lost-paragraph defect. The diff was honest about its inputs and wrong about
the law.

**Anti-pattern.** A view that re-parses the source independently. Any view that
can disagree with another view. A report whose changes came from the extractor,
which is what a diff of two PDFs is: the reader cannot tell a change in the law
from a change in the reading, and neither could the report.

---

## F10 · Resolvable identity

**Statement.** Every slug and id resolves to exactly one object; related
artefacts (addenda, instrument variants) are reachable from their base object.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The positions corpus had `czech-republic.json` and
`czechia-additional-notifications.json` for one jurisdiction; the second had an
empty `country` field, so a lookup by country silently lost a document.

**Anti-pattern.** Identity inferred from a file name that nobody validated. An
empty identifier field.

---

## F11 · Source provenance

**Statement.** Every source has a URL, a SHA-256, a date and a verified, dated
rights note. The register is complete: no source is silently absent from it.

**Scope.** sources. **Proof.** `test_f11_manifest_is_complete`,
`test_f11_hashes_match_if_present`.

**Why it exists.** Of six input PDFs, the old register covered two, and a second
file named `positions.sha256` actually contained hashes of PDFs that were not
positions. The register lied by omission.

**Anti-pattern.** A hash file whose name does not describe its contents. A hash
recorded once and never re-verified.

---

## F12 · Claim honesty

**Statement.** Every number or assertion in README and docs is produced by a
command or by a committed document; nothing is hand-copied, and no verification
is claimed without the artefact that proves it.

**Scope.** project. **Proof.** `known_defects`.

**Why it exists.** The old README claimed "CI job green" for a repository with
no `.github/` directory, "29 tests" for a suite of 32, and "100 jurisdictions, 0
problems" for a table of 107. Each claim was true when written and nothing
checked it afterwards.

**Anti-pattern.** A badge. A status line in prose. A count that is not generated.

---

## F13 · Single language (English)

**Statement.** Everything belonging to the project is in English: code,
comments, docstrings, test names, printed messages, machine-readable reports,
documents and commit messages. The corpus is exempt: it is source data and is
multilingual by nature (a country's MLI position is published in its own
language and must stay faithful to it).

**Scope.** project. **Proof.** `test_f13_no_italian_in_project_artifacts`.

**Why it exists.** The project is country-agnostic and may be evaluated or read
by third parties. A working language that is not the published one makes every
document twice as expensive to review. The corpus, `fixtures/`, `vendor/` and
`provenance/` are excluded from the check: quoting a source in its own language
is fidelity, not a language error.

**Anti-pattern.** A bilingual notice instead of a choice. Translating source
text "for consistency".

---

## F14 · No environment leakage

**Statement.** No artefact contains absolute local paths, user or machine names,
or any other trace of the environment it was produced in.

**Scope.** project. **Proof.** `test_f14_no_local_paths_in_artifacts`,
`test_no_committed_file_carries_a_machine_trace`, `known_defects`.

**Why it exists.** The committed `derived/index.json` contained an absolute path
into the builder's home directory, twice. It is harmless and it is a leak of both
portability and privacy - and it is why nothing generated here may record where
it was generated.

The probe `d22` reads the artefacts the pipeline writes, from a list of globs;
the class is wider than that list, and it has three shapes worth naming: an
absolute path, the directory a checkout happens to live in (a fact about one
desk, never about the project), and the account name on the machine that ran
the check. The second and third are what `harness/report.py` answers for itself
by printing the project's name from `pyproject.toml`, and what
`test_no_committed_file_carries_a_machine_trace` answers for every file git
tracks - the names that are supposed to be there (a copyright line, an email
address, a GitHub owner) excepted, because a repository that could not name its
own author would be a worse repository, not a cleaner one.

The rule is no longer written in a test file, and no longer in three of them. It
is `harness/discipline/machine_traces.py`, because the library and the server owe
it the same rule and the three copies had already drifted - three wordings, three
exemption lists, three answers to whether a checkout's own directory name is a
trace. It is vendored verbatim into those two repositories by
`scripts/vendor-discipline.py`, pinned there by hash, and read by
`scripts/discipline-drift.py` in CI: the copies byte for byte, and then the rule
*run* for each checkout under the identity its own CI gives it. Each half is read
by a run that can repair it - this repository's job holds this repository and the
server committed inside it, the library's own run holds the library and this
corpus - because a red run naming a copy its reader cannot write is a red people
learn to read past.

Two things the rule cannot decide by itself are declared rather than discovered.
A path written with a placeholder (`<user>`, the way `fixtures/known_defects.yaml`
writes one) is not a path to a machine. And the account names CI runs under are
exempt from the name rule, because they are ordinary English words this family's
own prose says - a workflow comment here reads "the runner reads what the corpus
was built from" - while a CI account names no person at all. The exemption is the
name and never the path: `test_a_ci_accounts_home_path_is_still_a_trace` proves
that the absolute-path rule still catches a home directory under that account,
and the scan is run on a desk under CI's identity
(`test_the_corpus_passes_the_rule_as_the_ci_account_sees_it`), because a rule
that collides with the repository's own prose is invisible from a desk - which is
how the first version of it went red on three workflows instead of here.

**Anti-pattern.** Any absolute path that survives into an output. A report that
names the machine that generated it. A committed file that names the folder it
was checked out into. A fourth copy of this rule, written in the repository that
happened to need it next.

---

## F15 · A run holds what its reader can repair

**Statement.** A run of the shared rules reads the checkouts the repository holding
it owns - its own, and the copies committed inside it - and leaves every other layer
to that layer's own run of the same control. A red a repository cannot repair is not
reported by it, and a layer a run is not handed is named rather than passed over in
silence.

**Scope.** project. **Proof.** `test_the_rule_refuses_each_clause`,
`test_the_job_holds_only_the_checkouts_this_repository_holds`,
`test_the_run_names_the_layer_it_was_not_handed`, `known_defects`. The rule is one
module, `harness/discipline/holds.py`, read by the probe and by the test - two
readings of it would be two rules, which is what this package exists to stop.

**Why it exists.** The corpus' `discipline` job checked the library out beside it and
handed the control that checkout, so the red it printed was about a copy no commit
in this repository could ever fix: the repair is a push into another repository. The
job was red for hours over a fact that was true and unanswerable from here, which is
the state that teaches a reader to scroll past a red. Split the other way, the
finding does not disappear: the library reads its own half in its own run of the same
control, over this corpus, where the repair is a re-vendor from here - and it is that
run which goes red when these rules move and its copy does not.

What the split must not become is silence. A run that stopped at the checkouts it
was handed would read as a run over the whole family, and the layer it left out
would be the one nobody notices leaving: so the reasons a layer is not read are
stated once, in the same module as the rule, and each run prints them.

**Anti-pattern.** A job that checks out a sibling because the comparison "needs" it
- the comparison needs the *source*, and the source is the one checkout a run may
read without holding. A copy reported where it cannot be written. A run that says
nothing about the layers it was not handed. Reporting a drift as somebody else's
problem and then not telling them: the library's own workflow is what notices, and
it has to be named here, because nothing in this repository reads that file any more.

---

## U1 · UN Model article set

**Statement.** The set and order of articles is exactly the source's (2017 and
2021 as published), verified against the table of contents.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The old gate `G1_id_set_order` did check this, and it was
worth keeping. The new pipeline keeps the check and states it as an invariant so
that it cannot be dropped in a refactor.

**Anti-pattern.** An article set derived from the extractor's output and then
"verified" against itself.

---

## U2 · Alternatives are structure

**Statement.** Where the source offers alternatives (articles 8, 18 and 25 in
both editions), each alternative is a labelled node and its paragraphs are never
confused with the other alternative's.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** See F4. The alternative is a branch of the law, not a
paragraph of it: two options that a State may choose between, printed one after
the other.

**Anti-pattern.** A `__v2` suffix in an id as the only thing that distinguishes
two branches.

---

## U3 · Body, commentary and apparatus are disjoint

**Statement.** The Convention text, the Commentary and the page apparatus are
three disjoint sets; the boundary with "Part Two / COMMENTARIES" is inviolable.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The Model is one PDF containing the Convention, the
Commentaries on every article, the historical notes and the apparatus. The
previous pipeline got this boundary broadly right and it must stay right: an
article body that swallows a paragraph of commentary is wrong in a way a
reviewer will not notice for months.

**Anti-pattern.** Treating the whole page as one text flow and hoping the font
size separates the parts.

---

## U4 · No broken words

**Statement.** A word hyphenated across a line break never becomes two tokens,
and a legitimate internal hyphen ("day-to-day") is never joined away.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** Broken-word joins ("subdivi sions", "substan-tially",
"Contract-ing") were already fixed before the 2026-09-27 audit. This is stated
as an invariant and carried as a regression probe precisely because it can be
lost silently in a rewrite.

**Anti-pattern.** Joining every hyphen. Splitting on whitespace and never
looking back.

---

## S1 · Signatories row completeness

**Statement.** The number of extracted rows equals the number of numbered rows
in the source, across every page including the first, with no gap in the
sequence.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** See F1. The specific injury: a loop written `range(1, len(doc))`,
skipping page 0, and a row whose name wrapped onto a second line.

**Anti-pattern.** A count of extracted rows. A table read page by page, where
one page is silently the wrong one.

---

## S2 · Clean signatories fields

**Statement.** No date, footnote mark or page artefact appears inside a
jurisdiction name.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The corpus contained `"jurisdiction": "Czechia
13-05-20204 16-08-20245"`, `"Curaçao*2"` and `"Hong Kong (China)6"`. Superscript
footnote markers glued the date cells to the name cell, and no test objected.

**Anti-pattern.** Splitting a table row by whitespace. Trusting that a name is a
name.

---

## S3 · Status is dated

**Statement.** `status_as_of` is the source's own date, and a stale snapshot is
declared as stale.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** A signatories table is a snapshot: the OECD republishes it.
Without a date, "Italy is a party" has no truth value.

**Anti-pattern.** The extraction date presented as the data date.

---

## P1 · No silent truncation

**Statement.** Extracted text is complete, or explicitly marked as truncated with
a reason.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** See F8. 491 excerpts, each exactly 1200 characters, none
flagged.

The check is made against the source, not against a length: every option of every
published position is compared with the text this pipeline reads for the same
option from the same document. On the MLI family that is 103 positions - all of
which it compares, because a family whose excerpts are only checked where they
are short is a family checked where the defect is least likely.

**Anti-pattern.** `text[:1200]`. A length limit that is a constant in a source
file and a surprise in the data.

---

## P2 · Covered-agreements tables

**Statement.** The "covered agreements" table is parsed into structured fields,
or declared not-parsed with a reason. An empty field is never silent.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** 37 of 103 position files had an empty `covered_agreements`
while the flattened table sat inside the `excerpt` field, and no warning was
raised anywhere.

The corpus holds one position per jurisdiction the OECD publishes, read in one
pass from the family's own directory: 103 positions for 110 documents, 98 of them
with their covered-agreements table read. The rest are not silent: each artefact
says why it has none, and the family's own report
(`corpora/mli/positions/batch-report.json`) lists them together with the tables
whose numbering has a hole in it and which numbers the projection found no row
for. A table the projection could not read is a declared gap, not an empty list.

**Anti-pattern.** An empty list that could mean "none" or "I did not look".

---

## P3 · Option classification budget

**Statement.** Every option carries a kind in {Reservation, Notification, Choice,
unclassified}; unclassified options are counted, listed and justified by
language, and stay under 2% of the total.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** 46 of 1620 options (2.84%) were unclassified in the old
corpus, above the project's own stated target, and the number was not surfaced
anywhere a reader would see it.

**Anti-pattern.** An "unclassified" bucket that grows every release and is never
looked at.

---

## P4 · Canonical slugs

**Statement.** One canonical slug per jurisdiction; addenda and instrument
variants are linked to their base object; the country name is never empty; and
every jurisdiction the corpus' own signatories table names is either a published
position or a document the position family declares unread, with the reason.

**Scope.** corpus. **Proof.** `known_defects`,
`test_p04_the_positions_cover_every_jurisdiction`.

**Why it exists.** See F10.

The coverage half of the statement is what makes the family a corpus rather than
a directory: 107 jurisdictions in the signatories table, 110 documents in the
family, 103 positions published, and the 7 jurisdictions that have no position
are exactly the 7 documents whose every page is a scanned image - named in the
family's report as unread, with the reason, so no jurisdiction disappears
silently between the two artefacts that are supposed to agree about it.

The identity half is load-bearing because the publisher ships more than one
document about some jurisdictions: 110 documents make 103 positions. The
document filed under a jurisdiction's own slug is its position; a second document
about it is published beside it, linked by `base_slug`, with a suffix taken from
the publisher's own file name (`additional-notifications`, `draft`) or from the
document's own first paragraph when the file name does not say what it is (the
Russian Federation's provisional list, beside the list it made on deposit). A
second document that neither its name nor its words can be told apart by is not
published under the position's slug at all: it is listed in the family's report,
because publishing it would lose one of the two.

**Anti-pattern.** Two files for one country. A slug that is a translation of a
name rather than the name the source uses.

---

## P5 · Title cells match printed numbers

**Statement.** In every readable position's covered-agreements table, each
printed number the number column holds opens exactly one row in the selected
reader. The legacy title-cell reader must not put multiple printed numbers in one
cell; where its measured cells disagree with the page, that position is either
read by the verified block reader or declared as a legacy exception. A printed
number is never silently lost.

**Scope.** corpus. **Proof.**
`test_p05_title_cells_hold_each_printed_number_once`,
`test_p05_a_number_inside_the_heading_is_justified_by_the_page`,
`test_p05_the_block_reader_tolerances_stay_inside_the_band_the_pages_allow`,
`test_p05_the_declared_tolerances_stay_inside_the_band_the_sources_allow`,
`test_p05_the_published_tolerances_are_the_ones_the_reader_uses`.

**Why it exists.** The reader's own gap declaration (`numbers_with_no_row`) was
trusted as the full account of what a table lost, and the audit of 2026-09-27
caught it under-reporting twice over: 31 of the 98 legacy reads hold title cells
with more than one printed number, and 21 of them declared no gap at all —
mexico published 51 rows numbered to 60 while the page prints a row 61, because
the gap count stops at the last number a published row carries. The mechanism
is a near-full last title line of a row's title block: the justified-edge test
(10 pt slack) cannot see the block boundary, two printed numbers fall into one
cell, the reader opens a row for the first and silently drops the second — or
the number is printed fused with the title's first line ("18 Convention
entre…" as one span) and the row it belongs to is never opened. The dropped
boundary also mis-files text: nigeria's row 1 carries the table's column
headings, ukraine's rows carry two rows' dates in one signature cell.

The block reader holds no shared tolerance either. The width at which a title
line counts as ragged, and the distance within which a mirror counts as a
printed line, are both fractions of the layout's own page pitch — the step a
page repeats between the lines of one column, measured from the page rather than
declared: a quarter of a line for the ragged shortfall, an eighth for the
mirror. The measurement has to skip the baselines a printed line is printed
with (an italic letter is set a fraction of a point above the roman text around
it), so the baselines are keyed by the column their leftmost word starts in and
only steps between two lines of the same column count; on algeria's bilingual
page that reads 13.8 pt where the median of all baselines reads 3.8, and on
israel's 10.3 where the median reads 7.7. The band each tolerance may then
occupy is not narrow — `.verify/probe_tolerance_windows.py` re-reads every
promoted layout under a grid of fixed tolerances and finds the rows identical
from 2.0 pt to 4.5 pt on all 31 — so the fraction is checkable rather than
fitted, and a tolerance that leaves its band is named by the test that pins it
rather than surfacing as one row that quietly moved.

The signatories reader's `ROW_PITCH_TOL` used to be declared as well, and is
measured now. What it decides is how far below its number a line may sit before
it is taken for a stray, as a multiple of the row pitch the reader already
measures on the page. The multiple is fixed by the table's own geometry: the
reader measures the step the table sets its lines at (`mli._line_step`, the modal
gap between two lines of one column, keyed by column exactly as `_page_pitch` is)
and the step it repeats its rows at (`mli._table_pitch`), and a row is
`_table_pitch / _line_step` of its own lines tall — 17.52 pt against 17.5 pt on
the signatories table, one line. A row's own text therefore reaches one row pitch
below its number, and half of one of those lines of slack is allowed on top. Both
terms of that threshold are measured and the half is a half, so nothing in it is
chosen by hand. Measured over the source by
`.verify/probe_row_pitch_depths.py`, the populations that separates are far apart:
the deepest line a row owns — a notification date the table prints under its
number and just too far above the next number to be attached to it — stands
0.808 of a pitch below it, while the first line belonging to a later block, the
intent-to-sign note under the last row, stands 2.017 pitches below the number
above it and the one whose absorption would move a row, "Lebanon", 3.376. The
threshold the reader decides with is the measured length — 17.52 pt plus half of
17.5, which is 1.4994 row pitches — and the artefact records it as the multiple a
reader of the artefact can rebuild the threshold from, rounded to the tenth the
printed geometry is read at, so 1.5 is what it carries. The corpus therefore
reads exactly as it did and no artefact needed republishing; the rounding is of
the report and not of the decision, and the 0.01 pt it costs lies between lines
that stand 14 pt and 59 pt from their numbers. The module constant left in that
name is the fallback for a table whose step or pitch cannot be measured, and it
is checked against the same band as the derived number.

The readers' remaining declared tolerances are pinned rather than derived, and
honestly so. `POS_ATTACH_PT`, `POS_ATTACH_REACH_PT` and `ROW_ATTACH_PT` (how far
above its number a row's lead-in, or a run's last line, may sit, in the
covered-agreements and signatories readers) are
*published measurements*: each travels inside its artefact as `row_attach_pt` or
`span_tol_pt`, so their value is part of the data and re-deriving it per layout
would republish the corpus. What is checked instead is that the reader and the
data still agree — the artefact says how it was measured and the reader must say
the same, and for the derived `row_pitch_tol` the reader's measurement of the
table is what the artefact is compared against. The signatories attach window is
not a length the page pins at all: `mli._row_attach_band` measures off the
placement the reading makes the furthest a line captured up to the next number
stands above that number and the nearest a line left with the number above
stands above the next one — (5.1600 pt, 8.1600 pt) on the source, a three-point
gap the table prints nothing in — so the declared 6.0 is a whole point inside an
interval the page leaves, and which distance inside it a reader uses is a choice
the published data already records. The reading publishes that interval itself,
as `qa.row_attach_band_pt` — `[5.16, 8.16]` on the source, in the same 0.01 pt
the artefact records its other printed distances in — so a consumer of the data
can see the room the window has without rerunning the reader. The
covered-agreements readings publish the same field for their own attach
tolerance, each over its own layout and through its own reader: `[6.77, 11.69]`
on egypt for the block reader's reach and `[5.76, 6.6]` on mauritius for the
number-first window, the 25 readings that decide with one of the two, and `[]` in
the other 75 — which is how the data says that a reading asks the tolerance
nowhere: 27 block and 48 number-first layouts place their spans by title cells or
leave one side of the decision empty, and on the two sources whose spans are
placed by the row markers the page prints (`azerbaijan`, `kuwait`) the window is
declared and published without being asked at all.
The same interval is printed in the position's derived markdown view, beside the
rows it decided (`derived/markdown/mli/positions/<slug>.md`, written by
`harness/views.py::attach_line`): the tolerance, the reader that decided with it
and the interval that layout left it, with an empty interval said in words rather
than drawn as `[]`, because "this reading asks that placement nowhere here, or
leaves one side of the decision empty" is a fact about the reading and not an
absent one. The band is therefore read where the rows are read, and the view is a
second place it cannot move silently: the view control reads the tolerance and
both edges back out of the line and holds them against the artefact's own
`row_attach_pt` and `row_attach_band_pt`, and names the reader the artefact's own
account gives, so a view that moved an edge, moved the tolerance or named the
other reader fails by the part that moved.

The signatories table's view carries the same line
(`derived/markdown/mli/signatories-and-parties.md`, written by
`harness/views.py::signatories_view`): its rows, and the window and band its own
reading publishes, in the same `attach_line` format with that table's own reader
named — because a tolerance both travels in the data and is read beside the rows
it decided nowhere else. The view control reads it back the same way, against
the artefact's own `row_attach_pt` and `row_attach_band_pt`, so a view that moved
an edge, moved the tolerance or named another reader fails by the part that moved
there too.

The family's own report carries every layout's band at once
(`corpora/mli/positions/batch-report.json`, `attach_bands`): each published
position's reader, tolerance and interval, with nulls where a layout publishes no
tolerance, and per tolerance the layouts that set the two edges of the global
intersection — so the intersection the tests pin is readable without re-reading
the sources, and a report that moved a band fails against the artefacts rather
than passing on a copy nobody re-checks.

Making the bands part of the artefacts is also what puts them under the drift
control: a repair that moves a run into one of these gaps is named there as a
difference in `qa.covered_agreements.row_attach_band_pt`, path by path against a
fresh reading, and the view that prints the same interval is regenerated and
compared beside it, instead of the difference showing up only in the invariants — and a repair that
moves the window is named in the view as well as in the JSON: rebuilding one
position below the band the page leaves it moves rows and band together, and the
drift control's line comparison on the two view texts names the attach line's
number among its units.
What
`tests/test_invariants.py` holds is the two halves of that claim: that the
interval measured from the placement is still the interval the sources print,
pinned exactly as the difference of two printed baselines and checked against
the walk's own record of the same band to the 0.005 pt the walk bisects at, and
that the number the artefact publishes for it is the interval the reader
measures now — the artefact and its reader cannot disagree about the gap the
reading sits in.

The covered-agreements readers attach in two ways, and the two are now declared
apart rather than as one window plus a slack. `POS_ATTACH_PT` is the number-first
reader's window — a span printed within it above a row's number belongs to that
row (`mli._row_of`) — and `POS_ATTACH_REACH_PT` is the block reader's reach: a run
of lines printed above a number is absorbed as that row's own prefix only within
that distance of the number (`mli._absorbs_prefix`). They were a single constant,
the reach being the window plus two points, and that made the two share one walk
and one band, so neither could be measured alone: the walk's lower edge came from
the reach's decisions while the number it reported was the window's. Each has its
own band now, measured where its own reader decides, off that reader's own
answers, over two disjoint halves of the corpus. `tests/mli_row_audit.py`'s
`covered_attach_band` measures the reach on the promoted layouts — four of the
thirty-one ask it (egypt, israel, sweden and ukraine) and egypt is tight on both
edges, giving 6.7700 pt to 11.6900 pt — and reports the window there as no band at
all, which the test asserts rather than assumes: no promoted layout's title column
is unjustified, so `covered_agreements` reads them with title cells or with the
displaced-x reader and never asks the placement. `number_first_attach_band`
measures the window on the other half — the 79 position sources the block reader
does not read, of which 62 ask the placement and 21 leave both sides open — and
the intersection is 5.7600 pt to 6.6000 pt, mauritius setting the lower edge with
the deepest lead-in and croatia the upper with the nearest line left above the
number below it. Both edges are distances the pages print, so the band is exact,
and the declared values sit in their bands half-open (6.0 in [5.7600, 6.6000),
8.0 in [6.7700, 11.6900)): both readers compare with `<=`, so a span or a run
printed exactly at the lower edge is captured and one printed exactly at the upper
edge would be too. The reach's band is also walked — the reading itself, away from
the declared value until the rows move — and its walked band, 7.0000 pt to
11.6875 pt, is the tighter record, so the measured band has to contain it. The
window is walked on its own half of the corpus, by the same bisection over the
sources the block reader does not read (`probe_constant_windows.py bisect
numberrows POS_ATTACH_PT`): 70 layouts are read with the module attribute
replaced, and the interval over which every one of them reads its declared rows
is 5.7627 pt to 6.3574 pt. The two records of the same interval are not equal,
and the difference is which layouts are asked. The band is intersected over the
layouts that left *both* sides of the decision open, while the walk asks every
layout that decides with the window — and a layout whose placement left one side
empty reports no band at all, so it is in no intersection while still bounding
the window from the side it did measure. That layout is poland, named by
`.verify/probe_number_first_edges.py`, whose rows move at 6.3632 pt while the
pages that do leave both sides print 6.6000 pt; on the lower side the two
records are one edge to the 0.005 pt the walk bisects at. The window's two edges
are also held against the reading directly, through the reader's rows rather than
the placement bookkeeping the band was measured from — the rows are the declared
ones at each edge and at the declared 6.0, and just beyond each edge the layout
that set it moves. Each artefact publishes the tolerance its own reader decided
with: the block-read positions carry the reach as `row_attach_pt` (8.0) and the
number-first ones the window (6.0), and the published-value check resolves which
one is meant from the artefact's own account of its reader — `printed_number_
anchors`, which only the block reader writes — requiring both halves to be
present so neither comparison is green by emptiness. `JUSTIFY_SLACK_PT` sits at 10 pt
inside a band that never closes above it, with no fraction of any layout's line
landing in it; and `RAGGED_COLUMN_TOL_PT` moves no row on any promoted layout at
the values that leave it as a bound.
`CELL_TOL_PT` moves no row either — it is published as `span_tol_pt` and read by
no decision — so it is pinned by its published value against the rows instead of
by a band, in `P5_UNEXERCISED_TOLERANCES`, and the two sets are checked not to
overlap. Each band is measured by `.verify/probe_constant_windows.py` and each
endpoint is bisected — the interval between a value the reading rejects and the
declared value it accepts is halved until it is 0.005 pt wide — so an endpoint is
a value that was itself read and accepted rather than a grid point: on the
promoted layouts `POS_ATTACH_REACH_PT` may run from 7.0000 pt to 11.6875 pt,
`DATE_WRAP_PT` (how far under a wrapped date fragment its year may stand before
the join is made, `mli._join_wrapped_dates`, which feeds both readers of the
position tables) from 14.0411 pt upward, `RAGGED_COLUMN_TOL_PT` from 0.4001 pt
upward, and `JUSTIFY_SLACK_PT` from 7.0361 pt upward - for these three the walk
found no upper edge within its range and says so, 400 pt, 512 pt and 320 pt being
where it stopped rather than where the band ends; on the signatories
table `ROW_ATTACH_PT` may run from 5.1621 pt to 8.1592 pt and `ROW_PITCH_TOL`
from 0.8086 pt to 3.3721 pt, the tightest band of the six — the band the *derived*
multiple is measured against, with `P5_DERIVED_TOLERANCES` naming it so neither
the pin nor the derivation can leave the other behind. Those signatories edges
are not merely measured but printed, and the walk's endpoints above are the same
two distances `mli._row_attach_band` reads off the placement exactly — 5.1600 pt
to 8.1600 pt, the difference being the 0.005 pt the walk bisects at. So the band
a declared window may occupy is a distance the table prints rather than an
interval a grid happened to find, and the two measurements of it are independent
of each other, one re-reading the sources at moved values and the other reading
the distances off the pages. The two signatories
bands are read off that source under its own register id: read as a position
batch it yields a single row, and a walk over that reading reports bounds for
text nobody publishes.

The pins are a sweep and not a list. Every constant the reader declares under the
tolerance naming - a name ending in `_PT` or `_TOL` - has to appear in one of the
three: a walked band, a band the reader measures for itself, or the range over
which it decides nothing. `test_p05_every_declared_tolerance_is_pinned_somewhere`
enumerates the module for them, so a tolerance added without a band fails by name
instead of deciding rows quietly, and a pin left behind for a constant the reader
has stopped declaring fails as a stale pin too. A number the reader derives
rather than declares is pinned by name in `P5_DERIVED_TOLERANCES` and held
against the band of the multiple it yields.

The same naming is checked in the source, because the shape that made the two
attach tolerances share one band was a *declaration*: the reach was written as
the window plus a slack, so one value wore two names and the layouts that read
one read the other, and no band could be about either alone. `tests/mli_row_audit.py`'s
`tolerance_audit` reads the harness for that shape — no module-level constant may
be computed from a declared tolerance, and no call may pass a declared
tolerance's number where the call takes a tolerance (`_x_clusters(..., tol=4.0)`
was the case, and those three sites now name `RAGGED_COLUMN_TOL_PT`, as the two
in `covered.py` do: the number column's own band, measured with the column
tolerance and not written again) — and
`test_p05_no_declared_tolerance_hides_a_second_role` asserts both lists empty, so
a tolerance cannot come to have a second role without a name failing. It also
*reports* the one shape that can be a legitimate coincidence, a default holding a
declared tolerance's number for a different role: `mli._x_clusters` clusters x
starts within 1.5 pt, which is not the row-pitch multiple, and `ledger`'s line
grouping allows a 25 pt gap, which is not `DATE_WRAP_PT`. Those two are named for
a reader by `.verify/probe_constant_roles.py`, which also prints which readers
name each declared tolerance — the question no band can ask, since a tolerance
read by two readers is one whose band is about neither.

A doubled cell does not always lose the number — a 0.5 pt overlap in the cell
column can keep the row count right while the *text* attribution is already
wrong — which is why the invariant measures the cells, not only counts. For
layout anomalies verified against their pages, the block reader keys each
ragged title block by the printed number inside it, and P5 checks that it emits
each measured number anchor exactly once; the test also pins the recovered
counterparty and title phrase. In addition to the nine initial promotions, Chile,
Colombia and Isle of Man were promoted only after their row counterparties,
titles and dates were checked against their PDFs. China also uses the block reader,
but only after a source-specific rule admits the four complete footer row lines
on their exact pages; regression pins check each row's counterparty, title,instrument and date pair. These 13 source layouts no longer need a legacy
exception. The layouts that remain on the legacy reader are declared by slug in
`P5_CELL_MODEL_EXCEPTIONS`. No layout is declared there today: the last two
exceptions, egypt and peru, were promoted on 2026-10-07, and every earlier
promotion - New Zealand and Slovenia with the merged date run split at the
measured date-column boundary, then algeria, brazil, israel, sweden and
cote-d'ivoire with the 2026-10-06 reader repairs - is named by the same test's
assertions so the list and the record cannot drift apart. The declaration runs
both ways: a mismatch without a declaration fails, and a declared slug whose
cells now match fails too, so that list cannot become a shelf for defects nobody
revisits. Egypt and Peru were the last two because their defect was the row
boundary itself rather than a column: Egypt prints each row's number inside its
heading, so the boundary has to be found from the heading's own mirror about the
number, and Peru prints row 7's counterparty 7pt left of the start the column's
other names share, so the column is measured from the title's printed right edge
inwards. Each exception, while one exists, carries a row-level record in
`DEFECT_INVENTORY` and a row the legacy read gets wrong in
`LEGACY_DEFECT_INVENTORY`, re-read live, so the exception compares the two
readers instead of resting on the block reading's own defect alone. The genuine absence is not an exception: where the page
itself prints no number (papua-new-guinea's row 5), the reader's gap declaration
is the honest account.

One decision inside the block reader is a habit over the whole layout rather
than a fact about a row: whether a run of lines above a number is that number's
own heading or the row above's tail. Egypt, Indonesia, Czechia and Ukraine print
the number inside the heading paragraph, so their rows' blocks open a whole
heading line above the number; every other layout - Israel is the one that
proves it - prints the number at the head of its row and opens on the number's
own line, a tenth of a point apart being one rounded baseline and not a line.
Because the vote is taken over rounded baselines, a version of it that accepted
openings at all read Israel as an inside-the-heading table and truncated every
one of its titles at the block boundary. The line the vote counts is not a shared
constant but half of each layout's own line spacing, measured from the same
anchored groups the vote is taken over, so a table with a different leading needs
no hand-measured number for its titles to survive. The habit is therefore pinned
three times by the same test: the set of layouts the reader calls
number-inside-the-heading is asserted against the reviewed record, the line must
have been measured at all, and the verdict must agree with the depth measured on
those groups, so neither a flipped layout, nor an unmeasurable line, nor a vote
over rounding passes unnoticed.

**Anti-pattern.** A numbering report that stops at the last published row, and
an exception list nobody prunes.

---

## P6 · Reservation scope lists

**Statement.** Every list of agreements a reservation announces within its scope
is read from the page that prints it, one reading per announcement, and
published with the rows the page's own table holds; a statement that announces
more than one list carries one reading each; and a table that was not read is
declared with the reader's reason, in the position's own `qa` and in the family's
report.

**Scope.** corpus. **Proof.** `known_defects`,
`test_p06_the_view_names_the_lists_the_artefact_holds`,
`test_p06_the_view_control_catches_a_stale_list`,
`test_p06_the_lists_are_the_tables_the_page_prints`,
`test_p06_a_row_the_page_leaves_empty_is_named_not_thinned`,
`test_p06_the_page_control_catches_an_invented_row`.

**Why it exists.** A reservation that says "the following agreements contain
provisions that are within the scope of this reservation" and then prints a
table settles, for one specific treaty, whether the reservation reaches it - and
this corpus kept the sentence and not the list, so the only honest answer was
"not in this data". Worse, six statements announce two lists each: Argentina's
Article 7 prints a reservation under Article 7(15)(b) and, under it, one under
Article 7(15)(c), each with its own table of agreements, and this corpus' own
option model reads the two statements as one option because the second carries
no printed label of its own. A reading that took the first announcement for the
statement's only list lost the second table in silence. The family now holds
127 announced lists, reads 126 of them and declares the one it cannot read
(Gabon's Article 17 prints no row numbers in a left column), and holds 2 176 rows
between them.

**What is read, and from where.** The table is located by its own heading row
rather than by the sentence above it, because a statement's prose can continue
past the announcement - Italy's Article 7 prints three lines of explanation
between the sentence and its table - and a table is not claimed when a later
announcement of the same statement stands between the two, because that second
table belongs to the other reservation. Its columns are split where the table
leaves its widest corridor in x - the vertical band no word of the table crosses,
which a justified line of one column cannot open inside that column - its rows
are anchored on the numbers that open their own lines, and each row's number,
counterparty, provision and page are published as the page prints them. What the
page prints in a heading the table does not name does not enter the list:
Norway's Article 3 carries three digits two points above its own headings, the
tail of the covered-agreements table on the page before, and reading them as rows
would put two agreements into a list of one. Nor does a cell that reads a word of
a heading and stands below the table's own first row become a heading: Senegal's
Article 9 list is set justified, so one run of `Royaume Uni de Grande` *is* the
word `de` of the French heading above it, and Mexico's Article 6 prints a `de` of
its own preamble text 400 pt under its headings.

**Where the lists are read.** The position's derived view
(`derived/markdown/mli/positions/<slug>.md`) carries one table per announced
list, after the covered agreements, with a line naming how many lists the
position's statements announce and, where a table was not read, the reader's own
reason in words. The view control reads those tables back against the artefact,
statement by statement, list by list and row by row, so the second list of a
two-list statement cannot go missing from the view either.

**Why the register exists.** `corpora/mli/positions/batch-report.json` carries
`reservation_scope_lists` (how many lists the statements announce, how many were
read, how many rows they hold, how many rows came back with an empty
counterparty or an empty text, and how many statements announce more than one
list), `reservations_announcing_a_list_not_read` (every announcement whose table
this reading could not read, with the reader's own reason),
`reservations_announcing_more_than_one_list` (the statements that announce more
than one, named, because their second table is the one likeliest to be lost) and
`reservation_scope_rows_with_an_empty_cell` (every row whose cell came back
empty, named with the page, the row's number and the cell - the family holds one,
Chile's Article 3 list row 33 on page 6, where the page prints a single
`Article 1(2)` between rows 33 and 34 and the row it stands nearest keeps it).
Each position publishes the same counts and the same names in its own
`qa.scope_lists`, and the control holds the two against each other and against
the artefacts: the named rows are held against the artefacts row by row, and
their number against the counts, so a cell lost to a page break cannot move a
number without saying which row it left.

**What is not claimed.** The rows are the page's, and they are not a judgement
about the reservation: whether a treaty named in a list is inside the reservation
is a question about the Convention's compatibility clauses, which this corpus
does not hold, so the corpus publishes the list and leaves that reading to its
reader. The page control holds the rows against the page in three ways - the
announcement count of the statement's own published prose, each row's number as
the number that opens its line on the row's own page, and every word of every
cell against the page it was read from - and it does not ask the fourth question,
whether the page prints a row the corpus dropped, because that needs the table's
extent on the page and a page can carry two tables under the same headings
(Argentina's page 15 prints its Article 13 reservation's table and, below it, a
notification's, each with its own run of numbers). The control says so here
rather than drawing a band it cannot draw.

**Anti-pattern.** A list announced and not kept, so one treaty's position inside
a reservation has to be called unknowable; a statement's second table read as if
the first were all it printed.

---

## M1 · Mapping verified against the source

**Statement.** Every row's Article number and title is read from the official
Convention PDF, and the test looks each title up again in the source's own words
on the page the row names, so the corpus cannot hold a title the Convention does
not print. Every target names an Article of the base text this corpus holds, in
each edition. Every Article declared to take no option is absent from every
position document. If the source hash changes, the test fails explicitly.

**Scope.** corpus. **Proof.** `test_m1_every_title_is_the_sources_title`,
`test_m1_targets_are_articles_of_the_base_text`,
`test_m1_articles_without_options_are_absent_from_the_positions`.

**Why it exists.** The mapping between MLI provisions and the Model articles is
the part of this project that a lawyer will read first, and it was the part with
the least verification: the titles were transcribed by hand, and a transcription
is a claim about a document nobody re-read.

**What the statement does not claim.** The `mode` and the `targets` are not
verified against the Convention, because the Convention does not state them: it
says what its provisions do in words ("shall apply in place of or in the absence
of provisions of a Covered Tax Agreement that ..."), never "this replaces
Article 10". They are declared once, in `provenance/mli-mapping.yaml`, with the
reasoning beside each line, and what the tests can do with them is check that
they resolve in a corpus that exists: a target naming no Article of the Model, a
mode outside the declared vocabulary, and an option-less Article that a position
document takes an option on are all failures. The rest is a reading of the
sources, and the artefact says so in its `qa` block rather than passing the
reading off as mechanical.

**Anti-pattern.** A hand-maintained table with no mechanical tie to the source.
A title that no test re-reads. A hash change that is not noticed.

---

## M2 · The engine never fakes

**Statement.** Missing base text, unreliable positions and unclassifiable
language all produce `unknown`, never a plausible answer.

**Scope.** corpus. **Proof.** `known_defects`.

**Why it exists.** The engine combines a country's MLI position with the base
convention text. Its most useful output is "this cannot be determined from the
sources available", and it must be willing to say so.

**Anti-pattern.** A fallback that produces a well-formed answer. A default
article text.

---

## What is non-negotiable

These four are not trade-offs; a change that breaks one is not a change to this
specification, it is a different project:

1. **The source is the only authority.** Where the corpus and the source
   disagree, the corpus is wrong, whatever the reason.
2. **Nothing is silent.** Every loss, every transform, every unclassified item
   is counted and named.
3. **Nothing is shipped unverified.** A claim without a reproducing command is
   an opinion.
4. **The corpus is the product; everything else is a view of it.** Views are
   regenerated, never edited.

## What version 1.0 means

Version 1.0 is reached when, for both Model editions and for the MLI layer:

* every invariant above has a test that passes on a freshly built corpus;
* every probe in `fixtures/known_defects.yaml` reports ABSENT on a freshly built corpus;
* `python -m harness --write`, run twice on the same repository with the same
  inputs, produces `docs/harness-status.md` byte for byte (the report describes
  what it found, so a different machine produces a different report - and says
  so);
* a build performed twice, from the same sources, produces identical bytes.

Until then the harness is the deliverable, and the honest status of every
unfinished test is visible in one command.

## The provenance rule

The source documents are the only authority: every count in `known_defects.yaml`
was read from the PDFs, and every probe is written from the source, not from
any earlier output. A test written by diffing old output against new output
proves the two agree, not that either is right. Tests are written from the
source documents.
