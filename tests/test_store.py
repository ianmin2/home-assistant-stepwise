"""The store keeps run state, and keeps it bounded."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from context import const, engine, export, models, store, util


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
            model="SD-2500",
            aliases=["the panasonic"],
            attributes={"programmes": [1, 2, 3, 4], "has_dispenser": True},
        )
        self.store.save_subject(subject)
        loaded = self.store.get_subject(subject.id)
        assert loaded is not None
        self.assertEqual(loaded.id, "panasonic_sd_2500")
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

    def test_reopening_a_database_leaves_it_at_the_current_version(self) -> None:
        version = self.store.schema_version()
        self.assertEqual(version, const.SCHEMA_VERSION)
        reopened = store.Store(self.store.path).connect()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.schema_version(), version)

    def test_quirks_are_scoped_to_the_instance_never_the_kind(self) -> None:
        other = self.store.save_subject(models.Subject.new("the spare machine", "bread_machine"))
        self.store.add_quirk(models.Quirk(self.subject.id, "yeast first"))
        self.assertEqual(self.store.quirks(other.id), [])


class MigrationCase(unittest.TestCase):
    """A database written by 0.1, opened by this version."""

    def a_version_one_database(self, steps: list[tuple[int, str, str]]) -> str:
        """A file shaped like 0.1 left it: stamped 1, missing the late columns."""
        path = str(Path(tempfile.mkdtemp()) / "stepwise.db")
        conn = sqlite3.connect(path)
        conn.executescript(store.SCHEMA)
        for table in ("runs", "quirks"):
            for column in ("subject_loose", "last_stated_at"):
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column in existing:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute(
            "INSERT INTO procedures (id, title, source, created_at, updated_at) "
            "VALUES ('p1', 'a loaf', 'user', ?, ?)",
            (util.iso(), util.iso()),
        )
        for n, instruction, speakable in steps:
            conn.execute(
                "INSERT INTO procedure_steps (procedure_id, n, instruction, speakable) "
                "VALUES ('p1', ?, ?, ?)",
                (n, instruction, speakable),
            )
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        conn.commit()
        conn.close()
        return path

    def test_the_columns_0_1_added_without_a_version_arrive(self) -> None:
        path = self.a_version_one_database([])
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        columns = {row["name"] for row in opened.conn.execute("PRAGMA table_info(runs)")}
        self.assertIn("subject_loose", columns)
        self.assertEqual(opened.schema_version(), const.SCHEMA_VERSION)

    def test_speech_the_old_code_mangled_is_repaired(self) -> None:
        """"Bake at 180" was stored as "180 of bake at". It is on disk, so the
        fix to the function repairs nothing on its own."""
        path = self.a_version_one_database(
            [
                (1, "Bake at 180", "180 of bake at"),
                (2, "wholemeal flour, 200 g", "200 g of wholemeal flour"),
            ]
        )
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        said = {
            row["n"]: row["speakable"]
            for row in opened.conn.execute("SELECT n, speakable FROM procedure_steps")
        }
        self.assertEqual(said[1], "Bake at 180")
        self.assertEqual(said[2], "200 g of wholemeal flour")

    def test_speech_somebody_wrote_by_hand_is_left_alone(self) -> None:
        path = self.a_version_one_database([(1, "Bake at 180", "into the oven, gas six")])
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        row = opened.conn.execute("SELECT speakable FROM procedure_steps").fetchone()
        self.assertEqual(row["speakable"], "into the oven, gas six")

    def test_a_repair_keeps_the_file_it_started_from(self) -> None:
        path = self.a_version_one_database([(1, "Bake at 180", "180 of bake at")])
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        kept = list(Path(path).parent.glob("stepwise.db.v*"))
        self.assertTrue(kept, "the file should be copied aside before data is rewritten")


    def test_a_database_that_lost_its_version_heals_rather_than_bricks(self) -> None:
        """Stamped current with no migrations run, an old database that lost
        its meta row had no touch_seq column, no speakable repair, and every
        run query dead — permanently, because the stamp destroyed the evidence.
        Tables with no readable version are the oldest known shape, not a fresh
        file."""
        path = self.a_version_one_database([(1, "Bake at 180", "180 of bake at")])
        conn = sqlite3.connect(path)
        conn.execute("DELETE FROM meta")
        conn.commit()
        conn.close()
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        self.assertEqual(opened.schema_version(), const.SCHEMA_VERSION)
        columns = {row["name"] for row in opened.conn.execute("PRAGMA table_info(runs)")}
        self.assertIn("touch_seq", columns)
        row = opened.conn.execute("SELECT speakable FROM procedure_steps").fetchone()
        self.assertEqual(row["speakable"], "Bake at 180")
        opened.open_runs()  # must not raise

    def test_an_existing_backup_is_never_mistaken_for_this_ones(self) -> None:
        """A stale .vN from an earlier database must not stand in for the
        backup this migration owes: the file about to be rewritten would have
        no copy at all, while the name claimed otherwise."""
        path = self.a_version_one_database([(1, "Bake at 180", "180 of bake at")])
        stale = Path(f"{path}.v2")
        stale.write_bytes(b"someone else's database")
        opened = store.Store(path).connect()
        self.addCleanup(opened.close)
        self.assertEqual(stale.read_bytes(), b"someone else's database")
        fresh = [p for p in Path(path).parent.glob("stepwise.db.v*") if p != stale]
        self.assertTrue(fresh, "a new backup name should have been taken")

    def test_a_database_from_a_newer_stepwise_is_refused(self) -> None:
        """Never open a newer database and misread it. Say so instead."""
        path = self.a_version_one_database([])
        opened = store.Store(path).connect()
        opened.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(const.SCHEMA_VERSION + 1),),
        )
        opened.conn.commit()
        opened.close()
        with self.assertRaises(store.StoreError):
            store.Store(path).connect()

class ContradictionCase(StoreCase):
    """Superseding used to need the same words, so opposites piled up."""

    def setUp(self) -> None:
        super().setUp()
        self.subject = self.store.save_subject(
            models.Subject.new("the bread machine", "bread_machine")
        )

    def test_a_quirk_that_contradicts_one_held_replaces_it(self) -> None:
        first = self.store.add_quirk(models.Quirk(self.subject.id, "the yeast goes in first"))
        second = self.store.add_quirk(models.Quirk(self.subject.id, "the yeast goes in last"))
        active = self.store.quirks(self.subject.id)
        self.assertEqual([q.id for q in active], [second.id])
        stale = self.store.get_quirk(first.id)
        assert stale is not None
        self.assertEqual(stale.status, const.QUIRK_SUPERSEDED)

    def test_an_unrelated_quirk_is_kept_alongside(self) -> None:
        self.store.add_quirk(models.Quirk(self.subject.id, "the yeast goes in first"))
        self.store.add_quirk(models.Quirk(self.subject.id, "the pan needs a good soak"))
        self.assertEqual(len(self.store.quirks(self.subject.id)), 2)

    def test_a_fact_that_contradicts_one_held_replaces_it(self) -> None:
        """Told the keys are in the bedroom and then the kitchen, an appending
        store says both. That is the thing this is meant to be better than."""
        self.store.add_fact("the keys are in the bedroom", self.subject.id)
        self.store.add_fact("the keys are not in the bedroom", self.subject.id)
        held = [fact["text"] for fact in self.store.facts(self.subject.id)]
        self.assertEqual(held, ["the keys are not in the bedroom"])

    def test_a_fact_can_be_forgotten(self) -> None:
        fact_id = self.store.add_fact("takes a 15 mm spanner", self.subject.id)
        self.store.forget_fact(fact_id)
        self.assertEqual(self.store.facts(self.subject.id), [])


class OrderingCase(StoreCase):
    def test_two_runs_touched_in_the_same_instant_still_have_an_order(self) -> None:
        """Millisecond stamps tie. "The one you last touched" must not be a
        coin toss when it does."""
        procedure = self.store.save_procedure(
            models.Procedure.new("a loaf", [models.Step(1, "flour")])
        )
        stamp = util.iso()
        first = models.Run.new(procedure.id, "the loaf")
        second = models.Run.new(procedure.id, "the other loaf")
        for run in (first, second):
            run.started_at = run.updated_at = stamp
            self.store.save_run(run)
        self.store.touch_run(first.id, stamp)
        self.assertEqual(self.store.open_runs()[0].id, first.id)
        self.store.touch_run(second.id, stamp)
        self.assertEqual(self.store.open_runs()[0].id, second.id)


class ExportCase(StoreCase):
    """"A run's history is a lab notebook, and it is already written." It was
    also unreadable: nothing could get it out of the database."""

    def setUp(self) -> None:
        super().setUp()
        self.engine = engine.Engine(self.store, engine.Settings())
        self.procedure_id = self.engine.procedure_plan(
            "Rosemary loaf",
            [{"instruction": "200 g wholemeal flour"}, {"instruction": "Bake at 180"}],
        ).data["procedure_id"]
        self.run_id = self.engine.run_start(
            self.procedure_id, reference="the rosemary loaf"
        ).data["run_id"]

    def written(self) -> str:
        run = self.store.get_run(self.run_id)
        assert run is not None
        return export.as_markdown(
            run,
            self.store.events(self.run_id),
            self.store.get_procedure(run.procedure_id),
            amendments=self.store.amendments(self.run_id),
        )

    def test_everything_that_happened_is_in_it(self) -> None:
        self.engine.run_advance(run_id=self.run_id)
        self.engine.run_note("gone a bit sticky", run_id=self.run_id)
        self.engine.run_ask("how long has it been", run_id=self.run_id)
        written = self.written()
        self.assertIn("the rosemary loaf", written)
        self.assertIn("gone a bit sticky", written)
        self.assertIn("how long has it been", written)
        self.assertIn("Completed step", written)

    def test_the_steps_are_written_as_they_stood(self) -> None:
        self.assertIn("Bake at 180", self.written())

    def test_a_pipe_in_a_note_does_not_break_the_table(self) -> None:
        self.engine.run_note("used the 15 mm | not the 10", run_id=self.run_id)
        rows = [line for line in self.written().split("\n") if line.startswith("|")]
        for row in rows:
            cells = row.count("|") - row.count("\\|")
            self.assertEqual(cells, 6, row)


    def test_a_note_with_a_newline_does_not_break_the_table(self) -> None:
        self.engine.run_note("line one\nline two | pipe", run_id=self.run_id)
        rows = [line for line in self.written().split("\n") if line.startswith("|")]
        for row in rows:
            self.assertEqual(row.count("|") - row.count("\\|"), 6, row)

    def test_a_spreadsheet_shows_a_note_and_never_runs_it(self) -> None:
        self.engine.run_note("=SUM(A1:A9)", run_id=self.run_id)
        run = self.store.get_run(self.run_id)
        assert run is not None
        written = export.as_csv(run, self.store.events(self.run_id))
        self.assertIn("'=SUM(A1:A9)", written)

    def test_the_csv_has_a_row_for_each_thing_that_happened(self) -> None:
        self.engine.run_advance(run_id=self.run_id)
        run = self.store.get_run(self.run_id)
        assert run is not None
        written = export.as_csv(run, self.store.events(self.run_id))
        self.assertEqual(len(written.strip().split("\n")), len(self.store.events(self.run_id)) + 1)


if __name__ == "__main__":
    unittest.main()
