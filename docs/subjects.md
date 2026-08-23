# Subjects

A subject is **the thing being worked on**: a bread machine, a radiator, a
bicycle, a houseplant, a knee, or a project that does not exist yet.

## They are instances, never categories

Two bicycles are two subjects. This is the part most systems get wrong, and it
is why "learn it once" is not good enough: a quirk learned about a derailleur
bike, silently applied years later to a singlespeed, is worse than having
learned nothing.

| Field | Example | Notes |
|---|---|---|
| `id` | `panasonic_sd_yr2550` | Derived from make and model, or from the label. Never spoken. |
| `kind` | `bread_machine` | Lower case with underscores. Gives a generic fallback. |
| `label` | `the winter bike` | What you call **this one**. How two of a sort are told apart out loud. |
| `make`, `model` | `Panasonic`, `SD-YR2550` | Asked for when they change the instructions, never assumed. |
| `aliases` | `["the panasonic"]` | Other things you call it. |
| `attributes` | `{"speeds": 11}` | Anything that changes instructions later. |
| `status` | `active` | Or `retired`, or `replaced`. |

## Adding a kind

There is no registry to edit. `kind` is a free string, and an unknown kind
still works: the agent falls back to generic knowledge about that sort of thing
while a known make and model gets its specifics.

Two places make a kind easier to say out loud:

- **`KIND_SYNONYMS`** in `resolution.py` maps everyday words to kinds, so "my
  bike" finds a subject of kind `bicycle`. Add a pair when the ordinary word
  differs from the kind.
- **`aliases`** on the subject itself handles anything personal to you, and is
  the right place for most of it.

## Attributes that change what is said

`attributes` is free-form, with one convention Stepwise reads: `programmes`
lets a machine name its own settings and say how long they take.

```yaml
attributes:
  programmes:
    "4": { name: wholemeal, duration_s: 11400 }
    "1": { name: basic }
```

A step whose `settings` names `programme`, `program`, `cycle`, `mode` or
`setting` then gets both: *"Programme four, medium crust. That's the wholemeal
one on yours. Shall I set a timer for 3 hours 10? That's the programme length."*

A list works too, where position is the programme number. A machine that knows
nothing simply gets nothing extra, which is the point of a generic fallback.

## A subject need not exist yet

For a build, `kind` is `project` and the attributes describe the target rather
than a product: the board, the pinout, the bill of materials, which parts have
arrived. The same run machinery applies, and so do the same identity rules —
"the sensor project" is one subject, and next year's is another.

## Contradiction is a fork, not an update

If somebody describes something inconsistent with a stored subject — "there's no
derailleur on this one" — the right response is *"different bike, or has this one
changed?"*, not overwriting the record. One creates a new subject; the other
amends it.

## Quirks

A quirk is a claim about **one** subject:

```
subject_id      bike_winter_hack       # the instance, never the kind
claim           "11 speed, needs a quick link not a pin"
learned_from    user | web | manual | observed
confidence      high | medium | low
material        true                   # does acting on it change instructions?
learned_at, last_confirmed_at, times_applied
```

The rules the code enforces:

1. **Said, not assumed.** A quirk that changes an instruction is spoken as an
   assertion you can reject in flight: *"On yours, yeast first, then the flour."*
2. **Re-confirmed when the ground may have moved.** Any one of four things is
   enough: the subject was matched by category rather than by name; the quirk
   came from the web and you have never confirmed it; you have said something
   contradicting it during this run; or it is material and has not been
   confirmed in a long time. Otherwise it is stated and the procedure carries
   on, because interrogating somebody about a machine they have owned for six
   years is the failure this rule exists to avoid.

   **Saying a quirk aloud never confirms it.** Only your answer does, through
   `quirk_confirm`. Otherwise a quirk confirms itself the first time it is
   spoken and then asserts itself forever.
3. **Superseded, never appended.** A new claim on the same subject replaces the
   old one, which stays readable as history.
4. **Scoped to a subject, never to a kind.** Nothing learned about one bicycle
   is ever applied to another.
5. **Visible and editable**, in *Configure → Things and their quirks*.
