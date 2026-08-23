"""Import the integration without importing Home Assistant.

`custom_components/stepwise/__init__.py` is the Home Assistant entry point and
imports Home Assistant. The core deliberately does not, so the tests register
synthetic packages pointing at the same directories and import the core modules
straight out of them, skipping the `__init__` files that would drag Home
Assistant in.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stepwise"
PKG = "stepwise_core"


def _package(name: str, path: Path) -> None:
    """Register a package without running its __init__."""
    if name in sys.modules:
        return
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


_package(PKG, INTEGRATION)
_package(f"{PKG}.search", INTEGRATION / "search")
_package(f"{PKG}.memory", INTEGRATION / "memory")

from stepwise_core import const, engine, export, models, resolution, speech, store, util
from stepwise_core.memory import base as memory_base
from stepwise_core.search import base as search_base
from stepwise_core.search import none as search_none

__all__ = [
    "const",
    "engine",
    "export",
    "memory_base",
    "models",
    "resolution",
    "search_base",
    "search_none",
    "speech",
    "store",
    "util",
]
