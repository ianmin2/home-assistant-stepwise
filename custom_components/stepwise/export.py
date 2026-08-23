"""A run, written out. No Home Assistant imports.

`run_events` is an append-only record of a physical job: every advance,
reposition, note, question and correction, each timestamped. PLAN section 10
calls that a lab notebook and the README says it is "already written by the
time you want it" — which was true, and useless, because there was no way to
read it out of the database.

Nothing here computes anything new. It is the spine, in the order it happened,
in something a person can keep.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from .const import (
    EVENT_ADVANCED,
    EVENT_AMENDED,
    EVENT_ASKED,
    EVENT_CHALLENGED,
    EVENT_FINISHED,
    EVENT_NOTE,
    EVENT_PAUSED,
    EVENT_QUIRK_CONFIRMED,
    EVENT_QUIRK_LEARNED,
    EVENT_QUIRK_RETRACTED,
    EVENT_QUIRK_STATED,
    EVENT_REPOSITIONED,
    EVENT_RESUMED,
    EVENT_RUN_STARTED,
    EVENT_TIMER_STARTED,
    EVENT_UNDONE,
)
from .models import Amendment, Procedure, Run, RunEvent, Subject
from .util import elapsed_seconds, parse_iso, say_elapsed, strip_ago

# What each kind of event is called when a person reads it back. The wording is
# plain on purpose: this is a record, not a narration, and a record that
# editorialises is worth less than one that does not.
HAPPENED = {
    EVENT_RUN_STARTED: "Started",
    EVENT_ADVANCED: "Completed step",
    EVENT_REPOSITIONED: "Moved to step",
    EVENT_UNDONE: "Put back to step",
    EVENT_NOTE: "Noted",
    EVENT_ASKED: "Asked",
    EVENT_CHALLENGED: "Disputed",
    EVENT_AMENDED: "Amended",
    EVENT_QUIRK_STATED: "Said aloud",
    EVENT_QUIRK_LEARNED: "Learned",
    EVENT_QUIRK_CONFIRMED: "Confirmed",
    EVENT_QUIRK_RETRACTED: "Forgotten",
    EVENT_TIMER_STARTED: "Timer set",
    EVENT_PAUSED: "Put down",
    EVENT_RESUMED: "Picked back up",
    EVENT_FINISHED: "Finished",
}


def _clock(stamp: str) -> str:
    moment = parse_iso(stamp)
    return moment.strftime("%Y-%m-%d %H:%M") if moment else stamp


def _since_start(started: str, stamp: str) -> str:
    """Elapsed time is the column a notebook is actually read for."""
    moment = parse_iso(stamp)
    gone = elapsed_seconds(started, moment) if moment else None
    if gone is None:
        return ""
    if gone < 60:
        return "0m"
    minutes = int(gone // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def rows(run: Run, events: list[RunEvent]) -> list[dict[str, str]]:
    """One row per thing that happened, in the order it happened."""
    return [
        {
            "at": _clock(event.at),
            "elapsed": _since_start(run.started_at, event.at),
            "step": str(event.step_n) if event.step_n else "",
            "what": HAPPENED.get(event.kind, event.kind),
            "detail": (event.text or "").strip(),
        }
        for event in events
    ]


def as_csv(run: Run, events: list[RunEvent]) -> str:
    """For a spreadsheet. One row per event, no cleverness."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["at", "elapsed", "step", "what", "detail"], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows(run, events))
    return buffer.getvalue()


def as_markdown(
    run: Run,
    events: list[RunEvent],
    procedure: Procedure | None = None,
    subject: Subject | None = None,
    amendments: list[Amendment] | None = None,
) -> str:
    """For reading, and for keeping.

    Deliberately not a narrative. Somebody wanting to know what happened at
    forty minutes in wants a table, and somebody filing it wants a heading.
    """
    lines: list[str] = [f"# {run.reference}", ""]
    if procedure:
        lines.append(f"**Procedure** — {procedure.title}")
    if subject:
        lines.append(f"**Thing** — {subject.described}")
    lines.append(f"**Started** — {_clock(run.started_at)}")
    if run.finished_at:
        took = strip_ago(
            say_elapsed(elapsed_seconds(run.started_at, parse_iso(run.finished_at)))
        )
        if took == "just now":
            took = "under a minute"
        lines.append(f"**Finished** — {_clock(run.finished_at)} ({took} altogether)")
    lines.append(f"**Status** — {run.status}")
    if run.outcome:
        lines.append(f"**How it went** — {run.outcome}")
    lines.extend(["", "## What happened", ""])

    table = rows(run, events)
    if table:
        lines.append("| Time | Elapsed | Step | What | Detail |")
        lines.append("|---|---|---|---|---|")
        for row in table:
            detail = row["detail"].replace("|", "\\|")
            lines.append(
                f"| {row['at']} | {row['elapsed']} | {row['step']} "
                f"| {row['what']} | {detail} |"
            )
    else:
        lines.append("Nothing recorded.")

    if amendments:
        lines.extend(["", "## Changes to the steps", ""])
        for change in amendments:
            why = f" — {change.why}" if change.why else ""
            lines.append(
                f"- **Step {change.step_n}** ({change.scope}): "
                f"*{change.was}* became *{change.now}*{why}"
            )

    if procedure:
        lines.extend(["", "## The steps as they stood", ""])
        for step in procedure.steps:
            lines.append(f"{step.n}. {step.instruction}")

    lines.extend(["", "---", "", "Recorded by Stepwise as the job was done."])
    return "\n".join(lines) + "\n"


def payload(
    run: Run,
    events: list[RunEvent],
    procedure: Procedure | None = None,
    subject: Subject | None = None,
    amendments: list[Amendment] | None = None,
) -> dict[str, Any]:
    """Everything an automation might want, without picking a format for it."""
    return {
        "run_id": run.id,
        "reference": run.reference,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "outcome": run.outcome,
        "subject": subject.described if subject else None,
        "procedure": procedure.title if procedure else None,
        "events": rows(run, events),
        "markdown": as_markdown(run, events, procedure, subject, amendments),
        "csv": as_csv(run, events),
    }
