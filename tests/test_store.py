"""The store keeps run state, and keeps it bounded."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context import const, models, store, util


def a_store() -> store.Store:
    tmp = tempfile.mkdtemp()
    return store.Store(str(Path(tmp) / "stepwise.db")).connect()


class StoreCase(unittest.TestCase):
    """Every case gets a fresh database and closes it afterwards."""

    def setUp(self) -> None:
        self.store = a_store()
        self.addCleanup(self.store.close)


def a_procedure(title: str = "Rosemary tangzhong loaf") -> models.Procedure:
    return models.Procedure.new(
        title,
        [
            models.Step(n=1, instruction="200 g wholemeal flour", ingredients=["wholemeal flour"]),
            models.Step(n=2, instruction="7 g salt", awaits=const.AWAITS_CONFIRM),
            models.Step(n=3, instruction="Programme four, medium crust", duration_s=11400),
        ],
        subject_kind="bread_machine",
        source=const.SOURCE_WEB,
    )


class TestSubjects(StoreCase):
    def test_roundtrip_keeps_aliases_and_attributes(self) -> None:
        subject = models.Subject.new(
            "the bread machine",
            "bread_machine",
            make="Panasonic",
            model="SD-YR2550",
            aliases=["the panasonic"],
            attributes={"programmes": [1, 2, 3, 4], "has_dispenser": True},
        )
        self.store.save_subject(subject)
        loaded = self.store.get_subject(subject.id)
        assert loaded is not None
        self.assertEqual(loaded.id, "panasonic_sd_yr2550")
        self.assertEqual(loaded.aliases, ["the panasonic"])
        self.assertTrue(loaded.attributes["has_dispenser"])

    def test_retired_subjects_stop_matching_but_stay_readable(self) -> None:
        old = self.store.save_subject(
            models.Subject.new("the winter bike", "bicycle", id="bike_old")
        )
        new = self.store.save_subject(models.Subject.new("the new bike", "bicycle", id="bike_new"))
        self.store.retire_subject(old.id, replaced_by=new.id)
        listed = [subject.id for subject in self.store.list_subjects()]
        self.assertEqual(listed, [new.id])
        recovered = self.store.get_subject(old.id)
        assert recovered is not None
        self.assertEqual(recovered.status, const.SUBJECT_REPLACED)
        self.assertEqual(recovered.replaced_by, new.id)

    def test_unique_id_never_collides(self) -> None:
        self.store.save_subject(models.Subject.new("a bike", "bicycle", id="bike"))
        self.assertEqual(self.store.unique_subject_id("bike"), "bike_2")


class TestProcedures(StoreCase):
    def test_steps_survive_the_roundtrip(self) -> None:
        procedure = self.store.save_procedure(a_procedure())
        loaded = self.store.get_procedure(procedure.id)
        assert loaded is not None
        self.assertEqual(loaded.total_steps, 3)
        self.assertEqual(loaded.step(2).awaits, const.AWAITS_CONFIRM)
        self.assertEqual(loaded.step(3).duration_s, 11400)

    def test_saving_again_replaces_steps_rather_than_appending(self) -> None:
        procedure = self.store.save_procedure(a_procedure())
        procedure.steps = procedure.steps[:2]
        self.store.save_procedure(procedure)
        loaded = self.store.get_procedure(procedure.id)
        assert loaded is not None
        self.assertEqual(loaded.total_steps, 2)

    def test_deduplicated_by_title_and_subject_kind(self) -> None:
        self.store.save_procedure(a_procedure())
        found = self.store.find_procedure("rosemary tangzhong loaf", "bread_machine")
        assert found is not None
        self.assertEqual(found.total_steps, 3)
        self.assertIsNone(self.store.find_procedure("rosemary tangzhong loaf", "radiator"))


class TestRunsAndEvents(StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.procedure = self.store.save_procedure(a_procedure())

    def test_events_are_an_append_only_spine(self) -> None:
        run = self.store.save_run(models.Run.new(self.procedure.id, "the rosemary loaf"))
        self.store.add_event(models.RunEvent(run.id, const.EVENT_RUN_STARTED, step_n=1))
        self.store.add_event(
            models.RunEvent(run.id, const.EVENT_NOTE, step_n=1, text="gone a bit sticky")
        )
        self.store.add_event(models.RunEvent(run.id, const.EVENT_ADVANCED, step_n=2))
        kinds = [event.kind for event in self.store.events(run.id)]
        self.assertEqual(
            kinds, [const.EVENT_RUN_STARTED, const.EVENT_NOTE, const.EVENT_ADVANCED]
        )
        note = self.store.last_event(run.id, [const.EVENT_NOTE])
        assert note is not None
        self.assertEqual(note.text, "gone a bit sticky")

    def test_open_runs_are_most_recently_touched_first(self) -> None:
        first = self.store.save_run(
            models.Run.new(self.procedure.id, "loaf one", updated_at=util.iso())
        )
        second = self.store.save_run(
            models.Run.new(self.procedure.id, "loaf two", updated_at="2020-01-01T00:00:00+00:00")
        )
        done = self.store.save_run(
            models.Run.new(self.procedure.id, "loaf three", status=const.RUN_DONE)
        )
        listed = [run.id for run in self.store.open_runs()]
        self.assertEqual(listed, [first.id, second.id])
        self.assertNotIn(done.id, listed)

    def test_prune_keeps_the_last_n_closed_runs_per_subject(self) -> None:
        subject = self.store.save_subject(models.Subject.new("the bread machine", "bread_machine"))
        for index in range(5):
            self.store.save_run(
                models.Run.new(
                    self.procedure.id,
                    f"loaf {index}",
                    subject_id=subject.id,
                    status=const.RUN_DONE,
                    updated_at=f"2026-01-0{index + 1}T00:00:00+00:00",
                )
            )
        live = self.store.save_run(
            models.Run.new(self.procedure.id, "loaf now", subject_id=subject.id)
        )
        dropped = self.store.prune_runs(keep_per_subject=2)
        self.assertEqual(dropped, 3)
        kept = [run.reference for run in self.store.recent_runs(subject.id)]
        self.assertIn("loaf now", kept)
        self.assertIn("loaf 4", kept)
        self.assertNotIn("loaf 0", kept)
        self.assertIsNotNone(self.store.get_run(live.id))


class TestQuirks(StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.subject = self.store.save_subject(
            models.Subject.new("the bread machine", "bread_machine", make="Panasonic")
        )

    def test_same_claim_supersedes_rather_than_appends(self) -> None:
        first = self.store.add_quirk(
            models.Quirk(self.subject.id, "Yeast first, salt at the top")
        )
        second = self.store.add_quirk(
            models.Quirk(
                self.subject.id,
                "yeast first salt at the top",
                confidence=const.CONFIDENCE_HIGH,
            )
        )
        active = self.store.quirks(self.subject.id)
        self.assertEqual([quirk.id for quirk in active], [second.id])
        stale = self.store.get_quirk(first.id)
        assert stale is not None
        self.assertEqual(stale.status, const.QUIRK_SUPERSEDED)
        self.assertEqual(stale.superseded_by, second.id)

    def test_saying_a_quirk_counts_it_but_confirms_nothing(self) -> None:
        """Only the person can confirm a quirk. The system saying it is not that."""
        quirk = self.store.add_quirk(models.Quirk(self.subject.id, "needs a quick link"))
        self.store.quirk_stated(quirk.id)
        reloaded = self.store.get_quirk(quirk.id)
        assert reloaded is not None
        self.assertEqual(reloaded.times_applied, 1)
        self.assertIsNotNone(reloaded.last_stated_at)
        self.assertIsNone(reloaded.last_confirmed_at, "saying it is not being told it is right")

    def test_confirming_a_quirk_is_a_separate_act(self) -> None:
        quirk = self.store.add_quirk(models.Quirk(self.subject.id, "needs a quick link"))
        self.store.quirk_stated(quirk.id)
        self.store.confirm_quirk(quirk.id)
        reloaded = self.store.get_quirk(quirk.id)
        assert reloaded is not None
        self.assertIsNotNone(reloaded.last_confirmed_at)

    def test_an_older_database_gains_the_new_columns(self) -> None:
        version = self.store.schema_version()
        self.assertGreaterEqual(version, 1)
        reopened = store.Store(self.store.path).connect()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.schema_version(), version)

    def test_quirks_are_scoped_to_the_instance_never_the_kind(self) -> None:
        other = self.store.save_subject(models.Subject.new("the spare machine", "bread_machine"))
        self.store.add_quirk(models.Quirk(self.subject.id, "yeast first"))
        self.assertEqual(self.store.quirks(other.id), [])


if __name__ == "__main__":
    unittest.main()
