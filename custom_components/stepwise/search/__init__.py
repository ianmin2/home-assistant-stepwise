"""Looking things up. Pluggable, never bundled (section 11).

Three adapters behind one interface. Bundling a scraper into the integration
would tie an integration's release cycle to the fragility of web scraping, so
the fetching lives elsewhere and this only knows how to ask.
"""

from __future__ import annotations

from typing import Any

from ..const import (
    CONF_SEARCH_BASE_URL,
    CONF_SEARCH_PROVIDER,
    CONF_SEARCH_RESPONSE_PATH,
    CONF_SEARCH_REST_COMMAND,
    SEARCH_BUNDLED,
    SEARCH_NONE,
    SEARCH_REST_COMMAND,
)
from .base import Result, SearchProvider
from .bundled import BundledSearch
from .none import NoSearch
from .rest_command import RestCommandSearch

__all__ = [
    "BundledSearch",
    "NoSearch",
    "RestCommandSearch",
    "Result",
    "SearchProvider",
    "build_provider",
]


def build_provider(hass: Any, options: dict[str, Any]) -> SearchProvider:
    """Whichever adapter the user configured, or an honest nothing."""
    choice = options.get(CONF_SEARCH_PROVIDER, SEARCH_NONE)

    if choice == SEARCH_REST_COMMAND:
        command = options.get(CONF_SEARCH_REST_COMMAND)
        if not command:
            return NoSearch("no rest_command was named in the settings")
        return RestCommandSearch(
            hass, command=command, response_path=options.get(CONF_SEARCH_RESPONSE_PATH) or ""
        )

    if choice == SEARCH_BUNDLED:
        base_url = options.get(CONF_SEARCH_BASE_URL) or ""
        if not base_url:
            return NoSearch("the bundled provider add-on has no address configured")
        return BundledSearch(hass, base_url=base_url)

    return NoSearch("no search provider is configured")
