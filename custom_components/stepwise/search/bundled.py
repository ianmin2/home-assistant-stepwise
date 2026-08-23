"""The optional bundled provider add-on.

Never a dependency. If the add-on is not running, this says so rather than
pretending the answer is unknown.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .base import Findings, SearchProvider, to_results

_LOGGER = logging.getLogger(__name__)


class BundledSearch(SearchProvider):
    """Asks the add-on, which does the searching, reranking and fetching."""

    name = "bundled"

    def __init__(self, hass: HomeAssistant, base_url: str, timeout: int = 20) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, scope: dict[str, Any] | None = None) -> Findings:
        session = async_get_clientsession(self.hass)
        body: dict[str, Any] = {"query": query}
        if scope:
            body["scope"] = {key: value for key, value in scope.items() if value}

        try:
            async with session.post(
                f"{self.base_url}/search", json=body, timeout=self.timeout
            ) as response:
                if response.status != 200:
                    return Findings(
                        provider=self.name,
                        unavailable=f"the provider answered {response.status}",
                    )
                payload = await response.json()
        except Exception as err:
            _LOGGER.debug("bundled search failed: %s", err)
            return Findings(provider=self.name, unavailable=f"the provider is not reachable: {err}")

        results = to_results(payload.get("results", payload))
        if not results:
            return Findings(provider=self.name, unavailable="the search came back empty")
        return Findings(results=results, provider=self.name)
