"""Nothing this repository commits may describe the machine it was built on.

Invariant F14, and the defect class behind it (`d22`): the committed
`derived/index.json` once carried an absolute path into the builder's home
directory, twice. `test_invariants.py` checks the artefacts the pipeline writes,
from a list of globs; the class is wider than that list, so this file checks
every file git tracks, whichever directory it is in:

  * an absolute local path - a home directory, a macOS machine root, a Windows
    home, a `file://` URL that names a local path;
  * the name of the directory this checkout happens to live in, which is a fact
    about one desk and never about the project (the same reason
    `harness/report.py` prints the project's name and not the folder's);
  * the account name of the machine that ran the checks.

The third needs a rule with exceptions, and the exceptions are the places a
repository is *supposed* to name its owner and its contact: a copyright line, an
email address, a GitHub URL, and a workflow's `repository:`. Anywhere else the
account name is a trace of the machine; a home path that carries it is caught by
the first rule as well, which is what makes the two worth having separately: one
catches the path, the other catches the name on its own.

The patterns are assembled from fragments, exactly as `harness/checks.py` builds
its own: this file is one of the files that gets scanned, and a check that
contains the token it looks for would fail itself.
"""
from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HOME_ROOTS = ("/" + "Users" + "/", "/" + "home" + "/")
_MACHINE_ROOTS = ("/" + "private" + "/var/",
                  "/" + "Volumes" + "/",
                  "/" + "var" + "/folders" + "/")
_WINDOWS_HOME = "C:" + "\\" + "Users" + "\\"
_FILE_URL = "file:" + "///"

# What a home path looks like: the root, then a concrete account name. The
# catalogue in `fixtures/` has to be able to say where a local path was, and it
# writes it with a placeholder - so a pattern that required a real name would
# leave that line alone, which is the behaviour wanted here as well.
TRACES = (
    ("an absolute home path",
     re.compile("(?:" + "|".join(_HOME_ROOTS) + ")[A-Za-z0-9._-]+")),
    ("a machine-local root",
     re.compile("|".join(re.escape(root) for root in _MACHINE_ROOTS))),
    ("a Windows home path", re.compile(re.escape(_WINDOWS_HOME))),
    ("a file:// URL naming a local path", re.compile(re.escape(_FILE_URL))),
)

# The lines on which naming the owner is the point: the rights declaration, and
# the GitHub owner a workflow asks to check out. Everything else that carries a
# GitHub owner is a URL, and is recognised as one.
OWNER_LINE = re.compile(r"Copyright \(c\) \d{4}|^\s*repository:")
OWNER_URL = re.compile(r"https?://(?:raw\.)?github\.com/$")

def _scratch(relative: Path) -> bool:
    """Whether a path inside a working copy is scratch rather than published.

    Every entry here is ignored on purpose by this repository, so the tracked
    scan never meets one; the working-tree scan does, and a build directory that
    records the absolute path a checkout was installed from would otherwise be
    read as a defect of the committed files.
    """
    scratch = {".git", "sources", "__pycache__", ".pytest_cache", ".venv",
               "venv", "build", "dist", ".verify"}
    return any(part in scratch or part.endswith(".egg-info")
               for part in relative.parts)


def _tracked(root: Path) -> list[Path]:
    """The files git tracks here, or the working tree when there is no git.

    A copy of a checkout - the way the umbrella folder keeps one - has no
    `.git`, so nothing can say what is committed. The whole tree is read
    instead, minus the scratch and the fetched bytes: the check is then
    broader than the committed surface, never narrower.
    """
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.SubprocessError):
        return [path for path in sorted(root.rglob("*"))
                if path.is_file() and not _scratch(path.relative_to(root))]
    return [root / name for name in listed.stdout.split("\0") if name]


def _project_name(root: Path) -> str | None:
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


def _where(text: str, index: int) -> str:
    return f"line {text.count(chr(10), 0, index) + 1}"


def _declares_the_owner(text: str, match: re.Match) -> bool:
    """Whether this occurrence of the account name is meant to be here."""
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

    `checkout` is the directory this repository was cloned into, `user` the
    account that ran the check, and `project` the name the manifest gives -
    which is the one folder name that is not a trace, because it is a fact
    about the project rather than about the machine.
    """
    hits: list[str] = []
    for label, pattern in TRACES:
        found = pattern.search(text)
        if found:
            hits.append(f"{label} ({found.group(0)!r}) at {_where(text, found.start())}")
    if checkout and checkout != project:
        for match in re.finditer(r"\b" + re.escape(checkout) + r"\b", text):
            hits.append(f"the directory this checkout lives in ({checkout}) "
                        f"at {_where(text, match.start())}")
    if user:
        for match in re.finditer(r"\b" + re.escape(user) + r"\b", text):
            if _declares_the_owner(text, match):
                continue
            hits.append(f"the account name on this machine ({user}) "
                        f"at {_where(text, match.start())}")
    return hits


def test_no_committed_file_carries_a_machine_trace():
    checkout = ROOT.name
    user = Path.home().name
    project = _project_name(ROOT)
    problems: list[str] = []
    for path in _tracked(ROOT):
        text = path.read_text(encoding="utf-8", errors="replace")
        for hit in traces_in(text, checkout=checkout, user=user, project=project):
            problems.append(f"{path.relative_to(ROOT)}: {hit}")
    assert not problems, (
        "a committed file describes the machine it was built on:\n  "
        + "\n  ".join(problems[:12]))


def test_the_detector_catches_every_trace_it_claims_to():
    """The positive control: a detector that never fires proves nothing."""
    checkout = "a-clone-called-something-else"
    user = "somebody"
    samples = (
        ("an absolute home path", "/" + "Users" + "/somebody/corpus.xml"),
        ("a machine-local root", "/" + "private" + "/var/folders/x/y/corpus.json"),
        ("a Windows home path", "C:" + "\\" + "Users" + "\\" + "somebody" + "\\doc.akn.xml"),
        ("a file:// URL naming a local path", "file:" + "///tmp/corpus.json"),
        ("the directory this checkout lives in",
         "cloned into a-clone-called-something-else"),
        ("the account name on this machine", "built on somebody's laptop"),
    )
    for expectation, sample in samples:
        found = traces_in(sample, checkout=checkout, user=user,
                          project="international-tax-law-corpus")
        assert any(expectation in hit for hit in found), (
            f"the detector no longer catches {expectation}: {sample!r} -> {found}")


def test_the_detector_leaves_the_declarations_alone():
    """Naming the owner and the contact is the point of these lines."""
    text = ("Copyright (c) 2026 somebody <somebody@example.com> - project\n"
            "Contact somebody@example.com before any reuse beyond reading.\n"
            "repository: somebody/international-tax-law-corpus\n"
            "badge: https://github.com/somebody/international-tax-law-corpus\n")
    assert not traces_in(text, checkout="international-tax-law-corpus", user="somebody",
                         project="international-tax-law-corpus")


def test_a_checkout_named_after_the_project_is_not_a_trace():
    """CI clones into the project's own name, and that name is not a machine."""
    text = "the corpus repository international-tax-law-corpus"
    assert not traces_in(text, checkout="international-tax-law-corpus",
                         user=None, project="international-tax-law-corpus")
    assert traces_in(text, checkout="intl", user=None,
                     project="international-tax-law-corpus") == []


def test_the_placeholder_the_catalogue_uses_is_not_a_trace():
    """`fixtures/` has to be able to say where a local path was, without one."""
    evidence = '"' + "/" + "Users" + "/<user>/Desktop/…/corpus.xml" + '"'
    assert not traces_in(evidence, checkout="x", user=None)
