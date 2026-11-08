"""The Coach page: chat with your coach about your character.

From top to bottom: the header (character, how fresh the game data is, refresh and "keep on
top" buttons), helper banners, quick-action chips, the conversation (or a welcome while it is
empty) and the box where the player types.

This file holds the *behavior* (what happens when a question is sent, when a save arrives,
when the coach is busy...). The look of each part lives in ``desktop/widgets/``.

The page never reads the game folder or the network itself. It talks only to the
``CoreBridge``, which does every slow thing (reading the game's files, "Answer now") in a
background thread and sends the result back as a signal.
"""

import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Final, NamedTuple

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from wow_coach.advice.contract import MAX_QUESTION_CHARS
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.compact import CompactCard
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.quick_actions import QUICK_ACTIONS, QuickAction
from wow_coach.desktop.state import AnswerView, StateView, read_answer
from wow_coach.desktop.theme import SPACE, SPACE_LARGE, Colors, current_colors
from wow_coach.desktop.widgets.bars import OpenQuestionsBar, ProblemBanner, SignInCard
from wow_coach.desktop.widgets.bubbles import MessageRow
from wow_coach.desktop.widgets.chat_view import ChatView
from wow_coach.desktop.widgets.composer import Composer
from wow_coach.desktop.widgets.flow import FlowLayout
from wow_coach.desktop.widgets.formatting import freshness
from wow_coach.desktop.widgets.header import HeaderCard
from wow_coach.desktop.widgets.refresh_banner import RefreshBanner
from wow_coach.desktop.widgets.styles import chat_style
from wow_coach.desktop.widgets.welcome import WelcomeView

BUSY_TEXT: Final = "The coach is still answering. Your question goes next."
MAX_TYPED_REMEMBERED: Final = 50  # typed questions kept to avoid showing them twice
WAITING_FOR_SAVE_TEXT: Final = "Waiting for fresh game data…"
CANCELLED_TEXT: Final = "Okay, asking with the game data I already have."
LIMIT_QUEUE_TEXT: Final = "Your waiting questions were not sent. Try them again when you can."
DEFAULT_ERROR: Final = "Something went wrong. Please try again in a moment."
OPEN_BUSY_TEXT: Final = "The coach is still answering. Try again in a moment."
OPEN_NONE_TEXT: Final = "There are no questions from the game waiting right now."
TICK_MS: Final = 30_000  # how often "12 min old" is recomputed (no disk reads)
QUEUE_RETRY_MS: Final = 1_500  # how often a waiting question tries the busy coach again

type AnswerKey = tuple[int, str, str | None]

_CHAT_PAGE: Final = 0
_WELCOME_PAGE: Final = 1


class WaitingQuestion(NamedTuple):
    """A question that is not sent yet, and the character it was typed for."""

    text: str
    character: str | None


def answer_key(answer: AnswerView) -> AnswerKey:
    """What makes an answer "the same one" when the state is read again."""
    return (answer.answered_at, answer.title, answer.question_id)


def _style(c: Colors) -> str:
    """The Coach page's own look."""
    return chat_style(c)


class CoachPage(Page):
    """Chat with your coach."""

    name = "coach"
    title = "Coach"

    def __init__(
        self,
        bridge: CoreBridge,
        parent: QWidget | None = None,
        *,
        now: Callable[[], float] = time.time,
        card_settings: QSettings | None = None,
        queue_retry_ms: int = QUEUE_RETRY_MS,
    ) -> None:
        """Build the page.

        Args:
            bridge: The bridge to the coach's brain.
            parent: The parent widget.
            now: The clock in seconds since 1970. Tests pass one they control.
            card_settings: Where the small card remembers its place (tests pass a temp file).
            queue_retry_ms: How often a waiting question tries the busy coach again.
        """
        super().__init__(bridge, parent)
        self._now = now
        self._card_settings = card_settings
        self._state = StateView()
        self._card: CompactCard | None = None
        self._loaded = False  # has the chat been filled from a state yet?
        self._character: str | None = None
        self._seen: set[AnswerKey] = set()  # answers already in the chat
        self._game_questions_seen: set[str] = set()  # ids of questions from the game shown
        # Questions typed here, remembered so their answer does not show them a second time.
        # The newest MAX_TYPED_REMEMBERED are kept, so this can never grow without end.
        self._typed_questions: deque[str] = deque(maxlen=MAX_TYPED_REMEMBERED)
        self._queued: list[WaitingQuestion] = []  # waiting for the coach to be free, oldest first
        self._busy_notice_shown = False  # "goes next" is said once per waiting spell
        self._fresh_questions: list[WaitingQuestion] = []  # waiting for the next save
        self._fresh_notice: MessageRow | None = None
        self._newest: AnswerView | None = None

        self._build()
        self._wire()
        self._restyle()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        # The coach can stay busy for a while after it published an answer (alerts),
        # and no event says when it is free again. So a waiting question asks again by itself.
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(queue_retry_ms)
        self._queue_timer.timeout.connect(self._retry_queue)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_card)
        self._update_freshness()
        self._sync_stack()

    # ---- building -----------------------------------------------------------------------

    def _build(self) -> None:
        self.header = HeaderCard()
        self.refresh_banner = RefreshBanner(now=self._now)
        self.problem_banner = ProblemBanner()
        self.questions_bar = OpenQuestionsBar()
        self.sign_in_card = SignInCard()
        self.chips = self._build_chips()
        self.welcome = WelcomeView()
        self.chat = ChatView()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.chat)  # _CHAT_PAGE
        self.stack.addWidget(self.welcome)  # _WELCOME_PAGE
        self.composer = Composer()

        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        column.setSpacing(SPACE)
        for widget in (
            self.header,
            self.refresh_banner,
            self.problem_banner,
            self.questions_bar,
            self.sign_in_card,
            self.chips,
        ):
            column.addWidget(widget)
        column.addWidget(self.stack, 1)
        column.addWidget(self.composer)

    def _build_chips(self) -> QWidget:
        """The row of quick-action chips (it wraps onto more rows in a narrow window)."""
        holder = QWidget()
        flow = FlowLayout(holder, spacing=SPACE // 2)
        self._chip_buttons: list[QPushButton] = []
        for action in QUICK_ACTIONS:
            chip = QPushButton(action.label)
            chip.setProperty("kind", "chip")
            chip.setToolTip(action.tooltip)
            chip.clicked.connect(lambda _checked=False, a=action: self.use_action(a))
            flow.addWidget(chip)
            self._chip_buttons.append(chip)
        return holder

    def _wire(self) -> None:
        self.header.character_chosen.connect(self.bridge.select_character)
        self.header.refresh_clicked.connect(self.start_refresh)
        self.header.keep_on_top_clicked.connect(self.toggle_card)
        self.refresh_banner.cancelled.connect(self._refresh_cancelled)
        self.refresh_banner.closed.connect(self._refresh_closed)
        self.questions_bar.answer_now.connect(self.answer_open_questions)
        self.bridge.open_questions_answered.connect(self._on_open_questions_answered)
        self.sign_in_card.sign_in.connect(lambda: self.navigate.emit("chatgpt"))
        self.composer.submitted.connect(self.send_question)
        self.welcome.chosen.connect(self.use_action)

    # ---- Page hooks ---------------------------------------------------------------------

    def show_state(self, state: StateView) -> None:
        """Redraw from a fresh state. Quick: no disk, no network."""
        self._state = state
        self.header.show_state(state)
        self._update_freshness()
        self.problem_banner.show_problem(state.problem)
        count = len(state.open_questions)
        from_game_is_automatic = state.settings.get("answer_questions_from_game") is True
        self.questions_bar.show_count(0 if from_game_is_automatic else count)
        self._update_signed_in(state.signed_in)
        self._update_chat(state)
        self._sync_stack()

    def on_event(self, kind: str, data: Mapping[str, object]) -> None:
        """React to one live event from the core."""
        if kind == "save":
            self._on_save(data)
        elif kind == "answer":
            self._on_answer(data)
        elif kind == "question":
            self._on_game_questions(data)
        elif kind == "error":
            self._on_error(data)
        elif kind == "info":
            self._on_info(data)
        elif kind == "signin" and data.get("state") == "signed_in":
            self.composer.focus_input()
        self._sync_stack()

    def on_theme_changed(self) -> None:
        """Light or dark mode changed: restyle this page and the small card."""
        self._restyle()
        if self._card is not None:
            self._card.update()

    def _restyle(self) -> None:
        """Apply this page's colors and redraw the button icons in them."""
        colors = current_colors()
        self.setStyleSheet(_style(colors))
        self.header.use_icons(colors)
        self.composer.use_icons(colors)

    # ---- asking -------------------------------------------------------------------------

    def use_action(self, action: QuickAction) -> None:
        """A chip or a suggestion card was picked."""
        if not self._state.signed_in:
            return
        if action.fills_composer:
            self.composer.set_text(action.question, action.cursor_position)
        else:
            self.send_question(action.question)

    def send_question(self, text: str) -> None:
        """Ask the coach. Waits for fresh data if a refresh is under way, and for the coach
        if it is busy."""
        question = text.strip()[:MAX_QUESTION_CHARS]
        if not question or not self._state.signed_in:
            return
        self._typed_questions.append(question)
        self.chat.add_player(question)
        waiting = WaitingQuestion(question, self._character)
        if self.refresh_banner.state == "waiting":
            self._fresh_questions.append(waiting)
            if self._fresh_notice is None:
                self._fresh_notice = self.chat.add_notice(WAITING_FOR_SAVE_TEXT)
        else:
            self._dispatch(waiting)
        self._sync_stack()

    def _dispatch(self, waiting: WaitingQuestion) -> None:
        """Hand a question to the bridge, or put it last in the queue when the coach is busy."""
        if len(self._queued) == 0 and self._try_to_ask(waiting):
            return
        self._queued.append(waiting)
        if not self._busy_notice_shown:
            self._busy_notice_shown = True
            self.chat.add_notice(BUSY_TEXT)
        self._queue_timer.start()

    def _try_to_ask(self, waiting: WaitingQuestion) -> bool:
        """Ask the coach now. True when it took the question (then its dots show)."""
        accepted = self.bridge.ask(waiting.text, waiting.character)
        if accepted:
            self.chat.set_typing(True)
        return accepted

    def _release_queue(self) -> None:
        """The coach finished (or failed): its dots go, and the next waiting question tries."""
        self.chat.set_typing(False)
        self._retry_queue()

    def _retry_queue(self) -> None:
        """Try to send the oldest waiting question.

        Only that one is tried, and it leaves the queue only once the coach took it, so the
        questions always go out in the order they were typed. Once the coach has one it is
        busy again, so the others wait for the next try.
        """
        if self._queued and self._try_to_ask(self._queued[0]):
            self._queued.pop(0)
        if not self._queued:
            self._queue_timer.stop()
            self._busy_notice_shown = False

    def _drop_waiting_questions(self) -> None:
        """Forget every question that has not been sent (another character was chosen)."""
        self._queued.clear()
        self._fresh_questions.clear()
        self._queue_timer.stop()
        self._busy_notice_shown = False

    def answer_open_questions(self) -> None:
        """ "Answer now" was pressed: answer the questions typed in the game.

        The bridge looks in the background; ``_on_open_questions_answered`` shows the result.
        """
        self.bridge.answer_open_questions()

    def _on_open_questions_answered(self, result: str) -> None:
        """The bridge says what "Answer now" did: started, busy, none or failed."""
        if result == "started":
            self.chat.set_typing(True)
        elif result == "busy":
            self.chat.add_notice(OPEN_BUSY_TEXT)
        elif result == "failed":
            self.chat.add_notice(DEFAULT_ERROR)
        else:
            self.chat.add_notice(OPEN_NONE_TEXT)
        self._sync_stack()

    # ---- refreshing the game data -------------------------------------------------------

    def start_refresh(self) -> None:
        """Show how to refresh and wait for the game to save."""
        self.header.refresh_button.setEnabled(False)
        self.refresh_banner.start()

    def _on_save(self, data: Mapping[str, object]) -> None:
        saved_at = data.get("saved_at")
        known = saved_at if isinstance(saved_at, int) and not isinstance(saved_at, bool) else None
        self.refresh_banner.mark_saved(known)
        self.header.refresh_button.setEnabled(True)
        self._ask_fresh_questions()

    def _refresh_cancelled(self) -> None:
        self.header.refresh_button.setEnabled(True)
        if self._fresh_questions:
            self.chat.add_notice(CANCELLED_TEXT)
            self._ask_fresh_questions()

    def _refresh_closed(self) -> None:
        self.header.refresh_button.setEnabled(True)

    def _ask_fresh_questions(self) -> None:
        """Ask the questions that waited for the save, oldest first."""
        if self._fresh_notice is not None:
            self.chat.remove(self._fresh_notice)
            self._fresh_notice = None
        waiting, self._fresh_questions = self._fresh_questions, []
        for question in waiting:
            self._dispatch(question)

    # ---- events -------------------------------------------------------------------------

    def _is_shown_character(self, data: Mapping[str, object]) -> bool:
        character = data.get("character")
        return not isinstance(character, str) or self._character in (None, character)

    def _on_answer(self, data: Mapping[str, object]) -> None:
        raw = data.get("answer")
        if isinstance(raw, Mapping) and self._is_shown_character(data):
            note = data.get("note")
            self._add_answer(
                read_answer(raw),
                live=True,
                note=note if isinstance(note, str) else "",
                written_to_game=data.get("written_to_game") is True,
            )
        self._release_queue()

    def _on_game_questions(self, data: Mapping[str, object]) -> None:
        questions = data.get("questions")
        if not isinstance(questions, list) or not self._is_shown_character(data):
            return
        for item in questions:
            if isinstance(item, Mapping):
                self._show_game_question(item.get("id"), item.get("text"))

    def _on_info(self, data: Mapping[str, object]) -> None:
        """A plain note from the core. It ends the wait too ("nothing new to answer")."""
        text = data.get("text")
        if isinstance(text, str) and text:
            self.chat.add_notice(text)
        self._release_queue()

    def _on_error(self, data: Mapping[str, object]) -> None:
        message = data.get("message")
        text = message if isinstance(message, str) and message else DEFAULT_ERROR
        is_limit = data.get("kind") == "limit"
        self.chat.add_error(text, is_limit=is_limit)
        if is_limit and self._queued:
            self._queued.clear()  # asking again right now would only hit the same limit
            self.chat.add_notice(LIMIT_QUEUE_TEXT)
        self._release_queue()

    # ---- the conversation ---------------------------------------------------------------

    def _update_chat(self, state: StateView) -> None:
        """Fill the chat from the state: everything at first, later only what is new."""
        if self._loaded and state.selected is None:
            return  # a failed read gives an empty state; keep what the player is reading
        if not self._loaded or state.selected != self._character:
            self._start_chat_for(state.selected)
            for answer in reversed(state.answers):  # the state lists the newest first
                self._add_answer(answer, live=False)
            self.chat.jump_to_newest()
            self._loaded = True
        else:
            for answer in reversed(state.answers):
                self._add_answer(answer, live=True)
        self.chat.refresh_times(self._now())

    def _start_chat_for(self, character: str | None) -> None:
        """Empty the chat: another character was chosen (or this is the first state)."""
        self._character = character
        self._seen.clear()
        self._game_questions_seen.clear()
        self._typed_questions.clear()
        self._drop_waiting_questions()
        self.chat.set_typing(False)
        self._newest = None
        self._fresh_notice = None
        self.chat.clear()
        self._show_in_card(None)

    def _add_answer(
        self, answer: AnswerView, *, live: bool, note: str = "", written_to_game: bool = False
    ) -> None:
        """Add one answer (and the question it belongs to), unless it is already there."""
        key = answer_key(answer)
        if key in self._seen:
            return
        self._seen.add(key)
        self._add_question_of(answer, animate=live)
        self.chat.add_answer(
            answer, now=self._now(), note=note, written_to_game=written_to_game, animate=live
        )
        if self._newest is None or answer.answered_at >= self._newest.answered_at:
            self._newest = answer
            self._show_in_card(answer)

    def _add_question_of(self, answer: AnswerView, *, animate: bool) -> None:
        """Show the question that led to an answer, unless the chat already shows it."""
        if not answer.question:
            return
        if answer.question_id is not None:
            self._show_game_question(answer.question_id, answer.question, animate=animate)
            return
        question = answer.question.strip()
        if question in self._typed_questions:
            self._typed_questions.remove(question)  # already shown when the player sent it
            return
        self.chat.add_player(question, animate=animate)

    def _show_game_question(
        self, question_id: object, text: object, *, animate: bool = True
    ) -> None:
        if not isinstance(question_id, str) or not isinstance(text, str):
            return
        if question_id in self._game_questions_seen:
            return
        self._game_questions_seen.add(question_id)
        self.chat.add_player(text, tag="from the game", animate=animate)

    # ---- small helpers ------------------------------------------------------------------

    def _update_signed_in(self, signed_in: bool) -> None:
        self.sign_in_card.setVisible(not signed_in)
        self.composer.set_input_enabled(signed_in)
        self.welcome.set_cards_enabled(signed_in)
        for chip in self._chip_buttons:
            chip.setEnabled(signed_in)

    def _sync_stack(self) -> None:
        """Show the welcome while the chat is empty, the conversation otherwise."""
        empty = self.chat.message_count() == 0
        self.stack.setCurrentIndex(_WELCOME_PAGE if empty else _CHAT_PAGE)

    def _update_freshness(self) -> None:
        self.header.pill.show_freshness(freshness(self._state.last_save, self._now()))

    def _tick(self) -> None:
        """Every 30 seconds: "12 min old" and "5 min ago" move on. Reads nothing from disk."""
        self._update_freshness()
        self.chat.refresh_times(self._now())

    # ---- the "keep on top" card ---------------------------------------------------------

    def toggle_card(self) -> None:
        """Show or hide the small always-on-top card."""
        if self._card is not None and self._card.isVisible():
            self._card.close()
            return
        if self._card is None:
            self._card = CompactCard(self._card_settings)
            self._card.open_requested.connect(self._raise_main_window)
            self._card.closed.connect(lambda: self.header.show_card_open(False))
            self._card.show_answer(self._newest)
        self._card.show_at_saved_position()
        self.header.show_card_open(True)

    @property
    def card(self) -> CompactCard | None:
        """The small card, once it was opened."""
        return self._card

    def _show_in_card(self, answer: AnswerView | None) -> None:
        if self._card is not None:
            self._card.show_answer(answer)

    def _raise_main_window(self) -> None:
        window = self.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def _close_card(self) -> None:
        if self._card is not None:
            self._card.close()
