"""Clean the player's trigger rules (``triggers`` in settings.json).

Anything missing, of the wrong type or out of range falls back to the default or is
clamped, so a damaged or hand-edited file can never break the app.
"""

import math
import re
from collections.abc import Mapping
from typing import Final

from wow_coach.triggers.contract import EVENT_KINDS, MODES, EventKind, Mode, TriggerSettings

MAX_COOLDOWN_MINUTES: Final = 240
MIN_TIMER_MINUTES: Final = 5
MAX_TIMER_MINUTES: Final = 240
MAX_RULES_CHARS: Final = 500
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")
DEFAULTS: Final = TriggerSettings()


def _whole_number(value: object) -> int | None:
    """An int (or a float with a whole value) but never a bool, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _clean_mode(value: object, default: Mode) -> Mode:
    for mode in MODES:
        if value == mode:
            return mode
    return default


def _clean_modes(value: object) -> dict[EventKind, Mode]:
    modes = dict(DEFAULTS.modes)
    if isinstance(value, Mapping):
        for kind in EVENT_KINDS:
            modes[kind] = _clean_mode(value.get(kind), modes[kind])
    modes["asked"] = "coach"  # the player asked, so it is always answered
    return modes


def _clean_cooldown(value: object) -> int:
    number = _whole_number(value)
    if number is None:
        return DEFAULTS.cooldown_minutes
    return min(max(number, 0), MAX_COOLDOWN_MINUTES)


def _clean_hour(value: object) -> int | None:
    number = _whole_number(value)
    return number if number is not None and 0 <= number <= 23 else None


def _clean_timer(value: object) -> int:
    number = _whole_number(value)
    if number is None or number <= 0:
        return 0
    return min(max(number, MIN_TIMER_MINUTES), MAX_TIMER_MINUTES)


def _clean_flag(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _clean_rules(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_CHARS.sub(" ", value).strip()[:MAX_RULES_CHARS]


def trigger_settings_from_dict(data: object) -> TriggerSettings:
    """Build the rules from loose data (a file, or the settings form), fixing bad values."""
    if not isinstance(data, Mapping):
        return DEFAULTS
    return TriggerSettings(
        modes=_clean_modes(data.get("modes")),
        cooldown_minutes=_clean_cooldown(data.get("cooldown_minutes")),
        quiet_in_instances=_clean_flag(data.get("quiet_in_instances"), DEFAULTS.quiet_in_instances),
        quiet_from_hour=_clean_hour(data.get("quiet_from_hour")),
        quiet_to_hour=_clean_hour(data.get("quiet_to_hour")),
        every_minutes=_clean_timer(data.get("every_minutes")),
        use_triage=_clean_flag(data.get("use_triage"), DEFAULTS.use_triage),
        rules_text=_clean_rules(data.get("rules_text")),
    )


def trigger_settings_to_dict(settings: TriggerSettings) -> dict[str, object]:
    """Plain data for settings.json (JSON-safe)."""
    return {
        "modes": dict(settings.modes),
        "cooldown_minutes": settings.cooldown_minutes,
        "quiet_in_instances": settings.quiet_in_instances,
        "quiet_from_hour": settings.quiet_from_hour,
        "quiet_to_hour": settings.quiet_to_hour,
        "every_minutes": settings.every_minutes,
        "use_triage": settings.use_triage,
        "rules_text": settings.rules_text,
    }
