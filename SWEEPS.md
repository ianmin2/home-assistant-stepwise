
# Sweeps

What adversarial review of our own releases keeps finding, and what happened
about it. The first two sweeps ran before 0.2.1 shipped and live in
[PLAN_GAPS.md](PLAN_GAPS.md); this file picks up from there, one section per
sweep, newest first.

The habit exists because of what the first sweep taught: a list of what
shipped, written from the list of what was planned, is fiction. The code is
the only witness worth calling. Every finding below was reproduced by
running the engine before it was believed, and fixed before it was written
down as fixed.

---

## The third sweep — 0.2.1 as shipped

Two deep dives into ground the first two sweeps never properly walked: the
correction flow (the flagship), and the resolution heuristics (the front
door). Plus a look at the seams the earlier fixes themselves created. All
findings executed, twenty-four in total. All fixed in 0.2.2 except the three
listed as accepted at the end.

### The headline

**Told the opposite of its own note, it agreed — and confirmed the opposite.**

> Stored: *"the yeast goes in first."*
> You say: *"the yeast goes in last."*
> It says: *"You're right, and I have that noted. Reordering."*

The agree-branch of `run_challenge` fired on string similarity alone, and the
plainest way to contradict a claim is to repeat it with one word changed — the
most similar string possible. The contradiction check existed, sat one branch
lower, and never got asked. Add a word ("…in last **actually**") and the right
branch fired, which is why no test ever saw it.

One line: the agree-branch now refuses anything the contradiction check
disputes. This was the worst finding of the round, and it was in the feature
the whole pitch leans on.

### The correction flow

| | What happened | Now |
|---|---|---|
| **Agreeing with the opposite** | As above | Contradictions can't agree |
| **Reorder + change in one call** | The change was applied against the pre-reorder step map, so it rewrote the wrong step — including the *shared template's* wrong step, permanently, for every future run | The map is re-read after the reorder |
| **Duplicate numbers in a reorder** | `reorder=[3,3,1]` cheerfully duplicated step 3 | Deduped, first occurrence wins |
| **Amending a step that doesn't exist** | "Changed step 9." — on a five-step run, with nothing changed | Says there are only five, changes nothing |
| **`also_steps` did nothing** | The tool advertised "other steps this change affects" and silently ignored them | They're amended too |
| **Confirming a withdrawn note** | "Yes, still right" on a retracted quirk said "I'll keep that" while keeping nothing | Says the note was already withdrawn |
| **Web-learned quirks born confirmed** | Every quirk made through the tools was stamped as user-confirmed, so the "read that somewhere, never confirmed by you" re-check could never fire | Only the person's own words confirm |
| **The fact outlives the quirk** | Every subject correction was mirrored into the facts table; retracting the quirk left the fact behind, re-asserted at every run start, forever, with no voice path out. Flagged in sweep one, never actually fixed | The mirror is gone — quirks already reach the agent |
| **Undo after a reorder** | Walked back to a step number from the *old* numbering, landing somewhere already done | If the steps have moved since the last pointer move, it asks where you want to be instead of guessing |
| **Empty quirks** | A reorder with no stated reason stored a quirk with an empty claim | No claim, no quirk |
| **Timers blaming the programme** | A step's own ten minutes offered as "that's the programme length" | The reason only names the programme when the number came from it |

### The front door

| | What happened | Now |
|---|---|---|
| **A paused run was invisible to "guide me through…"** | "Guide me through the rosemary loaf", with that loaf paused, got "There's the rosemary loaf on file" — as if you'd never started | Paused counts as on the go; it resumes |
| **Clean speech flagged as mishearing** | Five of twenty ordinary sentences got questioned. The worst: *"talk me through changing the chain"* → "By changing, did you mean chain?" — offering a word from later in the same sentence | Candidates already present in the utterance don't count; plurals and inflections of known words are known; the kind-synonyms list finally gets consulted |
| **"What else is there?"** | The list sat in the payload while the speech said "I can't answer that" | If the list was the answer, the list is the speech |
| **"whats next" (no apostrophe)** | Missed the what's-left check entirely — the exact case the comment above the regex claimed to handle | Matches |
| **"How long on this step?"** | Answered with total time remaining — confidently, and wrong | Answers time on this step |
| **"Go back" at step one** | "I'm not sure which you mean" plus three random steps | "You're already at the start" |
| **"Step 40" on a seven-step run** | Fell through to fuzzy guessing | "There are only seven" |
| **Re-requesting a known procedure in your own words** | *"That rosemary bread we did before"* planned a duplicate — the overlap scoring that `_pick_run` already had never made it into the library search | It did now |
| **Exact name, nagged anyway** | "The loaf", with "the rosemary loaf" also live, asked which — despite an exact match | An exact match wins outright |
| **Short sentences joined anyone's thought** | Any remark of five words or fewer glued onto a held half-intent, whoever said it | Up to three words joins freely (answers are short); four or five need a shared word |

### The seams the earlier fixes made

- **Silent resurrection.** "It's gone a bit sticky" quietly reopened a stopped
  run and said only "Noted." — a silent override, and the rule is there are
  none. Announced now, from one choke point rather than eleven reply sites
  each having to remember, because eleven sites remembering is how it got
  missed.
- **A voice pass over everything the sweeps added.** The fixes had started
  talking like a courier app ("Picked the rosemary loaf back up"). Now: *"Back
  on the rosemary loaf, then."* / *"Right, leaving the rosemary loaf at step
  two of three. It'll keep — just ask where were we when you're back."* /
  *"Hold on — I've got you on step 3. Did I lose you?"*

### Accepted, not fixed

- **"The second prove" when there's only one** lands on the one there is and
  doesn't argue about the word "second". Landing is audible, so a wrong
  assumption gets caught the way everything else does.
- **Near-synonym quirks still accumulate** — "yeast goes in before the flour"
  and "put yeast in at the start" are two active quirks, because the
  contradiction test wants shared words and these share almost none. The
  guard errs toward keeping what you said over merging what it can't prove is
  the same. The cost is an occasional double-statement; the alternative is
  quietly discarding a correction.
- **"do miney" for Domane** slips the mishearing net ("do" reads as filler).
  Tightening it re-opens the false-positive door the fix above just closed.

### Attacked and held

The README's own promises, tested as written: the yeast-first reorder carries
the pointer to the first outstanding step; a template amendment never touches
another live run of it; quirks never leak between two bikes; a 180-day-old
quirk is re-confirmed aloud with its age and provenance; stating a quirk never
confirms it; "go back, I've not done the salt yet" goes to the salt, not back
one; two radiators ask which; the garble net still catches *tang zong*,
*gadgia*, *wooster* and *panasonik* with the right single candidate; asides
answer from the clock and the procedure and refuse politely what they can't
know; and the whole 212-test suite, before and after.
