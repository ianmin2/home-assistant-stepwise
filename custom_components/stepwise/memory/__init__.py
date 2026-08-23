"""Where long-lived facts live (section 3).

Stepwise depends on a memory layer rather than reimplementing one. Run state
stays here; facts go there.
"""

from __future__ import annotations

from typing import Any

from ..const import CONF_MEMORY_BACKEND, MEMORY_HA_AI_MEMORY
from ..store import Store
from .base import Fact, MemoryBackend
from .builtin import BuiltinMemory
from .ha_ai_memory import HaAiMemory

__all__ = ["BuiltinMemory", "Fact", "HaAiMemory", "MemoryBackend", "build_backend"]


def build_backend(hass: Any, store: Store, options: dict[str, Any]) -> MemoryBackend:
    """The configured backend, always with the built-in one behind it."""
    builtin = BuiltinMemory(hass, store)
    if options.get(CONF_MEMORY_BACKEND) == MEMORY_HA_AI_MEMORY:
        return HaAiMemory(hass, fallback=builtin)
    return builtin
