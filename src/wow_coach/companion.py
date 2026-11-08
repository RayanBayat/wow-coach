"""Put wow-coach's own coach together from its real parts (0.9.0+).

Shared by ``wow-coach signin``, ``signout``, ``ask`` and the coach window, so all of them
use the same sign-in (the system keychain), the same usage caps and the same settings.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from wow_coach.ai.base import AIError, NotSignedIn
from wow_coach.ai.chatgpt_plan import ChatGPTPlan
from wow_coach.ai.chatgpt_signin import ChatGPTSignIn
from wow_coach.app_settings import AppSettings, load_settings, settings_path
from wow_coach.config import config_path
from wow_coach.datafolder import data_folder
from wow_coach.engine.coach import ChatCoach
from wow_coach.engine.model import choose_model
from wow_coach.gamedir import resolve_game_folder
from wow_coach.keychain import Keychain
from wow_coach.usage import UsageLog, usage_log_path

# OpenAI's wording for Sign in with ChatGPT (see docs/plans/chatgpt-signin-notes.md).
WELCOME_TITLE: Final = "You're using your ChatGPT plan."
WELCOME_TEXT: Final = (
    "Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings."
)
MANAGE_USAGE_URL: Final = "https://chatgpt.com/settings/usage"
REFRESH_LOCK_NAME: Final = "chatgpt-refresh.lock"


def build_sign_in(environ: Mapping[str, str], keychain: Keychain | None = None) -> ChatGPTSignIn:
    """The ChatGPT sign-in, kept in the system keychain."""
    lock = data_folder(environ=environ) / REFRESH_LOCK_NAME
    return ChatGPTSignIn(keychain or Keychain(), lock_path=lock)


def build_plan(
    sign_in: ChatGPTSignIn, settings: AppSettings, environ: Mapping[str, str]
) -> ChatGPTPlan:
    """The player's ChatGPT plan as an AI provider, with the player's usage caps."""
    log = UsageLog(
        usage_log_path(data_folder(environ=environ)),
        max_calls_per_hour=settings.max_calls_per_hour,
        max_calls_per_day=settings.max_calls_per_day,
    )
    return ChatGPTPlan(sign_in, usage_log=log)


def pick_plan_model(plan: ChatGPTPlan, settings: AppSettings) -> str:
    """The model to use: the player's choice if the plan has it, else a small, fast one."""
    model = choose_model([item.slug for item in plan.list_models()], settings.model)
    if model is None:
        raise AIError("Your ChatGPT plan lists no models wow-coach can use.")
    return model


def build_coach(*, wow_dir_flag: Path | None, environ: Mapping[str, str]) -> ChatCoach:
    """The coach, ready to answer. Raises a plain ``NotSignedIn`` before any sign-in."""
    settings = load_settings(settings_path(environ=environ))
    sign_in = build_sign_in(environ)
    if not sign_in.is_signed_in:
        raise NotSignedIn(
            "You're not signed in to ChatGPT yet. Run `wow-coach signin` first, "
            "or sign in from the coach window (`wow-coach app`)."
        )
    plan = build_plan(sign_in, settings, environ)
    model = pick_plan_model(plan, settings)
    wow_dir = resolve_game_folder(
        wow_dir_flag, environ=environ, config_file=config_path(environ=environ)
    ).path
    return ChatCoach(plan, model=model, wow_dir=wow_dir, environ=environ, settings=settings)
