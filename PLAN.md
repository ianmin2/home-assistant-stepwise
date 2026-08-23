
# Stepwise

**Guided step by step procedures for Home Assistant.**
For anything with a make, a model, or a knack to it: appliances, fixtures,
vehicles, tools.
A working name. Alternatives at the end.

Status: phases 1 to 5 are built and tested in this repository, and phase 6 is
prepared as far as it can be without a GitHub account — see docs/releasing.md.
This document stays the design; where the code deliberately differs, the
differences are listed in README.md.

---

## 1. What it is

A Home Assistant custom integration that lets a voice assistant walk somebody
through a multi step physical procedure, hands free, across days, with the
ability to be interrupted, corrected and resumed.

The canonical example:

> "I'd like to make a rosemary tangzhong loaf on my Panasonic bread machine.
> Fetch me a recipe and mail me a shopping list."
>
> *(next day)* "Guide me step by step."
> "First, two hundred grams of wholemeal flour."
> "My machine takes yeast first and salt at the top."
> *(checks the model, agrees or corrects, reorders the remaining steps,
> remembers the quirk)*
> "Tell me when the ingredients are in."
> "Done."
> "Programme four, medium crust. Shall I set a timer for three hours ten?"

Nothing about that is specific to bread, or to cooking. The same machinery
covers converting a radiator from a manual handle to a thermostatic valve,
replacing a worn bicycle chain, bleeding a heating system, descaling a
dishwasher, changing a car's air filter, repotting a plant, or a physio routine.

It also covers building something that does not exist yet: wiring an ESP32
project, assembling flat-pack, soldering a kit, setting up a NAS.

And it covers work that is not assembly at all. A researcher running a reaction,
logging observations against elapsed time, noting what changed at step four and
picking it up after lunch, is doing exactly the same thing as somebody making
bread. Note taking, result tracking and protocol following are the same shape.

Cooking is simply the easiest example to write down. If anything in the design
only makes sense in a kitchen, that is a bug.

### The actual product is pause and resume

Everything else serves this. A checklist app can list steps. What nobody has,
hands free, is the ability to stop in the middle because the doorbell went, or
because it is Tuesday now, and pick up exactly where you were without re-reading
anything.

That is why run state is a first class object rather than conversation history,
why `procedure_where()` takes no arguments, and why a step can wait indefinitely
on "tell me when that's in". Anything that makes resuming harder than saying
"where were we" is wrong, however good it looks in a single sitting.

### Built for interrupted attention

Losing your place is the normal case, not the failure case. People get
interrupted, put things down, come back on Tuesday, and forget which of three
half-finished things they are looking at. Plenty of people work that way all the
time, and everyone works that way sometimes: with a phone ringing, a child in
the room, or oily hands and no free finger to scroll with.

Designing for that is not an accessibility footnote bolted on at the end. It
decides the architecture, and it is why several things in this document that
look like polish are actually load bearing:

- **Resuming costs one utterance.** "Where were we." Never re-read anything,
  never scroll, never find your place in a list. If getting back in is harder
  than that, the tool has failed at the only job that matters.
- **A gap is never treated as failure.** No "you abandoned this", no nagging, no
  streaks, no progress bar implying you are behind. A run left for three days is
  simply a run left for three days, and it is picked up in the same tone it was
  put down.
- **The system holds the state, not the person.** Never "you said you'd already
  done the salt, right?" It knows, because it wrote it down with a timestamp
  when it happened.
- **One step at a time** is cognitive load management before it is voice
  ergonomics. The whole list is available on request and never volunteered.
- **The reference is restated** because the thing most often lost is not the
  step, it is which thing you were doing.
- **Asides do not cost you your place.** Asking a question mid-procedure must be
  free. Anything that punishes curiosity by losing the pointer is broken.
- **No shame in the wording, ever.** Not in prompts, not in the UI, not in
  notifications. "You still have a loaf half done" is a fact. "You never
  finished your loaf" is a judgement, and it is the reason people stop opening
  apps.

A checklist assumes an uninterrupted person. That assumption is what makes
checklists useless for exactly the work that most needs them.

### The stopwatch principle

A stopwatch has no opinion about what you are timing. It is uninterested in
whether you are boiling an egg or running a lab. It is unyielding about exactly
one thing: time.

Stepwise is the same. **Unopinionated about content, picky about context
stickiness.** It does not model recipes, or bikes, or reactions. It models a
thing you are part way through, when you last touched it, and how to get you
back to the right place in it. Everything domain specific comes from the model
or the web at the moment it is needed, and is not baked in.

That constraint is what makes it worth putting on HACS. A recipe integration
serves cooks. This serves anyone with something half finished.

## 2. What it is not

**It is not a memory integration.** Long lived facts (what you own,
what you prefer, who is allergic to what) belong in a memory layer, and a good
one already exists. Stepwise depends on it rather than reimplementing it.

The distinction matters, and getting it wrong is the main failure mode of this
class of project:

| | Facts | Run state |
|---|---|---|
| example | "the bread machine is a Panasonic SD-YR2550" | "step 3 of 9, awaiting confirmation" |
| lifetime | until it changes | hours to days, then archived |
| shape | a sentence | a structured row |
| retrieval | semantic, top k | direct, by id |
| volume | hundreds, forever | one active, few recent |

Dumping run state into a memory store is what produces the unbounded,
low signal memory file that these projects tend to accumulate. Keep them apart
and the fact store stays small enough to stay useful.

**It is also not a recipe database.** It does not ship content. It turns
content, from the web or from the user, into a procedure it can drive.

## 3. What it reuses

| Concern | Reuse | Why |
|---|---|---|
| Long term facts | [ha-ai-memory](https://github.com/Riscue/ha-ai-memory) | Maintained, semantic, already exposes native LLM tools to every Assist agent. Stepwise reads subject facts from it and writes learned quirks back. |
| Conversation agent | Whatever the user has | Never replaces the conversation platform. Integrations that do are unusable alongside an existing setup. |
| Timers | HA native voice timers | Built in since 2024.7, handled by intents, no model in the loop. Do not reinvent. |
| TTS/STT | HA Assist pipeline | Not our concern. |
| Web search | Pluggable, see section 8 | |

Positioning it as a companion to ha-ai-memory rather than a competitor is both
honest and better for adoption. Ideally, agree the integration point with that
project upstream.

## 4. Resolution, before there is a run

The first exchange is not a procedure. It is working out what the person
actually means, and it needs its own short-lived state.

```
"I want to make tangzhong bread"
  |
  ├─ Search what already exists here first. Their own past procedures, their
  |  own notes, before anything external. People repeat themselves, and the
  |  version they made last time beats a fresh search.
  |
  ├─ Disambiguate, out loud, including mishearings.
  |    "Tangzhong, the water roux method? Speech-to-text sometimes gives me
  |     that as yang zoong."
  |  Confirm or deny, then continue. Never guess silently at a term that
  |  sounded odd.
  |
  ├─ Gather what actually changes the steps, and nothing else.
  |    wholemeal or white, loaf size, which machine, any allergies
  |  Ask only what alters the outcome. This is not a form.
  |
  └─ Resolved -> create the reference, then build the steps.
```

**Speech-to-text disambiguation is a first class concern, not an edge case.**
Domain vocabulary is exactly what Whisper mangles: tangzhong, tare weight,
derailleur, ferrule, Maillard, ESP32-C6. When a term does not match anything
known, the agent offers its best phonetic candidates and asks, rather than
inventing a procedure for a word that was never said.

The resolution session is temporary. It holds the half-formed intent, the
questions asked and the answers given, and it either becomes a run or expires.
It is not stored as a fact and it is not stored as a run.

## 5. The reference

Once resolved, the thing gets a name, and the name gets used.

- The agent proposes one and the user may override it. "Rosemary tangzhong
  loaf", or "the landing radiator", or "batch seven".
- It is **restated casually** at natural moments, not announced: "On the
  rosemary loaf, next is two hundred grams of wholemeal." Not "Resuming run
  4a2f."
- On resume after a gap it leads with the reference, because that is the thing
  the person has lost, not the step number.

This is cheap and it is the main defence against temporal drift, where somebody
returns to a half-finished thing and cannot tell which half-finished thing it
is. Two loaves and a radiator in flight is normal.

## 6. Context stickiness

The configurable heart of the thing, and the reason it is a stopwatch rather
than a checklist.

**Everything is timestamped.** Every step advanced, note taken, question asked,
correction made. The model is given the current time on every turn, so elapsed
time is always answerable: "you started the tangzhong forty minutes ago".

**A run is hot, warm or cold**, purely by elapsed time since last contact:

| state | default | behaviour |
|---|---|---|
| hot | under 30 min | assumed. "Next" means this run, no preamble. |
| warm | 30 min to 4 h | named on first contact. "On the rosemary loaf, next is..." |
| cold | over 4 h | offered, never assumed. "You've a rosemary loaf half done from this morning. Carry on, or something new?" |

Both thresholds are configuration, not code. A researcher tracking a
twelve-hour reaction and somebody making a loaf want very different numbers, and
neither should be told they are wrong.

**Rolling, not fixed.** Any contact resets the clock. A run touched every twenty
minutes for nine hours stays hot throughout.

**Multiple runs may be live.** Hotness is per run. The reference is how they are
told apart.

## 7. Core model

Three objects. Everything else is detail.

### Subject

The thing being worked on. Deliberately not called an appliance: it is equally a
radiator, a bicycle, a car, a boiler, a houseplant or a person's knee.

```
subject
  id            panasonic_sd_yr2550        # or bike_winter_hack, rad_landing
  kind          bread_machine | radiator | bicycle | oven | ...
  make, model   Panasonic, SD-YR2550       # may be unknown, that is fine
  label         "the winter bike"          # what the user calls this ONE
  aliases       ["the bread machine", "the panasonic"]
  attributes    { programmes: [...], has_dispenser: true }
                { drivetrain: derailleur, speeds: 11 }
                { valve: TRV, pipe_mm: 15 }
                { board: esp32-c6, bom: [...], arrived: [...] }
  status        active | retired | replaced_by:<id>
  created_at, last_seen_at
```

`kind` gives a generic fallback, so an unknown air fryer still works from
generic air fryer knowledge, and an unknown radiator from generic radiator
knowledge, while a known model gets its specifics.

**Make and model are asked for, not assumed.** When a procedure's instructions
would differ by model, the agent asks. When they would not, it does not waste
the user's time.

**A subject need not exist yet.** For a build, `kind` is `project` and the
attributes describe the target rather than a product: the board, the pinout, the
bill of materials, which bits have already arrived. The same run machinery
applies, and the same identity rules: "the sensor project" is one subject, and
next year's is another.

### Identity, and the fact it drifts

This is the part most systems get wrong, and it is why "learn it once" is not
good enough.

"My bike" is not one bike. It is a different bike in five years, and possibly a
different bike this afternoon. A quirk learned about a derailleur bike, silently
applied years later to a singlespeed, is worse than having learned nothing: it
is confidently wrong, mid-instruction, while the user has oily hands.

So:

- **Subjects are instances, not categories.** Two bicycles are two subjects.
  `label` is what distinguishes them out loud.
- **Ambiguous reference is resolved, not guessed.** If "my bike" matches two
  active subjects, ask which. One matching subject and it proceeds.
- **Contradiction is a fork, not an update.** If the user describes something
  inconsistent with the stored subject ("there's no derailleur on this one"),
  the correct response is "different bike, or has this one changed?" and not
  overwriting the record. One creates a new subject; the other amends it.
- **Subjects retire.** Replaced, sold, scrapped. Retired subjects stop matching
  but stay readable, because their procedure history is still worth having.

### Procedure

A template. Ordered steps, subject-agnostic where possible.

```
procedure
  id, title, kind, yields, prep_notes
  steps [ { n, instruction, ingredients[], duration_s,
             awaits: none|confirm|timer, settings{} } ]
  source        web | user | generated
  subject_kind  bread_machine
```

Created by the LLM from a researched recipe, or by the user dictating, or
recalled from a previous run. Reusable and shareable.

### Run

One execution. The state machine.

```
run
  id, procedure_id, subject_id
  status        active | paused | done | abandoned
  current_step
  started_at, updated_at
  amendments [ { step_n, was, now, why, at } ]
  notes      [ { text, at } ]
```

**The run is the thing that makes "guide me step by step" work in a cold voice
session with no conversation history.** One lookup returns exactly where you
are.

## 8. How a procedure is addressed

Not everything the user says is "next". Three kinds of utterance, and only one
of them moves the run forward. Treating them all as advancement is the fastest
way to make this useless.

**Advance.** "Done." "That's in." "Next."
Moves the pointer. Timestamped.

**Position.** "I'm at the bit where the fruit goes in." "Skip to the second
prove." "Go back, I've not done the salt yet."
Moves the pointer somewhere else, by description rather than by number. The
model matches the description against the step list and **says which step it
landed on** so a wrong jump is caught immediately: "Right, step six, folding in
the fruit." Never silently reposition.

**Aside.** "How many calories is that?" "Is it OK to use dried rosemary?" "How
long has the tangzhong been resting?" "What was the flour weight again?"
Answered without moving anything. The pointer does not change, the step is not
completed, and the answer comes from the procedure, the notes, the elapsed
clock, or the wider world. Then it stops, so the person is still where they were.

Asides are the most common utterance in practice and the easiest to get wrong.
Anything that advances a run because somebody asked a question is broken.

**Also: observations.** "It's gone a bit sticky." "Reaction went cloudy at
forty minutes." Recorded against the current step with a timestamp, no movement.
This is what makes it usable for lab notes as much as baking.

## 8.1 Tools exposed to the agent

Deliberately few. Each does one thing and returns speakable text.

| Tool | Purpose |
|---|---|
| `resolve_intent(words)` | The requirements conversation. Searches what already exists, offers phonetic candidates for odd terms, asks only what changes the steps. Returns a resolved target or a question. |
| `subject_resolve(words)` | Turn "my bike" into one subject, or ask which. |
| `procedure_plan(target, subject)` | Compose or fetch the steps, store, name it. Does not start it. |
| `run_start(procedure, reference?)` | Begin. Returns step 1 and confirms the reference. |
| `run_where()` | Where am I, in which thing, and how long since. No arguments, by design. |
| `run_advance(note?)` | Complete current step, return next. |
| `run_goto(description)` | Reposition by description. Always reports where it landed. |
| `run_ask(question)` | Aside. Answers from procedure, notes, clock or world. Moves nothing. |
| `run_note(text)` | Record an observation against the current step and time. |
| `run_challenge(claim)` | The user disputes a step. See below. |
| `run_amend(step, change, why)` | Change a step in this run, optionally the procedure. |
| `run_finish(outcome?)` | Close, archive, optionally record how it went. |

Three design rules, learned from the assistant already running here:

- **`run_where()` takes no arguments.** Anything requiring the agent to
  remember an id defeats the point.
- **Every tool returns one speakable string plus structured fields.** The agent
  reads the string; it uses the fields only when asked for detail.
- **Positioning always reports where it landed.** The single most damaging
  failure is silently being on a different step from the person.

## 9. The correction flow

The most interesting part, and the reason this is not just a checklist.

> "My machine requires yeast first and salt at the top, which is the opposite of
> most machines."

```
procedure_challenge("yeast first, salt at top")
  |
  ├─ Which subject is this?         ambiguous -> ask which one
  ├─ Do we know its make/model?     no, and it matters -> ask, store it
  |
  ├─ Does a stored quirk cover it?
  |     agrees    -> "You're right, and I have that noted. Reordering."
  |     conflicts -> "My note says the opposite for the SD-YR2550. Shall I
  |                   re-check?"  (never silently overrule the person present)
  |
  ├─ Unknown -> search provider, scoped to make and model
  |     confirms  -> amend run, write quirk (source: web, confidence: high)
  |     refutes   -> say so, cite plainly, offer to proceed either way
  |     unclear   -> defer to the user, write quirk (source: user)
  |
  └─ Amend the remaining steps, not just the current one.
```

### Quirks are stated, never silently obeyed

A quirk is a claim about one subject. It is stored like this:

```
quirk
  subject_id      bike_winter_hack          # the instance, never the kind
  claim           "11 speed derailleur, needs a quick link not a pin"
  learned_from    user | web | manual | observed
  confidence      high | medium | low
  learned_at, last_confirmed_at, times_applied
  material        true                      # does acting on it change instructions?
```

Rules, replacing the earlier "ask once, ever", which was too rigid:

**1. Say it, do not assume it.** A quirk that changes an instruction is spoken
as an assertion the user can reject in flight, not applied invisibly.

> "Yeast first on yours, then the flour."
> not: *(silently reorders)*

Cheap to say, expensive to be wrong. The user corrects it in two words if it is
out of date, and never notices if it is right.

**2. Re-confirm when the ground may have moved.** Ask again, briefly, when any
of these hold:

- the subject was matched loosely ("my bike" with more than one on file)
- the quirk is material and has not been confirmed in a long time
- the quirk came from the web or from inference rather than from the user
- the user has said anything this session inconsistent with it

Otherwise state it and carry on. The failure to avoid is interrogating somebody
about a bread machine they have owned for six years.

**3. A contradiction is information, not an error.** "There's no derailleur on
this one" does not mean the stored quirk was wrong. It usually means this is a
different subject. Fork first, correct second.

**4. Quirks are scoped to a subject, never to a kind.** Nothing learned about
one bicycle is applied to another bicycle. Generic knowledge about bicycles
comes from the model or the web, and is labelled as such.

**5. Quirks are visible and editable.** They appear in the options panel with
their source and age. A wrong one that cannot be seen is permanent.

### And the rest of the correction flow

- **The person in the room outranks the internet about their own subject**, but
  is told when they are contradicted. Never a silent override in either
  direction.
- **Amendments are scoped.** Reordering a load order changes this run and this
  subject's quirks, not the underlying procedure that other people might use.

## 10. Storage

SQLite, one file, in the HA config directory.

```
subjects, procedures, procedure_steps, runs, run_events, run_amendments, quirks
```

`run_events` is the append-only spine: every advance, reposition, note,
question and correction, each with a timestamp. It gives elapsed-time answers,
hot/warm/cold classification, and a readable history of what actually happened,
which is the artefact a researcher wants at the end. Everything else is
derivable from it.

Rationale: run state is transactional and mutable, which is the wrong shape for
a vector store or a graph. Volume is tiny. A single file is inspectable,
diffable and trivially backed up with the rest of HA.

Semantic search over facts stays in ha-ai-memory. Stepwise stores no embeddings.

**Bounded by construction**, which is a stated requirement:

- Quirks **supersede** on the same subject rather than appending.
- Runs archive on completion; keep the last N per subject, drop the rest.
- Procedures are deduplicated by title and subject kind.
- **Nothing is written implicitly.** No automatic extraction of everything said.
  Facts enter through an explicit tool call. This is the single biggest cause of
  memory rot in comparable projects.

## 11. Configuration

A standard HA config flow, since HACS users expect one.

**Setup**

- **Conversation agents**: multi select. Which agents get the tools. In our case
  `Deep` gets them and `Voice` does not, because Voice tunnels. Sensible default:
  all conversation entities.
- **Memory backend**: `ha-ai-memory` (recommended, auto detected) or `built in`
  (a facts table in the same SQLite, for users who do not want a second
  integration).
- **Search provider**: see below.
- **Units**: metric or imperial, for reading quantities aloud.
- **Confirmation style**: wait for "done" versus advance on any speech.
- **Context stickiness**: the hot and cold thresholds, defaulting to 30 minutes
  and 4 hours. The single most important setting, and the one that makes the
  same integration serve a loaf and a twelve-hour reaction.
- **Reference naming**: agent proposes, always ask, or never ask.

**Options flow**

- Manage subjects: add, edit, label, retire, view and edit learned quirks. Quirks
  being user visible and editable matters, because a wrong one is otherwise
  invisible and permanent.
- Archive retention.
- Reset a stuck run.

### Search provider: pluggable, not bundled

Three adapters behind one interface:

1. **HA `rest_command`** (default). The user names an existing rest_command and
   the response path. Works with anything, including our research service, and
   ships nothing.
2. **Bundled provider** (optional add-on). SearXNG plus rerank plus fetch, the
   pipeline we already run. Offered as a separate HACS add-on, never a
   dependency.
3. **None.** The agent's own knowledge only. Degrades honestly rather than
   failing.

Bundling a scraper into the integration would be the sustainability mistake: it
ties the release cycle of an HA integration to the fragility of web scraping.
Interface plus optional add-on keeps them independent.

## 12. Voice design notes

Hard won from the existing assistant, and worth writing into the integration
rather than leaving to each user's prompt:

- **One step at a time.** Never read the whole procedure unless asked.
- **Say the quantity before the ingredient.** "Two hundred grams of wholemeal
  flour", not "wholemeal flour, two hundred grams". The ear needs the number
  first when hands are busy.
- **Never enumerate a set as a summary.** If the user asks what is left, list the
  remaining steps. "A few more" is not an answer.
- **Await explicitly.** "Tell me when that's in" and then stop talking. Do not
  advance on silence.
- **Timers are offered, never imposed**, and always with the rationale: "three
  hours ten, because that's the programme length".
- **State a quirk before relying on it**, so it can be corrected while the
  user's hands are busy rather than after the mistake.
- Steps ship with a `speakable` variant distinct from the written one.

## 13. Repository layout

```
custom_components/stepwise/
  __init__.py  config_flow.py  const.py
  store.py            SQLite access
  models.py           Subject, Procedure, Run
  llm_tools.py        the eight tools
  search/             base.py, rest_command.py, bundled.py, none.py
  memory/             base.py, ha_ai_memory.py, builtin.py
  strings.json  translations/
tests/
docs/
  subjects.md         adding a new subject kind
  procedures.md       procedure schema
hacs.json  README.md
```

## 14. Phases

**Test context throughout: a bread recipe.** Concrete, has real steps, real
timings, a real appliance with real quirks, natural pauses, and obvious asides
("how many calories"). If it works end to end for a tangzhong loaf it works for
a radiator. Do not build a second example until the first is genuinely good.

1. **Skeleton** *(built)*: config flow, SQLite store, subject CRUD and
   resolution. No LLM.
2. **Runs** *(built)*: plan, start, where, advance, finish, plus `run_events`
   and the hot/warm/cold clock. Demonstrable on the loaf.
2b. **Addressing** *(built)*: goto, ask, note. This is what separates it from a
   checklist and it should come before the clever stuff.
3. **Corrections** *(built)*: challenge, amend, quirks. The differentiating
   feature.
4. **Settings and timers** *(built)*: subject-aware recommendations, native
   timers.
5. **Providers** *(built)*: memory and search adapters, ha-ai-memory
   integration — provisional pending the upstream conversation below.
6. **HACS** *(prepared)*: docs, tests, brands submission, release. Docs, tests,
   continuous integration, changelog, icons and the release workflow are done.
   Pushing the repository, opening the brands pull request and tagging the
   release need a GitHub account rather than more code: docs/releasing.md is
   the running order.

Phases 1 to 3 are the product. 4 to 6 make it shippable.

## 15. Open questions

- **Name.** Stepwise, Mise, Sous, Handrail, Alongside. Stepwise is clearest;
  Mise (from mise en place) is nicer but reads as cooking-only, and this is not
  cooking-only.
- **Multi user.** Two people running procedures at once needs runs keyed by user.
  Cheap now, expensive to retrofit. Recommend building it in from the start even
  if the UI ignores it.
- **How much does resolution cost in latency?** Searching the local library,
  offering phonetic candidates and asking a clarifying question all happen before
  the person has been told anything useful. Worth measuring early: if resolution
  takes eight seconds, people will stop using it however good the rest is.
- **Should `run_events` be exportable?** A timestamped log of a procedure is
  exactly what a lab notebook is. Markdown or CSV export is close to free and may
  be the feature that wins the research audience.
- **Should procedures be shareable?** A community library of subject profiles
  and generic-by-model knowledge would be genuinely valuable, and a much better
  artefact than a recipe database. Instance quirks are private and never
  shareable. Out of scope for v1, but do not design it out.
- **Upstream contact.** Talk to ha-ai-memory before building the adapter, so the
  integration point is agreed rather than assumed.
