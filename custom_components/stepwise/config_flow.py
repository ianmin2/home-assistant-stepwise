"""Setup and options.

The options flow exists mostly so that quirks are visible and editable: a wrong
one that cannot be seen is permanent (section 9, rule 5).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ARCHIVE_KEEP_PER_SUBJECT,
    CONF_COLD_HOURS,
    CONF_CONFIRMATION_STYLE,
    CONF_HOT_MINUTES,
    CONF_MEMORY_BACKEND,
    CONF_REFERENCE_NAMING,
    CONF_SEARCH_BASE_URL,
    CONF_SEARCH_PROVIDER,
    CONF_SEARCH_RESPONSE_PATH,
    CONF_SEARCH_REST_COMMAND,
    CONF_UNITS,
    CONFIRM_ANY_SPEECH,
    CONFIRM_EXPLICIT,
    DEFAULTS,
    DOMAIN,
    MEMORY_BUILTIN,
    MEMORY_HA_AI_MEMORY,
    NAMING_ALWAYS_ASK,
    NAMING_NEVER_ASK,
    NAMING_PROPOSE,
    SEARCH_BUNDLED,
    SEARCH_NONE,
    SEARCH_REST_COMMAND,
    SUBJECT_ACTIVE,
    UNITS_IMPERIAL,
    UNITS_METRIC,
)
from .store import Store
from .util import elapsed_seconds, say_elapsed


def _choice(options: list[tuple[str, str]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=value, label=label) for value, label in options
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _quirk_label(quirk: Any) -> str:
    """A quirk with its source and its age, so a wrong one can be spotted."""
    age = say_elapsed(elapsed_seconds(quirk.last_confirmed_at or quirk.learned_at))
    return f"{quirk.claim} — {quirk.learned_from}, {age}"


def _number(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def settings_schema(current: dict[str, Any]) -> vol.Schema:
    """The settings that matter, with context stickiness first."""
    return vol.Schema(
        {
            vol.Required(
                CONF_HOT_MINUTES, default=current.get(CONF_HOT_MINUTES, DEFAULTS[CONF_HOT_MINUTES])
            ): _number(1, 1440, "minutes"),
            vol.Required(
                CONF_COLD_HOURS, default=current.get(CONF_COLD_HOURS, DEFAULTS[CONF_COLD_HOURS])
            ): _number(1, 168, "hours"),
            vol.Required(
                CONF_UNITS, default=current.get(CONF_UNITS, DEFAULTS[CONF_UNITS])
            ): _choice([(UNITS_METRIC, "Metric"), (UNITS_IMPERIAL, "Imperial")]),
            vol.Required(
                CONF_CONFIRMATION_STYLE,
                default=current.get(CONF_CONFIRMATION_STYLE, DEFAULTS[CONF_CONFIRMATION_STYLE]),
            ): _choice(
                [
                    (CONFIRM_EXPLICIT, "Wait to be told it is done"),
                    (CONFIRM_ANY_SPEECH, "Advance on any speech"),
                ]
            ),
            vol.Required(
                CONF_REFERENCE_NAMING,
                default=current.get(CONF_REFERENCE_NAMING, DEFAULTS[CONF_REFERENCE_NAMING]),
            ): _choice(
                [
                    (NAMING_PROPOSE, "Propose a name, accept an override"),
                    (NAMING_ALWAYS_ASK, "Always ask what to call it"),
                    (NAMING_NEVER_ASK, "Never ask, just name it"),
                ]
            ),
            vol.Required(
                CONF_MEMORY_BACKEND,
                default=current.get(CONF_MEMORY_BACKEND, DEFAULTS[CONF_MEMORY_BACKEND]),
            ): _choice(
                [
                    (MEMORY_BUILTIN, "Built in"),
                    (MEMORY_HA_AI_MEMORY, "ha-ai-memory"),
                ]
            ),
            vol.Required(
                CONF_SEARCH_PROVIDER,
                default=current.get(CONF_SEARCH_PROVIDER, DEFAULTS[CONF_SEARCH_PROVIDER]),
            ): _choice(
                [
                    (SEARCH_NONE, "None, the agent's own knowledge"),
                    (SEARCH_REST_COMMAND, "A rest_command you already have"),
                    (SEARCH_BUNDLED, "Bundled provider add-on"),
                ]
            ),
            vol.Optional(
                CONF_SEARCH_REST_COMMAND,
                description={"suggested_value": current.get(CONF_SEARCH_REST_COMMAND)},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_SEARCH_RESPONSE_PATH,
                description={"suggested_value": current.get(CONF_SEARCH_RESPONSE_PATH)},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_SEARCH_BASE_URL,
                description={"suggested_value": current.get(CONF_SEARCH_BASE_URL)},
            ): selector.TextSelector(),
            vol.Required(
                CONF_ARCHIVE_KEEP_PER_SUBJECT,
                default=current.get(
                    CONF_ARCHIVE_KEEP_PER_SUBJECT, DEFAULTS[CONF_ARCHIVE_KEEP_PER_SUBJECT]
                ),
            ): _number(0, 500, "runs"),
        }
    )


class StepwiseConfigFlow(ConfigFlow, domain=DOMAIN):
    """One instance, set up once."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Stepwise", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=settings_schema(DEFAULTS))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return StepwiseOptionsFlow()


class StepwiseOptionsFlow(OptionsFlow):
    """Settings, subjects, quirks, and a way out of a stuck run."""

    def __init__(self) -> None:
        self._subject_id: str | None = None

    # Plumbing ----------------------------------------------------------
    @property
    def _store(self) -> Store:
        return self.config_entry.runtime_data.store

    async def _execute(self, method: str, *args: Any) -> Any:
        return await self.hass.async_add_executor_job(getattr(self._store, method), *args)

    # Menu --------------------------------------------------------------
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "subjects", "runs"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        return self.async_show_form(
            step_id="settings", data_schema=settings_schema(dict(self.config_entry.options))
        )

    # Subjects ----------------------------------------------------------
    async def async_step_subjects(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        subjects = await self._execute("list_subjects", None, True)
        if not subjects:
            return self.async_abort(reason="no_subjects")
        if user_input is not None:
            self._subject_id = user_input["subject_id"]
            return await self.async_step_subject()
        return self.async_show_form(
            step_id="subjects",
            data_schema=vol.Schema(
                {
                    vol.Required("subject_id"): _choice(
                        [
                            (
                                subject.id,
                                f"{subject.described}"
                                + ("" if subject.status == SUBJECT_ACTIVE else " (retired)"),
                            )
                            for subject in subjects
                        ]
                    )
                }
            ),
        )

    async def async_step_subject(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._subject_id
        subject = await self._execute("get_subject", self._subject_id)
        if subject is None:
            return self.async_abort(reason="no_subjects")
        quirks = await self._execute("quirks", subject.id, False)

        if user_input is not None:
            subject.label = user_input["label"]
            subject.make = user_input.get("make") or None
            subject.model = user_input.get("model") or None
            subject.aliases = [
                alias.strip() for alias in user_input.get("aliases", "").split(",") if alias.strip()
            ]
            await self._execute("save_subject", subject)
            for quirk_id in user_input.get("retract", []):
                await self._execute("retract_quirk", quirk_id)
            if user_input.get("retire"):
                await self._execute("retire_subject", subject.id, None)
            return self.async_create_entry(data=dict(self.config_entry.options))

        schema: dict[Any, Any] = {
            vol.Required("label", default=subject.label): selector.TextSelector(),
            vol.Optional(
                "make", description={"suggested_value": subject.make}
            ): selector.TextSelector(),
            vol.Optional(
                "model", description={"suggested_value": subject.model}
            ): selector.TextSelector(),
            vol.Optional(
                "aliases", description={"suggested_value": ", ".join(subject.aliases)}
            ): selector.TextSelector(),
        }
        if quirks:
            # Quirks appear with their source and age, so a wrong one can go.
            schema[vol.Optional("retract", default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=quirk.id,
                            label=_quirk_label(quirk),
                        )
                        for quirk in quirks
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        schema[vol.Optional("retire", default=False)] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="subject",
            data_schema=vol.Schema(schema),
            description_placeholders={"subject": subject.described},
        )

    # Runs --------------------------------------------------------------
    async def async_step_runs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A way out of a stuck run, without shame about it."""
        runs = await self._execute("open_runs", None, None)
        if not runs:
            return self.async_abort(reason="no_runs")
        if user_input is not None:
            engine = self.config_entry.runtime_data.engine
            await self.hass.async_add_executor_job(
                lambda: engine.run_finish(run_id=user_input["run_id"], abandoned=True)
            )
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="runs",
            data_schema=vol.Schema(
                {
                    vol.Required("run_id"): _choice(
                        [
                            (
                                run.id,
                                f"{run.reference} — step {run.current_step}, "
                                f"{say_elapsed(elapsed_seconds(run.updated_at))}",
                            )
                            for run in runs
                        ]
                    )
                }
            ),
        )
