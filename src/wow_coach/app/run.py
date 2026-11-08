"""``wow-coach app``: builds the real objects, starts the window and runs until Ctrl+C."""

import contextlib
import os
import sys
import threading
import webbrowser
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from wow_coach.app.core import AppCore
from wow_coach.app.server import CoachServer
from wow_coach.app.watcher import Watcher
from wow_coach.app_settings import AppSettings, settings_path
from wow_coach.datafolder import data_folder
from wow_coach.usage import UsageLog, usage_log_path

LOCK_FILE_NAME = "refresh.lock"


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
    core = _build_core(wow_dir, environ)
    server = CoachServer(core, port)
    watcher = Watcher(core, wow_dir)
    server.start()
    watcher.start()
    url = server.start_url()
    print(f"The wow-coach window is open at {url}", file=out, flush=True)
    print("It only works on this computer. Press Ctrl+C to close it.", file=out, flush=True)
    if open_in_browser:
        webbrowser.open(url)
    try:
        _wait_for_ctrl_c()
    finally:
        watcher.stop()
        server.stop()


def _wait_for_ctrl_c() -> None:
    """Block until Ctrl+C (the main thread has nothing else to do)."""
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()


def _build_core(wow_dir: Path, environ: Mapping[str, str]) -> AppCore:
    """Create the real settings, keychain, sign-in, usage log, AI, engine and alerts."""
    # These modules are imported here, not at the top of the file: the engine and the alerts
    # are separate parts of wow-coach, and keeping the imports lazy means the window's own
    # code and its tests never need them (or the keychain and the network code behind them).
    from wow_coach.ai.chatgpt_plan import ChatGPTPlan  # noqa: PLC0415
    from wow_coach.ai.chatgpt_signin import ChatGPTSignIn  # noqa: PLC0415
    from wow_coach.alerts import SystemAlerts  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
    from wow_coach.app_settings import load_settings  # noqa: PLC0415
    from wow_coach.engine.coach import ChatCoach  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
    from wow_coach.keychain import Keychain  # noqa: PLC0415

    folder = data_folder(environ=environ)
    settings_file = settings_path(environ=environ)
    settings = load_settings(settings_file)
    signin = ChatGPTSignIn(Keychain(), lock_path=folder / LOCK_FILE_NAME)
    usage = UsageLog(
        usage_log_path(folder),
        max_calls_per_hour=settings.max_calls_per_hour,
        max_calls_per_day=settings.max_calls_per_day,
    )
    plan = ChatGPTPlan(signin, usage_log=usage)
    coach = ChatCoach(plan, wow_dir=wow_dir, settings_file=settings_file, environ=environ)
    return AppCore(
        coach=coach,
        signin=signin,
        alerts=SystemAlerts(),
        list_models=plan.list_models,
        settings_file=settings_file,
        wow_dir=wow_dir,
        usage=usage,
        on_settings_changed=lambda new: _apply_caps(usage, new),
    )


def _apply_caps(usage: UsageLog, settings: AppSettings) -> None:
    """Make new caps count at once (``UsageLog`` reads them on every call)."""
    usage._hour_cap = settings.max_calls_per_hour
    usage._day_cap = settings.max_calls_per_day
