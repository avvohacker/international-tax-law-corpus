"""Load the machine-readable defect catalogue.

`fixtures/known_defects.yaml` is the red half of the harness: it lists the
defects found by the 2026-09-27 audit, each with a probe that proves its absence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFECTS_PATH = ROOT / "fixtures" / "known_defects.yaml"
INVARIANTS_PATH = ROOT / "fixtures" / "invariants.yaml"

REQUIRED = ("id", "invariant", "status", "title", "check")
STATUSES = ("defect", "regression", "target")


@dataclass(frozen=True)
class Defect:
    id: str
    invariant: str
    status: str
    title: str
    check: str
    source: str = ""
    location: str = ""
    evidence: str = ""
    probe: str = ""
    probe_kind: str = "literal"
    targets: tuple[str, ...] = ()
    target: str = ""
    selector: str = ""
    expected: Any = None
    rule: str = ""
    pattern: str = ""
    why: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.invariant} · {self.id}"


def load_defects(path: Path | None = None) -> list[Defect]:
    raw = yaml.safe_load(Path(path or DEFECTS_PATH).read_text())
    out: list[Defect] = []
    for entry in raw:
        missing = [k for k in REQUIRED if k not in entry]
        if missing:
            raise ValueError(f"{entry.get('id', '<no id>')}: missing {missing}")
        known = set(Defect.__dataclass_fields__) - {"extra"}
        kwargs = {k: v for k, v in entry.items() if k in known}
        if "targets" in kwargs and kwargs["targets"]:
            kwargs["targets"] = tuple(kwargs["targets"])
        rest = {k: v for k, v in entry.items() if k not in known}
        out.append(Defect(**kwargs, extra=rest))
    return out


@dataclass(frozen=True)
class Invariant:
    id: str
    name: str
    statement: str
    scope: str
    enforced_by: tuple[str, ...]


def load_invariants(path: Path | None = None) -> list[Invariant]:
    raw = yaml.safe_load(Path(path or INVARIANTS_PATH).read_text())
    return [
        Invariant(
            id=e["id"],
            name=e["name"],
            statement=" ".join(str(e["statement"]).split()),
            scope=e["scope"],
            enforced_by=tuple(e.get("enforced_by") or ()),
        )
        for e in raw
    ]
