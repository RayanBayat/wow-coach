"""The ``wow-coach`` command line: setup, status, characters, progress, watch, mcp, check, wiki.

Every command accepts ``--wow-dir PATH`` (the game folder that contains ``WTF/``).
Without it we use the ``WOW_COACH_WOW_DIR`` variable, then the folder saved by
``wow-coach setup``, then look in the usual install places.
"""

import argparse
import contextlib
import importlib.metadata
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from wow_coach.characters import pick_character
from wow_coach.check import run_check
from wow_coach.config import config_path
from wow_coach.errors import WowCoachError
from wow_coach.gamedir import resolve_game_folder
from wow_coach.report import format_history, format_progress, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters
from wow_coach.server import format_character_list
from wow_coach.server import main as run_mcp_server
from wow_coach.setup import SetupChoices, SetupWorld, run_setup
from wow_coach.watch import watch
from wow_coach.web import Fetch, FetchBytes, PoliteFetcher, build_user_agent
from wow_coach.wiki import (
    DEFAULT_MAX_CHARS,
    answer_find_quest,
    answer_read_wiki_page,
    answer_search_wiki,
)

HISTORY_EVENTS_SHOWN = 10


def _build_parser() -> argparse.ArgumentParser:
    # Options shared by every command live in one parent parser, so each command
    # accepts --wow-dir after its name (``wow-coach status --wow-dir ...``).
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--wow-dir",
        type=Path,
        metavar="PATH",
        help="the game folder that contains WTF (default: $WOW_COACH_WOW_DIR, then the folder "
        "saved by `wow-coach setup`, then auto-detect)",
    )
    parser = argparse.ArgumentParser(
        prog="wow-coach",
        description="An AI coach for World of Warcraft: Forever. The CoachLink addon saves "
        "your character; these commands let you and any AI app read it.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    setup = commands.add_parser(
        "setup",
        parents=[shared],
        help="get everything ready: find the game, install the addon, create the notebook",
    )
    setup.add_argument("--yes", action="store_true", help="ask no questions, take the defaults")
    setup.add_argument(
        "--claude-code",
        action="store_true",
        help="also install the Claude Code agent and skill (then run: claude --agent wow-coach)",
    )
    setup.add_argument("--skip-addon", action="store_true", help="do not install the addon")
    status = commands.add_parser(
        "status", parents=[shared], help="print the character's status and recent history"
    )
    status.add_argument("--character", metavar="NAME", help="character name (default: newest save)")
    commands.add_parser(
        "characters",
        parents=[shared],
        help="list your characters, most recently played first, with their goals",
    )
    progress = commands.add_parser(
        "progress",
        parents=[shared],
        help="show how a character has progressed lately (sessions, levels, gold, deaths)",
    )
    progress.add_argument(
        "--character", metavar="NAME", help="character name (default: newest save)"
    )
    progress.add_argument(
        "--days", type=int, default=7, help="how many days back to look (default 7)"
    )
    commands.add_parser(
        "watch", parents=[shared], help="print a line each time you save with /coach"
    )
    commands.add_parser("mcp", parents=[shared], help="run the MCP server (for AI apps) over stdio")
    commands.add_parser(
        "check", parents=[shared], help="find out why it is not working (troubleshooting)"
    )
    wiki = commands.add_parser(
        "wiki", help="look something up on the Warcraft Wiki (search, or read one page)"
    )
    wiki.add_argument("query", nargs="?", help="what to search for")
    wiki.add_argument("--page", metavar="TITLE", help="read this page instead of searching")
    wiki.add_argument("--section", metavar="NAME", help="with --page: only this section")
    wiki.add_argument("--quest", type=int, metavar="ID", help="find the page of this quest ID")
    wiki.add_argument("--limit", type=int, default=5, help="how many search results (default 5)")
    return parser


def _wiki(arguments: argparse.Namespace, fetch: Fetch | None) -> int:
    download = PoliteFetcher(build_user_agent()) if fetch is None else fetch
    if arguments.quest is not None:
        print(answer_find_quest(arguments.quest, download))
    elif arguments.page:
        print(answer_read_wiki_page(arguments.page, arguments.section, DEFAULT_MAX_CHARS, download))
    elif arguments.query:
        print(answer_search_wiki(arguments.query, arguments.limit, download))
    else:
        print("wow-coach: give a search text, --page TITLE, or --quest ID", file=sys.stderr)
        return 2
    return 0


def _ask_the_player(question: str) -> str:
    """Ask a question in the terminal; no answer (input closed) counts as an empty one."""
    try:
        return input(question)
    except EOFError:
        return ""


def _setup(arguments: argparse.Namespace, download: FetchBytes | None) -> int:
    choices = SetupChoices(
        wow_dir_flag=arguments.wow_dir,
        assume_yes=arguments.yes,
        claude_code=arguments.claude_code,
        skip_addon=arguments.skip_addon,
    )
    world = SetupWorld(
        environ=os.environ,
        candidates=None,
        home=Path.home(),
        package_version=importlib.metadata.version("wow-coach"),
        download=PoliteFetcher(build_user_agent()).fetch_bytes if download is None else download,
        ask=_ask_the_player,
        interactive=sys.stdin.isatty(),
        now=time.time(),
        out=sys.stdout,
    )
    return run_setup(choices, world)


def _load_saved_characters(wow_dir_flag: Path | None) -> dict[str, Character]:
    """Find the game folder and read every saved character."""
    folder = resolve_game_folder(wow_dir_flag, config_file=config_path(environ=os.environ)).path
    return load_characters(find_saved_variables(folder))


def _choose_character(characters: dict[str, Character], wanted: str | None) -> Character:
    """The wanted character (default: newest save), or a friendly error."""
    chosen = pick_character(characters, wanted)
    if chosen is None:
        known = ", ".join(sorted(characters)) or "(none yet: type /coach in game)"
        raise WowCoachError(f"No character matches {wanted!r}. Known characters: {known}")
    return chosen


def _characters(wow_dir_flag: Path | None) -> int:
    characters = _load_saved_characters(wow_dir_flag)
    if not characters:
        raise WowCoachError("The CoachLink file has no characters yet: type /coach in game.")
    print(format_character_list(characters, time.time(), os.environ))
    return 0


def _progress(wow_dir_flag: Path | None, character: str | None, days: int) -> int:
    chosen = _choose_character(_load_saved_characters(wow_dir_flag), character)
    print(f"# Progress of {chosen.key}")
    print()
    print(format_progress(chosen.progress, chosen.history, days=days, now=time.time()))
    return 0


def _status(wow_dir_flag: Path | None, character: str | None) -> int:
    chosen = _choose_character(_load_saved_characters(wow_dir_flag), character)
    now = time.time()
    print(format_status(chosen.snapshot, now=now))
    print()
    print("## Recent history")
    print(format_history(chosen.history, limit=HISTORY_EVENTS_SHOWN, now=now))
    return 0


def _watch(wow_dir_flag: Path | None) -> int:
    folder = resolve_game_folder(wow_dir_flag, config_file=config_path(environ=os.environ)).path
    # Ctrl+C is how you are supposed to stop watching, so it is not an error.
    with contextlib.suppress(KeyboardInterrupt):
        watch(folder, out=sys.stdout, status=sys.stderr, sleep=time.sleep)
    return 0


def _mcp(wow_dir_flag: Path | None) -> int:
    run_mcp_server(wow_dir_flag)
    return 0


def _check(wow_dir_flag: Path | None) -> int:
    return run_check(
        wow_dir_flag, environ=os.environ, candidates=None, now=time.time(), out=sys.stdout
    )


def main(
    argv: Sequence[str] | None = None,
    fetch: Fetch | None = None,
    download: FetchBytes | None = None,
) -> int:
    """Run the command line and return the exit code (0 means success).

    ``fetch`` and ``download`` replace the web downloads of text and of files (tests only).
    """
    arguments = _build_parser().parse_args(argv)
    flag: Path | None = getattr(arguments, "wow_dir", None)
    commands: dict[str, Callable[[], int]] = {
        "setup": lambda: _setup(arguments, download),
        "status": lambda: _status(flag, arguments.character),
        "characters": lambda: _characters(flag),
        "progress": lambda: _progress(flag, arguments.character, arguments.days),
        "watch": lambda: _watch(flag),
        "mcp": lambda: _mcp(flag),
        "check": lambda: _check(flag),
        "wiki": lambda: _wiki(arguments, fetch),
    }
    try:
        return commands[arguments.command]()
    except (WowCoachError, OSError) as error:
        print(f"wow-coach: {error}", file=sys.stderr)
        return 1
