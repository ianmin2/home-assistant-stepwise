"""Small helpers shared by the core. Standard library only."""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime

# Time ------------------------------------------------------------------
# Everything is timestamped (section 6). Stored as ISO-8601 UTC text, which
# sorts lexicographically and stays readable in a SQLite browser.


def utcnow() -> datetime:
    """Current time, always timezone-aware UTC."""
    return datetime.now(UTC)


def iso(moment: datetime | None = None) -> str:
    """Format a moment for storage.

    Milliseconds, not seconds: two runs touched in the same second must still
    sort, because "the one you last touched" is how the right run is chosen.
    """
    if moment is None:
        moment = utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


def parse_iso(value: str | None) -> datetime | None:
    """Read a stored timestamp back."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def elapsed_seconds(since: str | datetime | None, now: datetime | None = None) -> float | None:
    """Seconds between a stored timestamp and now."""
    moment = parse_iso(since) if isinstance(since, str) else since
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return ((now or utcnow()) - moment).total_seconds()


def say_elapsed(seconds: float | None) -> str:
    """Elapsed time as a person would say it.

    Never precise beyond usefulness: "forty minutes ago" is the answer, not
    "39 minutes and 12 seconds ago".
    """
    if seconds is None:
        return "just now"
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)} minutes ago"
    hours = minutes / 60
    if hours < 24:
        whole = int(hours)
        rest = round((hours - whole) * 60)
        if rest >= 55:
            whole, rest = whole + 1, 0
        if whole == 1 and rest == 0:
            return "an hour ago"
        if rest < 5:
            return f"{whole} hours ago"
        return f"{whole} hours and {rest} minutes ago"
    days = hours / 24
    if days < 2:
        return "yesterday"
    if days < 7:
        return f"{int(days)} days ago"
    weeks = int(days / 7)
    if weeks == 1:
        return "last week"
    if weeks < 5:
        return f"{weeks} weeks ago"
    months = int(days / 30)
    return "last month" if months <= 1 else f"{months} months ago"


def strip_ago(text: str) -> str:
    """"40 minutes ago" -> "40 minutes", for the middle of a sentence."""
    return text[:-4].strip() if text.endswith(" ago") else text


def say_duration(seconds: float | None) -> str:
    """A duration, spoken. "three hours ten", not "3:10:00"."""
    if not seconds:
        return ""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        lead = "an hour" if hours == 1 else f"{hours} hours"
        if not minutes:
            return lead
        # "three hours ten" is how a person says it, but only once the tail is
        # big enough to sound like a number. "an hour 1" is not English.
        if minutes == 30:
            return "an hour and a half" if hours == 1 else f"{hours} and a half hours"
        if minutes == 1:
            return f"{lead} and a minute"
        if minutes < 10:
            return f"{lead} and {minutes} minutes"
        return f"{lead} {minutes}"
    if minutes:
        if secs >= 30:
            return "a minute and a half" if minutes == 1 else f"{minutes} and a half minutes"
        return "a minute" if minutes == 1 else f"{minutes} minutes"
    return f"{secs} seconds"


# Durations spoken inside an instruction ---------------------------------
# "Fry for thirty minutes" should offer a timer even when whoever wrote the
# step never filled in a duration field. Single-letter units are deliberately
# not accepted: "15 m" is millimetres as often as it is minutes.

_DURATION_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
}

# People say durations far more often than they write them.
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
    "twenty five": 25, "twenty-five": 25, "thirty five": 35, "thirty-five": 35,
    "forty five": 45, "forty-five": 45,
}

_NUMBERS = "|".join(
    re.escape(word) for word in sorted(_NUMBER_WORDS, key=len, reverse=True)
)

_DURATION = re.compile(
    rf"(\d+(?:[.,]\d+)?|{_NUMBERS})\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)


def _amount(text: str) -> float:
    cleaned = text.strip().lower()
    if cleaned in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[cleaned])
    return float(cleaned.replace(",", "."))

# Said rather than written. Longest first, so "half an hour" wins over "an hour".
_WORDED_DURATIONS = (
    ("three quarters of an hour", 2700),
    ("quarter of an hour", 900),
    ("half an hour", 1800),
    ("an hour and a half", 5400),
    ("a couple of minutes", 120),
    ("a few minutes", 180),
    ("an hour", 3600),
    ("a minute", 60),
)


def parse_duration(text: str) -> int | None:
    """Read a duration out of an instruction, or None if it does not state one.

    Conservative on purpose: a wrong timer is worse than no timer, so anything
    ambiguous is left alone.
    """
    if not text:
        return None
    lowered = text.lower()
    for phrase, seconds in _WORDED_DURATIONS:
        if phrase in lowered:
            return seconds

    found = [
        (match.start(), _amount(match.group(1)), match.group(2).lower())
        for match in _DURATION.finditer(text)
    ]
    if not found:
        return None

    start, amount, unit = found[0]
    total = amount * _DURATION_UNITS[unit]

    # "an hour and a half", written as "1 hr 30 mins": one duration, not two.
    if len(found) > 1 and unit.startswith("h"):
        next_start, next_amount, next_unit = found[1]
        gap = text[start:next_start]
        if next_unit.startswith("m") and len(gap) < 16 and "," not in gap:
            total += next_amount * _DURATION_UNITS[next_unit]

    return int(total) if total > 0 else None


# Identifiers -----------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "item") -> str:
    """A readable id. "Panasonic SD-2500" -> "panasonic_sd_2500"."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("_", folded).strip("_")
    return slug[:64] or fallback


def short_id(prefix: str = "") -> str:
    """An opaque id. Never spoken aloud; the reference is what gets said."""
    token = secrets.token_hex(4)
    return f"{prefix}_{token}" if prefix else token


# Text ------------------------------------------------------------------

_ARTICLES = ("the ", "a ", "an ", "my ", "our ", "this ", "that ")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation and leading articles, for matching."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = folded.encode("ascii", "ignore").decode("ascii").lower().strip()
    folded = re.sub(r"[^a-z0-9\s]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    for article in _ARTICLES:
        if folded.startswith(article):
            folded = folded[len(article) :]
            break
    return folded


def words(text: str) -> list[str]:
    return [word for word in normalise(text).split(" ") if word]


def oxford(items: list[str], joiner: str = "and") -> str:
    """Join a list the way it is read aloud."""
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {joiner} {items[1]}"
    return f"{', '.join(items[:-1])} {joiner} {items[-1]}"


# Claims that contradict each other -------------------------------------
# Markers that turn a claim into the opposite of a stored one. This lives here
# rather than in the engine because the store needs it too: a quirk that
# contradicts one already held must supersede it at the moment it is written,
# not merely be noticed later when both are read out together.
OPPOSITES = (
    ("first", "last"), ("top", "bottom"), ("before", "after"),
    ("start", "end"), ("above", "below"), ("clockwise", "anticlockwise"),
    ("left", "right"), ("open", "closed"), ("on", "off"),
)
NEGATIONS = ("no ", "not ", "never ", "isn't", "doesn't", "hasn't", "there's no", "without")


def contradicts(stored: str, claim: str) -> bool:
    """A contradiction is information, not an error — but spot it first."""
    stored_words, claim_words = set(words(stored)), set(words(claim))
    shared = stored_words & claim_words
    if len(shared) < 2:
        return False
    for left, right in OPPOSITES:
        if (left in stored_words and right in claim_words) or (
            right in stored_words and left in claim_words
        ):
            return True
    stored_low, claim_low = f" {normalise(stored)} ", f" {normalise(claim)} "
    negated_now = any(marker.strip() in claim_low for marker in NEGATIONS)
    negated_then = any(marker.strip() in stored_low for marker in NEGATIONS)
    return negated_now != negated_then and len(shared) >= 2
