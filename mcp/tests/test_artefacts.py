"""The memo in `itl_mcp.artefacts`: what it saves, and what it must not hide.

The server reads the same committed ledger for every question that touches its
edition, so a run reads the same bytes many times - measured with the corpus'
`scripts/read-audit.py`, the suite had to have 116 files and 14 MB present and
opened them 640 times, moving 240 MB. The memo makes the second read of a file
free, and the only thing that could go wrong is a reader being served bytes that
are no longer there.

So these tests are about the two halves at once: that a repeated read costs
nothing, and that a changed file is read again - through `verify_manifest_edition`,
which is the reader that hashes the two big ledgers, not only through the memo's
own front door.
"""

import hashlib
import json
import os
from pathlib import Path

from itl_mcp import artefacts
from itl_mcp.editions import DIFF_REPORT, EDITIONS, compare
from itl_mcp.verify import BYTES, verify_manifest_edition


def _counts() -> dict[str, int]:
    return artefacts.counters()


def test_the_same_bytes_are_read_once(tmp_path):
    """Two reads of one path: one miss, one hit, and the same text."""
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"eId": "art_5"}\n', encoding="utf-8")

    before = _counts()["misses"]
    first = artefacts.text(path)
    after_first = _counts()["misses"]
    second = artefacts.text(path)

    assert first == second == '{"eId": "art_5"}\n'
    assert after_first == before + 1, "the first read has to be a real read"
    assert _counts()["misses"] == after_first, (
        "the second read read the file again, which is the whole cost this "
        "memo exists to remove")


def test_a_document_is_handed_back_as_it_was_parsed(tmp_path):
    """One parse per file, so the second caller gets the object, not a copy.

    That is the contract the readers rely on: what you were given is the record,
    and changing it is not a way to change the corpus.
    """
    path = tmp_path / "treaty.json"
    path.write_text(json.dumps({"id": "uk-us-2001", "units": []}), encoding="utf-8")

    first = artefacts.document(path)
    second = artefacts.document(path)

    assert first is second
    assert first == {"id": "uk-us-2001", "units": []}


def test_the_digest_is_the_digest_of_the_bytes(tmp_path):
    """The memoised hash is the hash, and it is computed once."""
    path = tmp_path / "model-2017.spans.jsonl"
    path.write_bytes(b'{"eId": "art_5"}\n')

    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    before = _counts()["misses"]
    assert artefacts.sha256(path) == expected
    computed = _counts()["misses"]
    assert artefacts.sha256(path) == expected
    assert computed == before + 1, "one file, one digest, one read"
    assert _counts()["misses"] == computed


def test_a_file_that_grew_is_read_again(tmp_path):
    """Size is half the key: a longer file is a different file."""
    path = tmp_path / "position.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert artefacts.document(path) == {"a": 1}

    path.write_text('{"a": 1, "b": 2}', encoding="utf-8")
    assert artefacts.document(path) == {"a": 1, "b": 2}


def test_a_same_length_edit_is_read_again_when_its_mtime_moves(tmp_path):
    """The other half of the key, stated exactly.

    An edit that keeps the size - the byte-for-byte length a tampered page has -
    is caught by the mtime, and this test moves it explicitly rather than
    trusting a filesystem's clock resolution to differ between two writes.
    """
    path = tmp_path / "page.json"
    path.write_text('{"text": "clean"}', encoding="utf-8")
    assert artefacts.document(path) == {"text": "clean"}

    size = path.stat().st_size
    path.write_text('{"text": "dirt!"}', encoding="utf-8")
    assert path.stat().st_size == size, "this test is about the mtime half"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert artefacts.document(path) == {"text": "dirt!"}


def test_a_caller_that_changed_a_file_can_say_so(tmp_path):
    """`forget` is for a writer the key cannot see: an edit at the same tick."""
    path = tmp_path / "register.sha256"
    path.write_text("a" * 64, encoding="utf-8")
    assert artefacts.text(path) == "a" * 64

    # Written without touching size or mtime, which is what the key cannot see.
    stat = path.stat()
    path.write_bytes(b"b" * 64)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert artefacts.text(path) == "a" * 64, (
        "the key cannot see this edit, and this test says so rather than "
        "pretending the memo is omniscient")

    artefacts.forget(path)
    assert artefacts.text(path) == "b" * 64


def _corpus_with(tmp_path: Path, ledger: bytes, akn: bytes) -> Path:
    """The smallest corpus `verify_manifest_edition` will check, hashes declared."""
    corpus = tmp_path / "corpus"
    base = corpus / "corpora" / "un-model" / "2017"
    base.mkdir(parents=True)
    (base / "model-2017.spans.jsonl").write_bytes(ledger)
    (base / "model-2017.akn.xml").write_bytes(akn)
    (base / "model-2017.manifest.json").write_text(json.dumps({
        "ledger_sha256": hashlib.sha256(ledger).hexdigest(),
        "akn_sha256": hashlib.sha256(akn).hexdigest(),
        "source_file": "sources/un-model-2017.pdf",
        "source_sha256": "0" * 64,
    }), encoding="utf-8")
    return corpus


def _bytes_checks(corpus: Path) -> list:
    return [check for check in verify_manifest_edition(corpus, "2017")
            if check.kind == BYTES]


def test_the_reader_that_hashes_the_ledger_still_sees_a_tampered_ledger(tmp_path):
    """The memo must not be a place a tampered ledger hides.

    The ledger is the biggest thing a run hashes, so it is the file the memo
    saves the most on - and this is the reader that would be wrong if the memo
    served it from memory after it changed. Two edits are tried: one that moves
    the size, one that does not.
    """
    corpus = _corpus_with(tmp_path, b'{"eId": "art_5"}\n', b"<akn/>")
    assert all(check.ok for check in _bytes_checks(corpus)), "the fixture starts clean"

    (corpus / "corpora" / "un-model" / "2017" / "model-2017.spans.jsonl").write_bytes(
        b'{"eId": "art_5", "tampered": true}\n')
    assert [check.ok for check in _bytes_checks(corpus)] == [False, True], (
        "a ledger that grew must fail its bytes check on the second read")

    ledger = corpus / "corpora" / "un-model" / "2017" / "model-2017.spans.jsonl"
    stat = ledger.stat()
    ledger.write_bytes(b"x" * stat.st_size)      # same length, other bytes
    os.utime(ledger, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert [check.ok for check in _bytes_checks(corpus)] == [False, True], (
        "a same-length ledger must fail its bytes check when its mtime moved")


def test_a_second_question_reads_no_file_again(roots):
    """The claim in one line: the memo turns the second answer into no I/O.

    Asked against the live borrowings rather than a fixture, because the files
    that make the cost are the corpus' own two edition ledgers and its diff
    report, and a fixture would measure this memo on files nobody has.
    """
    artefacts.forget()
    first = compare(roots.corpus, "12B")
    read_for_the_first = _counts()
    assert read_for_the_first["misses"] > 0, "the first answer has to read something"
    assert (roots.corpus / DIFF_REPORT).is_file()
    assert set(first["present_in"]) == set(EDITIONS)

    second = compare(roots.corpus, "12B")
    after = _counts()
    assert second == first, "the second answer is the first answer"
    assert after["misses"] == read_for_the_first["misses"], (
        "the second question read a file again: "
        f"{after['misses'] - read_for_the_first['misses']} file(s) re-read")
    assert after["hits"] > read_for_the_first["hits"], (
        "nothing was served from memory, so the memo did nothing")
