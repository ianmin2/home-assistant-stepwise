"""The pluggable bits: reading whatever a provider sends back, and degrading
honestly when there is no provider at all."""

from __future__ import annotations

import ast
import asyncio
import unittest
from pathlib import Path

from context import memory_base, search_base, search_none

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "stepwise"


class TestReadingAResponse(unittest.TestCase):
    """Anything works, including whatever somebody already runs."""

    def test_a_dotted_path_reaches_into_a_response(self) -> None:
        payload = {"response": {"results": [{"content": "yeast first"}, {"content": "no"}]}}
        self.assertEqual(
            search_base.dig(payload, "response.results.0.content"), "yeast first"
        )

    def test_an_empty_path_is_the_whole_response(self) -> None:
        self.assertEqual(search_base.dig({"a": 1}, ""), {"a": 1})

    def test_a_path_that_goes_nowhere_is_nothing_rather_than_an_error(self) -> None:
        self.assertIsNone(search_base.dig({"a": 1}, "b.c"))
        self.assertIsNone(search_base.dig({"a": [1]}, "a.9"))
        self.assertIsNone(search_base.dig("a string", "a.b"))

    def test_results_are_made_of_whatever_shape_came_back(self) -> None:
        from_dicts = search_base.to_results(
            [{"title": "Panasonic manual", "content": "Yeast first", "url": "http://x"}]
        )
        self.assertEqual(from_dicts[0].title, "Panasonic manual")
        self.assertEqual(from_dicts[0].snippet, "Yeast first")
        self.assertEqual(from_dicts[0].url, "http://x")

        from_strings = search_base.to_results(["yeast first, salt at the top"])
        self.assertEqual(from_strings[0].snippet, "yeast first, salt at the top")

        self.assertEqual(search_base.to_results(None), [])

    def test_only_a_handful_of_results_are_carried(self) -> None:
        many = search_base.to_results([f"result {n}" for n in range(20)])
        self.assertEqual(len(many), 5)


class TestNoProvider(unittest.TestCase):
    def test_it_says_it_cannot_rather_than_returning_nothing_found(self) -> None:
        provider = search_none.NoSearch("no search provider is configured")
        findings = asyncio.run(provider.search("Panasonic SD-2500 yeast first"))
        self.assertFalse(findings.found)
        self.assertEqual(findings.unavailable, "no search provider is configured")
        self.assertEqual(findings.as_dict()["provider"], "none")


class TestAdapterSurface(unittest.TestCase):
    """The adapters import Home Assistant, so this reads them instead."""

    def test_every_configured_provider_has_an_adapter(self) -> None:
        source = (INTEGRATION / "search" / "__init__.py").read_text()
        for constant in ("SEARCH_REST_COMMAND", "SEARCH_BUNDLED", "SEARCH_NONE"):
            self.assertIn(constant, source)
        for module in ("base", "bundled", "none", "rest_command"):
            self.assertTrue((INTEGRATION / "search" / f"{module}.py").exists(), module)

    def test_a_provider_without_its_settings_degrades_to_nothing(self) -> None:
        tree = ast.parse((INTEGRATION / "search" / "__init__.py").read_text())
        source = ast.unparse(tree)
        self.assertIn("NoSearch('no rest_command was named in the settings')", source)
        self.assertIn("NoSearch('the bundled provider add-on has no address configured')", source)

    def test_the_memory_backend_always_has_the_builtin_behind_it(self) -> None:
        source = (INTEGRATION / "memory" / "__init__.py").read_text()
        self.assertIn("builtin = BuiltinMemory(hass, store)", source)
        self.assertIn("fallback=builtin", source)

    def test_the_upstream_adapter_says_it_is_provisional(self) -> None:
        source = (INTEGRATION / "memory" / "ha_ai_memory.py").read_text()
        self.assertIn("Provisional", source)
        self.assertIn("agree the integration point", source)


class TestFacts(unittest.TestCase):
    def test_a_fact_carries_where_it_came_from(self) -> None:
        fact = memory_base.Fact(text="the machine is a Panasonic", source="user", id="fct_1")
        self.assertEqual(
            fact.as_dict(), {"id": "fct_1", "text": "the machine is a Panasonic", "source": "user"}
        )


if __name__ == "__main__":
    unittest.main()
