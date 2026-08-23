"""Facts in the same SQLite file, for people who do not want a second integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..store import Store
from .base import Fact, MemoryBackend


class BuiltinMemory(MemoryBackend):
    """Small, explicit, and bounded: nothing is written unless a tool writes it."""

    name = "builtin"

    def __init__(self, hass: HomeAssistant, store: Store) -> None:
        self.hass = hass
        self.store = store

    async def facts(self, subject_id: str | None, query: str = "") -> list[Fact]:
        rows = await self.hass.async_add_executor_job(self.store.facts, subject_id)
        return [Fact(text=row["text"], source=row["source"], id=row["id"]) for row in rows]

    async def remember(
        self, text: str, subject_id: str | None = None, source: str = "stepwise"
    ) -> bool:
        await self.hass.async_add_executor_job(self.store.add_fact, text, subject_id, source)
        return True

    async def forget(self, fact_id: str) -> bool:
        await self.hass.async_add_executor_job(self.store.forget_fact, fact_id)
        return True
