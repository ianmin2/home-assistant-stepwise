"""The wording rules from section 12, which are load bearing rather than polish."""

from __future__ import annotations

import unittest

from context import const, models, speech


class TestWording(unittest.TestCase):
    def test_quantity_comes_before_the_ingredient(self) -> None:
        self.assertEqual(
            speech.quantity_first("wholemeal flour, 200 g"), "200 g of wholemeal flour"
        )
        self.assertEqual(speech.quantity_first("water, 250ml"), "250 ml of water")

    def test_reordering_does_not_touch_the_units(self) -> None:
        """Stored steps stay as written; conversion happens when they are said."""
        self.assertEqual(speech.quantity_first("flour, 7 oz"), "7 oz of flour")

    def test_a_phrase_that_already_leads_with_the_number_is_left_alone(self) -> None:
        self.assertEqual(speech.quantity_first("200 g wholemeal flour"), "200 g wholemeal flour")
        self.assertEqual(speech.quantity_first("a pinch of salt"), "a pinch of salt")

    def test_units_are_expanded_so_speech_says_grams(self) -> None:
        self.assertEqual(speech.expand_units("7 g salt"), "7 grams salt")
        self.assertEqual(speech.expand_units("15 mm pipe"), "15 millimetres pipe")

    def test_one_of_a_thing_is_said_singular(self) -> None:
        self.assertEqual(speech.expand_units("1 pt water"), "1 pint water")
        self.assertEqual(speech.expand_units("1 in clearance"), "1 inch clearance")

    def test_quantities_are_converted_to_the_system_in_use(self) -> None:
        self.assertEqual(speech.render("200 g flour", "imperial"), "7.1 ounces flour")
        self.assertEqual(speech.render("7 oz flour", "metric"), "198 grams flour")

    def test_a_recipe_already_in_the_right_system_is_left_alone(self) -> None:
        self.assertEqual(speech.render("7 oz flour", "imperial"), "7 ounces flour")
        self.assertEqual(speech.render("200 g flour", "metric"), "200 grams flour")

    def test_conversion_steps_up_to_the_unit_a_person_would_say(self) -> None:
        self.assertEqual(speech.render("1200 g flour", "imperial"), "2.6 pounds flour")
        self.assertEqual(speech.render("600 ml water", "imperial"), "1.1 pints water")
        self.assertEqual(speech.render("40 oz flour", "metric"), "1.1 kilograms flour")

    def test_numbers_that_are_not_quantities_are_untouched(self) -> None:
        self.assertEqual(
            speech.render("Programme four, medium crust", "imperial"),
            "Programme four, medium crust",
        )

    def test_a_wait_is_stated_explicitly_but_not_on_every_step(self) -> None:
        step = models.Step(2, "7 g salt", awaits=const.AWAITS_CONFIRM)
        self.assertIn("Tell me when", speech.say_step(step, prompt=True))
        self.assertNotIn("Tell me when", speech.say_step(step))

    def test_a_timer_is_offered_with_its_reason_never_imposed(self) -> None:
        offer = speech.timer_offer(11400, "the programme length")
        self.assertIn("Shall I set a timer", offer)
        self.assertIn("3 hours 10", offer)
        self.assertIn("that's the programme length", offer.lower())

    def test_a_quirk_is_said_as_something_that_can_be_rejected(self) -> None:
        self.assertEqual(
            speech.state_quirk("yeast first, then the flour"),
            "On yours, yeast first, then the flour.",
        )

    def test_a_gap_is_reported_as_a_fact_never_a_judgement(self) -> None:
        said = speech.no_shame("the rosemary loaf", 26000)
        self.assertIn("You still have the rosemary loaf part done", said)
        for shaming in ("never", "abandoned", "failed", "behind", "should"):
            self.assertNotIn(shaming, said.lower())

    def test_remaining_steps_are_listed_never_summarised(self) -> None:
        said = speech.remaining([models.Step(4, "add the fruit"), models.Step(5, "second prove")])
        self.assertIn("step 4, add the fruit", said)
        self.assertIn("step 5, second prove", said)
        self.assertNotIn("a few", said.lower())

    def test_the_reference_is_restated_casually_not_announced(self) -> None:
        said = speech.with_reference("the rosemary loaf", "Next is 200 grams of wholemeal flour")
        self.assertEqual(said, "On the rosemary loaf, next is 200 grams of wholemeal flour")

    def test_cold_offers_rather_than_assumes(self) -> None:
        said = speech.opener(const.COLD, "the rosemary loaf", 26000, "step 3")
        self.assertIn("Carry on, or something new?", said)


if __name__ == "__main__":
    unittest.main()
