"""Working out what was meant, before anything gets built."""

from __future__ import annotations

import unittest

from context import models, resolution


def subjects() -> list[models.Subject]:
    return [
        models.Subject.new(
            "the winter bike", "bicycle", id="bike_winter_hack", aliases=["the hack"]
        ),
        models.Subject.new("the summer bike", "bicycle", id="bike_summer"),
        models.Subject.new(
            "the bread machine",
            "bread_machine",
            make="Panasonic",
            model="SD-YR2550",
            aliases=["the panasonic"],
        ),
    ]


class TestSubjectResolution(unittest.TestCase):
    def test_one_match_proceeds(self) -> None:
        resolved = resolution.resolve_subject("the winter bike", subjects())
        self.assertTrue(resolved.resolved)
        assert resolved.subject is not None
        self.assertEqual(resolved.subject.id, "bike_winter_hack")
        self.assertFalse(resolved.loose)

    def test_two_matches_ask_which_rather_than_guess(self) -> None:
        resolved = resolution.resolve_subject("my bike", subjects())
        self.assertEqual(resolved.status, "ambiguous")
        self.assertIsNone(resolved.subject)
        self.assertIn("Which one", resolved.question or "")
        self.assertEqual(len(resolved.candidates), 2)
        self.assertTrue(resolved.loose)

    def test_an_alias_and_a_model_number_both_resolve(self) -> None:
        for spoken in ("the panasonic", "SD-YR2550", "the bread machine"):
            resolved = resolution.resolve_subject(spoken, subjects())
            assert resolved.subject is not None, spoken
            self.assertEqual(resolved.subject.id, "panasonic_sd_yr2550", spoken)

    def test_nothing_on_file_says_so(self) -> None:
        resolved = resolution.resolve_subject("the landing radiator", subjects())
        self.assertEqual(resolved.status, "unknown")
        self.assertIn("don't have anything on file", resolved.question or "")

    def test_a_lone_subject_of_the_kind_is_matched_loosely(self) -> None:
        only = [models.Subject.new("the big one", "bread_machine", id="bm_big")]
        resolved = resolution.resolve_subject("the bread machine", only)
        self.assertTrue(resolved.resolved, "one match proceeds")
        self.assertTrue(resolved.loose, "matched by kind, so it deserves re-confirming")


class TestMishearings(unittest.TestCase):
    def setUp(self) -> None:
        self.vocabulary = resolution.vocabulary_of(
            subjects(),
            [
                models.Procedure.new(
                    "Rosemary tangzhong loaf",
                    [models.Step(1, "200 g wholemeal flour", ingredients=["tangzhong"])],
                )
            ],
        )

    def test_a_mangled_term_is_offered_back_not_believed(self) -> None:
        found = resolution.odd_terms("I want to make yang zoong bread", self.vocabulary)
        self.assertTrue(found)
        term, candidates = found[0]
        self.assertIn("tangzhong", [name for name, _ in candidates])
        self.assertIn("Tangzhong", resolution.confirm_hearing(term, candidates))

    def test_a_known_term_is_not_queried(self) -> None:
        self.assertEqual(resolution.odd_terms("make the tangzhong loaf", self.vocabulary), [])

    def test_a_genuinely_new_word_is_not_an_error(self) -> None:
        self.assertEqual(resolution.odd_terms("descale the kettle", self.vocabulary), [])

    def test_sound_alike_beats_spelling(self) -> None:
        self.assertGreater(
            resolution.similarity("yang zoong", "tangzhong"),
            resolution.similarity("yang zoong", "wholemeal flour"),
        )


class TestLocalFirst(unittest.TestCase):
    def test_their_own_procedures_are_searched_before_anything_else(self) -> None:
        procedures = [
            models.Procedure.new("Rosemary tangzhong loaf", []),
            models.Procedure.new("Descale the dishwasher", []),
        ]
        found = resolution.search_local("rosemary tangzhong loaf", procedures)
        self.assertTrue(found)
        self.assertEqual(found[0].title, "Rosemary tangzhong loaf")

    def test_a_resolution_session_expires_rather_than_being_stored(self) -> None:
        session = resolution.ResolutionSession(
            "tangzhong bread", started_at="2020-01-01T00:00:00+00:00"
        )
        self.assertTrue(session.expired(ttl_minutes=30))
        fresh = resolution.ResolutionSession("tangzhong bread")
        self.assertFalse(fresh.expired(ttl_minutes=30))


if __name__ == "__main__":
    unittest.main()
