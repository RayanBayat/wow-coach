"""``build_coach_tools``: the tools wow-coach's own coach can use for one character.

Each tool is the same ability the MCP server offers under the same name, built on the same
``answer_*`` helpers, so Claude Code's coach and the built-in coach see the same things.
``tests/test_tools_registry.py`` compares the names and arguments of both so they cannot drift.

Differences from the MCP tools, on purpose:

* No ``character`` argument. The tools are built for one character, so the AI cannot wander
  to another player's journal.
* Not offered at all: ``list_characters`` (the app already knows the character),
  ``questions_from_game`` and ``send_advice_to_game`` (the app handles the in-game panel).
"""

import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from wow_coach.ai.base import ToolSpec
from wow_coach.notes import journal_path, notes_path
from wow_coach.tools.answers import (
    answer_character_status,
    answer_progress_summary,
    answer_read_notes,
    answer_recent_history,
    answer_save_notes,
)
from wow_coach.tools.base import CoachTool, ToolKind
from wow_coach.web import Fetch, PoliteFetcher, build_user_agent
from wow_coach.wiki import (
    DEFAULT_MAX_CHARS,
    MAX_SEARCH_RESULTS,
    answer_find_quest,
    answer_read_wiki_page,
    answer_search_wiki,
)

# Limits for the arguments. Notes text has no length limit here: the save helper refuses
# over 100 KB with a clear sentence, which is better than silently cutting the player's notes.
MAX_HISTORY_EVENTS = 100
MAX_PROGRESS_DAYS = 90
MAX_TITLE_CHARACTERS = 200
MAX_QUERY_CHARACTERS = 200
MIN_PAGE_CHARACTERS = 200
MAX_PAGE_CHARACTERS = 12_000
MAX_QUEST_ID = 10_000_000
_SHOWN_TEXT_CHARACTERS = 80  # how much of the AI's own words a description quotes


def _schema(
    properties: dict[str, object] | None = None, required: tuple[str, ...] = ()
) -> dict[str, object]:
    """A JSON schema for a tool's arguments."""
    return {"type": "object", "properties": properties or {}, "required": list(required)}


def _text_of(arguments: Mapping[str, object], name: str) -> str:
    """One argument as short one-line text, for a description. Never raises."""
    value = arguments.get(name)
    text = " ".join(str(value).split()) if value is not None else ""
    if len(text) > _SHOWN_TEXT_CHARACTERS:
        text = text[: _SHOWN_TEXT_CHARACTERS - 1] + "…"
    return text


def build_coach_tools(
    wow_dir: Path,
    character_key: str,
    *,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], float] = time.time,
    clean: Callable[[str], str] | None = None,
    fetch: Fetch | None = None,
) -> tuple[CoachTool, ...]:
    """The coach tools for one character.

    Args:
        wow_dir: The game folder (the one holding ``WTF/``).
        character_key: The character, as ``Name-Realm``.
        environ: Environment variables, where the notes live (default: the real ones).
        now: Gives the current time in seconds since 1970 (tests pass a fixed one).
        clean: Applied to every output; the engine passes its hiding of other players' names.
        fetch: How web pages are downloaded (default: a polite fetcher with a cache). Tests
            pass a fake one so they never use the network.
    """
    env = os.environ if environ is None else environ
    download = PoliteFetcher(build_user_agent()) if fetch is None else fetch
    cleaner: Callable[[str], str] = clean if clean is not None else (lambda text: text)
    journal = journal_path(character_key, environ=env)
    player_notes = notes_path(environ=env)

    def tool(
        name: str,
        kind: ToolKind,
        description: str,
        parameters: dict[str, object],
        handler: Callable[[dict[str, object]], str],
        describer: Callable[[Mapping[str, object]], str],
    ) -> CoachTool:
        return CoachTool(
            spec=ToolSpec(name, description, parameters),
            kind=kind,
            handler=handler,
            describer=describer,
            clean=cleaner,
        )

    def number(arguments: dict[str, object], name: str) -> int:
        value = arguments[name]
        return value if isinstance(value, int) else 0

    def text(arguments: dict[str, object], name: str) -> str:
        value = arguments.get(name)
        return value if isinstance(value, str) else ""

    def section_of(arguments: dict[str, object]) -> str | None:
        return text(arguments, "section") or None

    return (
        tool(
            "character_status",
            "read",
            "Get the full current status of the character as Markdown: level, XP, gold, "
            "location, quests (with quest IDs), talents, professions, gear, bags, bank, "
            "spells, reputations and more. Use it whenever the player asks what to do next, "
            "what to upgrade, or about quests, gear, items, gold or location. The data is "
            "only as fresh as its 'saved ... ago' line.",
            _schema(),
            lambda _args: answer_character_status(wow_dir, character_key, now()),
            lambda _args: "Read your character status",
        ),
        tool(
            "recent_history",
            "read",
            "Get the character's recent events (level-ups, deaths, quests), newest first. "
            "Use it to see what the player has been doing lately, for example to explain a "
            "death.",
            _schema(
                {
                    "limit": {
                        "type": "integer",
                        "description": "How many events to return (1 to 100).",
                        "default": 20,
                        "minimum": 1,
                        "maximum": MAX_HISTORY_EVENTS,
                    }
                }
            ),
            lambda args: answer_recent_history(
                wow_dir, character_key, number(args, "limit"), now()
            ),
            lambda _args: "Read your recent history",
        ),
        tool(
            "progress_summary",
            "read",
            "Summarize how the character has progressed lately, in plain words: sessions, "
            "levels, XP, gold, quests, deaths and what changed since last time. Use it at "
            "the start of a session and when the player asks how they are doing.",
            _schema(
                {
                    "days": {
                        "type": "integer",
                        "description": "How many days back to look (1 to 90).",
                        "default": 7,
                        "minimum": 1,
                        "maximum": MAX_PROGRESS_DAYS,
                    }
                }
            ),
            lambda args: answer_progress_summary(
                wow_dir, character_key, number(args, "days"), now()
            ),
            lambda _args: "Read your progress summary",
        ),
        tool(
            "read_coach_notes",
            "read",
            "Read the coach's memory: the player notes plus this character's journal. Use "
            "it before giving advice, so you remember the player's preferences, goals and "
            "what to do next. If there is no journal yet, ask for the goal and create it "
            "with save_coach_notes.",
            _schema(),
            lambda _args: answer_read_notes(player_notes, journal, character_key),
            lambda _args: "Read your character journal",
        ),
        tool(
            "save_coach_notes",
            "write",
            "Save this character's journal, replacing everything saved in it before. Use it "
            "when you learn something worth remembering about THIS character: spec, "
            "goals, progress, what you taught, what to do next. Call read_coach_notes first "
            "and send the full updated text (Markdown, under 100 KB). The earlier version "
            "is kept, so a mistake can be undone.",
            _schema(
                {"text": {"type": "string", "description": "The complete new journal."}},
                ("text",),
            ),
            lambda args: answer_save_notes(journal, text(args, "text"), "journal"),
            lambda _args: "Saved your character journal",
        ),
        tool(
            "save_player_notes",
            "write",
            "Save the player notes shared by all characters, replacing what was saved "
            "before. Use it when you learn how the player likes to be coached. Call "
            "read_coach_notes first and send the full updated text (Markdown, under 100 KB). "
            "Notes about one character belong in save_coach_notes. The earlier version is "
            "kept, so a mistake can be undone.",
            _schema(
                {"text": {"type": "string", "description": "The complete new player notes."}},
                ("text",),
            ),
            lambda args: answer_save_notes(player_notes, text(args, "text"), "player notes"),
            lambda _args: "Saved your player notes",
        ),
        tool(
            "search_wiki",
            "web",
            "Search the Warcraft Wiki and get matching page titles, one-line snippets and "
            "links. Use it when you do not know the exact page name, then call "
            "read_wiki_page with the title you want. Always cite the link you used.",
            _schema(
                {
                    "query": {
                        "type": "string",
                        "description": "What to look for, in plain words.",
                        "maxLength": MAX_QUERY_CHARACTERS,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many results to return (1 to 10).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": MAX_SEARCH_RESULTS,
                    },
                },
                ("query",),
            ),
            lambda args: answer_search_wiki(text(args, "query"), number(args, "limit"), download),
            lambda args: f'Searched the Warcraft Wiki for "{_text_of(args, "query")}"',
        ),
        tool(
            "read_wiki_page",
            "web",
            "Read a Warcraft Wiki page as plain text, with its key facts first. Use it for "
            "NPC locations, vendor stock and prices, quest givers and rewards, items, zones "
            "and game terms. Forever-only information is marked; prefer it. If you do not "
            "know the exact title, call search_wiki first. Always cite the page link.",
            _schema(
                {
                    "title": {
                        "type": "string",
                        "description": "The page title, for example 'Abigail Shiel'.",
                        "maxLength": MAX_TITLE_CHARACTERS,
                    },
                    "section": {
                        "type": "string",
                        "description": "Only return this section, for example 'Sells'.",
                        "maxLength": MAX_TITLE_CHARACTERS,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Longest answer to return.",
                        "default": DEFAULT_MAX_CHARS,
                        "minimum": MIN_PAGE_CHARACTERS,
                        "maximum": MAX_PAGE_CHARACTERS,
                    },
                },
                ("title",),
            ),
            lambda args: answer_read_wiki_page(
                text(args, "title"), section_of(args), number(args, "max_chars"), download
            ),
            _describe_read_page,
        ),
        tool(
            "find_quest",
            "web",
            "Find the Warcraft Wiki page of a quest from its quest ID (character_status "
            "shows each quest as '(quest 365)'). Use it instead of searching the quest "
            "title: Forever reuses Classic quests, and a title search often finds the Retail "
            "page. Then call read_wiki_page with the title it returns. Always cite the link.",
            _schema(
                {
                    "quest_id": {
                        "type": "integer",
                        "description": "The quest ID, for example 365.",
                        "minimum": 1,
                        "maximum": MAX_QUEST_ID,
                    }
                },
                ("quest_id",),
            ),
            lambda args: answer_find_quest(number(args, "quest_id"), download),
            lambda args: f"Looked up quest {_text_of(args, 'quest_id')} on the Warcraft Wiki",
        ),
    )


def _describe_read_page(arguments: Mapping[str, object]) -> str:
    title = _text_of(arguments, "title")
    section = _text_of(arguments, "section")
    where = f', section "{section}"' if section else ""
    return f'Read the Warcraft Wiki page "{title}"{where}'
