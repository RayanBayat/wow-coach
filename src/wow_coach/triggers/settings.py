"""Clean the player's choices (``triggers`` in settings.json).

Anything missing, of the wrong type or out of range falls back to the default, so a damaged
or hand-edited file can never break the app.

Older files (before "When the game saves") held a mode per kind of event, a timer, quiet
hours, a cooldown and triage text. They still load: see ``_migrated_on_save``.
"""

from collections.abc import Mapping
from typing import Final

from wow_coach.triggers.contract import ON_SAVE_CHOICES, OnSave, TriggerSettings

DEFAULTS: Final = TriggerSettings()


def _clean_flag(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _migrated_on_save(old_modes: object) -> OnSave:
    """Turn the old per-event modes into the one new choice.

    Any event on "coach" gives "advice"; else any on "notify" gives "notify"; when
    everything was off (the old default) the new default applies.
    """
    if not isinstance(old_modes, Mapping):
        return DEFAULTS.on_save
    chosen = [mode for kind, mode in old_modes.items() if kind != "asked"]
    if "coach" in chosen:
        return "advice"
    if "notify" in chosen:
        return "notify"
    return DEFAULTS.on_save


def _clean_on_save(data: Mapping[object, object]) -> OnSave:
    value = data.get("on_save")
    for choice in ON_SAVE_CHOICES:
        if value == choice:
            return choice
    return _migrated_on_save(data.get("modes"))


def trigger_settings_from_dict(data: object) -> TriggerSettings:
    """Build the settings from loose data (a file, or the settings form), fixing bad values."""
    if not isinstance(data, Mapping):
        return DEFAULTS
    return TriggerSettings(
        on_save=_clean_on_save(data),
        quiet_in_instances=_clean_flag(data.get("quiet_in_instances"), DEFAULTS.quiet_in_instances),
    )


def trigger_settings_to_dict(settings: TriggerSettings) -> dict[str, object]:
    """Plain data for settings.json (JSON-safe)."""
    return {"on_save": settings.on_save, "quiet_in_instances": settings.quiet_in_instances}
