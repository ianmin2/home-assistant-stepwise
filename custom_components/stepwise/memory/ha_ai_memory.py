"""Adapter for ha-ai-memory.

Provisional. The plan says to agree the integration point with that project
rather than assume it, so this calls services whose names are configurable and
falls back to the built-in store when they are not there. Nothing is lost if
the guess is wrong: it degrades to the same behaviour as having no adapter.

    https://github.com/Riscue/ha-ai-memory
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..search.base import dig
from .base import Fact, MemoryBackend

_LOGGER = logging.getLogger(__name__)

DEFAULT_DOMAIN = "ha_ai_memory"
DEFAULT_RECALL = "search"
DEFAULT_REMEMBER = "remember"
DEFAULT_FORGET = "forget"
DEFAULT_RESPONSE_PATH = "results"


class HaAiMemory(MemoryBackend):
    """Reads subject facts from ha-ai-memory and writes learned quirks back."""

    name = "ha_ai_memory"

    def __init__(
        self,
        hass: HomeAssistant,
        fallback: MemoryBackend,
        domain: str = DEFAULT_DOMAIN,
        recall_service: str = DEFAULT_RECALL,
        remember_service: str = DEFAULT_REMEMBER,
        forget_service: str = DEFAULT_FORGET,
        response_path: str = DEFAULT_RESPONSE_PATH,
    ) -> None:
        self.hass = hass
        self.fallback = fallback
        self.domain = domain
        self.recall_service = recall_service
        self.remember_service = remember_service
        self.forget_service = forget_service
        self.response_path = response_path

    async def available(self) -> bool:
        return self.hass.services.has_service(self.domain, self.recall_service)

    async def facts(self, subject_id: str | None, query: str = "") -> list[Fact]:
        if not await self.available():
            return await self.fallback.facts(subject_id, query)
        try:
            response = await self.hass.services.async_call(
                self.domain,
                self.recall_service,
                {"query": query or subject_id or ""},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("ha-ai-memory recall failed: %s", err)
            return await self.fallback.facts(subject_id, query)

        found: Any = dig(response, self.response_path)
        facts: list[Fact] = []
        for item in found or []:
            if isinstance(item, str):
                facts.append(Fact(text=item, source=self.name))
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("fact")
                if text:
                    facts.append(Fact(text=str(text), source=self.name, id=item.get("id")))
        return facts

    async def remember(
        self, text: str, subject_id: str | None = None, source: str = "stepwise"
    ) -> bool:
        if not self.hass.services.has_service(self.domain, self.remember_service):
            return await self.fallback.remember(text, subject_id, source)
        try:
            await self.hass.services.async_call(
                self.domain,
                self.remember_service,
                {"text": text, "subject": subject_id or "", "source": source},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("ha-ai-memory remember failed: %s", err)
            return await self.fallback.remember(text, subject_id, source)
        return True

    async def forget(self, fact_id: str) -> bool:
        """Unlearn one fact, falling back to the local table.

        A fact stored upstream can only be removed upstream, so if there is no
        service for it this says so rather than reporting a success it did not
        have. Anything that landed in the local table is still removable.
        """
        if not self.hass.services.has_service(self.domain, self.forget_service):
            return await self.fallback.forget(fact_id)
        try:
            await self.hass.services.async_call(
                self.domain, self.forget_service, {"id": fact_id}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.debug("ha-ai-memory forget failed: %s", err)
            return await self.fallback.forget(fact_id)
        return True
