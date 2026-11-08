"""What the trigger rules remember between runs: ``triggers-state.json`` in the data folder.

It holds only times (no secrets): when the coach last answered something the player did
not ask, per character, and when the timer last ran. A damaged file means "nothing
remembered", which at worst allows one extra answer.
"""

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from wow_coach.datafolder import data_folder
from wow_coach.triggers.contract import Decision

STATE_FILE_NAME: Final = "triggers-state.json"
MAX_STATE_BYTES: Final = 64_000
MAX_CHARACTERS: Final = 100  # keeps the file small however many characters come and go
MAX_KEY_CHARS: Final = 120


@dataclass(frozen=True, slots=True)
class TriggerState:
    """Times, in Unix seconds. 0 means never."""

    last_coach_at: Mapping[str, int] = field(default_factory=dict)  # "Name-Realm" -> time
    last_timer_at: int = 0


def state_path(*, environ: Mapping[str, str]) -> Path:
    """Where the state file lives."""
    return data_folder(environ=environ) / STATE_FILE_NAME


def _time(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _clean_times(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    cleaned = {}
    for key, raw in value.items():
        time = _time(raw)
        if isinstance(key, str) and 0 < len(key) <= MAX_KEY_CHARS and time is not None:
            cleaned[key] = time
    newest = sorted(cleaned.items(), key=lambda pair: pair[1], reverse=True)[:MAX_CHARACTERS]
    return dict(newest)


def state_from_dict(data: object) -> TriggerState:
    """Build the state from loose data, ignoring anything wrong."""
    if not isinstance(data, Mapping):
        return TriggerState()
    return TriggerState(
        last_coach_at=_clean_times(data.get("last_coach_at")),
        last_timer_at=_time(data.get("last_timer_at")) or 0,
    )


def load_state(path: Path) -> TriggerState:
    """Read the state file; anything missing or damaged gives an empty state."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
            return TriggerState()
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, RecursionError:
        return TriggerState()
    return state_from_dict(data)


def save_state(path: Path, state: TriggerState) -> None:
    """Write the state in one step (a temp file, then a rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"last_coach_at": dict(state.last_coach_at), "last_timer_at": state.last_timer_at}
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".triggers-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def record_decisions(
    state: TriggerState, decisions: Iterable[Decision], *, now: int
) -> TriggerState:
    """The state after these decisions were carried out.

    An unasked "coach" decision starts that character's cooldown. A timer decision that
    was not switched off restarts the timer. Questions the player asked change nothing.
    """
    coach_at = dict(state.last_coach_at)
    timer_at = state.last_timer_at
    for decision in decisions:
        kind = decision.event.kind
        if kind == "timer" and decision.action != "off":
            timer_at = now
        if kind != "asked" and decision.action == "coach":
            coach_at[decision.event.character_key] = now
    return replace(state, last_coach_at=_clean_times(coach_at), last_timer_at=timer_at)
