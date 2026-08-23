# Changelog

All notable changes to Stepwise are recorded here. Versions follow
[semantic versioning](https://semver.org/).

## [0.2.1] — 2026-08-23

> 0.2.0 was tagged locally, swept twice before being pushed, and superseded by
> the sweep's fixes — including one that would have bricked upgraded databases.
> It was never published, so nothing ships under that number: this release is
> everything 0.2.0 was meant to be, plus the twenty-two defects the two sweeps
> found in it.

**Trust the pointer, and trust what it says.** No new capabilities. The gaps
this closes, and the ones deliberately left open, are set out in
[PLAN_GAPS.md](PLAN_GAPS.md).

### Claims that were made and not kept

- **Quirks now supersede a contradiction, not only a repeat.** Supersession
  needed the same words, so "the yeast goes in first" and "the yeast goes in
  last" both stayed active, both bore on the same step, and both would have
  been read out in the same breath. The same fix in the facts table, which had
  the same defect.
- **A fact can be forgotten.** `forget_fact` had no callers anywhere — not a
  tool, not a service, not a screen. Facts now appear on a subject's page and
  can be ticked away, and forget is part of what a memory backend must provide.
- **A cold run is offered rather than assumed, whichever tool is asked.** Only
  `run_where` honoured that. Saying "done" two days later moved the pointer on
  whichever run happened to be touched last, silently.

### The pointer

- **Every advance says which step it landed on.** It was the only pointer move
  that announced nothing, and the one that happens fifty times a run — so a
  remark heard as "done" was a silent skip.
- **`run_advance` takes `from_step`**, the step the agent believes it read out.
  When it disagrees, nothing moves and the person is told where they are.
  Optional on purpose: requiring it would stall the commonest utterance in the
  product every time it went missing.
- **`run_undo`**, a sixteenth tool. It reverses the pointer and nothing else,
  and writes a new event rather than deleting the old one, because a spine that
  can be rewritten is not a record.
- **A run can be put down and picked back up.** `paused` had been declared since
  the first release and set by nothing, so a misheard "stop a sec" closed a run
  for good. `run_finish` now takes one decision — done, paused or stopped — and
  a run stopped in the last few hours is still found by name and offered back,
  which needs no decision from the model at all.
- **An offer can be answered yes.** A cold run offered rather than assumed, and
  a stopped one offered back, are both now picked up by whatever the person says
  next. Neither needs the agent to quote an id back, which section 8.1 says must
  never be required — and without that, both offers came round again as the same
  question indefinitely.
- **A finished run can no longer be advanced by id**, and an id that is
  invented, closed or somebody else's falls back to the obvious run rather than
  answering "nothing on the go" about a job plainly half done.
- **One engine call at a time.** The store locked every statement, but an engine
  call is a sequence of them — two advances at once both read step three, both
  wrote step four, and a step was silently skipped.
- **Runs carry a counter that only goes up.** Two touched in the same
  millisecond sorted arbitrarily, so switching to a run by name worked most of
  the time and silently did not the rest of it.

### What it says out loud

- **A trailing number is no longer always a quantity.** "Bake at 180" was spoken
  *and stored* as "180 of bake at"; "Programme 4" as "4 of Programme". Existing
  databases are repaired on upgrade — only where the text is exactly what the
  old code would have produced, so anything written by hand is left alone.
- **"C", "in" and "m" are not always units.** "Preheat to 180 C" came out as
  "180 cups of preheat to", and "Put 2 in the tin" as "Put 5.1 centimetres the
  tin". Temperatures are said as degrees.
- **Small masses are no longer converted into uselessness.** Seven grams of salt
  was offered as "0.2 ounces", which no scale reads and which rounding put 20%
  out.
- "an hour 1" is now "an hour and a minute", and "1 and a half minutes" is "a
  minute and a half".
- **A note says which step it is against** — "Noted, against step three" rather
  than "Noted." fifty times over, which is also a second free check that the
  pointer is where the person thinks it is.
- **A proposed name survives being said aloud.** "Descale the kettle" was
  becoming "Shall I call it *the descale the kettle*?" — and that is the phrase
  the front page teaches. A title that opens with a verb is now named after the
  thing it acts on.
- Acronyms and model numbers keep their case — "ESP32" was becoming "eSP32".
  "Two things on the go" counts, in both places that say it. "1 step", not
  "1 steps".

### Never silent, never a traceback

- **A tool that raises no longer takes the turn with it.** It says something has
  gone wrong *and where the person is*, because restating the place while
  failing is the product working.
- **A cold start says something.** It returned an empty line and a question
  built from the whole utterance — "I don't have anything on file for talk me
  through descaling the kettle. What is it?" — twice in the same payload.
- **An unanswerable aside says where you are**, and the remaining steps come
  back only when the remaining steps are what was asked for. Handed them
  unasked, a model with no line of its own read the list out.
- **"Talk me through" is no longer queried as a mishearing of "dough"** on any
  installation with a loaf on file. It is the phrase the front page teaches.
- A corrupt database, a locked one or a full disk now says what to do about it.

### Two people, one kitchen

- **The prompt no longer lists another person's runs** while the tools deny they
  exist. Whose run is whose is one predicate: no owner means the household, an
  owner means that person, a caller with no user context speaks for the house.
- **A half-formed intent lives four minutes, not thirty**, and a sentence that
  neither is short nor shares anything with what is held starts a new thought.
  Two people at one speaker were having their sentences glued together.

### Kept, and readable

- **`stepwise.export_run`** returns a run as markdown, CSV and rows. The README
  called the event log a lab notebook; there was no way to read it.
  `stepwise.list_runs` and `stepwise.finish_run` too.
- **Run events go on the Home Assistant event bus**, so an automation can act on
  a step being reached. Events rather than entities on purpose — see the README.
- **A numbered migration ladder.** The version was written on every connect
  *before* being read, which destroyed the one thing a migration needs, and it
  already disagreed with the schema on disk. A database from a newer Stepwise is
  now refused rather than misread, and the file is copied aside before any
  migration that rewrites data.
- **Removing the integration sets the database aside** rather than leaving it to
  resurrect itself on the next install.
- **Retention no longer keeps twenty runs in total** for anybody who never named
  a subject. Sequenced after the export, so there is a way to keep a record
  before anything deletes one.
- Diagnostics, carrying counts and settings and not one word of what a procedure
  is about.

### Found by sweeping the release itself, twice

The first sweep found dead ends and claims the notes made falsely; the second
found what the first had introduced. All of it is in
[PLAN_GAPS.md](PLAN_GAPS.md), including what was attacked and held.

- A database that lost its version marker was stamped current with no
  migrations run and every run query dead — permanently. It now heals: tables
  with no readable version walk the whole ladder from the oldest known shape.
- `run_undo` no longer moves the pointer of a stopped run; a paused run is
  offered once and then carries on rather than looping; asking with two live
  runs asks which one rather than denying both; a timer can no longer be
  recorded against a closed run.
- "I didn't mean done", said within ten minutes of a final "done", gets the
  run back. Anything older stays finished.
- "Top up the oil" is called the oil, not "the up the oil". "Bake at 350 F"
  keeps its Fahrenheit for a metric listener rather than being heard as 350
  Celsius. A challenge with nothing on file says so instead of going silent —
  and an engine reply with empty speech is now a test failure, structurally.
- Run events reach the event bus at all: they were fired with the async API
  from a worker thread, which Home Assistant refuses and the engine's own
  guard would have swallowed.
- A note with a newline no longer splits the exported table; a note starting
  `=SUM(` reaches a spreadsheet as text, not a formula; an explicit but wrong
  `run_id` to `export_run` is an error, not somebody else's record.

### Smaller

- The search response path can be configured. A botched edit meant the field
  never rendered at all, so the recommended search adapter always ran with an
  empty path. There is now a test that fails if any setting loses its box.
- A search is given six seconds before a voice turn gives up on it. The bundled
  provider was also passing a bare number where aiohttp wants a `ClientTimeout`,
  and reporting the resulting error as "the provider is not reachable".
- A timer is written into the record once it is genuinely running, not before.
- The handler that catches a failing tool no longer reads the database from the
  event loop to do it, which would have blocked Home Assistant in the one place
  whose whole job is to fail gracefully.
- `quantity_first` no longer takes a units argument it never read.
- An options page that tells you what to say to it.
- Every tool call is timed at debug level.

### Also here, from before the review

Work done after 0.1.0 and never released on its own.

#### Fixed

- After a reorder the pointer goes to the first step **not yet done**, rather
  than following the step it happened to be on. Told "yeast goes in first"
  before anything has gone in, the answer is step one — the old behaviour
  silently skipped the yeast the correction was about.

#### Added

- **Timers read out of the wording.** Nobody fills in a duration field; they
  write "wait 45 minutes for it to blister". Durations are now read from the
  instruction itself, in figures or words, and offered with their reason.
  Quantities are left alone, because a wrong timer is worse than no timer.
- **Switching between things on the go.** `run_where` takes an optional
  reference — the name a person said, never an id — and naming one makes it the
  current run, so what they say next lands on it. Leave the bread proving, go
  and strip a door, come back and ask how the loaf is doing.
- Telling Stepwise what something is, mid-run, attaches it to that run. The
  usual way this is asked for is a correction on a run that never named a
  subject, and the answer has to land somewhere.
- Asked which thing it is when nothing is on file, it asks for the thing —
  "Which bread machine is it? The order depends on the model." — rather than
  offering a choice of nothing.
- Mishearings split across two words are caught: speech-to-text turns
  *derailleur* into "rail er" and *tangzhong* into "yang zoong" far more often
  than it invents a single strange word.

#### Changed

- One best guess is offered rather than a list. "Tangzhong?" is a better
  question than "tangzhong, or Panasonic?"
- Short and common words are no longer queried unless the match is strong,
  so "check the flour is in" passes without comment.
- Timestamps are stored to the millisecond. Two runs touched in the same second
  sorted arbitrarily, and "the one you last touched" is how the right run gets
  chosen.
- A step that states its own duration no longer has the number read back three
  times over.

## [0.1.0] — 2026-08-23

First release. Phases 1 to 5 of [PLAN.md](PLAN.md).

### The run

- Runs as first-class state: one lookup returns exactly where you are, so
  "where were we" works in a cold voice session with no conversation history.
- Hot, warm and cold by elapsed time, both thresholds configurable. Any contact
  resets the clock; several runs may be live at once and are told apart by their
  reference.
- `run_events` as an append-only spine: every advance, reposition, note,
  question and correction, each timestamped.
- A run owns its steps, so an amendment changes that run and not the template
  somebody else is following.

### Addressing

- Advance, reposition, aside and observation as four distinct things, with only
  advancing moving the pointer.
- Positioning by description — "the bit where the fruit goes in", "go back, I've
  not done the salt" — matching on what a phrase is about, and always saying
  which step it landed on.
- Asides answered from the procedure, the notes or the clock, never at the cost
  of your place.

### Corrections

- The challenge flow: ask which subject, ask the make and model, agree with a
  stored quirk, report a contradiction, or search scoped to the make and model.
- Quirks stated aloud before they are relied on, and re-confirmed when the
  ground may have moved. Saying one never confirms it; only the person does.
- Amendments scoped to the run, the subject, or the procedure, including
  reordering, which carries the pointer with it.
- Contradicting a stored subject forks rather than overwrites.

### Resolution

- Local library searched before anything external.
- Phonetic candidates offered for terms speech-to-text may have mangled, rather
  than inventing a procedure for a word that was never said.
- Ambiguous references asked about, never guessed.

### Speaking

- Quantity before the ingredient, units expanded, and quantities converted to
  the system in use — stored steps keep whatever the source said.
- Timers offered with their reason and started only on a yes.
- No wording that implies somebody is behind, has abandoned something, or should
  have finished.

### Licence and data

- MIT, with an as-is disclaimer and no liability accepted, in
  [DISCLAIMER.md](DISCLAIMER.md).
- No telemetry, analytics or crash reporting of any kind. All state is one
  SQLite file in the Home Assistant configuration directory. Anything that
  leaves the machine does so because it was configured to.

### Configuration and providers

- Config flow with the stickiness thresholds first, plus an options flow for
  subjects, their quirks, and putting a stuck run down.
- Search: none, a `rest_command` you already have, or a bundled provider add-on.
- Facts: a built-in table, or ha-ai-memory with the built-in one behind it.
