"""Hold the checkouts a run is handed to one discipline, as CI sees them.

    python scripts/discipline-drift.py --corpus . --mcp mcp
    python scripts/discipline-drift.py --corpus . --library ../library --mcp ../mcp

The layers of this family, one set of rules, and until this control existed
nothing compared the copies of it: the copy of the machine-trace rule had drifted
into three wordings with three exemption lists, the workflow readers had drifted
into two different APIs, and the status board rule was a paragraph of prose each.
The drift was found by reading the three side by side by hand, which is not a
control. This is.

Which half each run holds is the decision this control is built on. A repository
is held to the rules by *its own* run of this script, and by no run it cannot act
on: the corpus' `discipline` job hands in the corpus and the server committed
inside it, the library's own workflow hands in this corpus and the library, and a
desk hands in whatever checkouts it has. `--corpus` names the one that owns the
rules and is the only required switch; a layer that is not handed in is *named* in
the summary as not read rather than quietly left out, because a run that reports
another repository's copy is a run whose red somebody else has to repair - and a
red nobody can act on is a red people learn to read past.

Six things are compared, and each of them can fail on its own:

  * **the copies**: `harness/discipline/` in the corpus against
    `vendor/discipline/` in the other two, byte for byte, and each copy against
    the pin it declares in `provenance/vendored-discipline.yaml`. Equal bytes are
    not enough by themselves - a family can agree on the wrong rule - but a copy
    that names its own rule is not a family at all;
  * **the rule, run**: the machine-trace scan is then run for each repository
    under the identity its *own* CI gives it - the account `runner`, the checkout
    `actions/checkout` makes in that repository's own workflow, which is the
    project's name - and must come back empty. This is the half that equal bytes
    cannot show: the rule walks through prose, and the prose differs. The first
    version of the rule failed here for all three layers, on lines that name
    nobody, because CI's account name is an ordinary English word and all three
    say it in their own workflow comments.

    The identity is the repository's own and not the one this control happens to
    give it: which directory a *sibling's* workflow checks another repository out
    into is that workflow's business, and the first version of this control
    scanned each repository under whatever path it was handed - which on the
    server's runner was `library`, and made the library look red for the word
    "library" in its own prose. A scan whose answer depends on the path the
    grader used is not a check about a machine;
  * **the floor**: every repository must declare the same `requires-python` and
    run it, as a matrix leg that runs the control, or "the family's floor" means
    three different things;
  * **the board**: one generated document per repository, naming the project
    rather than the checkout, held by a test that names both the document and the
    command that writes it, in a run that executes the tests;
  * **the reader**: the same workflow reader reads all three, so the floors above
    were compared by one implementation rather than by three that agree today;
  * **the documents**: every checkout's documents are read by the one rule the
    repositories share - the command that installs the server from the corpus'
    subfolder, the private repository no document may link, and the two documents
    a reader meets first. That rule was a test in each repository, and two
    readings of one rule are two rules: the library's had found its own failure
    and the corpus' had not been written yet.

The server is no longer a repository of its own. It is committed in this one,
under `mcp/`, and GitHub reads the workflows of a repository from its root and
from nowhere else - so the control that runs its tests is
`.github/workflows/mcp-drift.yml` here, and a `mcp/.github/workflows/` would be a
file that looks like a control and is never executed. The reading of a
repository's workflows therefore resolves, for every root, the repository whose
workflows actually run it: itself for the corpus and the library, the corpus for
the server it holds. Everything else - the copies, the pins, the scan, the floor
of a manifest, the board document - is read where it lies, subtree or not.

A desk can run this before pushing; CI runs it in every repository of the family,
each over the checkouts that repository holds, because what this refuses is a copy
that went on saying its own thing - and a copy is only compared by a run that has
both the copy and the source.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The account CI runs as, and the reason the machine-trace rule was rewritten:
# the name is an ordinary English word that all three layers say in their
# own prose. The run is done under it rather than under the desk's account, so
# that a repository whose text collides with its CI account is red here, before
# a runner ever sees it.
AS_CI = "runner"

# The two layers besides the corpus, and why a run that is not handed one says so
# rather than stopping at the checkouts it has. Named here because the summary has
# to tell a layer that was not read from one that was: a silence reads as a pass.
LAYERS = {
    "library": "it is a checkout of its own, and this half is read by this same "
               "script in the library's own run, over the corpus - the run whose "
               "repair is a re-vendor",
    "mcp": "the server is committed inside the corpus, under `mcp/`, and the "
           "corpus' own job hands it in",
}


def load(source: Path):
    """The discipline, loaded from a given copy of it.

    Loaded rather than imported by name: this control is run from three
    repositories, and the copy it must use is the corpus' own, whichever
    directory the run starts in.
    """
    spec = importlib.util.spec_from_file_location(
        "corpus_discipline", source / "__init__.py",
        submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["corpus_discipline"] = module
    spec.loader.exec_module(module)
    return module


def loader_for(script: Path):
    spec = importlib.util.spec_from_file_location("vendor_discipline", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendor_discipline"] = module
    spec.loader.exec_module(module)
    return module


def shared(root: Path) -> Path:
    """Where a repository keeps the shared discipline."""
    mine = root / "harness" / "discipline"
    return mine if mine.is_dir() else root / "vendor" / "discipline"


def workflows_root(root: Path) -> Path:
    """The repository whose workflows run the tests committed under ``root``.

    A repository of this family used to be a checkout of its own, with its
    workflows at its own root, and the reader of a repository's workflows was
    handed that root and nothing else. The server is now committed inside the
    corpus, and GitHub reads the workflows of a repository from its root and from
    nowhere else: a control at `mcp/.github/workflows/` would be a file that looks
    like one and is never executed. So the control stands where it is run, and
    this walks up to the first checkout that has workflows at all. The corpus, the
    library, and the server read as a standalone checkout answer with themselves.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".github" / "workflows").is_dir():
            return candidate
    return root


def board_problems(root: Path, project: str | None, workflows: Path,
                   discipline) -> list[str]:
    """Every way this repository's board breaks the rule, named.

    For a repository that stands alone this is the vendored rule itself, asked
    once. The server does not stand alone any more, and the one clause of the rule
    that is not about its own document - "CI runs the tests, or the third clause
    holds nothing" - is a fact about the repository that runs it. The four clauses
    that *are* about the document are read from the vendored rule's own facts, so
    that nothing here states a rule of its own; the fifth is read, in one line,
    where it is true.
    """
    if workflows == root:
        return discipline.board.problems(root, project)
    found = discipline.board.facts(root, project)
    clauses = {
        "exactly one generated document under `docs/`": found["documents"] == 1,
        "the document says which command writes it": bool(found["command"]),
        f"the document prints `- project: `{found['project']}`":
            found["names_the_project"],
        "a test names the document and the command that writes it":
            bool(found["current_test"]),
        f"a run executes that test (the workflows of {workflows})":
            discipline.ci.runs_pytest(workflows),
    }
    return [f"the board of {root}: {clause} does not hold"
            for clause, holds in clauses.items() if not holds]


def facts(root: Path, discipline) -> dict:
    """What the rules amount to in one repository, rules and paths apart."""
    project = discipline.machine_traces.project_name(root)
    workflows = workflows_root(root)
    board = discipline.board.facts(root, project)
    # The workflows belong to the repository that runs this one, and the board
    # rule's fifth clause reads them. Read from the subtree, they would report a
    # floor nobody runs and a control nobody executes.
    board["run_in_ci"] = discipline.ci.runs_pytest(workflows)
    return {
        "project": project,
        "workflows": workflows,
        "floor": discipline.ci.floor(root),
        "interpreters": sorted(set(discipline.ci.interpreters(workflows))),
        "matrix": sorted(set(discipline.ci.matrix_interpreters(workflows))),
        "suspect": discipline.ci.suspect(workflows),
        "board": board,
        "as_ci": discipline.machine_traces.problems(root, user=AS_CI,
                                                    checkout=project),
        "board_problems": board_problems(root, project, workflows, discipline),
        "documents": discipline.documents.check(root),
    }


def compare(read: list[tuple[str, Path]]) -> list[str]:
    """Every way the checkouts this run was handed disagree about the rules.

    `read` is the corpus first - the checkout that owns the rules - and then
    whichever layers this run holds. A copy is compared with the source for every
    layer but the first, which is the source.
    """
    owner = read[0][1]
    discipline = load(shared(owner))
    vendor = loader_for(HERE / "vendor-discipline.py")

    failures: list[str] = []
    sheets: dict[Path, dict] = {}
    for name, root in read:
        if not root.is_dir():
            failures.append(f"{root}: not a checkout, and this run was handed it")
            continue
        sheets[root] = facts(root, discipline)

        if name != read[0][0]:
            for problem in vendor.drifted(root):
                failures.append(f"{root}: {problem}")
        for problem in (sheets[root]["as_ci"] + sheets[root]["board_problems"]
                        + sheets[root]["documents"]):
            failures.append(f"{root}: {problem}")

    if not sheets:
        return failures

    floors = {root: sheet["floor"] for root, sheet in sheets.items()}
    if len(set(floors.values())) != 1:
        failures.append(f"the checkouts read here declare different floors: "
                        f"{ {str(root): floor for root, floor in floors.items()} }")
    for field in ("interpreters", "matrix"):
        values = {root: sheet[field] for root, sheet in sheets.items()}
        if len({tuple(value) for value in values.values()}) != 1:
            failures.append(f"the checkouts read here do not run the same {field}: "
                            f"{ {str(root): value for root, value in values.items()} }")
    for root, sheet in sheets.items():
        if sheet["suspect"]:
            failures.append(f"{root}: a python-version in the workflows is not "
                            f"one this reader can read: {sheet['suspect']}")
        if sheet["floor"] not in sheet["matrix"]:
            failures.append(f"{root}: the floor {sheet['floor']} is not a matrix "
                            f"leg {sheet['matrix']}: a claim nobody runs")
    return failures


def sheet(name: str, root: Path, discipline) -> str:
    found = facts(root, discipline)
    board = found["board"]
    lines = [
        f"{name}: {root}",
        f"  project {found['project']}, floor {found['floor']}, "
        f"interpreters {found['interpreters']}, matrix {found['matrix']}",
    ]
    if found["workflows"] != root:
        lines.append(f"  run by the workflows of {found['workflows']}, which "
                     f"holds it")
    lines += [
        f"  board {board['board']} by `{board['command']}`, held by "
        f"{board['current_test']}",
        f"  the machine-trace rule under the CI account: "
        f"{'clean' if not found['as_ci'] else str(len(found['as_ci'])) + ' traces'}",
        f"  the documents that point a reader at the server: "
        f"{'clean' if not found['documents'] else str(len(found['documents'])) + ' problem(s)'}",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/discipline-drift.py")
    parser.add_argument("--corpus", required=True, metavar="REPO",
                        help="the checkout that owns the shared rules")
    parser.add_argument("--library", metavar="REPO",
                        help="the library, when this run holds a checkout of it")
    parser.add_argument("--mcp", metavar="REPO",
                        help="the server, when this run holds a checkout of it")
    arguments = parser.parse_args(argv)

    handed = [("corpus", arguments.corpus), ("library", arguments.library),
              ("mcp", arguments.mcp)]
    read = [(name, Path(value).resolve()) for name, value in handed if value]
    if not shared(read[0][1]).is_dir():
        print(f"{read[0][1]} is not the corpus: {shared(read[0][1])} does not "
              f"exist", file=sys.stderr)
        return 2

    discipline = load(shared(read[0][1]))
    names = [name for name, _ in read]
    print(f"the shared discipline, as each checkout this run was handed holds it "
          f"({', '.join(names)}):\n")
    for name, root in read:
        if root.is_dir():
            print(sheet(name, root, discipline))
    for name, reason in LAYERS.items():
        if name not in names:
            print(f"\nnot read here: {name} - {reason}")

    failures = compare(read)
    if failures:
        print(f"\nthe checkouts read here ({', '.join(names)}) are not holding "
              f"one discipline:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("\none discipline: the copies match, the rule is clean under the CI "
          "account, the floor is one number every workflow read here runs, and "
          "each checkout prints a board it can prove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
