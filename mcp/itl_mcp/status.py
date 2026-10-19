"""The status board: what this layer knows, and what it does not.

The corpus prints a generated document beside the invariants it holds
(`harness/report.py` is that generator and `docs/harness-status.md` its output)
and the library prints one too. This layer had none, so a reader had to
reconstruct its state from a README, a workflow and a fixture. The rule is the
same one those two follow: every number in the document is produced by a command
— this module is that command — and a test compares the committed document with
its own output, so a hand edit is a red run rather than a drift nobody sees.

Nothing here needs the two checkouts. `itl_mcp.server` refuses to import without
`ITL_CORPUS_ROOT` and `ITL_LIBRARY_ROOT`, and a board that needed them could not
be printed in exactly the place a reader looks for it first. What is read here
is the repository's own committed evidence: the questions this layer promises,
the answers recorded against them, the workflows that run the control, and the
manifest's floor.

One of those is no longer read from the manifest's own directory. The server is
committed inside the corpus, under `mcp/`, and GitHub runs the workflows of a
repository from its root and from nowhere else, so the workflows that run this
package - and the repositories those workflows check out - are found one checkout
up (`itl_mcp.ci.repository`). The floor stays this package's own sentence in
`pyproject.toml`, because it is a claim about where a user may install the
package, not about where it is committed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml

from . import ci, drift

ROOT = Path(__file__).resolve().parent.parent
BOARD = Path("docs") / "status.md"
PACKAGE = Path("itl_mcp")
FIXTURE = Path("fixtures") / "expected-answers.json"
VERDICTS = Path("fixtures") / "verdicts"
EXPERIMENTS = Path("experiments")
PROJECT_NAME = "international-tax-law-mcp"

# The claim this layer makes about itself: it owns no data, reaches for no
# network and reads no PDF, because its evidence is the committed artefacts of
# the other two repositories. A claim no command checks is the kind this family
# refuses, so the modules are read here for the imports that would break it.
# Only import statements are read, which is why naming these in this list is not
# a hit; a module that really imported one would be.
IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", re.M)
EXTERNAL = frozenset(("urllib", "requests", "httpx", "aiohttp", "socket",
                      "fitz", "pymupdf", "pdfminer", "ssl"))
# The other way out of a process, and the one no import of a network client
# names: a module that runs `git` reaches the remote without importing anything
# on the list above. It is counted separately rather than folded in, because the
# claim and the exceptions are different facts - the package answers from
# committed bytes, and one maintenance command asks a remote a question that no
# answer depends on.
SPAWNS = re.compile(r"^\s*(?:from|import)\s+subprocess\b", re.M)


def project_name(root: Path) -> str:
    """The project's own name, read from the manifest at ``root``.

    Not ``root.name``: a checkout called `mcp` in CI, `intl-mcp` on one desk and
    something else on another would print three different boards from one
    repository, and none of the three tells a reader which project the board is
    about. The name in `pyproject.toml` is the one that travels.
    """
    try:
        manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(manifest["project"]["name"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return PROJECT_NAME


def external_readers(root: Path, folder: Path | None = None) -> list[str]:
    """The modules under ``folder`` that import a network client or a PDF reader."""
    found: list[str] = []
    for path in sorted((root / (folder or PACKAGE)).glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in IMPORT.finditer(text):
            if match.group(1) in EXTERNAL:
                found.append(path.name)
                break
    return found


def subprocess_users(root: Path, folder: Path | None = None) -> list[str]:
    """The modules that run another program, named.

    `library_pin` asks `git` for the library's head: it reaches a remote without
    importing a network client, so a scan of imports alone would print `no` over
    a module that does. Named rather than counted, so the board says which file a
    reader has to read to judge it.
    """
    return [path.name for path in sorted((root / (folder or PACKAGE)).glob("*.py"))
            if SPAWNS.search(path.read_text(encoding="utf-8"))]


def verdicts(root: Path) -> list[dict]:
    """The committed skeletons, read without the two checkouts.

    A board that needed the corpus and the library could not be printed where a
    reader looks for it first; what these files are is still readable from them,
    and the one number that would need the data - whether a skeleton is current -
    is the check command's job (`itl_mcp.skeleton --check`), which does need it.
    """
    out: list[dict] = []
    for path in sorted((root / VERDICTS).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            out.append({"name": path.name, "verdict": "unreadable",
                        "articles": 0, "inputs": 0})
            continue
        out.append({"name": path.name, "verdict": payload.get("verdict"),
                    "articles": len(payload.get("articles") or []),
                    "inputs": len(payload.get("inputs") or {})})
    return out


def control(root: Path, package: Path) -> list[str]:
    """The workflow files of ``root`` that run ``package``'s tests, in name order.

    Found rather than named: the board prints the control that exists, so a
    repository that renamed or moved it prints the new name instead of a path a
    reader has to be told to ignore. Two facts together make a control, and both
    are read from the file: it runs pytest, and it works *inside this package* -
    the package being the repository root when the server is a checkout of its
    own, and a directory under it when the server is committed inside the corpus.

    The second fact is what separates this control from a sibling control of the
    same run. The corpus' own drift job runs pytest as well and has since before
    the server moved in; a board that named it here would send a reader to a job
    that never reads these files.
    """
    inside = "." if package == root else package.relative_to(root).as_posix()
    found: list[str] = []
    for path in ci.workflows(root):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = [value for value in ci.values_for(document, "run")
                 if isinstance(value, str) and "pytest" in value]
        where = [value for value in ci.values_for(document, "working-directory")
                 if isinstance(value, str)]
        if steps and (inside == "." or inside in where):
            found.append(path.relative_to(root).as_posix())
    return found


def facts(root: Path) -> dict:
    """The recorded answers, or none when the fixture is not here.

    An absent fixture is a state of the repository, not a crash: the board says
    the file is missing and names the command that writes it. A reader of a
    board that refused to render would have to guess which of the two it was.
    """
    path = root / FIXTURE
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("facts") or {}


def rows(root: Path) -> list[dict]:
    """One row per tool the questions cover, in the order they first appear."""
    recorded = facts(root)
    out: list[dict] = []
    for question in drift.QUESTIONS:
        tool = str(question["tool"])
        if any(row["tool"] == tool for row in out):
            continue
        out.append({
            "tool": tool,
            "questions": sum(1 for q in drift.QUESTIONS if q["tool"] == tool),
            "facts": sum(1 for fact in recorded if fact.split("(", 1)[0] == tool),
        })
    return out


def render(root: Path | None = None) -> str:
    root = Path(root or ROOT)
    table = rows(root)
    recorded = facts(root)
    fixture = root / FIXTURE
    workflows = ci.repository(root)
    runs = control(workflows, root)
    versions = sorted(ci.interpreters(workflows), key=ci.order)
    floor = None
    try:
        floor = ci.floor(root)
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        floor = None
    if floor is None:
        floor_line = "this repository declares no floor in `pyproject.toml`"
    elif floor in versions:
        floor_line = f"the floor `{floor}` among them"
    else:
        floor_line = f"the floor `{floor}` is NOT among them"
    repositories = ci.checked_out_repositories(workflows)
    modules = len(list((root / PACKAGE).glob("*.py")))
    readers = external_readers(root)
    committed = verdicts(root)
    experiment_modules = len(list((root / EXPERIMENTS).glob("*.py")))
    experiment_readers = external_readers(root, EXPERIMENTS)

    lines: list[str] = []
    add = lines.append

    add("# Status")
    add("")
    add("Generated by `python -m itl_mcp.status --write`. Do not edit by hand: "
        "every number below is computed from the repository at the moment of "
        "writing.")
    add("")
    add(f"- project: `{project_name(root)}`")
    add(f"- recorded questions: {len(drift.QUESTIONS)} over {len(table)} tools "
        f"(`itl_mcp.drift.QUESTIONS`)")
    if fixture.is_file():
        add(f"- recorded facts: {len(recorded)} (`{FIXTURE.as_posix()}`, written "
            f"by `python -m itl_mcp.drift --write`)")
    else:
        add(f"- recorded facts: 0 — `{FIXTURE.as_posix()}` is absent: generate it "
            f"with `python -m itl_mcp.drift --write`")
    # The control's workflows are read from the checkout that runs them, and the
    # line says which that is: a reader who assumed they sit beside this file
    # would look in a directory that has none.
    named = ", ".join(f"`{name}`" for name in runs)
    if runs:
        add(f"- the workflows that run it: {named}"
            + ("" if workflows == root else
               " (of the repository that holds this package)"))
    else:
        add("- the workflows that run it: none — no workflow of "
            + ("this repository" if workflows == root
               else "the repository that holds this package")
            + " runs pytest")
    if repositories:
        # As URLs, because that is what they are: a repository slug is an
        # identifier a reader can follow, and writing the owner's name bare
        # would put the account name of a machine in a document - which is the
        # trace `tests/test_no_machine_traces.py` exists to refuse.
        listed = ", ".join(f"https://github.com/{name}" for name in repositories)
        held = ("" if workflows == root else
                "the repository that holds this package, in place - it is what "
                "the run stands in - plus ")
        add(f"- the control reads its evidence from: {held}{listed}")
    else:
        add("- the control reads its evidence from: nothing — no workflow of "
            + ("this repository" if workflows == root
               else "the repository that holds this package")
            + " checks out another repository")
    add(f"- interpreters CI runs: "
        f"{', '.join(versions) if versions else 'none named'} ({floor_line})")
    add(f"- this package reaches the network or reads a PDF by itself: "
        f"{'yes — ' + ', '.join(readers) if readers else 'no'} "
        f"({modules} module(s) under `{PACKAGE.as_posix()}/` scanned for an "
        f"import of one)")
    spawned = subprocess_users(root)
    if spawned:
        add(f"- a command, not a tool, asks a remote through another program: "
            f"{', '.join(spawned)} runs the `git` on the machine to learn whether "
            f"the library has moved past the pin; no module the server answers "
            f"with imports it")
    # The experiments are the one thing here that talks to something outside the
    # checkouts, and they are not part of the package the line above is about.
    # Saying so on the board is cheaper than a reader discovering it in a module
    # that the sentence above says does not exist.
    if experiment_modules:
        add(f"- the experiments under `{EXPERIMENTS.as_posix()}/`: "
            f"{experiment_modules} module(s), "
            + (f"{len(experiment_readers)} of them calling a model endpoint by "
               f"design ({', '.join(experiment_readers)})"
               if experiment_readers else "none of them reaching the network"))
    if committed:
        add(f"- committed verdicts: {len(committed)} "
            f"(`{VERDICTS.as_posix()}/`, written by "
            f"`python -m itl_mcp.skeleton --write`, held to the data by "
            f"`python -m itl_mcp.skeleton --check` and by "
            f"`tests/test_the_verdict_travels_as_a_file.py`)")
        for entry in committed:
            add(f"  - `{entry['name']}`: {entry['verdict']}, "
                f"{entry['articles']} Article(s) behind it, "
                f"{entry['inputs']} input(s) hashed")
    add("")
    add("## Answers that are recorded")
    add("")
    add("One row per tool the recorded questions cover, in the order the "
        "questions first name them.")
    add("")
    add("| tool | questions | facts |")
    add("| --- | --- | --- |")
    for row in table:
        add(f"| `{row['tool']}` | {row['questions']} | {row['facts']} |")
    add("")
    add("## Commands")
    add("")
    add("```console")
    add("ITL_CORPUS_ROOT=... ITL_LIBRARY_ROOT=... python -m itl_mcp.drift")
    add("                            # do the recorded answers still hold")
    add("ITL_CORPUS_ROOT=... ITL_LIBRARY_ROOT=... python -m itl_mcp.drift --write")
    add("                            # record them again: a decision, not a repair")
    add("python -m itl_mcp.status --write")
    add("                            # regenerate this board")
    add("```")
    return "\n".join(lines) + "\n"


def write(root: Path | None = None, out: Path | None = None) -> Path:
    root = Path(root or ROOT)
    target = Path(out) if out else root / BOARD
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(root), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m itl_mcp.status",
        description="Print, or write, the status board of this repository.")
    parser.add_argument(
        "--write", action="store_true",
        help=f"write {BOARD.as_posix()} (this is the only way it is written)")
    parser.add_argument(
        "--out", default=None,
        help="where --write puts the board (default: the committed one)")
    args = parser.parse_args(argv)

    if args.write:
        target = write(ROOT, Path(args.out) if args.out else None)
        print(f"written: {target}")
        return 0
    print(render(ROOT), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
