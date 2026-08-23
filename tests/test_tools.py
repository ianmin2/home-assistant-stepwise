"""The tool surface, checked without a Home Assistant install.

`llm_tools.py` imports Home Assistant, so this reads it rather than importing
it: enough to catch a tool that has been renamed, dropped, or left without a
description for the model to read.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "stepwise"

# Section 8.1, plus subject_save, which the correction flow needs: it is told to
# ask for a make and model, so it must be able to store one.
EXPECTED = {
    "resolve_intent",
    "subject_resolve",
    "subject_save",
    "quirk_confirm",
    "procedure_plan",
    "run_start",
    "run_where",
    "run_advance",
    "run_goto",
    "run_ask",
    "run_note",
    "run_challenge",
    "run_amend",
    "run_timer",
    "run_finish",
}


def tool_classes() -> dict[str, ast.ClassDef]:
    tree = ast.parse((INTEGRATION / "llm_tools.py").read_text())
    found: dict[str, ast.ClassDef] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(getattr(base, "id", "") == "StepwiseTool" for base in node.bases):
            continue
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and getattr(statement.targets[0], "id", "") == "name"
                and isinstance(statement.value, ast.Constant)
            ):
                found[statement.value.value] = node
    return found


class TestToolSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = tool_classes()

    def test_every_tool_in_the_design_exists(self) -> None:
        self.assertEqual(set(self.tools), EXPECTED)

    def test_where_never_needs_an_id_to_answer(self) -> None:
        """The rule is that nothing may require the agent to remember an id.

        A name the person said is not an id, so switching by reference is
        allowed; a required argument of any kind is not.
        """
        source = ast.unparse(self.tools["run_where"])
        self.assertNotIn("vol.Required", source)
        self.assertNotIn("run_id", source)

    def test_every_tool_tells_the_model_what_it_is_for(self) -> None:
        for name, node in self.tools.items():
            source = ast.unparse(node)
            self.assertIn("description", source, name)
            self.assertIn("parameters", source, name)

    def test_the_registered_list_matches_the_classes(self) -> None:
        tree = ast.parse((INTEGRATION / "llm_tools.py").read_text())
        registered = []
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TOOLS":
                registered = [element.id for element in node.value.elts]
        self.assertEqual(len(registered), len(EXPECTED))
        self.assertEqual(len(set(registered)), len(registered), "a tool is listed twice")

    def test_the_prompt_carries_the_rules_that_are_load_bearing(self) -> None:
        source = (INTEGRATION / "llm_tools.py").read_text()
        for rule in (
            "One step at a time",
            "quantity before the ingredient",
            "run_ask",
            "never cost somebody their place",
            "Never apply one \\\nsilently",
        ):
            self.assertIn(rule.replace("\\\n", ""), source.replace("\\\n", ""))


class TestPackaging(unittest.TestCase):
    def test_the_manifest_and_translations_line_up_with_the_flows(self) -> None:
        import json

        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], "stepwise")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["single_config_entry"])

        strings = json.loads((INTEGRATION / "strings.json").read_text())
        english = json.loads((INTEGRATION / "translations" / "en.json").read_text())
        self.assertEqual(strings, english, "translations/en.json is out of step")

        flow = ast.parse((INTEGRATION / "config_flow.py").read_text())
        steps = {
            node.name.removeprefix("async_step_")
            for node in ast.walk(flow)
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("async_step_")
        }
        described = set(strings["options"]["step"]) | set(strings["config"]["step"])
        self.assertEqual(steps - described, set(), "a flow step has no strings")


if __name__ == "__main__":
    unittest.main()


class TestBrandAssets(unittest.TestCase):
    """Home Assistant serves integration icons from its own brands repository.

    These are the two files that pull request carries, so their shape is worth
    checking here rather than finding out in review.
    """

    BRANDS = Path(__file__).resolve().parents[1] / "brands" / "custom_integrations" / "stepwise"

    @staticmethod
    def png_size(path: Path) -> tuple[int, int]:
        import struct

        header = path.read_bytes()[:24]
        assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
        width, height = struct.unpack(">II", header[16:24])
        return width, height

    def test_the_icon_is_the_size_brands_asks_for(self) -> None:
        self.assertEqual(self.png_size(self.BRANDS / "icon.png"), (256, 256))
        self.assertEqual(self.png_size(self.BRANDS / "icon@2x.png"), (512, 512))

    def test_the_icon_directory_is_named_after_the_domain(self) -> None:
        import json

        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(self.BRANDS.name, manifest["domain"])

    def test_the_release_workflow_guards_the_version(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn("does not match manifest version", workflow)
