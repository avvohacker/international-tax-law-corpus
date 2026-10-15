"""The four questions without the server, scored against the server's answers.

The README claims the folder is worth starting. This is the measurement behind
that claim, made executable: the same four questions -- two verdicts, one
reservation scope, one refusal -- go to a reader that has the files and no
server, and its answers are scored against the key, counting three failures
separately because they are not equally bad:

* **a wrong verdict** -- the token it answered with is not the token the data
  supports (`modified` for a treaty the MLI cannot reach);
* **a citation that does not carry the fact** -- a page, a row or a table named
  as evidence that is not in the answer the server gives, so the reader's
  evidence cannot be checked where it says to check;
* **a gap filled where the data is silent** -- an answer where the data cannot
  frame one, which is the failure this project exists to prevent: a list that
  was announced but never captured read as "not on the list", a treaty nobody
  can find returned as a treaty the MLI does not modify.

The key is the server's own answer, read through `itl_mcp` -- the same functions
the tools call -- so the comparison is against the thing being argued about and
not against a hand-written expectation. Two keys can differ: the recorded facts
in `fixtures/expected-answers.json` (what the drift control compares) and this
one (the whole answer, including the refusal and Article 7, which the fixture
does not record).

Usage, from `mcp/`, with `ITL_CORPUS_ROOT` and `ITL_LIBRARY_ROOT` exported:

    python experiments/score_answers.py key                # the key, printed
    python experiments/score_answers.py plain-reader       # the no-server baseline, scored
    python experiments/score_answers.py score T.json       # score a transcript
    python experiments/score_answers.py prompt             # what to hand a reader with no server
    python experiments/score_answers.py ask --out T.json   # needs ITL_MODEL_* (see below)

`ask` calls an OpenAI-compatible endpoint, named by environment variables and
never stored here: `ITL_MODEL_BASE_URL` (e.g. `https://api.openai.com/v1`),
`ITL_MODEL_API_KEY` and `ITL_MODEL_ID`. With `--dry-run` it writes the prompt
instead of sending it, which is also how the prompt's size is measured. A
transcript is the shape both `score` and `plain-reader` produce and consume:

    {"reader": "<who answered>", "answers": [
        {"question": "as_modified_verdict(treaty_id='uk-us-2001')",
         "verdict": "not-modified",
         "citations": [["signatories", 5, 105]]}]}

A citation is `[source, page, row]`, where `source` is `signatories` or the slug
of a position document, and `row` may be `null` when the answer names a page and
no row. It is supported when the key carries an entry with the same source and
page, and -- where both sides name a row -- the same row.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from plain_reader import (                                          # noqa: E402
    ARTICLE_7,
    NO_UK,
    QUESTIONS,
    UNKNOWN_TREATY,
    US_UK,
    transcripts,
)

from itl_mcp.reservations import scope                               # noqa: E402
from itl_mcp.roots import Roots, load_roots                          # noqa: E402
from itl_mcp.verdict import Undecidable, as_modified, _load_position  # noqa: E402

# What the reader is given: the artefacts the four questions are answered from,
# labelled as a reader would meet them. The sizes are read, not asserted.
MATERIAL = (
    ("corpora/mli/signatories-and-parties.json", "the MLI table: 107 rows"),
    ("corpora/mli/mapping.json", "the MLI's own Article list"),
    ("corpora/mli/positions/norway.json", "Norway's position"),
    ("corpora/mli/positions/united-kingdom.json", "the United Kingdom's position"),
    ("library:treaties/uk-us-2001/treaty.json", "the US-UK convention of 2001"),
    ("library:treaties/no-uk-2013/treaty.json", "the UK-Norway convention of 2013"),
    ("provenance/sources.yaml", "where each corpus artefact came from"),
    ("provenance/mli-positions.sha256", "the hashes of the positions"),
)

PROMPT = """You answer questions about tax treaties from the files below, and from
nothing else. Do not use knowledge about any country you think you have, and do
not fill a gap in the files: if the files cannot decide a question, say so.

{questions}

Answer with one JSON object and nothing else:

{{"reader": "<your name>", "answers": [
  {{"question": "<the question id, exactly as printed above>",
    "verdict": "<the answer>",
    "citations": [["signatories", <page>, <row, or null>]]}}]}}

A citation is [source, page, row], where source is "signatories" or the name of
a position document, and it must be a place the files really carry the fact.
"""

THE_QUESTIONS = (
    (US_UK, "What does the MLI do to the US-UK convention of 2001, and why?"),
    (NO_UK, "What does the MLI do to the UK-Norway convention of 2013, and by "
            "which Articles?"),
    (ARTICLE_7, "Does the UK-Norway convention of 2013 fall inside the reservation "
                "each party filed on MLI Article 7?"),
    (UNKNOWN_TREATY, "What does the MLI do to the treaty identified as "
                     "no-treaty-lives-here, and why?"),
)


def _evidence_of_verdict(corpus: Path, payload: dict) -> list[list]:
    """The places a verdict's answer carries, as citations a reader can check."""
    out: list[list] = []
    for standing in payload.get("mli_status") or []:
        # A jurisdiction the table does not print has no page to cite: the
        # absence is a fact of the answer, not a place a reader can point at.
        if standing.get("found_in_table") and standing.get("page") is not None:
            out.append(["signatories", standing.get("page"), None])
    for lookup in payload.get("covered_agreement_lookups") or []:
        # The slug the corpus publishes that document under, resolved the way the
        # verdict itself resolves it: the key is the server's answer.
        payload_of_party = _load_position(corpus, str(lookup.get("position_document_of")))
        slug = (payload_of_party or {}).get("slug")
        entry = lookup.get("entry") or {}
        if slug and entry:
            out.append([slug, entry.get("page"), entry.get("no")])
    return out


def key(roots: Roots) -> list[dict]:
    """The server's own answers to the four questions, with where they point."""
    out: list[dict] = []
    for question, treaty_id in ((US_UK, "uk-us-2001"), (NO_UK, "no-uk-2013")):
        try:
            payload = as_modified(roots, treaty_id).as_dict()
        except Undecidable as error:
            out.append({"question": question, "expected": "undecidable",
                        "silent": True, "evidence": [], "why": error.reason})
            continue
        out.append({"question": question, "expected": payload.get("verdict"),
                    "silent": False,
                    "evidence": _evidence_of_verdict(roots.corpus, payload),
                    "why": (payload.get("reasoning") or [""])[0]})

    answer = scope(roots, "no-uk-2013", "7")
    out.append({"question": ARTICLE_7, "expected": answer.get("answer"),
                "silent": answer.get("answer") is None,
                "evidence": [],
                "why": "; ".join(str(party.get("why")) for party in
                                 answer.get("parties") or [])})

    try:
        as_modified(roots, "no-treaty-lives-here")
        out.append({"question": UNKNOWN_TREATY, "expected": "not-modified",
                    "silent": False, "evidence": [], "why": "the library holds it"})
    except Undecidable as error:
        out.append({"question": UNKNOWN_TREATY, "expected": "undecidable",
                    "silent": True, "evidence": [], "why": error.reason})
    return out


def _token(value: object) -> object:
    """A verdict as a transcript may spell it, read back as the token it means."""
    if isinstance(value, str):
        folded = value.strip().strip('"').strip("'").casefold()
        return {"true": True, "false": False, "null": None, "none": None,
                "": None}.get(folded, folded)
    return value


def _cited(citation: list, entry: dict) -> bool:
    """Whether the key's answer carries the place this citation names."""
    try:
        source, page, row = citation
    except (TypeError, ValueError):
        return False
    for carried in entry["evidence"]:
        if str(carried[0]).casefold() != str(source).casefold():
            continue
        if carried[1] != page:
            continue
        if carried[2] is None or row is None or carried[2] == row:
            return True
    return False


def score(transcript: dict, entries: list[dict]) -> dict:
    """One transcript against the key: three counters, and what they were."""
    by_question = {answer.get("question"): answer
                   for answer in transcript.get("answers") or []}
    counts = {"wrong_verdict": 0, "filled_gap": 0, "unsupported_citation": 0}
    rows: list[dict] = []
    for entry in entries:
        given = by_question.get(entry["question"])
        row = {"question": entry["question"], "expected": entry["expected"],
               "answered": None, "verdict": "unanswered", "citations": ""}
        if given is None:
            rows.append(row)
            continue
        answered = _token(given.get("verdict"))
        row["answered"] = answered
        citations = given.get("citations") or []
        if answered == entry["expected"]:
            row["verdict"] = "ok"
        elif entry["silent"]:
            row["verdict"] = "gap filled"
            counts["filled_gap"] += 1
        else:
            row["verdict"] = "WRONG"
            counts["wrong_verdict"] += 1
        unsupported = [citation for citation in citations
                       if not _cited(citation, entry)]
        counts["unsupported_citation"] += len(unsupported)
        if unsupported:
            row["citations"] = f"{len(unsupported)} of {len(citations)} not in the answer"
        elif citations:
            row["citations"] = f"{len(citations)} supported"
        elif entry["evidence"] and not entry["silent"] and answered == entry["expected"]:
            row["citations"] = "none offered"
        rows.append(row)
    counts["unanswered"] = sum(1 for row in rows if row["verdict"] == "unanswered")
    return {"reader": transcript.get("reader") or "unnamed", "rows": rows,
            "counts": counts}


def _print(scored: dict) -> None:
    print(f"\nreader: {scored['reader']}")
    width = max(len(row["question"]) for row in scored["rows"])
    for row in scored["rows"]:
        print(f"  {row['question']:<{width}}  {row['verdict']:<10} "
              f"expected {row['expected']!r:<14} answered {row['answered']!r:<14} "
              f"{row['citations']}")
    counts = scored["counts"]
    print(f"  wrong verdict: {counts['wrong_verdict']}   "
          f"gaps filled: {counts['filled_gap']}   "
          f"citations that do not carry the fact: {counts['unsupported_citation']}   "
          f"unanswered: {counts['unanswered']}")


def _material(roots: Roots) -> list[tuple[str, Path]]:
    out = []
    for label, _note in MATERIAL:
        if label.startswith("library:"):
            out.append((label, roots.library / label.split(":", 1)[1]))
        else:
            out.append((label, roots.corpus / label))
    return out


def prompt(roots: Roots) -> str:
    questions = "\n".join(f"{index}. {text}\n   id: {question}"
                          for index, (question, text) in enumerate(THE_QUESTIONS, 1))
    listing = "\n".join(f"- {label}  ({path.stat().st_size / 1024:.1f} KB) - {note}"
                        for (label, path), (_l, note) in zip(_material(roots), MATERIAL))
    return PROMPT.format(questions=questions) + "\nThe files, as a reader with no server finds them:\n" + listing + "\n"


def ask(roots: Roots, out: Path, dry_run: bool) -> int:
    base = os.environ.get("ITL_MODEL_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("ITL_MODEL_API_KEY", "")
    model = os.environ.get("ITL_MODEL_ID", "")
    body = prompt(roots)
    if dry_run or not (base and api_key and model):
        if not dry_run:
            print("set ITL_MODEL_BASE_URL, ITL_MODEL_API_KEY and ITL_MODEL_ID to "
                  "actually ask a model; writing the prompt instead", file=sys.stderr)
        out.write_text(body, encoding="utf-8")
        print(f"prompt written to {out} ({len(body) / 1024:.1f} KB, the questions "
              f"and the file list; the files themselves are not inlined)")
        return 0
    for label, path in _material(roots):
        body += f"\n\n===== {label} =====\n" + path.read_text(encoding="utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "temperature": 0, "messages": [
            {"role": "user", "content": body}]}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:              # reported, not swallowed
        print(f"the model call failed: {error}", file=sys.stderr)
        return 2
    text = reply["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    transcript = json.loads(text[start:end + 1])
    transcript.setdefault("reader", model)
    out.write_text(json.dumps(transcript, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"transcript written to {out} (asked {len(body) / 1024:.1f} KB of files)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=("key", "plain-reader", "score", "prompt", "ask"))
    parser.add_argument("transcripts", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=Path("transcript.json"))
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)

    roots = load_roots()
    entries = key(roots)

    if arguments.what == "key":
        for entry in entries:
            print(f"\n{entry['question']}\n  expected: {entry['expected']!r}"
                  f"   silent: {entry['silent']}\n  evidence: {entry['evidence']}"
                  f"\n  why: {entry['why'][:160]}")
        return 0
    if arguments.what == "prompt":
        print(prompt(roots))
        return 0
    if arguments.what == "ask":
        return ask(roots, arguments.out, arguments.dry_run)
    if arguments.what == "plain-reader":
        for transcript in transcripts(roots.corpus, roots.library):
            _print(score(transcript, entries))
        return 0

    for path in arguments.transcripts:
        _print(score(json.loads(path.read_text(encoding="utf-8")), entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
