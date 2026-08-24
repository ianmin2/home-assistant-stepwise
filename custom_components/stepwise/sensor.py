"""Numbers, and only numbers.

Entities were held back for one reason: an entity's attributes are copied into
Home Assistant's recorder database and kept there, so a run's step text in an
attribute would quietly undo the promise that everything Stepwise knows lives
in one file you can delete.

These three are the exception that proves it. A count and a file size are small
numbers with no procedure in them, they are exactly what a dashboard wants to
graph, and recording their history costs nothing and reveals nothing. Anything
with words in it goes through the websocket API instead, where nothing is kept.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from . import StepwiseConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, kw_only=True)
class StepwiseSensorDescription(SensorEntityDescription):
    """One number, and where to find it."""

    value: Callable[[dict[str, Any]], int]


SENSORS: tuple[StepwiseSensorDescription, ...] = (
    StepwiseSensorDescription(
        key="runs_in_progress",
        translation_key="runs_in_progress",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda data: int(data["open_runs"]),
    ),
    StepwiseSensorDescription(
        key="procedures",
        translation_key="procedures",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: int(data["counts"].get("procedures", 0)),
    ),
    StepwiseSensorDescription(
        key="things",
        translation_key="things",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: int(data["counts"].get("subjects", 0)),
    ),
    StepwiseSensorDescription(
        key="database_size",
        translation_key="database_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value=lambda data: int(data["size_bytes"]),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: StepwiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = entry.runtime_data.store

    async def poll() -> dict[str, Any]:
        def gather() -> dict[str, Any]:
            return {
                "counts": store.stats(),
                "size_bytes": store.size_bytes(),
                "open_runs": len(store.open_runs()),
            }

        return await hass.async_add_executor_job(gather)

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Stepwise",
        update_method=poll,
        update_interval=SCAN_INTERVAL,
        config_entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data.coordinator = coordinator
    async_add_entities(StepwiseSensor(coordinator, entry, description) for description in SENSORS)


class StepwiseSensor(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity):
    """One count, or one size. Never a step, a note or a reference."""

    _attr_has_entity_name = True
    entity_description: StepwiseSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: StepwiseConfigEntry,
        description: StepwiseSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Stepwise",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value(self.coordinator.data)
