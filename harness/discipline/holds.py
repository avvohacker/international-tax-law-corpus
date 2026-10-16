"""What a run of the shared control holds, and what it leaves to another run.

`scripts/discipline-drift.py` is the control: it compares the copies of these rules
with the source they came from and runs them, for every checkout it is handed.
Which checkouts those are is not a detail of a command line - it is whose red a run
reports. A repository can repair a copy it holds; it cannot repair one that lives in
another repository, where the repair is a commit there. So the job that runs the
control holds the checkouts its own repository holds, and a layer it does not hold
is left to that layer's own run of the same control.

That was learned from a red nobody could act on. The corpus' `discipline` job
checked the library out beside it and reported whatever pin that checkout happened
to carry, so no commit in the corpus could turn the job green: the one repair for
that red is a push into another repository, which a reader of the run cannot make.
Measured from the other side, the answer was already there - the library runs this
same control in its own workflow, over this corpus and itself, and its repair is a
re-vendor from here.

The rule, in three clauses, each refused on its own:

  * the job runs the control and hands it `--corpus` - the checkout that owns the
    rules, and the one checkout a run may read without holding;
  * every other checkout it hands in is one the run holds: under the repository's
    own root, or inside the `--corpus` checkout. A path beside the root is a
    sibling, and what is in a sibling is that repository's to write;
  * the job checks out nothing but the `--corpus` source. A `repository:` key is a
    checkout of somebody else's code, and one the control is not handed is a
    checkout no reader of the run has.

A layer a run is not handed is not passed over in silence: `NOT_READ` is what the
run says about that layer, and the reasons are stated here rather than in each run,
because those layers are the same three for every run of this control.
"""
from __future__ import annotations

import shlex
from pathlib import Path

from . import ci

# What runs, what the job that runs it is called in every repository of the family,
# and the switch each layer travels under.
CONTROL = "scripts/discipline-drift.py"
JOB = "discipline"
LAYERS = ("corpus", "library", "mcp")
SWITCH = {layer: f"--{layer}" for layer in LAYERS}

# The two layers a run may be without, and what it says about each: where that half
# is read, and what its repair is. The corpus is not one of them - it is the one
# checkout a run must be handed, and a run without it has nothing to compare.
NOT_READ = {
    "library": "it is a checkout of its own, and this half is read by this same "
               "script in the library's own run, over the corpus - the run whose "
               "repair is a re-vendor",
    "mcp": "the server is committed inside the corpus, under `mcp/`, and the "
           "corpus' own job hands it in",
}


def switches(command: str) -> dict[str, str]:
    """The layer each switch of one command names, and the value beside it.

    Both spellings a workflow writes are read - `--layer value` and
    `--layer=value` - because a reader that knew only one of them would report a
    checkout as absent while it stands there in the command.
    """
    found: dict[str, str] = {}
    tokens = shlex.split(command)
    for position, token in enumerate(tokens):
        for layer, switch in SWITCH.items():
            if token == switch and position + 1 < len(tokens):
                found[layer] = tokens[position + 1]
            elif token.startswith(f"{switch}="):
                found[layer] = token.split("=", 1)[1]
    return found


def runs(root: Path) -> list[dict]:
    """Every job that runs the control, as the facts the rule is read from.

    `hands_in` and `leaves` are the layers, `source` is the value of `--corpus`,
    and `checkouts` are the `actions/checkout` steps the job makes - each with the
    repository it names and the path it puts it at, either of which may be empty.
    The job's own checkout of the repository it stands in is not one of them: it
    names nobody else's code and lands at the root.
    """
    out: list[dict] = []
    for path, job, body in ci.jobs(root):
        steps = [step for step in (body.get("steps") or [])
                 if isinstance(step, dict)]
        handed: dict[str, str] = {}
        commands: list[str] = []
        for step in steps:
            for value in ci.values_for(step, "run"):
                if isinstance(value, str) and CONTROL in value:
                    handed.update(switches(value))
                    commands.append(value)
        if not handed and not commands:
            continue
        checkouts = []
        for step in steps:
            if not str(step.get("uses") or "").startswith("actions/checkout"):
                continue
            repository = next((str(v) for v in ci.values_for(step, "repository")),
                              "")
            at = next((str(v) for v in ci.values_for(step, "path")), "")
            if repository or at:
                checkouts.append({"repository": repository, "path": at})
        out.append({
            "file": path,
            "job": job,
            "commands": commands,
            "values": handed,
            "source": handed.get("corpus", ""),
            "hands_in": [layer for layer in LAYERS if layer in handed],
            "leaves": [layer for layer in LAYERS if layer not in handed],
            "checkouts": checkouts,
        })
    return out


def _within(path: Path, holder: Path) -> bool:
    """Whether a checkout is one this holder has: itself, or something under it."""
    return path == holder or holder in path.parents


def problems(root: Path) -> list[str]:
    """Every way a run of the control reads a copy its repository cannot write."""
    found = runs(root)
    if not found:
        return [f"no job runs {CONTROL}: nothing holds the copies of the shared "
                f"rules against their source"]
    out: list[str] = []
    for run in found:
        where = f"{run['file'].name} `{run['job']}`"
        if not run["source"]:
            out.append(f"{where}: runs the control without `--corpus`, so the run "
                       f"has no source to compare the copies with")
            continue
        source = (root / run["source"]).resolve()
        for layer, value in run["values"].items():
            if layer == "corpus":
                continue
            held = (root / value).resolve()
            if _within(held, root.resolve()) or _within(held, source):
                continue
            out.append(f"{where}: hands the control `{SWITCH[layer]} {value}`, and "
                       f"that checkout is neither under this repository nor inside "
                       f"the `--corpus` checkout: the copy in it is not this "
                       f"repository's to write")
        for step in run["checkouts"]:
            if step["path"] and Path(step["path"]) == Path(run["source"]):
                continue
            named = step["repository"] or "a repository"
            at = f" into `{step['path']}`" if step["path"] else ""
            out.append(f"{where}: checks out {named}{at}, which the control is not "
                       f"handed: a checkout nothing reads is a checkout nobody "
                       f"repairs")
    return out
