"""Stepwise: guided step by step procedures for Home Assistant.

Sets up one SQLite file, one engine over it, and one LLM API that any
conversation agent can be given. Nothing else runs in the background.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

from . import services
from .const import DB_FILENAME, DOMAIN, EVENT_ADVANCED, EVENT_FINISHED
from .engine import Engine, Settings
from .llm_tools import StepwiseAPI
from .memory import MemoryBackend, build_backend
from .models import Run, RunEvent
from .search import SearchProvider, build_provider
from .store import Store, StoreError

_LOGGER = logging.getLogger(__name__)

type StepwiseConfigEntry = ConfigEntry["StepwiseData"]

# Fired for anything that happens in a run, so an automation can act on it —
# "when the loaf reaches the prove, dim the kitchen". Deliberately events and
# not entities: a run's step text in an entity attribute would be copied into
# the recorder database and kept there, which quietly undoes the promise that
# everything Stepwise knows lives in one file you can delete.
EVENT_BUS_ANY = f"{DOMAIN}_event"
EVENT_BUS_ADVANCED = f"{DOMAIN}_step_advanced"
EVENT_BUS_FINISHED = f"{DOMAIN}_run_finished"


@dataclass
class StepwiseData:
    """What a loaded entry owns."""

    store: Store
    engine: Engine
    api: StepwiseAPI
    search: SearchProvider
    memory: MemoryBackend


async def async_setup_entry(hass: HomeAssistant, entry: StepwiseConfigEntry) -> bool:
    """Open the store and offer the tools to conversation agents."""
    store = Store(hass.config.path(DB_FILENAME))
    try:
        await hass.async_add_executor_job(store.connect)
    except StoreError as err:
        # A database we will not use, for a reason a person can act on:
        # written by a newer Stepwise, or a migration that would not run.
        raise ConfigEntryError(str(err)) from err
    except sqlite3.DatabaseError as err:
        raise ConfigEntryError(
            f"{hass.config.path(DB_FILENAME)} could not be read as a database ({err}). "
            "Restore it from a backup, or move it aside to start again."
        ) from err
    except OSError as err:
        # A full disk or a locked file may well clear on its own, so this is
        # worth retrying rather than giving up on.
        raise ConfigEntryNotReady(f"Stepwise cannot reach its database: {err}") from err

    options = {**entry.data, **entry.options}
    engine = Engine(store, Settings.from_mapping(options))
    search = build_provider(hass, options)
    memory = build_backend(hass, store, options)
    api = StepwiseAPI(hass, engine, search=search, memory=memory)

    engine.observer = _announcer(hass)

    unregister = llm.async_register_api(hass, api)
    entry.async_on_unload(unregister)
    entry.runtime_data = StepwiseData(
        store=store, engine=engine, api=api, search=search, memory=memory
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    services.async_register(hass)

    _LOGGER.debug("Stepwise ready: %s", await hass.async_add_executor_job(store.stats))
    return True


def _announcer(hass: HomeAssistant) -> Any:
    """Put every run event on the bus, without the core knowing there is one."""

    def announce(event: RunEvent, run: Run) -> None:
        payload = {
            "run_id": run.id,
            "reference": run.reference,
            "kind": event.kind,
            "step": event.step_n,
            "text": event.text,
            "at": event.at,
        }
        hass.bus.async_fire(EVENT_BUS_ANY, payload)
        if event.kind == EVENT_ADVANCED:
            hass.bus.async_fire(EVENT_BUS_ADVANCED, payload)
        elif event.kind == EVENT_FINISHED:
            hass.bus.async_fire(EVENT_BUS_FINISHED, payload)

    return announce


async def async_unload_entry(hass: HomeAssistant, entry: StepwiseConfigEntry) -> bool:
    """Close the store. Run state is on disk, so there is nothing to flush."""
    data = entry.runtime_data
    data.engine.observer = None
    services.async_unregister(hass)
    await hass.async_add_executor_job(data.store.close)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: StepwiseConfigEntry) -> None:
    """Set the database aside when the integration is removed.

    Renamed rather than deleted, on purpose. A run's history is a record of
    something somebody actually did, and removing an integration is not the
    same as saying "throw that away" — people reinstall. Leaving it in place
    was worse: reinstalling silently resurrected every old run and every cold
    one it would then offer.
    """
    path = hass.config.path(DB_FILENAME)

    def set_aside() -> str | None:
        if not os.path.exists(path):
            return None
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        spare = f"{path}.removed-{stamp}"
        try:
            os.replace(path, spare)
        except OSError as err:  # pragma: no cover - disk trouble
            _LOGGER.warning("Could not set the Stepwise database aside: %s", err)
            return None
        for suffix in ("-wal", "-shm"):
            if os.path.exists(f"{path}{suffix}"):
                with contextlib.suppress(OSError):  # pragma: no cover
                    os.remove(f"{path}{suffix}")
        return spare

    spare = await hass.async_add_executor_job(set_aside)
    if spare:
        _LOGGER.info(
            "Stepwise removed. Its history is kept at %s — delete it to be rid of it.", spare
        )


async def _async_options_updated(hass: HomeAssistant, entry: StepwiseConfigEntry) -> None:
    """Apply new settings in place. The thresholds are meant to be fiddled with."""
    data = entry.runtime_data
    options = {**entry.data, **entry.options}
    data.engine.settings = Settings.from_mapping(options)
    data.search = build_provider(hass, options)
    data.memory = build_backend(hass, data.store, options)
    data.api.search = data.search
    data.api.memory = data.memory
