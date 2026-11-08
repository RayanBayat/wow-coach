"""The companion's settings: what the player chose in the coach window (0.9.0+).

Kept as a small JSON file, ``settings.json``, in wow-coach's data folder. It holds no
secrets: the ChatGPT sign-in lives in the system keychain (``keychain.py``). A damaged or
partial file never stops the program: missing or wrong values fall back to the defaults.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Final

from wow_coach.datafolder import data_folder
from wow_coach.triggers.contract import TriggerSettings
from wow_coach.triggers.settings import trigger_settings_from_dict, trigger_settings_to_dict

SETTINGS_FILE_NAME: Final = "settings.json"
MAX_SETTINGS_BYTES: Final = 64_000
# Caps that protect the player's ChatGPT plan. The window lets them change these.
MIN_CALLS: Final = 0
MAX_CALLS_PER_HOUR_LIMIT: Final = 200
MAX_CALLS_PER_DAY_LIMIT: Final = 2000
MAX_MODEL_CHARS: Final = 80


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Everything the player can change in the coach window."""

    # The model on the ChatGPT plan to use; None = pick a small, fast one by itself.
    model: str | None = None
    # Answer questions asked in the game's Coach panel as soon as the game saves them.
    answer_questions_from_game: bool = True
    # Show a desktop notification when an answer is ready.
    notify: bool = True
    # Read answers aloud (off by default: not everyone wants a talking PC).
    speak: bool = False
    # Never use more of the plan than this.
    max_calls_per_hour: int = 20
    max_calls_per_day: int = 100
    # Send other players' names (group members, mail senders, killers) to the AI. Off:
    # they are replaced with "a player" before anything leaves the PC.
    share_other_player_names: bool = False
    # Send the coach's notes (player notes and the character's journal) with each question.
    # They make answers fit the player, but they can hold personal notes, so it is a choice.
    send_coach_notes: bool = True
    # When the coach speaks up by itself (deaths, level-ups, a timer...). Manual by default.
    triggers: TriggerSettings = field(default_factory=TriggerSettings)


DEFAULTS: Final = AppSettings()


def settings_path(*, environ: Mapping[str, str]) -> Path:
    """Where the settings file lives."""
    return data_folder(environ=environ) / SETTINGS_FILE_NAME


def _clean_model(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    ok = 0 < len(value) <= MAX_MODEL_CHARS and all(c.isalnum() or c in "-._" for c in value)
    return value if ok else None


def _clean_count(value: object, default: int, limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, MIN_CALLS), limit)


def _clean_flag(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def settings_from_dict(data: Mapping[str, object]) -> AppSettings:
    """Build settings from loose data (a file, or a form in the window), fixing bad values."""
    return AppSettings(
        model=_clean_model(data.get("model")),
        answer_questions_from_game=_clean_flag(
            data.get("answer_questions_from_game"), DEFAULTS.answer_questions_from_game
        ),
        notify=_clean_flag(data.get("notify"), DEFAULTS.notify),
        speak=_clean_flag(data.get("speak"), DEFAULTS.speak),
        max_calls_per_hour=_clean_count(
            data.get("max_calls_per_hour"), DEFAULTS.max_calls_per_hour, MAX_CALLS_PER_HOUR_LIMIT
        ),
        max_calls_per_day=_clean_count(
            data.get("max_calls_per_day"), DEFAULTS.max_calls_per_day, MAX_CALLS_PER_DAY_LIMIT
        ),
        share_other_player_names=_clean_flag(
            data.get("share_other_player_names"), DEFAULTS.share_other_player_names
        ),
        send_coach_notes=_clean_flag(data.get("send_coach_notes"), DEFAULTS.send_coach_notes),
        triggers=trigger_settings_from_dict(data.get("triggers")),
    )


def settings_to_dict(settings: AppSettings) -> dict[str, object]:
    """The settings as plain JSON-ready data (also what the coach window shows)."""
    data = asdict(settings)
    data["triggers"] = trigger_settings_to_dict(settings.triggers)
    return data


def load_settings(path: Path) -> AppSettings:
    """Read the settings file; anything missing, damaged or wrong gives the defaults."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_SETTINGS_BYTES:
            return DEFAULTS
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, RecursionError:
        return DEFAULTS
    return settings_from_dict(data) if isinstance(data, dict) else DEFAULTS


def save_settings(path: Path, settings: AppSettings) -> None:
    """Write the settings file in one step (a temp file, then a rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(settings_to_dict(settings), indent=2, sort_keys=True) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def update_settings(settings: AppSettings, changes: Mapping[str, object]) -> AppSettings:
    """``settings`` with ``changes`` applied (unknown names ignored, bad values refused).

    ``changes["triggers"]`` may hold only some trigger fields; the others stay as they were.
    """
    simple = {item.name for item in fields(AppSettings)} - {"triggers"}
    merged = {**settings_to_dict(settings), **{k: v for k, v in changes.items() if k in simple}}
    cleaned = settings_from_dict(merged)
    # A bad value in `changes` falls back to the default; keep the old value instead.
    kept: dict[str, object] = {
        name: getattr(settings, name)
        for name in simple
        if name in changes and getattr(cleaned, name) != changes[name]
    }
    trigger_changes = changes.get("triggers")
    if isinstance(trigger_changes, Mapping):
        old = trigger_settings_to_dict(settings.triggers)
        kept["triggers"] = trigger_settings_from_dict({**old, **trigger_changes})
    else:
        kept["triggers"] = settings.triggers
    return replace(cleaned, **kept)  # type: ignore[arg-type]  # values come from the dataclass
