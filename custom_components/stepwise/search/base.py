"""The interface every search adapter meets. No Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Result:
    """One thing found. Cited plainly, never paraphrased into fact."""

    title: str
    snippet: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "snippet": self.snippet, "url": self.url}


@dataclass(slots=True)
class Findings:
    """What came back, and why nothing did when nothing did."""

    results: list[Result] = field(default_factory=list)
    provider: str = "none"
    unavailable: str | None = None

    @property
    def found(self) -> bool:
        return bool(self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "results": [result.as_dict() for result in self.results],
            "unavailable": self.unavailable,
        }


class SearchProvider:
    """Ask a scoped question and get back citable answers, or an honest nothing."""

    name = "base"

    async def search(self, query: str, scope: dict[str, Any] | None = None) -> Findings:
        raise NotImplementedError


def dig(payload: Any, path: str) -> Any:
    """Follow a dotted path into a response. "results.0.content"."""
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def to_results(payload: Any, limit: int = 5) -> list[Result]:
    """Make sense of whatever shape a provider returned."""
    if payload is None:
        return []
    if isinstance(payload, str):
        return [Result(title=payload[:120], snippet=payload)]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return [Result(title=str(payload)[:120], snippet=str(payload))]

    results: list[Result] = []
    for item in payload[:limit]:
        if isinstance(item, str):
            results.append(Result(title=item[:120], snippet=item))
            continue
        if not isinstance(item, dict):
            results.append(Result(title=str(item)[:120], snippet=str(item)))
            continue
        results.append(
            Result(
                title=str(item.get("title") or item.get("name") or item.get("url") or "")[:200],
                snippet=str(item.get("snippet") or item.get("content") or item.get("text") or ""),
                url=str(item.get("url") or item.get("link") or ""),
            )
        )
    return results
