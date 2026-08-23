# Changelog

All notable changes to Stepwise are recorded here. Versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

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

### Configuration and providers

- Config flow with the stickiness thresholds first, plus an options flow for
  subjects, their quirks, and putting a stuck run down.
- Search: none, a `rest_command` you already have, or a bundled provider add-on.
- Facts: a built-in table, or ha-ai-memory with the built-in one behind it.
