"""What an automation, a dashboard button or a script can ask for.

Deliberately few, and none of them able to move a run's pointer: that belongs
to the person doing the job and to the tools they talk to. What is here is
reading the record out, and the two housekeeping acts the options flow already
offers, so a wall panel can offer them too.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import export
from .const import DOMAIN
from .store import Store

SERVICE_EXPORT_RUN = "export_run"
SERVICE_LIST_RUNS = "list_runs"
SERVICE_FINISH_RUN = "finish_run"

EXPORT_SCHEMA = vol.Schema(
    {
        vol.Optional("run_id"): cv.string,
        vol.Optional("reference"): cv.string,
    }
)

LIST_SCHEMA = vol.Schema({vol.Optional("include_finished", default=False): cv.boolean})

FINISH_SCHEMA = vol.Schema(
    {
        vol.Required("run_id"): cv.string,
        vol.Optional("outcome"): cv.string,
        vol.Optional("abandoned", default=False): cv.boolean,
    }
)


def _entry_data(hass: HomeAssistant) -> tuple[Store, object]:
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [entry for entry in entries if getattr(entry, "runtime_data", None)]
    if not loaded:
        raise ServiceValidationError("Stepwise is not set up.")
    data = loaded[0].runtime_data
    return data.store, data.engine


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the actions once, for the whole integration."""

    async def export_run(call: ServiceCall) -> ServiceResponse:
        """The record of one run, as markdown, CSV and rows.

        Given nothing it exports the run last touched, because that is what
        somebody who has just finished a job means. Retention deletes closed
        runs eventually, and until now there was no way to keep one first.
        """
        store, _engine = _entry_data(hass)
        run_id = call.data.get("run_id")
        reference = call.data.get("reference")

        def gather() -> ServiceResponse:
            run = store.get_run(run_id) if run_id else None
            if run is None:
                candidates = store.recent_runs(limit=50)
                if reference:
                    wanted = reference.strip().lower()
                    candidates = [
                        item
                        for item in candidates
                        if wanted in item.reference.lower()
                    ] or candidates
                run = candidates[0] if candidates else None
            if run is None:
                raise ServiceValidationError("There is no run to export.")
            return export.payload(
                run,
                store.events(run.id),
                store.get_procedure(run.procedure_id),
                store.get_subject(run.subject_id) if run.subject_id else None,
                store.amendments(run.id),
            )

        return await hass.async_add_executor_job(gather)

    async def list_runs(call: ServiceCall) -> ServiceResponse:
        """Every run, for a dashboard that would rather not wait to be told."""
        store, engine = _entry_data(hass)

        def gather() -> ServiceResponse:
            runs = (
                store.recent_runs(limit=50)
                if call.data.get("include_finished")
                else store.open_runs()
            )
            return {"runs": [engine.run_summary(run) for run in runs]}

        return await hass.async_add_executor_job(gather)

    async def finish_run(call: ServiceCall) -> None:
        """Close a run from a button. The same act the options flow offers."""
        _store, engine = _entry_data(hass)
        await hass.async_add_executor_job(
            lambda: engine.run_finish(
                run_id=call.data["run_id"],
                outcome=call.data.get("outcome"),
                abandoned=call.data.get("abandoned", False),
            )
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_RUN,
        export_run,
        schema=EXPORT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_RUNS,
        list_runs,
        schema=LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_FINISH_RUN, finish_run, schema=FINISH_SCHEMA)


@callback
def async_unregister(hass: HomeAssistant) -> None:
    for service in (SERVICE_EXPORT_RUN, SERVICE_LIST_RUNS, SERVICE_FINISH_RUN):
        hass.services.async_remove(DOMAIN, service)
