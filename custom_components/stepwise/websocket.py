"""What the panel asks the integration, and what it is allowed to change.

Deliberately not entities. A run's step text in an entity attribute is copied
into Home Assistant's recorder database and kept there, which would quietly
undo the promise that everything Stepwise knows lives in one file you can
delete. A websocket command reads the same data, keeps nothing, and leaves no
entity ids to regret.

What may be changed here follows the same rule as everywhere else: subjects,
quirks, facts and procedures are yours to correct, and `run_events` is not.
A spine that can be rewritten is not a record, so a run's history can be read
and exported and never edited — and a run can be deleted, once, whole, after
the export has been offered.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import export
from .const import DOMAIN, SCHEMA_VERSION
from .engine import Engine
from .models import Procedure, Step, Subject
from .store import Store

COMMANDS = (
    "overview",
    "runs",
    "run",
    "subjects",
    "subject/save",
    "subject/delete",
    "quirk/retract",
    "fact/forget",
    "procedures",
    "procedure",
    "procedure/save",
    "procedure/delete",
    "run/start",
    "run/resume",
    "run/finish",
    "run/delete",
)


def _parts(hass: HomeAssistant) -> tuple[Store, Engine] | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        data = getattr(entry, "runtime_data", None)
        if data is not None:
            return data.store, data.engine
    return None


def _needs(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int):
    parts = _parts(hass)
    if parts is None:
        connection.send_error(msg_id, "not_ready", "Stepwise is not set up.")
        return None
    return parts


def _subject_json(store: Store, subject: Subject) -> dict[str, Any]:
    """A thing, with everything known about it — because a quirk nobody can
    see is a quirk nobody can correct."""
    return {
        "id": subject.id,
        "kind": subject.kind,
        "label": subject.label,
        "described": subject.described,
        "make": subject.make,
        "model": subject.model,
        "aliases": list(subject.aliases),
        "attributes": dict(subject.attributes),
        "status": subject.status,
        "quirks": [
            {
                "id": quirk.id,
                "claim": quirk.claim,
                "learned_from": quirk.learned_from,
                "confidence": quirk.confidence,
                "status": quirk.status,
                "learned_at": quirk.learned_at,
                "last_confirmed_at": quirk.last_confirmed_at,
                "last_stated_at": quirk.last_stated_at,
                "times_applied": quirk.times_applied,
            }
            for quirk in store.quirks(subject.id, include_inactive=True)
        ],
        "facts": [
            {"id": str(fact["id"]), "text": str(fact["text"]), "source": str(fact["source"])}
            for fact in store.facts(subject.id)
        ],
    }


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every command once, for the whole integration."""

    @websocket_api.websocket_command({vol.Required("type"): "stepwise/overview"})
    @websocket_api.async_response
    async def overview(hass, connection, msg):
        """Everything the top of the panel shows: how much, and what is live."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, engine = got

        def gather() -> dict[str, Any]:
            counts = store.stats()
            open_runs = store.open_runs()
            return {
                "counts": counts,
                "size_bytes": store.size_bytes(),
                "schema_version": store.schema_version(),
                "schema_version_expected": SCHEMA_VERSION,
                "open_runs": [engine.run_summary(run) for run in open_runs],
            }

        connection.send_result(msg["id"], await hass.async_add_executor_job(gather))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/runs",
            vol.Optional("include_finished", default=True): bool,
            vol.Optional("limit", default=50): int,
        }
    )
    @websocket_api.async_response
    async def runs(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, engine = got

        def gather() -> dict[str, Any]:
            found = (
                store.recent_runs(limit=int(msg["limit"]))
                if msg["include_finished"]
                else store.open_runs()
            )
            listed = []
            for run in found:
                summary = engine.run_summary(run)
                procedure = store.get_procedure(run.procedure_id)
                subject = store.get_subject(run.subject_id) if run.subject_id else None
                listed.append(
                    {
                        **summary,
                        "title": procedure.title if procedure else None,
                        "total_steps": len(store.get_run_steps(run.id)),
                        "subject": subject.described if subject else None,
                        "subject_id": run.subject_id,
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "outcome": run.outcome,
                    }
                )
            return {"runs": listed}

        connection.send_result(msg["id"], await hass.async_add_executor_job(gather))

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/run", vol.Required("run_id"): str}
    )
    @websocket_api.async_response
    async def run(hass, connection, msg):
        """One run, whole: its steps, and every timestamped thing that happened."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, engine = got

        def gather() -> dict[str, Any] | None:
            found = store.get_run(msg["run_id"])
            if found is None:
                return None
            procedure = store.get_procedure(found.procedure_id)
            subject = store.get_subject(found.subject_id) if found.subject_id else None
            steps = store.get_run_steps(found.id)
            events = store.events(found.id)
            return {
                **engine.run_summary(found),
                "title": procedure.title if procedure else None,
                "procedure_id": found.procedure_id,
                "subject": subject.described if subject else None,
                "subject_id": found.subject_id,
                "started_at": found.started_at,
                "finished_at": found.finished_at,
                "outcome": found.outcome,
                "total_steps": len(steps),
                "steps": [
                    {
                        "n": step.n,
                        "instruction": step.instruction,
                        "speakable": step.said,
                        "ingredients": list(step.ingredients),
                        "duration_s": step.duration_s,
                        "awaits": step.awaits,
                        "settings": dict(step.settings),
                    }
                    for step in steps
                ],
                # Read-only, always. This is the record of what happened.
                "history": export.rows(found, events),
                "amendments": [
                    {
                        "step_n": change.step_n,
                        "was": change.was,
                        "now": change.now,
                        "why": change.why,
                        "scope": change.scope,
                        "at": change.at,
                    }
                    for change in store.amendments(found.id)
                ],
            }

        result = await hass.async_add_executor_job(gather)
        if result is None:
            connection.send_error(msg["id"], "not_found", "No such run.")
            return
        connection.send_result(msg["id"], result)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/subjects",
            vol.Optional("include_retired", default=True): bool,
        }
    )
    @websocket_api.async_response
    async def subjects(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def gather() -> dict[str, Any]:
            found = store.list_subjects(include_retired=msg["include_retired"])
            return {"subjects": [_subject_json(store, subject) for subject in found]}

        connection.send_result(msg["id"], await hass.async_add_executor_job(gather))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/subject/save",
            vol.Optional("subject_id"): str,
            vol.Required("label"): str,
            vol.Required("kind"): str,
            vol.Optional("make"): vol.Any(str, None),
            vol.Optional("model"): vol.Any(str, None),
            vol.Optional("aliases", default=[]): [str],
        }
    )
    @websocket_api.async_response
    async def subject_save(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def save() -> dict[str, Any]:
            existing = store.get_subject(msg["subject_id"]) if msg.get("subject_id") else None
            if existing is None:
                subject = Subject.new(msg["label"], msg["kind"])
                subject.id = store.unique_subject_id(subject.id)
            else:
                subject = existing
                subject.label = msg["label"]
                subject.kind = msg["kind"]
            subject.make = msg.get("make") or None
            subject.model = msg.get("model") or None
            subject.aliases = [alias for alias in msg["aliases"] if alias.strip()]
            store.save_subject(subject)
            return _subject_json(store, subject)

        connection.send_result(msg["id"], await hass.async_add_executor_job(save))

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/subject/delete", vol.Required("subject_id"): str}
    )
    @websocket_api.async_response
    async def subject_delete(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got
        await hass.async_add_executor_job(store.delete_subject, msg["subject_id"])
        connection.send_result(msg["id"], {"deleted": msg["subject_id"]})

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/quirk/retract", vol.Required("quirk_id"): str}
    )
    @websocket_api.async_response
    async def quirk_retract(hass, connection, msg):
        """A wrong quirk that cannot be forgotten is permanent. This is the tap."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got
        await hass.async_add_executor_job(store.retract_quirk, msg["quirk_id"])
        connection.send_result(msg["id"], {"retracted": msg["quirk_id"]})

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/fact/forget", vol.Required("fact_id"): str}
    )
    @websocket_api.async_response
    async def fact_forget(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got
        await hass.async_add_executor_job(store.forget_fact, msg["fact_id"])
        connection.send_result(msg["id"], {"forgotten": msg["fact_id"]})

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/procedures", vol.Optional("limit", default=200): int}
    )
    @websocket_api.async_response
    async def procedures(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def gather() -> dict[str, Any]:
            found = store.list_procedures(limit=int(msg["limit"]))
            return {
                "procedures": [
                    {
                        "id": procedure.id,
                        "title": procedure.title,
                        "kind": procedure.kind,
                        "subject_kind": procedure.subject_kind,
                        "source": procedure.source,
                        "updated_at": procedure.updated_at,
                        "total_steps": procedure.total_steps,
                    }
                    for procedure in found
                ]
            }

        connection.send_result(msg["id"], await hass.async_add_executor_job(gather))

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/procedure", vol.Required("procedure_id"): str}
    )
    @websocket_api.async_response
    async def procedure(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def gather() -> dict[str, Any] | None:
            found = store.get_procedure(msg["procedure_id"])
            if found is None:
                return None
            return {
                "id": found.id,
                "title": found.title,
                "kind": found.kind,
                "subject_kind": found.subject_kind,
                "source": found.source,
                "steps": [
                    {
                        "n": step.n,
                        "instruction": step.instruction,
                        "speakable": step.said,
                        "ingredients": list(step.ingredients),
                        "duration_s": step.duration_s,
                        "awaits": step.awaits,
                    }
                    for step in found.steps
                ],
            }

        result = await hass.async_add_executor_job(gather)
        if result is None:
            connection.send_error(msg["id"], "not_found", "No such procedure.")
            return
        connection.send_result(msg["id"], result)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/procedure/save",
            vol.Optional("procedure_id"): str,
            vol.Required("title"): str,
            vol.Optional("subject_kind"): vol.Any(str, None),
            vol.Required("steps"): [
                {
                    vol.Required("instruction"): str,
                    vol.Optional("duration_s"): vol.Any(int, None),
                    vol.Optional("ingredients", default=[]): [str],
                }
            ],
        }
    )
    @websocket_api.async_response
    async def procedure_save(hass, connection, msg):
        """Edit a template. Runs already under way own their own steps and are
        untouched — which is what makes editing one safe."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def save() -> dict[str, Any]:
            from . import speech

            steps = [
                Step(
                    n=index,
                    instruction=raw["instruction"].strip(),
                    speakable=speech.quantity_first(raw["instruction"].strip()),
                    ingredients=list(raw.get("ingredients") or []),
                    duration_s=raw.get("duration_s") or None,
                )
                for index, raw in enumerate(msg["steps"], start=1)
                if raw["instruction"].strip()
            ]
            existing = store.get_procedure(msg["procedure_id"]) if msg.get("procedure_id") else None
            if existing is None:
                built = Procedure.new(msg["title"], steps)
                built.subject_kind = msg.get("subject_kind") or None
            else:
                built = existing
                built.title = msg["title"]
                built.subject_kind = msg.get("subject_kind") or built.subject_kind
                built.steps = steps
            store.save_procedure(built)
            return {"procedure_id": built.id, "total_steps": len(steps)}

        connection.send_result(msg["id"], await hass.async_add_executor_job(save))

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/procedure/delete", vol.Required("procedure_id"): str}
    )
    @websocket_api.async_response
    async def procedure_delete(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got
        await hass.async_add_executor_job(store.delete_procedure, msg["procedure_id"])
        connection.send_result(msg["id"], {"deleted": msg["procedure_id"]})

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/run/start",
            vol.Required("procedure_id"): str,
            vol.Optional("reference"): vol.Any(str, None),
            vol.Optional("subject_id"): vol.Any(str, None),
        }
    )
    @websocket_api.async_response
    async def run_start(hass, connection, msg):
        """The button. Starting from a panel is the same act as saying so."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        _store, engine = got
        reply = await hass.async_add_executor_job(
            lambda: engine.run_start(
                msg["procedure_id"],
                reference=msg.get("reference") or None,
                subject_id=msg.get("subject_id") or None,
            )
        )
        connection.send_result(msg["id"], reply.as_dict())

    @websocket_api.websocket_command(
        {vol.Required("type"): "stepwise/run/resume", vol.Required("run_id"): str}
    )
    @websocket_api.async_response
    async def run_resume(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        _store, engine = got
        reply = await hass.async_add_executor_job(lambda: engine.run_reopen(run_id=msg["run_id"]))
        connection.send_result(msg["id"], reply.as_dict())

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/run/finish",
            vol.Required("run_id"): str,
            vol.Optional("outcome"): vol.Any(str, None),
            vol.Optional("how", default="done"): vol.In(["done", "paused", "stopped"]),
        }
    )
    @websocket_api.async_response
    async def run_finish(hass, connection, msg):
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        _store, engine = got
        reply = await hass.async_add_executor_job(
            lambda: engine.run_finish(
                run_id=msg["run_id"], outcome=msg.get("outcome") or None, how=msg["how"]
            )
        )
        connection.send_result(msg["id"], reply.as_dict())

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "stepwise/run/delete",
            vol.Required("run_id"): str,
            vol.Optional("export_first", default=True): bool,
        }
    )
    @websocket_api.async_response
    async def run_delete(hass, connection, msg):
        """Deleting a run destroys the record of something somebody did, so
        the record comes back in the reply first. Refusing to hand it over
        would be worse than the deletion."""
        got = _needs(hass, connection, msg["id"])
        if got is None:
            return
        store, _engine = got

        def remove() -> dict[str, Any]:
            found = store.get_run(msg["run_id"])
            keepsake = None
            if found is not None and msg["export_first"]:
                keepsake = export.as_markdown(
                    found,
                    store.events(found.id),
                    store.get_procedure(found.procedure_id),
                    store.get_subject(found.subject_id) if found.subject_id else None,
                    store.amendments(found.id),
                )
            store.delete_run(msg["run_id"])
            return {"deleted": msg["run_id"], "markdown": keepsake}

        connection.send_result(msg["id"], await hass.async_add_executor_job(remove))

    for command in (
        overview,
        runs,
        run,
        subjects,
        subject_save,
        subject_delete,
        quirk_retract,
        fact_forget,
        procedures,
        procedure,
        procedure_save,
        procedure_delete,
        run_start,
        run_resume,
        run_finish,
        run_delete,
    ):
        websocket_api.async_register_command(hass, command)


__all__ = ["COMMANDS", "async_register"]
