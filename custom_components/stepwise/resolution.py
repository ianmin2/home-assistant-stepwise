"""Working out what the person actually means, before there is a run.

Two jobs (section 4): turning "my bike" into exactly one subject, and catching
the words speech-to-text mangles. Domain vocabulary is exactly what Whisper
gets wrong, so a term that matches nothing known is offered back as phonetic
candidates rather than silently believed.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import Procedure, Run, Subject
from .util import iso, normalise, oxford, utcnow, words

# Everyday words for a kind, so "my bike" finds a subject of kind "bicycle".
# Anything beyond this belongs in a subject's own aliases.
KIND_SYNONYMS: dict[str, str] = {
    "bike": "bicycle",
    "cycle": "bicycle",
    "pushbike": "bicycle",
    "breadmaker": "bread_machine",
    "bread maker": "bread_machine",
    "breadmachine": "bread_machine",
    "rad": "radiator",
    "fridge": "refrigerator",
    "freezer": "freezer",
    "dishwasher": "dishwasher",
    "washer": "washing_machine",
    "washing machine": "washing_machine",
    "car": "car",
    "boiler": "boiler",
    "plant": "houseplant",
    "printer": "printer3d",
}

# Words that carry no distinguishing weight when matching a subject.
_NOISE = {
    "the", "a", "an", "my", "our", "this", "that", "one", "please", "in", "on",
    "with", "for", "to", "of", "and", "it", "its", "using", "use",
}

# Filler that speech-to-text is good at, so a pair containing one of these is
# not a word broken in two: it is a word and some scaffolding.
_PAIR_NOISE = {
    "is", "are", "was", "were", "be", "been", "am", "i", "im", "you", "your",
    "me", "we", "they", "do", "does", "did", "get", "got", "make", "made",
    "take", "check", "want", "need", "put", "has", "have", "had", "will",
    "would", "can", "could", "at", "by", "from", "up", "down", "out", "off",
    "over", "but", "or", "if", "so", "then", "there", "here", "what", "when",
    "how", "why", "not", "no", "yes", "just", "now", "next", "step", "about",
    "some", "any", "soon", "please", "probably", "maybe", "wants",
}

# Ordinary English that happens to be long enough to look like a term. These
# are never what somebody is naming, so a close phonetic match to one of them
# is a false alarm — and "talk me through" is the phrase the front page tells
# people to say, which used to come back as "Dough? Speech-to-text sometimes
# gives me that as through."
_ORDINARY = {
    "through", "though", "although", "against", "around", "across", "before",
    "after", "while", "until", "unless", "under", "above", "below", "between",
    "about", "again", "another", "other", "these", "those", "their", "there",
    "where", "which", "whose", "still", "every", "each", "both", "little",
    "talk", "walk", "guide", "show", "tell", "start", "finish", "begin",
    "please", "thanks", "should", "would", "could", "might", "going", "doing",
    "being", "something", "anything", "everything", "nothing", "myself",
    "really", "properly", "quickly", "slowly", "first", "second", "third",
    "ready", "right", "wrong", "better", "worse", "enough",
}

_SOUND_CLASSES = (
    ("bfpv", "B"),
    ("cgjkqsxz", "K"),
    ("dt", "T"),
    ("l", "L"),
    ("mn", "N"),
    ("r", "R"),
    ("wy", "W"),
    ("h", ""),
)


def sound_key(text: str) -> str:
    """A crude consonant skeleton, good enough to compare mishearings.

    Not a phonetic algorithm with a name: the job here is only to make
    "yang zoong" and "tangzhong" look similar enough to be offered as a
    candidate, and the comparison is fuzzy rather than an equality test.
    """
    key: list[str] = []
    for char in normalise(text).replace(" ", ""):
        for letters, code in _SOUND_CLASSES:
            if char in letters:
                if code and (not key or key[-1] != code):
                    key.append(code)
                break
    return "".join(key)


def similarity(left: str, right: str) -> float:
    """How alike two terms are, by spelling and by sound."""
    a, b = normalise(left), normalise(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    spelled = difflib.SequenceMatcher(None, a, b).ratio()
    sounded = difflib.SequenceMatcher(None, sound_key(a), sound_key(b)).ratio()
    return max(spelled, (spelled + sounded) / 2)


def phonetic_candidates(
    term: str,
    vocabulary: Iterable[str],
    limit: int = 3,
    threshold: float = 0.62,
    margin: float = 0.08,
) -> list[tuple[str, float]]:
    """Best guesses at what an odd-sounding term was meant to be.

    Only guesses close to the best one are kept. "Tangzhong?" is a good
    question; "tangzhong, or Panasonic?" is a worse one, and offering the
    also-ran is what makes somebody stop trusting the question.
    """
    scored: dict[str, float] = {}
    for known in vocabulary:
        if not known:
            continue
        score = similarity(term, known)
        if score >= threshold and normalise(known) != normalise(term):
            scored[known] = max(scored.get(known, 0.0), score)
    ranked = sorted(scored.items(), key=lambda pair: (-pair[1], pair[0]))
    if not ranked:
        return []
    best = ranked[0][1]
    return [(name, score) for name, score in ranked if best - score <= margin][:limit]


def vocabulary_of(
    subjects: Sequence[Subject] = (), procedures: Sequence[Procedure] = ()
) -> list[str]:
    """Everything this installation already knows how to say."""
    known: list[str] = []
    for subject in subjects:
        known.extend(part for part in (subject.label, subject.make, subject.model) if part)
        known.extend(subject.aliases)
        known.append(subject.kind.replace("_", " "))
    for procedure in procedures:
        known.append(procedure.title)
        for step in procedure.steps:
            known.extend(step.ingredients)
    seen: dict[str, None] = {}
    for item in known:
        cleaned = (item or "").strip()
        if cleaned and normalise(cleaned) not in {normalise(k) for k in seen}:
            seen[cleaned] = None
    return list(seen)


@dataclass(slots=True)
class SubjectMatch:
    subject: Subject
    score: float
    how: str  # id | label | alias | make_model | kind | phonetic

    @property
    def distinguishing(self) -> bool:
        """Did the words pick out this one thing, or merely its category?"""
        return self.how in ("id", "label", "alias", "make_model")


@dataclass(slots=True)
class SubjectResolution:
    """Resolved, ambiguous, or nothing known yet. Never a silent guess."""

    status: str  # resolved | ambiguous | unknown
    subject: Subject | None = None
    candidates: list[SubjectMatch] = field(default_factory=list)
    question: str | None = None
    loose: bool = False
    speech: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "subject_id": self.subject.id if self.subject else None,
            "subject": self.subject.described if self.subject else None,
            "loose": self.loose,
            "candidates": [
                {"id": match.subject.id, "label": match.subject.described, "how": match.how}
                for match in self.candidates
            ],
            "question": self.question,
        }


def match_subjects(spoken: str, subjects: Sequence[Subject]) -> list[SubjectMatch]:
    """Score every active subject against what was said."""
    said = normalise(spoken)
    said_words = [word for word in words(spoken) if word not in _NOISE]
    kind_hint = None
    for phrase, kind in KIND_SYNONYMS.items():
        if phrase in said or phrase in said_words:
            kind_hint = kind
            break

    matches: list[SubjectMatch] = []
    for subject in subjects:
        best: tuple[float, str] | None = None

        def offer(score: float, how: str) -> None:
            nonlocal best
            if score > 0 and (best is None or score > best[0]):
                best = (score, how)

        if said and said == normalise(subject.id):
            offer(1.0, "id")
        offer(similarity(said, subject.label), "label")
        for alias in subject.aliases:
            offer(similarity(said, alias), "alias")
        make_model = " ".join(part for part in (subject.make, subject.model) if part)
        if make_model:
            offer(similarity(said, make_model), "make_model")
            if subject.model and normalise(subject.model) in said:
                offer(0.99, "make_model")
        kind_words = subject.kind.replace("_", " ")
        named_the_kind = (kind_hint and kind_hint == subject.kind) or (
            normalise(kind_words) and normalise(kind_words) in said
        )
        if named_the_kind:
            # Naming the category is a match, but never a distinguishing one.
            offer(0.7, "kind")
        else:
            offer(min(similarity(said, kind_words), 0.69), "kind")

        if best and best[0] >= 0.55:
            matches.append(SubjectMatch(subject=subject, score=best[0], how=best[1]))

    matches.sort(key=lambda match: (-match.score, match.subject.label))
    return matches


def resolve_subject(
    spoken: str, subjects: Sequence[Subject], gap: float = 0.12
) -> SubjectResolution:
    """One matching subject and it proceeds. Two and it asks which."""
    matches = match_subjects(spoken, subjects)
    if not matches:
        return SubjectResolution(
            status="unknown",
            question=f"I don't have anything on file for {spoken.strip()}. What is it?",
            speech=f"I don't have anything on file for {spoken.strip()}. What is it?",
        )

    best = matches[0]
    rivals = [match for match in matches[1:] if best.score - match.score < gap]

    if rivals:
        # Ambiguous reference is resolved, not guessed (section 7).
        options = [match.subject.described for match in [best, *rivals]]
        question = f"Which one, {oxford(options, 'or')}?"
        return SubjectResolution(
            status="ambiguous",
            candidates=[best, *rivals],
            question=question,
            loose=True,
            speech=question,
        )

    # Loose means "worth re-confirming a quirk against": matched by category,
    # or matched by a name that only nearly fits.
    loose = not best.distinguishing or best.score < 0.9
    return SubjectResolution(
        status="resolved",
        subject=best.subject,
        candidates=[best],
        loose=loose,
        speech=best.subject.described,
    )


# The endings a known word can wear and still be itself.
_SUFFIXES = {"s", "es", "ing", "ed", "d", "er", "ers", "ier"}


def odd_terms(
    spoken: str, vocabulary: Sequence[str], min_length: int = 5
) -> list[tuple[str, list[tuple[str, float]]]]:
    """Terms that match nothing known, with what they might have been.

    Adjacent words are tried together as well as alone, because speech-to-text
    breaks one unfamiliar word into two familiar ones far more often than it
    invents a single strange one: "derailleur" comes back as "the rail er", and
    "tangzhong" as "yang zoong". A pair that matches something known beats
    either of its halves.

    Only reported when there is something plausible to offer. A genuinely new
    word is not an error; it is just a new word.
    """

    def already_known(term: str) -> bool:
        return any(normalise(known) == term or term in normalise(known) for known in vocabulary)

    known_words = {word for known in vocabulary for word in words(known)}
    # The kinds people say — "freezer", "boiler" — are as known as anything in
    # the library, and inflections of a known word are the word: "changing" is
    # not a mishearing while "change" sits in the vocabulary, and "houseplants"
    # is not strange because only "houseplant" is on file.
    known_words |= {word for phrase in KIND_SYNONYMS for word in words(phrase)}

    def familiar(term: str) -> bool:
        """A known word wearing an English ending is the known word.

        "Changing" is not a mishearing while "change" is on file, and
        "houseplants" is not strange because only "houseplant" is. The ending
        must be a real suffix, though — "panasonik" is one letter off
        "panasonic" and that is a mishearing, which is the whole trade.
        """
        if term in known_words:
            return True
        for known in known_words:
            if len(known) < 4:
                continue
            stems = {known}
            if known.endswith("e"):
                stems.add(known[:-1])  # change -> chang + ing
            for stem in stems:
                if term != stem and term.startswith(stem) and term[len(stem):] in _SUFFIXES:
                    return True
        return False
    spoken_words = words(spoken)
    findings: list[tuple[str, list[tuple[str, float]]]] = []
    consumed: set[int] = set()

    # Pairs first, so the better match wins over one of its halves.
    for index in range(len(spoken_words) - 1):
        left, right = spoken_words[index], spoken_words[index + 1]
        if left in _NOISE or right in _NOISE:
            continue  # "the tangzhong" is not a mishearing of anything
        if left in _PAIR_NOISE or right in _PAIR_NOISE:
            continue
        if left in _ORDINARY or right in _ORDINARY:
            continue
        if familiar(left) or familiar(right):
            continue
        if index in consumed or index + 1 in consumed:
            continue
        pair = f"{left} {right}"
        joined = pair.replace(" ", "")
        if len(joined) < min_length or already_known(joined) or already_known(pair):
            continue
        candidates = phonetic_candidates(joined, vocabulary)
        # A pair needs to be a better match than a single word does, because
        # there are far more pairs to go wrong.
        if candidates and candidates[0][1] >= 0.70:
            findings.append((pair, candidates))
            consumed.update({index, index + 1})

    for index, term in enumerate(spoken_words):
        if index in consumed or len(term) < min_length:
            continue
        if term in _NOISE or term in _PAIR_NOISE or already_known(term) or familiar(term):
            continue
        if term in _ORDINARY:
            continue  # a common word is a common word, not a mangled one
        # A short word needs a better match before it is queried. "Check" is
        # close enough to plenty of things to be worth asking about, and asking
        # would be wrong every time.
        # Long everyday words sit surprisingly close to brand names — weather
        # scores 0.69 against Worcester — while genuine garble lands higher:
        # wooster 0.82, panasonik 0.94. The line goes between them.
        threshold = 0.75 if len(term) <= 6 else 0.72
        candidates = phonetic_candidates(term, vocabulary, threshold=threshold)
        if candidates:
            findings.append((term, candidates))

    # Offering a word the person also said is nonsense on its face: "by
    # changing, did you mean chain?" — the chain is two words later in the
    # same sentence. Such candidates go; a finding with none left goes whole.
    heard = set(spoken_words)

    def unsaid(candidate: str) -> bool:
        parts = [word for word in words(normalise(candidate)) if word not in _NOISE]
        return not parts or not all(word in heard for word in parts)

    kept: list[tuple[str, list[tuple[str, float]]]] = []
    for term, candidates in findings:
        remaining = [(candidate, score) for candidate, score in candidates if unsaid(candidate)]
        if remaining:
            kept.append((term, remaining))
    return kept


def confirm_hearing(term: str, candidates: list[tuple[str, float]]) -> str:
    """Ask, rather than inventing a procedure for a word that was never said."""
    if not candidates:
        return ""
    guesses = [candidate for candidate, _ in candidates]
    if len(guesses) == 1:
        return (
            f"{guesses[0].capitalize()}? Speech-to-text sometimes gives me that as "
            f"{term}."
        )
    return f"By {term}, did you mean {oxford(guesses, 'or')}?"


@dataclass(slots=True)
class LocalMatch:
    """Something this installation already has. Searched before the web."""

    kind: str  # procedure | run
    id: str
    title: str
    score: float
    when: str | None = None


def search_local(
    spoken: str, procedures: Sequence[Procedure], runs: Sequence[Run] = (), threshold: float = 0.55
) -> list[LocalMatch]:
    """Their own past procedures and runs first. People repeat themselves."""
    found: list[LocalMatch] = []
    said_words = set(words(spoken)) - _NOISE
    for procedure in procedures:
        score = similarity(spoken, procedure.title)
        title_words = set(words(procedure.title)) - _NOISE
        if said_words and title_words:
            # A long sentence around a short title dilutes plain similarity —
            # "that rosemary bread we did before" barely resembles "Rosemary
            # tangzhong loaf" as a string, and a duplicate got planned. What
            # the words have in common is the better witness.
            overlap = len(said_words & title_words) / len(title_words)
            score = max(score, overlap * 0.9 if overlap >= 0.5 else score)
        if score >= threshold:
            found.append(
                LocalMatch("procedure", procedure.id, procedure.title, score, procedure.updated_at)
            )
    for run in runs:
        score = similarity(spoken, run.reference)
        if score >= threshold:
            found.append(LocalMatch("run", run.id, run.reference, score, run.updated_at))
    found.sort(key=lambda match: (-match.score, match.when or ""))
    return found


@dataclass(slots=True)
class ResolutionSession:
    """The half-formed intent. Temporary by design (section 4).

    Not stored as a fact and not stored as a run: it either becomes a run or it
    expires.
    """

    words: str
    started_at: str = field(default_factory=iso)
    asked: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    subject_id: str | None = None
    loose: bool = False
    target: str | None = None

    def ask(self, question: str) -> str:
        if question not in self.asked:
            self.asked.append(question)
        return question

    def answer(self, question: str, reply: str) -> None:
        self.answers[question] = reply

    # Half an hour was far too long for a speaker in a shared kitchen: a
    # second person's unrelated sentence was being glued onto the first
    # person's half-formed intent. Long enough to answer a question, short
    # enough that somebody else's remark is a new thought.
    TTL_MINUTES = 4

    def expired(self, ttl_minutes: int | None = None, now: Any = None) -> bool:
        from .util import elapsed_seconds

        gone = elapsed_seconds(self.started_at, now or utcnow())
        return gone is not None and gone > (ttl_minutes or self.TTL_MINUTES) * 60
