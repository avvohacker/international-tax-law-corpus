"""Hold the three repositories to one discipline, as CI sees them.

    python scripts/discipline-drift.py --corpus . --library ../library --mcp ../mcp

Three repositories, one set of rules, and until this control existed nothing
compared them: the copy of the machine-trace rule had drifted into three
wordings with three exemption lists, the workflow readers had drifted into two
different APIs, and the status board rule was a paragraph of prose each. The
drift was found by reading the three side by side by hand, which is not a
control. This is.

Five things are compared, and each of them can fail on its own:

  * **the copies**: `harness/discipline/` in the corpus against
    `vendor/discipline/` in the other two, byte for byte, and each copy against
    the pin it declares in `provenance/vendored-discipline.yaml`. Equal bytes are
    not enough by themselves - a family can agree on the wrong rule - but a copy
    that names its own rule is not a family at all;
  * **the rule, run**: the machine-trace scan is then run for each repository
    under the identity CI gives it - the account `runner`, the checkout named
    after the project - and must come back empty. This is the half that equal
    bytes cannot show: the rule walks through prose, and the prose differs. The
    first version of the rule failed here for all three repositories, on lines
    that name nobody, because CI's account name is an ordinary English word and
    all three say it in their own workflow comments;
  * **the floor**: every repository must declare the same `requires-python` and
    run it, as a matrix leg that runs the control, or "the family's floor" means
    three different things;
  * **the board**: one generated document per repository, naming the project
    rather than the checkout, held by a test that names both the document and the
    command that writes it, in a run that executes the tests;
  * **the reader**: the same workflow reader reads all three, so the floors above
    were compared by one implementation rather than by three that agree today.

A desk can run this before pushing; CI runs it in every repository of the three,
because the drift it refuses is invisible from inside any one of them.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The account CI runs as, and the reason the machine-trace rule was rewritten:
# the name is an ordinary English word that all three repositories say in their
# own prose. The run is done under it rather than under the desk's account, so
# that a repository whose text collides with its CI account is red here, before
# a runner ever sees it.
AS_CI = "runner"


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


def facts(root: Path, discipline) -> dict:
    """What the rules amount to in one repository, rules and paths apart."""
    project = discipline.machine_traces.project_name(root)
    board = discipline.board.facts(root, project)
    return {
        "project": project,
        "floor": discipline.ci.floor(root),
        "interpreters": sorted(set(discipline.ci.interpreters(root))),
        "matrix": sorted(set(discipline.ci.matrix_interpreters(root))),
        "suspect": discipline.ci.suspect(root),
        "board": board,
        "as_ci": discipline.machine_traces.problems(root, user=AS_CI,
                                                    checkout=project),
        "as_desk": discipline.machine_traces.problems(root),
        "board_problems": discipline.board.problems(root, project),
    }


def compare(corpus: Path, library: Path, mcp: Path) -> list[str]:
    """Every way the three repositories disagree about the shared discipline."""
    source = shared(corpus)
    discipline = load(source)
    vendor = loader_for(HERE / "vendor-discipline.py")

    failures: list[str] = []
    sheets: dict[Path, dict] = {}
    for root in (corpus, library, mcp):
        if not root.is_dir():
            failures.append(f"{root}: not a checkout, and the control reads three")
            continue
        sheets[root] = facts(root, discipline)

        if root != corpus:
            for problem in vendor.drifted(root):
                failures.append(f"{root}: {problem}")
        problems = sheets[root]["as_ci"] + sheets[root]["board_problems"]
        if sheets[root]["as_desk"]:
            problems += [f"(the desk's own account) {hit}"
                         for hit in sheets[root]["as_desk"]]
        for problem in problems:
            failures.append(f"{root}: {problem}")

    if len(sheets) != 3:
        return failures

    floors = {root: sheet["floor"] for root, sheet in sheets.items()}
    if len(set(floors.values())) != 1:
        failures.append(f"the three repositories declare different floors: "
                        f"{ {str(root): floor for root, floor in floors.items()} }")
    for field in ("interpreters", "matrix"):
        values = {root: sheet[field] for root, sheet in sheets.items()}
        if len({tuple(value) for value in values.values()}) != 1:
            failures.append(f"the three workflows do not run the same {field}: "
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
    return "\n".join((
        f"{name}: {root}",
        f"  project {found['project']}, floor {found['floor']}, "
        f"interpreters {found['interpreters']}, matrix {found['matrix']}",
        f"  board {board['board']} by `{board['command']}`, held by "
        f"{board['current_test']}",
        f"  the machine-trace rule under the CI account: "
        f"{'clean' if not found['as_ci'] else str(len(found['as_ci'])) + ' traces'}",
    ))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/discipline-drift.py")
    parser.add_argument("--corpus", required=True, metavar="REPO")
    parser.add_argument("--library", required=True, metavar="REPO")
    parser.add_argument("--mcp", required=True, metavar="REPO")
    arguments = parser.parse_args(argv)

    roots = [Path(name).resolve() for name in
             (arguments.corpus, arguments.library, arguments.mcp)]
    names = ["corpus", "library", "mcp"]
    if not shared(roots[0]).is_dir():
        print(f"{roots[0]} is not the corpus: {shared(roots[0])} does not exist",
              file=sys.stderr)
        return 2

    discipline = load(shared(roots[0]))
    print("the shared discipline, as each repository holds it:\n")
    for name, root in zip(names, roots):
        if root.is_dir():
            print(sheet(name, root, discipline))

    failures = compare(*roots)
    if failures:
        print("\nthe three are not holding one discipline:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("\none discipline: the copies match, the rule is clean under the CI "
          "account, the floor is one number the three workflows run, and each "
          "repository prints a board it can prove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
