"""What the CI actually runs, read from the workflows.

`pyproject.toml` declares the floor this code is written against
(`requires-python = ">=3.11"`), and SPEC.md is explicit that a claim nobody
executes is an opinion, so `.github/workflows/corpus-drift.yml` runs the whole
control again on the floor and on the newest release beside the 3.13 the corpus
is built and published with. Two readers need that list - the test that holds
the floor and the workflows together, and the status board that prints both -
so it is read here once, rather than twice with two chances to disagree.

This is the shared reader, vendored verbatim from here into
`international-tax-law-library` and into the server folder `mcp/` of the corpus
by `scripts/vendor-discipline.py`: each layer reads its own workflows with these
same functions, so the floor of one can be compared with the floor of another
without either writing its own YAML walker. The two copies that used to
exist beside this one had already drifted - one of them could read the
`repository:` keys a checkout names, the others could not - and nothing noticed,
which is the class `scripts/discipline-drift.py` now refuses.

Nothing here interprets YAML beyond what a value under a key is, and a
`python-version` that is not a quoted `X.Y` string is reported rather than
coerced: YAML reads the unquoted `3.10` as the number 3.1, and an interpreter
whose last digit vanished is worse than a missing one, because it compares equal
to nothing.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

VERSION = re.compile(r"\d+\.\d+")
NAME = re.compile(r"^\d+\.\d+$")
EXPRESSION = re.compile(r"\$\{\{")


def workflows(root: Path) -> list[Path]:
    """The workflow files of this repository, in name order."""
    return sorted((root / ".github" / "workflows").glob("*.y*ml"))


def order(name: str) -> tuple[int, ...]:
    """A version as numbers, so that 3.9 sorts below 3.10."""
    found = VERSION.search(name)
    if not found:
        return (0,)
    return tuple(int(part) for part in found.group(0).split("."))


def floor(root: Path) -> str:
    """The version `requires-python` names, as `X.Y`."""
    manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requires = str(manifest["project"]["requires-python"])
    found = VERSION.search(requires)
    if not found:
        raise ValueError(
            f"pyproject.toml declares requires-python = {requires!r}, which "
            f"names no version: a floor nobody can read is not a floor")
    return found.group(0)


def values_for(node, key: str) -> list:
    """Every raw value under one `key`, wherever the key sits."""
    if isinstance(node, dict):
        found: list = []
        for name, value in node.items():
            if name == key:
                found.extend(value if isinstance(value, list) else [value])
            else:
                found.extend(values_for(value, key))
        return found
    if isinstance(node, list):
        found = []
        for item in node:
            found.extend(values_for(item, key))
        return found
    return []


def _matrix_values(node) -> list:
    """Every raw value under a `strategy.matrix`'s `python-version`."""
    if isinstance(node, dict):
        found: list = []
        for key, value in node.items():
            if key == "matrix" and isinstance(value, dict):
                found.extend(values_for(value, "python-version"))
            else:
                found.extend(_matrix_values(value))
        return found
    if isinstance(node, list):
        found = []
        for item in node:
            found.extend(_matrix_values(item))
        return found
    return []


def _named(values: list) -> list[str]:
    """The values that name an interpreter, in order, de-duplicated.

    Only an `X.Y` string names one: `${{ matrix.python-version }}` names the
    matrix, whose legs are counted from the matrix itself, and an unquoted number
    or a channel name names something this reader cannot compare. Those are left
    to `suspect`, which reports them - dropping them here without a word would be
    the silent gap this module exists to close.
    """
    names: list[str] = []
    for value in values:
        if isinstance(value, str) and NAME.match(value) and value not in names:
            names.append(value)
    return names


def _documents(root: Path):
    for path in workflows(root):
        yield path, yaml.safe_load(path.read_text(encoding="utf-8"))


def jobs(root: Path) -> list[tuple[Path, str, dict]]:
    """Every job the workflows declare: the file, its name, and its body.

    A job is the unit a control is declared in: which repositories it checks out,
    what it installs and the command it runs are read off its own steps and nowhere
    else. The readers around this one answer for the whole checkout, which is right
    for a floor and wrong for a control - this corpus checks the library out in the
    jobs that answer from it, and the job that runs the drift control does not, so
    a reading that took the file for the job would report that checkout as the
    control's own evidence, and would go on reporting it after the control had been
    handed a different pair.
    """
    found: list[tuple[Path, str, dict]] = []
    for path, document in _documents(root):
        for name, body in ((document or {}).get("jobs") or {}).items():
            if isinstance(body, dict):
                found.append((path, str(name), body))
    return found


def steps(root: Path, job: str) -> list[tuple[Path, dict]]:
    """The steps of every job called ``job``, with the file that declares it."""
    found: list[tuple[Path, dict]] = []
    for path, name, body in jobs(root):
        if name != job:
            continue
        for step in body.get("steps") or []:
            if isinstance(step, dict):
                found.append((path, step))
    return found


def interpreters(root: Path) -> list[str]:
    """Every interpreter the workflows name, in file order, de-duplicated."""
    found: list[str] = []
    for _, document in _documents(root):
        for name in _named(values_for(document, "python-version")):
            if name not in found:
                found.append(name)
    return found


def matrix_interpreters(root: Path) -> list[str]:
    """The interpreters of the `strategy.matrix` legs only.

    The floor is meant to be verified by a matrix leg - a job that runs the whole
    control - and not by a scalar `python-version` in some step: a check that
    only looked for the string would stay green the day that job is deleted,
    which is the state this module exists to refuse.
    """
    found: list[str] = []
    for _, document in _documents(root):
        for name in _named(_matrix_values(document)):
            if name not in found:
                found.append(name)
    return found


def checked_out_repositories(root: Path) -> list[str]:
    """The other repositories a workflow asks to check out, in order.

    A `repository:` key is an `actions/checkout` of somebody else's repository:
    both the corpus and the library for the server, which holds neither, and this
    corpus for the library's own run of the drift control. Reading them out of the
    workflow is what stops a document from telling a reader which repositories are
    its evidence from a list somebody typed - the workflow is the place that
    knows, and it changes whenever the evidence does.
    """
    found: list[str] = []
    for _, document in _documents(root):
        for value in values_for(document, "repository"):
            if isinstance(value, str) and value not in found:
                found.append(value)
    return found


def runs_pytest(root: Path) -> bool:
    """Whether any workflow step runs the repository's tests.

    The rule a generated document rests on - "a test holds the committed file
    against the command's own output" - is worth nothing if no run executes that
    test, which is a state a green badge cannot show. This is the reader for
    that question, shared by the three status boards' rules.
    """
    for _, document in _documents(root):
        for value in values_for(document, "run"):
            if isinstance(value, str) and "pytest" in value:
                return True
    return False


def suspect(root: Path) -> list[str]:
    """The `python-version` values that are neither a version nor a reference.

    YAML reads the unquoted `3.10` as the number 3.1: a name that lost its last
    digit is not a version anybody wrote, and it compares equal to nothing. A
    name this reader cannot read at all (`nightly`, an unquoted suffix) is
    reported here too, rather than dropped from the list the floor is checked
    against - a version nobody can name is a check nobody has.
    """
    out: list[str] = []
    for _, document in _documents(root):
        for value in values_for(document, "python-version"):
            if isinstance(value, str) and (NAME.match(value)
                                           or EXPRESSION.search(value)):
                continue
            rendered = value if isinstance(value, str) else repr(value)
            if rendered not in out:
                out.append(rendered)
    return out
