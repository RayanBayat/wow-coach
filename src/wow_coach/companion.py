"""Put wow-coach's own coach together from its real parts (0.9.0+).

Shared by ``wow-coach signin``, ``signout``, ``ask`` and the coach window, so all of them
use the same sign-in (the system keychain), the same usage caps and the same settings.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from wow_coach.ai.base import AIError, NotSignedIn
from wow_coach.ai.chatgpt_plan import ChatGPTPlan
from wow_coach.ai.chatgpt_signin import ChatGPTSignIn
from wow_coach.app_settings import AppSettings, load_settings, settings_path
from wow_coach.config import config_path
from wow_coach.datafolder import data_folder
from wow_coach.engine.coach import ChatCoach
from wow_coach.engine.contract import CoachReply
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
PRIVACY_URL: Final = "https://github.com/RayanBayat/wow-coach/blob/main/docs/privacy.md"
# Shown before signing in: OpenAI's terms ask for a privacy notice before any data is processed.
PRIVACY_SUMMARY: Final = (
    "When you sign in, wow-coach sends your character's data, your questions, the recent "
    "conversation and the coach's notes to OpenAI, using your ChatGPT plan. Other players' "
    "names are hidden unless you allow them. Nothing else leaves this computer, except your "
    "own speak-up rules and event summaries if you turn on the small helper AI."
)


def build_sign_in(environ: Mapping[str, str], keychain: Keychain | None = None) -> ChatGPTSignIn:
    """The ChatGPT sign-in, kept in the system keychain."""
    lock = data_folder(environ=environ) / REFRESH_LOCK_NAME
    return ChatGPTSignIn(keychain or Keychain(), lock_path=lock)


def build_usage_log(settings: AppSettings, environ: Mapping[str, str]) -> UsageLog:
    """The usage log with the player's caps (calls per hour and per day)."""
    return UsageLog(
        usage_log_path(data_folder(environ=environ)),
        max_calls_per_hour=settings.max_calls_per_hour,
        max_calls_per_day=settings.max_calls_per_day,
    )


def build_plan(
    sign_in: ChatGPTSignIn, settings: AppSettings, environ: Mapping[str, str]
) -> ChatGPTPlan:
    """The player's ChatGPT plan as an AI provider, with the player's usage caps."""
    return ChatGPTPlan(sign_in, usage_log=build_usage_log(settings, environ))


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


type CoachFactory = Callable[..., ChatCoach]


class LiveCoach:
    """A coach that reads the settings again before every answer.

    The coach window can change the settings at any time (the model, whether other players'
    names are shared...). This builds a fresh ``ChatCoach`` for each answer with the newest
    settings, and remembers the chosen model so the plan's model list is fetched only when
    the player's choice changes.
    """

    def __init__(
        self,
        plan: ChatGPTPlan,
        *,
        wow_dir: Path,
        environ: Mapping[str, str],
        settings_file: Path,
        make_coach: CoachFactory = ChatCoach,
    ) -> None:
        self._plan = plan
        self._wow_dir = wow_dir
        self._environ = environ
        self._settings_file = settings_file
        self._make_coach = make_coach
        self._model_for: tuple[str | None, str] | None = None  # (the player's choice, model)

    def _model(self, settings: AppSettings) -> str:
        if self._model_for is None or self._model_for[0] != settings.model:
            self._model_for = (settings.model, pick_plan_model(self._plan, settings))
        return self._model_for[1]

    def _coach(self) -> ChatCoach:
        settings = load_settings(self._settings_file)
        return self._make_coach(
            self._plan,
            model=self._model(settings),
            wow_dir=self._wow_dir,
            environ=self._environ,
            settings=settings,
        )

    def ask(self, question: str, *, character: str | None = None) -> CoachReply:
        """Answer a question typed outside the game."""
        return self._coach().ask(question, character=character)

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        """Answer the questions waiting in the game's Coach panel."""
        return self._coach().answer_open_questions(character=character)
