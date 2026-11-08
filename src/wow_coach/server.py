"""The ``wow-coach`` MCP server: lets Claude read the CoachLink data over stdio.

The file is split in two layers:

* ``answer_*`` functions do the work (find file, load, format) and return plain text.
  They take ``wow_dir`` and ``now`` as arguments, so tests can call them directly.
* ``build_server`` wraps them in thin MCP tools. The tool docstrings are what
  Claude reads when deciding which tool to call.

Important: stdout is the MCP channel, so logging goes to stderr only.
"""

import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from wow_coach.config import config_path
from wow_coach.errors import WowCoachError
from wow_coach.gamedir import resolve_game_folder
from wow_coach.notes import (
    PLAYER_NOTES_MISSING,
    journal_goal,
    journal_missing_message,
    journal_path,
    notes_path,
    read_notes,
    save_notes,
)
from wow_coach.report import format_age, format_history, format_progress, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters
from wow_coach.web import Fetch, PoliteFetcher, build_user_agent
from wow_coach.wiki import (
    DEFAULT_MAX_CHARS,
    answer_find_quest,
    answer_read_wiki_page,
    answer_search_wiki,
)

SERVER_NAME = "wow-coach"
SERVER_INSTRUCTIONS = (
    "Coach the player of World of Warcraft: Forever. The player may have several "
    "characters, and each has its own memory: start by calling list_characters and let the "
    "player choose one. Then read it with character_status, progress_summary and "
    "read_coach_notes (the player notes plus that character's journal), and pass the "
    "character's name to every tool. Update the journal with save_coach_notes (one per "
    "character) and the shared player notes with save_player_notes when you learn "
    "something worth remembering. For game facts (where "
    "an NPC is, what a vendor sells, who gives a quest, what it rewards) use read_wiki_page, "
    "or search_wiki to find the right page first, and cite the page link. Look quests up "
    "with find_quest and the quest ID from character_status, not by title."
)

logger = logging.getLogger(__name__)


def _snapshot_time(character: Character) -> float:
    """When the character's snapshot was saved (0 if unknown)."""
    saved_at = character.snapshot.get("savedAt")
    return float(saved_at) if isinstance(saved_at, (int, float)) else 0.0


def pick_character(characters: dict[str, Character], wanted: str | None) -> Character | None:
    """Choose a character: the newest snapshot by default, else a case-insensitive match.

    ``wanted`` may be the bare name (``Testchar``) or the full key (``Testchar-Testrealm``).
    Returns None when nothing matches.
    """
    if not characters:
        return None
    if wanted is None:
        return max(characters.values(), key=_snapshot_time)
    wanted_lower = wanted.strip().lower()
    for character in characters.values():
        bare_name = character.key.split("-", 1)[0]
        if wanted_lower in (character.key.lower(), bare_name.lower()):
            return character
    return None


def _load_all(wow_dir: Path) -> dict[str, Character] | str:
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


def _unknown_character_message(wanted: str | None, characters: dict[str, Character]) -> str:
    if not characters:
        return "The CoachLink file contains no characters yet. Type /coach in game."
    return f"No character matches {wanted!r}. Known characters: {_known_names(characters)}"


def _character_description(character: Character, now: float, journal_file: Path) -> str:
    """One line: ``Name-Realm: level 8 Undead Mage, Zone, last played 5 min ago, goal: ...``."""
    snap = character.snapshot
    saved_at = _snapshot_time(character)
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
    newest_first = sorted(characters.values(), key=_snapshot_time, reverse=True)
    return "\n".join(
        _character_description(character, now, journal_path(character.key, environ=environ))
        for character in newest_first
    )


def answer_list_characters(wow_dir: Path, now: float, environ: Mapping[str, str]) -> str:
    """Text for the ``list_characters`` tool: most recently played first."""
    loaded = _load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    if not loaded:
        return "The CoachLink file contains no characters yet. Type /coach in game."
    return format_character_list(loaded, now, environ)


def answer_character_status(wow_dir: Path, character: str | None, now: float) -> str:
    """Text for the ``character_status`` tool."""
    loaded = _load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return _unknown_character_message(character, loaded)
    return format_status(chosen.snapshot, now=now)


def answer_recent_history(wow_dir: Path, character: str | None, limit: int, now: float) -> str:
    """Text for the ``recent_history`` tool."""
    loaded = _load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return _unknown_character_message(character, loaded)
    return format_history(chosen.history, limit=max(limit, 1), now=now)


def answer_progress_summary(wow_dir: Path, character: str | None, days: int, now: float) -> str:
    """Text for the ``progress_summary`` tool."""
    loaded = _load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    chosen = pick_character(loaded, character)
    if chosen is None:
        return _unknown_character_message(character, loaded)
    return format_progress(chosen.progress, chosen.history, days=days, now=now)


def _read_file_or_explain(path: Path, missing_message: str) -> str:
    """The file's text, the missing message, or a sentence about why it can't be read."""
    try:
        return read_notes(path, missing_message=missing_message)
    except OSError as error:
        return f"Could not read {path}: {error}"


def answer_read_notes(player_file: Path, journal_file: Path | None, character_key: str) -> str:
    """Text for the ``read_coach_notes`` tool: the player notes, then the character journal.

    ``journal_file`` is None when the character could not be found; ``character_key`` then
    holds the explanation instead of a name.
    """
    player = _read_file_or_explain(player_file, PLAYER_NOTES_MISSING)
    if journal_file is None:
        journal = character_key
        heading = "# Character journal"
    else:
        journal = _read_file_or_explain(journal_file, journal_missing_message(character_key))
        heading = f"# Character journal: {character_key}"
    return f"# Player notes (shared by all characters)\n\n{player}\n\n---\n\n{heading}\n\n{journal}"


def answer_save_notes(notes_file: Path, text: str, what: str) -> str:
    """Text for the two save tools (errors become messages the AI can act on).

    ``what`` names the kind of notes in the confirmation, for example ``"journal"``.
    """
    try:
        return save_notes(notes_file, text, what=what)
    except WowCoachError as error:
        return str(error)
    except OSError as error:
        return f"Could not save the {what} to {notes_file}: {error}"


def build_server(
    wow_dir_flag: Path | None = None,
    environ: Mapping[str, str] | None = None,
    fetch: Fetch | None = None,
) -> MCPServer:
    """Create the MCP server and register its tools.

    The game folder is looked up on every call (not once at start-up), so the server keeps
    working if the game is installed or the environment is fixed while the AI app is open.

    Args:
        wow_dir_flag: The ``--wow-dir`` value, or None to use the variable or auto-detect.
        environ: Environment variables (default: the real ones).
        fetch: How web pages are downloaded (default: a polite fetcher with a cache). Tests
            pass a fake one so they never use the network.
    """
    env = os.environ if environ is None else environ
    download = PoliteFetcher(build_user_agent()) if fetch is None else fetch
    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    writes_notes = ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )

    def game_folder() -> Path | str:
        """The game folder, or the sentence that says why it can't be found."""
        try:
            return resolve_game_folder(
                wow_dir_flag, environ=env, config_file=config_path(environ=env)
            ).path
        except WowCoachError as error:
            return str(error)

    def with_game_folder(answer: Callable[[Path], str]) -> str:
        """Run ``answer`` with the game folder, or return why it can't be found."""
        folder = game_folder()
        return folder if isinstance(folder, str) else answer(folder)

    def find_character(wanted: str | None) -> Character | str:
        """The chosen character (default: most recently saved), or why none was found."""
        folder = game_folder()
        if isinstance(folder, str):
            return folder
        loaded = _load_all(folder)
        if isinstance(loaded, str):
            return loaded
        chosen = pick_character(loaded, wanted)
        return chosen if chosen is not None else _unknown_character_message(wanted, loaded)

    @server.tool(annotations=read_only)
    def list_characters() -> str:
        """List the player's WoW characters, most recently played first, to choose from.

        Use this at the start of every coaching session, before anything else, so the
        player can choose which character to coach (or start a new one). Each line shows
        name-realm, level, race, class, zone, how long ago it was last played and the
        goal from that character's journal (or "no journal yet").
        """
        return with_game_folder(lambda folder: answer_list_characters(folder, time.time(), env))

    @server.tool(annotations=read_only)
    def character_status(character: str | None = None) -> str:
        """Get the full current status of a WoW character as Markdown.

        Use this whenever the player asks what to do next, what to upgrade, or about
        their quests, talents, gear, items, gold or location. It covers everything the
        addon saves: level, XP, gold, play time, location, stats, buffs, quests (with
        who to hand them in to), talents, professions and recipes, worn gear, every
        item in the bags, bank and mail, spells, action bars, reputations, currencies,
        the Legacy system, group, pet and mounts. Check the "saved ... ago" line: data
        is only as fresh as the last logout, /reload or /coach, and may be stale. The
        bank, mail and recipes are as fresh as their "seen ... ago" line.

        Args:
            character: Character name ("Testchar") or "Name-Realm", case-insensitive.
                Leave empty for the most recently saved character.
        """
        return with_game_folder(
            lambda folder: answer_character_status(folder, character, time.time())
        )

    @server.tool(annotations=read_only)
    def recent_history(character: str | None = None, limit: int = 20) -> str:
        """Get a character's recent events (level-ups, deaths, quests), newest first.

        Use this to see what the player has been doing lately, for example to explain
        a death or to track progress between coaching sessions.

        Args:
            character: Character name or "Name-Realm", case-insensitive.
                Leave empty for the most recently saved character.
            limit: Maximum number of events to return (default 20).
        """
        return with_game_folder(
            lambda folder: answer_recent_history(folder, character, limit, time.time())
        )

    @server.tool(annotations=read_only)
    def progress_summary(character: str | None = None, days: int = 7) -> str:
        """Summarize how a character has progressed lately, in plain words.

        Use this at the start of a session and whenever the player asks how they are
        doing: it shows when and where they last played, the play sessions of the last
        days, levels, XP, gold, quests and deaths, and what changed since the previous
        session. Compare it with the plan in the character's journal.

        Args:
            character: Character name or "Name-Realm", case-insensitive.
                Leave empty for the most recently saved character.
            days: How many days back to look (default 7).
        """
        return with_game_folder(
            lambda folder: answer_progress_summary(folder, character, days, time.time())
        )

    @server.tool(annotations=read_only)
    def read_coach_notes(character: str | None = None) -> str:
        """Read the coach's memory: the player notes plus one character's journal.

        Use this at the start of a coaching session, before giving advice, so you
        remember the player's preferences, this character's goals, choices, lessons
        already taught and what to do next. Both parts come back with clear headings. If
        the character has no journal yet, the answer says so: ask for their goal and create
        it with save_coach_notes.

        Args:
            character: Character name or "Name-Realm", case-insensitive.
                Leave empty for the most recently saved character.
        """
        found = find_character(character)
        if isinstance(found, str):
            return answer_read_notes(notes_path(environ=env), None, found)
        return answer_read_notes(
            notes_path(environ=env), journal_path(found.key, environ=env), found.key
        )

    @server.tool(annotations=writes_notes)
    def save_coach_notes(text: str, character: str | None = None) -> str:
        """Save a character's journal, replacing everything saved in it before.

        Use this when you learn something worth remembering about THIS character: its
        spec and professions, goals and plans, progress, what you taught and what to do
        next. Because it replaces the whole journal, call read_coach_notes first and send
        the full updated text (Markdown, under 100 KB). Things about the player in general
        (not this character) belong in save_player_notes.

        Args:
            text: The complete new content of the journal.
            character: Character name or "Name-Realm", case-insensitive.
                Leave empty for the most recently saved character.
        """
        found = find_character(character)
        if isinstance(found, str):
            return found
        return answer_save_notes(journal_path(found.key, environ=env), text, "journal")

    @server.tool(annotations=writes_notes)
    def save_player_notes(text: str) -> str:
        """Save the player notes shared by all characters, replacing what was saved before.

        Use this when you learn how the player likes to be coached (detail level,
        click-by-click steps, Questie or not, solo or group, computer details). Because it
        replaces everything, call read_coach_notes first and send the full updated text
        (Markdown, under 100 KB). Notes about one character belong in save_coach_notes.

        Args:
            text: The complete new content of the player notes.
        """
        return answer_save_notes(notes_path(environ=env), text, "player notes")

    # These tools reach out to a website, so unlike the others they are "open world".
    web_lookup = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

    @server.tool(annotations=web_lookup)
    def search_wiki(query: str, limit: int = 5) -> str:
        """Search the Warcraft Wiki and get matching page titles, one-line snippets and links.

        Use this when you do not know the exact page name, for example "trade supplies
        Brill" or "Camping 101". Then call read_wiki_page with the title you want. The
        wiki has pages for Forever-only content too. Always cite the link you used.

        Args:
            query: What to look for, in plain words.
            limit: How many results to return (1 to 10, default 5).
        """
        return answer_search_wiki(query, limit, download)

    @server.tool(annotations=web_lookup)
    def read_wiki_page(
        title: str, section: str | None = None, max_chars: int = DEFAULT_MAX_CHARS
    ) -> str:
        """Read a Warcraft Wiki page as plain text, with its key facts listed first.

        Use this for NPC locations and coordinates, vendor stock and prices, quest
        givers and rewards, items, zones and game terms. Text is labelled when it only
        applies to Classic, Retail or Forever; Forever-only info is marked, and Forever
        is the game being played, so prefer it. Redirects are followed. If you do not
        know the exact title, call search_wiki first. Always cite the page link.

        Args:
            title: The page title, for example "Abigail Shiel" or "Camping 101: Cooking".
            section: Only return this section, for example "Sells" or "Rewards". Long
                pages list their section names so you can ask for one.
            max_chars: Longest answer to return (default 6000).
        """
        return answer_read_wiki_page(title, section, max_chars, download)

    @server.tool(annotations=web_lookup)
    def find_quest(quest_id: int) -> str:
        """Find the Warcraft Wiki page of a quest from its quest ID.

        Use this instead of searching the quest title: Forever reuses Classic quests (same
        ID), and a title search often finds the Retail page, which has other NPCs and
        rewards. character_status shows each quest as "(quest 365)". Then call
        read_wiki_page with the title it returns. If several pages are listed, read the
        one for Classic or Forever. Always cite the link you used.

        Args:
            quest_id: The quest ID, for example 365.
        """
        return answer_find_quest(quest_id, download)

    return server


def main(wow_dir_flag: Path | None = None) -> None:
    """Entry point: run the server over stdio."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    build_server(wow_dir_flag).run(transport="stdio")
