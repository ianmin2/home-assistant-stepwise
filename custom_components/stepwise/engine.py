"""The state machine, and everything the tools actually do.

One rule shapes this whole file: the system holds the state, not the person.
Every call is timestamped, every call resets the run's clock, and only the
calls that are meant to move the pointer move it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import speech
from .const import (
    ATTR_PROGRAMMES,
    AWAITS_CONFIRM,
    AWAITS_TIMER,
    COLD,
    CONFIDENCE_MEDIUM,
    CONFIRM_EXPLICIT,
    DEFAULT_ARCHIVE_KEEP_PER_SUBJECT,
    DEFAULT_COLD_HOURS,
    DEFAULT_HOT_MINUTES,
    EVENT_ADVANCED,
    EVENT_AMENDED,
    EVENT_ASKED,
    EVENT_CHALLENGED,
    EVENT_FINISHED,
    EVENT_NOTE,
    EVENT_QUIRK_CONFIRMED,
    EVENT_QUIRK_LEARNED,
    EVENT_QUIRK_RETRACTED,
    EVENT_QUIRK_STATED,
    EVENT_REPOSITIONED,
    EVENT_RUN_STARTED,
    EVENT_TIMER_STARTED,
    HOT,
    LEARNED_FROM_OBSERVED,
    LEARNED_FROM_USER,
    LEARNED_FROM_WEB,
    NAMING_ALWAYS_ASK,
    NAMING_NEVER_ASK,
    NAMING_PROPOSE,
    QUIRK_STALE_DAYS,
    RUN_ABANDONED,
    RUN_ACTIVE,
    RUN_DONE,
    SCOPE_PROCEDURE,
    SCOPE_RUN,
    SCOPE_SUBJECT,
    SETTING_KEYS,
    SOURCE_GENERATED,
    UNITS_METRIC,
    WARM,
)
from .models import Amendment, Procedure, Quirk, Run, RunEvent, Step, Subject
from .resolution import (
    ResolutionSession,
    confirm_hearing,
    odd_terms,
    resolve_subject,
    search_local,
    similarity,
    vocabulary_of,
)
from .speech import sentence
from .store import Store
from .util import (
    elapsed_seconds,
    iso,
    normalise,
    oxford,
    say_duration,
    say_elapsed,
    slugify,
    utcnow,
    words,
)


@dataclass(slots=True)
class Settings:
    """Configuration, not code. The thresholds are the whole point."""

    hot_minutes: int = DEFAULT_HOT_MINUTES
    cold_hours: int = DEFAULT_COLD_HOURS
    units: str = UNITS_METRIC
    confirmation_style: str = CONFIRM_EXPLICIT
    reference_naming: str = NAMING_PROPOSE
    archive_keep_per_subject: int = DEFAULT_ARCHIVE_KEEP_PER_SUBJECT

    @staticmethod
    def from_mapping(data: dict[str, Any] | None) -> Settings:
        data = dict(data or {})
        known = {
            "hot_minutes": int(data.get("hot_minutes", DEFAULT_HOT_MINUTES)),
            "cold_hours": int(data.get("cold_hours", DEFAULT_COLD_HOURS)),
            "units": data.get("units", UNITS_METRIC),
            "confirmation_style": data.get("confirmation_style", CONFIRM_EXPLICIT),
            "reference_naming": data.get("reference_naming", NAMING_PROPOSE),
            "archive_keep_per_subject": int(
                data.get("archive_keep_per_subject", DEFAULT_ARCHIVE_KEEP_PER_SUBJECT)
            ),
        }
        return Settings(**known)


@dataclass(slots=True)
class Reply:
    """One speakable string plus structured fields (section 8.1).

    The agent reads `speech`. It uses the fields only when asked for detail.
    """

    speech: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"speech": self.speech, **self.data}


# Scaffolding in a positioning phrase: everything except what it is about.
POSITION_NOISE = {
    "the", "a", "an", "my", "this", "that", "it", "im", "i", "am", "at", "in", "on",
    "to", "into", "of", "for", "with", "go", "goes", "going", "gone", "skip", "jump",
    "back", "bit", "part", "where", "when", "which", "one", "step", "next", "now",
    "please", "just", "we", "were", "was", "is", "are", "do", "did", "done", "you",
    "and", "then", "up", "down", "over", "again", "still", "not",
}

# Asking to be reminded of something already said, rather than asking the world.
_RECALL = re.compile(
    r"\b(what was|what were|what is the|what s the|whats the|how much|how many|"
    r"remind me|say again|tell me again)\b"
)

# Words that describe where a thing goes, rather than which thing it is.
ORDERING_WORDS = {
    "first", "last", "top", "bottom", "before", "after", "start", "end", "begin",
    "finish", "order", "instead", "opposite", "reverse", "swap", "machine", "mine",
    "takes", "needs", "goes", "put", "add",
}

# Words that mean "go back" rather than naming a step.
_BACKWARDS = re.compile(r"\b(back|previous|before|prior|last one|undo)\b")
_STEP_NUMBER = re.compile(r"\bstep\s+(\d+)\b")
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
# Markers that turn a claim into a contradiction of a stored one.
_OPPOSITES = (
    ("first", "last"), ("top", "bottom"), ("before", "after"),
    ("start", "end"), ("above", "below"), ("clockwise", "anticlockwise"),
    ("left", "right"), ("open", "closed"), ("on", "off"),
)
_NEGATIONS = ("no ", "not ", "never ", "isn't", "doesn't", "hasn't", "there's no", "without")


class Engine:
    """Everything the tools call. Synchronous; the Home Assistant layer defers it."""

    def __init__(self, store: Store, settings: Settings | None = None) -> None:
        self.store = store
        self.settings = settings or Settings()
        # Half-formed intents, in memory only. A resolution session is not a
        # fact and not a run: it either becomes a run or it expires.
        self._sessions: dict[str, ResolutionSession] = {}

    # Resolution sessions ------------------------------------------------
    def session(self, user_id: str | None = None) -> ResolutionSession | None:
        """What is half said, if anything still is."""
        key = user_id or ""
        held = self._sessions.get(key)
        if held is None:
            return None
        if held.expired():
            del self._sessions[key]
            return None
        return held

    def _session_for(self, spoken: str, user_id: str | None) -> ResolutionSession:
        key = user_id or ""
        held = self.session(user_id)
        if held is None:
            held = ResolutionSession(words=spoken)
            self._sessions[key] = held
        elif spoken and spoken not in held.words:
            held.words = f"{held.words} {spoken}".strip()
        return held

    def _end_session(self, user_id: str | None) -> None:
        """It became a run, so it stops being an intent."""
        self._sessions.pop(user_id or "", None)

    @property
    def wait_to_be_told(self) -> bool:
        """Whether a step says so when it is waiting on the person."""
        return self.settings.confirmation_style == CONFIRM_EXPLICIT

    # Clock -------------------------------------------------------------
    def stickiness(self, run: Run, now: datetime | None = None) -> tuple[str, float]:
        """Hot, warm or cold, purely by elapsed time. Rolling, not fixed."""
        since = elapsed_seconds(run.updated_at, now or utcnow()) or 0.0
        if since < self.settings.hot_minutes * 60:
            return HOT, since
        if since < self.settings.cold_hours * 3600:
            return WARM, since
        return COLD, since

    # Bookkeeping -------------------------------------------------------
    def _record(
        self,
        run: Run,
        kind: str,
        step_n: int | None = None,
        text: str | None = None,
        **data: Any,
    ) -> RunEvent:
        """Append to the spine and reset the clock. Any contact counts."""
        stamp = iso()
        event = self.store.add_event(
            RunEvent(run_id=run.id, kind=kind, at=stamp, step_n=step_n, text=text, data=data)
        )
        run.updated_at = stamp
        self.store.touch_run(run.id, stamp)
        if run.subject_id:
            self.store.touch_subject(run.subject_id, stamp)
        return event

    def _procedure(self, run: Run) -> Procedure:
        """The procedure as this run sees it: its own steps, not the template.

        A run snapshots the steps when it starts, so an amendment made halfway
        through a loaf changes that loaf and nothing else.
        """
        procedure = self._template(run)
        snapshot = self.store.get_run_steps(run.id)
        if snapshot:
            procedure.steps = snapshot
        return procedure

    def _template(self, run: Run) -> Procedure:
        """The shared procedure, untouched by any run."""
        procedure = self.store.get_procedure(run.procedure_id)
        if procedure is None:  # pragma: no cover - only on a hand-edited database
            raise LookupError(f"procedure {run.procedure_id} is missing")
        return procedure

    def _current_step(self, run: Run, procedure: Procedure | None = None) -> Step | None:
        procedure = procedure or self._procedure(run)
        return procedure.step(run.current_step)

    def current_run(self, user_id: str | None = None, run_id: str | None = None) -> Run | None:
        """The run in play. Most recently touched wins; several may be live."""
        if run_id:
            return self.store.get_run(run_id)
        open_runs = self.store.open_runs(user_id=user_id)
        return open_runs[0] if open_runs else None

    # Resolution --------------------------------------------------------
    def resolve_intent(self, spoken: str, user_id: str | None = None) -> Reply:
        """The requirements conversation (section 4). Local library first."""
        subjects = self.store.list_subjects()
        procedures = self.store.list_procedures()
        runs = self.store.recent_runs(limit=20)
        vocabulary = vocabulary_of(subjects, procedures)
        session = self._session_for(spoken, user_id)

        heard = odd_terms(spoken, vocabulary)
        if heard:
            term, candidates = heard[0]
            question = session.ask(confirm_hearing(term, candidates))
            return Reply(
                question,
                {
                    "status": "confirm_hearing",
                    "heard": term,
                    "candidates": [name for name, _ in candidates],
                },
            )

        local = search_local(spoken, procedures, runs)
        if local:
            best = local[0]
            if best.kind == "run":
                run = self.store.get_run(best.id)
                if run and run.status in (RUN_ACTIVE,):
                    return self.run_where(user_id=user_id, run_id=run.id)
            said = (
                f"You've done {best.title} before. Same again, or start fresh?"
                if best.kind == "procedure"
                else f"There's {best.title} on file."
            )
            return Reply(
                said,
                {
                    "status": "found_local",
                    "matches": [
                        {"kind": match.kind, "id": match.id, "title": match.title}
                        for match in local[:3]
                    ],
                },
            )

        subject = resolve_subject(spoken, subjects)
        session.target = spoken.strip()
        if subject.resolved and subject.subject:
            session.subject_id = subject.subject.id
            session.loose = subject.loose
        elif subject.question:
            session.ask(subject.question)
        return Reply(
            "",
            {
                "status": "needs_planning",
                "target": spoken.strip(),
                "subject": subject.as_dict(),
                "asked_already": list(session.asked),
                "known_subject_kinds": sorted({item.kind for item in subjects}),
                "ask_only_what_changes_the_steps": True,
            },
        )

    def subject_resolve(self, spoken: str, user_id: str | None = None) -> Reply:
        """Turn "my bike" into one subject, or ask which."""
        resolution = resolve_subject(spoken, self.store.list_subjects())
        session = self._session_for(spoken, user_id)
        if resolution.resolved and resolution.subject:
            self.store.touch_subject(resolution.subject.id)
            # Remembered so that a quirk about a loosely matched thing is
            # re-confirmed rather than asserted (section 9, rule 2).
            session.subject_id = resolution.subject.id
            session.loose = resolution.loose
            return Reply(resolution.subject.described, resolution.as_dict())
        if resolution.question:
            session.ask(resolution.question)
        return Reply(resolution.question or "", resolution.as_dict())

    def subject_save(
        self,
        label: str,
        kind: str,
        make: str | None = None,
        model: str | None = None,
        aliases: Sequence[str] | None = None,
        attributes: dict[str, Any] | None = None,
        subject_id: str | None = None,
        changed: bool = False,
    ) -> Reply:
        """Create or amend one subject. A fork, when the user says it differs."""
        existing = self.store.get_subject(subject_id) if subject_id else None
        if existing and not changed:
            # A contradiction is a fork, not an update (section 7). Overwriting
            # here is how one bicycle's history quietly becomes another's.
            differs = [
                (field_name, was, now)
                for field_name, was, now in (
                    ("make", existing.make, make),
                    ("model", existing.model, model),
                )
                if was and now and normalise(was) != normalise(now)
            ]
            if differs:
                return Reply(
                    f"That doesn't match what I have for {existing.spoken}. "
                    f"Different one, or has this one changed?",
                    {
                        "status": "fork_or_amend",
                        "subject_id": existing.id,
                        "differs": [
                            {"field": name, "stored": was, "said": now}
                            for name, was, now in differs
                        ],
                        "if_different": "call subject_save again without subject_id",
                        "if_changed": "call subject_save again with changed true",
                    },
                )

        if existing:
            existing.label = label or existing.label
            existing.kind = kind or existing.kind
            existing.make = make if make is not None else existing.make
            existing.model = model if model is not None else existing.model
            if aliases is not None:
                existing.aliases = list(aliases)
            if attributes:
                existing.attributes.update(attributes)
            existing.last_seen_at = iso()
            self.store.save_subject(existing)
            return Reply(f"Noted, {existing.described}.", {"subject_id": existing.id})

        base = slugify(" ".join(part for part in (make, model) if part) or label, "subject")
        subject = Subject(
            id=self.store.unique_subject_id(base),
            kind=kind,
            label=label,
            make=make,
            model=model,
            aliases=list(aliases or []),
            attributes=dict(attributes or {}),
        )
        self.store.save_subject(subject)
        return Reply(f"Right, {subject.described}.", {"subject_id": subject.id, "created": True})

    # Planning ----------------------------------------------------------
    def procedure_plan(
        self,
        title: str,
        steps: Sequence[dict[str, Any]],
        subject_id: str | None = None,
        subject_kind: str | None = None,
        yields: str | None = None,
        prep_notes: str | None = None,
        source: str = SOURCE_GENERATED,
    ) -> Reply:
        """Compose or fetch the steps, store, name it. Does not start it."""
        if not steps:
            return Reply("I need the steps before I can plan anything.", {"status": "no_steps"})

        subject = self.store.get_subject(subject_id) if subject_id else None
        kind = subject_kind or (subject.kind if subject else None)

        built: list[Step] = []
        for index, raw in enumerate(steps, start=1):
            instruction = str(raw.get("instruction", "")).strip()
            if not instruction:
                continue
            ingredients = [str(item) for item in raw.get("ingredients", []) or []]
            spoken = raw.get("speakable")
            if not spoken:
                spoken = speech.quantity_first(instruction, self.settings.units)
            duration = raw.get("duration_s")
            awaits = raw.get("awaits") or (AWAITS_TIMER if duration else AWAITS_CONFIRM)
            built.append(
                Step(
                    n=int(raw.get("n", index)),
                    instruction=instruction,
                    speakable=spoken,
                    ingredients=ingredients,
                    duration_s=int(duration) if duration else None,
                    awaits=awaits,
                    settings=dict(raw.get("settings") or {}),
                )
            )

        existing = self.store.find_procedure(title, kind)
        procedure = Procedure(
            id=existing.id if existing else Procedure.new(title, []).id,
            title=title.strip(),
            steps=built,
            kind=kind,
            subject_kind=kind,
            yields=yields,
            prep_notes=prep_notes,
            source=source,
            created_at=existing.created_at if existing else iso(),
        )
        self.store.save_procedure(procedure)

        proposed = self.propose_reference(procedure, subject)
        counted = f"{procedure.total_steps} steps for {procedure.title}."
        if self.settings.reference_naming == NAMING_NEVER_ASK:
            said = counted
        elif self.settings.reference_naming == NAMING_ALWAYS_ASK:
            said = f"{counted} What shall I call it?"
        else:
            said = f"{counted} Shall I call it {proposed}?"
        return Reply(
            said,
            {
                "procedure_id": procedure.id,
                "title": procedure.title,
                "steps": procedure.total_steps,
                "proposed_reference": (
                    None if self.settings.reference_naming == NAMING_ALWAYS_ASK else proposed
                ),
                "must_ask_for_a_name": self.settings.reference_naming == NAMING_ALWAYS_ASK,
                "replaced_existing": bool(existing),
            },
        )

    def propose_reference(self, procedure: Procedure, subject: Subject | None = None) -> str:
        """A name a person would use, never "run 4a2f"."""
        title = procedure.title.strip()
        lowered = title[0].lower() + title[1:] if title[:1].isupper() else title
        return f"the {lowered}" if not lowered.startswith("the ") else lowered

    # The run -----------------------------------------------------------
    def run_start(
        self,
        procedure_id: str,
        reference: str | None = None,
        subject_id: str | None = None,
        user_id: str | None = None,
    ) -> Reply:
        """Begin. Returns step one and confirms the reference."""
        procedure = self.store.get_procedure(procedure_id)
        if procedure is None:
            return Reply("I can't find that procedure.", {"status": "unknown_procedure"})
        if not procedure.steps:
            return Reply("That procedure has no steps yet.", {"status": "no_steps"})

        subject = self.store.get_subject(subject_id) if subject_id else None
        name = (reference or "").strip() or self.propose_reference(procedure, subject)
        session = self.session(user_id)
        loosely_matched = bool(
            subject and session and session.subject_id == subject.id and session.loose
        )
        run = Run.new(
            procedure_id=procedure.id,
            reference=name,
            subject_id=subject.id if subject else None,
            user_id=user_id,
            current_step=procedure.steps[0].n,
            subject_loose=loosely_matched,
        )
        self.store.save_run(run)
        self.store.save_run_steps(run.id, procedure.steps)
        self._record(run, EVENT_RUN_STARTED, step_n=run.current_step, text=name)
        self._end_session(user_id)  # the intent became a run

        first = procedure.step(run.current_step)
        assert first is not None
        lines: list[str] = []
        stated = self.quirks_to_state(run, first, subject)
        lines.extend(item["speech"] for item in stated)
        lines.append(speech.say_step(first, self.settings.units, prompt=self.wait_to_be_told))
        return Reply(
            " ".join(part for part in lines if part),
            {
                "run_id": run.id,
                "reference": run.reference,
                "step": self._step_data(first),
                "total_steps": procedure.total_steps,
                "subject": subject.described if subject else None,
                "quirks_stated": stated,
            },
        )

    def run_where(self, user_id: str | None = None, run_id: str | None = None) -> Reply:
        """Where am I, in which thing, and how long since. No arguments, by design."""
        open_runs = self.store.open_runs(user_id=user_id)
        if run_id:
            run = self.store.get_run(run_id)
            open_runs = [run] if run else []
        if not open_runs:
            return Reply("Nothing on the go.", {"status": "nothing_active", "runs": []})

        run = open_runs[0]
        state, since = self.stickiness(run)
        procedure = self._procedure(run)
        step = procedure.step(run.current_step)
        summary = (
            f"you're on step {step.n} of {procedure.total_steps}, "
            f"{speech.say_step(step, self.settings.units, prompt=self.wait_to_be_told)}"
            if step
            else "you're at the end."
        )

        if len(open_runs) > 1 and state != HOT:
            # Several live runs and none of them assumed: name them, offer.
            names = [other.reference for other in open_runs]
            said = f"Two things on the go: {oxford(names)}. Which one?"
            return Reply(
                said,
                {
                    "status": "several_live",
                    "runs": [self._run_data(other) for other in open_runs],
                },
            )

        said = sentence(speech.opener(state, run.reference, since, summary))
        if state == COLD and step:
            said = (
                f"{speech.no_shame(run.reference, since)} "
                f"You were on step {step.n} of {procedure.total_steps}, "
                f"{speech.say_step(step, self.settings.units)}. Carry on?"
            )
        self.store.touch_run(run.id)
        return Reply(
            said,
            {
                "status": "active",
                "run_id": run.id,
                "reference": run.reference,
                "state": state,
                "since_seconds": round(since),
                "since": say_elapsed(since),
                "step": self._step_data(step) if step else None,
                "total_steps": procedure.total_steps,
                "other_runs": [self._run_data(other) for other in open_runs[1:]],
            },
        )

    def run_advance(
        self, note: str | None = None, run_id: str | None = None, user_id: str | None = None
    ) -> Reply:
        """Complete the current step, return the next. The only tool that moves on."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})

        procedure = self._procedure(run)
        done = procedure.step(run.current_step)
        state, _since = self.stickiness(run)  # as of arrival, before the clock resets
        self._record(run, EVENT_ADVANCED, step_n=run.current_step, text=note)

        following = [step for step in procedure.steps if step.n > run.current_step]
        if not following:
            return self._close(run, procedure, outcome=None, status=RUN_DONE, last_step=done)

        nxt = following[0]
        run.current_step = nxt.n
        self.store.save_run(run)

        subject = self.store.get_subject(run.subject_id) if run.subject_id else None
        hint = self.subject_hint(nxt, subject)
        said = speech.say_step(nxt, self.settings.units)
        stated = self.quirks_to_state(run, nxt, subject)
        if stated:
            said = " ".join([*(item["speech"] for item in stated), said])
        if state != HOT:
            said = speech.with_reference(run.reference, said)
        if hint["speech"]:
            said = f"{said} {hint['speech']}"
        timer_seconds = nxt.duration_s or hint["duration_s"]
        if nxt.awaits == AWAITS_TIMER and timer_seconds:
            because = "the programme length" if hint["name"] else "the step length"
            said = f"{said} {speech.timer_offer(timer_seconds, because)}"

        return Reply(
            said,
            {
                "status": "advanced",
                "run_id": run.id,
                "reference": run.reference,
                "completed_step": done.n if done else None,
                "step": self._step_data(nxt),
                "steps_left": len(following) - 1,
                "total_steps": procedure.total_steps,
                "quirks_stated": stated,
                "timer_offer_seconds": timer_seconds if nxt.awaits == AWAITS_TIMER else None,
                "subject_setting": hint["name"],
            },
        )

    def run_goto(
        self, description: str, run_id: str | None = None, user_id: str | None = None
    ) -> Reply:
        """Reposition by description. Always reports where it landed."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        procedure = self._procedure(run)
        target, confidence, candidates = self._locate(description, procedure, run.current_step)

        if target is None:
            options = [f"step {step.n}, {step.said}" for step in candidates[:3]]
            said = (
                f"I'm not sure which you mean. {oxford(options, 'or')}?"
                if options
                else "I can't find that step."
            )
            return Reply(
                said,
                {
                    "status": "unsure",
                    "run_id": run.id,
                    "candidates": [self._step_data(step) for step in candidates[:3]],
                },
            )

        was = run.current_step
        run.current_step = target.n
        self.store.save_run(run)
        self._record(
            run,
            EVENT_REPOSITIONED,
            step_n=target.n,
            text=description,
            was=was,
            confidence=confidence,
        )
        return Reply(
            speech.landed(target, self.settings.units),
            {
                "status": "repositioned",
                "run_id": run.id,
                "reference": run.reference,
                "was_step": was,
                "step": self._step_data(target),
                "total_steps": procedure.total_steps,
                "confidence": round(confidence, 2),
            },
        )

    def run_ask(
        self, question: str, run_id: str | None = None, user_id: str | None = None
    ) -> Reply:
        """An aside. Answers from procedure, notes or clock. Moves nothing."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        procedure = self._procedure(run)
        step = procedure.step(run.current_step)
        self._record(run, EVENT_ASKED, step_n=run.current_step, text=question)

        answer, source = self._answer(question, run, procedure, step)
        remaining_steps = [item for item in procedure.steps if item.n > run.current_step]
        notes = [
            {"text": event.text, "at": event.at, "step": event.step_n}
            for event in self.store.events(run.id, [EVENT_NOTE])
        ]
        return Reply(
            answer or "",
            {
                "status": "answered" if answer else "needs_answer",
                "answered_from": source,
                "run_id": run.id,
                "reference": run.reference,
                "pointer_unchanged": True,
                "step": self._step_data(step) if step else None,
                "remaining": [self._step_data(item) for item in remaining_steps],
                "notes": notes,
                "started": say_elapsed(elapsed_seconds(run.started_at)),
                "on_this_step": say_elapsed(self._on_step_seconds(run)),
                "ingredients": sorted(
                    {item for one in procedure.steps for item in one.ingredients}
                ),
            },
        )

    def run_note(
        self, text: str, run_id: str | None = None, user_id: str | None = None
    ) -> Reply:
        """An observation, against the current step and time. Nothing moves."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        event = self._record(run, EVENT_NOTE, step_n=run.current_step, text=text)
        return Reply(
            "Noted.",
            {
                "status": "noted",
                "run_id": run.id,
                "reference": run.reference,
                "step": run.current_step,
                "at": event.at,
                "pointer_unchanged": True,
            },
        )

    def run_finish(
        self,
        outcome: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        abandoned: bool = False,
    ) -> Reply:
        """Close, archive, optionally record how it went."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        procedure = self._procedure(run)
        return self._close(
            run,
            procedure,
            outcome=outcome,
            status=RUN_ABANDONED if abandoned else RUN_DONE,
            last_step=procedure.step(run.current_step),
        )

    def _close(
        self,
        run: Run,
        procedure: Procedure,
        outcome: str | None,
        status: str,
        last_step: Step | None,
    ) -> Reply:
        run.status = status
        run.finished_at = iso()
        run.outcome = outcome
        self.store.save_run(run)
        self._record(run, EVENT_FINISHED, step_n=run.current_step, text=outcome, status=status)
        self.store.prune_runs(self.settings.archive_keep_per_subject)
        said = (
            f"That's {run.reference} done."
            if status == RUN_DONE
            else f"Left {run.reference} there."
        )
        return Reply(
            said,
            {
                "status": status,
                "run_id": run.id,
                "reference": run.reference,
                "outcome": outcome,
                "steps_completed": run.current_step,
                "total_steps": procedure.total_steps,
                "took": say_elapsed(elapsed_seconds(run.started_at)),
            },
        )

    # Corrections -------------------------------------------------------
    def run_challenge(
        self, claim: str, run_id: str | None = None, user_id: str | None = None
    ) -> Reply:
        """The user disputes a step (section 9). Decides, never overrules silently."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        procedure = self._procedure(run)
        self._record(run, EVENT_CHALLENGED, step_n=run.current_step, text=claim)

        subject = self.store.get_subject(run.subject_id) if run.subject_id else None
        if subject is None:
            return Reply(
                "Which one is this, so I note it against the right thing?",
                {
                    "status": "needs_subject",
                    "run_id": run.id,
                    "claim": claim,
                    "candidates": [
                        {"id": item.id, "label": item.described}
                        for item in self.store.list_subjects()
                    ],
                },
            )

        if not (subject.make and subject.model):
            # Asked for, not assumed, and only when it changes the instructions.
            return Reply(
                f"What make and model is {subject.spoken}? It changes the order.",
                {
                    "status": "needs_make_model",
                    "run_id": run.id,
                    "subject_id": subject.id,
                    "claim": claim,
                },
            )

        affected = self._steps_touching(claim, procedure, run.current_step)
        known = self.store.quirks(subject.id)
        agreeing = [quirk for quirk in known if similarity(quirk.claim, claim) >= 0.7]
        conflicting = [quirk for quirk in known if self._contradicts(quirk.claim, claim)]

        if agreeing:
            quirk = agreeing[0]
            self.store.quirk_stated(quirk.id)
            self.store.confirm_quirk(quirk.id)
            return Reply(
                "You're right, and I have that noted. Reordering.",
                {
                    "status": "agrees",
                    "run_id": run.id,
                    "subject_id": subject.id,
                    "quirk_id": quirk.id,
                    "claim": claim,
                    "affected_steps": [self._step_data(step) for step in affected],
                },
            )

        if conflicting:
            quirk = conflicting[0]
            model = " ".join(part for part in (subject.make, subject.model) if part)
            return Reply(
                f"My note says the opposite for the {model}. Shall I re-check?",
                {
                    "status": "conflicts",
                    "run_id": run.id,
                    "subject_id": subject.id,
                    "quirk_id": quirk.id,
                    "stored_claim": quirk.claim,
                    "claim": claim,
                    "search_query": f"{model} {claim}",
                    "affected_steps": [self._step_data(step) for step in affected],
                },
            )

        model = " ".join(part for part in (subject.make, subject.model) if part)
        return Reply(
            "",
            {
                "status": "unknown",
                "run_id": run.id,
                "subject_id": subject.id,
                "claim": claim,
                "search_query": f"{model} {claim}",
                "search_scope": {"make": subject.make, "model": subject.model},
                "affected_steps": [self._step_data(step) for step in affected],
                "if_confirmed": "run_amend with scope subject, learned_from web",
                "if_unclear": "defer to the user, learned_from user",
            },
        )

    def run_amend(
        self,
        step_n: int = 0,
        change: str = "",
        why: str | None = None,
        scope: str = SCOPE_RUN,
        run_id: str | None = None,
        user_id: str | None = None,
        learned_from: str = LEARNED_FROM_USER,
        confidence: str = CONFIDENCE_MEDIUM,
        also_steps: Sequence[int] | None = None,
        reorder: Sequence[int] | None = None,
    ) -> Reply:
        """Change a step in this run, optionally the subject's quirks or the procedure."""
        run = self.current_run(user_id, run_id)
        if run is None:
            return Reply("Nothing on the go.", {"status": "nothing_active"})
        procedure = self._procedure(run)
        sources = self.store.run_step_sources(run.id)
        amended: list[dict[str, Any]] = []

        if reorder:
            # Reordering a load order changes this run, and this subject's
            # quirks if asked, never the procedure other people follow.
            by_number = {step.n: step for step in procedure.steps}
            wanted = [number for number in reorder if number in by_number]
            wanted += [step.n for step in procedure.steps if step.n not in wanted]
            was_order = [step.n for step in procedure.steps]
            moved: list[Step] = []
            new_sources: dict[int, int | None] = {}
            for position, number in enumerate(wanted, start=1):
                step = by_number[number]
                new_sources[position] = sources.get(number, number)
                moved.append(
                    Step(
                        n=position,
                        instruction=step.instruction,
                        speakable=step.speakable,
                        ingredients=list(step.ingredients),
                        duration_s=step.duration_s,
                        awaits=step.awaits,
                        settings=dict(step.settings),
                    )
                )
            self.store.save_run_steps(run.id, moved)
            for position, step in enumerate(moved, start=1):
                self.store.save_run_step(run.id, step, source_n=new_sources.get(position))
            # The pointer follows the step the person is actually on.
            if run.current_step in by_number:
                run.current_step = wanted.index(run.current_step) + 1
            self.store.save_run(run)
            self.store.add_amendment(
                Amendment(
                    run_id=run.id,
                    step_n=0,
                    was=",".join(str(number) for number in was_order),
                    now=",".join(str(number) for number in wanted),
                    why=why or change,
                    scope=scope,
                )
            )
            amended.append({"reordered_to": wanted})
            procedure = self._procedure(run)

        if change:
            for number in [step_n, *(also_steps or [])]:
                step = procedure.step(number)
                if step is None:
                    continue
                was = step.instruction
                if number != step_n:
                    continue
                step.instruction = change
                step.speakable = speech.quantity_first(change, self.settings.units)
                self.store.save_run_step(run.id, step, source_n=sources.get(number, number))
                self.store.add_amendment(
                    Amendment(
                        run_id=run.id,
                        step_n=number,
                        was=was,
                        now=step.instruction,
                        why=why,
                        scope=scope,
                    )
                )
                amended.append({"step": number, "was": was, "now": step.instruction})
                if scope == SCOPE_PROCEDURE:
                    # Only when the user says the template itself was wrong.
                    template = self._template(run)
                    source = sources.get(number, number)
                    original = template.step(source) if source else None
                    if original is not None:
                        original.instruction = step.instruction
                        original.speakable = step.speakable
                        self.store.save_step(template.id, original)

        self._record(run, EVENT_AMENDED, step_n=step_n, text=change or why, scope=scope, why=why)

        quirk_id = None
        if scope in (SCOPE_SUBJECT, SCOPE_PROCEDURE) and run.subject_id:
            quirk = self.store.add_quirk(
                Quirk(
                    subject_id=run.subject_id,
                    claim=why or change,
                    learned_from=learned_from,
                    confidence=confidence,
                    material=True,
                    last_confirmed_at=iso(),
                )
            )
            quirk_id = quirk.id
            self._record(
                run, EVENT_QUIRK_LEARNED, step_n=step_n, text=quirk.claim, quirk_id=quirk.id
            )

        procedure = self._procedure(run)
        current = procedure.step(run.current_step)
        if reorder:
            said = (
                f"Reordered. {speech.landed(current, self.settings.units)}"
                if current
                else "Reordered."
            )
        elif current and current.n == step_n:
            said = f"Changed. {speech.say_step(current, self.settings.units)}"
        else:
            said = f"Changed step {step_n}."
        return Reply(
            said,
            {
                "status": "amended",
                "run_id": run.id,
                "scope": scope,
                "amended": amended,
                "quirk_id": quirk_id,
                "step": self._step_data(current) if current else None,
            },
        )

    # Subject-aware settings ---------------------------------------------
    def subject_hint(self, step: Step | None, subject: Subject | None) -> dict[str, Any]:
        """What this one calls the setting, and how long it takes.

        A subject that knows its own programmes turns "programme four" into
        "programme four, the wholemeal one" and supplies the length for a timer
        offer when the step itself has no duration. An unknown machine simply
        gets nothing extra, which is the point of a generic fallback.
        """
        empty: dict[str, Any] = {"name": None, "duration_s": None, "speech": ""}
        if step is None or subject is None or not step.settings:
            return empty
        programmes = subject.attributes.get(ATTR_PROGRAMMES)
        if not programmes:
            return empty

        chosen = next(
            (step.settings[key] for key in SETTING_KEYS if key in step.settings), None
        )
        if chosen is None:
            return empty

        entry: Any = None
        if isinstance(programmes, dict):
            entry = programmes.get(str(chosen)) or programmes.get(chosen)
        elif isinstance(programmes, list):
            if isinstance(chosen, int) and 1 <= chosen <= len(programmes):
                entry = programmes[chosen - 1]
            else:
                entry = next(
                    (
                        item
                        for item in programmes
                        if normalise(str(item)) == normalise(str(chosen))
                    ),
                    None,
                )
        if entry is None:
            return empty

        name = entry.get("name") if isinstance(entry, dict) else str(entry)
        duration = entry.get("duration_s") if isinstance(entry, dict) else None
        said = f"That's the {name} one on yours." if name else ""
        return {
            "name": name,
            "duration_s": int(duration) if duration else None,
            "speech": said,
        }

    # Timers --------------------------------------------------------------
    def run_timer(
        self,
        seconds: int,
        name: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
    ) -> Reply:
        """Record that a timer was asked for. Home Assistant runs the timer.

        Offered, never imposed: this is called after the person has agreed to
        one, not instead of asking.
        """
        run = self.current_run(user_id, run_id)
        label = (name or (run.reference if run else "") or "timer").strip()
        if run is not None:
            self._record(
                run, EVENT_TIMER_STARTED, step_n=run.current_step, text=label, seconds=int(seconds)
            )
        return Reply(
            f"Timer set for {say_duration(seconds)}.",
            {
                "status": "timer_recorded",
                "run_id": run.id if run else None,
                "reference": run.reference if run else None,
                "name": label,
                "seconds": int(seconds),
                "pointer_unchanged": True,
            },
        )

    # Quirks ------------------------------------------------------------
    def quirks_to_state(
        self, run: Run, step: Step | None, subject: Subject | None = None
    ) -> list[dict[str, Any]]:
        """Say it, do not assume it (section 9, rule 1).

        Returns the quirks that bear on this step, each with the exact words to
        say and whether they need re-confirming rather than merely stating.
        """
        if subject is None and run.subject_id:
            subject = self.store.get_subject(run.subject_id)
        if subject is None or step is None:
            return []

        stated: list[dict[str, Any]] = []
        for quirk in self.store.quirks(subject.id):
            if not quirk.material or not self._bears_on(quirk.claim, step):
                continue
            reconfirm, why = self._needs_reconfirm(quirk, run)
            age = say_elapsed(elapsed_seconds(quirk.last_confirmed_at or quirk.learned_at))
            said = (
                speech.reconfirm_quirk(quirk.claim, quirk.learned_from, age)
                if reconfirm
                else speech.state_quirk(quirk.claim)
            )
            self._record(
                run, EVENT_QUIRK_STATED, step_n=step.n, text=quirk.claim, quirk_id=quirk.id
            )
            self.store.quirk_stated(quirk.id)
            stated.append(
                {
                    "quirk_id": quirk.id,
                    "claim": quirk.claim,
                    "speech": said,
                    "reconfirm": reconfirm,
                    "because": why,
                    "learned_from": quirk.learned_from,
                }
            )
        return stated

    def _needs_reconfirm(self, quirk: Quirk, run: Run | None = None) -> tuple[bool, str | None]:
        """Re-confirm when the ground may have moved (section 9, rule 2).

        Four things move the ground, and any of them is enough. Otherwise the
        quirk is stated and the procedure carries on, because interrogating
        somebody about a bread machine they have owned for six years is the
        failure this rule exists to avoid.
        """
        if run is not None and run.subject_loose:
            return True, "there is more than one of these on file"
        if quirk.learned_from in (LEARNED_FROM_WEB, LEARNED_FROM_OBSERVED) and not (
            quirk.last_confirmed_at
        ):
            return True, "learned from the web, never confirmed by you"
        if run is not None and self._contradicted_during(run, quirk.claim):
            return True, "you have said something different this session"
        age = elapsed_seconds(quirk.last_confirmed_at or quirk.learned_at)
        if quirk.material and age and age > QUIRK_STALE_DAYS * 86400:
            return True, "material and not confirmed in a long time"
        return False, None

    def _contradicted_during(self, run: Run, claim: str) -> bool:
        """Has anything said during this run disagreed with this quirk?"""
        for event in self.store.events(run.id, [EVENT_CHALLENGED]):
            if event.text and self._contradicts(claim, event.text):
                return True
        return False

    def quirk_confirm(
        self,
        quirk_id: str,
        still_right: bool = True,
        run_id: str | None = None,
        user_id: str | None = None,
    ) -> Reply:
        """The person answers a re-confirmation. Only they can settle it."""
        quirk = self.store.get_quirk(quirk_id)
        if quirk is None:
            return Reply("I can't find that note.", {"status": "unknown_quirk"})
        run = self.current_run(user_id, run_id)

        if still_right:
            self.store.confirm_quirk(quirk.id)
            if run is not None:
                self._record(
                    run,
                    EVENT_QUIRK_CONFIRMED,
                    step_n=run.current_step,
                    text=quirk.claim,
                    quirk_id=quirk.id,
                )
            return Reply(
                "Right, I'll keep that.",
                {"status": "confirmed", "quirk_id": quirk.id, "claim": quirk.claim},
            )

        self.store.retract_quirk(quirk.id)
        if run is not None:
            self._record(
                run,
                EVENT_QUIRK_RETRACTED,
                step_n=run.current_step,
                text=quirk.claim,
                quirk_id=quirk.id,
            )
        return Reply(
            "Forgotten. What's the case now?",
            {
                "status": "retracted",
                "quirk_id": quirk.id,
                "claim": quirk.claim,
                "then": "run_amend with scope subject, learned_from user",
            },
        )

    # Helpers -----------------------------------------------------------
    def _on_step_seconds(self, run: Run) -> float | None:
        arrivals = [EVENT_ADVANCED, EVENT_REPOSITIONED, EVENT_RUN_STARTED]
        for event in reversed(self.store.events(run.id, arrivals)):
            if event.step_n == run.current_step or event.kind != EVENT_ADVANCED:
                return elapsed_seconds(event.at)
        return elapsed_seconds(run.started_at)

    def _step_data(self, step: Step | None) -> dict[str, Any] | None:
        if step is None:
            return None
        return {
            "n": step.n,
            "instruction": step.instruction,
            "speakable": speech.say_step(step, self.settings.units),
            "ingredients": step.ingredients,
            "duration_s": step.duration_s,
            "awaits": step.awaits,
            "settings": step.settings,
        }

    def run_summary(self, run: Run) -> dict[str, Any]:
        """One live run, as the prompt and the options panel describe it."""
        return self._run_data(run)

    def _run_data(self, run: Run) -> dict[str, Any]:
        state, since = self.stickiness(run)
        return {
            "run_id": run.id,
            "reference": run.reference,
            "state": state,
            "since": say_elapsed(since),
            "step": run.current_step,
            "status": run.status,
        }

    def _locate(
        self, description: str, procedure: Procedure, current: int
    ) -> tuple[Step | None, float, list[Step]]:
        """Match a description against the step list. Never a silent jump."""
        said = normalise(description)
        # Words the procedure itself uses. Anything else cannot discriminate.
        discriminating = {
            word
            for step in procedure.steps
            for word in words(" ".join([step.instruction, step.said, *step.ingredients]))
        } - POSITION_NOISE

        number = _STEP_NUMBER.search(said)
        if number:
            step = procedure.step(int(number.group(1)))
            if step:
                return step, 1.0, []

        for word, index in _ORDINALS.items():
            if re.search(rf"\b{word}\b", said):
                # "the second prove": the index-th step that matches the rest.
                rest = re.sub(rf"\b{word}\b", " ", said).strip()
                matches = [
                    step
                    for step in procedure.steps
                    if self._describes(rest, step, discriminating) >= 0.45
                ]
                if len(matches) >= index:
                    return matches[index - 1], 0.8, []

        # What the phrase is about beats how it is phrased: "go back, I've not
        # done the salt yet" is about the salt, not about going back one.
        scored = sorted(
            ((self._describes(said, step, discriminating), step) for step in procedure.steps),
            key=lambda pair: -pair[0],
        )
        if scored and scored[0][0] >= 0.55:
            best_score, best_step = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if best_score - runner_up >= 0.08:
                return best_step, best_score, []

        if _BACKWARDS.search(said):
            earlier = [step for step in procedure.steps if step.n < current]
            if earlier:
                return earlier[-1], 0.9, []

        near = [step for score, step in scored if score > 0.3][:3]
        return None, 0.0, near or list(procedure.steps[:3])

    @staticmethod
    def _describes(said: str, step: Step, discriminating: set[str] | None = None) -> float:
        """How well a description picks out this step.

        Only words that appear somewhere in the procedure count as evidence.
        "Go back, I've not done the salt yet" is about the salt: "back" and
        "yet" say nothing about which step, so they are not held against it.
        """
        haystack = " ".join([step.instruction, step.said, *step.ingredients])
        step_words = set(words(haystack))
        said_words = set(words(said)) - POSITION_NOISE
        if discriminating is not None:
            said_words = {word for word in said_words if word in discriminating}
        score = similarity(said, haystack)
        if said_words:
            hits = sum(
                1
                for word in said_words
                if word in step_words
                or any(similarity(word, other) >= 0.85 for other in step_words)
            )
            score = max(score, (hits / len(said_words)) * 0.95)
        return score

    def _steps_touching(self, claim: str, procedure: Procedure, current: int) -> list[Step]:
        """Amend the remaining steps, not just the current one (section 9).

        What a claim is about is the thing it names — the yeast and the salt —
        not the ordering words it uses to say where they go.
        """
        terms = set(words(claim)) - POSITION_NOISE - ORDERING_WORDS
        ahead = [step for step in procedure.steps if step.n >= current]

        named = [
            step
            for step in ahead
            if terms & {word for item in step.ingredients for word in words(item)}
        ]
        if named:
            return named

        return [
            step
            for step in ahead
            if terms & (set(words(step.instruction)) - POSITION_NOISE - ORDERING_WORDS)
        ]

    @staticmethod
    def _bears_on(claim: str, step: Step) -> bool:
        terms = set(words(claim))
        step_words = set(words(" ".join([step.instruction, step.said, *step.ingredients])))
        return bool(terms & step_words)

    @staticmethod
    def _contradicts(stored: str, claim: str) -> bool:
        """A contradiction is information, not an error — but spot it first."""
        stored_words, claim_words = set(words(stored)), set(words(claim))
        shared = stored_words & claim_words
        if len(shared) < 2:
            return False
        for left, right in _OPPOSITES:
            if (left in stored_words and right in claim_words) or (
                right in stored_words and left in claim_words
            ):
                return True
        stored_low, claim_low = f" {normalise(stored)} ", f" {normalise(claim)} "
        negated_now = any(marker.strip() in claim_low for marker in _NEGATIONS)
        negated_then = any(marker.strip() in stored_low for marker in _NEGATIONS)
        return negated_now != negated_then and len(shared) >= 2

    def _answer(
        self, question: str, run: Run, procedure: Procedure, step: Step | None
    ) -> tuple[str | None, str]:
        """What can be answered from the clock, the procedure or the notes."""
        asked = normalise(question)

        if "how long" in asked or "how much longer" in asked:
            if any(term in asked for term in ("been", "so far", "since", "resting", "in for")):
                def spoken(seconds: float | None) -> str:
                    return say_duration(seconds) if (seconds or 0) >= 60 else "under a minute"

                return (
                    f"{sentence(spoken(self._on_step_seconds(run)))} on this step, "
                    f"{spoken(elapsed_seconds(run.started_at))} altogether."
                ), "clock"
            left = sum(
                item.duration_s or 0 for item in procedure.steps if item.n >= run.current_step
            )
            if left:
                return f"About {say_duration(left)} left.", "procedure"

        asked_set = set(words(question))
        if "left" in asked_set or "remaining" in asked_set or "remains" in asked_set:
            return speech.remaining(
                [item for item in procedure.steps if item.n > run.current_step], self.settings.units
            ), "procedure"

        if "where" in asked and step:
            said = speech.say_step(step, self.settings.units)
            return (
                speech.with_reference(run.reference, f"you're on step {step.n}, {said}"),
                "run",
            )

        # "What was the flour weight again?" — a recall question, and only a
        # recall question, is answered by finding the step that named it.
        recall = _RECALL.search(asked) or asked.endswith("again")
        asked_words = set(words(question)) - POSITION_NOISE - {"what", "again", "much", "many"}
        if recall and asked_words:
            for item in procedure.steps:
                haystack = set(words(" ".join([item.instruction, *item.ingredients])))
                if asked_words & haystack:
                    said = speech.say_step(item, self.settings.units)
                    return f"Step {item.n}, {said}", "procedure"

        return None, "model"
