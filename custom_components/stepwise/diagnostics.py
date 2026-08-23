"""What to attach to a bug report, with none of what a run is about.

Counts, versions and settings. Never a step, a note, a reference, a quirk or a
subject's name: a procedure is somebody's kitchen or somebody's heating system,
and a diagnostics download is a file people paste into public issues.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import StepwiseConfigEntry
from .const import SCHEMA_VERSION


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StepwiseConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data

    def gather() -> dict[str, Any]:
        return {
            "counts": data.store.stats(),
            "schema_version": data.store.schema_version(),
            "schema_version_expected": SCHEMA_VERSION,
            "open_runs": len(data.store.open_runs()),
        }

    return {
        "settings": data.engine.settings.as_dict(),
        "search_provider": getattr(data.search, "name", "unknown"),
        "memory_backend": getattr(data.memory, "name", "unknown"),
        "storage": await hass.async_add_executor_job(gather),
    }
