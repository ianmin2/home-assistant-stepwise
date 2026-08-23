"""What Stepwise expects of a memory backend. No Home Assistant imports.

Long-lived facts are not run state, and keeping them apart is the whole point
of section 2. Stepwise reads a subject's facts and writes back what it learns;
it stores no embeddings and does no semantic search of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Fact:
    """One durable thing that is true about a subject."""

    text: str
    source: str = "stepwise"
    id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "source": self.source}


class MemoryBackend:
    """Read facts about one thing; write back what was learned about it."""

    name = "base"

    async def available(self) -> bool:
        return True

    async def facts(self, subject_id: str | None, query: str = "") -> list[Fact]:
        raise NotImplementedError

    async def remember(
        self, text: str, subject_id: str | None = None, source: str = "stepwise"
    ) -> bool:
        raise NotImplementedError

    async def forget(self, fact_id: str) -> bool:
        """Unlearn one fact.

        Part of the contract, not an extra. A memory that can only be added to
        is the thing this is meant to be better than: told one thing and then
        the opposite, it ends up asserting both, with no way to settle it by
        voice. A backend that genuinely cannot forget should return False and
        say so, rather than quietly doing nothing.
        """
        return False
