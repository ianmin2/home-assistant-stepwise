# Disclaimer and data statement

These terms **supplement** the [MIT licence](LICENSE) and do not replace or
narrow it. Where the two overlap, they say the same thing: the software is
provided as-is and the authors accept no liability. Where this document says
more, it is because a tool that talks people through physical work deserves to
say more.

The licence text itself is left exactly as the standard MIT licence, word for
word, so that it stays a recognised licence rather than a bespoke one.

## 1. No warranty of any kind

The software is provided **"as is"**, without warranty of any kind, express or
implied — including but not limited to warranties of merchantability, fitness
for a particular purpose, accuracy, and non-infringement.

Nobody warrants that it will work, that it will keep working, that it is free of
defects, or that anything it says is correct.

## 2. What it does, and why that matters

Stepwise reads out procedures for **physical tasks**. The steps are composed by
a language model, taken from the open web, or dictated by a person. Any of those
can be wrong, out of date, wrong for your particular make and model, or wrong in
a way that matters.

**You remain entirely responsible for what you actually do.** In particular:

- **Check anything that could hurt you or damage property** against the
  manufacturer's own instructions before acting on it.
- **Gas, electrical, structural, pressurised, chemical, automotive and medical
  work** should be done by a qualified person where the law, your insurer, or
  ordinary good sense requires it. A voice assistant reading out steps is not a
  substitute for a competent professional, and must not be treated as one.
- **Food safety, allergens, dosages and quantities** are yours to verify. A
  misheard word or a converted unit can change a quantity.
- **Your own judgement outranks the software.** If a step looks wrong, it may
  well be wrong. Stop.
- Never rely on it as a safety system, an alarm, a reminder for anything
  critical, or a record you cannot afford to lose.

The software has no way of knowing whether an instruction is safe for you, your
equipment, or your situation, and it does not try to.

## 3. No liability, in either direction

To the fullest extent permitted by applicable law, the authors and copyright
holders accept **no liability whatsoever** arising from or connected with the
software or its use, including without limitation:

- personal injury, illness, or death;
- damage to property, equipment, buildings, vehicles or materials;
- wasted, spoiled or ruined ingredients, components or work;
- loss of data, loss of profit, loss of time, business interruption;
- any indirect, incidental, special, exemplary, punitive or consequential loss;

whether the claim arises in contract, tort (including negligence), breach of
statutory duty, or otherwise, and whether or not the possibility of such loss
was known or foreseeable.

Equally, the authors make **no claim over, and take no responsibility for**, the
content you create with it, the procedures you record, or what you choose to do
with either.

**Nothing here excludes or limits liability that cannot lawfully be excluded or
limited** — for example liability for death or personal injury caused by
negligence, for fraud or fraudulent misrepresentation, or any other liability
which applicable law does not permit to be excluded. If any part of this section
is held unenforceable, the remainder continues to apply.

## 4. Data

**Stepwise collects nothing.** There is no telemetry, no analytics, no crash
reporting, no usage statistics, no licence check, and no hardcoded endpoint of
any kind. The authors never receive your data, and do not want it.

**Everything it stores is local.** One SQLite file, `stepwise.db`, in your Home
Assistant configuration directory, alongside the rest of your Home Assistant
data. It is yours: readable, backed up with everything else, and deleted by
deleting the file.

**What leaves your machine does so because you configured it to**, and only
then:

| Thing | When it happens |
|---|---|
| Your words reach a conversation agent | Whenever you talk to any Home Assistant assistant. If that agent is a cloud model, your words go wherever that provider sends them. This is Home Assistant's plumbing and your choice of agent, not something Stepwise adds. |
| A search query is sent | Only if you set a search provider. The `rest_command` option calls a command **you** already defined; the bundled option posts to an address **you** typed in. With the default of *None*, nothing is sent. |
| A fact is written to a memory integration | Only if you select the ha-ai-memory backend. The built-in backend keeps facts in the same local SQLite file. |

Those third parties — your model provider, your search endpoint, any other
integration — have their own terms and their own handling of your data. **They
are outside this software's control and outside its authors' responsibility.**
Satisfying yourself about them is your decision to make.

## 5. Not professional advice

Nothing produced by this software is professional advice of any kind — not
medical, legal, engineering, electrical, gas, structural, veterinary,
nutritional or financial. It is a tool for keeping your place in a list of
steps, and nothing about it should be read as a recommendation to do any
particular thing.

## 6. Not affiliated

Stepwise is an independent custom integration. It is **not** affiliated with,
endorsed by, or supported by the Home Assistant project, Nabu Casa, the
ha-ai-memory project, or any manufacturer whose products appear in examples or
in your own data. Product and company names are used only to identify the things
being worked on, and remain the property of their owners.

## 7. No obligation to support

The authors are under no obligation to provide support, fixes, updates, or
continued availability of anything, and may change or abandon any of it at any
time.

---

*This document is written carefully but it is not legal advice, and its authors
are not your lawyers. If your use of this software carries commercial or
regulatory weight, have somebody qualified in your jurisdiction review it.*
