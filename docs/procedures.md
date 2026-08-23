# Procedures

A procedure is a **template**: ordered steps, subject-agnostic where possible.
A run is one execution of it.

## Schema

```
procedure
  id, title, kind, subject_kind, yields, prep_notes, source
  steps [ { n, instruction, speakable, ingredients[], duration_s, awaits, settings{} } ]
```

| Field | Purpose |
|---|---|
| `instruction` | The step as written. |
| `speakable` | The step as read aloud. Generated from the instruction if absent. |
| `ingredients` | What the step consumes or needs. Used to answer "what was the flour weight" and to work out which steps a correction touches. |
| `duration_s` | How long it takes. Drives timer offers and "how much longer". |
| `awaits` | `none`, `confirm` (wait to be told), or `timer`. |
| `settings` | Machine settings: programme, crust, torque, temperature. |

`source` is `web`, `user` or `generated`. It is stored and not yet acted on:
the intent — a `generated` step yielding to the person at once while a `web`
step cites — is [deferred work](../PLAN_GAPS.md), and this sentence will change
when it lands. Nothing reads the field today.

## Speakable steps

The ear needs the number before the thing when hands are busy, so
`"wholemeal flour, 200 g"` becomes `"200 grams of wholemeal flour"`, and units
are expanded so text-to-speech says *grams* rather than *gee*. Anything already
leading with a quantity is left alone.

If you write `speakable` yourself it is used verbatim.

## A run owns its steps

When a run starts it takes a **copy** of the procedure's steps. Everything that
happens next — rewording, reordering — happens to the run's copy.

This is what makes amendment scoping honest:

| Scope | Changes this run | Records a quirk | Rewrites the template |
|---|---|---|---|
| `run` | yes | no | no |
| `subject` | yes | yes | no |
| `procedure` | yes | yes | yes |

Reordering a load order for one bread machine changes that loaf and that
machine's quirks. It does not change the procedure somebody else is following.

## Timers

A step with a `duration_s`, a step whose programme the subject knows the length
of, **or a step whose wording simply says how long it takes**, is offered a
timer with its reason attached.

Nobody fills in a duration field. They write "wait 45 minutes for it to
blister", so that is where Stepwise looks — figures or words, `45 minutes`,
`an hour`, `forty-five minutes`, `1 hr 30`. Quantities are left alone: `15 mm`,
`25 Nm` and `200 g` are not times, and a wrong timer is worse than no timer.

When the number came from somewhere the person cannot see, the offer says where
from — *"Shall I set a timer for 3 hours 10? That's the programme length."* When
the step just said it out loud, it points at it instead: *"Shall I set a timer
for that?"*

Offered, never imposed. `run_timer` starts one of Home Assistant's own voice
timers, and only after the person has said yes. Timers belong to the device
being spoken to, so on a device that cannot run them Stepwise says so plainly
and keeps the elapsed time itself — "how long has that been?" is answerable
either way.

## Deduplication

Procedures are deduplicated by title and subject kind: planning
"Rosemary tangzhong loaf" for a `bread_machine` twice replaces the steps rather
than accumulating a second copy. Runs already in flight are unaffected, because
they hold their own steps.

## Addressing a procedure

Only one kind of utterance moves a run forward.

| Utterance | Tool | Effect |
|---|---|---|
| "Done", "that's in", "next" | `run_advance` | Moves the pointer, timestamped. |
| "How's the loaf doing?" | `run_where` with a reference | Switches to that run and reports it. Whatever comes next lands there. |
| "Skip to the second prove", "go back, I've not done the salt" | `run_goto` | Moves the pointer by description, and **says which step it landed on**. |
| "How many calories is that?" | `run_ask` | Answers. Moves nothing. |
| "It's gone a bit sticky" | `run_note` | Recorded against the step and the time. |

Positioning matches on what the phrase is *about*: only words the procedure
itself uses count as evidence, so "go back, I've not done the salt yet" goes to
the salt rather than back one step. When nothing matches confidently it asks
instead of jumping, because silently being on a different step from the person
is the single most damaging failure.
