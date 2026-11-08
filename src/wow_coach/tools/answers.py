"""The ``answer_*`` functions: the real work behind every coach tool, returning plain text.

Two callers share them, so the two can never drift apart:

* the MCP server (``wow_coach.server``), for Claude Code and other AI apps;
* wow-coach's own tool registry (``wow_coach.tools.registry``), for its built-in coach.

They take ``wow_dir`` and ``now`` as arguments, so tests can call them directly. They never
raise for expected problems (missing file, unknown character): they return a sentence the
AI can act on.
"""

import logging
from collections.abc import Mapping
from pathlib import Path

from wow_coach.characters import pick_character, snapshot_time
from wow_coach.engine.notes_digest import is_private, split_sections, without_private_sections
from wow_coach.errors import WowCoachError
from wow_coach.notes import (
    PLAYER_NOTES_MISSING,
    journal_goal,
    journal_missing_message,
    journal_path,
    read_notes,
    save_notes,
)
from wow_coach.report import format_age, format_history, format_progress, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters

logger = logging.getLogger(__name__)


def load_all(wow_dir: Path) -> dict[str, Character] | str:
    """Load every character, or return a friendly error message instead."""
    try:
        return load_characters(find_saved_variables(wow_dir))
    except WowCoachError as error:
        logger.warning("Could not load CoachLink data: %s", error)
        return str(error)
    except OSError as error:
        logger.warning("Could not read CoachLink data: %s", error)
        return f"Could not read the CoachLink file: {error}"


def _known_names(characters: dict[str, Character]) -> str:
    return ", ".join(sorted(characters)) or "(none)"


def unknown_character_message(wanted: str | None, characters: dict[str, Character]) -> str:
    """The sentence for "that character does not exist"."""
    if not characters:
        return "The CoachLink file contains no characters yet. Type /coach in game."
    return f"No character matches {wanted!r}. Known characters: {_known_names(characters)}"


def _character_description(character: Character, now: float, journal_file: Path) -> str:
    """One line: ``Name-Realm: level 8 Undead Mage, Zone, last played 5 min ago, goal: ...``."""
    snap = character.snapshot
    saved_at = snapshot_time(character)
    age = format_age(now - saved_at) if saved_at else "at an unknown time"
    kind = " ".join(str(snap[key]) for key in ("race", "class") if key in snap)
    if journal_file.is_file():
        goal = journal_goal(journal_file)
        journal = f"goal: {goal}" if goal else "journal has no goal yet"
    else:
        journal = "no journal yet"
    return (
        f"- {character.key}: level {snap.get('level', '?')} {kind or '?'}, "
        f"{snap.get('zone', 'unknown zone')}, last played {age}, {journal}"
    )


def format_character_list(
    characters: dict[str, Character], now: float, environ: Mapping[str, str]
) -> str:
    """One line per character, most recently played first (empty text if there are none)."""
    newest_first = sorted(characters.values(), key=snapshot_time, reverse=True)
    return "\n".join(
        _character_description(character, now, journal_path(character.key, environ=environ))
        for character in newest_first
    )


def answer_list_characters(wow_dir: Path, now: float, environ: Mapping[str, str]) -> str:
    """Text for the ``list_characters`` tool: most recently played first."""
    loaded = load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    if not loaded:
        return "The CoachLink file contains no characters yet. Type /coach in game."
    return format_character_list(loaded, now, environ)


def answer_character_status(wow_dir: Path, character: str | None, now: float) -> str:
    """Text for the ``character_status`` tool."""
    loaded = load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return unknown_character_message(character, loaded)
    return format_status(chosen.snapshot, now=now)


def answer_recent_history(wow_dir: Path, character: str | None, limit: int, now: float) -> str:
    """Text for the ``recent_history`` tool."""
    loaded = load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return unknown_character_message(character, loaded)
    return format_history(chosen.history, limit=max(limit, 1), now=now)


def answer_progress_summary(wow_dir: Path, character: str | None, days: int, now: float) -> str:
    """Text for the ``progress_summary`` tool."""
    loaded = load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return unknown_character_message(character, loaded)
    return format_progress(chosen.progress, chosen.history, days=days, now=now)


def _read_file_or_explain(path: Path, missing_message: str) -> str:
    """The file's text, the missing message, or a sentence about why it can't be read."""
    try:
        return read_notes(path, missing_message=missing_message)
    except OSError as error:
        return f"Could not read {path}: {error}"


def answer_read_notes(
    player_file: Path,
    journal_file: Path | None,
    character_key: str,
    *,
    hide_private: bool = False,
) -> str:
    """Text for the ``read_coach_notes`` tool: the player notes, then the character journal.

    With ``hide_private`` the sections about the player's computer are left out (the built-in
    coach sends what it reads to the AI, and those sections stay on this computer).

    ``journal_file`` is None when the character could not be found; ``character_key`` then
    holds the explanation instead of a name.
    """
    player = _read_file_or_explain(player_file, PLAYER_NOTES_MISSING)
    if hide_private:
        player = without_private_sections(player)
    if journal_file is None:
        journal = character_key
        heading = "# Character journal"
    else:
        journal = _read_file_or_explain(journal_file, journal_missing_message(character_key))
        if hide_private:
            journal = without_private_sections(journal)
        heading = f"# Character journal: {character_key}"
    return f"# Player notes (shared by all characters)\n\n{player}\n\n---\n\n{heading}\n\n{journal}"


def _with_private_sections_back(notes_file: Path, text: str) -> str:
    """``text`` plus the saved file's computer sections that ``text`` does not have itself.

    The AI never saw those sections (see ``answer_read_notes``), so its text lacks them;
    saving must not erase them.
    """
    try:
        old = notes_file.read_text(encoding="utf-8") if notes_file.is_file() else ""
    except OSError:
        return text
    have = {section.heading for section in split_sections(text) if is_private(section)}
    missing = [s for s in split_sections(old) if is_private(s) and s.heading not in have]
    return "\n\n".join([text.rstrip(), *(s.text for s in missing)]) + "\n" if missing else text


def answer_save_notes(notes_file: Path, text: str, what: str, *, keep_private: bool = False) -> str:
    """Text for the two save tools (errors become messages the AI can act on).

    ``what`` names the kind of notes in the confirmation, for example ``"journal"``.
    The file being replaced is first kept in a ``.history`` folder (see ``notes.save_notes``).
    With ``keep_private`` the file's sections about the player's computer are kept.
    """
    try:
        if keep_private:
            text = _with_private_sections_back(notes_file, text)
        return save_notes(notes_file, text, what=what)
    except WowCoachError as error:
        return str(error)
    except OSError as error:
        return f"Could not save the {what} to {notes_file}: {error}"
