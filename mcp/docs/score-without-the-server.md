# Scoring a reader that has the files and no server

The README claims the folder is worth starting. That claim is checkable, and this
is the check: the four questions the comparison is about — two verdicts, one
reservation scope, one refusal — put to a reader that has the same artefacts and
no server, and scored against the server's own answers.

Everything here is executable. From `mcp/`, with the two roots exported:

```bash
python experiments/score_answers.py key              # the key, printed
python experiments/score_answers.py plain-reader     # the baseline, measured
python experiments/score_answers.py prompt           # what a reader with no server is given
python experiments/score_answers.py ask --out T.json # the same, asked of a model
```

## The key

The key is not hand-written: it is read through `itl_mcp`, the same functions the
tools call, so the comparison is with the thing being argued about. It is four
entries, each with the answer, whether that answer is a **silence**, and the
places a reader could cite:

| question | the answer | a silence? | can be cited at |
| --- | --- | --- | --- |
| `as_modified_verdict(treaty_id='uk-us-2001')` | `not-modified` | no | the signatories row on page 5, the United Kingdom's covered-agreements row on page 18 |
| `as_modified_verdict(treaty_id='no-uk-2013')` | `modified` | no | the signatories rows on pages 4 and 5, Norway's row on page 4, the United Kingdom's row on page 13 |
| `reservation_scope(mli_article='7', treaty_id='no-uk-2013')` | `null` | **yes** | nothing: the Article files no reservation to be inside |
| `as_modified_verdict(treaty_id='no-treaty-lives-here')` | `undecidable` | **yes** | nothing: the library does not hold it |

Two of the four answers are silences, which is the point of asking them.

## The transcript, and the three counters

A reader's answers are transcribed in one shape — the shape `plain-reader`
produces and `score` reads — and `ask` makes a model produce it:

```json
{"reader": "who answered",
 "answers": [{"question": "as_modified_verdict(treaty_id='uk-us-2001')",
              "verdict": "not-modified",
              "citations": [["signatories", 5, 105]]}]}
```

Three failures are counted separately, because they are not equally bad:

| counter | what it is |
| --- | --- |
| **wrong verdict** | a token the data does not support, on a question the data can answer |
| **citation that does not carry the fact** | a page or row named as evidence that the server's answer does not carry, so the evidence cannot be checked where the reader says to check |
| **gap filled where the data is silent** | an answer to a question the data cannot frame — a list announced and never captured read as "not on the list", a treaty nobody can find returned as a treaty the MLI does not modify |

A fourth number is reported and not counted: **unanswered**, because a reader that
declines to answer is failing differently again. And a correct token with no
evidence is reported in the row as *none offered* — the token is not the answer.

## The measured baseline

`plain_reader.py` is a reader with no server, no tools and no `itl_mcp`: it reads
the same artefacts and applies the plainest rule each question suggests. It comes
in three variants, and the differences between them are the finding:

| reader | wrong verdict | gaps filled | citations that do not carry the fact |
| --- | --- | --- | --- |
| `strict` — a name matches as the table prints it | **1** | **1** | 0 |
| `helpful` — the marker stripped, a longer official form accepted | 0 | **1** | 0 |
| `analogy` — `helpful`, plus answering what it cannot find | 0 | **2** | 0 |

What each row says:

* **The marker costs a verdict, not a citation.** `strict` never finds the United
  Kingdom's row, because the table prints `United Kingdom*`, concludes that the
  MLI cannot modify a treaty one of whose parties is not a party, and answers
  `not-modified` for the UK–Norway convention — the one treaty in the library the
  MLI *does* modify. The same reader answers the first verdict correctly and with
  **no evidence at all**: the token is right because the wrong reason and the
  right reason happen to agree there. That is the case for asking for the chain
  and not only the verdict.
* **The announced list is not a habit; it is a missing rule.** All three variants
  answer `false` — "not on the list" — for Article 7, where the server answers
  `null` with the reason: Norway files two statements there and neither is a
  reservation, and the second one *announces* a list the corpus never captured.
  No amount of careful reading recovers a list that is not in the file; the rule
  that saves the answer is the server's.
* **Answering what it cannot find costs the fourth question**, and only a reader
  with that habit pays it. This is the smallest of the traps and the one most
  likely to be met in practice, because a model that cannot find something
  usually answers anyway.

No variant produced an unsupported citation: these are readers that cite
carefully and reason from a wrong premise. A model's failures are expected to land
in a different mix, which is exactly what the three counters are for.

## The model half, not measured here

`ask` calls an OpenAI-compatible endpoint named by environment variables —
`ITL_MODEL_BASE_URL`, `ITL_MODEL_API_KEY`, `ITL_MODEL_ID` — sends the four
questions and the contents of the eight artefacts (441.5 KB, the same seven data
files the server reads plus the positions' hash register), and writes the reply as
a transcript to be scored by the same command:

```bash
ITL_MODEL_BASE_URL=... ITL_MODEL_API_KEY=... ITL_MODEL_ID=... \
  python experiments/score_answers.py ask --out model.json
python experiments/score_answers.py score model.json
```

It was **not run**: no model and no credential to one exist in the environment
these numbers were taken in, and a score invented here would be the failure this
whole folder is built to prevent. `ask --dry-run` writes the prompt instead, which
is how its size is measured, and the transcript it produces is scored by a command
whose counters are tested against hand-built transcripts — so the missing number
is one command away, not one experiment away.

## What this does not measure

* **Whether a reader is a good proxy for a model.** The baseline is deterministic
  and its rules are stated; a model's are not. The counters compare both to the
  same key, which is all they promise.
* **Whether the four questions are representative.** They are the ones the README
  discusses — the two verdicts, the reservation question and the refusal — out of
  the twelve the drift control records and the sixty-odd the tools can be asked.
* **The right level for the citation counters.** A citation is `[source, page,
  row]`, and it is supported when the key carries that source and page, with the
  row checked when both sides name one. A model that answers in prose instead of
  citing structured places has to be transcribed by hand, and the transcription is
  where a score can be made to look better or worse.
* **Anything about latency or cost.** The comparison is about answers, not about
  how fast or how cheaply they arrive.
