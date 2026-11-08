"""``wow-coach app``: builds the real objects, starts the window and runs until Ctrl+C."""

import contextlib
import os
import sys
import threading
import webbrowser
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from wow_coach.ai.base import AIError
from wow_coach.ai.chatgpt_plan import ChatGPTPlan
from wow_coach.alerts import SystemAlerts
from wow_coach.app.core import AppCore
from wow_coach.app.launcher import open_start_page
from wow_coach.app.server import CoachServer
from wow_coach.app.watcher import Watcher
from wow_coach.app_settings import AppSettings, load_settings, settings_path
from wow_coach.companion import LiveCoach, build_sign_in, build_usage_log
from wow_coach.engine.model import choose_small_model
from wow_coach.usage import UsageLog

SNAP_HINT = "If your browser shows an error or does not open, paste the link above into it."


def run_app(
    *,
    wow_dir: Path,
    port: int = 0,
    open_in_browser: bool = True,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
) -> None:
    """Start the coach window and keep it running until the player presses Ctrl+C.

    Args:
        wow_dir: The game folder (the one that contains ``WTF/``).
        port: The port to listen on; 0 picks a free one.
        open_in_browser: Open the player's browser on the start link.
        environ: Environment variables (default: the real ones).
        out: Where to print the link (default: standard output).
    """
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    core = build_core(wow_dir, environ)
    server = CoachServer(core, port)
    watcher = Watcher(core, wow_dir)
    server.start()
    watcher.start()
    url = server.start_url()
    print(f"The wow-coach window is open at {url}", file=out, flush=True)
    print("It only works on this computer. Press Ctrl+C to close it.", file=out, flush=True)
    clean_up = open_start_page(url, webbrowser.open) if open_in_browser else None
    print(SNAP_HINT, file=out, flush=True)
    print("Press Enter here for a new link, Ctrl+C to close.", file=out, flush=True)
    try:
        _wait_for_ctrl_c(server, out)
    finally:
        if clean_up is not None:
            clean_up()
        watcher.stop()
        server.stop()


def _wait_for_ctrl_c(server: CoachServer, out: TextIO) -> None:
    """Wait until Ctrl+C. Each Enter prints a new one-time link (the old, unused one stops)."""
    with contextlib.suppress(KeyboardInterrupt):
        print_links_on_enter(server, out, sys.stdin)
        threading.Event().wait()  # no terminal input available: just wait for Ctrl+C


def print_links_on_enter(server: CoachServer, out: TextIO, stdin: TextIO | None) -> None:
    """For each line the player types (Enter), print a fresh one-time start link."""
    while stdin is not None and stdin.readline():
        print(server.fresh_start_url(), file=out, flush=True)
        print(SNAP_HINT, file=out, flush=True)


def build_core(wow_dir: Path, environ: Mapping[str, str]) -> AppCore:
    """Create the real settings, keychain sign-in, usage log, AI, engine and alerts.

    ``companion.py`` builds the same sign-in and caps as ``wow-coach ask``, so the window and
    the command line share one keychain entry, one usage log and one refresh lock.
    """
    settings_file = settings_path(environ=environ)
    settings = load_settings(settings_file)
    sign_in = build_sign_in(environ)
    usage = build_usage_log(settings, environ)
    plan = ChatGPTPlan(sign_in, usage_log=usage)
    coach = LiveCoach(plan, wow_dir=wow_dir, environ=environ, settings_file=settings_file)
    return AppCore(
        coach=coach,
        signin=sign_in,
        alerts=SystemAlerts(),
        list_models=plan.list_models,
        settings_file=settings_file,
        wow_dir=wow_dir,
        usage=usage,
        on_settings_changed=lambda new: _apply_caps(usage, new),
        triage_provider=plan,
        small_model=_small_model_finder(plan),
    )


def _small_model_finder(plan: ChatGPTPlan) -> Callable[[], str | None]:
    """A function giving the small model for triage; the plan's list is fetched only once."""
    cache: list[str | None] = []

    def find() -> str | None:
        if not cache:
            try:
                cache.append(choose_small_model([m.slug for m in plan.list_models()]))
            except AIError:
                return None  # not signed in, or offline: skip triage this time, try again later
        return cache[0]

    return find


def _apply_caps(usage: UsageLog, settings: AppSettings) -> None:
    """Make new caps count at once (``UsageLog`` reads them on every call)."""
    usage.set_caps(
        max_calls_per_hour=settings.max_calls_per_hour,
        max_calls_per_day=settings.max_calls_per_day,
    )
