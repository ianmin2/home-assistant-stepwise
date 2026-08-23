"""Constants for Stepwise.

Deliberately free of Home Assistant imports so the core is importable, and
testable, without a Home Assistant install.
"""

from __future__ import annotations

DOMAIN = "stepwise"

# Storage ---------------------------------------------------------------
DB_FILENAME = "stepwise.db"
SCHEMA_VERSION = 3

# Configuration keys ----------------------------------------------------
CONF_MEMORY_BACKEND = "memory_backend"
CONF_SEARCH_PROVIDER = "search_provider"
CONF_SEARCH_REST_COMMAND = "search_rest_command"
CONF_SEARCH_RESPONSE_PATH = "search_response_path"
CONF_SEARCH_BASE_URL = "search_base_url"
CONF_UNITS = "units"
CONF_CONFIRMATION_STYLE = "confirmation_style"
CONF_HOT_MINUTES = "hot_minutes"
CONF_COLD_HOURS = "cold_hours"
CONF_REFERENCE_NAMING = "reference_naming"
CONF_ARCHIVE_KEEP_PER_SUBJECT = "archive_keep_per_subject"

MEMORY_HA_AI_MEMORY = "ha_ai_memory"
MEMORY_BUILTIN = "builtin"

SEARCH_REST_COMMAND = "rest_command"
SEARCH_BUNDLED = "bundled"
SEARCH_NONE = "none"

UNITS_METRIC = "metric"
UNITS_IMPERIAL = "imperial"

CONFIRM_EXPLICIT = "explicit"  # wait for "done"
CONFIRM_ANY_SPEECH = "any_speech"

NAMING_PROPOSE = "propose"  # agent proposes, user may override
NAMING_ALWAYS_ASK = "always_ask"
NAMING_NEVER_ASK = "never_ask"

# Context stickiness. Section 6: both thresholds are configuration, never code.
DEFAULT_HOT_MINUTES = 30
DEFAULT_COLD_HOURS = 4
DEFAULT_ARCHIVE_KEEP_PER_SUBJECT = 20

DEFAULTS = {
    CONF_MEMORY_BACKEND: MEMORY_BUILTIN,
    CONF_SEARCH_PROVIDER: SEARCH_NONE,
    CONF_UNITS: UNITS_METRIC,
    CONF_CONFIRMATION_STYLE: CONFIRM_EXPLICIT,
    CONF_HOT_MINUTES: DEFAULT_HOT_MINUTES,
    CONF_COLD_HOURS: DEFAULT_COLD_HOURS,
    CONF_REFERENCE_NAMING: NAMING_PROPOSE,
    CONF_ARCHIVE_KEEP_PER_SUBJECT: DEFAULT_ARCHIVE_KEEP_PER_SUBJECT,
}

# Run stickiness --------------------------------------------------------
HOT = "hot"
WARM = "warm"
COLD = "cold"

# Subject status --------------------------------------------------------
SUBJECT_ACTIVE = "active"
SUBJECT_RETIRED = "retired"
SUBJECT_REPLACED = "replaced"

# Run status ------------------------------------------------------------
RUN_ACTIVE = "active"
RUN_PAUSED = "paused"
RUN_DONE = "done"
RUN_ABANDONED = "abandoned"

OPEN_RUN_STATUSES = (RUN_ACTIVE, RUN_PAUSED)

# Step await semantics --------------------------------------------------
AWAITS_NONE = "none"
AWAITS_CONFIRM = "confirm"
AWAITS_TIMER = "timer"

# run_events kinds. The append-only spine (section 10).
EVENT_RUN_STARTED = "run_started"
EVENT_ADVANCED = "advanced"
EVENT_REPOSITIONED = "repositioned"
EVENT_UNDONE = "undone"
EVENT_NOTE = "note"
EVENT_ASKED = "asked"
EVENT_CHALLENGED = "challenged"
EVENT_AMENDED = "amended"
EVENT_QUIRK_STATED = "quirk_stated"
EVENT_QUIRK_LEARNED = "quirk_learned"
EVENT_QUIRK_CONFIRMED = "quirk_confirmed"
EVENT_QUIRK_RETRACTED = "quirk_retracted"
EVENT_PAUSED = "paused"
EVENT_RESUMED = "resumed"
EVENT_FINISHED = "finished"
EVENT_TIMER_STARTED = "timer_started"

# Step settings that name a machine programme, so a subject that knows its own
# programmes can say which one this is and how long it takes.
SETTING_KEYS = ("programme", "program", "cycle", "mode", "setting")
ATTR_PROGRAMMES = "programmes"

# Quirks ----------------------------------------------------------------
LEARNED_FROM_USER = "user"
LEARNED_FROM_WEB = "web"
LEARNED_FROM_MANUAL = "manual"
LEARNED_FROM_OBSERVED = "observed"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

QUIRK_ACTIVE = "active"
QUIRK_SUPERSEDED = "superseded"
QUIRK_RETRACTED = "retracted"

# A material quirk that has not been confirmed for this long is re-confirmed
# out loud before it is relied on (section 9, rule 2).
QUIRK_STALE_DAYS = 180

# Amendment scope -------------------------------------------------------
SCOPE_RUN = "run"
SCOPE_SUBJECT = "subject"
SCOPE_PROCEDURE = "procedure"

# Procedure source ------------------------------------------------------
SOURCE_WEB = "web"
SOURCE_USER = "user"
SOURCE_GENERATED = "generated"
