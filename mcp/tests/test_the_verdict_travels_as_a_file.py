"""The committed skeleton: what a command writes, and what a stale one does.

Three things are asserted, and the third is the one that makes the file a control
rather than a copy of an answer:

* the committed skeleton is what `python -m itl_mcp.skeleton --write` writes now,
  byte for byte - the same treatment the corpus gives every derived artefact it
  commits, so a hand edit is a red run;
* it is the citable half and not the payload: the chain is there, the prose and
  the quoted excerpts are not, and every input it was computed from is named by a
  label that describes the checkout and never a machine;
* a skeleton whose recorded digest has moved **makes the tool refuse**, with the
  input named and the command to run. That check is exercised by pointing the
  tool at a copy with a wrong digest - the positive control the first two
  assertions would otherwise not have.
"""
import json
import shutil
from pathlib import Path

import pytest

from itl_mcp import skeleton

REPO = Path(__file__).resolve().parents[1]


def committed() -> Path:
    return REPO / "fixtures" / "verdicts"


def test_the_committed_skeleton_is_what_the_command_writes(roots, tmp_path):
    """Generated, not edited: the bytes a computation produces, on the nose."""
    written = skeleton.write(roots, tmp_path)
    assert written, "the library holds no treaty, so this check is about nothing"
    assert sorted(path.name for path in written) == \
        sorted(path.name for path in committed().glob("*.json")), \
        "the committed directory and the library disagree about which treaties exist"
    for path in written:
        here = committed() / path.name
        assert path.read_text(encoding="utf-8") == here.read_text(encoding="utf-8"), (
            f"{path.name} is not what `python -m itl_mcp.skeleton --write` writes "
            f"now, so it is a copy of an answer rather than a control")


def test_every_committed_skeleton_passes_its_own_check(roots):
    problems = skeleton.check(roots)
    assert not problems, "a committed skeleton is stale or missing:\n  " + \
        "\n  ".join(problems)


def test_the_skeleton_is_the_citable_half_and_not_the_payload(roots):
    """The chain, the lookups and the silences - and none of the quoted prose."""
    for treaty_id in skeleton.treaties(roots):
        written = (committed() / f"{treaty_id}.json").read_text(encoding="utf-8")
        payload = json.loads(written)
        assert payload["verdict"] in ("modified", "not-modified")
        # The chain is the verdict's own shape: a treaty the MLI does not reach
        # has no Articles behind it, and one it reaches has all of them.
        if payload["verdict"] == "modified":
            assert payload["articles"], "the chain is what makes it citable"
            assert payload["covered_agreement_lookups"], \
                "a modified verdict stands on the lookups that found it covered"
        else:
            assert payload["articles"] == [], payload["articles"]
            assert any("not a signatory or party" in str(step)
                       for step in payload["reasoning"]), \
                "a verdict that is not modified must say which party is outside the MLI"
        assert "what_it_does" not in written, "the MLI's own prose is not the verdict"
        assert "excerpt" not in written, \
            "the words a document files belong to the document, not to this file"
        assert payload["inputs"], "a skeleton that names no input cannot go stale"
        # A label that described the machine would be the trace the family
        # refuses; these name the checkout and the artefact inside it.
        for label in payload["inputs"]:
            assert label.startswith(("corpus:", "library:")), label
            assert not label.startswith("/"), label


def test_a_moved_digest_makes_the_tool_refuse(roots, monkeypatch, tmp_path):
    """The positive control: one wrong digest, and the answer stops being given."""
    folder = tmp_path / "verdicts"
    folder.mkdir()
    for path in committed().glob("*.json"):
        shutil.copy2(path, folder / path.name)
    treaty_id = skeleton.treaties(roots)[0]
    payload = json.loads((folder / f"{treaty_id}.json").read_text(encoding="utf-8"))
    payload["inputs"] = {f"corpus:{'x' * 8}.json": "0" * 64}
    (folder / f"{treaty_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(skeleton, "DIRECTORY", folder)
    reason = skeleton.stale(roots, treaty_id)
    assert reason is not None and "skeleton --write" in reason, reason

    # And through the tool, which is where a caller meets it. The tool takes its
    # directory from the module, so the copy under test is the one it reads.
    from itl_mcp import server

    answer = json.loads(server.as_modified_verdict(treaty_id))
    assert answer["verdict"] == "stale", answer
    assert "skeleton --write" in answer["reason"], answer


def test_the_current_skeleton_does_not_stop_the_answer(roots):
    """The same path, with nothing tampered with: the verdict comes back."""
    from itl_mcp import server

    assert skeleton.stale(roots, skeleton.treaties(roots)[0]) is None
    answer = json.loads(server.as_modified_verdict(skeleton.treaties(roots)[0]))
    assert answer["verdict"] in ("modified", "not-modified"), answer


def test_nothing_here_reaches_the_network_or_reads_a_pdf(roots):
    """The skeleton is the verdict against the checkouts, and nothing else.

    The board asserts this package reaches no network, and a module that hashed
    a remote copy of the data would have to be reported there.
    """
    text = (REPO / "itl_mcp" / "skeleton.py").read_text(encoding="utf-8")
    for reader in ("urllib", "requests", "httpx", "socket", "fitz"):
        assert f"import {reader}" not in text, reader


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
