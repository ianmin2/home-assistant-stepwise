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
from .util import parse_duration, say_duration, say_elapsed

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

# Units whose abbreviation is also an ordinary English word. "Put 2 in the tin"
# is not two inches. What separates the two is the word that follows: a unit is
# followed by what is being measured ("1 in clearance", "2 in of slack"), while
# the preposition is followed by whatever the thing goes into. `parse_duration`
# takes the same line about single letters, deliberately.
_AMBIGUOUS_UNITS = {"m", "l", "in"}
_AFTER_A_PREPOSITION = {
    "the", "a", "an", "this", "that", "these", "those", "it", "them",
    "my", "your", "our", "their", "its", "his", "her",
    "there", "here", "each", "every", "both", "either", "any", "some", "all",
    "order", "place", "position", "turn", "front", "case", "half", "line",
}

# "180 C" is a temperature. Said as a unit it becomes a volume.
_DEGREES = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:°\s*)?([CF])\b")

# The tail of a phrase that means the number after it is a setting or a target,
# not an amount of anything: "bake at 180", "tighten to 25 Nm".
_CONNECTING = {
    "at", "to", "for", "on", "in", "of", "by", "with",
    "until", "till", "from", "about", "around", "onto", "into",
}
_SETTINGS_TAIL = {
    "programme", "program", "cycle", "mode", "setting", "speed",
    "gas", "mark", "level", "number", "position", "channel", "step",
}


def _unit_here(match: re.Match[str], unit: str) -> bool:
    """Whether this abbreviation is really a unit, given what follows it."""
    if unit.lower().replace(" ", "") not in _AMBIGUOUS_UNITS:
        return True
    rest = match.string[match.end() :].lstrip()
    if not rest[:1].isalpha():
        return True  # end of the phrase, or punctuation: nothing else it can be
    return rest.split()[0].strip(",:.;").lower() not in _AFTER_A_PREPOSITION


def say_degrees(text: str) -> str:
    """"180 C" -> "180 degrees". Before anything reads C as a unit."""
    return _DEGREES.sub(lambda m: f"{m.group(1)} degrees", text)


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
        if not factor_and_unit or not _unit_here(match, unit):
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
        # Seven grams is a fifth of an ounce. No kitchen scale reads that, and
        # rounding it to one decimal puts it 20% out. Leave it in the units the
        # source used and say those, rather than convert it into uselessness.
        if converted < 1:
            return match.group(0)
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
        if not word or not _unit_here(match, unit):
            return match.group(0)
        if amount.replace(",", ".") in ("1", "1.0"):
            word = _singular(word)
        return f"{amount} {word}"

    return re.sub(r"(\d+(?:[.,]\d+)?)\s*(fl oz|[a-zA-Z]{1,4})\b", swap, text)


def render(text: str, units: str = "") -> str:
    """A quantity as it should be heard: right system, unit said as a word."""
    return expand_units(say_degrees(convert_units(text, units)))


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
    amount = match.group("amount").strip()
    unit = (match.group("unit") or "").strip()
    if unit and unit.lower() not in UNIT_WORDS and len(unit) > 2:
        return phrase
    # A number at the end of an instruction is not always an amount of
    # something. "Bake at 180" and "Programme 4" are a target and a setting;
    # inverting them says "180 of bake at". What decides it is the word the
    # phrase ends on, not the number.
    tail = item.split()[-1].strip(" ,:.").lower() if item.split() else ""
    if tail in _CONNECTING or tail in _SETTINGS_TAIL:
        return phrase
    if item[:1].isupper() and not item.isupper() and " " in item:
        item = item[0].lower() + item[1:]
    lead = f"{amount} {unit}".strip()
    return f"{lead} of {item}" if item else lead


def soften(text: str) -> str:
    """Lower the opening letter for the middle of a sentence.

    Not blindly: "ESP32" must not become "eSP32", nor "SD-2500" "sD-2500". A
    word that carries a capital anywhere but the front, or a digit, is a name.
    """
    head = text.split(" ", 1)[0].strip(",:.;")
    if not text[:1].isupper():
        return text
    if head.isupper() or any(ch.isdigit() for ch in head) or head[1:] != head[1:].lower():
        return text
    return text[0].lower() + text[1:]


def legacy_quantity_first(phrase: str) -> str:
    """What `quantity_first` used to produce, kept so the damage can be found.

    Before 0.2 a number at the end of any phrase was treated as a quantity, so
    "Bake at 180" was stored as "180 of bake at". That text is on disk in every
    database written by 0.1. Regenerating every `speakable` would overwrite the
    ones an author wrote by hand, so the repair asks a narrower question: is
    this exactly what the old function would have produced from the
    instruction? If it is, it was generated, and it can be generated again.
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


def joined(*parts: str) -> str:
    """Run spoken fragments together, ending each one properly."""
    said = []
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        if part[-1] not in ".?!:":
            part = f"{part}."
        said.append(part)
    return " ".join(said)


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
        if parse_duration(step.said):
            return said  # the step already says how long; do not say it twice
        return f"{said}. That's {say_duration(step.duration_s)}."
    if prompt and step.awaits == AWAITS_CONFIRM:
        # Await explicitly, then stop talking. Never advance on silence.
        return f"{said}. Tell me when that's done."
    return said


def with_step(number: int, said: str) -> str:
    """Say which step this is, every time the pointer moves.

    The only pointer move that never announced itself was the one that happens
    fifty times a run. A step that is skipped by mistake — because a remark was
    heard as "done" — is then skipped silently, which is the failure this whole
    thing exists to prevent. One clause makes it audible.
    """
    return f"Step {number}. {sentence(said)}" if said else f"Step {number}."


def with_reference(reference: str, sentence: str) -> str:
    """Restated casually at natural moments, never announced as an id."""
    if not reference:
        return sentence
    return f"On {reference}, {soften(sentence)}"


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
    """Offered, never imposed, and always with the rationale.

    The rationale is what makes an offer correctable: "three hours ten, because
    that's the programme length" invites "no, mine's shorter". When the step
    has just said the number out loud, repeating it is noise rather than
    rationale, so the offer simply points at it.
    """
    if not seconds:
        return ""
    if because == "what the step says":
        return "Shall I set a timer for that?"
    return f"Shall I set a timer for {say_duration(seconds)}? That's {because}."


def state_quirk(claim: str) -> str:
    """Said as an assertion the user can reject in flight, not applied silently."""
    claim = claim.strip().rstrip(".")
    if not claim:
        return ""
    return f"On yours, {soften(claim)}."


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
    return f"Right, step {step.n}, {soften(said)}"


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
