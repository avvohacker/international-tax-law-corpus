"""The same provision in the two UN Model editions, side by side.

A reader asking about "Article 5" of the UN Model is asking about two documents,
and one of them may say nothing at all. The 2021 edition added Article 12B
(income from automated digital services); the 2017 edition has no such Article,
so an answer that only quoted 2021 would present an addition as if it were the
provision's whole history, and an answer that only quoted 2017 would silently
drop a provision a reader may be looking for.

This module answers that question from what the corpus commits:

* each edition's **node index** (``model-<edition>.nodes.jsonl``), which is where
  the units come from -- their eIds, their numbers, the page each is anchored to;
* the corpus's own **edition diff** (``derived/reports/diff-un-model-2017-2021``),
  which is the corpus's declared reading of what changed between them, node by
  node and note by note, and which records the full old and new text of every
  unit it calls changed;
* each edition's **manifest**, re-checked here the way every other answer is.

What this module does NOT do is decide what a difference means for a particular
treaty. It reports what the two editions print, cites the units, and names the
edition that is silent -- the reader decides what to make of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import artefacts
from .verify import verify_manifest_edition

EDITIONS = ("2017", "2021")
DIFF_REPORT = Path("derived") / "reports" / "diff-un-model-2017-2021.json"

# The two editions the corpus holds and the diff between them. Kept as constants
# so a third edition is a conscious addition rather than a wildcard.
FROM, TO = EDITIONS

# The four buckets the corpus's diff reads an Article's units into, and the same
# four it reads the Article's notes into. All four are named in the answer even
# when three of them are empty, because "2 changed" cannot be told apart from
# "renumbered was not looked at" -- and a summary that silently dropped a bucket
# would drop it exactly on the day it stopped being empty. `renumbered` is empty
# in the report as committed; saying so is the point.
DIFF_BUCKETS = ("changed", "added", "removed", "renumbered")


def _bucket_counts(recorded: dict | None) -> dict[str, int]:
    """How many units the diff records in each of its four buckets."""
    return {name: len((recorded or {}).get(name) or []) for name in DIFF_BUCKETS}


def _spell(counts: dict[str, int]) -> str:
    """``3 changed, 1 removed`` -- the buckets that are not empty."""
    return ", ".join(f"{count} {name}" for name, count in counts.items() if count)


def normalise_article(raw: str) -> str:
    """``12B`` / ``12 B`` / ``art_12B`` / ``Article 12B`` -> ``12B``.

    The corpus spells the same Article differently in different artefacts: node
    eIds are ``art_23A`` while the diff report and the printed heading say
    ``23 A``. Matching on the normalised form is what lets a reader ask with
    either spelling.
    """
    cleaned = str(raw).strip()
    cleaned = re.sub(r"^\s*(art(icle)?)[_\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned.upper()


def _read_nodes(corpus: Path, edition: str) -> list[dict]:
    path = corpus / "corpora" / "un-model" / edition / f"model-{edition}.nodes.jsonl"
    if not path.is_file():
        raise FileNotFoundError(
            f"the {edition} edition's node index (model-{edition}.nodes.jsonl) "
            f"is not in this checkout, so that edition cannot be quoted")
    return [json.loads(line) for line in artefacts.text(path).splitlines()
            if line.strip()]


def _article_nodes(nodes: list[dict], article: str) -> list[dict]:
    """The Article node and everything under it, in document order.

    The eId is the only primary key the corpus publishes, so membership is by
    eId: ``art_5`` itself and every ``art_5__...`` beneath it. No text is
    searched, because a mention of "Article 5" inside Article 7 is not a unit
    of Article 5.
    """
    stem = f"art_{article}"
    return [node for node in nodes
            if node.get("eId") == stem
            or str(node.get("eId", "")).startswith(f"{stem}__")]


def _cite(nodes: list[dict]) -> list[dict]:
    """The units of an Article, as a reader can cite them."""
    return [
        {
            "eId": node.get("eId"),
            "tag": node.get("tag"),
            "number": node.get("number", ""),
            "page": node.get("page"),
            "heading": node.get("title") or None,
        }
        for node in nodes
    ]


def diff_report(corpus: Path) -> dict:
    path = corpus / DIFF_REPORT
    if not path.is_file():
        raise FileNotFoundError(
            f"the corpus's edition diff is not in this checkout ({DIFF_REPORT})")
    return artefacts.document(path)


def _by_number(entries: list[dict]) -> dict[str, dict]:
    return {normalise_article(entry.get("number", "")): entry
            for entry in entries or []}


def _report_reading(report: dict, article: str) -> dict:
    """What the corpus's own diff says about this Article, unparaphrased.

    The entry itself is returned, not a summary of it: the diff quotes the whole
    old and new text of every unit it calls changed, and a reader is entitled to
    the text rather than to this server's description of it.
    """
    added = _by_number(report.get("added")).get(article)
    if added:
        return {"in_the_corpus_diff": "added", "entry": added}
    removed = _by_number(report.get("removed")).get(article)
    if removed:
        return {"in_the_corpus_diff": "removed", "entry": removed}
    modified = _by_number(report.get("modified")).get(article)
    if modified:
        return {"in_the_corpus_diff": "modified", "entry": modified}
    unchanged = {normalise_article(number)
                 for number in (report.get("unchanged") or {}).get("articles", [])}
    if article in unchanged:
        return {"in_the_corpus_diff": "unchanged", "entry": None}
    return {"in_the_corpus_diff": "not_in_the_diff", "entry": None}


def compare(corpus: Path, article: str) -> dict:
    """One Article, in both editions, with the edition that is silent named."""
    asked = normalise_article(article)
    if not asked:
        raise ValueError("no Article number was given")

    report = diff_report(corpus)
    nodes = {edition: _read_nodes(corpus, edition) for edition in EDITIONS}
    units = {edition: _article_nodes(nodes[edition], asked)
             for edition in EDITIONS}

    reading = _report_reading(report, asked)

    answer: dict = {
        "article": asked,
        "editions": list(EDITIONS),
        "from": report.get("from", {}).get("edition"),
        "to": report.get("to", {}).get("edition"),
        "present_in": {edition: bool(units[edition]) for edition in EDITIONS},
        "units": {edition: _cite(units[edition]) for edition in EDITIONS},
        "in_the_corpus_diff": reading["in_the_corpus_diff"],
        "checks": [check.as_dict()
                   for edition in EDITIONS
                   for check in verify_manifest_edition(corpus, edition)],
        "note": (
            "the units are the corpus's own nodes, cited by the eId the corpus "
            "gives them; the diff is the corpus's declared comparison of the two "
            "editions' AKN documents, not of their PDFs, and it quotes the whole "
            "of every unit it calls changed"),
    }

    if reading["entry"] is not None:
        answer["corpus_diff_entry"] = reading["entry"]

    here = [edition for edition in EDITIONS if units[edition]]
    silent = [edition for edition in EDITIONS if not units[edition]]
    if not here:
        answer["reading"] = (
            f"neither edition holds an Article {asked}: neither node index has a "
            f"node with the eId art_{asked}, so this is not a provision either "
            f"edition prints, and there is nothing to compare")
        return answer

    said = (f"Article {asked} is present in the "
            f"{' and the '.join(here)} edition"
            f"{'s' if len(here) > 1 else ''}: "
            f"{', '.join(f'{len(units[e])} unit(s) in {e}' for e in here)}.")
    if silent:
        said += (f" The {' and the '.join(silent)} edition is silent on it: its "
                 f"node index holds no node with the eId art_{asked}, so that "
                 f"edition does not print this Article at all.")
    verdict = reading["in_the_corpus_diff"]
    if verdict == "modified":
        units = _bucket_counts(reading["entry"].get("units"))
        notes = _bucket_counts(reading["entry"].get("notes"))
        said += (f" The corpus's own edition diff records it as modified: it "
                 f"reads the Article's units into four buckets "
                 f"({', '.join(DIFF_BUCKETS)}) and finds "
                 f"{_spell(units) or 'none of them populated'}, carrying the "
                 f"text of every unit it records in corpus_diff_entry. The same "
                 f"four buckets are recorded for the Article's own notes: "
                 f"{_spell(notes) or 'all four empty'}.")
        if reading["entry"].get("retitled"):
            said += (f" It records the Article as retitled, from "
                     f"\u201c{reading['entry'].get('old_heading')}\u201d to "
                     f"\u201c{reading['entry'].get('heading')}\u201d.")
    elif verdict == "unchanged":
        said += (" The corpus's own edition diff records it as unchanged between "
                 "the two editions.")
    elif verdict in ("added", "removed"):
        units = _bucket_counts(reading["entry"].get("units"))
        said += (f" The corpus's own edition diff records it as {verdict} by the "
                 f"later edition, which is the same fact the silence above "
                 f"states.")
        said += (f" Under that entry it carries {_spell(units)}."
                 if _spell(units) else
                 " That entry names the Article and does not quote units "
                 "under it, so the corpus's diff is where the fact of the "
                 "addition lives and the node index above is where its text "
                 "does.")
    elif verdict == "not_in_the_diff":
        said += (" The corpus's diff does not name it among the Articles added, "
                 "removed, modified or unchanged, so no statement about a change "
                 "can be made from that report.")
    answer["reading"] = said
    return answer


def uncomparable(message: str) -> dict:
    """The payload for an Article the corpus cannot compare with itself.

    One builder, called by the tool and by the drift control, so the two cannot
    come to carry different refusals -- which they had.
    """
    return {
        "error": message,
        "note": ("this is a real answer: the corpus in this checkout cannot "
                 "be compared with itself, and this server does not guess "
                 "what the other edition says"),
    }
