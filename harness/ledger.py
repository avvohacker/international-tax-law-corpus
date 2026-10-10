"""The span ledger: read the page as positioned spans, decide each one by rule.

Why a ledger instead of heuristics
----------------------------------
The previous pipeline decided what to keep by looking at the text (font size,
line shape, regexes) and then checked the result with form gates. An apparatus
line that happened to look like body text entered the corpus and nobody saw it:
the corpus contained "be deductible Articles 24 and 25 under the same
conditions", where "Articles 24 and 25" is the running header at the top of the
page (page 57 of the 2017 PDF, y = 26, size 10, while the body is 11pt).

In this model the corpus is a *projection* of the source span stream::

    spans  = SpanStream.read(pdf, source)          # every span, nothing dropped
    ledger = Classifier.classify(spans, Ledger())  # each span kept/dropped, by rule
    corpus = Projection.build(ledger.kept, source) # structural nodes over kept spans
    ok, why = verify_roundtrip(corpus, ledger, source)

Two properties follow by construction rather than by inspection:

* no insertion - only kept spans reach the corpus, so a running header can never
  appear inside a sentence unless a rule explicitly keeps it;
* no deletion - every span is either kept or in `dropped` with a rule id and a
  reason, so a lost paragraph is a visible ledger entry.

And one property is checked by round-trip: rebuilding the span sequence from the
projection reproduces the classified stream exactly.

The page geometry is *measured*, not assumed. `R-BAND-DEFINE` in
`rules/00-global.yaml` says where the bands come from; `measure()` implements it:
a header band and a footer band are the vertical positions at which short lines
appear on most pages, and the note band is the tail of a page whose lines are set
smaller than the body. For the 2017 Model that yields header y<40 (807 of 828
pages), footer y>590 (809 pages), body 11pt, notes 10pt.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"

# Markers the UN Model prints inline: thin space, digits, thin space.
MARKER_RE = re.compile("[\u2009\u2004]?\\d{1,3}[\u2009\u2004]")
_SOFT = "\xad"

# What a paragraph marker can look like, in one place: "1.", "4.1", "(a)",
# "(ii)", "(A)". The shape names the marker; how deep it sits is read from the
# column it is printed in (see `marker_columns`).
MARKER_TOKEN = (r"(?:(?:\d{1,2}\.\d{1,2})|(?:\d{1,2}\.)|"
                r"(?:\([a-z]{1,4}\))|(?:\([A-Z]\)))")

# The tolerance two marker positions share a column within; the real number is
# read from `rules/00-global.yaml` (R-MARKER-COLUMN) and this is only the
# fallback for a caller that passes no ledger. Measured: the marker columns of
# the 2017 Model stand at x = 59.7, 71.7, 92.4 and 112.5, and the closest pair
# is 11.5pt apart.
MARKER_COLUMN_TOL = 6.0

BANDS = ("header", "footer", "note", "body")
DECISIONS = ("keep", "drop", "structural", "transform")
KINDS = ("span", "policy", "declaration")
REGIONS = ("front_matter", "body", "commentary")

# What kind of page this document has, declared by the source and not guessed
# from it (rules/00-global.yaml R-SOURCE-SHAPE, rules/20-mli.yaml for the ones
# that are not prose):
#
#   prose  a page whose top is a running header and whose foot is a page number
#   table  a page that is rows of one table all the way down
#   mixed  a prose document whose pages carry tables that reach the top
#
# The bands and the rules that read them are statements about a *prose* page.
# Reading them on a table is not a near miss, it is a wrong answer: measured on
# the OECD signatories table, 8 short lines repeat at y = 502 on 4 of the 6
# pages - they are table rows that happen to align - and a footer band taken
# from them starts at y = 500, halfway up a table whose rows run to y = 760.
SHAPES = ("prose", "table", "mixed")

# How many pages a short line must repeat at the same height on before its
# height is a band. Declared by R-BAND-DEFINE per source: a page number repeats
# on every page, a table row's height repeats by accident on a third of them.
DEFAULT_BAND_PAGE_SHARE = 0.30
BAND_PARAMS = ("page_share",)


class RuleError(Exception):
    """A rule that cannot be evaluated. Raised instead of silently ignored."""


# --------------------------------------------------------------------------- #
# source units
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Span:
    """One run of text as it exists in the PDF, before any interpretation."""
    source: str
    page: int          # 0-based page index
    y: float           # top edge, points
    x: float           # left edge, points
    size: float        # font size, points
    text: str
    x1: float = 0.0    # right edge, points
    line: int = 0      # index of the line within the page
    flags: int = 0     # PyMuPDF span flags (superscript, italic, ...)

    @property
    def raw(self) -> str:
        return self.text


@dataclass(frozen=True)
class Line:
    """The spans that share one printed line. The unit rules are matched on."""
    source: str
    page: int
    index: int
    y: float
    x0: float
    x1: float
    size: float
    text: str            # raw, spans joined exactly as printed
    spans: tuple

    @property
    def match_text(self) -> str:
        return normalise(self.text)

    @property
    def ends_hyphenated(self) -> bool:
        stripped = self.text.rstrip()
        return stripped.endswith(("-", _SOFT))


def normalise(text: str) -> str:
    """Whitespace-collapsed form used for matching, never for the corpus."""
    flat = (text.replace("\t", " ").replace("\u2009", " ").replace("\u2004", " ")
            .replace("\xa0", " ").replace(_SOFT, "-"))
    return re.sub(r"\s+", " ", flat).strip()


# --------------------------------------------------------------------------- #
# printed lines
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LinePolicy:
    """How a printed line is rebuilt from the positioned spans of a page.

    A PDF has no lines, only spans, and PyMuPDF's grouping is not the printer's:
    it splits a tab-indented marker into a line of its own. Paragraph 1 of
    article 1 arrives as "1.\t" at x = 59 and the sentence at x = 90, so a rule
    matching `^(\d{1,2}\.) ` saw neither, and the Convention's paragraphs were
    body text with a marker stuck to the front of the sentence.

    The three numbers are declared by `R-LINE-BUILD` and measured from the
    document: inside a printed line consecutive spans sit 0.0pt apart, a tab
    column starts 11-21pt to the right, and printed lines are 13pt apart
    vertically. A source whose text is laid out in table cells declares a
    smaller gap, because for a table two cells of one row must stay two spans.

    `space_gap_pt` is the third measurement, and it is a different question: not
    "which spans are one line" but "which spans a line must be read with a space
    between them". PyMuPDF hands back one span per font run, and the runs of a
    printed line are contiguous - measured on the 2017 Convention, the gaps
    inside a run are 0.0-1.7pt (383 pairs wider than 0.5pt, the widest 1.7pt,
    where an italic letter leans into the roman bracket beside it) while a marker
    in a tab column stands 2.4pt or more away. Concatenating runs regardless
    welds a marker to the words it numbers: the ledger read article 29's
    "(2) with respect to an item of income" as "(2)with respect to an item of
    income", a word the source contains nowhere.
    """
    max_gap_pt: float = 25.0
    y_tol_pt: float = 2.5
    space_gap_pt: float = 2.0

    @classmethod
    def from_params(cls, rule_id: str, params) -> "LinePolicy":
        data = dict(params or {})
        unknown = sorted(set(data) - {"max_gap_pt", "y_tol_pt", "space_gap_pt"})
        if unknown:
            raise RuleError(f"{rule_id}: unknown line parameter {unknown[0]!r}")
        return cls(max_gap_pt=float(data.get("max_gap_pt", cls.max_gap_pt)),
                   y_tol_pt=float(data.get("y_tol_pt", cls.y_tol_pt)),
                   space_gap_pt=float(data.get("space_gap_pt", cls.space_gap_pt)))

    def describe(self) -> str:
        return (f"line: spans within {self.y_tol_pt:g}pt vertically and "
                f"{self.max_gap_pt:g}pt apart horizontally, a space printed "
                f"where the gap is {self.space_gap_pt:g}pt or more")


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Rule:
    id: str
    decision: str
    applies_to: tuple = ("*",)
    when: dict = field(default_factory=dict)
    rationale: str = ""
    kind: str = "span"
    node: str = ""
    transform: str = ""
    region_starts: str = ""
    prevents: tuple = ()
    akn: str = ""
    name_pattern: str = ""
    catch_all: bool = False
    params: dict = field(default_factory=dict)
    node_by_level: dict = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return re.sub(r"\s+", " ", self.rationale).strip()

    def applies(self, source: str) -> bool:
        return any(source == pat or fnmatch_case(pat, source) for pat in self.applies_to)


def fnmatch_case(pattern: str, value: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return pattern == value


def load_rules(source: str, directory: Path | None = None) -> list:
    """Every `kind: span` rule that applies to this source, in file order."""
    out = [rule for rule in _load(source, directory).values()
           if rule.kind == "span"]
    catch_alls = [r.id for r in out if r.catch_all]
    if len(catch_alls) > 1:
        raise RuleError(f"{source}: more than one catch-all rule: {catch_alls}")
    return out


def load_declarations(source: str, directory: Path | None = None) -> dict:
    """The `kind: declaration` rules of a source, by id.

    A declaration is a standing decision about the pipeline - how lines are
    rebuilt, where the page bands come from - rather than a decision about one
    line. It is read here and never guessed at in code.
    """
    return {rule.id: rule for rule in _load(source, directory)
            if rule.kind == "declaration"}


def line_policy(source: str, directory: Path | None = None) -> "LinePolicy":
    """The line-reconstruction policy of a source, from declared parameters.

    A global `R-LINE-BUILD` covers every source; a source may declare a more
    specific one (the signatories table does, so that table cells stay apart).
    The most specific declaration wins, and having none is an error: line
    grouping decides what every rule matches on, so it cannot be a default
    nobody wrote down.
    """
    declared = [(rule, rule.applies_to) for rule in _load(source, directory).values()
                if rule.id.startswith("R-LINE-BUILD")]
    if not declared:
        raise RuleError(
            f"{source}: no R-LINE-BUILD declaration. Line grouping is what every "
            f"rule is matched on, so it is declared, not assumed")
    specific = [rule for rule, applies in declared if "*" not in applies]
    chosen = (specific or [rule for rule, _applies in declared])[-1]
    return LinePolicy.from_params(chosen.id, chosen.params)


def source_shape(source: str, directory: Path | None = None) -> str:
    """What kind of page this source has, from a declared `R-SOURCE-SHAPE`.

    Same reasoning as `line_policy` and `marker_column_policy`: the answer is a
    property of the document, so it is declared where it can be read and argued
    with, and having no declaration is an error rather than a default. The
    global `R-SOURCE-SHAPE` says `prose` for every source - which is right for
    every source this repository read first - and a source that is not prose
    declares its own.
    """
    declared = [rule for rule in _load(source, directory).values()
                if rule.id.startswith("R-SOURCE-SHAPE")]
    if not declared:
        raise RuleError(
            f"{source}: no R-SOURCE-SHAPE declaration. The page bands, and every "
            f"rule that reads one, are statements about a prose page; a source "
            f"whose pages are something else has to say so")
    specific = [rule for rule in declared if "*" not in rule.applies_to]
    chosen = (specific or declared)[-1]
    unknown = sorted(set(chosen.params) - {"shape"})
    if unknown:
        raise RuleError(f"{chosen.id}: unknown source-shape parameter "
                        f"{unknown[0]!r}")
    shape = str(chosen.params.get("shape", "prose"))
    if shape not in SHAPES:
        raise RuleError(f"{chosen.id}: unknown shape {shape!r} "
                        f"(declared shapes: {', '.join(SHAPES)})")
    return shape


def band_policy(source: str, directory: Path | None = None) -> dict:
    """How this source's page bands are measured, from declared parameters.

    A band is a height at which short lines repeat page after page: that is
    where the running headers stand and that is where the page numbers stand.
    How many pages count as "page after page" is the one number the measurement
    needs, and it is declared rather than fixed, because the two kinds of page
    answer it differently:

      * on a prose page the page number is on every page, so even a permissive
        share finds it - and the share is permissive on purpose, so that a
        header that changes on a chapter's first page still sets the band;
      * on the OECD signatories table, short lines repeat at y = 502 on 4 of 6
        pages (share 0.67) purely because table rows align by accident, while
        the page number repeats on 6 of 6 (share 1.00). At the default share the
        footer band would begin at y = 500, halfway up a table that runs to
        y = 760, and every row below it would be apparatus.
    """
    declared = [rule for rule in _load(source, directory).values()
                if rule.id.startswith("R-BAND-DEFINE")]
    if not declared:
        raise RuleError(
            f"{source}: no R-BAND-DEFINE declaration. The bands are what the "
            f"apparatus rules are written against, so they are declared, not "
            f"assumed")
    specific = [rule for rule in declared if "*" not in rule.applies_to]
    chosen = (specific or declared)[-1]
    unknown = sorted(set(chosen.params) - set(BAND_PARAMS))
    if unknown:
        raise RuleError(f"{chosen.id}: unknown band parameter {unknown[0]!r}")
    share = float(chosen.params.get("page_share", DEFAULT_BAND_PAGE_SHARE))
    if not 0.0 < share <= 1.0:
        raise RuleError(f"{chosen.id}: page_share must be within (0, 1], got "
                        f"{share!r}")
    return {"page_share": share, "rule": chosen.id}


def _hyphen_mark(lines: list, transforms: list) -> str:
    """Which character this document prints where it breaks a word.

    Two editions of one instrument, two typographic habits, and one character
    whose meaning depends on the habit:

      * the 2017 Model breaks words with the soft hyphen (U+00AD): measured over
        the Convention, 199 of its 200 line-ending marks are soft, and the one
        plain hyphen is the word "day-to-day" broken at its own hyphen;
      * the 2021 Model breaks words with a plain "-": 205 of its 206 marks are
        plain, and the one soft mark is set *after* a hyphen ("Contract-\xad"),
        which is a break as well.

    So the document is asked which it does, and the answer decides what a plain
    hyphen at the end of a line means. The threshold is declared by
    R-HYPHEN-JOIN and the measurement is printed in the audit report with every
    other one; a share near the threshold is a document whose habit is not
    established, which is a thing to look at rather than to round.
    """
    rule = next((r for r in transforms
                 if r.transform == "join_hyphenated_line"), None)
    threshold = float((rule.params or {}).get("soft_hyphen_share_min", 0.5) \
                      if rule is not None else 0.5)
    soft = plain = 0
    for line in lines:
        tail = line.text.rstrip()
        if not tail.endswith(("-", _SOFT)):
            continue
        if tail.endswith(_SOFT):
            soft += 1
        else:
            plain += 1
    total = soft + plain
    if not total:
        return "hyphen"
    return "soft" if soft / total >= threshold else "hyphen"


def marker_column_policy(source: str, directory: Path | None = None) -> float:
    """How far apart two marker positions may be and still be one column.

    Same reasoning as `line_policy`: the number is a measurement of the source,
    so it is declared in `rules/00-global.yaml` (R-MARKER-COLUMN) rather than
    written into the code, and having no declaration is an error.
    """
    declared = [rule for rule in _load(source, directory).values()
                if rule.id.startswith("R-MARKER-COLUMN")]
    if not declared:
        raise RuleError(
            f"{source}: no R-MARKER-COLUMN declaration. A paragraph marker takes "
            f"its depth from the column it is printed in, so the tolerance that "
            f"column is measured with is declared, not assumed")
    chosen = declared[-1]
    unknown = sorted(set(chosen.params) - {"x_tol_pt"})
    if unknown:
        raise RuleError(f"{chosen.id}: unknown marker-column parameter "
                        f"{unknown[0]!r}")
    return float(chosen.params.get("x_tol_pt", MARKER_COLUMN_TOL))


def _load(source: str, directory: Path | None = None) -> dict:
    """Every rule in rules/*.yaml that applies to this source, by id."""
    base = Path(directory or RULES_DIR)
    out: dict = {}
    for path in sorted(base.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            rule = Rule(
                id=raw["id"],
                decision=raw["decision"],
                applies_to=tuple(raw.get("applies_to") or ("*",)),
                when=dict(raw.get("when") or {}),
                rationale=str(raw.get("rationale") or ""),
                kind=raw.get("kind", "span"),
                node=raw.get("node", ""),
                transform=raw.get("transform", ""),
                region_starts=raw.get("region_starts", ""),
                prevents=tuple(raw.get("prevents") or ()),
                akn=raw.get("akn", ""),
                name_pattern=raw.get("name_pattern", ""),
                catch_all=bool(raw.get("catch_all")),
                params=dict(raw.get("params") or {}),
                node_by_level={int(k): str(v) for k, v in
                               (raw.get("node_by_level") or {}).items()},
            )
            _validate(rule)
            if rule.applies(source):
                out[rule.id] = rule
    return out


def _validate(rule: Rule) -> None:
    if rule.decision not in DECISIONS:
        raise RuleError(f"{rule.id}: unknown decision {rule.decision!r}")
    if rule.kind not in KINDS:
        raise RuleError(f"{rule.id}: unknown kind {rule.kind!r}")
    if rule.decision == "transform" and not rule.transform:
        raise RuleError(f"{rule.id}: a transform rule needs a `transform`")
    if rule.kind == "span" and rule.decision != "transform" and not rule.when:
        raise RuleError(f"{rule.id}: a decision rule needs a `when`")
    if rule.region_starts and rule.region_starts not in REGIONS:
        raise RuleError(f"{rule.id}: unknown region {rule.region_starts!r}")
    if rule.catch_all and rule.decision != "drop":
        raise RuleError(
            f"{rule.id}: a catch-all rule must drop. A catch-all that keeps is "
            f"how 'unknown' becomes 'body' - the exact failure this ledger exists "
            f"to prevent")


# --------------------------------------------------------------------------- #
# conditions
# --------------------------------------------------------------------------- #

SUPPORTED = (
    "all_of", "any_of", "not", "always", "band", "region", "shape",
    "text_matches", "text_fullmatch", "font_pt", "font_min_pt", "font_max_pt",
    "line_ends_with_hyphen", "next_line_starts_lowercase", "follows",
    "x0_min_pt", "x0_max_pt", "y_min_pt", "y_max_pt", "page_in",
    "text_matches_raw", "superscript_marker",
)


def superscript_markers(line: "Line") -> list:
    """The spans of this line that the printer raised: a footnote's marker.

    A marker is not a word, and the two documents that carry markers here print
    them in two different ways, which is why there are two rules for it:

      * the UN Model spaces its marker off with thin spaces at the body size
        ("recognised pension fund 12 to which"), which is what R-NOTE-MARK
        reads, and the reading form has already collapsed those spaces;
      * the OECD material raises it and sets it smaller - measured, a 6pt span
        with the superscript flag set in a line of 9pt text ("Curaçao*2",
        "Hong Kong (China)6", both in the signatories table) - and what tells it
        from the letters around it is exactly that: raised, and smaller.

    Both halves are required. `flags & 1` alone would take any raised character
    (a footnote's own number, a superscript reference in a title); the size is
    what makes it smaller than the text it annotates, and the text has to be a
    bare number, because a marker is a note's number and nothing else.
    """
    out = []
    for span in line.spans:
        if not (span.flags & 1) or span.size >= line.size - 0.4:
            continue
        if re.fullmatch(r"\d{1,3}", span.text.strip() or ""):
            out.append(span)
    return out


def evaluate_when(when: dict, ctx: dict, rule_id: str) -> bool:
    unknown = sorted(set(when) - set(SUPPORTED))
    if unknown:
        raise RuleError(
            f"{rule_id}: condition {unknown[0]!r} is not implemented by this "
            f"classifier (supported: {', '.join(SUPPORTED)})")
    for key, value in when.items():
        if not _condition(key, value, ctx, rule_id):
            return False
    return True


def _condition(key: str, value, ctx: dict, rule_id: str) -> bool:
    if key == "always":
        return bool(value)
    if key == "all_of":
        return all(evaluate_when(item, ctx, rule_id) for item in value)
    if key == "any_of":
        return any(evaluate_when(item, ctx, rule_id) for item in value)
    if key == "not":
        return not evaluate_when(value, ctx, rule_id)
    if key == "band":
        wanted = (value,) if isinstance(value, str) else tuple(value)
        return ctx["band"] in wanted
    if key == "region":
        return ctx["region"] == value
    if key == "shape":
        # What kind of page this document has (R-SOURCE-SHAPE). The rules that
        # read a band are statements about a prose page - "a bare number where
        # page numbers stand is a page number", "what stands where the running
        # headers stand is a running header" - and applying them to a table is
        # not a near miss but a wrong answer, so they say which page they are
        # about instead of being applied to all of them.
        wanted = (value,) if isinstance(value, str) else tuple(value)
        return ctx.get("shape", "prose") in wanted
    if key == "font_pt":
        return abs(ctx["size"] - float(value)) < 0.05
    if key == "font_min_pt":
        return ctx["size"] >= float(value) - 0.05
    if key == "font_max_pt":
        return ctx["size"] <= float(value) + 0.05
    if key == "line_ends_with_hyphen":
        return ctx["ends_hyphenated"] is bool(value)
    if key == "next_line_starts_lowercase":
        return ctx["next_starts_lowercase"] is bool(value)
    if key == "follows":
        return ctx["previous_rule"] == value
    if key == "x0_min_pt":
        return ctx["x0"] >= float(value)
    if key == "x0_max_pt":
        return ctx["x0"] <= float(value)
    if key == "y_min_pt":
        return ctx["y"] >= float(value)
    if key == "y_max_pt":
        return ctx["y"] <= float(value)
    if key == "page_in":
        return ctx["page"] in {int(page) for page in value}
    if key == "superscript_marker":
        line = ctx.get("line")
        return bool(superscript_markers(line)) if line is not None else False
    if key == "text_matches_raw":
        # The text as printed, thin spaces and tabs included, for the few rules
        # that are about typography rather than about words: a footnote anchor is
        # a thin space, a digit and another thin space, and the matching form -
        # which collapses thin spaces into ordinary ones - cannot see it.
        return bool(re.search(value, ctx.get("text_raw", ctx["text"]), re.M))
    if key in ("text_matches", "text_fullmatch"):
        flags = re.M
        matched = (re.search(value, ctx["text"], flags) if key == "text_matches"
                   else re.fullmatch(value, ctx["text"], flags))
        return bool(matched)
    raise RuleError(f"{rule_id}: condition {key!r} is declared but not reached")


# --------------------------------------------------------------------------- #
# page geometry
# --------------------------------------------------------------------------- #

@dataclass
class Geometry:
    body_size: float
    header_y_max: float
    footer_y_min: float
    note_y_min: dict = field(default_factory=dict)   # page -> y

    def band(self, page: int, y: float, size: float) -> str:
        if y < self.header_y_max:
            return "header"
        if y >= self.footer_y_min:
            return "footer"
        note_from = self.note_y_min.get(page)
        if note_from is not None and y >= note_from - 1.0:
            return "note"
        return "body"

    def describe(self) -> str:
        notes = sum(1 for _ in self.note_y_min)
        return (f"body {self.body_size}pt · header y<{self.header_y_max:.0f} · "
                f"footer y>{self.footer_y_min:.0f} · notes on {notes} page(s)")


def measure(lines: list, policy: dict | None = None) -> Geometry:
    """Measure the bands from the document itself (rules/00-global.yaml R-BAND-DEFINE).

    `policy` is `band_policy(source)`: the one declared number is the share of
    pages a short line must repeat at a height on before that height is a band.
    """
    if not lines:
        return Geometry(body_size=0.0, header_y_max=0.0, footer_y_min=1e9)
    share = float((policy or {}).get("page_share", DEFAULT_BAND_PAGE_SHARE))
    by_size = Counter(round(l.size, 1) for l in lines)
    body_size = by_size.most_common(1)[0][0]

    # Where the text block is, as percentiles, not as a guess: a running header
    # and a page number stand *outside* the range the body covers. Position is
    # the discriminator on purpose - in the 2021 edition the header is set at
    # the same size as the body, so a rule based on "a different size" would see
    # no header at all and let it into the text.
    ordered = sorted(l.y for l in lines)
    low = ordered[int(0.05 * (len(ordered) - 1))]
    high = ordered[int(0.95 * (len(ordered) - 1))]

    pages = len({l.page for l in lines})
    # Counted in *pages*, not in lines. A table's column headings are several
    # short lines at one height on one page, so counting lines lets a single
    # page's header block outvote the share on its own; counting pages asks the
    # question the band is actually about - on how many pages does text stand at
    # this height.
    top: dict = {}
    bottom: dict = {}
    for line in lines:
        if len(line.match_text) > 40:
            continue
        if line.y < low - 5.0:
            top.setdefault(round(line.y), set()).add(line.page)
        elif line.y > high + 5.0:
            bottom.setdefault(round(line.y), set()).add(line.page)

    need = share * pages
    header_candidates = [y for y, seen in top.items() if len(seen) >= need]
    footer_candidates = [y for y, seen in bottom.items() if len(seen) >= need]
    header_y_max = (max(header_candidates) + 2.0) if header_candidates else 0.0
    footer_y_min = (min(footer_candidates) - 2.0) if footer_candidates else 1e9

    # The note band is the tail of a page set smaller than that page's own body
    # text. Both references matter, and picking either one alone gets a real
    # edition wrong:
    #
    #   * the document's most common size is 10pt in the 2021 edition, because
    #     the Commentaries (10pt) outnumber the Convention (11pt), so the
    #     footnotes are not "smaller than the body" and footnote 11 of article 1
    #     was read as article text (d10, d11);
    #   * the line immediately above the tail is a chapter title (12-14pt) on the
    #     pages that open a chapter, so every line of article 3 on page 30 looked
    #     like a footnote set smaller than the title above it.
    #
    # So: the page decides, and a run counts as notes only if it is *narrower*
    # than the size most of that page is set at.
    note_y_min: dict = {}
    per_page: dict = {}
    for line in lines:
        per_page.setdefault(line.page, []).append(line)
    for page, page_lines in per_page.items():
        ordered = [line for line in sorted(page_lines, key=lambda l: -l.y)
                   if header_y_max <= line.y < footer_y_min]
        if not ordered:
            continue
        page_size = Counter(round(l.size, 1) for l in ordered).most_common(1)[0][0]
        tail: list = []
        for line in ordered:                  # bottom up, while smaller
            if round(line.size, 1) < page_size - 0.4:
                tail.append(line)
            else:
                break
        if tail and len(tail) < len(ordered):
            note_y_min[page] = min(l.y for l in tail)
    return Geometry(body_size=body_size, header_y_max=header_y_max,
                    footer_y_min=footer_y_min, note_y_min=note_y_min)


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #

class SpanStream:
    """Read a PDF as an ordered stream of spans. Deterministic, no filtering."""

    @staticmethod
    def read(pdf: Path, source: str) -> list:
        path = Path(pdf)
        return list(_read_cached(str(path.resolve()), source,
                                 int(path.stat().st_mtime)))

    @staticmethod
    def read_lines(pdf: Path, source: str) -> list:
        return group_lines(SpanStream.read(pdf, source))


@lru_cache(maxsize=8)
def _read_cached(path_str: str, source: str, mtime: int) -> tuple:
    """Every span on every page, in geometric reading order.

    Nothing is filtered here - not by size, not by position, not by content.
    The running header of page 57 is in this stream, and that is the point:
    deciding it is apparatus is the classifier's job, and the decision is
    recorded with a rule id.
    """
    import fitz  # PyMuPDF, imported here so the harness loads without it

    document = fitz.open(path_str)
    out: list = []
    try:
        for page_index in range(document.page_count):
            page = document[page_index]
            lines = []
            for block in page.get_text("dict").get("blocks", ()):
                if block.get("type") != 0:
                    continue
                for raw_line in block.get("lines", ()):
                    spans = []
                    for raw_span in raw_line.get("spans", ()):
                        text = raw_span.get("text") or ""
                        if not text.strip():
                            continue
                        box = raw_span.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                        spans.append((box, float(raw_span.get("size") or 0.0),
                                      text, int(raw_span.get("flags") or 0)))
                    if not spans:
                        continue
                    box = raw_line.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                    lines.append((box, spans))
            # Geometric reading order: top to bottom, then left to right. The
            # PDF's block order is usually the same; this one is checkable.
            lines.sort(key=lambda item: (round(item[0][1], 1), round(item[0][0], 1)))
            for line_index, (box, spans) in enumerate(lines):
                for span_box, size, text, flags in spans:
                    out.append(Span(source=source, page=page_index,
                                    y=float(span_box[1]), x=float(span_box[0]),
                                    size=size, text=text, x1=float(span_box[2]),
                                    line=line_index, flags=flags))
    finally:
        document.close()
    return tuple(out)


def group_lines(spans: list, policy: "LinePolicy | None" = None) -> list:
    """Rebuild the printed lines of a document, and record that grouping.

    The lines returned hold re-stamped spans - `Span.line` becomes the index of
    the printed line on its page - so that the ledger, the projection and the
    node index all count lines the way the printer did. Nothing is dropped here:
    every span comes back inside exactly one line.

    Two passes, in this order, because the order spans arrive in is the reader's
    and not the printer's. First the page is cut into horizontal bands, by
    height (`y_tol_pt`); then each band is cut into the lines printed across it,
    left to right (`max_gap_pt`). Grouping in one pass - "does this span belong
    to the line I am building?" - cannot work, because the spans of a line do not
    arrive left to right: an italic letter is set a fraction of a point higher
    than the roman text around it, so it arrives *first* and opens a line of its
    own. That is how "such permanent establishment or fixed base, or with (b)
    business activities referred to in (c) of paragraph 1" became "such
    permanent establishb c ment or fixed base, or with ( ) business activities
    referred to in ( ) of paragraph 1" - every letter of a marker moved to the
    front of its line, and the rest of the marker emptied.
    """
    policy = policy or LinePolicy()
    per_page: dict = {}
    for span in spans:
        per_page.setdefault(span.page, []).append(span)

    lines: list = []
    for page in sorted(per_page):
        ordered = sorted(per_page[page], key=lambda s: (s.y, s.x))
        groups: list = []
        for band in _y_bands(ordered, policy):
            groups.extend(_x_groups(band, policy))
        groups.sort(key=lambda group: (min(s.y for s in group),
                                       min(s.x for s in group)))
        for index, row in enumerate(groups):
            lines.append(_line(page, index, row, policy))
    return lines


def _y_bands(spans: list, policy: LinePolicy) -> list:
    """One band per printed height on the page, spans in the order given.

    Measured against the band's own top edge rather than its last span, so the
    band cannot creep down a page a tolerance at a time: printed lines stand
    13pt apart and the tolerance is 2.5pt.
    """
    bands: list = []
    for span in spans:
        if bands and span.y - bands[-1][0].y <= policy.y_tol_pt:
            bands[-1].append(span)
        else:
            bands.append([span])
    return bands


def _x_groups(band: list, policy: LinePolicy) -> list:
    """One group per printed line in a band: spans left to right, gap by gap.

    A gap wider than `max_gap_pt` is a column, and a column is a line of its own
    (the signatories table declares a smaller gap, because for a table two cells
    of one row are two spans). The edge each span is measured against is the
    group's rightmost reach so far, so a long span that covers the position of a
    later one - "( ) business activities referred to in (" covers the "c" inside
    it - keeps that span in the group it belongs to instead of starting a new
    line at a column that is not there.
    """
    groups: list = []
    right = 0.0
    for span in sorted(band, key=lambda s: s.x):
        if not groups or span.x - right > policy.max_gap_pt:
            groups.append([span])
            right = span.x1
        else:
            groups[-1].append(span)
            right = max(right, span.x1)
    return groups


def regroup_lines(spans: list, policy: "LinePolicy | None" = None) -> list:
    """The printed lines of an already-grouped stream, without regrouping it.

    Used by the projection: the ledger keeps spans that `group_lines` already
    stamped with their printed line, and regrouping them must not renumber
    anything - the round-trip compares span for span against the ledger, so a
    second opinion about where lines start would be a second answer to a question
    that has one.
    """
    policy = policy or LinePolicy()
    grouped: dict = {}
    for span in spans:
        grouped.setdefault((span.page, span.line), []).append(span)
    lines: list = []
    # Ordered by the stamp, never by re-measuring: two rows can share a height
    # (a marker and the sentence beside it, further apart than a line's own
    # spacing) and then "sort by y" is a tie broken by something else, which is
    # how the projection came to hold two spans in the wrong order.
    for (page, index) in sorted(grouped):
        members = sorted(grouped[(page, index)], key=lambda s: s.x)
        lines.append(Line(
            source=members[0].source, page=page, index=index,
            y=min(s.y for s in members), x0=min(s.x for s in members),
            x1=max(s.x1 for s in members), size=max(s.size for s in members),
            text=printed_run(members, policy), spans=tuple(members)))
    return lines


def printed_run(spans, policy: "LinePolicy | None" = None) -> str:
    """The text of consecutive spans of one printed line, spaces restored.

    The runs of a printed line are contiguous, so their texts concatenate; a run
    that starts a whole column's width after the previous one ends was printed
    after a space or a tab, and reading it as if it touched the previous word
    invents a word: "(2)with respect to an item of income" is in no source. The
    threshold is `LinePolicy.space_gap_pt`, measured (2.0pt, between the widest
    in-run gap at 1.7pt and the nearest tab column at 2.4pt).
    """
    policy = policy or LinePolicy()
    pieces: list = []
    previous: "Span | None" = None
    for span in spans:
        if previous is not None and span.x - previous.x1 >= policy.space_gap_pt \
                and pieces and pieces[-1][-1:] not in ("", " ") \
                and span.text[:1] not in ("", " "):
            pieces.append(" ")
        pieces.append(span.text)
        previous = span
    return "".join(pieces)


def _line(page: int, index: int, row: list, policy: "LinePolicy | None" = None) -> Line:
    policy = policy or LinePolicy()
    members = tuple(replace(span, line=index)
                    for span in sorted(row, key=lambda s: s.x))
    return Line(
        source=members[0].source, page=page, index=index,
        y=min(s.y for s in members), x0=min(s.x for s in members),
        x1=max(s.x1 for s in members), size=max(s.size for s in members),
        text=printed_run(members, policy), spans=members)


# --------------------------------------------------------------------------- #
# the ledger
# --------------------------------------------------------------------------- #

@dataclass
class Ledger:
    """Every span, with the rule that kept, dropped or transformed it."""
    kept: list = field(default_factory=list)          # [(Span, rule id)]
    dropped: list = field(default_factory=list)       # [(Span, rule id, reason)]
    transformed: list = field(default_factory=list)   # [(Span, rule id, note)]
    unclaimed_spans: list = field(default_factory=list)
    read: int = 0
    geometry: Geometry | None = None
    unclaimed_rule: str = ""
    spans: list = field(default_factory=list)         # the stream as read, re-stamped
    line_policy: "LinePolicy | None" = None
    paragraph_tags: dict = field(default_factory=dict)
    # The same tolerance `MARKER_COLUMN_TOL` names, taken from it rather than
    # written twice: the number is declared in rules/00-global.yaml
    # (R-MARKER-COLUMN) and one of these two sites is the fallback for a caller
    # that passes no ledger, so a repair that moved one alone would leave the
    # other reading text the page prints in a different column.
    marker_column_tol: float = MARKER_COLUMN_TOL
    # Which character this document prints where it breaks a word: "soft" when
    # its hyphenation marks are the soft hyphen (the 2017 edition), "hyphen"
    # when they are a plain "-" (2021). Measured per document in `_hyphen_mark`
    # and declared by R-HYPHEN-JOIN, because the same character means opposite
    # things in the two editions and only the document can say which.
    hyphen_mark: str = "hyphen"
    # What kind of page this source has (R-SOURCE-SHAPE) and the one number its
    # page bands are measured with (R-BAND-DEFINE). Recorded on the ledger
    # because "the top of this page is a running header" is a claim a reader has
    # to be able to check: `shape` says which claim was made.
    shape: str = "prose"
    band_policy: dict = field(default_factory=dict)

    def drop(self, span: Span, rule: str, reason: str) -> None:
        self.dropped.append((span, rule, reason))

    def keep(self, span: Span, rule: str) -> None:
        self.kept.append((span, rule))

    def transform(self, span: Span, rule: str, note: str) -> None:
        self.transformed.append((span, rule, note))

    @property
    def audited(self) -> bool:
        """True when every span that was read has exactly one decision."""
        return self.read > 0 and len(self.kept) + len(self.dropped) == self.read

    @property
    def decisions(self) -> int:
        return len(self.kept) + len(self.dropped)

    def transforms_of(self, span: Span) -> list:
        """Every declared rewrite of this span, in the order the rules ran."""
        return [(rule, note) for candidate, rule, note in self.transformed
                if candidate is span]

    def rule_counts(self) -> dict:
        counts: Counter = Counter()
        for _span, rule in self.kept:
            counts[("kept", rule)] += 1
        for _span, rule, _reason in self.dropped:
            counts[("dropped", rule)] += 1
        for _span, rule, _note in self.transformed:
            counts[("transformed", rule)] += 1
        return counts

    def context(self) -> dict:
        """The numbers the audit report and the tests talk about."""
        return {
            "read": self.read,
            "kept": len(self.kept),
            "dropped": len(self.dropped),
            "transformed": len(self.transformed),
            "unclaimed": len(self.unclaimed_spans),
            "audited": self.audited,
        }


class Classifier:
    """Assign each span to body / heading / apparatus / note, by declared rules.

    Rules live in `rules/*.yaml`: "why was this text dropped?" always has an
    answer that is not a comment in a source file.
    """

    @staticmethod
    def classify(spans: list, ledger: Ledger | None = None,
                 rules: list | None = None, source: str | None = None,
                 policy: "LinePolicy | None" = None) -> Ledger:
        spans = list(spans)
        book = ledger if ledger is not None else Ledger()
        source = source or (spans[0].source if spans else "")
        rules = list(rules) if rules is not None else load_rules(source)

        decisions = [r for r in rules if r.decision != "transform"]
        transforms = [r for r in rules if r.decision == "transform"]
        if not decisions:
            raise RuleError(
                f"no decision rule applies to source {source!r}: the classifier "
                f"refuses to guess what a span is")

        book.read = len(spans)
        if not lines_claimed(decisions):
            raise RuleError(
                f"no catch-all rule applies to source {source!r}: without one, "
                f"text that no rule anticipates cannot be accounted for")
        book.line_policy = policy or line_policy(source)
        book.paragraph_tags = next((r.node_by_level for r in decisions
                                    if r.node_by_level), {})
        book.marker_column_tol = marker_column_policy(source)
        book.shape = source_shape(source)
        book.band_policy = band_policy(source)
        lines = group_lines(spans, book.line_policy)
        book.spans = [span for line in lines for span in line.spans]
        book.geometry = measure(lines, book.band_policy)
        book.hyphen_mark = _hyphen_mark(lines, transforms)
        book.unclaimed_rule = next((r.id for r in decisions if r.catch_all), "")
        regions = _regions(lines, rules, book.geometry, book.shape)

        previous_rule = ""
        for position, line in enumerate(lines):
            nxt = lines[position + 1] if position + 1 < len(lines) else None
            ctx = {
                "band": book.geometry.band(line.page, line.y, line.size),
                "region": regions.get((line.page, line.index), "body"),
                "shape": book.shape,
                "line": line,
                "size": line.size,
                "x0": line.x0,
                "y": line.y,
                "page": line.page,
                "text": line.match_text,
                "ends_hyphenated": line.ends_hyphenated,
                "next_starts_lowercase": bool(
                    nxt and nxt.page == line.page and nxt.text[:1].islower()),
                "previous_rule": previous_rule,
            }
            rule = next((r for r in decisions
                         if evaluate_when(r.when, ctx, r.id)), None)
            if rule is None:
                raise RuleError(
                    f"no rule claims line {line.page}:{line.index} "
                    f"({line.match_text[:60]!r}); every source must declare a "
                    f"final catch-all rule, so that 'unknown' can never become "
                    f"'body'")
            previous_rule = rule.id
            for span in line.spans:
                if rule.decision == "drop":
                    book.drop(span, rule.id, rule.reason)
                else:
                    book.keep(span, rule.id)
            if rule.catch_all:
                book.unclaimed_spans.extend(line.spans)

        _apply_transforms(lines, transforms, book, source, regions)
        return book


def lines_claimed(decisions: list) -> bool:
    return any(r.catch_all for r in decisions)


def _regions(lines: list, rules: list, geometry: Geometry,
             shape: str = "prose") -> dict:
    """Which part of the document each line belongs to, from declared markers."""
    starts = {r.id: r.region_starts for r in rules if r.region_starts}
    current = "front_matter"
    out: dict = {}
    for position, line in enumerate(lines):
        nxt = lines[position + 1] if position + 1 < len(lines) else None
        ctx = {
            "band": geometry.band(line.page, line.y, line.size),
            "region": current, "shape": shape, "size": line.size, "x0": line.x0,
            "y": line.y, "page": line.page,
            "text": line.match_text, "ends_hyphenated": line.ends_hyphenated,
            "next_starts_lowercase": bool(
                nxt and nxt.page == line.page and nxt.text[:1].islower()),
            "previous_rule": "",
        }
        for rule in rules:
            if rule.id not in starts:
                continue
            if evaluate_when(rule.when, ctx, rule.id):
                current = starts[rule.id]
                break
        out[(line.page, line.index)] = current
    return out


def _apply_transforms(lines: list, transforms: list, book: Ledger,
                      source: str, regions: dict | None = None) -> None:
    """Second pass: declared rewrites of kept text, recorded in the ledger.

    The band and the region are the real ones, not placeholders: a transform
    declares where it applies ("strip footnote markers, in the body"), and a
    transform that cannot see where it is would apply everywhere - including to
    the number of the note it points at.
    """
    for rule in transforms:
        for position, line in enumerate(lines):
            nxt = lines[position + 1] if position + 1 < len(lines) else None
            ctx = {
                # Transforms rewrite the text as printed, so they read the raw
                # line, not the whitespace-collapsed form the rules match on.
                "band": (book.geometry.band(line.page, line.y, line.size)
                         if book.geometry is not None else "body"),
                "region": (regions or {}).get((line.page, line.index), "body"),
                # The shape travels to the transforms too: a transform that
                # declares where it applies has to be able to see the same facts
                # the decision rules saw, or the two disagree about the page.
                "shape": book.shape,
                "line": line,
                "size": line.size,
                "x0": line.x0,
                "y": line.y,
                "page": line.page,
                # Two forms of the line, deliberately: `text` is the collapsed
                # form every rule is written against, and `text_raw` is the line
                # as printed, for a rule about typography (R-NOTE-MARK is about
                # thin spaces, which the collapsed form has already eaten).
                "text": line.match_text, "text_raw": line.text,
                "ends_hyphenated": line.ends_hyphenated,
                "next_starts_lowercase": bool(
                    nxt and nxt.page == line.page and nxt.text[:1].islower()),
                "previous_rule": "",
            }
            if not evaluate_when(rule.when, ctx, rule.id):
                continue
            if rule.transform == "join_hyphenated_line":
                span = line.spans[-1]
                if not _kept(book, span):
                    continue
                if not (line.ends_hyphenated and ctx["next_starts_lowercase"]):
                    continue
                if nxt is not None and nxt.page == line.page:
                    # Which character this document prints where it breaks a word
                    # is measured, not assumed, and the measurement decides
                    # whether a plain hyphen at the end of a line is a break at
                    # all: the 2017 edition marks its breaks with the soft hyphen
                    # and prints "day-to-" for the compound "day-to-day", while
                    # the 2021 edition breaks words with a plain "-". A rule that
                    # stripped the hyphen either way read the 2017 sentence as
                    # "more of the day-today activities" - a word in no edition.
                    tail = line.text.rstrip()
                    kept_hyphen = (book.hyphen_mark == "soft"
                                   and tail.endswith("-")
                                   and not tail.endswith(_SOFT))
                    book.transform(span, rule.id,
                                   "join_with_next_kept_hyphen" if kept_hyphen
                                   else "join_with_next")
            elif rule.transform == "strip_markers_to_anchors":
                for span in line.spans:
                    if _kept(book, span) and MARKER_RE.search(span.text):
                        note = ",".join(
                            m.group(0).strip("\u2009\u2004")
                            for m in MARKER_RE.finditer(span.text))
                        book.transform(span, rule.id, f"anchors:{note}")
            elif rule.transform == "strip_superscript_marker":
                # The marker leaves the text and is recorded as the note it
                # points at, on the marker's own span: `number:2` says "this
                # span is the number of a node", which is why emptying it takes
                # the marker out of "Curaçao*2" and leaves "Curaçao*" - a
                # jurisdiction with an asterisk and no note number in its name.
                # Slicing the digit off the words instead would be the defect
                # this rule exists to prevent: d18's "Czechia 13-05-20204
                # 16-08-20245" is what guessing at the end of a string produces.
                for span in superscript_markers(line):
                    if _kept(book, span):
                        book.transform(span, rule.id,
                                       f"number:{span.text.strip()}")
            elif rule.transform == "split_marker_to_number":
                for span in line.spans:
                    if not _kept(book, span):
                        continue
                    note = marker_note(span.text)
                    if note:
                        book.transform(span, rule.id, note)
                        break
                else:
                    # The marker is printed across spans, so no single span holds
                    # it: "(a)" is "(" and "a)". The line has it, so the note is
                    # recorded on the span the marker starts in - as
                    # `number_across`, which says "the marker begins here and
                    # continues", because `number:` says "this span *is* the
                    # marker" and emptying a span that is not the whole marker is
                    # how the "(" of every lettered item disappeared while its
                    # "a)" stayed.
                    first = next((s for s in line.spans if _kept(book, s)), None)
                    found = MARKER_PREFIX_RE.match(line.match_text)
                    if first is not None and found:
                        book.transform(first, rule.id,
                                       f"number_across:{found.group(1)}")
            else:
                raise RuleError(
                    f"{rule.id}: transform {rule.transform!r} is declared but not "
                    f"implemented by this ledger")


def _kept(book: Ledger, span: Span) -> bool:
    return any(candidate is span for candidate, _rule in book.kept)


# A paragraph marker as this PDF prints it: "1.", "(a)", "(ii)", "(A)", either
# alone in its span (the usual case - PyMuPDF splits the tab) or opening it.
SPAN_MARKER_RE = re.compile(r"^(" + MARKER_TOKEN + r")$")
SPAN_MARKER_OPEN_RE = re.compile(r"^(" + MARKER_TOKEN + r") (?=\S)")


def marker_note(text: str) -> str:
    """How to turn this span into a node number, or "" if it is not a marker."""
    flat = normalise(text)
    alone = SPAN_MARKER_RE.match(flat)
    if alone:
        return f"number:{alone.group(1)}"
    opening = SPAN_MARKER_OPEN_RE.match(flat)
    if opening:
        return f"number_prefix:{opening.group(1)}"
    return ""


# --------------------------------------------------------------------------- #
# text transforms, as the projection must apply them
# --------------------------------------------------------------------------- #

def joined_text(span: Span, book: Ledger | None) -> str:
    """The span's text with the ledger's declared rewrites applied.

    Every rewrite is a `transform` entry of the ledger, so "the text changed
    here, like this" is a record rather than an undocumented edit. A span may
    carry more than one: the same span can be a paragraph marker and hold a
    footnote anchor.
    """
    if book is None:
        return span.text
    return apply_rewrites(span.text, [note for _rule, note
                                      in book.transforms_of(span)])


def apply_rewrites(text: str, notes, cut_markers: bool = True) -> str:
    """The ledger's rewrites, as text in and text out.

    Split out of `joined_text` so that they can be applied to a ledger's
    *records* as well as to its spans. A reader of a written `.spans.jsonl` has
    the declarations and no `Span` objects, and "what did this text become"
    must have one implementation, or it has two answers - and `test_f02`
    compares the corpus against that answer.
    """
    if not notes:
        return text
    for note in notes if cut_markers else ():
        if note.startswith("number:") or note.startswith("number_prefix:"):
            # The marker is the node's number: it leaves the text, and the
            # ledger says so. `number_prefix` cuts a marker printed in the same
            # span as the words it numbers. `number_across` is neither - the
            # marker starts in this span and runs past it, so the cutting happens
            # on the joined line, in `_strip_declared_marker`.
            marker = note.split(":", 1)[1] if ":" in note else ""
            text = "" if note.startswith("number:") else \
                text.lstrip()[len(marker):].lstrip()
    for note in notes:
        if note.startswith("anchors:"):
            text = MARKER_RE.sub("", text)
        elif note.startswith("join_with_next"):
            # Both marks go, and both is the point: the printer sets the
            # hyphenation hyphen *and* a soft hyphen after it ("Contract-\xad"),
            # so removing one character left "Contract-" joined to "ing" and the
            # corpus read "Contract-ing" (d15). A word broken across a line is
            # one word, and the mark that broke it is not part of it.
            #
            # `join_with_next_kept_hyphen` is the other case, and it is a
            # different sentence: the line was broken at a hyphen the word
            # already had, so the hyphen stays and only the space of the break
            # goes ("day-to-" + "day" is "day-to-day").
            stripped = text.rstrip()
            if note == "join_with_next_kept_hyphen":
                text = stripped
            else:
                text = (stripped.rstrip("-" + _SOFT)
                        if stripped.endswith(("-", _SOFT)) else stripped)
    return text


# --------------------------------------------------------------------------- #
# reading a written ledger back
# --------------------------------------------------------------------------- #

NOTE_SEPARATOR = "; "


def notes_of(record: dict) -> list:
    """The rewrite notes a ledger record carries, in the order they were made."""
    note = str(record.get("note") or "")
    return [part for part in note.split(NOTE_SEPARATOR) if part]


def reading_of(records: list, policy: "LinePolicy | None" = None,
               cut_markers: bool = True) -> str:
    """The text a written ledger says was printed: kept spans, read as recorded.

    This is what makes the ledger a record rather than a log. Everything the
    text depends on is in the file - each span's text and x1 (a span starting a
    column's width after the previous one ends was printed after a space), each
    span's printed line, the rewrites a rule declared, and the line policy the
    whole reading was made with. So the corpus' own words can be checked against
    the ledger rather than against a second reader of the PDF: `test_f02` asks
    for every word of the AKN to be a word of this string, which no writer can
    satisfy by inventing, duplicating or reordering text.

    Dropped spans are not here, and that is the point of the comparison: text a
    rule dropped may not appear in the corpus, however it got there.

    `cut_markers` says what to do with a paragraph marker. The writer moves it
    into the element that carries the number (`<num>`), so a reader comparing the
    corpus with this reading wants it here: the corpus' text holds the number
    too, and a comparison that cut it would report every number as text the
    ledger does not have.
    """
    policy = policy or LinePolicy()
    lines: list = []                 # [(key, [record, ...])], in document order
    for record in records:
        if str(record.get("decision")) == "drop":
            continue
        key = (record.get("page"), record.get("line"))
        if not lines or lines[-1][0] != key:
            lines.append((key, [record]))
        else:
            lines[-1][1].append(record)

    pieces: list = []
    previous: list = []
    for _key, members in lines:
        text = _record_line_text(members, policy, cut_markers)
        if pieces and pieces[-1][-1:] not in ("", " ") and text[:1] not in ("", " "):
            if not any(note.startswith("join_with_next")
                       for note in notes_of(previous[-1])):
                pieces.append(" ")
        pieces.append(text)
        previous = members
    return "".join(pieces)


def _record_line_text(members: list, policy: LinePolicy,
                      cut_markers: bool = True) -> str:
    """One printed line of records: its text, rewrites applied, marker cut.

    The within-line rule is `printed_run`'s, read off `x` and `x1`, and the
    marker is cut the way `_strip_declared_marker` cuts it - a marker printed
    across two spans belongs to neither of them, so it is removed from the line
    they make together.
    """
    pieces: list = []
    previous: dict | None = None
    for record in members:
        text = apply_rewrites(str(record.get("text") or ""), notes_of(record),
                              cut_markers)
        if previous is not None and pieces and pieces[-1][-1:] not in ("", " ") \
                and text[:1] not in ("", " "):
            if float(record.get("x") or 0.0) \
                    - float(previous.get("x1") or 0.0) >= policy.space_gap_pt:
                pieces.append(" ")
        pieces.append(text)
        previous = record
    text = "".join(pieces)
    if not cut_markers:
        return text
    for note in notes_of(members[0]):
        if not note.startswith("number"):
            continue
        marker = note.split(":", 1)[1] if ":" in note else ""
        stripped = text.lstrip()
        if marker and stripped.startswith(marker):
            text = stripped[len(marker):].lstrip()
        break
    return text


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #

@dataclass
class Node:
    tag: str
    eId: str
    number: str = ""
    title: str = ""
    level: int = 0          # marker depth: 1 paragraph, 2 subparagraph, 3 point
    spans: list = field(default_factory=list)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            for node in child.walk():
                yield node

    def full_text(self, book: Ledger | None = None) -> str:
        """The text of this node and of everything below it."""
        return _full_text(self, book)

    def text(self, book: Ledger | None = None) -> str:
        """The node's own text, as printed.

        Spans inside a printed line are joined exactly as they were set; two
        spans on different lines are joined by the space the line break stands
        for - unless the ledger declared a hyphen join across that break, in
        which case the two halves are one word and nothing may be inserted.
        """
        return _join_spans(self.spans, book)


def _join_spans(spans, book: Ledger | None) -> str:
    """One string from a span sequence: the text the projection must produce.

    Two spacings, both read off the page rather than assumed. Between two printed
    lines the printer broke the line, so there was a space (or a hyphen, which
    the ledger declares as a transform); between two spans of one printed line
    there is a space only where the printer's own gap is wide enough to be one -
    `printed_run`'s measurement - and the corpus must agree with the line text a
    rule was matched against, not merely be similar to it.
    """
    policy = (book.line_policy if book is not None and book.line_policy
              else LinePolicy())
    pieces: list = []
    previous_key = None
    previous_span = None
    for span in spans:
        key = (span.page, span.line)
        piece = joined_text(span, book)
        if previous_key is not None and pieces and pieces[-1][-1:] not in ("", " ") \
                and piece[:1] not in ("", " "):
            if key != previous_key:
                if not _joins_next(previous_span, book):
                    pieces.append(" ")
            elif span.x - previous_span.x1 >= policy.space_gap_pt:
                pieces.append(" ")
        pieces.append(piece)
        previous_key, previous_span = key, span
    return _strip_declared_marker(spans, "".join(pieces), book)


def _strip_declared_marker(spans, text: str, book: Ledger | None) -> str:
    """A paragraph's marker leaves its text, however many spans it was printed in.

    A marker is its own span only when PyMuPDF felt like it: "1." arrives alone
    in its span, but "(a)" arrives split into "(" and "a)" - the parenthesis set
    in a different font run from the letter it encloses. Stripping the marker per
    span therefore worked for numbered paragraphs and left "(a)" at the front of
    every lettered item, so the corpus printed its own marker twice: once as the
    node's number and once as the first word of its text. The ledger entry is the
    same one either way (`number:(a)`), and only the place the characters live
    differs, which is what this function is for.
    """
    if book is None or not spans:
        return text
    for _rule, note in book.transforms_of(spans[0]):
        if not note.startswith("number"):
            continue
        marker = note.split(":", 1)[1] if ":" in note else ""
        stripped = text.lstrip()
        if marker and stripped.startswith(marker):
            return stripped[len(marker):].lstrip()
    return text


def _full_text(node: "Node", book: Ledger | None) -> str:
    """The text of a node and of everything under it."""
    return " ".join(part for part in (n.text(book) for n in node.walk()) if part)


def _joins_next(span, book: Ledger | None) -> bool:
    """True when the ledger declares that this span's line runs into the next."""
    if book is None or span is None:
        return False
    return any(note.startswith("join_with_next")
               for _rule, note in book.transforms_of(span))


# The *shape* of a marker names it; the column it is printed in decides how deep
# it sits. The two are not the same, and the difference is not a detail: article
# 29 numbers its list of definitions (a), (b), ..., (i), (j), so the ninth item
# is printed "(i)" and, read as text, is indistinguishable from the roman
# numeral that opens a nested list. A shape table cannot tell them apart; the
# printed column can, and it is measured (`marker_columns`) rather than guessed.
#
# A marker is also allowed more than one dot: the 2017 Model prints a paragraph
# numbered "4.1" between paragraphs 4 and 5 of article 5, at the paragraph
# column and the paragraph tab stop, and the two list items that hang from it
# are its children. Reading "4.1" as body text put them under paragraph 4
# instead and gave two nodes the same identity.
MARKER_PREFIX_RE = re.compile(r"^(" + MARKER_TOKEN + r")(?=\s|$)")
ARTICLE_NUMBER_RE = re.compile(r"^(Article\s?\d{1,2}\s?[A-Z]?)")
CHAPTER_NUMBER_RE = re.compile(r"^(Chapter\s+[IVXLC]+)")
# `\s` where the source may set a no-break space: the 2021 edition prints
# "Article 25 (Alternative A)" with no-break spaces inside it, and a pattern
# written with ordinary spaces matched neither number nor title.
ALTERNATIVE_RE = re.compile(r"^(Article\s?\d{1,2}\s?[A-Z]?)\s+"
                            r"\((?:alternative|Alternative)\s+([AB])\)$")
PARAGRAPH_ROLE = "paragraph"


class Projection:
    """Build structural nodes (document/chapter/article/paragraph/note) over kept spans."""

    @staticmethod
    def build(kept: list, source: str, book: Ledger | None = None) -> Node:
        lines = regroup_lines([span for span, _rule in kept],
                          book.line_policy if book is not None else None)
        decisions = {id(span): rule for span, rule in kept}
        tags = dict(book.paragraph_tags) if book is not None else {}
        counters: Counter = Counter()
        leading = _leading(lines)
        tol = book.marker_column_tol if book is not None else MARKER_COLUMN_TOL
        columns = marker_columns(kept, tol,
                                 book.line_policy if book is not None else None)

        root = Node(tag="document", eId=source)
        front = Node(tag="front_matter", eId=f"{source}__front_matter")
        root.children.append(front)

        chapter: Node | None = None
        article: Node | None = None
        alternative: Node | None = None
        note_open: Node | None = None
        instrument: Node | None = None
        preamble: Node | None = None
        open_paragraphs: list = []
        text_node: Node | None = None
        text_parent: Node | None = None
        last_y: tuple | None = None

        def anchor() -> Node:
            """Where a new node attaches: the deepest open structural node."""
            for candidate in (alternative, article, chapter, preamble, instrument):
                if candidate is not None:
                    return candidate
            return front

        for line in lines:
            tag = _node_of(decisions.get(id(line.spans[0]), ""))

            if tag in (None, "alinea"):
                # Unnumbered text: a run of lines is one alinea, not one node per
                # line. It continues while the lines follow one another down the
                # page, and across a page break when the previous line reached
                # the foot of its page - the sentence ran off the page, and
                # starting a new node there would cut a paragraph at every page
                # boundary (the previous corpus' paragraph diff came from
                # counting text blocks like these).
                where = open_paragraphs[-1] if open_paragraphs else anchor()
                continues = (text_node is not None and text_parent is where
                             and last_y is not None
                             and _follows(line, last_y, leading,
                                          footer=_footer_of(book, lines, last_y)))
                if continues:
                    text_node.spans.extend(line.spans)
                else:
                    text_node = Node(tag="alinea",
                                     eId=_eid(where, "alinea", counters))
                    where.children.append(text_node)
                    text_node.spans.extend(line.spans)
                    text_parent = where
                last_y = (line.page, line.y)
                continue

            if tag == "convention_title":
                # The instrument itself, as against the book that carries it:
                # the title, the naming sentence under it and then the preamble.
                # The line is the container's own heading, so text that follows
                # before the preamble heading attaches here and not to the front
                # matter - which is where it landed when the title was a leaf, and
                # which put the instrument's opening words inside the book's
                # cover matter.
                instrument = Node(tag="convention", eId=f"{source}__convention",
                                  title=_join_spans(line.spans, book))
                instrument.spans.extend(line.spans)
                root.children.append(instrument)
                text_node = text_parent = None
                open_paragraphs = []
            elif tag == "preamble_heading":
                heading = _join_spans(line.spans, book)
                preamble = Node(tag="preamble",
                                eId=f"{source}__convention__preamble",
                                title=heading)
                preamble.spans.extend(line.spans)
                (instrument or root).children.append(preamble)
                text_node = text_parent = None
                open_paragraphs = []
            elif tag == "document_boundary":
                boundary = Node(tag="document_boundary",
                                eId=f"{source}__part_two",
                                title=_join_spans(line.spans, book))
                boundary.spans.extend(line.spans)
                root.children.append(boundary)
                chapter = article = alternative = text_node = text_parent = None
                preamble = instrument = None
                note_open = None
                open_paragraphs = []
            elif tag == "chapter":
                heading = _join_spans(line.spans, book)
                number = _first(CHAPTER_NUMBER_RE, heading) or heading
                chapter = Node(tag="chapter", number=number,
                               eId=_eid(root, "ch", counters, number))
                root.children.append(chapter)
                article = alternative = text_node = text_parent = None
                open_paragraphs = []
                chapter.spans.extend(line.spans)
            elif tag == "chapter_title":
                if chapter is not None:
                    # The title is written from the spans, with the ledger's
                    # rewrites applied: a transform the classifier declared has
                    # to reach the title too, or the title is the one place a
                    # footnote marker can still sit. A long title wraps onto a
                    # second line (R-CHAPTER-NAME-CONT), and appending rather
                    # than replacing is what keeps the first half: replacing it
                    # left the chapter titled "CONVENTION BETWEEN DEVELOPED AND
                    # DEVELOPING COUNTRIES" without the "TAXES COVERED BY THE".
                    piece = _join_spans(line.spans, book)
                    chapter.title = f"{chapter.title} {piece}".strip()
                    chapter.spans.extend(line.spans)
            elif tag == "article":
                heading = _join_spans(line.spans, book)
                number = _first(ARTICLE_NUMBER_RE, heading) or heading
                parent = chapter if chapter is not None else root
                article = Node(tag="article", number=number,
                               eId=_eid(parent, "art", counters, number))
                parent.children.append(article)
                alternative = text_node = text_parent = None
                open_paragraphs = []
                article.spans.extend(line.spans)
            elif tag == "article_title":
                if article is not None:
                    piece = _join_spans(line.spans, book)
                    article.title = f"{article.title} {piece}".strip()
                    article.spans.extend(line.spans)
            elif tag == "alternative":
                label = _join_spans(line.spans, book)
                parent = article if article is not None else anchor()
                found = ALTERNATIVE_RE.match(label)
                alternative = Node(
                    tag="alternative", level=0,
                    number=found.group(1) if found else label,
                    title=f"alternative {found.group(2)}" if found else "",
                    eId=_eid(parent, "alt", counters, label))
                parent.children.append(alternative)
                alternative.spans.extend(line.spans)
                text_node = text_parent = None
                open_paragraphs = []
            elif tag == "note":
                # A note runs until the next numbered note or the page ends: its
                # continuation lines are part of it, not notes of their own.
                continues = (note_open is not None and last_y is not None
                             and line.page == last_y[0]
                             and line.y - last_y[1] <= 1.6 * leading
                             and not re.match(r"^\d{1,3}\s", line.match_text))
                # Where the note belongs: the deepest open node, not the article.
                # A footnote is printed at the foot of the page it belongs to, so
                # in the stream it stands between the body text above it and the
                # text that continues on the next page - and the projection has
                # to preserve that order, because the round-trip compares the
                # spans of the nodes, in order, with the stream. Hanging the note
                # on the article while the list it interrupts is still open puts
                # the list item that resumes after it *inside a branch that
                # precedes the note*, and the round-trip fails: the second
                # failure shape this projection has produced, and the reason the
                # parent is chosen here rather than at the top.
                where = open_paragraphs[-1] if open_paragraphs else anchor()
                new_note = not continues
                if new_note:
                    note_open = Node(tag="note",
                                     eId=_eid(where, "note", counters,
                                              line.match_text),
                                     number=_leading_number(line.match_text))
                    where.children.append(note_open)
                note_open.spans.extend(line.spans)
                # The open paragraphs stay open. A footnote interrupts the page,
                # not the hierarchy: clearing the stack here detached every list
                # item that resumed after a footnote from its list - the (ii) of
                # article 29(f) became a child of the article, at the same depth
                # as (f) itself.
                text_node = text_parent = None
            elif tag == PARAGRAPH_ROLE:
                marker = _marker_number(line, book)
                level = _marker_level(line, columns, tol)
                node_tag = tags.get(level)
                if node_tag is None:
                    raise RuleError(
                        f"{source}: marker {marker!r} is depth {level} and no "
                        f"rule declares a node for that depth "
                        f"(R-PARA-NUMBER node_by_level has {sorted(tags)}): a "
                        f"marker this ledger has no name for is not a paragraph")
                # Where a node belongs follows from its depth, never from the
                # text: the last open node shallower than this marker is its
                # parent. Reading the depth off the generated id instead is what
                # nested "(b)" inside "(a)" - the id carries the marker, not the
                # depth, so every level looked like level 0.
                parent = next((p for p in reversed(open_paragraphs)
                               if p.level < level), anchor())
                paragraph = Node(tag=node_tag, level=level, number=marker,
                                 eId=_eid(parent, "para", counters, marker))
                parent.children.append(paragraph)
                open_paragraphs = [p for p in open_paragraphs
                                   if p.level < level] + [paragraph]
                paragraph.spans.extend(line.spans)
                text_node = text_parent = paragraph
            else:
                raise RuleError(f"unknown node {tag!r}")
            last_y = (line.page, line.y)

        return root


def _follows(line: Line, last_y: tuple, leading: float,
             footer: float | None = None) -> bool:
    """True when this line continues the text node the previous line ended.

    Two ways to continue, both measured rather than assumed: the next line on the
    same page, closer than one and a half line spacings; or the first lines of the
    next page, when the previous line stood at the foot of its own page (within
    two spacings of the page footer), which is what a sentence looks like when it
    runs off the page.
    """
    previous_page, previous_y = last_y
    if line.page == previous_page:
        return line.y - previous_y <= 1.6 * leading
    if footer is None:
        return False
    return line.page == previous_page + 1 and previous_y >= footer - 2.0 * leading


def _footer_of(book: Ledger | None, lines: list, last_y: tuple) -> float | None:
    """Where the text block of the previous line's page ends."""
    if book is None or book.geometry is None:
        return None
    return book.geometry.footer_y_min


def _leading(lines: list) -> float:
    gaps = [b.y - a.y for a, b in zip(lines, lines[1:])
            if a.page == b.page and 0 < b.y - a.y < 40]
    if not gaps:
        return 13.0
    gaps.sort()
    return gaps[len(gaps) // 2]


def _node_of(rule: str) -> str | None:
    """Which structural role a rule opens, or None for plain body text."""
    return {
        "R-CHAPTER-NUMBER": "chapter",
        "R-CHAPTER-NAME": "chapter_title",
        "R-ART-NUMBER": "article",
        "R-ART-NAME": "article_title",
        "R-ALTERNATIVE-LABEL": "alternative",
        "R-NOTE-BAND": "note",
        "R-PARA-NUMBER": PARAGRAPH_ROLE,
        "R-BODY-TEXT": "alinea",
        "R-PART-TWO": "document_boundary",
        "R-CONVENTION-START": "convention_title",
        "R-PREAMBLE-START": "preamble_heading",
    }.get(rule)


def _eid(parent: Node, kind: str, counters: Counter, text: str = "") -> str:
    """A stable, readable id for a node - and never the same id twice.

    An identity is a promise that one eId names one object (invariant F10, and
    the one Akoma Ntoso itself makes). Two nodes under one parent that would
    both be `art_29__p7__ph__pi` are not a numbering detail to be patched with a
    suffix: they mean the projection put a list item at the wrong depth, and
    that is what this raise says.
    """
    candidate = _candidate_eid(parent, kind, counters, text)
    if any(child.eId == candidate for child in parent.children):
        raise RuleError(
            f"two nodes under {parent.eId} would both be {candidate!r}: the "
            f"marker {text!r} is used twice at one depth, so the nesting is "
            f"wrong - an eId that names two nodes names neither")
    return candidate


def _candidate_eid(parent: Node, kind: str, counters: Counter,
                   text: str = "") -> str:
    """The id a node would have, before it is checked against its siblings."""
    counters[kind] += 1
    counter = str(counters[kind])
    if kind == "art":
        # Anchored on the heading, not searched: an unanchored match on "Chapter
        # X" grabs the C of "Chapter" and gives every chapter the same id. The
        # 2017 edition prints the sub-numbered articles as "Article 23 A" and
        # its running header as "Article 23A", so both spellings normalise here.
        found = re.match(r"Article\s?(\d{1,2})\s?([A-Z]?)", text)
        return f"art_{found.group(1) + found.group(2) if found else counter}"
    if kind == "ch":
        found = re.match(r"Chapter\s+([IVXLC]+)", text)
        return f"ch_{found.group(1) if found else counter}"
    if kind == "alt":
        found = re.search(r"[Aa]lternative\s+([AB])", text)
        return f"{parent.eId}__alt_{found.group(1) if found else counter}"
    if kind == "note":
        # Notes repeat their number on every article, so the id has to say which
        # article the note hangs from, or two notes collide (invariant F10).
        return f"{parent.eId}__note{_leading_number(text) or counter}"
    if kind == "para":
        # The marker, stripped to what an XML id may hold: "1." = p1, "(a)" = pa.
        return f"{parent.eId}__p{re.sub(r'[^0-9A-Za-z]', '', text) or counter}"
    if kind == "alinea":
        return f"{parent.eId}__a{counter}"
    return f"{parent.eId}__p{_leading_number(text) or counter}"


def _leading_number(text: str) -> str:
    """The marker a paragraph or note opens with: "4", "a", "ii", "A".

    Case is preserved on purpose: "a" and "A" are different markers, and
    lowercasing both would make two nodes collide on the same eId. Both spellings
    the source uses are accepted - "1." and "(a)" - because the earlier pattern
    here required an opening parenthesis, so every numbered paragraph fell back to
    a positional counter and the 2017 note 10 became "note20".
    """
    match = re.match(r"^\s*(?:\(([0-9]{1,3}|[A-Za-z]{1,6})\)|"
                     r"([0-9]{1,3})\.|([0-9]{1,3})(?=[\s\u2009\u2004]))",
                     text or "")
    if not match:
        return ""
    return match.group(1) or match.group(2) or match.group(3) or ""


def _marker_number(line: Line, book: Ledger | None) -> str:
    """The marker of a paragraph, as the node's number: "1.", "(a)", "(ii)".

    Preferred source is the ledger: `R-PARA-MARKER` records the marker as a
    transform of the span that holds it, so the number is read from a decided
    fact rather than re-parsed from the text.
    """
    if book is not None:
        for span in line.spans:
            for _rule, note in book.transforms_of(span):
                if note.startswith("number"):
                    return note.split(":", 1)[1]
    found = MARKER_PREFIX_RE.match(line.match_text)
    return found.group(1) if found else line.match_text.split(" ")[0]


def marker_columns(kept: list, tol: float = MARKER_COLUMN_TOL,
                   policy: "LinePolicy | None" = None) -> list:
    """The columns paragraph markers are printed in, left to right.

    Measured from the document, never chosen. A paragraph marker stands at the
    left edge of a column that is the same on every page, and the columns are
    the depths: 1 is the outermost. The roman column is right-aligned - "(i)",
    "(ii)" and "(iii)" end together, so they do not start together - which is
    why a column is a cluster with a declared tolerance and not an equality.

    Measured for the 2017 Model: x = 59.7 ("1.", "4.1"), 71.7 ("(a)"),
    92.4 ("(i)", "(ii)", "(iii)") and 112.5 ("(A)"); the 2021 edition adds a
    fifth at x = 131.7 ("(I)").
    """
    decisions = {id(span): rule for span, rule in kept}
    positions = [round(line.spans[0].x, 1)
                 for line in regroup_lines([span for span, _rule in kept], policy)
                 if decisions.get(id(line.spans[0])) == "R-PARA-NUMBER"]
    columns: list = []
    for x in sorted(positions):
        if columns and x - columns[-1][-1] <= tol:
            columns[-1].append(x)
        else:
            columns.append([x])
    return [round(sum(group) / len(group), 1) for group in columns]


def _marker_level(line: Line, columns: list, tol: float) -> int:
    """How deep a marker sits: the rank of the column it is printed in.

    Text alone cannot answer this. Article 29 of the 2017 Model numbers its list
    of definitions (a), (b), ..., (i), (j), so its ninth item is printed "(i)" -
    the same glyphs as the roman numeral opening a nested list, at a different
    column. Reading the depth off the shape made that item a sibling of the
    sub-items of item (h) and gave three nodes one identity. The column is the
    evidence a reader uses, and a marker printed in no measured column raises
    RuleError rather than being emitted at a guessed depth.
    """
    if not columns:
        raise RuleError("no paragraph marker was kept, so no marker column "
                        "could be measured")
    x = line.spans[0].x
    nearest = min(columns, key=lambda column: abs(column - x))
    if abs(nearest - x) > tol:
        raise RuleError(
            f"paragraph marker {line.match_text[:24]!r} is printed at "
            f"x = {x:.1f}, which is no measured marker column "
            f"({', '.join(f'{column:.1f}' for column in columns)}): this "
            f"ledger declares no depth for it")
    return columns.index(nearest) + 1


def _first(pattern: "re.Pattern", text: str) -> str:
    """The first group of a match at the start of the text, or ""."""
    found = pattern.match(text or "")
    return found.group(1) if found else ""


# --------------------------------------------------------------------------- #
# verification and reporting
# --------------------------------------------------------------------------- #

def verify_roundtrip(projection, book: Ledger, source: str) -> tuple:
    """Rebuild the span sequence from the projection and compare it with the stream.

    This is what makes F2/F3/F5 mechanical: if the round-trip is exact, the
    corpus contains nothing that was not in the source and lost nothing that was
    in it (typographic transforms excepted, and those are ledger entries).
    """
    rebuilt = [span for node in projection.walk() for span in node.spans]
    expected = [span for span, _rule in book.kept]
    if len(rebuilt) != len(expected):
        return False, (f"{source}: the projection holds {len(rebuilt)} spans, the "
                       f"ledger kept {len(expected)}")
    for position, (got, want) in enumerate(zip(rebuilt, expected)):
        if got is want:
            continue
        if (got.page, got.line, round(got.x, 1), got.text) != \
                (want.page, want.line, round(want.x, 1), want.text):
            return False, (f"{source}: span {position} differs - projection has "
                           f"p{got.page}:{got.line} {got.text[:50]!r}, the ledger "
                           f"kept p{want.page}:{want.line} {want.text[:50]!r}")
    return True, f"{source}: {len(rebuilt)} placed spans reproduce the kept stream"


def audit_report(book: Ledger) -> str:
    """Human-readable account of what was kept, dropped and transformed."""
    lines = ["span ledger", "=" * 11]
    if book.geometry is not None:
        lines.append(f"geometry: {book.geometry.describe()}")
    if book.shape != "prose":
        lines.append(f"page shape: {book.shape}")
    if book.band_policy:
        lines.append(f"bands: a height is a band on "
                     f"{book.band_policy['page_share']:.0%} or more of the pages "
                     f"({book.band_policy.get('rule', '')})")
    if book.line_policy is not None:
        lines.append(f"lines: {book.line_policy.describe()}")
    if book.paragraph_tags:
        levels = ", ".join(f"{level}:{tag}" for level, tag
                           in sorted(book.paragraph_tags.items()))
        lines.append(f"marker depth -> node: {levels}")
    columns = marker_columns(book.kept, book.marker_column_tol, book.line_policy)
    if columns:
        lines.append("marker column -> depth: " + ", ".join(
            f"{column:.1f}:{rank}" for rank, column in enumerate(columns, 1)))
    context = book.context()
    lines.append(f"spans read: {context['read']}")
    lines.append(f"  kept:        {context['kept']}")
    lines.append(f"  dropped:     {context['dropped']}")
    lines.append(f"  transformed: {context['transformed']}")
    lines.append(f"every span decided: {'yes' if book.audited else 'NO'}")
    lines.append("")
    lines.append("by rule")
    for (what, rule), count in sorted(book.rule_counts().items()):
        lines.append(f"  {what:<11} {rule:<24} {count:>7}")
    numbers = Counter(rule for _span, rule, _reason in book.dropped)
    if numbers:
        lines.append("")
        lines.append("dropped, by rule")
        for rule, count in numbers.most_common():
            reason = next((r for _s, rid, r in book.dropped if rid == rule), "")
            lines.append(f"  {rule:<24} {count:>7}  {reason[:90]}")
    if book.unclaimed_spans:
        lines.append("")
        lines.append(f"unclaimed ({len(book.unclaimed_spans)}) - no rule of this "
                     f"source claimed them, so they were dropped by "
                     f"{book.unclaimed_rule or 'the catch-all rule'}; review:")
        for span in book.unclaimed_spans[:20]:
            lines.append(f"  p{span.page:<4} y{span.y:6.1f} {span.text.strip()[:70]!r}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# artefact writer
# --------------------------------------------------------------------------- #

# The record's fields, in the order each row writes them. `x1` is here because
# the text of a printed line depends on it: a span that starts a column's width
# after the previous one ends was printed after a space, and a reader holding
# only `x` cannot tell. A ledger that cannot be read back into the text it
# records is a log, not a record.
LEDGER_FIELDS = ("page", "line", "x", "x1", "y", "size", "decision", "rule",
                 "transform", "note", "text")
LEDGER_DECISIONS = ("keep", "drop", "unclaimed")


def ledger_records(spans: list | None, book: Ledger) -> tuple:
    """The ledger as data: a header, then one array per span in document order.

    `spans` is the stream the ledger was built from, usually `book.spans` - the
    reader's spans re-stamped with their printed line, which is the numbering the
    rest of the corpus uses.

    Compact on purpose. The ledger is a verbatim record of every span in an
    828-page document, so repeating ten key names 35,000 times would triple the
    file for no reader's benefit: the header declares the fields and the rule
    ids once, and each line is an array in that order. `corpus.load_spans`
    turns it back into dictionaries.
    """
    spans = list(spans if spans is not None else book.spans)
    rules: list = []
    decision: dict = {}
    for span, rule in book.kept:
        decision[id(span)] = ("keep", rule, "", "")
    for span, rule, _reason in book.dropped:
        decision[id(span)] = ("drop", rule, "", "")
    for span, rule, note in book.transformed:
        what, held_rule, kept_rule, held_note = decision.get(
            id(span), ("unclaimed", rule, "", ""))
        combined = "; ".join(part for part in (held_note, note) if part)
        decision[id(span)] = (what, held_rule or rule, kept_rule or rule, combined)

    rows = []
    for span in spans:
        what, rule, transform, note = decision.get(id(span),
                                                   ("unclaimed", "", "", ""))
        for name in (rule, transform):
            if name and name not in rules:
                rules.append(name)
        rows.append([span.page, span.line, round(span.x, 2), round(span.x1, 2),
                     round(span.y, 2),
                     round(span.size, 2), LEDGER_DECISIONS.index(what) if what in
                     LEDGER_DECISIONS else 2,
                     rules.index(rule) if rule else -1,
                     rules.index(transform) if transform else -1,
                     note, span.text])
    policy = book.line_policy or LinePolicy()
    header = {"format": "span ledger v1", "fields": list(LEDGER_FIELDS),
              "decisions": list(LEDGER_DECISIONS), "rules": rules,
              # The measurements the text is built with travel with the text: a
              # reader of this file can rebuild the reading it records without
              # re-reading the PDF, and without being handed this program.
              "line_policy": {"max_gap_pt": policy.max_gap_pt,
                              "y_tol_pt": policy.y_tol_pt,
                              "space_gap_pt": policy.space_gap_pt},
              "hyphen_mark": book.hyphen_mark,
              # And the two claims about the shape of a page that decided what is
              # apparatus: a reader who disagrees with "the top of this page is a
              # running header" needs to see that it was claimed, and how.
              "page_shape": book.shape,
              "bands": dict(book.band_policy),
              "source": spans[0].source if spans else "", "spans": len(spans)}
    return header, rows


def node_records(projection: Node, spans: list) -> list:
    """The structural index: eId, tag, page and span range, per node.

    The range is a pair of indexes into the span ledger - the file written
    beside this one - so that "where does this paragraph come from" has an answer
    a reader can follow: open `model-<edition>.spans.jsonl`, read the records
    between those two numbers, and the page, the column and the text are there.

    An index into the projection's own walk order would be cheaper and useless:
    the walk is not written down anywhere, so a number in that numbering names a
    position in a list that exists only while the program runs. A node whose
    spans are not in the ledger is an error and not an omission - provenance
    nobody can look up is not provenance.
    """
    position = {id(span): index for index, span in enumerate(spans)}
    out: list = []

    def visit(node: Node, depth: int, parent: str) -> None:
        if node.spans:
            indexes: list = []
            for span in node.spans:
                index = position.get(id(span))
                if index is None:
                    raise RuleError(
                        f"{node.eId}: the node holds a span that is not in the "
                        f"ledger ({span.page + 1}:{span.text[:30]!r}), so its "
                        f"provenance cannot be followed")
                indexes.append(index)
            out.append({
                "eId": node.eId, "tag": node.tag, "number": node.number,
                "title": node.title, "parent": parent, "depth": depth,
                "page": node.spans[0].page,
                "spans": [min(indexes), max(indexes)],
            })
        for child in node.children:
            visit(child, depth + 1, node.eId)

    visit(projection, 0, "")
    return out
