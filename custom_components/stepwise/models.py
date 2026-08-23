"""The core model. Three objects and their satellites (section 7).

Plain dataclasses with no Home Assistant imports, so the model can be exercised
in a test without a Home Assistant install.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from .const import (
    AWAITS_CONFIRM,
    AWAITS_NONE,
    CONFIDENCE_MEDIUM,
    LEARNED_FROM_USER,
    QUIRK_ACTIVE,
    RUN_ACTIVE,
    SCOPE_RUN,
    SOURCE_GENERATED,
    SUBJECT_ACTIVE,
)
from .util import iso, short_id, slugify


def _loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(slots=True)
class Subject:
    """The thing being worked on. An instance, never a category."""

    id: str
    kind: str
    label: str
    make: str | None = None
    model: str | None = None
    aliases: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = SUBJECT_ACTIVE
    replaced_by: str | None = None
    created_at: str = field(default_factory=iso)
    last_seen_at: str = field(default_factory=iso)

    @staticmethod
    def new(label: str, kind: str, **kwargs: Any) -> Subject:
        base = kwargs.pop("id", None) or slugify(
            " ".join(part for part in (kwargs.get("make"), kwargs.get("model")) if part) or label,
            fallback="subject",
        )
        return Subject(id=base, kind=kind, label=label, **kwargs)

    @property
    def spoken(self) -> str:
        """What this subject is called out loud."""
        return self.label or " ".join(part for part in (self.make, self.model) if part) or self.id

    @property
    def described(self) -> str:
        """Label plus make and model, when they are known and differ."""
        make_model = " ".join(part for part in (self.make, self.model) if part)
        if make_model and self.label and make_model.lower() not in self.label.lower():
            return f"{self.label} ({make_model})"
        return self.spoken

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["aliases"] = _dumps(self.aliases)
        row["attributes"] = _dumps(self.attributes)
        return row

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> Subject:
        return Subject(
            id=row["id"],
            kind=row["kind"],
            label=row["label"],
            make=row["make"],
            model=row["model"],
            aliases=_loads(row["aliases"], []),
            attributes=_loads(row["attributes"], {}),
            status=row["status"],
            replaced_by=row["replaced_by"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
        )


@dataclass(slots=True)
class Step:
    """One instruction. `speakable` is the ear's version (section 12)."""

    n: int
    instruction: str
    speakable: str | None = None
    ingredients: list[str] = field(default_factory=list)
    duration_s: int | None = None
    awaits: str = AWAITS_NONE
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def said(self) -> str:
        return self.speakable or self.instruction

    @property
    def waits_for_person(self) -> bool:
        return self.awaits == AWAITS_CONFIRM

    def to_row(self, procedure_id: str) -> dict[str, Any]:
        row = asdict(self)
        row["procedure_id"] = procedure_id
        row["ingredients"] = _dumps(self.ingredients)
        row["settings"] = _dumps(self.settings)
        return row

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> Step:
        return Step(
            n=row["n"],
            instruction=row["instruction"],
            speakable=row["speakable"],
            ingredients=_loads(row["ingredients"], []),
            duration_s=row["duration_s"],
            awaits=row["awaits"],
            settings=_loads(row["settings"], {}),
        )


@dataclass(slots=True)
class Procedure:
    """A template. Ordered steps, subject-agnostic where possible."""

    id: str
    title: str
    steps: list[Step] = field(default_factory=list)
    kind: str | None = None
    subject_kind: str | None = None
    yields: str | None = None
    prep_notes: str | None = None
    source: str = SOURCE_GENERATED
    created_at: str = field(default_factory=iso)
    updated_at: str = field(default_factory=iso)

    @staticmethod
    def new(title: str, steps: list[Step], **kwargs: Any) -> Procedure:
        return Procedure(
            id=kwargs.pop("id", None) or short_id(slugify(title, fallback="procedure")[:32]),
            title=title,
            steps=steps,
            **kwargs,
        )

    def step(self, n: int) -> Step | None:
        for step in self.steps:
            if step.n == n:
                return step
        return None

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("steps", None)
        return row

    @staticmethod
    def from_row(row: Mapping[str, Any], steps: list[Step] | None = None) -> Procedure:
        return Procedure(
            id=row["id"],
            title=row["title"],
            steps=steps or [],
            kind=row["kind"],
            subject_kind=row["subject_kind"],
            yields=row["yields"],
            prep_notes=row["prep_notes"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class Run:
    """One execution. The state machine, and the thing "where were we" reads."""

    id: str
    procedure_id: str
    reference: str
    subject_id: str | None = None
    status: str = RUN_ACTIVE
    current_step: int = 1
    started_at: str = field(default_factory=iso)
    updated_at: str = field(default_factory=iso)
    finished_at: str | None = None
    outcome: str | None = None
    user_id: str | None = None
    subject_loose: bool = False

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["subject_loose"] = 1 if self.subject_loose else 0
        return row

    @staticmethod
    def new(procedure_id: str, reference: str, **kwargs: Any) -> Run:
        return Run(
            id=kwargs.pop("id", None) or short_id("run"),
            procedure_id=procedure_id,
            reference=reference,
            **kwargs,
        )

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> Run:
        return Run(
            id=row["id"],
            procedure_id=row["procedure_id"],
            reference=row["reference"],
            subject_id=row["subject_id"],
            status=row["status"],
            current_step=row["current_step"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
            outcome=row["outcome"],
            user_id=row["user_id"],
            subject_loose=bool(row["subject_loose"]),
        )


@dataclass(slots=True)
class RunEvent:
    """The append-only spine. Everything else is derivable from these."""

    run_id: str
    kind: str
    at: str = field(default_factory=iso)
    step_n: int | None = None
    text: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("id", None)
        row["data"] = _dumps(self.data)
        return row

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> RunEvent:
        return RunEvent(
            id=row["id"],
            run_id=row["run_id"],
            kind=row["kind"],
            at=row["at"],
            step_n=row["step_n"],
            text=row["text"],
            data=_loads(row["data"], {}),
        )


@dataclass(slots=True)
class Amendment:
    """A change to a step. Scoped, never silently global (section 9)."""

    run_id: str
    step_n: int
    was: str
    now: str
    why: str | None = None
    scope: str = SCOPE_RUN
    at: str = field(default_factory=iso)
    id: str = field(default_factory=lambda: short_id("amd"))

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> Amendment:
        return Amendment(
            id=row["id"],
            run_id=row["run_id"],
            step_n=row["step_n"],
            was=row["was"],
            now=row["now"],
            why=row["why"],
            scope=row["scope"],
            at=row["at"],
        )


@dataclass(slots=True)
class Quirk:
    """A claim about one subject. Stated, never silently obeyed."""

    subject_id: str
    claim: str
    learned_from: str = LEARNED_FROM_USER
    confidence: str = CONFIDENCE_MEDIUM
    material: bool = True
    status: str = QUIRK_ACTIVE
    learned_at: str = field(default_factory=iso)
    last_confirmed_at: str | None = None
    last_stated_at: str | None = None
    times_applied: int = 0
    superseded_by: str | None = None
    id: str = field(default_factory=lambda: short_id("qrk"))

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["material"] = 1 if self.material else 0
        return row

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> Quirk:
        return Quirk(
            id=row["id"],
            subject_id=row["subject_id"],
            claim=row["claim"],
            learned_from=row["learned_from"],
            confidence=row["confidence"],
            material=bool(row["material"]),
            status=row["status"],
            learned_at=row["learned_at"],
            last_confirmed_at=row["last_confirmed_at"],
            last_stated_at=row["last_stated_at"],
            times_applied=row["times_applied"],
            superseded_by=row["superseded_by"],
        )
