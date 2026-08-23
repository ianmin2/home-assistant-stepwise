"""Search through a rest_command the user already has.

The default, and the one that ships nothing: name an existing rest_command and
the path to the answer in its response, and anything works — including a
research service somebody already runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .base import VOICE_BUDGET_SECONDS, Findings, SearchProvider, dig, to_results

_LOGGER = logging.getLogger(__name__)


class RestCommandSearch(SearchProvider):
    """Calls one rest_command and reads the answer out of its response."""

    name = "rest_command"

    def __init__(self, hass: HomeAssistant, command: str, response_path: str = "") -> None:
        self.hass = hass
        self.command = command
        self.response_path = response_path

    async def search(self, query: str, scope: dict[str, Any] | None = None) -> Findings:
        payload: dict[str, Any] = {"query": query, "q": query}
        for key, value in (scope or {}).items():
            if value:
                payload[key] = value

        try:
            async with asyncio.timeout(VOICE_BUDGET_SECONDS):
                response = await self.hass.services.async_call(
                    "rest_command",
                    self.command,
                    payload,
                    blocking=True,
                    return_response=True,
                )
        except TimeoutError:
            _LOGGER.debug("rest_command %s took too long for a voice turn", self.command)
            return Findings(
                provider=self.name, unavailable="the search took too long to wait for"
            )
        except HomeAssistantError as err:
            _LOGGER.debug("rest_command %s failed: %s", self.command, err)
            return Findings(provider=self.name, unavailable=f"the rest_command failed: {err}")

        content: Any = response
        if isinstance(response, dict) and "content" in response:
            content = response["content"]
        if isinstance(content, str):
            with contextlib.suppress(ValueError):
                content = json.loads(content)

        results = to_results(dig(content, self.response_path))
        if not results:
            return Findings(provider=self.name, unavailable="the search came back empty")
        return Findings(results=results, provider=self.name)
