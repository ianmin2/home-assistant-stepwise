"""The tool surface, checked without a Home Assistant install.

`llm_tools.py` imports Home Assistant, so this reads it rather than importing
it: enough to catch a tool that has been renamed, dropped, or left without a
description for the model to read.
"""

from __future__ import annotations

import ast
import json
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
    "run_undo",
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


class TestTheSettingsFormMatchesItsLabels(unittest.TestCase):
    """A setting with a translation and no box is a setting nobody can set.

    `search_response_path` shipped that way: a botched edit passed it to
    voluptuous as a message rather than a key, the real key was written twice,
    and the two markers collapsed into one — so the field never rendered, while
    its labels sat in strings.json looking correct. Nothing caught it, because
    config_flow.py needs Home Assistant to import and so nothing imported it.
    This reads the source instead.
    """

    @staticmethod
    def schema_keys() -> set[str]:
        """Every key the settings form actually builds, read out of the source."""
        tree = ast.parse((INTEGRATION / "config_flow.py").read_text())
        constants = {
            node.targets[0].id: node.value.value
            for node in ast.parse((INTEGRATION / "const.py").read_text()).body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("Optional", "Required") or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in constants:
                found.add(constants[first.id])
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
        return found

    def test_every_translated_setting_has_a_box_to_type_it_in(self) -> None:
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        built = self.schema_keys()
        for section, step in (("config", "user"), ("options", "settings")):
            labelled = set(strings[section]["step"][step]["data"])
            missing = labelled - built
            self.assertEqual(
                missing,
                set(),
                f"{section}/{step} has labels for settings the form never shows: {missing}",
            )

    def test_no_setting_is_offered_without_a_label(self) -> None:
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        labelled = set(strings["config"]["step"]["user"]["data"]) | set(
            strings["options"]["step"]["settings"]["data"]
        )
        for step in ("subjects", "subject", "runs"):
            labelled |= set(strings["options"]["step"][step].get("data", {}))
        unlabelled = {key for key in self.schema_keys() if key not in labelled}
        self.assertEqual(unlabelled, set(), f"no label for: {unlabelled}")

    def test_the_two_translation_files_agree(self) -> None:
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        english = json.loads((INTEGRATION / "translations" / "en.json").read_text())
        self.assertEqual(strings, english)


class TestToolSchemasMatchEngineSignatures(unittest.TestCase):
    """Every tool key must be an engine parameter, or the call dies live.

    `StepwiseTool._run` does `getattr(self.engine, method)(**kwargs)`, so a
    `vol` key with no matching parameter is a TypeError in the middle of a
    voice turn — the kind of drift nothing else can catch, because the tool
    layer needs Home Assistant to import and the engine does not. The 0.2
    review promised this test and first shipped only the claim of it.
    """

    @staticmethod
    def forwarding_tools() -> dict[str, tuple[str, set[str]]]:
        """Tools that splat tool_args straight into an engine method.

        Returns {tool_class: (engine_method, schema_keys)} for every tool whose
        async_call passes **tool_input.tool_args to _run. Tools that rename
        their arguments by hand are checked by their own tests.
        """
        tree = ast.parse((INTEGRATION / "llm_tools.py").read_text())
        found: dict[str, tuple[str, set[str]]] = {}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            method: str | None = None
            splats = False
            keys: set[str] = set()
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if isinstance(func, ast.Attribute) and func.attr == "_run" and call.args:
                    arg = call.args[-1]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        method = arg.value
                    splats = splats or any(
                        kw.arg is None
                        and isinstance(kw.value, ast.Attribute)
                        and kw.value.attr == "tool_args"
                        for kw in call.keywords
                    )
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in ("Required", "Optional")
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                ):
                    keys.add(call.args[0].value)
            if method and splats:
                found[node.name] = (method, keys)
        return found

    def test_every_forwarded_key_is_an_engine_parameter(self) -> None:
        import inspect

        from context import engine

        forwarding = self.forwarding_tools()
        self.assertGreater(len(forwarding), 5, "the AST walk found too little to trust")
        for tool, (method, keys) in forwarding.items():
            target = getattr(engine.Engine, method, None)
            self.assertIsNotNone(target, f"{tool} calls engine.{method}, which does not exist")
            params = set(inspect.signature(target).parameters) - {"self"}
            strays = keys - params
            self.assertEqual(
                strays,
                set(),
                f"{tool} offers {sorted(strays)} which engine.{method} does not take — "
                f"a TypeError on a live voice call",
            )

    def test_every_required_engine_parameter_is_offered(self) -> None:
        import inspect

        from context import engine

        for tool, (method, keys) in self.forwarding_tools().items():
            target = getattr(engine.Engine, method)
            required = {
                name
                for name, param in inspect.signature(target).parameters.items()
                if name not in ("self", "user_id") and param.default is inspect.Parameter.empty
            }
            missing = required - keys
            self.assertEqual(
                missing,
                set(),
                f"engine.{method} requires {sorted(missing)} and {tool} never sends it",
            )


class TestNothingGoesQuiet(unittest.TestCase):
    def test_no_engine_reply_is_ever_born_silent(self) -> None:
        """Section 8.1: every tool returns one speakable line. Three tools
        shipped returning an empty one, each at a moment somebody had been
        waiting longest — so the invariant is now structural, not situational.
        """
        src = (INTEGRATION / "engine.py").read_text()
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Reply"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == ""
            ):
                self.fail(f"engine.py:{node.lineno} builds a Reply with empty speech")


class TestTheManagerSurface(unittest.TestCase):
    """The card can write, so what it can write to is the thing to pin.

    websocket.py imports Home Assistant, so this reads it rather than running
    it — enough to catch a command that quietly gains the power to rewrite the
    one thing that must never be rewritten.
    """

    @staticmethod
    def commands() -> dict[str, str]:
        """Every registered command name, and the function behind it."""
        tree = ast.parse((INTEGRATION / "websocket.py").read_text())
        found: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                for arg in decorator.args:
                    if not isinstance(arg, ast.Dict):
                        continue
                    for key, value in zip(arg.keys, arg.values, strict=False):
                        is_type = (
                            isinstance(key, ast.Call)
                            and key.args
                            and isinstance(key.args[0], ast.Constant)
                            and key.args[0].value == "type"
                        )
                        if is_type and isinstance(value, ast.Constant):
                            found[value.value] = node.name
        return found

    def test_every_declared_command_is_actually_registered(self) -> None:
        source = (INTEGRATION / "websocket.py").read_text()
        declared = self.commands()
        for name in declared:
            self.assertTrue(name.startswith("stepwise/"), name)
        listed = ast.literal_eval(
            source.split("COMMANDS = ", 1)[1].split(")", 1)[0] + ")"
        )
        self.assertEqual(
            {f"stepwise/{item}" for item in listed},
            set(declared),
            "COMMANDS and the registered handlers disagree",
        )

    def test_nothing_offers_to_edit_the_history(self) -> None:
        """`run_events` is append-only: a spine that can be rewritten is not a
        record. The card may read it, export it, and delete a run whole — never
        edit what happened."""
        forbidden = ("event/", "history/", "event/save", "history/edit")
        for name in self.commands():
            for bad in forbidden:
                self.assertNotIn(bad, name, f"{name} would edit the record")

    def test_the_store_is_never_touched_from_the_event_loop(self) -> None:
        """Every command reads through an executor, like the rest of the
        integration — a websocket handler blocking the loop on SQLite is the
        same bug as any other, just harder to notice."""
        source = (INTEGRATION / "websocket.py").read_text()
        tree = ast.parse(source)
        lines = source.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            for method in ("store.get_run(", "store.stats(", "store.open_runs("):
                if method in body:
                    self.assertIn(
                        "async_add_executor_job",
                        body,
                        f"{node.name} touches the store without an executor",
                    )

    def test_destructive_things_ask_first_and_say_what_goes(self) -> None:
        """Every command that destroys something must be reached through the
        confirmation, never called straight from a button."""
        card = (INTEGRATION / "frontend" / "stepwise-card.js").read_text()
        for destructive in (
            "run/delete",
            "subject/delete",
            "procedure/delete",
            "quirk/retract",
            "fact/forget",
        ):
            self.assertNotIn(
                f'_act("{destructive}"',
                card,
                f"{destructive} is called without asking first",
            )
            self.assertIn(f'type: "{destructive}"', card, f"{destructive} has no confirmation")

    def test_the_browsers_own_dialogs_are_never_used(self) -> None:
        """window.confirm freezes the page, ignores the theme, and cannot say
        what is about to be lost. Home Assistant ships a real dialog."""
        card = (INTEGRATION / "frontend" / "stepwise-card.js").read_text()
        for relic in ("window.confirm", "window.alert", "window.prompt", "window.open"):
            self.assertNotIn(relic, card, f"{relic} has no place here")
        self.assertIn("ha-dialog", card, "confirmations should use Home Assistant's dialog")

    def test_deleting_a_run_hands_the_record_back(self) -> None:
        """Destroying the record of something somebody did, without offering
        them a copy first, would be worse than the deletion."""
        card = (INTEGRATION / "frontend" / "stepwise-card.js").read_text()
        self.assertIn("keepsake", card)
        websocket = (INTEGRATION / "websocket.py").read_text()
        self.assertIn('vol.Optional("export_first", default=True)', websocket)

    def test_the_card_ships_with_the_integration(self) -> None:
        card = INTEGRATION / "frontend" / "stepwise-card.js"
        self.assertTrue(card.exists(), "the card file is missing")
        body = card.read_text()
        self.assertIn("stepwise-card", body)
        # It talks over the websocket API, not to entities: nothing it shows
        # should ever reach the recorder database.
        self.assertIn("callWS", body)


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
