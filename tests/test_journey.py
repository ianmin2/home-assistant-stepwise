"""The canonical example, played end to end, with a day in the middle.

This is the acceptance test the design asks for: if it works for a tangzhong
loaf it works for a radiator.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

from context import const, engine, store, util

RECIPE = [
    {"instruction": "200 g wholemeal flour", "ingredients": ["wholemeal flour"]},
    {"instruction": "7 g salt", "ingredients": ["salt"]},
    {"instruction": "5 g dried yeast", "ingredients": ["yeast"]},
    {"instruction": "Chopped rosemary, 10 g", "ingredients": ["rosemary"]},
    {
        "instruction": "Programme four, medium crust",
        "duration_s": 11400,
        "awaits": "timer",
        "settings": {"programme": 4, "crust": "medium"},
    },
]


class TestADayApart(unittest.TestCase):
    """Fetch a recipe today, bake tomorrow, be interrupted in the middle."""

    def setUp(self) -> None:
        self.store = store.Store(str(Path(tempfile.mkdtemp()) / "stepwise.db")).connect()
        self.addCleanup(self.store.close)
        self.engine = engine.Engine(self.store, engine.Settings())

    def put_it_down(self, run_id: str, hours: float) -> None:
        """Time passes. That is all that happens."""
        run = self.store.get_run(run_id)
        assert run is not None
        run.updated_at = util.iso(util.utcnow() - timedelta(hours=hours))
        self.store.save_run(run)

    def test_the_whole_thing(self) -> None:
        # "I'd like to make a rosemary tangzhong loaf on my Panasonic bread machine."
        machine = self.engine.subject_save(
            "the bread machine", "bread_machine", make="Panasonic", model="SD-2500"
        ).data["subject_id"]
        planned = self.engine.procedure_plan(
            "Rosemary tangzhong loaf", RECIPE, subject_id=machine, source=const.SOURCE_WEB
        )
        self.assertIn("Shall I call it", planned.speech)

        # Nothing has started. A plan is not a run.
        self.assertEqual(self.engine.run_where().speech, "Nothing on the go.")

        # (next day) "Guide me step by step."
        begun = self.engine.run_start(
            planned.data["procedure_id"], reference="the rosemary loaf", subject_id=machine
        )
        run_id = begun.data["run_id"]
        self.assertIn("200 grams wholemeal flour", begun.speech)

        # "My machine takes yeast first and salt at the top."
        challenged = self.engine.run_challenge("my machine takes yeast first and salt at the top")
        self.assertEqual(challenged.data["status"], "unknown")
        self.assertIn("Panasonic SD-2500", challenged.data["search_query"])
        self.assertEqual([step["n"] for step in challenged.data["affected_steps"]], [2, 3])

        # The search agrees, so the remaining steps are reordered and the quirk
        # is written against this machine — not against bread machines.
        self.engine.run_amend(
            reorder=[3, 1, 2, 4, 5],
            why="yeast first, salt at the top",
            scope=const.SCOPE_SUBJECT,
            learned_from=const.LEARNED_FROM_WEB,
            confidence=const.CONFIDENCE_HIGH,
        )
        order = [step.instruction for step in self.store.get_run_steps(run_id)]
        self.assertEqual(order[0], "5 g dried yeast")
        # Nothing had been added yet, so the correction goes back to step one.
        self.assertEqual(self.store.get_run(run_id).current_step, 1)
        template = self.store.get_procedure(planned.data["procedure_id"])
        self.assertEqual(template.steps[0].instruction, "200 g wholemeal flour")

        # "Tell me when the ingredients are in." "Done."
        self.engine.run_advance()
        self.engine.run_advance()

        # The doorbell goes. An hour later: "where were we"
        self.put_it_down(run_id, hours=1)
        warm = self.engine.run_where()
        self.assertEqual(warm.data["state"], const.WARM)
        self.assertTrue(warm.speech.startswith("On the rosemary loaf,"))
        self.assertEqual(warm.data["step"]["ingredients"], ["salt"])

        # An aside costs nothing.
        here = self.store.get_run(run_id).current_step
        self.engine.run_ask("how many calories is that?")
        self.assertEqual(self.store.get_run(run_id).current_step, here)

        # An observation, against the step and the time.
        self.engine.run_note("dough's gone a bit sticky")

        self.engine.run_advance()
        self.engine.run_advance()

        # "Programme four, medium crust. Shall I set a timer for three hours ten?"
        last = self.engine.run_where()
        self.assertEqual(last.data["step"]["settings"], {"programme": 4, "crust": "medium"})
        self.assertEqual(last.data["step"]["duration_s"], 11400)

        # It is left overnight. Cold: offered, never assumed, and never scolded.
        self.put_it_down(run_id, hours=14)
        cold = self.engine.run_where()
        self.assertEqual(cold.data["state"], const.COLD)
        self.assertIn("Carry on?", cold.speech)
        for shaming in ("never", "abandoned", "failed", "should have"):
            self.assertNotIn(shaming, cold.speech.lower())

        done = self.engine.run_advance()
        self.assertEqual(done.data["status"], const.RUN_DONE)
        self.assertIn("That's the rosemary loaf done.", done.speech)

        # What is left behind: a readable history, and one quirk about one machine.
        history = [event.kind for event in self.store.events(run_id)]
        self.assertEqual(history[0], const.EVENT_RUN_STARTED)
        self.assertIn(const.EVENT_CHALLENGED, history)
        self.assertIn(const.EVENT_AMENDED, history)
        self.assertIn(const.EVENT_NOTE, history)
        self.assertIn(const.EVENT_ASKED, history)
        self.assertEqual(history[-1], const.EVENT_FINISHED)

        quirks = self.store.quirks(machine)
        self.assertEqual(len(quirks), 1)
        self.assertEqual(quirks[0].claim, "yeast first, salt at the top")
        self.assertEqual(quirks[0].learned_from, const.LEARNED_FROM_WEB)

        # And the next loaf on this machine states it before relying on it.
        again = self.engine.run_start(
            planned.data["procedure_id"], reference="tomorrow's loaf", subject_id=machine
        )
        spoken = again.speech
        for _ in range(3):
            if "On yours, yeast first, salt at the top." in spoken:
                break
            spoken = self.engine.run_advance().speech
        self.assertIn("On yours, yeast first, salt at the top.", spoken)


if __name__ == "__main__":
    unittest.main()


class TestTheCorrectionThatActuallyHappens(unittest.TestCase):
    """The real shape of it, from a text chat that went exactly this way.

    Nobody is interrogated up front. A recipe is fetched, it assumes what most
    machines assume, and the mismatch only surfaces once the reading starts.
    """

    LIQUIDS_FIRST: ClassVar[list[dict]] = [
        {"instruction": "250 ml water", "ingredients": ["water"]},
        {"instruction": "400 g strong white flour", "ingredients": ["flour"]},
        {"instruction": "7 g salt", "ingredients": ["salt"]},
        {"instruction": "5 g dried yeast", "ingredients": ["yeast"]},
        {"instruction": "Programme four, medium crust", "duration_s": 11400, "awaits": "timer"},
    ]

    def setUp(self) -> None:
        self.store = store.Store(str(Path(tempfile.mkdtemp()) / "stepwise.db")).connect()
        self.addCleanup(self.store.close)
        self.engine = engine.Engine(self.store, engine.Settings())

    def test_liquids_first_corrected_to_yeast_first(self) -> None:
        # "A yang zoong rosemary loaf for my bread maker." No machine named, and
        # none asked for: nothing about the recipe needs it yet.
        planned = self.engine.procedure_plan(
            "Rosemary tangzhong loaf", self.LIQUIDS_FIRST, subject_kind="bread_machine"
        )
        run_id = self.engine.run_start(
            planned.data["procedure_id"], reference="the rosemary loaf"
        ).data["run_id"]

        # "Guide me through it step by step." It reads what most machines want.
        self.assertEqual(self.engine.run_where().data["step"]["ingredients"], ["water"])

        # "Oh — but my machine takes the yeast in first."
        asked = self.engine.run_challenge("my machine takes the yeast in first")
        self.assertEqual(asked.data["status"], "needs_subject")
        self.assertEqual(asked.speech, "Which bread machine is it? The order depends on the model.")
        self.assertEqual(asked.data["candidates"], [], "nothing on file, so nothing to choose from")

        # They go and look at it. "It's a Panasonic SD-2500."
        named = self.engine.subject_save(
            "the bread machine", "bread_machine", make="Panasonic", model="SD-2500"
        )
        subject_id = named.data["subject_id"]
        self.assertEqual(named.data["attached_to_run"], run_id, "it belongs to this run now")
        self.assertEqual(self.store.get_run(run_id).subject_id, subject_id)

        # Asked again, it now knows what to look up.
        checked = self.engine.run_challenge("my machine takes the yeast in first")
        self.assertEqual(checked.data["status"], "unknown")
        self.assertIn("Panasonic SD-2500", checked.data["search_query"])
        self.assertEqual([step["n"] for step in checked.data["affected_steps"]], [4])

        # "Ah, that makes sense." Yeast to the front, and remembered for this
        # machine — not for bread machines in general.
        fixed = self.engine.run_amend(
            reorder=[4, 1, 2, 3, 5],
            why="yeast goes in first on this machine",
            scope=const.SCOPE_SUBJECT,
            learned_from=const.LEARNED_FROM_WEB,
            confidence=const.CONFIDENCE_HIGH,
        )

        # Step one, because nothing had gone in yet — and it says what step one
        # now is, since the step under that number has changed.
        self.assertIn("step 1, 5 grams dried yeast", fixed.speech)
        self.assertEqual(self.store.get_run(run_id).current_step, 1)
        here = self.engine.run_where().data["step"]
        self.assertEqual(here["ingredients"], ["yeast"])
        self.assertEqual(here["n"], 1)

        # The template is untouched, and the quirk belongs to the machine.
        template = self.store.get_procedure(planned.data["procedure_id"])
        self.assertEqual(template.steps[0].instruction, "250 ml water")
        quirks = self.store.quirks(subject_id)
        self.assertEqual([quirk.claim for quirk in quirks], ["yeast goes in first on this machine"])

    def test_the_same_correction_after_the_water_is_already_in(self) -> None:
        """If they had already poured the water, it does not send them back to it."""
        planned = self.engine.procedure_plan(
            "Rosemary tangzhong loaf", self.LIQUIDS_FIRST, subject_kind="bread_machine"
        )
        run_id = self.engine.run_start(
            planned.data["procedure_id"], reference="the rosemary loaf"
        ).data["run_id"]
        self.engine.run_advance()  # water in
        self.engine.run_advance()  # flour in

        self.engine.run_amend(reorder=[4, 1, 2, 3, 5])
        remaining = self.engine.run_where().data["step"]
        self.assertEqual(remaining["ingredients"], ["yeast"], "the yeast is still outstanding")
        self.assertEqual(self.store.get_run(run_id).current_step, 1)
