"""Detect non-English (Italian) text in the project's own artefacts.

Design notes, because a bad detector is worse than none:

* SCOPE. The invariant covers the *project's own* text - code, comments,
  docstrings, test names, printed messages, reports, docs. It does NOT cover the
  corpus: a country's MLI position is published in its own language and the data
  must stay faithful to it. `fixtures/` and `corpora/` are therefore exempt, and
  so is `vendor/` (third-party schema).

* PRECISION. English and Italian share short words ("per", "con", "come", "non",
  "una", "la"). Those are excluded on purpose: a detector that flags "per cent"
  would be turned off within a day. What is left is unambiguous Italian -
  function words that do not occur in English, Italian morphology (-zione,
  -mente, -ità, -ggio), and Italian-only accented endings.

* STYLE. Matching is case-insensitive on word boundaries. Words that are also
  English are listed in ALLOW so that the list stays auditable.

* SELF-EXEMPTION. This module necessarily contains the language it detects, so
  it is the one file excluded from its own scan. The exemption is not taken on
  trust: `tests/test_invariants.py::test_f13_detector_still_catches_italian`
  proves on an Italian sample that the detector still bites.
"""
from __future__ import annotations

import re
from pathlib import Path

# Unambiguous Italian function words and verb forms.
ITALIAN_WORDS = """
allora anche ancora avrebbe avrebbero bisogna cioè cosicché cosi' degli della
delle dell dello dentro dev' deve devono diversamente dunque dopo egli ella
entrambe entrambi essendo essi farebbe fra gli quindi invece infatti inoltre
loro mentre neanche negli nella nelle nessuno niente oppure ovvero perché
perche' percio' pochissimo poiché potrebbe dovrebbe prima purché qualcuno
quando quantunque quello questa queste questi quest' soltanto sono sopra
soprattutto sotto specialmente sulla sulle talvolta tramite tuttavia vanno
venga vengono venivano verrebbe volte
""".split()

# Suffixes that are Italian and not English. Deliberately narrow: "-ate"
# (separate, create) and "-iamo" style endings were removed because they match
# ordinary English words, and a detector with false positives gets disabled.
ITALIAN_SUFFIX_RE = re.compile(
    r"\b[a-z]{4,}(?:zione|zioni|mente|ità|aggio|aggi|eggi|istico|istica|istici"
    r"|istiche|erebbe|erebbero|arono|eranno|iranno|issimo|issima)\b",
    re.IGNORECASE)

# Italian accented endings, which English text does not use.
ITALIAN_ACCENT_RE = re.compile(r"\b[a-z]*[àèìòù][a-z]*\b", re.IGNORECASE)

# Words that look Italian but are legitimate here.
# Words present in ITALIAN_WORDS (or matched by the patterns above) that are
# legitimate here: Latin/English usage, or English words that merely look
# Italian. Keep this list short and justified - it is the detector's only
# escape hatch, and every entry is a small hole in the check.
ALLOW = {
    # Latin / English usage
    "prima", "fra", "secondo", "stato", "via", "sale", "meta", "sotto",
    # source-domain words that appear verbatim in multilingual documents
    "reserva", "reserve", "reserves", "notifica", "notification",
    # `Norvège` is the French name of Norway as the Cote d'Ivoire table prints
    # it, quoted verbatim in the reviewed row pins of `tests/test_invariants.py`:
    # the pin measures a counterparty exactly, and the source's own word is the
    # only value the row can hold.
    "norvège",
    # `à` is the French preposition the francophone positions print (`prévue à
    # l'article 6(4)`), quoted in `harness/mli.py` where the reader declares the
    # French sentence that announces a list. The accent rule above is written
    # for Italian endings and this word is not Italian: it is the page's own
    # word, in a quotation of a sentence the reader has to match.
    "à",
}

WORD_RE = re.compile(r"\b([A-Za-zÀ-ÿ']+)\b")

PROJECT_GLOBS = (
    "src/**/*.py", "harness/**/*.py", "tests/**/*.py", "tools/*",
    "docs/**/*.md", "rules/**/*.yaml", "provenance/**/*.yaml",
    "*.md", "*.toml", "*.yaml", "*.yml", "*.cfg", "*.txt",
    ".github/**/*.yml",
)

# Parts of the tree whose text is not this project's prose:
#   fixtures/  the catalogues, which carry regexes and source excerpts
#   corpora/   the corpus itself, multilingual by nature (invariant F13)
#   vendor/    third-party schema, quoted verbatim
#   sources/   the input documents
EXEMPT_PARTS = ("fixtures", "corpora", "vendor", "sources", ".venv", ".git")

# This file, which cannot avoid containing the language it detects.
SELF_EXEMPT = ("harness/language.py",)


def _is_exempt(path: Path, root: Path) -> bool:
    if any(part in EXEMPT_PARTS for part in path.parts):
        return True
    try:
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return False
    return rel in SELF_EXEMPT


def violations(root: Path) -> list[tuple[Path, int, str]]:
    """[(path, line number, word)] for every suspicious token found."""
    out: list[tuple[Path, int, str]] = []
    seen: set[Path] = set()
    for pattern in PROJECT_GLOBS:
        for path in sorted(Path(root).glob(pattern)):
            if path in seen or not path.is_file() or _is_exempt(path, root):
                continue
            seen.add(path)
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for word in WORD_RE.findall(line):
                    low = word.lower()
                    if low in ALLOW:
                        continue
                    if (low in ITALIAN_WORDS
                            or ITALIAN_SUFFIX_RE.fullmatch(word)
                            or ITALIAN_ACCENT_RE.fullmatch(word)):
                        out.append((path, lineno, word))
    return out
