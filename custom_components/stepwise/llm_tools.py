"""The tools, as Home Assistant's LLM API sees them.

Deliberately few, each doing one thing and returning one speakable string plus
structured fields (section 8.1). Everything blocking happens in an executor;
nothing here holds the event loop.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent, llm
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonObjectType

from .const import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DOMAIN,
    LEARNED_FROM_MANUAL,
    LEARNED_FROM_OBSERVED,
    LEARNED_FROM_USER,
    LEARNED_FROM_WEB,
    SCOPE_PROCEDURE,
    SCOPE_RUN,
    SCOPE_SUBJECT,
    SOURCE_GENERATED,
    SOURCE_USER,
    SOURCE_WEB,
)
from .engine import Engine
from .memory import MemoryBackend
from .search import SearchProvider

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required("instruction", description="The step, written out"): str,
        vol.Optional(
            "speakable", description="The same step as it should be read aloud"
        ): str,
        vol.Optional("ingredients", description="Things this step consumes or needs"): [str],
        vol.Optional("duration_s", description="How long this step takes, in seconds"): int,
        vol.Optional(
            "awaits",
            description="none, confirm (wait for the person), or timer",
        ): vol.In(["none", "confirm", "timer"]),
        vol.Optional("settings", description="Machine settings for this step"): dict,
    }
)


class StepwiseTool(llm.Tool):
    """A tool over one engine call, run off the event loop."""

    def __init__(
        self,
        engine: Engine,
        search: SearchProvider | None = None,
        memory: MemoryBackend | None = None,
    ) -> None:
        self.engine = engine
        self.search = search
        self.memory = memory

    @staticmethod
    def _user_id(llm_context: llm.LLMContext) -> str | None:
        return llm_context.context.user_id if llm_context.context else None

    async def _run(self, hass: HomeAssistant, method: str, **kwargs: Any) -> JsonObjectType:
        def call() -> JsonObjectType:
            return getattr(self.engine, method)(**kwargs).as_dict()

        try:
            return await hass.async_add_executor_job(call)
        except Exception as err:  # the turn must not die silently
            _LOGGER.exception("Stepwise tool %s failed", method)
            return self._sorry(method, err)

    def _sorry(self, method: str, err: Exception) -> JsonObjectType:
        """Fail, and still say where they are.

        A tool that raises takes the whole turn with it, and the person — hands
        full, halfway through something — gets whatever the agent says when it
        has nothing. Restating the place is the one thing worth saying, so it
        is tried first and separately: if that fails too, say so plainly rather
        than pretending.
        """
        where = ""
        try:
            run = self.engine.current_run()
            if run is not None:
                where = (
                    f" You were on {run.reference}, step {run.current_step}."
                    " Nothing has moved."
                )
        except Exception:  # already failing; do not fail louder
            where = ""
        return {
            "speech": f"Something's gone wrong at my end.{where}",
            "status": "failed",
            "tool": method,
            "error": str(err),
            "pointer_unchanged": True,
        }


class ResolveIntentTool(StepwiseTool):
    """The requirements conversation, before there is a run."""

    name = "resolve_intent"
    description = (
        "Work out what the person means before planning anything. Searches what this "
        "home already has first, offers phonetic candidates for terms that may have "
        "been misheard, and reports what still needs asking. Ask only what changes "
        "the steps. Does not start anything."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "words", description="What the person said, as close to verbatim as possible"
            ): str
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass,
            "resolve_intent",
            spoken=tool_input.tool_args["words"],
            user_id=self._user_id(llm_context),
        )


class SubjectResolveTool(StepwiseTool):
    """Turn "my bike" into one subject, or ask which."""

    name = "subject_resolve"
    description = (
        "Turn what the person called a thing into exactly one known subject. If two "
        "match, it returns a question to ask rather than guessing. Subjects are "
        "instances, never categories: two bicycles are two subjects."
    )
    parameters = vol.Schema(
        {vol.Required("words", description="What the person called it"): str}
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass,
            "subject_resolve",
            spoken=tool_input.tool_args["words"],
            user_id=self._user_id(llm_context),
        )


class SubjectSaveTool(StepwiseTool):
    """Record or amend one subject, including the make and model when asked for."""

    name = "subject_save"
    description = (
        "Create a subject, or amend one that exists, when the person tells you what "
        "something is. Use it to store a make and model you were asked for. If the "
        "If a run is under way without one, the answer is attached to it. If the "
        "person describes something inconsistent with a stored subject it will refuse "
        "and ask: create a new subject if it is a different thing, or pass changed "
        "once they confirm this one has changed."
    )
    parameters = vol.Schema(
        {
            vol.Required("label", description="What the person calls this one thing"): str,
            vol.Required(
                "kind",
                description=(
                    "Category, lower case with underscores: bread_machine, radiator, "
                    "bicycle, project"
                ),
            ): str,
            vol.Optional("make", description="Manufacturer, if known"): str,
            vol.Optional("model", description="Model number, if known"): str,
            vol.Optional("aliases", description="Other things the person calls it"): [str],
            vol.Optional(
                "attributes", description="Anything that changes instructions later"
            ): dict,
            vol.Optional(
                "subject_id", description="Amend this existing subject rather than creating one"
            ): str,
            vol.Optional(
                "changed",
                description=(
                    "True only when the person has confirmed this is the same thing and it "
                    "has changed, rather than a different one"
                ),
            ): bool,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "subject_save", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class QuirkConfirmTool(StepwiseTool):
    """The person answers a re-confirmation. Only they can settle it."""

    name = "quirk_confirm"
    description = (
        "Record the answer when you have re-confirmed a quirk out loud and the person "
        "replied. Yes keeps it and marks it confirmed by them; no forgets it, and you "
        "should then ask what is actually the case and store that with run_amend. "
        "Saying a quirk aloud never confirms it: only this does."
    )
    parameters = vol.Schema(
        {
            vol.Required("quirk_id", description="From the quirk you read out"): str,
            vol.Optional("still_right", description="What they said. Defaults to yes"): bool,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "quirk_confirm", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class ProcedurePlanTool(StepwiseTool):
    """Compose or fetch the steps, store, name it. Does not start it."""

    name = "procedure_plan"
    description = (
        "Store an ordered set of steps as a procedure and propose a name for it. "
        "Give the quantity before the ingredient in every step. This does not start "
        "anything: call run_start when the person is ready to begin."
    )
    parameters = vol.Schema(
        {
            vol.Required("title", description="What this procedure is"): str,
            vol.Required("steps", description="The steps, in order"): [STEP_SCHEMA],
            vol.Optional("subject_id", description="The thing it will be done to or with"): str,
            vol.Optional(
                "subject_kind", description="Category, if there is no specific subject"
            ): str,
            vol.Optional("yields", description="What it produces"): str,
            vol.Optional("prep_notes", description="Anything needed before starting"): str,
            vol.Optional(
                "source", description="Where the steps came from"
            ): vol.In([SOURCE_WEB, SOURCE_USER, SOURCE_GENERATED]),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(hass, "procedure_plan", **tool_input.tool_args)


class RunStartTool(StepwiseTool):
    """Begin. Returns step one and confirms the reference."""

    name = "run_start"
    description = (
        "Start a procedure. Returns the first step and the reference the run will be "
        "called by. Read out any quirks it returns before the step itself."
    )
    parameters = vol.Schema(
        {
            vol.Required("procedure_id", description="From procedure_plan"): str,
            vol.Optional(
                "reference", description="What to call this run out loud, e.g. the rosemary loaf"
            ): str,
            vol.Optional("subject_id", description="The thing being worked on"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        reply = await self._run(
            hass, "run_start", user_id=self._user_id(llm_context), **tool_input.tool_args
        )
        subject_id = tool_input.tool_args.get("subject_id")
        if self.memory is not None and subject_id:
            facts = await self.memory.facts(subject_id)
            if facts:
                reply["known_facts"] = [fact.as_dict() for fact in facts]
        return reply


class RunWhereTool(StepwiseTool):
    """Where am I, in which thing, and how long since. No arguments, by design."""

    name = "run_where"
    description = (
        "Where the person is: which run, which step, and how long since they last "
        "touched it. Call this whenever they ask where they were, or say anything "
        "that assumes you already know. Needs nothing to answer. Pass reference "
        "only to switch to a different thing they are part way through, using the "
        "name they said for it — never an id. Naming one makes it the current one, "
        "so what they say next lands on it."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "reference", description="What they called it, e.g. the rosemary loaf"
            ): str
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_where", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunAdvanceTool(StepwiseTool):
    """The only tool that moves the run forward."""

    name = "run_advance"
    description = (
        "Complete the current step and return the next one. Only for 'done', "
        "'that's in', 'next'. Never call this because the person asked a question, "
        "and never because they remarked on how it is going: 'it's gone sticky' is "
        "not 'done'. Pass from_step with the number of the step you last read out, "
        "so a run that has drifted out of step with you is caught rather than moved."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "note", description="Anything they said while completing it"
            ): str,
            vol.Optional(
                "from_step",
                description="The number of the step you just read out to them",
            ): int,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_advance", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunUndoTool(StepwiseTool):
    """Put the pointer back where it was, and say so."""

    name = "run_undo"
    description = (
        "Reverse the last thing that moved the run — 'no, go back', 'I didn't mean "
        "done', 'that wasn't finished'. Says which step it put them back on. It "
        "moves the pointer and nothing else: it does not unlearn anything, and it "
        "does not stop a timer."
    )
    parameters = vol.Schema(
        {vol.Optional("run_id", description="Only when more than one run is live"): str}
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_undo", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunGotoTool(StepwiseTool):
    """Reposition by description. Always reports where it landed."""

    name = "run_goto"
    description = (
        "Move to a different step described in words: 'the bit where the fruit goes "
        "in', 'skip to the second prove', 'go back, I've not done the salt'. Always "
        "say which step it landed on. If it is unsure it asks instead of moving."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "description", description="How the person described where they are"
            ): str,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_goto", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunAskTool(StepwiseTool):
    """An aside. Moves nothing."""

    name = "run_ask"
    description = (
        "Answer a question asked mid-procedure without moving the pointer: 'how many "
        "calories', 'how long has that been resting', 'what was the flour weight'. "
        "Returns an answer when it can, and the run's context when the answer needs "
        "you. The person stays exactly where they were."
    )
    parameters = vol.Schema(
        {
            vol.Required("question", description="What they asked"): str,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_ask", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunNoteTool(StepwiseTool):
    """Record an observation against the current step and time."""

    name = "run_note"
    description = (
        "Record something the person observed — 'it's gone a bit sticky', 'cloudy at "
        "forty minutes' — against the current step, with the time. Moves nothing."
    )
    parameters = vol.Schema(
        {
            vol.Required("text", description="What they observed"): str,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_note", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


class RunChallengeTool(StepwiseTool):
    """The user disputes a step."""

    name = "run_challenge"
    description = (
        "The person says a step is wrong for their particular thing. Returns what to "
        "do: ask which subject, ask the make and model, agree because it is already "
        "noted, report that a stored note says the opposite, or hand you a search "
        "query scoped to their make and model. Never overrule them silently, and "
        "never accept silently either: say which it is."
    )
    parameters = vol.Schema(
        {
            vol.Required("claim", description="What they said, in their words"): str,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        reply = await self._run(
            hass, "run_challenge", user_id=self._user_id(llm_context), **tool_input.tool_args
        )
        if self.search is None or reply.get("status") not in ("unknown", "conflicts"):
            return reply

        # Scoped to the make and model, because that is what the answer turns on.
        findings = await self.search.search(
            str(reply.get("search_query") or ""), reply.get("search_scope")
        )
        return {**reply, "search": findings.as_dict()}


class RunAmendTool(StepwiseTool):
    """Change a step, or the order, in this run — and optionally further."""

    name = "run_amend"
    description = (
        "Change a step's wording, or reorder the steps, for this run. Scope decides "
        "how far it goes: 'run' is this run only, 'subject' also records it as a "
        "quirk of that one thing, 'procedure' also rewrites the shared template. "
        "Amend the remaining steps, not just the current one."
    )
    parameters = vol.Schema(
        {
            vol.Optional("step_n", description="Which step to reword"): int,
            vol.Optional("change", description="The new wording for that step"): str,
            vol.Optional(
                "reorder", description="Every step number, in the order they should now happen"
            ): [int],
            vol.Optional("why", description="Why, in the person's words. Becomes the quirk"): str,
            vol.Optional("scope", description="How far the change reaches"): vol.In(
                [SCOPE_RUN, SCOPE_SUBJECT, SCOPE_PROCEDURE]
            ),
            vol.Optional("also_steps", description="Other steps this change affects"): [int],
            vol.Optional("learned_from", description="Where the correction came from"): vol.In(
                [LEARNED_FROM_USER, LEARNED_FROM_WEB, LEARNED_FROM_MANUAL, LEARNED_FROM_OBSERVED]
            ),
            vol.Optional("confidence", description="How sure it is"): vol.In(
                [CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW]
            ),
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        reply = await self._run(
            hass, "run_amend", user_id=self._user_id(llm_context), **tool_input.tool_args
        )
        if self.memory is not None and reply.get("quirk_id"):
            # Stepwise keeps run state; durable facts belong in the memory layer.
            claim = tool_input.tool_args.get("why") or tool_input.tool_args.get("change") or ""
            subject = await hass.async_add_executor_job(
                lambda: self.engine.store.get_run(str(reply.get("run_id")))
            )
            if claim and subject and subject.subject_id:
                await self.memory.remember(claim, subject.subject_id, source="stepwise")
        return reply


class RunTimerTool(StepwiseTool):
    """Start one of Home Assistant's own timers, once the person has agreed."""

    name = "run_timer"
    description = (
        "Start a Home Assistant timer for a step, after offering it and being told "
        "yes. Never start one unasked. The timer belongs to the device being spoken "
        "to, so it will refuse on a device that cannot run timers — say so plainly "
        "rather than pretending one is running."
    )
    parameters = vol.Schema(
        {
            vol.Required("seconds", description="How long, in seconds"): int,
            vol.Optional(
                "name", description="What to call it. Defaults to the run's reference"
            ): str,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        args = dict(tool_input.tool_args)
        seconds = int(args.get("seconds") or 0)
        if seconds <= 0:
            return {"speech": "How long for?", "status": "no_duration"}

        recorded = await self._run(
            hass, "run_timer", user_id=self._user_id(llm_context), **args
        )

        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        slots: dict[str, Any] = {
            unit: {"value": value}
            for unit, value in (("hours", hours), ("minutes", minutes), ("seconds", secs))
            if value
        }
        slots["name"] = {"value": recorded.get("name") or "timer"}

        try:
            await intent.async_handle(
                hass,
                DOMAIN,
                intent.INTENT_START_TIMER,
                slots,
                context=llm_context.context,
                language=llm_context.language,
                assistant=llm_context.assistant,
                device_id=llm_context.device_id,
            )
        except (intent.IntentError, HomeAssistantError) as err:
            # Degrade honestly rather than claiming a timer that is not running.
            return {
                **recorded,
                "speech": (
                    "I can't set a timer on this device. I'll keep the time here "
                    "instead — ask me how long it has been."
                ),
                "status": "timer_unavailable",
                "timer_started": False,
                "why": str(err),
            }

        return {**recorded, "timer_started": True}


class RunFinishTool(StepwiseTool):
    """Close, archive, optionally record how it went."""

    name = "run_finish"
    description = (
        "Close a run. Record how it went if they said: it is the note that makes the "
        "next one better. Use abandoned when they are stopping rather than finishing, "
        "and say so plainly, without judgement."
    )
    parameters = vol.Schema(
        {
            vol.Optional("outcome", description="How it went, in their words"): str,
            vol.Optional("abandoned", description="Stopping rather than finishing"): bool,
            vol.Optional("run_id", description="Only when more than one run is live"): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        return await self._run(
            hass, "run_finish", user_id=self._user_id(llm_context), **tool_input.tool_args
        )


TOOLS: tuple[type[StepwiseTool], ...] = (
    ResolveIntentTool,
    SubjectResolveTool,
    SubjectSaveTool,
    QuirkConfirmTool,
    ProcedurePlanTool,
    RunStartTool,
    RunWhereTool,
    RunAdvanceTool,
    RunUndoTool,
    RunGotoTool,
    RunAskTool,
    RunNoteTool,
    RunChallengeTool,
    RunAmendTool,
    RunTimerTool,
    RunFinishTool,
)

PROMPT = """\
You are guiding somebody through a physical procedure, hands free, one step at a \
time. They may be interrupted, may put it down for days, and may have oily hands \
and no free finger to scroll with.

How to speak:
- One step at a time. Never read the whole procedure unless asked.
- Say the quantity before the ingredient: "two hundred grams of wholemeal flour".
- Say a step's `speakable` text, not its written instruction.
- When something must be waited for, say so and then stop talking. Never treat \
silence as agreement.
- If asked what is left, list the remaining steps. "A few more" is not an answer.
- Timers are offered with their reason, never imposed. Start one with run_timer \
only after they say yes.
- Never imply somebody is behind, has abandoned something, or should have \
finished. A run left for three days is simply a run left for three days.

Which tool:
- "Done", "that's in", "next" -> run_advance, passing from_step with the number \
of the step you last read out. Nothing else advances a run.
- "No, go back", "I didn't mean done" -> run_undo. It says where it put them back.
- A question of any kind -> run_ask. Asking must never cost somebody their place.
- An observation -> run_note.
- "Skip to...", "go back...", "I'm at the bit where..." -> run_goto, and always \
say which step it landed on.
- "Where were we" or anything that assumes you already know -> run_where.
- If a tool answers that it has them on a different step, believe it and say so. \
It is holding the record; you are holding a guess.
- "That's wrong for mine" -> run_challenge, then run_amend once it is settled.

Quirks are said out loud before they are relied on, so they can be corrected \
while hands are busy: "yeast first on yours, then the flour". Never apply one \
silently. When a tool hands you a quirk marked for re-confirming, ask, and pass \
the answer to quirk_confirm: saying a quirk aloud does not confirm it, and only \
the person can. If somebody contradicts a stored quirk, ask whether this is a \
different thing before overwriting anything: two bicycles are two subjects.
"""


class StepwiseAPI(llm.API):
    """The tools, offered to whichever conversation agents the user picks."""

    def __init__(
        self,
        hass: HomeAssistant,
        engine: Engine,
        search: SearchProvider | None = None,
        memory: MemoryBackend | None = None,
    ) -> None:
        super().__init__(hass=hass, id=DOMAIN, name="Stepwise")
        self.engine = engine
        self.search = search
        self.memory = memory

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        user_id = llm_context.context.user_id if llm_context.context else None
        prompt = await self.hass.async_add_executor_job(self._prompt, user_id)
        return llm.APIInstance(
            api=self,
            api_prompt=prompt,
            llm_context=llm_context,
            tools=[tool(self.engine, self.search, self.memory) for tool in TOOLS],
        )

    def _prompt(self, user_id: str | None = None) -> str:
        """The static rules, plus the time and whatever is already in flight.

        Filtered by whoever is asking, the same way every tool is. Unfiltered,
        the prompt told one person about another's runs while the tools denied
        they existed, and the model was left holding two contradictory accounts
        of what was on the go.
        """
        now = dt_util.now()
        lines = [PROMPT, f"The time is {now.strftime('%A %H:%M, %-d %B %Y')}."]
        lines.append(
            "Wait to be told a step is done before advancing."
            if self.engine.wait_to_be_told
            else (
                "A plain acknowledgement may be taken as the step being done. An "
                "observation, a correction, or anything they are reacting to is not: "
                "\"it's gone sticky\" and \"it's smoking\" are not questions, and "
                "neither of them means done."
            )
        )

        if self.search is not None and getattr(self.search, "name", "none") == "none":
            lines.append(
                "You have no search provider, so say plainly when something is beyond "
                "what you know rather than guessing."
            )

        live = [
            run
            for run in self.engine.store.open_runs(user_id=user_id)
            if self.engine.may_touch(run, user_id)
        ]
        if live:
            lines.append("Already part done:")
            for run in live[:5]:
                data = self.engine.run_summary(run)
                lines.append(
                    f"- {data['reference']}: step {data['step']}, last touched "
                    f"{data['since']} ({data['state']})"
                )
            lines.append(
                "A hot run can be assumed. A warm one is named before you continue it. "
                "A cold one is offered, never assumed."
            )
        return "\n".join(lines)
