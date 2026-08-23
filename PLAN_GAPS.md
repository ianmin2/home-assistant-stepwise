
# Where Stepwise is lagging

**A gap analysis against the code as it stands, August 2026.**
Companion to [PLAN.md](PLAN.md), which is the design. This document is the
distance between the design and what is actually built, plus the distance
between what is built and what the rest of the world shipped while it was being
written.

Every claim here was checked against running code. Where something looks like a
gap and turns out to be handled, it is listed in [section 7](#7-not-gaps) with
the code that handles it — a false gap is worse than a missing one, because it
costs the same attention and buys nothing.

---

## 1. The short version

Three findings decide the shape of this release.

**The positioning is currently false in code.** The README says quirks
supersede rather than accumulate; they accumulate whenever the wording differs.
It says cold runs are offered and never assumed; only `run_where` honours that,
and every tool that moves the pointer ignores it. These are not features that
are missing. They are claims that are made and not kept, which is worse.

**The worst failure the project names is the one it does not defend against.**
PLAN §8.1: *"the single most damaging failure is silently being on a different
step from the person."* `run_goto` defends against this properly — a confidence
threshold, a runner-up margin, an "unsure, which of these?" reply, and it always
announces where it landed. `run_advance` does none of those things, announces
nothing, and cannot be undone. It is also the utterance that happens fifty times
a run.

**What it says out loud is mangled in ways a person hears within a minute.**
Verified through the real pipeline: `"Preheat to 180 C"` is spoken as *"180 cups
of preheat to"*. `"Bake at 180"` becomes *"180 of bake at"*. `"Put 2 in the
tin"` becomes *"Put 5.1 centimetres the tin"*. Seven grams of salt, in imperial,
is offered as *"0.2 ounces"*, which no kitchen scale can read and which is 20%
out from rounding.

So 0.2 is not a feature release. It is **trust the pointer, and trust what it
says**.

---

## 2. What changed outside

The landscape moved between 0.1.0 and now, and it moved in a direction that is
mostly good for this project.

| | What shipped | What it means here |
|---|---|---|
| **Alexa+** | To every US Prime household, 4 Feb 2026. LLM-backed, household memory, per-step recipe timers set unasked, claims to "pick up where you left off" | The claim is conversational context, not a durable pointer. Reviewers at three months call autonomous multi-step "half-baked" |
| **Gemini for Home** | Conversational memory window extended to **15 minutes**, shipped July 2026 as a headline feature | Gemini Live guidance is session-bound. End the session and the state is gone |
| **Google Nest Hub** | *Deleted* step-by-step recipe following, Feb 2024, as "underutilised" — with the cookbook and saved recipes | Demand is proven by the complaints. The screen-first form of it was measured and cut |
| **iFixit FixBot** | Voice, hands-free, grounded in 125,000 repair guides, photo diagnosis, part compatibility | Explicitly no step tracking, no resumption |
| **Connected-worker tier** | Dozuki, Tulip, Parsable, Poka, Augmentir, L2L — durable step state, deviation capture, timestamped records, shift handover | Does what Stepwise does. Tablet-first, per-seat, factory-priced, uninterested in a household |

### The single sharpest fact

**Alexa+ shipped a memory system that cannot be corrected by voice.** Tell it
your keys are in the bedroom, then tell it they are in the kitchen, and it holds
both. There is no spoken way to make it forget.

Stepwise's entire correction flow — `run_challenge` → `run_amend` →
`quirk_confirm(still_right=False)` → `retract_quirk` — is a working answer to
exactly that defect.

Resumption is a roadmap item for Amazon and Google. **Voice-correctable
per-instance knowledge is a shipped defect for Amazon.** The positioning should
lead with the thing they got wrong, not the thing they got early — a nine-month
lead on a roadmap item is not a moat, and an architectural choice they cannot
cheaply retrofit onto an append-only household memory is closer to one.

Which makes G1 and G2 below not housekeeping. They are the difference between
that argument being true and being marketing.

---

## 3. Gaps, in priority order

Severity: **critical** — the product's own premise fails. **high** — a person
hits it in normal use. **medium** — degrades trust. **low** — cosmetic.

### 3.1 The positioning is false in code

#### G1 · Contradictory quirks accumulate
`store.py:482-497` · **critical** · hours

`add_quirk` supersedes only when `normalise(existing.claim) == normalise(new)`.
`Engine._contradicts()` at `engine.py:1526` already understands opposites and
negations, and is used at *read* time — `_needs_reconfirm`, `run_challenge` —
and never at write time. So *"yeast goes in first"* and *"yeast goes in last"*
both stay `active`, both satisfy `_bears_on()` for the same step, and
`quirks_to_state()` will read **both aloud in the same breath**.

This is Alexa's keys bug, reproduced inside the feature built to beat it. The
README's "quirks supersede rather than accumulate" is unearned until it is
fixed.

#### G2 · The fact store cannot forget
`store.py:560` · **critical** · hours

`forget_fact` exists and is called by nothing — no tool, no service, no options
step. Meanwhile `RunAmendTool` writes into memory on *every* subject-scoped
amendment, so each learned quirk is stored twice: once correctable, in `quirks`,
retractable from the options flow; and once permanently, in `facts`.

You cannot run the "Alexa can't forget, we can" argument while your own fact
table cannot forget either.

**It is the same bug as G1, in a second store, and it reaches further than the
entry suggests.** `add_fact` already dedupes on exact normalised text, so what
survives is precisely the *contradiction* case — identical to G1. And
`MemoryBackend` has no `forget` in the abstract base at all, so wiring up
`forget_fact` repairs only the built-in backend; `ha_ai_memory` still cannot
forget. Treat G1 and G2 as one defect with three call sites, not two tickets.

#### G3 · "Cold is offered, never assumed" holds in exactly one tool
`engine.py:258-263` · **critical** · hours

`current_run()` returns `open_runs()[0]` — most recently touched — with no
stickiness check at all. `run_where` honours hot/warm/cold properly
(`engine.py:627-645`). `run_advance`, `run_goto`, `run_note`, `run_challenge`,
`run_amend` and `run_finish` do not; `run_advance` computes the state only to
decide whether to prefix the reference.

Say "done" two days later with two runs open, and the pointer moves on the
most recently touched one, silently. An adversarial reviewer reproduces this in
ninety seconds.

### 3.2 Pointer integrity

#### G4 · Advance is unguarded, unannounced, and cannot be undone
`engine.py:688-738` · **critical** · half a day

Three separate absences, compounding:

- **No agreement check.** It advances whatever run was touched last, with no
  confirmation that the model is on the step it thinks it is.
- **No announcement.** Verified: `run_advance()` returns `'7 grams salt'` — no
  number, no "of nine". It is the *only* pointer move that does not say where it
  landed. `run_goto` says it, `run_where` says it, `run_amend` says it.
- **No undo.** Nothing in the fifteen tools reverses a pointer move.

The failure: person on step 3 of 9 says *"It's in — oh, and it's clumping."* A
small model emits `run_advance` **and** `run_note`. The pointer is on 4. They
hear step 5's instruction, assume the salt was fine, and are silently a step
ahead. The event log records an `advanced` at that timestamp, so even the audit
trail agrees with the machine.

**The asymmetry is the design insight**: note-mistaken-for-advance skips work
silently; advance-mistaken-for-note merely stalls, and the person says "next"
again. Only one direction needs defending.

**Announcing the number is the higher-value half, not the undo.** A backwards
`run_goto` already restores the pointer, so a path out exists; what is missing
is the *audit* that makes somebody notice they need it. Saying "step four of
nine" costs one clause and turns a silent skip into an audible one. Build that
first, and `run_undo` second.

`from_step` should be **optional**. A model confident enough to call
`run_advance` on an observation is confident enough to pass the number it just
read out, and to be wrong identically — so requiring it does not prevent the
skip, while it does reliably stall the most frequent utterance in the product.
What it does catch is model desync from stale context, and for that, optional is
enough: the desynced model is exactly the one still holding an old number. Log
absent, present and mismatched, so 0.3 has evidence rather than a second guess.

`run_undo` should be **pointer-only, and append rather than delete**. Quirks are
already reversible through `quirk_confirm(still_right=False)`, and a second way
to unlearn the same thing recreates the discrimination problem this exists to
fix. Cancelling a timer somebody is relying on, from a tool that cannot
guarantee it started, is a new silent failure. Reordering is tempting and still
no — reversal has to reconcile `run_steps`, `source_n`, `run_amendments` and the
pointer, and the previous order is already recorded verbatim in the amendment's
`was` column when that is wanted later. Whatever it reverses, it **writes a new
event and never deletes the `advanced` one**: mutating the spine kills the
lab-notebook claim the day G28 ships.

#### G5 · "Stop" is permanent — `paused` is declared and never implemented
`const.py:73,96,97` · **high** · half a day

`RUN_PAUSED`, `EVENT_PAUSED` and `EVENT_RESUMED` exist in `const.py`, and
`OPEN_RUN_STATUSES` includes paused. **Nothing anywhere sets or emits them** —
verified by grep across the tree.

Speech-to-text turns *"hang on, stop a sec"* into a stop. The model calls
`run_finish(abandoned=True)`. The run leaves `open_runs` forever, "where were
we" answers *"Nothing on the go"*, and the options flow only offers to close
runs, never to reopen one. For a project whose stated product **is** pause and
resume, the word most likely to be misheard is unrecoverable by voice.

**A pause flag solves the consequence, not the misrecognition.** Moving the
burden from "wrong tool" to "wrong flag on the right tool" makes it worse, if
anything: a boolean gets less model attention than a tool name. *"Hang on, stop
a sec"* and *"I'm giving up on this"* are genuinely ambiguous in text, and no
prompt line fixes that at 4B.

What repairs **both** choices is cheaper than pause: **make a recently closed
run findable by its reference.** `run_where("the loaf")` on a run abandoned ten
minutes ago should say *"you left the rosemary loaf at step three, about ten
minutes ago — pick it up?"* That is a read-path change: no new tool, no new
status, and **no model discrimination at all**, which is the only kind of fix a
small model cannot defeat. Pause then becomes a nicety on top rather than the
load-bearing part.

Two constraints if it ships anyway, and it should. Do not add `paused=True`
alongside `abandoned=True` — two booleans means the model sets both or neither;
one `how: "done" | "paused" | "stopped"` is one decision. And **pruning has to
respect it**: `prune_runs` deletes on `(RUN_DONE, RUN_ABANDONED)`, so a
mistakenly abandoned run becomes a deletion candidate as soon as twenty others
exist for that subject — which, with the NULL bucketing in G27, arrives far
sooner than anyone expects. Reopenability and G27 are one ticket.

#### G6 · A hallucinated or stale `run_id` reports "Nothing on the go"
`engine.py:258-263, 597-602` · **high** · an hour

Verified: `run_where(run_id='run_deadbeef')` returns *"Nothing on the go."*
while a run is live. A small model echoing a run id from three turns ago makes
the core promise fail in the most alarming way available — asked "where were
we", mid-loaf, it says there is nothing.

**Where the fix goes matters more than the gap does.** That repro is
engine-level: `RunWhereTool` exposes only `reference`, so `run_where`'s `run_id`
is reachable from the options flow and nowhere else. The version a person
actually hits is `run_advance(run_id=<hallucinated>)`. So the fallback belongs
in `current_run`, which all nine `run_id`-accepting tools inherit — patching
`run_where` would tick the gap off and leave it live everywhere that matters.

#### G7 · A closed run can still be advanced by id
`engine.py:258-263` · **medium** · fifteen minutes

Verified: after `run_finish(abandoned=True)`, `run_advance(run_id=…)` on that
run returns the next instruction and moves `current_step` from 2 to 3 on a run
whose status is `abandoned`. `current_run()` never filters on
`OPEN_RUN_STATUSES`. Silent mutation of archived history, invisible in
`open_runs`.

#### G8 · Lost update: two concurrent advances skip a step
`engine.py:688-738`, `store.py:356-359` · **high** · small

The store layer is sound — one connection, `check_same_thread=False`, every
statement through an `RLock`, multi-statement writes holding it throughout.
**The engine layer is where it breaks.** `run_advance` reads the run at :692 and
saves the whole row at :707 with no lock across, and `save_run` is a full-row
upsert. Two concurrent advances both read step 3 and both write step 4. One step
is silently skipped, and the log shows two `advanced` events at step 3.

Reachable today: two voice satellites, or the options flow's `run_finish`
racing a live session. It gets more reachable the moment automations can call
in.

### 3.3 What it says out loud

All verified by running `speech` and `util` directly.

#### G9 · Any instruction ending in a bare number is mangled
`speech.py:71-74` · **high** · two hours

`quantity_first` is applied automatically whenever the model omits `speakable`,
which `docs/procedures.md` documents as the normal case. `_TRAILING_QUANTITY`
matches any `.+?` followed by a number, so a trailing *setting* is treated as a
trailing *quantity*:

| Written | Spoken **and stored** |
|---|---|
| `Bake at 180` | **"180 of bake at"** |
| `Programme 4` | **"4 of Programme"** |
| `Set the oven to 200` | **"200 of set the oven to"** |
| `Preheat to 180 C` | **"180 cups of preheat to"** |

It persists into later answers: `run_ask("what is left")` returns *"Left to do:
step 3, 5 grams dried yeast; step 4, 180 of bake at."* `test_speech.py` pins
only the cases that work.

**And it is on disk.** `quantity_first` output is written into
`Step.speakable` at plan time (`engine.py:469`), saved to `procedure_steps`,
copied into `run_steps` when a run starts, and regenerated on amendment
(`engine.py:1100`). Every existing install is storing *"180 of bake at"*.
**Fixing the function repairs nothing already saved**, so G9 is not a bug fix —
it is a bug fix plus a data repair, which makes it a migration, which puts it
behind G25. There is no flag recording which `speakable` values were generated
and which an author supplied, so the repair must identify its own past output:
where `legacy_quantity_first(instruction)` equals the stored value, it was
generated and can be regenerated. Where it does not, somebody wrote it and it
must be left alone.

#### G10 · The unit expander eats "C", "in" and "m"
`speech.py:60,122,145` · **high** · two hours

The regex `(\d+…)\s*([a-zA-Z]{1,4})\b` cannot tell a unit from the next English
word. Verified: `"Put 2 in the tin"` → **"Put 5.1 centimetres the tin"** under
metric. `c` maps to cups, so a temperature becomes a volume.

`util.parse_duration` already solved this exact problem deliberately, with a
comment — *"`15 m` is millimetres as often as it is minutes"*. The same
discipline needs applying one module over.

#### G11 · Converted small masses are unusable and 20% out
`speech.py:79-86` · **medium** · half a day

Verified: `7 g salt` → **"0.2 ounces of salt"**; `10 g of chopped rosemary` →
**"0.4 ounces"**. `_tidy` rounds to one decimal, so the error is large and the
number is unreadable on any scale. DISCLAIMER §2 names this risk specifically —
*"a converted unit can change a quantity"*.

#### G12 · "an hour 1"
`util.py:103` · **medium** · twenty minutes

Verified: 3660 → *"an hour 1"*. 3720 → *"an hour 2"*. 5400 → *"an hour 30"*.
7260 → *"2 hours 1"*. These reach the person through `timer_offer`: *"Shall I
set a timer for an hour 1?"* The design's own example (11400 → *"3 hours 10"*)
happens to work, which is why it was never noticed.

#### G13 · "Noted." fifty times
`engine.py:834` · **medium** · twenty minutes

`run_note` returns the literal string every time. The README's own transcript
promises better — *"Noted, against step three."* The step number is sitting in
the reply already. Saying it is variation **and** a second free audit of the
pointer.

#### G14 · Proposed references are ungrammatical for verb-phrase titles
`engine.py:520-524` · **medium** · an hour

`propose_reference` lowercases and prefixes "the". *"Rosemary loaf"* gives the
good case. The README's own quick-start phrase gives a title like *"Descale the
kettle"* → *"Shall I call it **the descale the kettle**?"* The name is the main
defence against temporal drift (PLAN §5); it has to survive being said aloud.

#### G15 · Blind lowercasing mangles acronyms and model numbers
`speech.py:219,259,277` · **low** · ten minutes

`landed()`, `with_reference()` and `state_quirk()` all do
`text[0].lower() + text[1:]` unconditionally, so "ESP32…" becomes "eSP32" and
"SD-2500…" becomes "sD-2500". `quantity_first` already carries the right guard
at `speech.py:169`; it just needs reusing.

#### G16 · "Two things on the go" with three things
`engine.py:630` · **low** · five minutes

Verified: *"Two things on the go: the loaf, the door and the radiator."*

### 3.4 Failure, silence and first contact

#### G17 · No exception boundary anywhere in the tool layer
`llm_tools.py:73-77` · **high** · two hours

`StepwiseTool._run` calls into the engine with no `try`. Home Assistant's
conversation integrations catch `HomeAssistantError` and `vol.Invalid` around
tool calls; anything else propagates and the person gets the agent's generic
failure line, with no idea whether the step was recorded. (That last clause is
reasoning about HA's behaviour, not something executed here — the gap and the
fix stand either way.) Live paths that raise something else: a
bare `LookupError` from `_template()` (`engine.py:250`), reachable after a
restored backup; an `assert` in `run_start` (`engine.py:561`), which vanishes
entirely under `python -O`; any `sqlite3.OperationalError`.

The fix is thematically the most on-brand change in this document: catch, log,
and return a reply that **still says where the person is** — *"Something's gone
wrong at my end. You were on step three of the rosemary loaf, seven grams of
salt."* Failing while restating the place is the product working, not failing.

#### G18 · Empty `speech` on the two longest paths
`engine.py:317, 807` · **high** · two hours

`resolve_intent` on a cold start returns `speech: ''`. So does `run_ask`
whenever `_answer` cannot answer. PLAN §8.1's contract is that every tool
returns one speakable string, and these two return nothing at the moments the
person has been waiting longest.

Worse, `run_ask` compensates by handing back every remaining step, every note
and every ingredient — so a small model with no line to say and a list in front
of it will read the list, breaking both "one step at a time" and "never
summarise a set".

#### G19 · The first sentence a new user hears quotes their whole utterance back
`engine.py:310`, `resolution.py:239-243` · **high** · an hour

Verified on an empty database, with the README's own quick-start phrase:

```
resolve_intent("talk me through descaling the kettle")
  speech:         ''
  subject.question: "I don't have anything on file for talk me through
                     descaling the kettle. What is it?"
  asked_already:    [the same string again]
```

With `speech` empty, the only speakable-looking string in the payload is that
question — present twice, which doubles the odds a small model reads it out.
This is the quick start producing the worst first impression available: an
unnecessary question, in the wrong words, before anything useful.

#### G20 · After install, nothing tells anyone what to say
**high** · a day, half of it cheap

The config flow ends on a thresholds form. The options menu offers Settings,
Things and their quirks, Put a run down. There is no phrase list, no
notification, no entity, no service. The config entry card does appear under
Settings → Devices & Services, so the install is visible — but it registers no
platforms, so there is **nothing in the state machine, nothing to put on a
dashboard, and nothing an automation can reach**. The README has the phrases. The person standing in the kitchen does not have the
README.

#### G21 · A search inside `run_challenge` blocks the voice turn with no budget
`search/rest_command.py:39-46` · **medium** · an hour

`RunChallengeTool` awaits the search inline. `BundledSearch` allows 20 seconds;
`RestCommandSearch` sets **no timeout of its own** — it inherits whatever the
user's `rest_command` is configured with, default 10 seconds. It cannot hang
forever; the gap is that Stepwise imposes no budget of its own and cannot know
the user's. The person says *"my machine takes the yeast first"* and the
assistant goes quiet for as long as somebody else's setting says.

### 3.5 Two people, one kitchen

#### G22 · The prompt leaks every user's runs while the tools hide them
`llm_tools.py:667` · **high** · an hour

`_prompt` calls `open_runs()` with no user filter and lists up to five as
"Already part done", while every tool filters by `llm_context.context.user_id`.
Verified: Bob gets *"Nothing on the go."* from `run_where` **and** `run_advance`
while Alice's loaf is live — and Bob's system prompt is simultaneously telling
the model *"the rosemary loaf: step 1, last touched just now (hot)"*. The model
holds two contradictory sources of truth and picks whichever suits.

`async_get_api_instance` has the context in hand. `_prompt` takes no argument.

#### G23 · `run_id` bypasses ownership entirely
`engine.py:259-260, 598-600` · **medium** · an hour

`current_run` returns `store.get_run(run_id)` unchecked, and `run_where`
replaces the filtered list with an unchecked lookup. Nine tools accept `run_id`
and all nine inherit it.

**Worth correcting in PLAN.md:** §15 calls multi-user "cheap now, expensive to
retrofit". The expensive part — the schema — is already done. `runs.user_id`
exists, round-trips, is written by `run_start`, and `open_runs` filters on it.
Only enforcement and the read paths are missing, and they are localised. That is
a real de-risking of the roadmap and the plan should say so.

#### G24 · Two people on one speaker share a resolution session
`engine.py:186-194` · **medium** · two hours

Sessions key on `user_id or ""` and a new utterance is *appended*. Verified end
to end: A says *"talk me through bleeding the landing radiator"*, B says *"make
a cup of tea"*, and the session's words become
`'talk me through bleeding the landing radiator make a cup of tea'` — which is
what `odd_terms` and `search_local` then run against. Thirty minutes is far too
long a TTL for a shared kitchen speaker.

### 3.6 Data safety

#### G25 · The schema version is destroyed before it can be read, and already lies
`store.py:194-207`, `const.py:13` · **high** · half a day

Three problems, compounding:

1. `_migrate` **overwrites** `meta.schema_version` with the current constant on
   every connect, without ever reading the old value. The one piece of
   information any future migration needs is destroyed before anything can look
   at it.
2. `schema_version()` is called by nothing but a test. It gates no behaviour.
3. The schema has **already** changed twice — `ADDED_COLUMNS` lists
   `runs.subject_loose` and `quirks.last_stated_at`, both post-0.1.0 — and
   `SCHEMA_VERSION` is still `1`. The number is already wrong.

What happens in 0.3 when a change is not additive? Nothing good.
`executescript` with `IF NOT EXISTS` will not touch an existing table, the
`ADDED_COLUMNS` trick only handles defaulted column adds, and there is no hook
for a rename, a backfill or a repair. And in the other direction there is **no
downgrade guard**: install 0.3, get a schema change, roll back to 0.2, and the
older code opens a newer database and silently misreads it.

Deferring this is asymmetric. Every day it ships, more installs exist whose
version marker is unreliable, and the first non-additive change becomes a
data-loss event rather than a migration.

`tests/test_store.py:199` is named `test_an_older_database_gains_the_new_columns`
and does not exercise the `ALTER TABLE` path at all — it builds a
current-schema database and reopens it. The name overstates the coverage.

#### G26 · Corrupt, locked or full disk: handled nowhere
`__init__.py:41-42` · **high** · half a day

`store.connect` is called with no `try`. A corrupt file, a permissions problem
or a full disk means a raw traceback, no `ConfigEntryError`, no repairs issue,
no guidance. At runtime no engine or store method catches `sqlite3.Error`.

The codebase already has the right instinct — `llm_tools.py:533-545` degrades
honestly when a timer cannot be set, and says so aloud. This is the same
treatment for a write failure.

#### G27 · Retention keeps 20 runs *total* for anything unnamed
`store.py:572-577` · **medium** · small

`prune_runs` groups on `row["subject_id"]`, so every `NULL` subject shares one
bucket. `strings.json` says "Finished runs kept **per thing**". Someone who
never names a subject keeps 20 finished runs in total.

Two smaller notes: pruning only happens on close, so abandoned-by-neglect runs
never prune and a lowered setting does not take effect until the next
completion. And the run's whole event log goes with it — **with no way to get it
out first** (G28). Sequencing matters.

#### G28 · No export, and the README promises one
**high** · hours

*"A run's history is a lab notebook, and it is already written."* The user
cannot read it. `run_events` is a complete append-only spine — advance,
reposition, note, ask, challenge, amend, quirk stated/learned/confirmed/
retracted, timer, finish — and there is no route out of the database.

PLAN §15 files this as an open question. It should not be open. Shipping
destructive retention (G27) with no export is the combination that turns a
nice-to-have into a trust problem. It is also the single best value-to-effort
item in this document, and it is squarely in lane: it is the artefact of holding
state, not a diversification.

#### G29 · A timer that failed is still logged as started
`engine.py:1254-1257` · **medium** · small

The event is recorded before the intent is attempted. On failure the tool
honestly says it cannot set a timer — and the append-only spine already says one
started. Cosmetic today; not once the spine is exportable.

#### G30 · No `async_remove_entry`
**medium** · trivial

Deleting the integration leaves `stepwise.db` in the config directory forever
(the `-wal` and `-shm` files are checkpointed away by `store.close()` on a clean
unload, and survive only an unclean shutdown), and reinstalling silently resurrects every old run, quirk and
cold-run prompt. `README.md:512` says the data is "deleted by deleting the
file", which a Home Assistant OS user cannot do without a file-editor add-on.

It should **rename, not delete** — never silently destroy a lab notebook.

### 3.7 Platform citizenship

#### G31 · The search response path can never be configured
`config_flow.py:132-140` · **high** · five minutes

A botched edit, found independently by all three reviews:

```python
vol.Optional(
    CONF_SEARCH_BASE_URL,
    CONF_SEARCH_RESPONSE_PATH,        # lands in voluptuous's `msg` slot
    description={"suggested_value": current.get(CONF_SEARCH_RESPONSE_PATH)},
): selector.TextSelector(),
vol.Optional(
    CONF_SEARCH_BASE_URL,             # same key again
    ...
): selector.TextSelector(),
```

`vol.Marker.__hash__` is `hash(self.schema)` and `__eq__` compares the schema,
so the two markers collide in the dict literal. Python keeps the **first** key
object with the **second** value, so the marker that survives is the mangled
one — carrying the stray `msg` and the response-path `suggested_value`, which
is why the base-URL box is prefilled from the wrong setting. Both values are
identical `TextSelector()`s, so the net effect is simply that
**`search_response_path` never appears in the form**, despite having
labels and a description in `strings.json`. `RestCommandSearch` always runs with
`response_path=""`, `dig()` returns the raw payload, and the setting the docs
describe cannot be set.

Nothing catches it. The keys are call expressions, so ruff is silent;
`config_flow.py` is never imported by the suite because neither `voluptuous`
nor `homeassistant` is installed in CI.

#### G32 · No bus events, no entities, nothing visible in Home Assistant
**high** · small for events

No `PLATFORMS`, no `async_forward_entry_setups`, no entity classes, nothing
fired on the bus. An integration with no surface is invisible: no dashboard, no
automation trigger, no way to build *"when the loaf reaches the prove, dim the
kitchen"*.

**The recorder objection, which decides the order.** An entity exposing step
text writes procedure content into `homeassistant_v2.db` indefinitely, which
quietly undoes the README's *"everything lives in one SQLite file… deleted by
deleting the file"* — precisely the leak PLAN §2 exists to prevent. So:

1. **Bus events first.** `hass.bus.async_fire` from `Engine._record`. No entity
   registry, no recorder bloat, and it makes dashboards and tablet cards
   somebody else's problem. Highest value per line in this document.
2. **Entity design decided, shipped later.** One *static* sensor —
   `sensor.stepwise_runs_in_progress`, compact attributes — not one per run:
   entity churn and orphaned registry rows when `prune_runs` deletes. Entity IDs
   are permanent once shipped; get the scheme right before committing.
3. **A `todo` entity per run: rule out, and say why.** `todo` semantics —
   arbitrary check-off, reorder, delete — directly contradict "only
   `run_advance` moves the pointer". A user ticking item 5 would have to be
   ignored or silently trigger a `run_goto`. The plan's discipline should win.

#### G33 · No diagnostics
**medium** · trivial

`store.stats()` already computes the right payload and is used for one debug
log line. `async_get_config_entry_diagnostics` is about forty lines of
almost-written code.

#### G34 · Step provenance is stored and never used
`models.py:154` · **medium** · hours

`Procedure.source` is written by `procedure_plan` and read by nothing.
`docs/procedures.md` states that *"where a step came from decides how loudly it
is defended when somebody disputes it"*. No code does that. Meanwhile the
default is `SEARCH_NONE`, so out of the box the steps for physical work come
from the model's own weights, and nothing says so.

Against iFixit's 125,000 guides this is the softest surface on the project, and
it is the one with the liability attached. It is also cheap honesty that
differentiates: nobody else tells you where the step came from.

#### G35 · No channel for a warning the source already gave
`llm_tools.py:39-53` · **high** · half a day

The step schema is `instruction / speakable / ingredients / duration_s / awaits
/ settings`. `awaits` is a *pacing* concept, not a hazard one. There is no
`caution` field, and `PROMPT` never mentions safety.

DISCLAIMER §2 says the software *"has no way of knowing whether an instruction
is safe … and it does not try to"*, and the code is consistent with that. But
the disclaimer's other clauses imply a warning **survives the pipeline**, and
today it cannot: if the source says *"isolate at the consumer unit before
touching anything"*, the model's only option is to bury it in `instruction`,
where `quantity_first` may rewrite it and `render` may convert numbers inside
it.

The disciplined fix is not a hazard taxonomy. It is an optional `caution`,
spoken *before* the instruction, never unit-converted, plus one prompt line:
*"If the source gives a caution for a step, put it in `caution`. Never invent
one and never drop one."* Stepwise still makes no safety judgement. It stops
losing the one the source made.

#### G36 · "Advance on any speech" instructs the model to advance on an alarm
`llm_tools.py:657-660` · **high** · ten minutes

With `CONFIRM_ANY_SPEECH`, the prompt says: *"Any reply that is not a question
may be taken as the step being done."*

*"It's gone a bit sticky"* is not a question. *"That's wrong for mine"* is not a
question. *"It's smoking"* is not a question. In a domain that includes mains
electricity and drained heating systems, that sentence is wrong.
`strings.json` is honest about the setting; the prompt is not.

#### G37 · `procedure_plan` demands nested JSON from small models
`llm_tools.py:39-53, 220` · **medium** · hours

`steps` requires a list of objects with a required `instruction` key. Eight
steps of nested JSON from a 4B model is both the slowest thing on the cold path
and the likeliest to come back malformed, costing a `vol.Invalid` retry round
trip. Accepting `vol.Any([str], [STEP_SCHEMA])` costs roughly a quarter of the
tokens and is nearly impossible to get wrong — and the engine already
synthesises `speakable`, `duration_s` and `awaits` from the instruction text.

#### G38 · The cold path is three model round trips, and none of it is measured
**high** · a day

Traced for *"talk me through descaling the kettle"* on an empty install:

| | | |
|---|---|---|
| 1 | Prompt build | milliseconds |
| 2 | Model → `resolve_intent` | tens of ms — **not** the bottleneck |
| 3 | Model **invents the whole procedure as nested JSON** | 300-600 output tokens. On Qwen 3 4B at ~20 tok/s: **15-30 seconds of silence** |
| 4 | Model → `run_start` | step one is finally spoken |

PLAN §15 asked how much resolution costs and the answer is: not much — the
generation does. Nothing in the codebase measures any of it; grep for
`perf_counter` across `custom_components` returns nothing.

There is also a genuine N+1 to kill: `Store.list_procedures` issues a
`get_steps` query **per procedure** — up to 50 — purely so `vocabulary_of` can
harvest ingredient names.

#### G39 · CI never imports the two Home Assistant-facing modules
**medium** · half a day

`tests/context.py` registers synthetic packages so the core imports without Home
Assistant. That split is genuinely well done and **should not be undone** — it
is why 139 tests run in 0.77 seconds with no install.

But `test_tools.py` inspects `llm_tools.py` with `ast.parse` rather than
importing it, and `config_flow.py` is only `ast`-parsed too. Both have zero
executed coverage, and G31 is the proof: a live, user-visible defect shipped in
a module nothing imports.

Two cheap closures, neither requiring the HA harness:

- **A schema/translations test.** Assert every key in `settings_schema` appears
  in `strings.json` and vice versa. Thirty lines, and it catches G31 and its
  whole class.
- **A signature test.** `StepwiseTool._run` does
  `getattr(self.engine, method)(**kwargs)`, so any mismatch between a tool's
  `vol` keys and an engine method's parameters is a `TypeError` on a live voice
  call. The engine *is* importable without HA. AST-parse the tool classes' keys
  and check them against `inspect.signature`. Forty lines, zero new
  dependencies, best ratio in the document.

#### G40 · The configured search provider is unreachable where the README shows it
`llm_tools.py:422-429` · **medium** · half a day

`self.search` is used by exactly one tool: `RunChallengeTool`. So the front
page's *"Fetch me a recipe"* → *"Nine steps"* is entirely the agent's own
knowledge, and a `rest_command` the user carefully configured is used only for
settling disputes. The prompt even says "you have no search provider" when it is
`none`, and says nothing when one exists.

#### G41 · English-only, and nowhere stated
**medium now, blocks adoption beyond English** · 1-2 weeks

Every spoken string is a Python literal: `speech.py` throughout, `util.say_
elapsed` and `say_duration`, sentences built directly in `engine.py`, the whole
`PROMPT`, `resolution.py`. The unit tables are English-language and
British-imperial (a 20 fl oz pint). `translations/` is `en` only.
`llm_context.language` is available and is used — but only to pass to the timer
intent.

Neither README nor PLAN says the integration is English-only. That is an
**unstated** limit, which is the worse kind: a German user installs it, Home
Assistant's fallback machinery translates the config UI, and the assistant then
speaks English at them mid-recipe.

The awkwardness is real and worth naming: the wording rules are load-bearing *by
design* — PLAN §12 puts them in the integration precisely so they do not live in
every user's prompt. Translating them means translating a behaviour, not a
string table.

#### G42 · Hands-free continuity is not Stepwise's to give
**low** · docs

If every "done" needs a wake word, the hands-free story is weaker than
SideChef's, and the tool layer cannot fix it: the conversation agent owns
`continue_conversation`. Be honest about the boundary and document Home
Assistant's setting rather than implying parity.

#### G43 · No content acquisition path
**medium** · docs now, adapter later

`procedure_plan` taking steps from the agent is the correct architecture
(PLAN §2: not a recipe database). But a user holding a recipe URL has no route
except reading it to the model, and Mealie and Cooklang users have a step list
in another integration that Stepwise cannot see. Document the pairing with
`powerllm` / `llm_intents` now; an adapter — **only** an adapter, never a
content store — later.

#### G44 · Housekeeping
`README.md:612` claims 120 tests; there are 139.

---

## 4. Where "the thing nobody else does" is weakest

Worth knowing before the first person says *"isn't this just…"*.

- **The claim holds in one tool.** G3. *"Where were we"* is impeccable.
  *"Done"* is not.
- **"Quirks supersede rather than accumulate" is false in the contradiction
  case.** G1 — and it is stated in both README and PLAN §10.
- **The pointer is durable; the content is not grounded.** G34. Against 125,000
  verified guides, *"the steps came from a language model and we never say so"*
  is the softest surface, and the one carrying the liability.
- **"A run's history is a lab notebook"** — and there is no way to read it.
  G28.
- **Resumption is a roadmap item for two trillion-dollar competitors.** Lead
  with correction and per-instance identity instead: those are architectural
  choices Amazon cannot cheaply retrofit onto an append-only memory.

## 5. What is unmatched, and should be pushed harder

1. **Voice-correctable, per-instance, superseded knowledge.** Once G1 and G2
   land, this is the strongest line available and it should lead the README's
   competitive framing, ahead of resumption.
2. **The append-only spine as a deliverable artefact.** Close G28 and Stepwise
   has what no consumer assistant has and every connected-worker platform
   charges per seat for. Bread is the wrong hero example for this; a repair log
   and a lab notebook are right.
3. **State that is server-side, not session-side.** Gemini's window is fifteen
   minutes; Alexa's is conversational. Say *"any room, after a reboot, on
   Tuesday"* explicitly — none of them can currently make that claim.
4. **The prompt injects live state.** `StepwiseAPI._prompt` puts open runs,
   their step, their elapsed time and their stickiness class into the system
   prompt every turn, so resumption partly survives an agent that calls no tool
   at all. Good engineering, undocumented and unclaimed.
5. **Composition with Home Assistant itself.** Tick both the Assist API and
   Stepwise on one agent and the assistant holding your durable pointer can also
   turn on the actual oven. Zero code, absent from the README.
6. **The no-shame rule as an addressable audience.** Every competitor nags,
   streaks or gamifies.

## 6. Where closing a gap would be wrong

Recorded so they are not revisited every release.

- **Auto-setting timers (Alexa+ parity).** The offer carries *why* the number is
  what it is, and that is what makes a wrong duration correctable *before* it
  matters. An imposed timer is correctable only after. Do not even add the
  option — its existence invites the wrong default.
- **Bundling or scraping content.** Enters a content war against 125,000 guides
  on day one with none, and ties the release cycle to scraping fragility.
- **A step-following UI.** Google built exactly this, measured it, and deleted
  it. Ship the state (G32) so people can build their own card; do not ship the
  card.
- **Becoming a memory integration.** Duplicates ha-ai-memory and Alexa's single
  strongest capability. Note that the one place Stepwise *does* write facts is
  the one place it has an Alexa-shaped defect (G2).
- **Photo diagnosis and part compatibility.** FixBot's value is grounding, not
  vision. A wrong part identification under an as-is disclaimer is a liability
  event.
- **Enterprise deviation workflow** — sign-offs, approvals, SOP versioning.
  Makes the household case worse (PLAN §4: *"this is not a form"*) and wins no
  factories. The cheap 80% is an exported record (G28), which is in lane.
- **Streaks, nudges, progress bars.** A stated position with a named audience.

## 7. Not gaps

Checked, and already handled. Listed so the same ground is not re-covered.

| Looks like | Actually |
|---|---|
| Naive datetimes, DST bugs | `util.py:15-56` is aware-UTC throughout, millisecond precision, deliberate and documented. `dt_util.now()` in the prompt is correctly local. No bug |
| SQLite unsafe across executor threads | One connection, `check_same_thread=False`, every statement through an `RLock`, multi-statement writes holding it. The *store* is sound — G8 is the engine layer |
| Store called from the event loop | Every call goes through `async_add_executor_job`. Verified, no exceptions |
| CI is just unittest and ruff | It also runs `hassfest` **and** the HACS validator, and `release.yml` gates the tag against the manifest version. Above average for 2026 |
| `archive_keep_per_subject` does nothing | It prunes, and the cascade is real (`PRAGMA foreign_keys=ON`). G27 is about *how* it buckets |
| Multi-user needs a schema retrofit | Already done. `runs.user_id` exists, round-trips, is written and filtered on. Only enforcement is missing — PLAN §15 should be corrected |
| Asides cost you your place | They genuinely do not. `pointer_unchanged: True`, pinned end to end at `test_journey.py:100` |
| Quirks can confirm themselves | `store.quirk_stated()` deliberately does not touch `last_confirmed_at`, with the reasoning in the docstring. Correct |
| `run_where` resetting the clock is a bug | Intentional — PLAN §6, *"any contact resets the clock"*, tested |
| No conversation-agent picker | A documented, correct deviation. HA attaches LLM APIs from the agent's own settings; a second picker could disagree with the real one |
| Legacy config-entry patterns | `entry.runtime_data` with a typed alias, `async_on_unload` for both registrations, modern `OptionsFlow`. Current-era throughout |
| Missing `quality_scale` in the manifest | Correct as things stand — it is core tooling, and an unverified key risks breaking a hassfest run on every push |

---

## 8. The 0.2 cut

**Theme: trust the pointer, and trust what it says.** No new capabilities.

Both architecture reviews called the first draft of this cut too large — forty
items against a theme of "no new capabilities", while containing two new
capabilities. It has been trimmed and, more importantly, **sequenced**: several
of these items are ordering hazards rather than independent tickets.

### The gate

**G25 is not an item in this release. It is the gate on it.**

The reason is G9. `quantity_first` output is *persisted*, so fixing the function
leaves *"180 of bake at"* on disk in every existing install. Repairing that is a
data migration — and the current `ADDED_COLUMNS` mechanism only knows how to add
a defaulted column. Anything in this release that touches schema or stored data
has to wait for a real migration ladder, or it entrenches the hack that G25
exists to replace.

### Order

| | Lands | Why here |
|---|---|---|
| 1 | **G36** prompt no longer says to advance on any non-question | Ten minutes, and it is the only place the shipped code instructs the model to advance on an alarm. No defensible reason for it to sit behind thirty tickets |
| 2 | **G31** config-flow key collision | Standalone, five minutes |
| 3 | **G25** migration ladder: read before write, numbered steps, downgrade refusal, `SCHEMA_VERSION` to 2 | The gate. Everything with DDL or a backfill comes after |
| 4 | **G9-G16** speech fixes, **plus the stored-data repair** | The repair identifies its own past output — where `legacy_quantity_first(instruction)` equals the stored `speakable`, it was generated and can be regenerated; where it does not, an author wrote it and it is left alone |
| 5 | **G8** coarse engine lock | Before anything else does read-modify-write on a run |
| 6 | **G3 + G4** stickiness guard, announce the number, `from_step`, `run_undo` | Together: both change what `run_advance` does to the pointer, and sequentially the second rewrites the first's tests |
| 7 | **G6 + G7 + G23** one `_may_touch` predicate in `current_run` | Centralised, so the keying policy can change later at one site rather than nine |
| 8 | **G22 + G24** prompt user filter, session TTL and keying | Before G32 — a bus event carrying another user's run reference is a privacy regression introduced by a feature meant to be additive |
| 9 | **G1 + G2** contradiction supersedes, in both stores, plus `forget` on the backend base | One defect, three call sites |
| 10 | **G17 + G18 + G19** exception boundary that restates position; speech on the silent paths; cap `run_ask`'s payload; cold-start first impression | The payload cap is its own change — a good line *and* nine steps in front of the model still gets the list read aloud |
| 11 | **G28** export | Before G27, and before G30: "rename, don't delete" only means something once the file can be read |
| 12 | **G27 + G5** prune buckets and reopenability | One ticket, per §3.2. The bucket fix must keep *more* than today, never less |
| 13 | **G26, G29, G30, G32, G33, G38, G39, G20, G21, G44** | Independent. G32 is bus events only |

### Out, with reasons rather than silence

| | Why |
|---|---|
| **G34** provenance said aloud | A positioning feature, not a bug, and it needs a decision about what "defended more loudly" actually does. 0.3 |
| **G35** `caution` field | Adds a column, so it must land after G25 — and after G9-G11, or the caution is mangled on the way out by the bugs being fixed in the same release. The safety argument is strong; the sequencing is not. 0.3, early |
| **G37** plain-string steps, and `procedure_plan(start_now=)` | Justified entirely by latency, which G38 says is unmeasured. Sequence after the instrumentation. Note `start_now` is the half that *removes* a round trip and is the better of the two |
| **G32.2** the entity itself | Entity ids are the only irreversible thing in reach. Designed in 0.2, shipped in 0.3 |
| **G40** search on the planning path | Adds seconds to the path G38 already says is too slow |
| **G41** i18n | 1-2 weeks, and a behaviour rather than a string table. **State the limit in 0.2** — it is the largest ceiling on adoption, larger than any feature here |
| **G43** import adapters | Docs in 0.2. Adapter in 0.3, and only ever an adapter |
| Photo identification, shared library | See §6, and PLAN §15 |

### One policy that must be written down, not just coded

`open_runs` treats `user_id IS NULL` as visible to everyone, and every
voice-satellite run without a user context lands there. G23's guard cannot be
written without deciding what that means: **NULL is the household, a set
`user_id` is private.** If the guard rejects NULL-owned runs it breaks the
primary use case; if it silently permits them it is not a guard. Writing the
policy down now is what makes a `device_id` layer possible in 0.3 — without it,
0.2 ships a guard whose semantics nobody can reconstruct.

### One deliberate breach of a stated principle

PLAN §8.1 says the tools are *"deliberately few"*, and 0.2 adds a sixteenth:
`run_undo`.

It is justified by the project's own words. PLAN §8.1 also says the most
damaging failure is silently being on a different step, and undo is the direct
answer to it — the append-only spine already holds everything required, so the
tool is a read of data that exists rather than a new concept. A sixteenth tool
that repairs the worst failure is a better trade than fifteen that cannot.

It is also the *only* new tool surface in this release. Voice pause was cut to
its read-path half for exactly this reason: one breach, not two.

### What actually shipped in 0.2

Recorded honestly, because a plan that is never checked against the release is
just a wish.

**Closed:** G1, G2, G3, G4, G5 (both halves — the flag *and* the read path),
G6, G7, G8, G9 including the migration that repairs stored text, G10, G11, G12,
G13, G14, G15, G16, G17, G18 including the payload cap, G19, G20 (the options
page), G21 (and a latent aiohttp bug in the bundled provider found while
fixing it), G22, G23, G24, G25, G26, G27, G28, G29, G30, G31 with the test that
catches it, G32 (events), G33, G36, G38 (the instrumentation), G39 (both cheap
tests), G41 (stated, not fixed), G44.

**Caught by reviewing this release before tagging it**, and worth recording
because the first draft of this very list claimed three of them were done when
they were not:

- **Both new offers were dead ends.** A cold run offered rather than assumed,
  and a stopped run offered back, each came round again as the same question for
  ever: nothing touched the run, so nothing changed, and the only way out was
  the agent quoting an id — the one thing section 8.1 forbids. The cold case was
  a *regression*: before 0.2 it advanced silently, which was wrong, but it moved.
  An offer is now contact, and a "yes" lands on the run it was about.
- **`run_reopen` worked and was reachable from nothing.** No tool, no service,
  no caller but its own test — so "Pick it up?" could not be answered. Reopening
  now happens through the tools that already exist rather than a seventeenth one.
- **G13, G14 and G16 were listed as done and were not.** The helper for G16 was
  written and never applied at the call site that had the bug, so the same
  conversation gave two different counts depending on which tool answered. G13
  and G14 had not been touched at all. All three are done now.
- The failure handler read the database from the event loop.
- `run_reopen` mutated a run outside the engine lock — the exact bug class the
  lock was added for.

**The lesson worth keeping:** a list of what shipped, written from the list of
what was planned, is a work of fiction. Check the release against the code, not
against the plan.

**Found while doing it, and fixed:**

- Runs were ordered by timestamp alone, so two touched in the same millisecond
  sorted arbitrarily. Switching to a run by name worked most of the time and
  silently did not the rest of it. They now carry a counter that only goes up.
- `BundledSearch` passed a bare integer where aiohttp wants a `ClientTimeout`,
  and the resulting error was swallowed by a catch-all that reported it as "the
  provider is not reachable". The provider may never have worked.
- "Talk me through" — the phrase the front page teaches — was being queried as
  a mishearing of "dough" on any installation with a loaf on file.

**Deferred, as planned:** G34, G35, G37, G40, G43, the entity itself, and i18n.

**Still open and now sharper:** whether the `speakable` column needs a
provenance flag of its own. The 0.2 repair identifies its own past output by
comparison, which works exactly once — a second change to `quantity_first`
would have nothing to compare against. A flag saying "this was generated"
should go in before that is needed, not after.

---

*Sources for §2 are recorded in the release notes for 0.2.*
