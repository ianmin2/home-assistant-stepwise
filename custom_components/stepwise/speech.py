"""How things are said (section 12).

The wording rules live here rather than in each user's prompt, because they are
the difference between usable and not when hands are busy: quantity first, one
step at a time, the reference restated, and never a word of judgement about a
gap.
"""

from __future__ import annotations

import re

from .const import (
    AWAITS_CONFIRM,
    AWAITS_TIMER,
    HOT,
    UNITS_IMPERIAL,
    UNITS_METRIC,
    WARM,
)
from .models import Step
from .util import say_duration, say_elapsed

# Reading a quantity aloud happens in two moves: convert it to the system the
# person actually uses, then say the unit as a word rather than a letter.
# Stored instructions keep whatever the source said, so nothing is lost.
#
# Imperial here is British: pints and fluid ounces are the UK ones.
TO_IMPERIAL: dict[str, tuple[float, str]] = {
    "g": (0.035274, "oz"),
    "kg": (2.20462, "lb"),
    "ml": (0.0351951, "fl oz"),
    "l": (1.75975, "pt"),
    "mm": (0.0393701, "in"),
    "cm": (0.393701, "in"),
    "m": (3.28084, "ft"),
}

TO_METRIC: dict[str, tuple[float, str]] = {
    "oz": (28.3495, "g"),
    "lb": (453.592, "g"),
    "floz": (28.4131, "ml"),
    "pt": (568.261, "ml"),
    "in": (2.54, "cm"),
    "ft": (0.3048, "m"),
}

# Units, expanded so text-to-speech says "grams" rather than "gee".
UNIT_WORDS = {
    "g": "grams",
    "kg": "kilograms",
    "mg": "milligrams",
    "ml": "millilitres",
    "l": "litres",
    "tsp": "teaspoons",
    "tbsp": "tablespoons",
    "oz": "ounces",
    "lb": "pounds",
    "c": "cups",
    "mm": "millimetres",
    "cm": "centimetres",
    "m": "metres",
    "in": "inches",
    "ft": "feet",
    "floz": "fluid ounces",
    "pt": "pints",
    "nm": "newton metres",
    "deg": "degrees",
}

_TRAILING_QUANTITY = re.compile(
    r"^(?P<item>.+?)[,:]?\s*(?P<amount>\d+(?:[.,]\d+)?(?:\s*(?:-|to)\s*\d+(?:[.,]\d+)?)?)\s*"
    r"(?P<unit>[a-zA-Z]{1,4})?$"
)

_LEADING_QUANTITY = re.compile(r"^\s*\d")


def _tidy(amount: float) -> str:
    """A number a person would say. Not a number a calculator would print."""
    if amount >= 100:
        return str(round(amount))
    if amount >= 10:
        return str(round(amount)) if abs(amount - round(amount)) < 0.05 else f"{amount:.1f}"
    rounded = round(amount, 1)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"


def convert_units(text: str, units: str = "") -> str:
    """Put quantities into the system the person actually uses.

    Only quantities in the other system are touched, so a recipe already
    written in ounces is left alone for somebody working in ounces.
    """
    if units not in (UNITS_METRIC, UNITS_IMPERIAL):
        return text
    table = TO_IMPERIAL if units == UNITS_IMPERIAL else TO_METRIC

    def swap(match: re.Match[str]) -> str:
        amount, unit = match.group(1), match.group(2)
        key = unit.lower().replace(" ", "")
        factor_and_unit = table.get(key) or table.get(unit.lower())
        if not factor_and_unit:
            return match.group(0)
        factor, becomes = factor_and_unit
        try:
            value = float(amount.replace(",", "."))
        except ValueError:  # pragma: no cover - the regex guarantees a number
            return match.group(0)
        converted = value * factor
        # Step up to the unit a person would actually say.
        if becomes == "g" and converted >= 1000:
            converted, becomes = converted / 1000, "kg"
        elif becomes == "ml" and converted >= 1000:
            converted, becomes = converted / 1000, "l"
        elif becomes == "oz" and converted >= 16:
            converted, becomes = converted / 16, "lb"
        elif becomes == "fl oz" and converted >= 20:  # a UK pint is 20 fl oz
            converted, becomes = converted / 20, "pt"
        return f"{_tidy(converted)} {becomes}"

    return re.sub(r"(\d+(?:[.,]\d+)?)\s*(fl oz|[a-zA-Z]{1,4})\b", swap, text)


# One of a thing is said differently from several.
_SINGULARS = {"inches": "inch", "feet": "foot"}


def _singular(word: str) -> str:
    return _SINGULARS.get(word, word[:-1] if word.endswith("s") else word)


def expand_units(text: str) -> str:
    """"200 g of flour" -> "200 grams of flour"."""

    def swap(match: re.Match[str]) -> str:
        amount, unit = match.group(1), match.group(2)
        word = UNIT_WORDS.get(unit.lower().replace(" ", ""))
        if not word:
            return match.group(0)
        if amount.replace(",", ".") in ("1", "1.0"):
            word = _singular(word)
        return f"{amount} {word}"

    return re.sub(r"(\d+(?:[.,]\d+)?)\s*(fl oz|[a-zA-Z]{1,4})\b", swap, text)


def render(text: str, units: str = "") -> str:
    """A quantity as it should be heard: right system, unit said as a word."""
    return expand_units(convert_units(text, units))


def quantity_first(phrase: str, units: str = "") -> str:
    """The ear needs the number first when hands are busy.

    "wholemeal flour, 200 g" -> "200 g of wholemeal flour". Anything that
    already leads with a number is left alone. Units are neither converted nor
    spelled out here: that happens when the step is spoken, so changing the
    units setting changes what is said without rewriting anything stored.
    """
    phrase = (phrase or "").strip()
    if not phrase or _LEADING_QUANTITY.match(phrase):
        return phrase
    match = _TRAILING_QUANTITY.match(phrase)
    if not match:
        return phrase
    item = match.group("item").strip(" ,:")
    if item[:1].isupper() and not item.isupper() and " " in item:
        item = item[0].lower() + item[1:]
    amount = match.group("amount").strip()
    unit = (match.group("unit") or "").strip()
    if unit and unit.lower() not in UNIT_WORDS and len(unit) > 2:
        return phrase
    lead = f"{amount} {unit}".strip()
    return f"{lead} of {item}" if item else lead


def sentence(text: str) -> str:
    """Capitalise the opening of a spoken line."""
    text = (text or "").strip()
    return f"{text[0].upper()}{text[1:]}" if text else text


def say_step(step: Step, units: str = "", prompt: bool = False) -> str:
    """One step, as it is read out. Never the whole list.

    `prompt` adds the explicit await. It is said when re-entering a run or when
    a step is genuinely a wait, and not on every advance: "await explicitly"
    means never advancing on silence, not repeating yourself.
    """
    said = sentence(render(step.said, units))
    if step.awaits == AWAITS_TIMER and step.duration_s:
        return f"{said}. That's {say_duration(step.duration_s)}."
    if prompt and step.awaits == AWAITS_CONFIRM:
        # Await explicitly, then stop talking. Never advance on silence.
        return f"{said}. Tell me when that's done."
    return said


def with_reference(reference: str, sentence: str) -> str:
    """Restated casually at natural moments, never announced as an id."""
    if not reference:
        return sentence
    body = sentence[0].lower() + sentence[1:] if sentence[:1].isupper() else sentence
    return f"On {reference}, {body}"


def opener(state: str, reference: str, since_seconds: float | None, step_summary: str) -> str:
    """Hot assumes, warm names, cold offers (section 6).

    A gap is never treated as failure: no "you abandoned this", no streaks, no
    implication that anybody is behind.
    """
    if state == HOT:
        return step_summary
    if state == WARM:
        return with_reference(reference, step_summary)
    return (
        f"You've {reference} part done, last touched {say_elapsed(since_seconds)}. "
        f"Carry on, or something new?"
    )


def timer_offer(seconds: float | None, because: str) -> str:
    """Offered, never imposed, and always with the rationale."""
    if not seconds:
        return ""
    return f"Shall I set a timer for {say_duration(seconds)}? That's {because}."


def state_quirk(claim: str) -> str:
    """Said as an assertion the user can reject in flight, not applied silently."""
    claim = claim.strip().rstrip(".")
    if not claim:
        return ""
    return f"On yours, {claim[0].lower()}{claim[1:]}."


def reconfirm_quirk(claim: str, source: str, age: str) -> str:
    """Brief, and only when the ground may have moved (section 9, rule 2)."""
    claim = claim.strip().rstrip(".")
    origin = {
        "web": "I read that somewhere",
        "user": "you told me",
        "manual": "the manual says",
        "observed": "I picked that up",
    }.get(source, "I have it noted")
    return f"{claim[0].upper()}{claim[1:]} — {origin}, {age}. Still right?"


def landed(step: Step, units: str = "") -> str:
    """Positioning always reports where it landed (section 8.1)."""
    said = render(step.said, units)
    return f"Right, step {step.n}, {said[0].lower()}{said[1:]}"


def remaining(steps: list[Step], units: str = "") -> str:
    """Never enumerate a set as a summary. "A few more" is not an answer."""
    if not steps:
        return "Nothing left, that's the lot."
    lines = [f"step {step.n}, {render(step.said, units)}" for step in steps]
    if len(lines) == 1:
        return f"Just {lines[0]}."
    return "Left to do: " + "; ".join(lines) + "."


def no_shame(reference: str, since_seconds: float | None) -> str:
    """A fact, not a judgement. "You still have a loaf half done" — never
    "you never finished your loaf"."""
    return f"You still have {reference} part done, last touched {say_elapsed(since_seconds)}."
