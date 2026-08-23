"""The loaf, end to end. If it works for a tangzhong loaf it works for a radiator."""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from context import const, engine, models, store, util

LOAF = [
    {"instruction": "200 g wholemeal flour", "ingredients": ["wholemeal flour"]},
    {"instruction": "7 g salt", "ingredients": ["salt"]},
    {"instruction": "5 g dried yeast", "ingredients": ["yeast"]},
    {"instruction": "Chopped rosemary, 10 g", "ingredients": ["rosemary"]},
    {"instruction": "First prove, 45 minutes", "duration_s": 2700, "awaits": "timer"},
    {"instruction": "Knock back and shape", "ingredients": ["dough"]},
    {"instruction": "Programme four, medium crust", "duration_s": 11400, "awaits": "timer"},
]


class Kitchen(unittest.TestCase):
    """A bread machine, a loaf, and a run part way through it."""

    def setUp(self) -> None:
        path = Path(tempfile.mkdtemp()) / "stepwise.db"
        self.store = store.Store(str(path)).connect()
        self.addCleanup(self.store.close)
        self.engine = engine.Engine(self.store, engine.Settings())
        self.subject_id = self.engine.subject_save(
            "the bread machine", "bread_machine", make="Panasonic", model="SD-2500"
        ).data["subject_id"]
        self.procedure_id = self.engine.procedure_plan(
            "Rosemary tangzhong loaf", LOAF, subject_id=self.subject_id
        ).data["procedure_id"]

    def start(self, reference: str = "the rosemary loaf") -> str:
        return self.engine.run_start(
            self.procedure_id, reference=reference, subject_id=self.subject_id
        ).data["run_id"]

    def age(self, run_id: str, minutes: float) -> None:
        """Push a run's last contact into the past."""
        run = self.store.get_run(run_id)
        assert run is not None
        run.updated_at = util.iso(util.utcnow() - timedelta(minutes=minutes))
        self.store.save_run(run)


class TestPlanningAndStarting(Kitchen):
    def test_planning_stores_steps_but_does_not_start_anything(self) -> None:
        reply = self.engine.procedure_plan("Descale the dishwasher", LOAF[:2])
        self.assertEqual(reply.data["steps"], 2)
        self.assertEqual(self.store.open_runs(), [])
        self.assertIn("Shall I call it", reply.speech)

    def test_planning_the_same_title_twice_replaces_rather_than_duplicates(self) -> None:
        again = self.engine.procedure_plan(
            "Rosemary tangzhong loaf", LOAF[:3], subject_id=self.subject_id
        )
        self.assertTrue(again.data["replaced_existing"])
        self.assertEqual(again.data["procedure_id"], self.procedure_id)
        self.assertEqual(len(self.store.list_procedures()), 1)

    def test_starting_returns_step_one_and_the_reference(self) -> None:
        reply = self.engine.run_start(
            self.procedure_id, reference="the rosemary loaf", subject_id=self.subject_id
        )
        self.assertIn("200 grams wholemeal flour", reply.speech)
        self.assertEqual(reply.data["reference"], "the rosemary loaf")
        self.assertEqual(reply.data["step"]["n"], 1)
        self.assertEqual(reply.data["total_steps"], 7)

    def test_a_run_owns_its_steps_from_the_start(self) -> None:
        run_id = self.start()
        self.assertEqual(len(self.store.get_run_steps(run_id)), 7)


class TestWhereWereWe(Kitchen):
    def test_where_takes_no_arguments_and_answers_anyway(self) -> None:
        self.start()
        reply = self.engine.run_where()
        self.assertEqual(reply.data["step"]["n"], 1)
        self.assertEqual(reply.data["state"], const.HOT)

    def test_nothing_on_the_go_is_said_plainly(self) -> None:
        self.assertEqual(self.engine.run_where().speech, "Nothing on the go.")

    def test_hot_assumes_warm_names_cold_offers(self) -> None:
        run_id = self.start()

        self.assertEqual(self.engine.run_where().data["state"], const.HOT)

        self.age(run_id, 90)
        warm = self.engine.run_where()
        self.assertEqual(warm.data["state"], const.WARM)
        self.assertTrue(warm.speech.startswith("On the rosemary loaf,"))

        self.age(run_id, 60 * 8)
        cold = self.engine.run_where()
        self.assertEqual(cold.data["state"], const.COLD)
        self.assertIn("Carry on?", cold.speech)
        self.assertIn("You still have the rosemary loaf part done", cold.speech)

    def test_the_thresholds_are_configuration_not_code(self) -> None:
        run_id = self.start()
        self.age(run_id, 90)
        patient = engine.Engine(self.store, engine.Settings(hot_minutes=180, cold_hours=12))
        self.assertEqual(patient.run_where().data["state"], const.HOT)

    def test_any_contact_resets_the_clock(self) -> None:
        run_id = self.start()
        self.age(run_id, 90)
        self.engine.run_note("gone a bit sticky")
        self.assertEqual(self.engine.run_where().data["state"], const.HOT)

    def test_several_live_runs_are_named_rather_than_assumed(self) -> None:
        first = self.start("the rosemary loaf")
        second = self.start("the white loaf")
        self.age(first, 200)
        self.age(second, 100)
        reply = self.engine.run_where()
        self.assertEqual(reply.data["status"], "several_live")
        self.assertIn("the white loaf", reply.speech)
        self.assertIn("the rosemary loaf", reply.speech)


class TestAddressing(Kitchen):
    """Three kinds of utterance, and only one of them moves the run forward."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.start()

    def test_advance_moves_the_pointer_and_records_the_time(self) -> None:
        reply = self.engine.run_advance()
        self.assertEqual(reply.data["step"]["n"], 2)
        self.assertEqual(reply.data["completed_step"], 1)
        advanced = self.store.events(self.run_id, [const.EVENT_ADVANCED])
        self.assertEqual(len(advanced), 1)
        self.assertIsNotNone(util.parse_iso(advanced[0].at))

    def test_an_aside_answers_without_moving_anything(self) -> None:
        self.engine.run_advance()
        before = self.store.get_run(self.run_id).current_step
        reply = self.engine.run_ask("how many calories is that?")
        self.assertEqual(self.store.get_run(self.run_id).current_step, before)
        self.assertTrue(reply.data["pointer_unchanged"])

    def test_an_aside_about_the_clock_is_answered_from_the_clock(self) -> None:
        reply = self.engine.run_ask("how long has the tangzhong been resting?")
        self.assertEqual(reply.data["answered_from"], "clock")
        self.assertIn("on this step", reply.speech)

    def test_asking_what_is_left_lists_the_steps(self) -> None:
        reply = self.engine.run_ask("what's left?")
        self.assertIn("step 2, 7 grams salt", reply.speech)
        self.assertNotIn("a few", reply.speech.lower())

    def test_asking_what_a_quantity_was_answers_from_the_procedure(self) -> None:
        self.engine.run_advance()
        reply = self.engine.run_ask("what was the flour weight again?")
        self.assertIn("200 grams wholemeal flour", reply.speech)
        self.assertEqual(reply.data["answered_from"], "procedure")

    def test_an_unanswerable_aside_hands_context_to_the_model(self) -> None:
        reply = self.engine.run_ask("is it ok to use dried rosemary?")
        self.assertEqual(reply.data["status"], "needs_answer")
        self.assertEqual(reply.data["answered_from"], "model")
        self.assertIn("rosemary", reply.data["ingredients"])

    def test_a_note_is_recorded_against_the_step_and_the_time(self) -> None:
        self.engine.run_advance()
        self.engine.run_note("it's gone a bit sticky")
        notes = self.store.events(self.run_id, [const.EVENT_NOTE])
        self.assertEqual(notes[0].text, "it's gone a bit sticky")
        self.assertEqual(notes[0].step_n, 2)
        self.assertEqual(self.store.get_run(self.run_id).current_step, 2)

    def test_positioning_by_description_reports_where_it_landed(self) -> None:
        reply = self.engine.run_goto("the bit where the rosemary goes in")
        self.assertEqual(reply.data["step"]["n"], 4)
        self.assertTrue(reply.speech.startswith("Right, step 4,"))

    def test_positioning_backwards_by_what_is_missing_not_by_the_word_back(self) -> None:
        for _ in range(4):
            self.engine.run_advance()
        reply = self.engine.run_goto("go back, I've not done the salt yet")
        self.assertEqual(reply.data["step"]["n"], 2)

    def test_an_ordinal_picks_the_right_one_of_a_repeated_step(self) -> None:
        self.engine.procedure_plan(
            "Two prove loaf",
            [
                {"instruction": "Mix"},
                {"instruction": "First prove, 45 minutes", "duration_s": 2700},
                {"instruction": "Knock back"},
                {"instruction": "Second prove, 40 minutes", "duration_s": 2400},
            ],
        )
        procedure = self.store.find_procedure("Two prove loaf")
        run_id = self.engine.run_start(procedure.id, reference="the white loaf").data["run_id"]
        reply = self.engine.run_goto("skip to the second prove", run_id=run_id)
        self.assertEqual(reply.data["step"]["n"], 4)

    def test_an_unclear_jump_asks_rather_than_moving(self) -> None:
        before = self.store.get_run(self.run_id).current_step
        reply = self.engine.run_goto("the thing with the stuff")
        self.assertEqual(reply.data["status"], "unsure")
        self.assertEqual(self.store.get_run(self.run_id).current_step, before)
        self.assertIn("not sure which you mean", reply.speech)


class TestFinishing(Kitchen):
    def test_advancing_past_the_last_step_closes_the_run(self) -> None:
        run_id = self.start()
        for _ in range(len(LOAF)):
            reply = self.engine.run_advance()
        self.assertEqual(reply.data["status"], const.RUN_DONE)
        self.assertIn("That's the rosemary loaf done.", reply.speech)
        self.assertEqual(self.store.get_run(run_id).status, const.RUN_DONE)
        self.assertEqual(self.engine.run_where().speech, "Nothing on the go.")

    def test_finishing_early_records_how_it_went(self) -> None:
        run_id = self.start()
        self.engine.run_advance()
        reply = self.engine.run_finish(outcome="a bit dense, needs more water")
        self.assertEqual(reply.data["outcome"], "a bit dense, needs more water")
        run = self.store.get_run(run_id)
        self.assertEqual(run.status, const.RUN_DONE)
        self.assertEqual(run.outcome, "a bit dense, needs more water")

    def test_leaving_it_is_not_failure(self) -> None:
        self.start()
        reply = self.engine.run_finish(abandoned=True)
        self.assertEqual(reply.data["status"], const.RUN_ABANDONED)
        self.assertIn("Left the rosemary loaf there.", reply.speech)
        for shaming in ("never", "failed", "abandoned"):
            self.assertNotIn(shaming, reply.speech.lower())

    def test_the_event_log_is_the_readable_history(self) -> None:
        run_id = self.start()
        self.engine.run_advance(note="all in")
        self.engine.run_note("gone a bit sticky")
        self.engine.run_ask("how long?")
        self.engine.run_finish(outcome="good")
        kinds = [event.kind for event in self.store.events(run_id)]
        self.assertEqual(
            kinds,
            [
                const.EVENT_RUN_STARTED,
                const.EVENT_ADVANCED,
                const.EVENT_NOTE,
                const.EVENT_ASKED,
                const.EVENT_FINISHED,
            ],
        )


class TestCorrections(Kitchen):
    """The differentiating feature (section 9)."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.start()

    def test_an_unknown_claim_is_scoped_to_make_and_model_for_searching(self) -> None:
        reply = self.engine.run_challenge("my machine takes yeast first and salt at the top")
        self.assertEqual(reply.data["status"], "unknown")
        self.assertIn("Panasonic SD-2500", reply.data["search_query"])
        self.assertEqual([step["n"] for step in reply.data["affected_steps"]], [2, 3])

    def test_a_claim_about_an_unidentified_subject_asks_which(self) -> None:
        nameless = self.engine.procedure_plan("Bleed a radiator", LOAF[:2]).data["procedure_id"]
        run_id = self.engine.run_start(nameless, reference="the landing radiator").data["run_id"]
        reply = self.engine.run_challenge("this one needs a square key", run_id=run_id)
        self.assertEqual(reply.data["status"], "needs_subject")

    def test_make_and_model_are_asked_for_when_they_change_the_answer(self) -> None:
        bare = self.engine.subject_save("the spare machine", "bread_machine").data["subject_id"]
        run_id = self.engine.run_start(
            self.procedure_id, reference="the spare loaf", subject_id=bare
        ).data["run_id"]
        reply = self.engine.run_challenge("yeast goes in first on this one", run_id=run_id)
        self.assertEqual(reply.data["status"], "needs_make_model")
        self.assertIn("What make and model", reply.speech)

    def test_a_known_quirk_agrees_out_loud(self) -> None:
        self.store.add_quirk(
            models.Quirk(self.subject_id, "yeast first, salt at the top")
        )
        reply = self.engine.run_challenge("yeast first, salt at the top")
        self.assertEqual(reply.data["status"], "agrees")
        self.assertIn("I have that noted", reply.speech)

    def test_a_contradiction_is_said_out_loud_never_silently_overruled(self) -> None:
        self.store.add_quirk(models.Quirk(self.subject_id, "yeast first, salt at the top"))
        reply = self.engine.run_challenge("no, salt first and yeast at the bottom")
        self.assertEqual(reply.data["status"], "conflicts")
        self.assertIn("Shall I re-check?", reply.speech)
        self.assertIn("SD-2500", reply.speech)

    def test_reordering_changes_this_run_and_not_the_template(self) -> None:
        reply = self.engine.run_amend(
            reorder=[3, 1, 2, 4, 5, 6, 7],
            why="yeast first, salt at the top on this machine",
            scope=const.SCOPE_SUBJECT,
            learned_from=const.LEARNED_FROM_WEB,
            confidence=const.CONFIDENCE_HIGH,
        )
        self.assertIn("Reordered.", reply.speech)
        run_steps = [step.instruction for step in self.store.get_run_steps(self.run_id)]
        self.assertEqual(run_steps[0], "5 g dried yeast")
        template = [step.instruction for step in self.store.get_procedure(self.procedure_id).steps]
        self.assertEqual(template[0], "200 g wholemeal flour")

    def test_reordering_goes_back_to_the_first_thing_not_yet_done(self) -> None:
        """Told "yeast first" before the yeast is in, the answer is the yeast.

        Following the step they happened to be on would leave the yeast out of
        the loaf entirely, which is the whole reason they corrected you.
        """
        self.engine.run_advance()  # the flour is in; on the salt
        reply = self.engine.run_amend(reorder=[3, 1, 2, 4, 5, 6, 7])
        run = self.store.get_run(self.run_id)
        self.assertEqual(run.current_step, 1)
        self.assertEqual(self.engine.run_where().data["step"]["instruction"], "5 g dried yeast")
        self.assertIn("Back to step 1", reply.speech)

    def test_reordering_does_not_send_you_back_over_finished_work(self) -> None:
        for _ in range(3):  # flour, salt and yeast are all in
            self.engine.run_advance()
        self.engine.run_amend(reorder=[3, 1, 2, 4, 5, 6, 7])
        run = self.store.get_run(self.run_id)
        self.assertEqual(run.current_step, 4)
        self.assertEqual(
            self.engine.run_where().data["step"]["instruction"], "Chopped rosemary, 10 g"
        )

    def test_a_subject_scoped_amendment_writes_a_quirk_with_its_source(self) -> None:
        reply = self.engine.run_amend(
            reorder=[3, 1, 2, 4, 5, 6, 7],
            why="yeast first, salt at the top",
            scope=const.SCOPE_SUBJECT,
            learned_from=const.LEARNED_FROM_WEB,
            confidence=const.CONFIDENCE_HIGH,
        )
        quirks = self.store.quirks(self.subject_id)
        self.assertEqual(len(quirks), 1)
        self.assertEqual(quirks[0].claim, "yeast first, salt at the top")
        self.assertEqual(quirks[0].learned_from, const.LEARNED_FROM_WEB)
        self.assertEqual(quirks[0].id, reply.data["quirk_id"])

    def test_a_run_scoped_amendment_leaves_the_subject_alone(self) -> None:
        self.engine.run_amend(2, "9 g salt", why="bigger loaf today")
        self.assertEqual(self.store.quirks(self.subject_id), [])
        self.assertEqual(self.store.get_run_steps(self.run_id)[1].instruction, "9 g salt")

    def test_amending_the_procedure_changes_the_template_too(self) -> None:
        self.engine.run_amend(
            2, "7 g fine salt", why="fine salt dissolves", scope=const.SCOPE_PROCEDURE
        )
        template = self.store.get_procedure(self.procedure_id)
        self.assertEqual(template.step(2).instruction, "7 g fine salt")

    def test_an_amendment_survives_being_put_down_and_picked_up(self) -> None:
        self.engine.run_amend(2, "9 g salt")
        reopened = engine.Engine(store.Store(self.store.path).connect())
        self.addCleanup(reopened.store.close)
        self.assertEqual(reopened.store.get_run_steps(self.run_id)[1].instruction, "9 g salt")


class TestQuirks(Kitchen):
    def test_a_quirk_is_stated_before_it_is_relied_on(self) -> None:
        self.store.add_quirk(
            models.Quirk(
                self.subject_id,
                "yeast goes in before the salt",
                learned_from=const.LEARNED_FROM_USER,
                last_confirmed_at=util.iso(),
            )
        )
        self.start()
        reply = self.engine.run_advance()  # onto the salt step
        self.assertTrue(reply.data["quirks_stated"])
        self.assertIn("On yours, yeast goes in before the salt.", reply.speech)
        self.assertFalse(reply.data["quirks_stated"][0]["reconfirm"])

    def test_a_web_learned_quirk_is_re_confirmed_rather_than_asserted(self) -> None:
        self.store.add_quirk(
            models.Quirk(
                self.subject_id,
                "salt goes in last",
                learned_from=const.LEARNED_FROM_WEB,
                last_confirmed_at=None,
            )
        )
        self.start()
        reply = self.engine.run_advance()
        stated = reply.data["quirks_stated"][0]
        self.assertTrue(stated["reconfirm"])
        self.assertIn("Still right?", reply.speech)

    def test_a_quirk_about_one_subject_is_never_applied_to_another(self) -> None:
        other = self.engine.subject_save(
            "the spare machine", "bread_machine", make="Zojirushi", model="BB-PDC20"
        ).data["subject_id"]
        self.store.add_quirk(models.Quirk(other, "yeast goes in before the salt"))
        self.start()
        reply = self.engine.run_advance()
        self.assertEqual(reply.data["quirks_stated"], [])

    def test_stating_a_quirk_counts_it_and_leaves_a_trail(self) -> None:
        quirk = self.store.add_quirk(
            models.Quirk(
                self.subject_id, "yeast goes in before the salt", last_confirmed_at=util.iso()
            )
        )
        run_id = self.start()
        self.engine.run_advance()
        self.assertEqual(self.store.get_quirk(quirk.id).times_applied, 1)
        stated = self.store.events(run_id, [const.EVENT_QUIRK_STATED])
        self.assertEqual(len(stated), 1)


class TestHousekeeping(Kitchen):
    def test_finishing_prunes_old_runs_but_keeps_the_recent_ones(self) -> None:
        engine_small = engine.Engine(
            self.store, engine.Settings(archive_keep_per_subject=2)
        )
        for index in range(4):
            run_id = engine_small.run_start(
                self.procedure_id, reference=f"loaf {index}", subject_id=self.subject_id
            ).data["run_id"]
            engine_small.run_finish(run_id=run_id)
        closed = [
            run for run in self.store.recent_runs(self.subject_id, limit=50)
            if run.status == const.RUN_DONE
        ]
        self.assertEqual(len(closed), 2)


if __name__ == "__main__":
    unittest.main()


class TestSayingIsNotConfirming(Kitchen):
    """Only the person can confirm a quirk (section 9, rule 2)."""

    def test_a_web_quirk_keeps_asking_until_the_person_answers(self) -> None:
        self.store.add_quirk(
            models.Quirk(
                self.subject_id,
                "salt goes in last",
                learned_from=const.LEARNED_FROM_WEB,
                last_confirmed_at=None,
            )
        )
        self.start()
        said_once = self.engine.run_advance()
        self.assertTrue(said_once.data["quirks_stated"][0]["reconfirm"])

        # Saying it aloud must not mark it confirmed, or it never asks again.
        self.engine.run_goto("step 1")
        said_twice = self.engine.run_advance()
        self.assertTrue(
            said_twice.data["quirks_stated"][0]["reconfirm"],
            "stating a quirk confirmed it, which is the bug this test exists for",
        )

    def test_confirming_it_settles_it(self) -> None:
        quirk = self.store.add_quirk(
            models.Quirk(
                self.subject_id, "salt goes in last", learned_from=const.LEARNED_FROM_WEB
            )
        )
        run_id = self.start()
        self.engine.run_advance()
        reply = self.engine.quirk_confirm(quirk.id, still_right=True)
        self.assertEqual(reply.data["status"], "confirmed")
        self.assertIsNotNone(self.store.get_quirk(quirk.id).last_confirmed_at)
        self.assertTrue(self.store.events(run_id, [const.EVENT_QUIRK_CONFIRMED]))

        self.engine.run_goto("step 1")
        self.assertFalse(self.engine.run_advance().data["quirks_stated"][0]["reconfirm"])

    def test_rejecting_it_forgets_it_and_asks_what_is_right(self) -> None:
        quirk = self.store.add_quirk(models.Quirk(self.subject_id, "salt goes in last"))
        self.start()
        reply = self.engine.quirk_confirm(quirk.id, still_right=False)
        self.assertEqual(reply.data["status"], "retracted")
        self.assertIn("What's the case now?", reply.speech)
        self.assertEqual(self.store.quirks(self.subject_id), [])

    def test_a_loosely_matched_subject_is_re_confirmed_against(self) -> None:
        # A thing whose label says nothing about what sort of thing it is, so
        # naming the category is the only way to reach it.
        vague = self.engine.subject_save("the big one", "radiator").data["subject_id"]
        self.store.add_quirk(
            models.Quirk(vague, "salt goes in last", last_confirmed_at=util.iso())
        )
        matched = self.engine.subject_resolve("the radiator", user_id="ian")
        self.assertEqual(matched.data["subject_id"], vague)
        self.assertTrue(matched.data["loose"], "matched by category, not by name")

        run_id = self.engine.run_start(
            self.procedure_id, reference="the loose loaf", subject_id=vague, user_id="ian"
        ).data["run_id"]
        self.assertTrue(self.store.get_run(run_id).subject_loose)
        stated = self.engine.run_advance(run_id=run_id).data["quirks_stated"]
        self.assertTrue(stated[0]["reconfirm"])
        self.assertIn("more than one", stated[0]["because"])

    def test_something_said_this_session_reopens_a_settled_quirk(self) -> None:
        self.store.add_quirk(
            models.Quirk(
                self.subject_id, "yeast first, salt at the top", last_confirmed_at=util.iso()
            )
        )
        self.start()
        settled = self.engine.run_advance()
        self.assertFalse(settled.data["quirks_stated"][0]["reconfirm"])

        self.engine.run_challenge("no, salt first and yeast at the bottom")
        self.engine.run_goto("step 1")
        reopened = self.engine.run_advance()
        self.assertTrue(reopened.data["quirks_stated"][0]["reconfirm"])
        self.assertIn("said something different", reopened.data["quirks_stated"][0]["because"])


class TestSettingsThatDoSomething(Kitchen):
    def test_advancing_on_any_speech_stops_saying_tell_me_when(self) -> None:
        talkative = engine.Engine(
            self.store, engine.Settings(confirmation_style=const.CONFIRM_ANY_SPEECH)
        )
        reply = talkative.run_start(
            self.procedure_id, reference="the quick loaf", subject_id=self.subject_id
        )
        self.assertNotIn("Tell me when", reply.speech)
        self.assertIn("200 grams wholemeal flour", reply.speech)

    def test_always_ask_proposes_nothing(self) -> None:
        asker = engine.Engine(
            self.store, engine.Settings(reference_naming=const.NAMING_ALWAYS_ASK)
        )
        reply = asker.procedure_plan("Descale the kettle", LOAF[:2])
        self.assertIn("What shall I call it?", reply.speech)
        self.assertIsNone(reply.data["proposed_reference"])

    def test_never_ask_says_nothing_about_names(self) -> None:
        quiet = engine.Engine(self.store, engine.Settings(reference_naming=const.NAMING_NEVER_ASK))
        reply = quiet.procedure_plan("Descale the kettle", LOAF[:2])
        self.assertNotIn("call it", reply.speech)

    def test_imperial_changes_what_is_said_not_what_is_stored(self) -> None:
        imperial = engine.Engine(self.store, engine.Settings(units=const.UNITS_IMPERIAL))
        reply = imperial.run_start(
            self.procedure_id, reference="the imperial loaf", subject_id=self.subject_id
        )
        self.assertIn("7.1 ounces", reply.speech)
        stored = self.store.get_run_steps(reply.data["run_id"])[0]
        self.assertEqual(stored.instruction, "200 g wholemeal flour")


class TestSubjectIdentity(Kitchen):
    def test_a_contradiction_is_a_fork_rather_than_an_overwrite(self) -> None:
        reply = self.engine.subject_save(
            "the bread machine",
            "bread_machine",
            make="Panasonic",
            model="SD-ZB2512",
            subject_id=self.subject_id,
        )
        self.assertEqual(reply.data["status"], "fork_or_amend")
        self.assertIn("Different one, or has this one changed?", reply.speech)
        self.assertEqual(self.store.get_subject(self.subject_id).model, "SD-2500")

    def test_a_confirmed_change_is_applied(self) -> None:
        self.engine.subject_save(
            "the bread machine",
            "bread_machine",
            make="Panasonic",
            model="SD-ZB2512",
            subject_id=self.subject_id,
            changed=True,
        )
        self.assertEqual(self.store.get_subject(self.subject_id).model, "SD-ZB2512")


class TestSubjectAwareSettings(Kitchen):
    """Phase 4: a machine that knows its own programmes says which one this is."""

    def setUp(self) -> None:
        super().setUp()
        self.engine.subject_save(
            "the bread machine",
            "bread_machine",
            subject_id=self.subject_id,
            attributes={
                "programmes": {
                    "4": {"name": "wholemeal", "duration_s": 11400},
                    "1": {"name": "basic"},
                }
            },
        )
        self.procedure_id = self.engine.procedure_plan(
            "Programme loaf",
            [
                {"instruction": "200 g wholemeal flour"},
                {"instruction": "Programme four", "awaits": "timer", "settings": {"programme": 4}},
            ],
            subject_id=self.subject_id,
        ).data["procedure_id"]

    def test_the_programme_is_named_and_its_length_offered(self) -> None:
        self.engine.run_start(
            self.procedure_id, reference="the programme loaf", subject_id=self.subject_id
        )
        reply = self.engine.run_advance()
        self.assertIn("That's the wholemeal one on yours.", reply.speech)
        self.assertIn("Shall I set a timer for 3 hours 10", reply.speech)
        self.assertIn("that's the programme length", reply.speech.lower())
        self.assertEqual(reply.data["timer_offer_seconds"], 11400)
        self.assertEqual(reply.data["subject_setting"], "wholemeal")

    def test_an_unknown_machine_simply_gets_nothing_extra(self) -> None:
        plain = self.engine.subject_save("the spare machine", "bread_machine").data["subject_id"]
        self.engine.run_start(self.procedure_id, reference="the spare loaf", subject_id=plain)
        reply = self.engine.run_advance()
        self.assertNotIn("on yours", reply.speech)
        self.assertIsNone(reply.data["subject_setting"])

    def test_a_timer_is_recorded_against_the_run(self) -> None:
        run_id = self.engine.run_start(
            self.procedure_id, reference="the programme loaf", subject_id=self.subject_id
        ).data["run_id"]
        reply = self.engine.run_timer(11400, name="the programme loaf")
        self.assertIn("3 hours 10", reply.speech)
        self.assertTrue(reply.data["pointer_unchanged"])
        started = self.store.events(run_id, [const.EVENT_TIMER_STARTED])
        self.assertEqual(started[0].data["seconds"], 11400)


class TestResolutionSessions(Kitchen):
    def test_an_intent_is_held_only_until_it_becomes_a_run(self) -> None:
        self.engine.resolve_intent("I want to make a rosemary tangzhong loaf", user_id="ian")
        held = self.engine.session("ian")
        assert held is not None
        self.assertIn("rosemary", held.words)

        self.engine.run_start(
            self.procedure_id, reference="the rosemary loaf", subject_id=self.subject_id,
            user_id="ian",
        )
        self.assertIsNone(
            self.engine.session("ian"), "it became a run, so it is no longer an intent"
        )

    def test_an_intent_left_alone_expires(self) -> None:
        self.engine.resolve_intent("something half said", user_id="ian")
        held = self.engine.session("ian")
        assert held is not None
        held.started_at = "2020-01-01T00:00:00+00:00"
        self.assertIsNone(self.engine.session("ian"))

    def test_questions_already_asked_are_not_asked_twice(self) -> None:
        self.engine.procedure_plan(
            "Tangzhong loaf",
            [{"instruction": "50 g tangzhong", "ingredients": ["tangzhong"]}],
        )
        first = self.engine.resolve_intent("make me a yang zoong loaf", user_id="ian")
        self.assertEqual(first.data["status"], "confirm_hearing")
        held = self.engine.session("ian")
        assert held is not None
        self.assertEqual(len(held.asked), 1)
        self.engine.resolve_intent("make me a yang zoong loaf", user_id="ian")
        self.assertEqual(len(self.engine.session("ian").asked), 1)
