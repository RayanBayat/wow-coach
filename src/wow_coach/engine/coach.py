"""``ChatCoach``: answers questions with the player's AI and shows them in the Coach panel.

One question goes through these steps: load the character from the save, build the
messages, ask the AI, read the JSON reply, write it to ``Advice.lua`` and remember the
conversation. An ``AIError`` is not caught here: the window or the CLI shows its sentence.
"""

import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Final

from wow_coach.advice.contract import (
    AdviceAnswer,
    AdviceFile,
    Question,
)
from wow_coach.advice.limits import limit_answer
from wow_coach.advice.merge import add_answer
from wow_coach.advice.paths import advice_addon_for, advice_file_path
from wow_coach.advice.questions import open_questions
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.writer import interface_from_herobridge, update_advice
from wow_coach.ai.base import Provider
from wow_coach.app_settings import AppSettings
from wow_coach.characters import pick_character
from wow_coach.engine.agent import Activity, AgentResult, run_agent
from wow_coach.engine.answer import ANSWER_SCHEMA, parse_answer
from wow_coach.engine.contract import CoachReply
from wow_coach.engine.conversation import (
    ChatAnswer,
    ChatMessage,
    Source,
    append_messages,
    conversation_path,
    new_message_id,
    now_iso,
    read_messages,
)
from wow_coach.engine.memory import LocalMemory
from wow_coach.engine.prompt import PromptData, build_messages
from wow_coach.engine.redact import other_player_names, redact_names, without_own_names
from wow_coach.errors import WowCoachError
from wow_coach.notes import journal_path, notes_path
from wow_coach.report import format_history, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters
from wow_coach.tools import CoachTool, build_coach_tools
from wow_coach.web import Fetch

MAX_OUTPUT_TOKENS: Final = 800
CONTEXT_MESSAGES: Final = 60  # newest chat messages read for the prompt (it keeps what fits)
HISTORY_EVENTS: Final = 10
_NOTES_TOOLS: Final = ("read_coach_notes", "save_coach_notes", "save_player_notes")
type ActivityListener = Callable[[str, Activity], None]  # (character key, what is happening)
_WRITE_ERRORS: Final = (WowCoachError, OSError, ValueError, OverflowError, RecursionError)


class NoSuchCharacterError(WowCoachError):
    """The save has no character with the requested name."""


def _read_text_or_empty(path: Path) -> str:
    """A text file's content; empty when it is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError:
        return ""


def _saved_at(character: Character) -> int | None:
    value = character.snapshot.get("savedAt")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def provider_id(name: str) -> str:
    """A short id for a provider's display name: "ChatGPT (your plan)" becomes "chatgpt"."""
    words = "".join(c if c.isalnum() else " " for c in name.lower()).split()
    if words[:1] == ["chatgpt"]:
        return "chatgpt"
    return "-".join(words) or "unknown"


def _answer_as_text(answer: AdviceAnswer) -> str:
    """The answer in one piece of text, for the conversation memory."""
    steps = "; ".join(answer.steps)
    return " ".join(part for part in (answer.title + ".", steps, answer.text) if part)


class ChatCoach:
    """The coach engine (see ``engine/contract.py``) on top of any ``Provider``."""

    def __init__(
        self,
        provider: Provider,
        *,
        model: str,
        wow_dir: Path,
        environ: Mapping[str, str],
        settings: AppSettings,
        now: Callable[[], float] = time.time,
        on_activity: ActivityListener | None = None,
        fetch: Fetch | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._wow_dir = wow_dir
        self._environ = environ
        self._settings = settings
        self._now = now
        self._on_activity = on_activity
        self._fetch = fetch  # None: the real, polite wiki fetcher
        self._memory = LocalMemory(environ=environ)
        self._own_characters: frozenset[str] = frozenset()  # every character in the save

    # ---- the Coach contract ---------------------------------------------------------

    def ask(
        self, question: str, *, character: str | None = None, source: Source = "app"
    ) -> CoachReply:
        """Answer a question typed outside the game (or sent after a save, ``source="save"``)."""
        text = question.strip()
        if not text:
            raise WowCoachError("Type a question first.")
        return self._answer(self._load_character(character), text, None, source=source)

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        """Answer every question from the Coach panel that has no answer yet."""
        found = self._load_character(character)
        advice = read_advice_file(self._advice_path())
        done = self._memory.answered_ids(found.key)
        todo = [q for q in open_questions(found, advice) if q.id not in done]
        return [self._answer(found, item.text, item) for item in todo]

    # ---- steps ---------------------------------------------------------------------

    def _advice_path(self) -> Path:
        return advice_file_path(self._wow_dir)

    def _load_character(self, wanted: str | None) -> Character:
        """Read the save and pick the character. Raises a plain ``WowCoachError`` if none."""
        characters = load_characters(find_saved_variables(self._wow_dir))
        found = pick_character(characters, wanted)
        if found is None:
            known = ", ".join(sorted(characters)) or "none yet"
            raise NoSuchCharacterError(
                f"No saved character matches {wanted!r}. Characters in the save: {known}."
            )
        self._own_characters = frozenset(key.split("-", 1)[0] for key in characters)
        return found

    def _prompt_data(
        self, found: Character, question: str, history: list[ChatMessage]
    ) -> PromptData:
        now = self._now()
        return PromptData(
            status=format_status(found.snapshot, now=now),
            history=format_history(found.history, limit=HISTORY_EVENTS, now=now),
            journal=self._coach_notes(journal_path(found.key, environ=self._environ)),
            player_notes=self._coach_notes(notes_path(environ=self._environ)),
            messages=history,
            question=question,
        )

    def _coach_notes(self, path: Path) -> str:
        """A notes file's text, or nothing when the player keeps their notes to themselves."""
        return _read_text_or_empty(path) if self._settings.send_coach_notes else ""

    def _names_to_hide(self, found: Character) -> set[str]:
        """Other players' names in this save plus those seen in earlier saves."""
        if self._settings.share_other_player_names:
            return set()
        current = other_player_names(found, own=self._own_characters)
        with contextlib.suppress(OSError):
            self._memory.add_seen_names(found.key, current)
        return without_own_names(
            current | self._memory.seen_names(found.key), found, own=self._own_characters
        )

    def _answer(
        self, found: Character, question: str, asked: Question | None, *, source: Source = "app"
    ) -> CoachReply:
        history = self._chat_history(found.key)
        hidden = self._names_to_hide(found)
        build_messages(self._prompt_data(found, question, history), hidden_names=hidden)
        run = self._run_ai(found, hidden, question, history, asked)
        reply = run.answer
        parsed = parse_answer(reply.text, answered_at=int(self._now()), source=self._provider.name)
        answer = self._tie_to_question(parsed, asked)
        if asked is not None:  # before the write, which may fail
            with contextlib.suppress(OSError):
                self._memory.add_answered(found.key, asked.id)
        written, note = self._write(found, answer)
        self._remember(
            found.key, question, answer, run, source="game" if asked else source, asked=asked
        )
        return CoachReply(
            character_key=found.key,
            answer=answer,
            written_to_game=written,
            note=note,
            sources=run.sources,
            lookups=run.lookups,
        )

    def _run_ai(
        self,
        found: Character,
        hidden: set[str],
        question: str,
        history: list[ChatMessage],
        asked: Question | None,
    ) -> AgentResult:
        """Ask the AI, letting it use the tools the player allowed (see ``engine/agent.py``)."""
        tools = self._tools(found, hidden)
        search = self._settings.web_search
        messages = build_messages(
            self._prompt_data(found, question, history),
            hidden_names=hidden,
            tools=bool(tools) or search,
            save_notes=any(tool.kind == "write" for tool in tools),
        )
        del asked  # a question from the game is answered the same way

        def on_activity(activity: Activity) -> None:
            if self._on_activity is not None:
                self._on_activity(found.key, activity)

        return run_agent(
            self._provider,
            messages,
            model=self._model,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            json_schema=ANSWER_SCHEMA,
            tools=tools,
            web_search=search,
            on_activity=on_activity,
        )

    def _tools(self, found: Character, hidden: set[str]) -> tuple[CoachTool, ...]:
        """The tools the player allows for this character; none when tools are off.

        Every tool output hides other players' names, like the prompt does. Without
        permission to share the notes, the notes tools are left out; without permission
        to save, the two save tools are.
        """
        if not self._settings.use_tools:
            return ()
        tools = build_coach_tools(
            self._wow_dir,
            found.key,
            environ=self._environ,
            now=self._now,
            clean=lambda text: redact_names(text, hidden),
            fetch=self._fetch,
            hide_private_notes=True,
        )
        allowed = [
            tool
            for tool in tools
            if (self._settings.save_notes or tool.kind != "write")
            and (self._settings.send_coach_notes or tool.name not in _NOTES_TOOLS)
        ]
        return tuple(allowed)

    @staticmethod
    def _tie_to_question(answer: AdviceAnswer, asked: Question | None) -> AdviceAnswer:
        """Mark the answer as the one for a game question, so the question counts as answered."""
        if asked is None:
            return answer
        return limit_answer(
            replace(answer, question_id=asked.id, question=asked.text, asked_at=asked.asked_at)
        )

    def _write(self, found: Character, answer: AdviceAnswer) -> tuple[bool, str]:
        """Put the answer in Advice.lua. Returns (written, a plain note for the player)."""
        addons_dir = self._wow_dir / "Interface" / "AddOns"
        first_time = not (addons_dir / advice_addon_for(addons_dir).folder_name).exists()

        def change(current: AdviceFile) -> AdviceFile:
            return add_answer(
                current,
                found.key,
                answer,
                based_on_save=_saved_at(found),
                now=answer.answered_at,
            )

        try:
            update_advice(
                addons_dir,
                change,
                interface=interface_from_herobridge(addons_dir),
                now=answer.answered_at,
            )
        except _WRITE_ERRORS as error:
            return False, f"The answer is here, but it could not be saved for the game: {error}"
        if first_time:
            return True, (
                "In the game after you restart it completely once (a /reload is not enough "
                "the first time). After that, a /reload shows new answers."
            )
        return True, "In the game after your next /reload."

    def _chat_history(self, character_key: str) -> list[ChatMessage]:
        """The newest chat messages, from every source. Claude chats only if the player allows."""
        found = read_messages(
            conversation_path(character_key, environ=self._environ), limit=CONTEXT_MESSAGES
        )
        if self._settings.use_claude_chats:
            return found
        return [item for item in found if item.source != "claude-code"]

    def _remember(
        self,
        character_key: str,
        question: str,
        answer: AdviceAnswer,
        run: AgentResult,
        *,
        source: Source,
        asked: Question | None,
    ) -> None:
        """Keep the question and answer in the chat history. A failure here is not an error."""
        asked_at = self._now()
        answered_at = max(float(answer.answered_at), asked_at)
        question_id = new_message_id("app") if asked is None else f"game:{asked.id}"
        messages = [
            ChatMessage("user", question, question_id, now_iso(asked_at), source),
            ChatMessage(
                "assistant",
                _answer_as_text(answer),
                new_message_id(),
                now_iso(answered_at),
                source,
                provider=provider_id(self._provider.name),
                model=run.answer.model,
                answer=ChatAnswer(
                    answer.title,
                    answer.steps,
                    answer.text,
                    answer.warnings,
                    sources=run.sources,
                    lookups=run.lookups,
                ),
            ),
        ]
        with contextlib.suppress(OSError):
            append_messages(conversation_path(character_key, environ=self._environ), messages)
