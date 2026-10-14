# International Tax Law Data — a guide with maps and tables

*What this project is, written for a professor or researcher of international
tax law with no assumed background in software, AI, or agents. This English
original is the source of truth; any translation into another language lives
outside this repository.*

## 1. In one sentence

This is a **citable law library**: it takes official PDFs — the UN Model
Double Taxation Convention (2017 and 2021 editions) and the OECD material on
the Multilateral Instrument (MLI) — and turns them into texts that can be
cited article by article, where **every sentence points back to the exact
page of the PDF it came from**. The page is the provenance of the reading, which
is how the text can be checked against the printing; what a citation names is the
provision - article, paragraph, point - and no page number is part of it.

It is not a legal adviser, it does not interpret, and it never fills a gap
with a guess: where the source is unclear or unreadable, **it says so**
instead of inventing.

## 2. Map 1 — the journey of a document (from page to citable text)

```
Official PDF (UN / OECD)
  │  e.g. the 2021 UN Model, the MLI position of Italy
  │  The PDFs are not stored here: they belong to their publishers.
  │  What is stored is their fingerprint (SHA-256 hash).
  ▼
READING — "the ledger of every printed line"
  │  The program reads every run of text together with its place
  │  on the page (page, line, horizontal position, font size).
  │  Nothing is dropped at this stage: running headers and page
  │  numbers are read too, then classified.
  ▼
CLASSIFICATION — "body or furniture?"
  │  Every line is decided by a written, readable rule (files in
  │  `rules/`): treaty body, footnote, running header, page number,
  │  chapter heading, and so on.
  │  A line no rule claims is a visible error, never a silence.
  ▼
PROJECTION — the legal structure
  │  The "body" lines become nodes: chapter → article → paragraph
  │  → point → alinea; the alternatives (Articles 8, 18, 25:
  │  "Alternative A / B") become labelled branches, never plain
  │  text; footnotes become `note` nodes anchored at the right point.
  ▼
ROUND-TRIP CHECK
  │  The structured text is expanded back into the line sequence
  │  and compared with what was read: the two must match exactly
  │  (apart from declared line-end word joins).
  ▼
CORPUS (the product) + VIEWS (the reading forms)
   corpus: legal XML (AKN), JSON, reading ledgers
   views:  one Markdown file per article, readable tables,
           the 2017-to-2021 comparison, the general index
```

**A chambers analogy:** the PDF is the photocopy; the corpus is the critical
edition of a code — same text, but with stable numbering, checkable
references, and an apparatus that always states *which page* each paragraph
comes from.

## 3. Map 2 — what the library holds today

```
CORPUS (corpora/)
│
├─ UN Model 2017 ── 33 articles + alternatives (8, 18, 25) + 4 notes
│    XML + manifest + span ledger + node index + Markdown views
│
├─ UN Model 2021 ── 34 articles + alternatives (8, 18, 25) + 5 notes
│    XML + manifest + span ledger + node index + Markdown views
│
└─ OECD material on the Multilateral Instrument (MLI)
     ├─ Table of signatories and parties: 107 numbered rows 1–107,
     │   no gaps, with its own date ("status as of") and 3 doubtful
     │   cells published with their measurements (never decided silently)
     ├─ Convention-to-treaty map: 39 rows (Articles 1–39), titles READ
     │   from the PDF (never typed by hand), effects declared
     │   separately with reasoning
     └─ Country MLI positions: 110 declared documents → 103 published
         positions (one per jurisdiction) + the family report
         (batch-report.json: which were read, which were not, and why).
         7 documents are unreadable: scanned images (deposit notices)
         with no text — declared unread, never guessed by OCR.
```

## 4. Table 1 — the three content families (what they answer)

| Family | Content | Question it answers | Form it takes |
|---|---|---|---|
| UN Model 2017 / 2021 | Model Convention text, article by article | "What does Article X of the 2021 UN Model say, paragraph by paragraph?" | One file per article (`article-*.md`) + XML with page and line references |
| MLI signatories and parties | Who signed or ratified the MLI, with dates | "Is Italy (or country Y) a party? With which dates and notifications?" | 107-row JSON table + Markdown view |
| MLI country positions | Each country reservation, notification, and choice + its covered-agreements table + the lists of agreements a reservation prints within its scope (127 announced lists, 126 read, 2 176 rows) | "For that bilateral treaty, does country X reservation cover Article Y?" | One JSON per country + a view with counterparty, date and reservation-scope tables; every blank carries its reason |
| MLI map | What each MLI Convention article does to the bilateral treaty | "Does MLI Article 6 replace or complete Model Article 7?" | 39 rows with PDF-read titles + declared and checked modes and targets |
| Edition comparison | What changed between the 2017 and 2021 Models | "Did Article 12B exist in 2017?" | Markdown + JSON report, recomputed from the corpus (never by re-reading the PDFs) |

## 5. Table 2 — the guarantees (invariants: what is promised and how it is proved)

| Promise (in legal language) | How it is secured (without jargon) | What a breach looks like |
|---|---|---|
| Completeness (F1, U1, S1) | Counts are checked against the source: articles, paragraphs, 107 signatory rows; what is missing sits in a reasoned `missing` list | Failed test with expected vs found number |
| Nothing foreign (F2, F5, U3) | Running headers, page numbers, chapter titles, and note fragments never enter the body | Probe naming the file and line of the intruding text |
| Nothing lost (F3, U4, P1) | Every body word is in the corpus, apart from declared typographic joins; truncation is banned | Probe on the missing passage; excerpts always whole with `truncated: false` |
| Faithful structure (F4, U2) | Alternatives A/B are labelled branches; no fake paragraphs | Tests on nodes rather than on text |
| Traceability (F6) | Every unit carries source, hash, page, and span range | Test on every leaf; the span ledger is the proof |
| Reproducibility (F7) | Same sources + same code = same bytes; no index or database tracked; no machine paths (F14) | Byte-identical double-build test |
| Never invented (F8, M2, P2, P3) | An absent datum is `unknown`/`unclassified` with a reason; unread tables carry reasons; unclassifiable options stay under 2% with language reasons | Tests and probes on the `unknown` cases |
| Consistent views (F9) | Markdown, JSON, XML, and reports are generated from one structure; the 2017-to-2021 comparison is recomputed from the corpus | Test that renders the report again and compares byte for byte |
| Resolvable identity (F10, P4) | One canonical slug per jurisdiction; addenda linked (`base_slug`); positions reconciled against the signatory table | Coverage test + slug probes |
| Source provenance (F11) | Register `sources.yaml`: URL, SHA-256, date, verified and dated rights note; no PDF tracked | Register-completeness test + hash re-check |
| Honest claims (F12) | Every number in README and docs is produced by a command or a tracked document | Probes on the claims |
| English only (F13) | Code, tests, and reports in English; the corpus stays multilingual (fidelity to sources) | Italian-language detector over the project |
| Verified map (M1) | 39 titles re-read in the PDF at the stated page; targets resolved in the Model; option-free articles absent from positions | Three dedicated tests (titles, targets, absences) |
| Reservation scope kept (P6) | Every list a reservation prints under itself ("the following agreements are within the scope of this reservation") is read, one reading per announcement - including the six statements that print two, whose second table the corpus' own option model would otherwise lose - and printed in the position's view | A test re-reads every list on its page (row numbers, cells, announcement count); a second test reads each view back against the artefact; a third shows the control biting |

## 6. Table 3 — the controls (what the dashboard does)

| Control | Purpose (analogy) | Command |
|---|---|---|
| Status | The signal lamp: is there a corpus, and what does the control see? | `python -m harness status` |
| Probes | The sentinels: 26 defects from the 2026-09-27 audit, which must read ABSENT here | `python -m harness probes` / `pytest tests/test_known_defects.py` |
| Probe discipline | The honesty rule: every sentinel states its defect, target and deciding rule, and reports NOT-EVALUATED — never a quiet pass — when its artefact does not exist yet | `python -m harness probes` |
| Ledger | The expert report: reads one PDF and prints the line-by-line account with the rule behind every drop | `python -m harness ledger --source un-model-2021` (add `--write` to publish) |
| Drift | The auditor: re-reads the PDFs and names only divergent artefacts; the automated check opens the fix proposal | `python -m harness drift` (plus `--write`, `--body`, `--check-schema`) |
| Edition diff | The update notes: 2017 to 2021, article by article | `python -m harness diff` (plus `--write`) |
| Report | The minutes: full board of invariants and probes | `python -m harness report` / `docs/harness-status.md` |
| Measurers (`.verify/probe_*`) | The calipers: they measure on the PDFs the safe interval of each reading tolerance (bisection at 0.005 pt) | scripts in `.verify/` (e.g. `probe_constant_windows.py`) |

Three verdicts per probe — and the third is the most important: `ABSENT`
(checked, defect absent), `PRESENT` (checked, defect present, with file and
line), `NOT-EVALUATED` (artefact missing: the control says so aloud instead
of passing quietly).

## 7. Map 3 — the hard cases (and how they were settled without tricks)

- **Russia with two documents / Czechia with extra notifications /
  Mauritius as a draft.** The deposited document under the jurisdiction slug
  counts; the second sits beside it, linked (`base_slug`), with a suffix
  from the file name or the document first paragraph. Never two files under
  one name, never a country lost silently.
- **Names in another language or official form** (Algeria in French, the
  full Hong Kong form, Turkey/Turkiye): aliases in the
  `jurisdictions.yaml` register, never branches in code. The name is read
  from the document opening (largest title line, or first sentence, or file
  name only as a last resort).
- **Covered-agreement tables with gapped numbering (11 cases) or
  bilingual columns (2 cases):** published as they stand, missing numbers
  listed. Renumbering for neatness is banned: it would make the table
  uncheckable against the page.
- **Measured reading tolerances, never hand-picked:** how high above its
  number a line may sit, how short a title line may be, and so on are
  intervals measured on the pages (and published in the artefacts as
  `row_attach_band_pt`, also in the Markdown views beside the rows). A fix
  that moves a line into such an interval is named explicitly by the drift
  control.
- **Block reader vs legacy reader:** 13 hard layouts (Egypt, Peru, Chile,
  Colombia, Isle of Man, China under a dedicated rule, and others) moved to
  the verified reader only after line-by-line checks against the PDF. No
  layout holds an exception today; the test fails both for a missing and
  for a stale exception.
- **One statement, two lists of agreements (6 cases).** Six reservations print
  two tables under one printed label: Argentina's Article 7 says the agreements
  within the scope of the reservation under Article 7(15)(b) and, in the next
  paragraph, the same under 7(15)(c). The corpus reads a statement by its
  printed label, so the two reservations are one option - and a reading that
  took the first announcement for the statement's whole list dropped the second
  table in silence. The reading now keeps one list per announcement and the
  family names those six statements, so the case shows up as a shorter list and
  not only as a smaller count.

## 8. What the project does NOT do (an honest boundary)

- It gives no legal advice and interprets no reservation: it provides the
  checked text on which counsel reasons.
- It runs no OCR: the 7 image scans stay declared unread with reasons.
- It does not redistribute the PDFs (they belong to UN/OECD): scripts
  import them on the fly, check the hash, and publish structured text with
  attribution.
- The OECD Model and the Commentaries are not yet in scope (an explicit
  scope decision, not an omission): the invariants already cover them.

## 9. How to check it in 10 minutes (no code knowledge needed)

1. `python -m harness status` — green means "corpus present, no probe fires".
2. Open one article in `derived/markdown/` and compare it with the PDF at
   the page named in the matching JSON.
3. Open `corpora/mli/positions/italy.json`: 84 covered agreements numbered
   with no gaps, 19 article sections, whole excerpts.
4. Open `derived/reports/diff-un-model-2017-2021.md`: 27 modified,
   1 added, 6 unchanged — the corpus own numbers, not a second reading.
5. `python -m harness drift` — "0 divergent" means re-reading the PDFs
   today yields the same artefacts.

## 10. Reference numbers (generated, never hand-copied)

- Invariants: 29 (F1–F14, U1–U4, S1–S3, P1–P6, M1–M2) · known-defect
  probes: 26 · test functions: 78 in 9 files.
- Corpus: 2 UN editions (33 + 34 articles), 107 signatory rows, 39 map
  rows, 110 documents → 103 positions + family report (104 JSON files),
  98 agreement tables read, 103 Markdown position views.
- Reservation scope lists: 64 positions announce at least one, 127 lists
  announced, 126 read, 2 176 rows between them, 6 statements announcing two
  lists each, 1 announced list left unread and 1 row whose cell came back empty -
  both named, not counted only (`batch-report.json`, `reservation_scope_lists`,
  `reservations_announcing_a_list_not_read`,
  `reservation_scope_rows_with_an_empty_cell`).
