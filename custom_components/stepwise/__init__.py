"""Stepwise: guided step by step procedures for Home Assistant.

Sets up one SQLite file, one engine over it, and one LLM API that any
conversation agent can be given. Nothing else runs in the background.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import DB_FILENAME
from .engine import Engine, Settings
from .llm_tools import StepwiseAPI
from .memory import MemoryBackend, build_backend
from .search import SearchProvider, build_provider
from .store import Store

_LOGGER = logging.getLogger(__name__)

type StepwiseConfigEntry = ConfigEntry["StepwiseData"]


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
    await hass.async_add_executor_job(store.connect)

    options = {**entry.data, **entry.options}
    engine = Engine(store, Settings.from_mapping(options))
    search = build_provider(hass, options)
    memory = build_backend(hass, store, options)
    api = StepwiseAPI(hass, engine, search=search, memory=memory)

    unregister = llm.async_register_api(hass, api)
    entry.async_on_unload(unregister)
    entry.runtime_data = StepwiseData(
        store=store, engine=engine, api=api, search=search, memory=memory
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.debug("Stepwise ready: %s", await hass.async_add_executor_job(store.stats))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StepwiseConfigEntry) -> bool:
    """Close the store. Run state is on disk, so there is nothing to flush."""
    data = entry.runtime_data
    await hass.async_add_executor_job(data.store.close)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: StepwiseConfigEntry) -> None:
    """Apply new settings in place. The thresholds are meant to be fiddled with."""
    data = entry.runtime_data
    options = {**entry.data, **entry.options}
    data.engine.settings = Settings.from_mapping(options)
    data.search = build_provider(hass, options)
    data.memory = build_backend(hass, data.store, options)
    data.api.search = data.search
    data.api.memory = data.memory
