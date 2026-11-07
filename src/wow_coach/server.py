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
from wow_coach.notes import notes_path, read_notes, save_notes
from wow_coach.report import format_age, format_history, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters
from wow_coach.web import Fetch, PoliteFetcher, build_user_agent
from wow_coach.wiki import DEFAULT_MAX_CHARS, answer_read_wiki_page, answer_search_wiki

SERVER_NAME = "wow-coach"
SERVER_INSTRUCTIONS = (
    "Coach the player of World of Warcraft: Forever. Before coaching, read the character "
    "with character_status (use list_characters if unsure who is playing). Keep a "
    "notebook between sessions: read it with read_coach_notes at the start and update it "
    "with save_coach_notes when you learn something worth remembering. For game facts (where "
    "an NPC is, what a vendor sells, who gives a quest, what it rewards) use read_wiki_page, "
    "or search_wiki to find the right page first, and cite the page link."
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


def answer_list_characters(wow_dir: Path, now: float) -> str:
    """Text for the ``list_characters`` tool."""
    loaded = _load_all(wow_dir)
    if isinstance(loaded, str):
        return loaded
    if not loaded:
        return "The CoachLink file contains no characters yet. Type /coach in game."
    lines = []
    for character in sorted(loaded.values(), key=_snapshot_time, reverse=True):
        snap = character.snapshot
        saved_at = _snapshot_time(character)
        age = format_age(now - saved_at) if saved_at else "unknown time"
        lines.append(
            f"- {character.key}: level {snap.get('level', '?')} {snap.get('class', '?')}, "
            f"{snap.get('zone', 'unknown zone')}, saved {age}"
        )
    return "\n".join(lines)


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


def answer_read_notes(notes_file: Path) -> str:
    """Text for the ``read_coach_notes`` tool."""
    try:
        return read_notes(notes_file)
    except OSError as error:
        return f"Could not read the coach notes at {notes_file}: {error}"


def answer_save_notes(notes_file: Path, text: str) -> str:
    """Text for the ``save_coach_notes`` tool (errors become messages the AI can act on)."""
    try:
        return save_notes(notes_file, text)
    except WowCoachError as error:
        return str(error)
    except OSError as error:
        return f"Could not save the coach notes to {notes_file}: {error}"


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

    def with_game_folder(answer: Callable[[Path], str]) -> str:
        """Run ``answer`` with the game folder, or return why it can't be found."""
        try:
            folder = resolve_game_folder(
                wow_dir_flag, environ=env, config_file=config_path(environ=env)
            ).path
        except WowCoachError as error:
            return str(error)
        return answer(folder)

    @server.tool(annotations=read_only)
    def list_characters() -> str:
        """List the WoW characters the CoachLink addon has saved.

        Use this first when you do not know which characters exist, or to see how old
        each snapshot is. Shows level, class, zone and snapshot age per character.
        """
        return with_game_folder(lambda folder: answer_list_characters(folder, time.time()))

    @server.tool(annotations=read_only)
    def character_status(character: str | None = None) -> str:
        """Get the full current status of a WoW character as Markdown.

        Use this whenever the player asks what to do next, what to upgrade, or about
        their quests, talents, gear, gold or location. It covers level, XP, gold,
        location, bags, quests, talents, professions, gear and spells. Check the
        "saved ... ago" line: data is only as fresh as the last logout, /reload or
        /coach, and may be stale.

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
    def read_coach_notes() -> str:
        """Read the coach's notebook: what you saved about this player in earlier sessions.

        Use this at the start of a coaching session, before giving advice, so you
        remember the player's goals, lessons already taught and what to do next.
        """
        return answer_read_notes(notes_path(environ=env))

    @server.tool(annotations=writes_notes)
    def save_coach_notes(text: str) -> str:
        """Save the coach's notebook, replacing everything saved before.

        Use this when you learn something worth remembering: the player's goals, what
        you taught, what they should do next. Because it replaces the whole notebook,
        call read_coach_notes first and send the full updated text (Markdown, under 100 KB).

        Args:
            text: The complete new content of the notebook.
        """
        return answer_save_notes(notes_path(environ=env), text)

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

    return server


def main(wow_dir_flag: Path | None = None) -> None:
    """Entry point: run the server over stdio."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    build_server(wow_dir_flag).run(transport="stdio")
