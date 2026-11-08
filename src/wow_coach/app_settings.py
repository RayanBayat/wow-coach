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
MAX_MODEL_CHARS: Final = 80
# The overlay (the coach as a see-through panel on top of the game): how solid it is, in
# percent, and the key that shows or hides it. Below 60 % the text is too hard to read.
MIN_OVERLAY_OPACITY: Final = 60
MAX_OVERLAY_OPACITY: Final = 100
DEFAULT_OVERLAY_OPACITY: Final = 92
# Ctrl+Shift+Space: WoW's default keys are mostly single keys, Shift+key and Ctrl+key, so
# this three-key chord does not clash (Space alone is "jump").
DEFAULT_OVERLAY_HOTKEY: Final = "Ctrl+Shift+Space"
# How big the desktop app is drawn, in percent of normal (Qt applies it when the app starts).
UI_SCALE_CHOICES: Final = (70, 80, 90, 100, 110, 120, 130)
DEFAULT_UI_SCALE: Final = 100
MAX_HOTKEY_CHARS: Final = 40


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Everything the player can change in the coach window."""

    # The model on the ChatGPT plan to use; None = pick a small, fast one by itself.
    model: str | None = None
    # Answer questions asked in the game's Coach panel as soon as the game saves them.
    answer_questions_from_game: bool = True
    # Show a desktop notification when an answer is ready.
    notify: bool = True
    # Send other players' names (group members, mail senders, killers) to the AI. Off:
    # they are replaced with "a player" before anything leaves the PC.
    share_other_player_names: bool = False
    # Send the coach's notes (player notes and the character's journal) with each question.
    # They make answers fit the player, but they can hold personal notes, so it is a choice.
    send_coach_notes: bool = True
    # Use the chats the player had with their Claude Code coach: show them in the window and
    # give them to the AI as part of the recent conversation.
    use_claude_chats: bool = True
    # Let the coach use tools while answering: read the character's status, history and
    # notes and look things up on the Warcraft Wiki.
    use_tools: bool = True
    # Let the coach also search the web (run by OpenAI as part of the ChatGPT plan).
    web_search: bool = True
    # Let the coach save the notebook (player notes and character journal). Off: it can
    # read them but not change them.
    save_notes: bool = True
    # Show what the coach looked up under its answers (and live while it works).
    show_lookups: bool = True
    # "When the game saves": what the coach tells you after a save (notes, optionally advice).
    triggers: TriggerSettings = field(default_factory=TriggerSettings)
    # The overlay panel's see-through level (60-100 %; 100 = solid).
    overlay_opacity: int = DEFAULT_OVERLAY_OPACITY
    # The key that shows or hides the overlay, in Qt's portable text ("Ctrl+Shift+Space").
    overlay_hotkey: str = DEFAULT_OVERLAY_HOTKEY
    # The desktop app's size, in percent: one of ``UI_SCALE_CHOICES``.
    ui_scale: int = DEFAULT_UI_SCALE


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


def _clean_flag(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _clean_opacity(value: object) -> int:
    """A whole number from 60 to 100, else the default (a bool is not a number)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_OVERLAY_OPACITY
    in_range = MIN_OVERLAY_OPACITY <= value <= MAX_OVERLAY_OPACITY
    return value if in_range else DEFAULT_OVERLAY_OPACITY


def _clean_scale(value: object) -> int:
    """One of the offered sizes (70 to 130 percent), else the normal size."""
    if isinstance(value, bool) or value not in UI_SCALE_CHOICES:
        return DEFAULT_UI_SCALE
    return int(value)  # checked against the whole-number choices above


def _clean_hotkey(value: object) -> str:
    """Key text such as "Ctrl+Shift+Space": plain printable characters, not too long."""
    if not isinstance(value, str):
        return DEFAULT_OVERLAY_HOTKEY
    value = value.strip()
    plain = value.isascii() and value.isprintable()
    return value if plain and 0 < len(value) <= MAX_HOTKEY_CHARS else DEFAULT_OVERLAY_HOTKEY


def settings_from_dict(data: Mapping[str, object]) -> AppSettings:
    """Build settings from loose data (a file, or a form in the window), fixing bad values."""
    return AppSettings(
        model=_clean_model(data.get("model")),
        answer_questions_from_game=_clean_flag(
            data.get("answer_questions_from_game"), DEFAULTS.answer_questions_from_game
        ),
        notify=_clean_flag(data.get("notify"), DEFAULTS.notify),
        share_other_player_names=_clean_flag(
            data.get("share_other_player_names"), DEFAULTS.share_other_player_names
        ),
        send_coach_notes=_clean_flag(data.get("send_coach_notes"), DEFAULTS.send_coach_notes),
        use_claude_chats=_clean_flag(data.get("use_claude_chats"), DEFAULTS.use_claude_chats),
        use_tools=_clean_flag(data.get("use_tools"), DEFAULTS.use_tools),
        web_search=_clean_flag(data.get("web_search"), DEFAULTS.web_search),
        save_notes=_clean_flag(data.get("save_notes"), DEFAULTS.save_notes),
        show_lookups=_clean_flag(data.get("show_lookups"), DEFAULTS.show_lookups),
        triggers=trigger_settings_from_dict(data.get("triggers")),
        overlay_opacity=_clean_opacity(data.get("overlay_opacity")),
        overlay_hotkey=_clean_hotkey(data.get("overlay_hotkey")),
        ui_scale=_clean_scale(data.get("ui_scale")),
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
