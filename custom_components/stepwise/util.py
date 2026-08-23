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
    """Format a moment for storage."""
    if moment is None:
        moment = utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


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
        if minutes:
            return f"{hours} hours {minutes}" if hours != 1 else f"an hour {minutes}"
        return "an hour" if hours == 1 else f"{hours} hours"
    if minutes:
        if secs >= 30:
            return f"{minutes} and a half minutes"
        return "a minute" if minutes == 1 else f"{minutes} minutes"
    return f"{secs} seconds"


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
