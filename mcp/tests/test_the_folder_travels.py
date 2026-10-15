"""The folder travels, and the export answers what this checkout answers.

The README says which half is portable: the **server** answers from an export of
this folder and the two roots, while the **suite** is the half that holds the
seat. That was measured once by hand - exported into a temporary directory, the
server answered and 8 of the 156 tests before this file failed, all of them
because they read the holding repository - and a measurement recorded in a commit
message is not a control. This file is the control.

What it does not do is guess what the answers should be. Both processes are asked
the same questions - the ones the drift control records, plus one refusal - and
their answers must be identical once parsed. A hand-written expectation would
agree with the day it was written; two independent readings of the same artefacts
cannot agree by accident, and the day the exported copy loses something it needs,
only one of the two can answer at all.

The failure this file exists for is a module that reads something beside it: a
fixture, a workflow, a board, a sibling checkout. Committed here, every test in
this suite stays green while the folder a reader takes away answers nothing.

Two things the process under test has to be told, and both were learned by the
positive control at the end of this file failing rather than by reading:

  * an **editable install** of this very package (`pip install -e .`, which the
    compatibility job runs for the `itl-mcp` command) writes a `.pth` that
    installs a finder ahead of `sys.path` - so a plain `python -m itl_mcp.server`
    in the exported directory loads *the checkout the export was copied from*, and
    this file would compare the checkout with itself. The spawned process
    therefore starts with `-S` - no `site`, so no `.pth` runs - and an explicit
    `sys.path`: this folder first, then the third-party packages the server needs.
    The resolution is asserted before any comparison, so a future shadowing shows
    up as a failure of the premise rather than as a green comparison of one thing
    with itself;
  * the export is of the files the holding repository **commits** under this
    folder, read from the working tree. An untracked file a module needs is
    exactly what stays behind and makes this red, which is what a reader copying
    the folder out of a fresh clone would get.
"""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from itl_mcp import ci, drift

REPO = Path(__file__).resolve().parents[1]

# Every question the drift control records, plus one the data cannot answer: a
# refusal is the absence of a fact, so the fixture records none, and it has to
# travel with the folder like every other answer.
REFUSAL = ("as_modified_verdict", {"treaty_id": "no-treaty-lives-here"})

# How a difference is reported: as the question that moved, not as two dicts.
DETAIL = "  {label}\n    here:     {here}\n    exported: {there}"

# The bootstrap of every process this file starts, run with `-S`. `sys.path`
# alone is not enough: an editable install of this package writes a `.pth` that
# installs a finder ahead of `sys.path`, and the export would be shadowed by the
# checkout it came from. With `-S` no `.pth` is read at all, and the two entries
# below are the whole of what the process can import from.
BOOTSTRAP = """
import runpy, sys
sys.path.insert(0, {export!r})
sys.path.append({site!r})
import itl_mcp
here = str(itl_mcp.__file__)
if not here.startswith({export!r}):
    print("the export is shadowed: itl_mcp resolves to " + here, file=sys.stderr)
    raise SystemExit(2)
"""

# What `python -c` runs when the server is asked to speak, and when only the
# resolution is checked.
SERVE = BOOTSTRAP + "\nrunpy.run_module('itl_mcp.server', run_name='__main__')\n"
RESOLVE = BOOTSTRAP + "\nprint(here)\n"


def committed(folder: Path) -> list[Path]:
    """The files the holding repository commits under ``folder``.

    Read from the working tree, so what travels is what a reader of this checkout
    would see; an untracked file is not committed, and does not travel.
    """
    holder = Path(ci.repository(folder))
    listed = subprocess.run(
        ["git", "-C", str(holder), "ls-files", "-z", str(folder.relative_to(holder))],
        capture_output=True, text=True, check=True)
    return [holder / name for name in listed.stdout.split("\0") if name]


def export(destination: Path) -> Path:
    """Copy the committed folder to ``destination``, and nothing else."""
    for path in committed(REPO):
        target = destination / "mcp" / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return destination / "mcp"


def site_packages() -> str:
    """Where this interpreter keeps the packages the server needs (SDK, PyYAML).

    Named explicitly because the spawned process runs with `-S`, which is what
    keeps any installed copy of *this* package away from the export.
    """
    import mcp as sdk

    return str(Path(sdk.__file__).resolve().parents[1])


def program(body: str, where: Path) -> str:
    return body.format(export=str(where), site=site_packages())


def _parameters(where: Path, corpus: str, library: str, body: str):
    return StdioServerParameters(
        command=sys.executable,
        args=["-S", "-c", program(body, where)],
        cwd=str(where),
        env={
            "ITL_CORPUS_ROOT": corpus,
            "ITL_LIBRARY_ROOT": library,
        },
    )


def resolve(where: Path) -> str:
    """The `itl_mcp` a process started in ``where`` actually loads."""
    finished = subprocess.run(
        [sys.executable, "-S", "-c", program(RESOLVE, where)],
        cwd=str(where), capture_output=True, text=True)
    return (finished.stdout.strip() or finished.stderr.strip())


def _text(result) -> str:
    """The text a tool returned, which is always this server's JSON payload."""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


async def _answers(where: Path, corpus: str, library: str,
                   calls: list[tuple[str, dict]]) -> tuple[list[str], list]:
    """Start the server at ``where``, handshake, ask ``calls``, return both."""
    async with stdio_client(_parameters(where, corpus, library, SERVE)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            answers = []
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                answers.append(json.loads(_text(result)))
    return sorted(tool.name for tool in listed.tools), answers


def test_a_folder_taken_out_answers_what_this_checkout_answers(tmp_path, roots):
    """The same questions, to two processes, from two folders: one answer."""
    calls = [(question["tool"], question["arguments"]) for question in drift.QUESTIONS]
    calls.append(REFUSAL)
    labels = [f"{name}({', '.join(f'{key}={value!r}' for key, value in sorted(arguments.items()))})"
              for name, arguments in calls]

    corpus, library = str(roots.corpus), str(roots.library)
    exported = export(tmp_path / "addendum")

    assert resolve(exported).startswith(str(exported)), (
        "the process in the exported folder did not load the export, so this test "
        f"would compare this checkout with itself: {resolve(exported)}")

    here_tools, here = asyncio.run(_answers(REPO, corpus, library, calls))
    there_tools, there = asyncio.run(_answers(exported, corpus, library, calls))

    assert there_tools == here_tools, (
        "the exported folder offers different tools than this checkout: "
        f"{sorted(set(here_tools) - set(there_tools))} missing, "
        f"{sorted(set(there_tools) - set(here_tools))} unasked for")

    differences = [DETAIL.format(label=label, here=here[index], there=there[index])
                   for index, label in enumerate(labels) if here[index] != there[index]]
    assert not differences, (
        "the folder does not travel: taken out of the checkout it answers "
        "differently, so a reader who takes it away has a second set of answers\n"
        + "\n".join(differences))


def test_the_control_fails_when_a_module_does_not_travel(tmp_path, roots):
    """The positive control: one module left behind, and the answers part ways.

    A comparison of two processes proves nothing if it cannot notice a
    difference, and the difference a reader would meet is a file that did not
    come along. `itl_mcp/verdict.py` is the one to drop: `server.py` imports it
    to register the tool, so an export without it cannot answer the question
    asked here at all - not with the same payload, and not with a different one.

    Two earlier versions of this control picked the wrong file and passed what
    they should have failed: `library.py`, which the verdict does not read (the
    reading of the treaty artefacts lives in `verdict.py` and `artefacts.py`),
    and a plain `python -m` start, which an editable install of this package
    silently redirected to the checkout the export came from.
    """
    folder = export(tmp_path / "incomplete")
    (folder / "itl_mcp" / "verdict.py").unlink()

    corpus, library = str(roots.corpus), str(roots.library)
    calls = [("as_modified_verdict", {"treaty_id": "no-uk-2013"})]
    here = asyncio.run(_answers(REPO, corpus, library, calls))[1]
    try:
        there = asyncio.run(_answers(folder, corpus, library, calls))[1]
    except Exception as error:            # a tool that could not be served at all
        there = [f"the exported folder could not answer: "
                 f"{type(error).__name__}: {error}"]

    assert there != here, (
        "an export missing the module every treaty answer reads replied with the "
        f"very same payload: {here} - so nothing here compares anything")
