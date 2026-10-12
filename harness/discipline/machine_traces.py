"""Nothing this family commits may describe the machine it was built on.

The corpus states this as invariant F14, and states why: a committed
`derived/index.json` once carried an absolute path into the builder's home
directory. The class is wider than the artefacts a pipeline writes, so the rule
is applied to every file a repository tracks, in all three repositories of the
family, whoever wrote them:

  * an absolute local path - a home directory, a macOS machine root, a Windows
    home, a `file://` URL that names a local path;
  * the name of the directory the checkout happens to live in, which is a fact
    about one desk and never about the project;
  * the account name of the machine that ran the checks.

This module is the one implementation of that rule. It used to be three: each
repository carried its own copy of the detector, the copies had drifted - three
wordings, three exemption lists, three answers to "is the checkout's own name a
trace?" - and nothing compared them. It is vendored verbatim from here into
`international-tax-law-library` and `international-tax-law-mcp` by
`scripts/vendor-discipline.py`, and pinned there by hash
(`provenance/vendored-discipline.yaml`), so a copy that goes back to inventing
its own rule is a red test rather than a surprise, and
`scripts/discipline-drift.py` runs this scan for each of the three as CI sees
them.

Two things a rule about machines cannot decide by itself, declared here rather
than discovered at the moment it matters:

  * The third rule is about a *person's* account name, and CI runs as an account
    whose name is an ordinary English word. All three repositories say that word
    in their own prose - a workflow comment reads "the runner reads what the
    corpus was built from" - so the rule as first written failed on every
    compatibility job the day it was added, on a line that names nobody. A CI
    account names no person, so the accounts CI uses are declared exempt in
    `CI_ACCOUNTS`. The exemption is only ever the *name* and never the path: the
    first rule still catches a home directory under that account on its own, and
    `test_a_ci_accounts_home_path_is_still_a_trace` proves it. Widening the list
    changes these bytes, and these bytes are pinned in two repositories, so an
    exemption added to silence a failure is a commit somebody has to read.
  * A path written with a placeholder - `<user>`, the way the defect catalogue
    writes one - is not a path to a machine, and is left alone.

The patterns are assembled from fragments, exactly as `harness/checks.py` builds
its own: this file is one of the files that gets scanned, and a check that
contains the token it looks for would fail itself. That is not caution in the
abstract: the first version of this file wrote its own positive control with a
whole machine root inside it, and failed its own scan on the compatibility jobs
before it ever looked at anybody else's work.
"""
from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

_HOME_ROOTS = ("/" + "Users" + "/", "/" + "home" + "/")
_MACHINE_ROOTS = ("/" + "private" + "/var/",
                  "/" + "Volumes" + "/",
                  "/" + "var" + "/folders" + "/")
_WINDOWS_HOME = "C:" + "\\" + "Users" + "\\"
_FILE_URL = "file:" + "///"

# The accounts CI runs as, whose names are ordinary English words. A name here
# is never looked for on its own; a path carrying it is still a trace.
CI_ACCOUNTS = frozenset({"runner", "github-actions"})

# What a home path looks like: the root, then a concrete account name. A
# placeholder is left alone, which is the behaviour wanted here: a document may
# say where a local path *would* be.
TRACES = (
    ("an absolute home path",
     re.compile("(?:" + "|".join(_HOME_ROOTS) + ")[A-Za-z0-9._-]+")),
    ("a machine-local root",
     re.compile("|".join(re.escape(root) for root in _MACHINE_ROOTS))),
    ("a Windows home path", re.compile(re.escape(_WINDOWS_HOME))),
    ("a file:// URL naming a local path", re.compile(re.escape(_FILE_URL))),
)

# The lines on which naming an owner is the point: the rights declaration, and
# the GitHub owner a workflow asks to check out. Everything else that carries a
# GitHub owner is a URL, and is recognised as one.
OWNER_LINE = re.compile(r"Copyright \(c\) \d{4}|^\s*repository:")
OWNER_URL = re.compile(r"https?://(?:raw\.)?github\.com/$")


def scratch(relative: Path) -> bool:
    """Whether a path inside a working copy is scratch rather than published.

    Every entry here is ignored on purpose by all three repositories, so the
    tracked scan never meets one; the working-tree scan does, and a build
    directory that records the absolute path a checkout was installed from
    would otherwise be read as a defect of the committed files.
    """
    scratch_names = {".git", "sources", "__pycache__", ".pytest_cache", ".venv",
                     "venv", "build", "dist", ".verify"}
    return any(part in scratch_names or part.endswith(".egg-info")
               for part in relative.parts)


def tracked(root: Path) -> list[Path]:
    """The files git tracks at ``root``, or the working tree when there is none.

    A copy of a checkout - the way an umbrella folder keeps one - has no
    `.git`, so nothing can say what is committed. The whole tree is read
    instead, minus the scratch and the fetched bytes: the check is then broader
    than the committed surface, never narrower.
    """
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.SubprocessError):
        return [path for path in sorted(root.rglob("*"))
                if path.is_file() and not scratch(path.relative_to(root))]
    return [root / name for name in listed.stdout.split("\0") if name]


def project_name(root: Path) -> str | None:
    """The name `pyproject.toml` gives the project, or None if it cannot be read.

    A checkout named after its project - which is what CI does - must not be
    reported as a trace of the machine: the name in the manifest is the one that
    travels, and the folder has to be allowed to match it.
    """
    try:
        manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(manifest["project"]["name"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return None


def where(text: str, index: int) -> str:
    return f"line {text.count(chr(10), 0, index) + 1}"


def declares_the_owner(text: str, match: re.Match) -> bool:
    """Whether this occurrence of a name is meant to be there."""
    start, end = match.span()
    if text[end:end + 1] == "@" or text[start - 1:start] == "@":
        return True                                  # an email address
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start:line_end if line_end != -1 else len(text)]
    if OWNER_LINE.search(line):
        return True                                  # a rights or owner line
    return bool(OWNER_URL.search(text[line_start:start]))   # a GitHub owner path


def traces_in(text: str, *, checkout: str | None, user: str | None,
              project: str | None = None) -> list[str]:
    """Every machine trace in one file's text, as readable descriptions.

    ``checkout`` is the directory a repository was cloned into, ``user`` the
    account that ran the check, and ``project`` the name the manifest gives -
    which is the one folder name that is not a trace, because it is a fact about
    the project rather than about the machine.

    ``user`` in `CI_ACCOUNTS` is exempt from the name rule, and only from it:
    see the module docstring for why, and
    `test_a_ci_accounts_home_path_is_still_a_trace` for what still catches it.
    """
    hits: list[str] = []
    for label, pattern in TRACES:
        found = pattern.search(text)
        if found:
            hits.append(f"{label} ({found.group(0)!r}) at {where(text, found.start())}")
    if checkout and checkout != project:
        for match in re.finditer(r"\b" + re.escape(checkout) + r"\b", text):
            hits.append(f"the directory this checkout lives in ({checkout}) "
                        f"at {where(text, match.start())}")
    if user and user not in CI_ACCOUNTS:
        for match in re.finditer(r"\b" + re.escape(user) + r"\b", text):
            if declares_the_owner(text, match):
                continue
            hits.append(f"the account name on this machine ({user}) "
                        f"at {where(text, match.start())}")
    return hits


def problems(root: Path, *, user: str | None = None,
             checkout: str | None = None) -> list[str]:
    """Every machine trace in every file this repository commits, named.

    ``user`` and ``checkout`` default to this machine's account and this
    directory's name. A caller that names them is asking what a *different*
    machine would see - which is how the three repositories are held to one rule
    on a desk: `scripts/discipline-drift.py` runs this scan for each of them
    under the identity CI gives it, and a repository whose own prose collides
    with its CI account is caught there rather than on the runner.
    """
    here = root.name if checkout is None else checkout
    account = Path.home().name if user is None else user
    project = project_name(root)
    found: list[str] = []
    for path in tracked(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for hit in traces_in(text, checkout=here, user=account, project=project):
            found.append(f"{path.relative_to(root)}: {hit}")
    return found
