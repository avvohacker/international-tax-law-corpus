# Design

How this pipeline is built, and why it is built this way rather than the way the
previous one was.

## 1 · Purpose and non-goals

**Purpose.** Turn a small set of official PDFs - the two editions of the UN Model
Double Taxation Convention and the OECD material on the Multilateral Instrument
- into a corpus that can be cited: a document whose text is identical to the
source's, whose structure is the source's, and whose every unit can be traced
back to the page and position it came from.

**Non-goals.** This is not a legal advice engine, not a set of "good enough"
extractions, and not a place where a missing datum is filled with a plausible
one. Where the source is ambiguous, the corpus says so.

**The single design decision behind everything else.** The previous pipeline read
the page as text and then decided, with filters and regular expressions, what was
body and what was apparatus. This one keeps the page as an ordered stream of
positioned spans, decides the fate of each span by a declared rule, and treats
the corpus as a projection of the spans that were kept.

## 2 · Repository layout

```
provenance/sources.yaml          register of every input: url, sha256, date, rights
sources/                         the PDFs themselves (fetched, hashed, never committed)
rules/<nn>-<scope>.yaml          the classification rules, by id
fixtures/invariants.yaml         what faithful means (machine-readable)
fixtures/known_defects.yaml      the audit, as probes that assert a defect is absent
harness/                         the harness: catalogue, probe engine, status report
tests/                           the invariants, as tests
corpora/<family>/<edition>/
    model-<edition>.akn.xml      the AKN 3.0 body projection
    model-<edition>.manifest.json  counts, missing[], source reference, ledger digest
    model-<edition>.spans.jsonl  the ledger: one line per span, with its rule
    model-<edition>.nodes.jsonl  the structural index: eId, tag, page, span range
corpora/mli/
    signatories-and-parties.json
    mapping.json                               the Convention, Article by Article
    positions/<slug>.json
derived/
    markdown/<family>/<edition>/article-*.md   a view
    markdown/<family>/positions/<slug>.md      a view (covered agreements)
    index.json                                 a view
    reports/*.md                               generated reports
    fts/*.db                                   generated index - never tracked
```

`corpora/` is the product. `derived/` is a view of it. `sources/` is input.
Nothing is written by hand into `corpora/` or `derived/`, ever.

## 3 · The span ledger

This is the seam. `harness/ledger.py` declares it; the extractor implements it.

```
spans = SpanStream.read(pdf, source)          # every span, on every page, nothing dropped
ledger = Classifier.classify(spans, rules)    # each span kept / dropped / transformed, by rule id
corpus = Projection.build(ledger.kept, source)  # structural nodes over kept spans
ok, detail = verify_roundtrip(corpus, pdf, source)
```

A **span** is one run of text with its position: page, x, y, font size, text, and
the index of the printed line it belongs to. It carries no interpretation.
Reading is deterministic and has no opinions, and nothing is filtered while
reading: the running header of page 57 is in the stream, and that is the point -
deciding it is apparatus is the classifier's job, and the decision is recorded
with a rule id.

A **printed line** is rebuilt before anything is decided, because a PDF has no
lines: PyMuPDF splits a tab-indented marker into a line of its own, so paragraph
1 of article 1 arrives as `1.\t` at x = 59 and the sentence at x = 90. The
numbers that rebuild a line are declared by `R-LINE-BUILD`, and they are
measured: inside a printed line consecutive spans sit 0.0pt apart, a tab column
starts 11-21pt to the right, and printed lines are 13pt apart. A source laid out
in table cells declares a narrower gap, because for a table two cells of one row
must stay two spans. The grouping is stamped back onto the spans, so the ledger,
the projection and the node index all count lines the way the printer did.

Two passes, in this order, because the order spans arrive in is the reader's and
not the printer's. The page is first cut into horizontal bands by height
(`y_tol_pt` = 2.5pt), then each band into the lines printed across it from left
to right (`max_gap_pt` = 25pt). One pass cannot work, and the reason is a
fidelity defect rather than a preference: an italic letter is set a fraction of a
point above the roman text around it - measured, the `a` of "attributable to (a)
them" sits 0.15pt higher than its own line - so it arrives *first* and a one-pass
grouper gives it a line of its own, ahead of the words it belongs among. That is
how the corpus came to read "only so much of a them as is attributable to () that
permanent establishment" for "only so much of them as is attributable to (a) that
permanent establishment", and "such permanent establishb c ment or fixed base, or
with ( ) business activities referred to in ( ) of paragraph 1" for "such
permanent establishment or fixed base, or with (b) business activities referred
to in (c) of paragraph 1 of Article 7" - every marker letter moved to the front
of its line with the rest of the marker emptied.

A third measurement, `space_gap_pt` (2.0pt), answers a different question: not
which spans are one line, but which spans of a line must be read with a space
between them. PyMuPDF hands back one span per font run, and the runs of a line
are contiguous - on the 2017 Convention the gaps inside a run reach 1.7pt (383
pairs wider than 0.5pt, an italic letter leaning into the roman bracket beside
it) while a marker in a tab column stands 2.4pt or more away. Concatenating runs
regardless welds a marker to the words it numbers: article 29's "(2) with respect
to an item of income" was read as "(2)with respect to an item of income", a word
no page of the source prints.

The **classifier** gives every span exactly one decision, and the decision is
always a rule id from `rules/*.yaml`. There is no default: a span that no rule
claims is an error the classifier must report, because an unclaimed span is the
place where apparatus gets in. That is the whole difference from the previous
pipeline, where "kept" was the fallback and "dropped" required a pattern to
match. The last rule of every source is a catch-all that *drops*, so "unknown"
cannot become "body" quietly - it becomes a listed span in the audit report.

A **transform** is a rewrite the ledger declares rather than performs silently,
and there are three:

* `R-PARA-MARKER` moves a paragraph marker out of the text and into the node's
  number (`number:1.`), so "1." is a number and "This Convention shall apply to
  persons who are residents..." is the sentence. The marker is its own span in
  this PDF, so nothing is edited: the span is kept, and its text is declared to
  be a number.
* `R-NOTE-MARK` strips a footnote anchor (thin space, digits, thin space, 9pt
  inside 11pt text) from the body and records it as `anchors:12`.
* `R-HYPHEN-JOIN` joins a word broken across a line end, and says which pair of
  lines it joined. Which character marks a break is measured per document, not
  assumed, because the two editions print it differently: 199 of the 200
  line-ending marks in the 2017 Convention are soft hyphens (U+00AD) and the
  plain one is the compound "day-to-day"; the 2021 Convention marks 205 of its
  206 with a plain hyphen. The share (`soft_hyphen_share_min`) decides, for a
  plain hyphen at a line end, between "a break to strip" and "a hyphen the word
  already had": the note is `join_with_next` in the first case and
  `join_with_next_kept_hyphen` in the second. Without the measurement the corpus
  read the 2017 sentence "more of the day-to-day activities" as "more of the
  day-today activities", which is a word in no edition.

The **projection** turns kept spans into nodes. Its vocabulary is the AKN4UN
guidelines (part 1, 4.4.2-4.4.3), which are the authority for modelling a UN
document: `paragraph` for a numbered "1.", `point` for a lettered or roman item
(the item of a `list`), `indent` for indented text with no marker of its own,
`alinea` for unnumbered text in a numbered hierarchy, `hcontainer` for the
alternative branches of articles 8, 18 and 25. Where a node belongs follows from
its marker's depth and from nothing else: a depth this ledger has no name for
raises `RuleError` instead of being emitted at the wrong level, which is how the
fourth depth of article 29 (pages 66-72) was found.

The document-level nodes are `front_matter` (the book: cover, contents,
foreword, introduction), `convention` with its `preamble` child (the instrument
from "TITLE OF THE CONVENTION" onward), chapter, article, alternative, note, and
the `document_boundary` that closes the Convention where the Commentaries begin.

**Why this makes the invariants mechanical.** F2 (no insertion): only kept spans
reach the corpus, so a running header can appear inside a sentence only if a rule
explicitly kept it, and that rule is in a file anyone can read. F3 (no deletion):
every span is either kept or in `dropped` with a rule id and a reason, so a lost
paragraph is a visible ledger entry with a name. F5 (apparatus separation):
footnote text is a rule, not a font-size threshold that happens to be 10pt.
F6 (traceability): the ledger *is* the provenance.

**How the note band is measured.** A footnote is not "text smaller than the
body": in the 2021 edition the Commentaries (10pt) outnumber the Convention
(11pt), so the document's most common size is the smaller one and a rule written
that way read the footnotes of articles 1 and 29 as article text. Nor is it "text
smaller than the line above", because on the page that opens a chapter the line
above is a 14pt chapter title and every line of article 3 looked like a footnote.
What is measured is local to the page: the run of lines at its foot set smaller
than the size most of that page is set at. That is the same evidence a reader
uses, and it is why the footnote of article 1 in the 2021 edition ends up in a
`note` node instead of inside section 4.

**Round-trip.** Rebuilding the span sequence from the projection must reproduce
the classified stream exactly, apart from the transforms the ledger declares
(dehyphenation, marker stripping). This is the one check that can catch a
projection bug that no rule-level check would see, and it is the reason a
`verify_roundtrip` exists at all rather than a family of shape gates.

**Ledger output.** `corpora/<family>/<edition>/model-<edition>.spans.jsonl` is the
ledger written out: a header declaring the fields, the rule ids and the
measurements the reading was made with (`line_policy`, `hyphen_mark`,
`page_shape`, `bands`), then one array per span with `page`, `line`, `x`, `x1`,
`y`, `size`, `decision`, `rule`, `transform`, `note`, `text`. It is committed.
It is the evidence, and it is what a reviewer reads to answer "why is this
sentence not in the corpus?".

The header carries the two claims about the shape of a page as well as its
measurements, and that is deliberate: "the top of this page is a running header"
is a claim, not a measurement, and a reader who disagrees with it needs to see
that it was made. `page_shape` is `prose` for a page whose top is a running
header and whose foot is a page number, `table` for a page that is rows of one
table, `mixed` for prose whose pages carry tables that resume at the top; the
rules that read a band say which of the three they are about, and F7's reading of
the OECD material is the reason that distinction exists at all (see §4).

It is also *readable*: `ledger.reading_of` rebuilds the text the file records
from the records alone - each span's text with the rewrites its record declares,
spans of one printed line glued as the printer printed them, lines separated by
the space a break stands for. `x1` is in the file, and the line policy is in the
header, precisely so that this is possible: a span that starts a column's width
after the previous one ended was printed after a space, and a ledger that records
the text but not the geometry cannot be read back into the text it records. That
is what lets F2 compare the corpus against the ledger rather than against a
second reading of the PDF, and it is why the comparison is arithmetic instead of
impressionistic.

Compact rather than self-describing per line, and the reason is arithmetic: the
2017 Model has 35,729 spans, and repeating ten key names on each of them triples
the file (16 MB against 3.5 MB) for no reader's benefit. `corpus.load_spans`
turns it back into dictionaries, so nothing downstream knows the difference.

**The implementation, as it stands**, measured with
`python -m harness ledger --source un-model-2017`:

```
geometry   body 11.0pt · header y<28 (807 of 828 pages) · footer y>603 (809 pages)
lines      spans within 2.5pt vertically and 25pt apart horizontally,
           a space printed where the gap is 2pt or more
markers    column 59.7:depth 1, 71.7:2, 93.4:3, 111.7:4, 129.7:5
spans      35,729 read · 1,992 kept · 33,737 dropped · 476 transformed · 0 unclaimed
structure  33 articles (1, 2, ..., 12A, 23A, 23B, ..., 31), all titled, in 7 chapters
           6 alternative branches (articles 8, 18, 25 - two each)
           139 paragraphs, 133 points, 34 alineas, 4 notes, convention + preamble
rules      31,239 spans dropped after the Commentaries boundary (page 78)
           1,238 body-text spans, 272 paragraph markers turned into numbers,
           200 hyphen joins (one of which keeps its hyphen), 4 footnote anchors
transform  hyphen_mark soft (199 of 200 line-ending marks are soft hyphens)
round-trip exact - 1,992 placed spans reproduce the kept stream
determinism  two runs of --write produce byte-identical files
```

The 2021 edition measures the same way (2,237 kept spans, 34 articles, 5 notes,
boundary on page 79); it is the edition that exposed two of the measurements
above - the note band and the size of the "Part Two" divider, which its contents
page prints as a bare heading eight pages before the real one.

**The OECD material, read the same way.** The MLI documents - the signatories
table, the Convention, and the 110 position documents of the family - classify with
their own rule layer (`rules/20-mli.yaml`) and their own measurements, and the
two editions of the Model are unchanged by any of it - the bands the 2017 and
2021 Models are read with are the same before and after the page-share
measurement was introduced (header y<28, footer y>603, notes on 54 and 104
pages). Measured with `python -m harness ledger --source mli-...`:

```
signatories table   page shape table · 9pt · header y<84 · footer y>550 · notes on 5 pages
                    744 spans read · 738 kept · 6 dropped (R-MLI-PAGE-NUMBER) · 0 unclaimed
positions (family)  page shape mixed · 110 documents · 3,164 pages · 8pt to 13pt body
                    (67 of them at 11pt) · 204,765 spans read · 200,675 kept
                    4,090 dropped · 262 transformed · 1,722 unclaimed
positions (Italy)   page shape mixed · 11pt · header y<74 · footer y>784 · no note block
                    3,098 spans · 3,046 kept · 52 dropped (R-MLI-PAGE-NUMBER) · 0 unclaimed
positions (Germany) page shape mixed · 10.5pt · header y<77 · footer y>783 · notes on 11 pages
                    1,804 spans · 1,764 kept · 40 dropped · 0 unclaimed
Convention (2016)   page shape prose · 11pt · footer y>764 · no note block
                    2,266 spans · 2,218 kept · 48 dropped (R-PAGE-NUMBER) · 0 unclaimed
```

The family's 1,722 unclaimed spans are the reading's weakest number and they are
published for that reason. They are not lost silently - each document's own audit
lists every one with its text - but they are dropped by the catch-all rather than
by a rule that names what they are, and most of the total is one thing: the
publisher's deposit stamp ("Deposited on 20 November 2020"), repeated in the
footer band of every page of the document that carries it. What is *not* that is
the part that needs a rule, and the measurement says which: on Canada's and
China's positions a covered agreement's title continuation ("Northern Ireland for
the Avo...") is among them, and a cell's line that no rule claims is text the
corpus does not hold.

Two of those lines are measurements this layer exists for. The signatories table
is the document that showed the band model was prose-specific: 8 short lines
repeat at y = 502 on 4 of its 6 pages because table rows align by accident, so at
the Model's band share the footer band begins halfway up a table whose rows run to
y = 760 - and the share is now declared per source (0.80 here, where the page
number is on 6 of 6 pages and the rows on 4 of 6), so the only line in the footer
band is the page number. The positions are the document that showed a header band
can be a lie in the other direction: Italy's page 2 opens with the covered
agreement "Bangladesh Original" / "6 Convention between the" at y = 72, inside
the band a prose rule would call a running header, so a rule that read the band
would drop a covered agreement on every page it continued onto - defect d21
arriving through a rule instead of through an omission.

**The signatories table, projected.** `harness/mli.py` is the MLI projection, and
its first document is live: `corpora/mli/signatories-and-parties.json`, built by
`python -m harness ledger --source mli-signatories-and-parties --write` and
compared byte for byte by F7. Measured with that command:

```
rows              107, numbered 1..107, contiguous, in the source's order
names             "Curaçao*" (the footnote's 2 stripped by R-MLI-NOTE-MARK),
                  "Democratic Republic of the Congo" (a name wrapped over two lines)
status_as_of      "15 September 2026" printed, 2026-09-15 parsed
lines outside     the column headings and the prose before and after the table,
                  listed in the artefact's qa rather than dropped
judgement calls   3 cells, listed with both distances
```

Those three judgement calls are the point of the module. A row is opened by its
number and a cell belongs to the row whose number is the last one above it, but
three of the table's 600-odd cells would go elsewhere under that rule alone, so
the rule is stated and the exceptions are published: the first half of "Democratic
Republic of the Congo" stands 5.2pt *above* the number 29 it belongs to, Finland's
second notification date stands 14.2pt below the number 35 while 8.2pt above the
number 36, and Andorra's arbitration profile stands 2.5pt above its own number.
The two distances and the row each cell went to are written into the artefact's
`qa` block, so the reading can be checked against the page instead of trusted -
which is the difference between this and the old corpus' `"jurisdiction":
"Czechia 13-05-20204 16-08-20245"`, where a cell boundary nobody had stated was
decided by a split on whitespace.

**A position's document, projected - and the projection names no jurisdiction.**
The second document of the MLI projection is `corpora/mli/positions/<slug>.json`,
written by `python -m harness ledger --source mli-position-<x> --write`: the
options the document publishes for each article (the excerpt whole, and
`truncated: false` to say so - defect d19 was a `[:1200]` slice) and the covered
agreements table under Article 2. Four are built: Italy (52 pages, 19 article
sections, 84 rows), Germany (40 pages, 20 sections, 35 rows), the Czech Republic
(26 pages, 15 sections, 86 rows) and the Czech Republic's additional notifications
(7 pages, an addendum, published under `czechia-additional-notifications` with
`base_slug: czechia` - defects d20 and d21 gone).

The module was written once, as a function of the geometry, and it was not
extended per country afterwards. It finds the document's articles from the
numbered outline the document itself prints; it takes the jurisdiction's name
from the title set larger than the text (16pt against an 11pt body) or, for an
addendum that has no such line, from the document's own first sentence - never
from the file name, which is the publisher's (`mli-position-czechia-additional-
notifications.pdf` while every document calls the jurisdiction "Czech Republic");
it reads the covered-agreements table under the article numbered 2 rather than
under the words of its heading, so a position published in another language is
read the same way; and it measures the table's six columns from the table
(`no`, `other_jurisdiction`, `instrument`, `signature`, `entry_into_force`,
`title`) instead of declaring them, because two positions do not print them at
the same x - declared columns would be right for the first document and silently
shifted for the second. `grep -i 'italy\|german\|czech' harness/mli.py` returns
comments only: the measured evidence, with the page it was measured on. The one
jurisdiction-specific decision left - which name and slug to publish, and under
which other names the sources print the same jurisdiction - is data in
`provenance/jurisdictions.yaml`, read by `mli.canonical()`, so adding a country is
a register entry and a `--source`, not a branch.

The table's rows are opened by their own numbers, as on the signatories table,
and the projection records what it could not fit rather than attaching it: Italy's
`qa.covered_agreements` carries the six measured column x's, the numbering
(`first: 1`, `last: 84`, contiguous), `spans_that_fitted_no_column: 0` and
`numbered_rows_without_a_number: 0`. When the title column cannot be told apart -
Italy's is not justified, so its wrapped cells have no interior line that is not
also a cell - the artefact says which signal it used instead
(`rows_delimited_by: the row numbers`) rather than leaving the reader to infer it.

**The Convention, mapped - the half that is read and the half that is declared.**
The third document `harness/mli.py` projects is `corpora/mli/mapping.json`: one
row per Article of the Convention, built by `python -m harness ledger --source
mli-convention-2016 --write`. It exists because this project's subject is not
only what a treaty says but what the MLI does to it, and because that mapping was
the part of the previous build with the weakest verification: its titles had been
transcribed by hand.

So no title is typed here. `mli.mapping()` reads the Article headings from the
kept spans - 39 of them, 1..39 without a gap, in the source's order - and the test
looks each one up *again* in the source's own words on the page the row names, so
a title that was not printed on that page fails the build's own check. What tells
a heading from the body is a measurement rather than a word list: the Convention
sets an Article heading in bold (every span's PyMuPDF flags carry bit 4) and its
body text in the regular weight, so a body sentence that says "Article 16 (Mutual
Agreement Procedure)" - and a position document's quoted "Article 2 - Protocol" in
a table cell - are not headings. Three of the titles are longer than one line and
run onto the next (Article 9's continues "Principally from Immovable Property",
Article 12's "Arrangements and Similar Strategies", Article 13's "Exemptions");
a continuation is admitted while it is bold, on the same page and at the heading's
own left edge (measured: 0.0pt to the right, 12.6pt below), and the three are
listed in the artefact's `qa` so that a reader can see which line the title came
from.

The other half of a row cannot be read, and is declared instead: whether an
Article replaces a treaty provision or inserts a preamble, and which Articles of
the base text it acts on, are in `provenance/mli-mapping.yaml`, one line per
Article with the reasoning beside it. The projection refuses a disagreement in
either direction - an Article the source prints and the register does not
declare, and a declared Article the source does not print - and the tests push
the declaration against the corpus: every target must resolve to an Article of
the Model *in each edition the corpus holds*, and every Article declared to take
no option must be absent from every position document. Both checks have
already earned their keep: the previous reading of Article 5 resolved to "23A,
23B or 23", and the UN Model has no Article 23 - it is 23A and 23B, the
exemption and the credit method - so the phantom alternative is gone; and Article
26 was called administrative, when its own first paragraph says it applies in
place of treaty provisions, which makes it the mutual agreement article's
replacement and not a final clause.

**Editions are declared, not discovered.** `corpus.editions()` used to be a scan
for `corpora/<family>/<edition>/` directories, and the MLI corpus broke it on
contact: `corpora/mli/positions/` is a directory, so the scan called it an edition
and F1, F2, F4 and F6 all demanded an AKN document inside the country positions.
An edition is now the corpus artefact of a source that declares `produces: akn`.
An edition that is declared and absent is still returned - F1 has to be able to
report the AKN it is missing.

The four apparatus defects of the audit are now structurally absent, not filtered
afterwards: `be deductible Articles 24 and 25 under the same conditions` (d01),
the chapter-footer tail glued to a paragraph (d02), the footnote inside "at least
50 per 12 cent" (d09), and "Article 8 (alternative B)" swallowed by the previous
branch (d14) cannot be produced, because the spans that carry them are dropped by
a rule or live in a node of their own. What the ledger says about each of them is
in `corpora/un-model/2017/model-2017.spans.jsonl`, span by span.

Writing the AKN document found four defects of the *reading* that the audit had
not named, because they are not apparatus - they are wrong words: the reordered
words around every italic marker letter (`of a them as is attributable to ()`),
the two statements of article 11(4) interleaved (`establishb c ment`), the weld
`(2)with`, and the compound `day-today`. All four are fixed at the measurement
that caused them, and F2 now checks the corpus against the ledger's own reading
of its kept spans - so a word the writer invented, duplicated or moved is a
failure with the offending word in the message, not an impression.

## 4 · Rule vocabulary

Rules live in `rules/*.yaml` and are read by the classifier. They are data, not
code, for one reason: "why was this text dropped?" must have an answer that is
not a comment in a Python file.

A rule declares `id`, `decision` (`keep` | `drop` | `transform` | `structural`),
`applies_to` (source ids or `*`), a `when` condition, a `rationale`, and the
`prevents` list - the ids of the probes in `fixtures/known_defects.yaml` that
this rule exists to prevent. That last field is the useful one: it makes every
rule answerable with "because of d09".

Conditions are a small declarative language, implemented in `harness/ledger.py`
(`SUPPORTED`): `band`, `shape`, `region`, `text_matches`, `text_fullmatch`,
`text_matches_raw` (the line as printed, for the rules that are about typography
- a footnote anchor is a thin space, and the matching form has already collapsed
it), `superscript_marker` (the line carries a span the printer raised and set
smaller, which is how the OECD documents print a footnote marker - "Curaçao*2",
"Hong Kong (China)6"), `font_pt`, `font_min_pt`, `font_max_pt`, `x0_min_pt`,
`line_ends_with_hyphen`, `next_line_starts_lowercase`, `follows`, `always`, and
the composites `all_of`, `any_of`, `not`. It is deliberately not
Turing-complete: an extractor that needs arbitrary code to decide what is body
text is an extractor that has stopped being explicable.

`shape` is the vocabulary's newest word and the one that earned its place by
being absent. `band` answers "where on the page is this text", and that question
means different things on a prose page and on a table: on a prose page the top is
a running header, on a table it is a row of the table. Every rule that reads a
band is therefore written `shape: prose`, and a source declares which of the
three shapes it has (`R-SOURCE-SHAPE`: prose, table, mixed). Without it the
rule layer had no way to say "this document is not a book", and the only honest
options were to drop a table's rows as apparatus or to keep a table's page
numbers as data.

Three rule fields carry declared data rather than a condition, all of them
measured from the document and all of them enforced - `line_policy`,
`marker_column_policy`, `source_shape` and `band_policy` each raise when their
declaration is missing rather than falling back on a default:

* `params` on `R-LINE-BUILD` - the tolerances a printed line is rebuilt with
  (25pt, 2.5pt, and the 2pt gap that means "the printer left a space");
* `params` on `R-BAND-DEFINE` - `page_share`, how many pages a short line must
  repeat at a height on before that height is a band (0.30 by default, 0.80 for
  the signatories table), counted in *pages* and not in lines, because a table's
  column headings are several short lines at one height on one page and a line
  count lets one page's header block outvote the share on its own;
* `params` on `R-SOURCE-SHAPE` - which of the three kinds of page this document
  has;
* `node_by_level` - maps a marker's depth to the node it opens, so
  ``"marker depth -> node: 1:paragraph, 2:point, 3:point, 4:point"`` is read off
  the rules rather than written into the code.

A rule may use a condition this classifier does not implement. It is not
ignored: `evaluate_when` raises, naming the rule and the condition, so a rule
that is declared but not enforced cannot look like a rule that holds. The MLI
rules were in that state - they named table geometry no reader produced, which is
why the OECD sources could not be classified at all - and they are not any more:
the reading layer they now declare uses only this vocabulary, and the structure
that does still need conditions nobody has implemented (a row, a cell, an option)
is declared as what it is, a standing decision with a reason
(`R-MLI-STRUCTURE-PENDING`) rather than a rule that looks enforceable.

Four rule fields carry meaning beyond the condition:

* `kind` - `span` (evaluated per line), `policy` (a standing decision about the
  pipeline, e.g. "never truncate") or `declaration` (how something is measured).
  Only `span` rules are evaluated; the other two are read by people.
* `region_starts` - this line begins a region (`body`, `commentary`). Regions are
  how "before the Convention", "the Convention" and "the Commentaries" stay
  distinct without the classifier knowing what any of them say.
* `catch_all` - the last rule of a source, and it must `drop`. A catch-all that
  keeps is how `unknown` becomes `body`; the loader refuses to load one.
* `x0_min_pt` - horizontal position, and it earns its place: the 2017 table of
  contents prints "Article 1" at the left margin while the Convention prints the
  same words centred, so the left edge is what tells a heading from a contents
  entry.

The band definitions are measured, not assumed. `R-BAND-DEFINE` states that the
header and footer bands come from lines that repeat at the same vertical position
on consecutive pages. A line is called a running header because it appears where
the running headers appear, page after page - not because it matches a pattern.

## 5 · Projections and views

Everything a consumer sees is generated from the corpus, in one pass, in
`derived/`:

* `derived/markdown/<family>/<edition>/article-*.md` - one file per article, the
  form most people read;
* `derived/markdown/<family>/positions/<slug>.md` - one file per MLI position,
  a table of the counterparty and the dates each covered-agreement row holds,
  rendered from the position artefact and never from the PDF again;
* `derived/reports/*.md` - the edition diff and the coverage report;
* `derived/index.json` - the manifest of everything, with hashes;
* `derived/fts/*.db` - the search index, disposable.

No view re-parses a source. This is invariant F9, and it is the difference
between "the diff says article 1 gained a paragraph" being a finding about the
law and being a bug report about the extractor.

**The edition diff, as the one view that describes two editions at once.**
`harness/diff.py` compares the two editions the corpus holds - not the two PDFs -
node by node: `paragraph`, `point` and `alinea` by eId, `authorialNote` separately
because a note is a node of its own and a change in one is not a change in the
paragraph it hangs from, and `hcontainer` branches by `@name`. An article is
modified when any of those, or its heading, differs. Nothing is truncated: a
quoted unit is the whole unit, because a view that cut a paragraph would be the
defect P1 exists to prevent, one layer up. The report is written as markdown (a
word-level diff: what the 2021 text dropped struck through, what it added in
bold) and as JSON (`derived/reports/diff-<family>-<a>-<b>.{md,json}`), from one
comparison, by `python -m harness diff --write`.

Built that way, the old defect cannot recur - and it is worth saying exactly why,
because the defect was not a formatting bug. The previous report (d24) was
produced by reading the two PDFs a *second* time, and a second reading is where
the artefacts came from: it showed the 2017 edition gaining "Articles 8 and 9" in
the middle of a sentence, which is a page's running head, and it showed a fourth
paragraph of Article 1 that was a footnote fragment. The two trees agreed with
each other and neither was the document. So the report is now a function of the
corpus, its quotations are the nodes' own text, and the probe that used to be a
placeholder string is a recomputation: `report_matches_corpus` re-derives the
comparison from the corpus in the project it is evaluating and requires the
report to agree in both directions - every Article the corpus holds as modified is
in the report's modified list, every Article the report lists is one the corpus
holds as modified, and the summary numbers are the recomputed ones. Against a
report built from a second reading of the PDFs it fires, and its own detail
says exactly:

```
the report and the corpus disagree:
  the corpus holds Article(s) 22, 25, 5 as modified and the report does not
  the report says modified 20 and the corpus says 23
  the report says unchanged 13 and the corpus says 10
```

and here it says `27 modified, 1 added, 6 unchanged - the corpus' own numbers`.
`test_f09_diff_report_is_a_view_of_the_corpus` additionally renders the report
again and compares it byte for byte, so a stale file is a failure and not a
surprise.

## 6 · Determinism and provenance

* JSON is written with sorted keys and a fixed indent; XML with a fixed
  serialisation. No timestamp, no hostname, no absolute path, no dictionary
  ordering, no set iteration in an output path (F7, F14).
* `corpora/**/manifest.json` records the source id, its SHA-256, the article
  count, the paragraph count, the `missing` list, and the SHA-256 of the ledger
  file.
* `provenance/sources.yaml` records, for each input, where it came from, which
  bytes were used, and what the rights are. The PDFs are not committed; the
  hashes are.
* A build run twice from the same sources produces identical bytes, and the test
  suite says so out loud (`test_f07_build_is_byte_identical`).

## 7 · The harness

Two halves, deliberately separate:

* **green** - `fixtures/invariants.yaml`, what the corpus must satisfy, enforced
  by tests that fail while the corpus does not exist, telling you which artefact
  they are waiting for;
* **red** - `fixtures/known_defects.yaml`, what the corpus must stop containing,
  as probes carried from the 2026-09-27 audit.

Three states, and the third is the important one. A probe can report ABSENT
(checked, not present), PRESENT (checked, present, with file and line), or
NOT-EVALUATED (the artefact does not exist yet). A harness that can only say
"pass" and "fail" will eventually say "pass" about something it never looked at.

**Probe discipline.** A probe that has never been shown to fire is
indistinguishable from a broken probe - and shape-only gates were exactly that:
well-formed checks that passed while the corpus contained a footnote in the
middle of a sentence. So every probe here states its defect, its target files,
and the rule that decides it, and a probe whose artefact does not exist yet
reports `NOT-EVALUATED` instead of passing quietly.

## 8 · Build order

The order is not negotiable, and it is the order this repository already
follows:

1. the specification (this document, `SPEC.md`, and the two fixture catalogues);
2. the harness, red on the defects and honest about what it cannot see;
3. the extractor, against a harness that was already trying to fail it;
4. the views, generated from the corpus;
5. the reports, generated from the views.

Nothing in step 3 is written before steps 1 and 2 exist. A pipeline built first
and tested afterwards can only ever be tested against its own assumptions - which
is how a build reaches green with a footnote inside "at least 50 per cent".

## 9 · Decisions left open on purpose

These are real choices, to be made with evidence when the extractor exists. They
are written down so that making them is a decision rather than a drift:

* **Span granularity.** Settled as printed spans (PyMuPDF's own division, one
  per font run), which is what makes the round-trip exact. The open part is
  whether the ledger should also record the intermediate step between spans and
  nodes for a reviewer who wants to see the paragraph, not the span.
* **The note band by tail, not by rule.** A note is detected as the tail of a
  page set smaller than the body. It works on this document (it finds exactly the
  three footnotes of the Convention and stops the 2021-style accident of a note
  landing mid-sentence), but a page whose last body line is legitimately set
  smaller - a caption, a table - would be read as a note and its text would leave
  the body. The mitigation is that it is *visible*: notes are counted, listed and
  attached to a node. A rule that recognises a note's own furniture (the number
  followed by an em space, the short rule above it) would be stronger.
* **Hyphen joins are declared but still a judgement.** Settled for these two
  documents and the shape of the question known: the document is asked which
  character it prints at a line end (199 of 200 marks in the 2017 Convention are
  soft hyphens, 205 of 206 in 2021 are plain) and that decides whether a plain
  "-" is a break or part of the word. What is *not* settled is a document that
  breaks words with a plain hyphen *and* writes compounds with one ("allow-\n
  ances" beside "day-to-\n day"): the share is then no discriminator and this
  would join the compound wrongly. A dictionary of the source's own words, or
  the typographic rule "a break is a break only where the line reaches the
  text's right margin", would decide it; the ledger records every join, so the
error is findable either way.
* **Which model conventions are in scope.** Today the corpus holds the UN Model
  (2017 and 2021, Convention text) and the OECD material on the Multilateral
  Instrument. The **OECD Model Tax Convention is not in the register and not in
  `sources/`**, and it was excluded on *scope* grounds only (1,000+ pages, a
  separate extraction cycle), leaving the decision explicitly open. The rights
  question was left open with it, and is now measured rather than asserted: each
  printing states its own terms, read on the files - the 1963 draft and the 1977
  Model carry a permission clause, the printings from 1992 to 2017 read "(c)
  OECD" with permission or Copyright Clearance Center wording, and only the 2025
  Update and the 2025 Full Version are openly licensed (CC BY 4.0, published
  after 1 July 2024). "Use with citation" is not a single OECD rule and this
  document must not claim one on the publisher's behalf: what each source permits
  belongs in its register entry. So
  this is a scope decision to record before any code: a source id, its URL, hash
  and rights note; a rule layer of its own, because the OECD volume is laid out
  differently from the UN PDFs (two-column pages, Commentary beside the Model
  text); and a corpus family of its own. The invariants need no change - F1, F2,
  F4 and F6 already iterate over every family under `corpora/`.
* **The PDF reader is a hidden input.** Spans depend on PyMuPDF's font-run
  segmentation, so the reader's version belongs in the manifest next to the PDF's
  hash. Reproducibility today means "same reader, same PDF, same bytes".
* **The whole MLI projection is built, and every probe speaks.** The reading
  layer exists and is verified (§3): every span claimed, the page furniture
  dropped by name, 0 unclaimed across every document, and the Model's own
  readings unchanged by it. Four projections stand on it: the signatories table
  (`corpora/mli/signatories-and-parties.json`, 107 contiguous rows; probes d16,
  d17 and d18 ABSENT rather than NOT-EVALUATED), the whole family of position
  documents (`corpora/mli/positions/<slug>.json` - 103 positions, one per
  jurisdiction, each with the options its document publishes for an Article and,
  where the document has one, its covered-agreements table; d19, d20 and d21
  ABSENT too), the MLI-to-Model mapping (`corpora/mli/mapping.json`, 39 rows whose
  numbers and titles are read from the Convention and whose modes and targets are
  declared; invariant M1), and the edition diff
  (`derived/reports/diff-un-model-2017-2021.{md,json}`, a view of the corpus and
  not a second reading of the two PDFs; F9). Nothing in any of them names a
  jurisdiction or a document: the tables are read where the document prints them,
  and the per-jurisdiction decision - which name and slug to publish, and under
  which other names the sources print the same jurisdiction - is data in
  `provenance/jurisdictions.yaml` (P4).

  What the family adds to that model, because one document per jurisdiction is
  how the publisher ships but not what every directory holds:

  * **the family is one source**, declared in the register by a directory and a
    manifest of per-file hashes rather than by 110 entries saying the same thing,
    and read in one pass (`ledger --source mli-positions-batch --write`). What it
    publishes is not only the positions but its own account of itself
    (`batch-report.json`): how many documents are declared, which were read,
    which were not and why, and which jurisdictions have more than one document;
  * **a document that cannot be read is declared, not published empty.** Seven
    documents of the family are the OECD's deposit notices: every page is a
    scanned image, the only text is a rotated stamp, and this pipeline has no
    OCR. They are in the report with the reader's own reason;
  * **the jurisdiction is read from the document's own opening**, and only from
    there: a line that *is* a name this corpus publishes (the largest such line,
    because a title is set larger than the letterhead above it - Hong Kong's
    position opens with the issuing administration's letterhead for the People's
    Republic of China), then a jurisdiction named *inside* an opening sentence
    (Canada's cover has no title line at all), and only then the publisher's file
    name. Measured on the family: 100 documents by their own title, 2 by the
    position they belong to, 1 by its file name (Papua New Guinea's, whose first
    pages are the OECD's template). Searching the *whole* document instead of its
    opening is what made Algeria's position resolve to Canada: a French cover
    title, 1,638 lines all set at the same size, and a covered agreement naming
    Canada;
  * **every decision that could be wrong is published with its authority.**
    `qa.jurisdiction` names the line the jurisdiction was read from, how it was
    resolved, and - for a companion document - what gave it its suffix. A
    jurisdiction named in another language or in a formal form is an *alias in the
    register* (Algeria's French name, Hong Kong's full name, Türkiye's older
    "Turkey"), never a rule in the code;
  * **gaps are published, not repaired.** The family's report lists the positions
    whose covered-agreements table was not read (5, each with the reason its
    artefact gives: two documents have no such table, two tables' columns are not
    yet measured - bilingual tables, whose cells this corpus holds in two scripts
    - and one has no dated table) and the tables whose numbering runs with a hole
    (11, with which numbers the projection found no row for). Renumbering a table
    to close its gaps would make it uncheckable against the page it came from,
    and that is the trade this project does not make.

  One measured reading is worth recording because it changed seven
  jurisdictions at once: the row number of a covered-agreements table is printed
  as `1.` on some positions and as `1` on others, and a rule that required a bare
  integer read those tables as having no numbering at all - which is why their
  rows were absent from the corpus rather than wrong in it.

  The decision this bullet used to hold - cell coordinates or PDF table
  detection - is settled in favour of coordinates, and the measurement is why: on
  the signatories table the number cell is right-aligned at x = 82.3-86.2, the
  jurisdiction at x = 113.0, the signature date at 251.0, the deposit at 346.7,
  the entry into force at 445.9, the later notifications at 623.2 and the
  arbitration profile at 708.1, and the closest pair of columns is 94pt apart.
  Detection would be faster and could not be explained, and here it would also be
  wrong: the table's own cells are not aligned (a cell is printed 15pt below the
  line its row's number stands on), so a detector that drew its rows from
  alignment would put a date in the wrong jurisdiction.

* **The projection's tolerances are constants, and that is the inconsistency
  left.** `ROW_ATTACH_PT` (6.0) and `ROW_PITCH_TOL` (1.5) in `harness/mli.py` are
  measurements of the signatories table with the evidence written beside them,
  and the artefact publishes both in its `qa` block - but every other measurement
  in this pipeline is a declared parameter in `rules/`, read by a `*_policy`
  function that raises when the declaration is missing. Moving these two would
  add a fifth policy reader for two numbers and a projection that has produced
  one document; leaving them is a small inconsistency with a large cause. Noted
  here so that the next projection does not inherit the exception.

* **The OECD Model Tax Convention is still a scope decision, not an oversight.**
  Registered today: the two UN Model editions and the OECD MLI material. The
  OECD Model Tax Convention itself is neither in the register nor in `sources/`,
  and the reason is size and layout, not rights, which are per document and read
  on the files (2025: CC BY 4.0; the printings before it: "(c) OECD" with
  permission wording). Integrating it means a source id, URL, hash and rights
  note;
  a rule layer of its own, because that volume is two-column with the Commentary
  beside the Model text; and a family of its own. Nothing in the invariants needs
  to change: F1, F2, F4 and F6 iterate every family under `corpora/`, and the
  reading layer's three page shapes are exactly the vocabulary a two-column page
  would need to declare.
* **The comment: is the Commentary part of the product?** Today it is a hard
  boundary that is dropped, and the dropped set is listed. Making the
  Commentaries a first-class part of the corpus is a scope decision, not a
  technical one.
* **What the family's reading still drops by default.** 1,722 spans across 54 of
the 110 documents are dropped by `R-MLI-UNCLAIMED` rather than by a rule that
names what they are: the publisher's deposit stamp in the footer band, above all,
and - on two positions - a covered agreement's title continuation. The first is an
apparatus rule waiting to be measured (`R-MLI-FOOTER-TEXT`, beside
`R-MLI-PAGE-NUMBER`, which already covers the bare number in that band); the
second is not apparatus at all and is a gap in the corpus until it is read.
* **Two tables whose columns the measurement still misses.** Azerbaijan's and
Kuwait's covered agreements are not in the corpus, and the reason is measured:
`covered_agreements()` finds the table's title column as the *commonest* x of the
words left of the dates, and on those two layouts that x is the instrument column
beside the title (Azerbaijan's is 380.8, where its titles stand at 117.5), because
the instrument column carries more printed words than the title column does. The
numbers are then looked for in the wrong band and neither they nor the
counterparty column are found, and the artefact says exactly that. The fix is the
same shape as the rest of this project - measure the column where the table
prints it - and the measurement that would do it is already in the reading: the
number column is the column whose values run 1, 2, 3, which can be found before
the title column is asked for, with the title column then being the leftmost
column of words to its right.
* **The tables whose numbering runs with a hole.** 11 positions print a covered
agreements run with gaps (Spain's is 1..86 with 77 rows, Czechia's 1..87 with 86).
The artefact publishes which numbers have no row, and the corpus does not
renumber: whether the missing number belongs to a row the table prints without a
number (the reading lists those too) or to a row this projection did not see is
not yet known for each of the 11, and the difference matters to an invariant that
wants a contiguous run.
* **Where the position text's language is recorded.** A `language` field per
  document, asserted against the document's own text, or nothing. A wrong
  language tag is worse than none.
