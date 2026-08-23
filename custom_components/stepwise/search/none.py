"""No provider. Degrades honestly rather than failing (section 11)."""

from __future__ import annotations

from typing import Any

from .base import Findings, SearchProvider


class NoSearch(SearchProvider):
    """The agent's own knowledge only, and it is told so."""

    name = "none"

    def __init__(self, because: str = "no search provider is configured") -> None:
        self.because = because

    async def search(self, query: str, scope: dict[str, Any] | None = None) -> Findings:
        return Findings(provider=self.name, unavailable=self.because)
