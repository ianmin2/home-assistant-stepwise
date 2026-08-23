# Stepwise

**Guided step by step procedures for Home Assistant.**

A voice assistant that walks you through a multi-step physical procedure, hands
free, across days, and lets you be interrupted, corrected and resumed.

> "Guide me step by step."
> "First, two hundred grams of wholemeal flour."
> "My machine takes yeast first and salt at the top."
> *(checks the model, agrees or corrects, reorders the remaining steps,
> remembers the quirk)*
> "Tell me when the ingredients are in."
> "Done."

Nothing about that is specific to bread. The same machinery covers converting a
radiator to a thermostatic valve, replacing a bicycle chain, wiring an ESP32
project, or logging observations against elapsed time in a lab.

The design lives in [PLAN.md](PLAN.md). This README is how to run it.

## The actual product is pause and resume

A checklist app can list steps. What nobody has, hands free, is the ability to
stop in the middle because the doorbell went, or because it is Tuesday now, and
pick up exactly where you were without re-reading anything.

- **Resuming costs one utterance.** "Where were we."
- **A gap is never treated as failure.** No streaks, no nagging, no progress bar
  implying you are behind.
- **The system holds the state, not you.** It knows, because it wrote it down
  with a timestamp when it happened.
- **Asides are free.** Asking a question mid-procedure never costs you your
  place.

## Installing

**HACS**: *HACS → three dots → Custom repositories →*
`https://github.com/ianmin2/stepwise`, category *Integration*. Install, then
restart Home Assistant.

**By hand**: copy `custom_components/stepwise` into your `config/custom_components`
directory and restart.

Then *Settings → Devices & Services → Add Integration → Stepwise*.

## Giving an agent the tools

Stepwise registers an LLM API called **Stepwise**. Attach it to whichever
conversation agent should be able to run procedures:

*Settings → Devices & Services →* your conversation agent *→ Configure →
Control Home Assistant →* **Stepwise**.

Give it to the agent that thinks, not to one that tunnels to another agent. Any
agent without the API attached is unaffected.

## Settings

The two thresholds are the important ones, and they are the reason the same
integration serves a loaf and a twelve-hour reaction.

| Setting | Default | What it decides |
|---|---|---|
| Assume this run for | 30 minutes | While a run is *hot*, "next" means it, with no preamble. |
| Offer rather than assume after | 4 hours | Past this a run is *cold*: offered, never assumed. |
| Units | Metric | Quantities are converted for reading aloud. A recipe in grams is read in ounces to somebody working in ounces, and the stored step keeps what the source said. |
| Moving on | Wait to be told | Whether silence can ever advance a step. It cannot, by default. |
| Naming a run | Propose | Whether the agent proposes a reference, always asks, or never asks. |
| Long term facts | Built in | Where durable facts live. See *Looking things up*. |
| Looking things up | None | Search provider. See *Looking things up*. |
| Finished runs kept per thing | 20 | Archive retention. Runs are bounded by construction. |

Anything in flight is between the two thresholds — *warm* — and gets named
before it is continued: "On the rosemary loaf, next is..."

### Things and their quirks

*Configure → Things and their quirks* lists every subject with what has been
learned about it, each quirk showing where it came from and when it was last
confirmed. A wrong quirk that cannot be seen is permanent, so they are all
visible and any of them can be forgotten.

*Configure → Put a run down* closes a stuck run. It is worded as a fact, not a
failure, and the history stays.

## The tools

Deliberately few. Each does one thing and returns one speakable string plus
structured fields.

| Tool | Purpose |
|---|---|
| `resolve_intent` | The requirements conversation. Searches what you already have first, offers phonetic candidates for misheard terms, reports what still needs asking. |
| `subject_resolve` | Turn "my bike" into one subject, or ask which. |
| `subject_save` | Record or amend one thing, including the make and model it was asked for. |
| `procedure_plan` | Store the steps and propose a name. Does not start anything. |
| `run_start` | Begin. Returns step one and the reference. |
| `run_where` | Where am I, in which thing, how long since. Takes no arguments, by design. |
| `run_advance` | Complete this step, return the next. The only tool that moves a run forward. |
| `run_goto` | Reposition by description, always reporting where it landed. |
| `run_ask` | An aside. Answers from the procedure, the notes or the clock. Moves nothing. |
| `run_note` | Record an observation against the current step and time. |
| `run_challenge` | The person disputes a step. Decides between agreeing, contradicting, or searching. |
| `run_amend` | Change a step or the order, scoped to this run, this thing, or the template. |
| `quirk_confirm` | Record the person's answer when a quirk was re-confirmed out loud. Saying a quirk never confirms it; only this does. |
| `run_timer` | Start one of Home Assistant's own timers, after offering it and being told yes. |
| `run_finish` | Close, archive, optionally record how it went. |

## Storage

One SQLite file, `stepwise.db`, in your Home Assistant config directory. It is
inspectable, diffable, and backed up with the rest of Home Assistant.

`run_events` is the append-only spine: every advance, reposition, note, question
and correction, each timestamped. Elapsed-time answers, the hot/warm/cold
classification and a readable history of what actually happened all come from
it.

Nothing is written implicitly. Facts enter through an explicit tool call, which
is the single biggest cause of memory rot in comparable projects.

## Looking things up

When somebody disputes a step, Stepwise scopes a search to their make and model
and hands the results back with the challenge. Three adapters, chosen in
settings:

| Provider | What it does |
|---|---|
| **None** (default) | The agent's own knowledge. It is told there is no provider, so it says when something is beyond it rather than guessing. |
| **A rest_command you already have** | Name an existing `rest_command` and the path to the answer in its response, for example `response.results.0.content`. Works with anything, and ships nothing. |
| **Bundled provider add-on** | Posts to `/search` on an address you give it. Optional, never a dependency. |

Long-lived facts work the same way. **Built in** keeps them in a `facts` table in
the same SQLite file, for people who do not want a second integration.
**ha-ai-memory** reads a subject's facts from
[that integration](https://github.com/Riscue/ha-ai-memory) and writes learned
quirks back to it, with the built-in store always behind it so nothing is lost
if it is not there.

That adapter is **provisional**: the plan says to agree the integration point
upstream rather than assume it, so it calls services whose names default to
sensible guesses and falls back cleanly when they are absent.

## Not built yet

Phases 1 to 5 of [PLAN.md](PLAN.md) are here. Remaining, from phase 6:

- **Brands submission** — a pull request to `home-assistant/brands`. The icons
  are drawn and waiting in [brands/](brands/custom_integrations/stepwise); the
  pull request needs a GitHub account.
- **A tagged release** and HACS listing. Everything for both is prepared —
  see [docs/releasing.md](docs/releasing.md).
- **The upstream conversation** with ha-ai-memory, which turns the provisional
  adapter into an agreed one.

## Two deliberate differences from PLAN.md

- **No conversation-agent multi-select.** Home Assistant attaches LLM APIs from
  the agent's own settings, so a picker here would be a second switch that could
  disagree with the real one. Attach Stepwise per agent as described above.
- **`subject_save` is a thirteenth tool.** The correction flow is required to
  ask for a make and model when it changes the instructions, so it needs a way
  to store the answer.

## Development

The core has no Home Assistant imports, so it runs anywhere:

```bash
python3 -m unittest discover -s tests
ruff check custom_components tests
```

Both run in CI on every push, alongside Home Assistant's own `hassfest` and the
HACS validator.

`tests/context.py` loads the core without importing the Home Assistant entry
point. Every rule in the design that can be tested is tested against the bread
example, because if it works end to end for a tangzhong loaf it works for a
radiator.

## Credits

Designed by [@ianmin2](https://github.com/ianmin2) — [PLAN.md](PLAN.md) is the
document everything here was built from, and it is worth reading before changing
anything.

Phases 1 to 3 were implemented by Claude Opus 5, working in
[Claude Code](https://claude.com/claude-code) .
