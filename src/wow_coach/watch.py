"""``wow-coach watch``: print one line each time the HeroBridge addon saves.

An AI app can run this in the background; every printed line tells it "the player just
typed /coach (or logged out), go read the new snapshot".

How it notices: every 2 seconds it asks the operating system when each save file last
changed (a ``stat`` call). That is answered from memory, so polling never wakes up a slow
game hard disk. We never read the file until it has changed.
"""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from wow_coach.advice.paths import advice_file_path
from wow_coach.advice.questions import open_questions
from wow_coach.advice.reader import read_advice_file
from wow_coach.errors import WowCoachError
from wow_coach.report_values import looks_unloaded
from wow_coach.savedvars import Character, find_saved_variables, load_characters

POLL_SECONDS = 2
SETTLE_SECONDS = 1  # the game may still be writing right after the change time moves

type ChangeTimes = dict[Path, int]


def change_times(wow_dir: Path) -> ChangeTimes:
    """Last-changed time of every account's save file (empty until the first save).

    Both names count: HeroBridge.lua, and CoachLink.lua from before 0.11.0.
    """
    paths = [
        path
        for file_name in ("HeroBridge.lua", "CoachLink.lua")
        for path in wow_dir.glob(f"WTF/Account/*/SavedVariables/{file_name}")
    ]
    times: ChangeTimes = {}
    for path in paths:
        try:
            times[path] = path.stat().st_mtime_ns
        except OSError:
            continue  # the file vanished between listing and asking; try again next poll
    return times


def _saved_at(character: Character) -> float:
    value = character.snapshot.get("savedAt")
    return float(value) if isinstance(value, (int, float)) else 0.0


def describe_newest_snapshot(wow_dir: Path) -> str:
    """Say who just saved, e.g. ``Testchar level 8 (reason: coach)``.

    The game keeps one snapshot per character, so the largest ``savedAt`` is the one
    that was just written. Problems are returned as text, never raised: a half-written
    file must not stop the watcher.
    """
    try:
        characters = load_characters(find_saved_variables(wow_dir))
    except (WowCoachError, OSError) as error:
        first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
        return f"(could not read the snapshot: {first_line})"
    if not characters:
        return "(could not read the snapshot: the file has no characters yet)"
    newest = max(characters.values(), key=_saved_at)
    snapshot = newest.snapshot
    name, level, reason = (snapshot.get(key, "?") for key in ("name", "level", "reason"))
    extra = "; almost empty, type /coach" if looks_unloaded(snapshot) else ""
    if reason == "ask":
        extra += "; " + _open_questions_text(wow_dir, newest)
    return f"{name} level {level} (reason: {reason}{extra})"


def _open_questions_text(wow_dir: Path, character: Character) -> str:
    """``1 open question`` from the Coach panel (questions wow-coach hasn't answered yet)."""
    advice_file = advice_file_path(wow_dir)
    count = len(open_questions(character, read_advice_file(advice_file)))
    return f"{count} open question" + ("" if count == 1 else "s")


def _say(out: TextIO, text: str) -> None:
    """Write one line and flush it, so a program reading our output sees it immediately."""
    print(text, file=out, flush=True)


def watch(
    wow_dir: Path,
    *,
    out: TextIO,
    status: TextIO,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = datetime.now,
) -> None:
    """Watch forever; stop it with Ctrl+C (the caller handles ``KeyboardInterrupt``).

    Only save lines go to ``out``: a program such as Claude Code's Monitor treats every
    line there as an event to answer. The start line goes to ``status`` (standard error
    on the command line), so restarting the watcher is not an event.
    ``sleep`` and ``clock`` are arguments so tests can run this without real waiting.
    """
    last_seen = change_times(wow_dir)
    _say(status, f"watching for /coach saves (started {clock():%H:%M:%S})")
    while True:
        sleep(POLL_SECONDS)
        if change_times(wow_dir) == last_seen:
            continue
        sleep(SETTLE_SECONDS)
        last_seen = change_times(wow_dir)
        _say(out, f"HeroBridge saved at {clock():%H:%M:%S}: {describe_newest_snapshot(wow_dir)}")
