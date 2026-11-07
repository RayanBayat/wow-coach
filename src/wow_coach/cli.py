"""The ``wow-coach`` command line: status, watch, mcp, check and wiki.

Every command accepts ``--wow-dir PATH`` (the game folder that contains ``WTF/``).
Without it we use the ``WOW_COACH_WOW_DIR`` variable, then look in the usual install places.
"""

import argparse
import contextlib
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from wow_coach.check import run_check
from wow_coach.errors import WowCoachError
from wow_coach.gamedir import resolve_game_folder
from wow_coach.report import format_history, format_status
from wow_coach.savedvars import find_saved_variables, load_characters
from wow_coach.server import main as run_mcp_server
from wow_coach.server import pick_character
from wow_coach.watch import watch
from wow_coach.web import Fetch, PoliteFetcher, build_user_agent
from wow_coach.wiki import DEFAULT_MAX_CHARS, answer_read_wiki_page, answer_search_wiki

HISTORY_EVENTS_SHOWN = 10


def _build_parser() -> argparse.ArgumentParser:
    # Options shared by every command live in one parent parser, so each command
    # accepts --wow-dir after its name (``wow-coach status --wow-dir ...``).
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--wow-dir",
        type=Path,
        metavar="PATH",
        help="the game folder that contains WTF (default: $WOW_COACH_WOW_DIR, then auto-detect)",
    )
    parser = argparse.ArgumentParser(
        prog="wow-coach",
        description="An AI coach for World of Warcraft: Forever. The CoachLink addon saves "
        "your character; these commands let you and any AI app read it.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    status = commands.add_parser(
        "status", parents=[shared], help="print the character's status and recent history"
    )
    status.add_argument("--character", metavar="NAME", help="character name (default: newest save)")
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
    wiki.add_argument("--limit", type=int, default=5, help="how many search results (default 5)")
    return parser


def _wiki(arguments: argparse.Namespace, fetch: Fetch | None) -> int:
    download = PoliteFetcher(build_user_agent()) if fetch is None else fetch
    if arguments.page:
        print(answer_read_wiki_page(arguments.page, arguments.section, DEFAULT_MAX_CHARS, download))
    elif arguments.query:
        print(answer_search_wiki(arguments.query, arguments.limit, download))
    else:
        print("wow-coach: give a search text, or --page TITLE to read a page", file=sys.stderr)
        return 2
    return 0


def _status(wow_dir_flag: Path | None, character: str | None) -> int:
    folder = resolve_game_folder(wow_dir_flag).path
    characters = load_characters(find_saved_variables(folder))
    chosen = pick_character(characters, character)
    if chosen is None:
        known = ", ".join(sorted(characters)) or "(none yet: type /coach in game)"
        raise WowCoachError(f"No character matches {character!r}. Known characters: {known}")
    now = time.time()
    print(format_status(chosen.snapshot, now=now))
    print()
    print("## Recent history")
    print(format_history(chosen.history, limit=HISTORY_EVENTS_SHOWN, now=now))
    return 0


def _watch(wow_dir_flag: Path | None) -> int:
    folder = resolve_game_folder(wow_dir_flag).path
    # Ctrl+C is how you are supposed to stop watching, so it is not an error.
    with contextlib.suppress(KeyboardInterrupt):
        watch(folder, out=sys.stdout, sleep=time.sleep)
    return 0


def _mcp(wow_dir_flag: Path | None) -> int:
    run_mcp_server(wow_dir_flag)
    return 0


def _check(wow_dir_flag: Path | None) -> int:
    return run_check(
        wow_dir_flag, environ=os.environ, candidates=None, now=time.time(), out=sys.stdout
    )


def main(argv: Sequence[str] | None = None, fetch: Fetch | None = None) -> int:
    """Run the command line and return the exit code (0 means success).

    ``fetch`` replaces the web download (tests only).
    """
    arguments = _build_parser().parse_args(argv)
    flag: Path | None = getattr(arguments, "wow_dir", None)
    commands: dict[str, Callable[[], int]] = {
        "status": lambda: _status(flag, arguments.character),
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
