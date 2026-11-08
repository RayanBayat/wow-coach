"""The ChatGPT page: sign in, see your plan usage, pick a model, sign out.

Three looks, one at a time:

* **Signed out**: what signing in does, a short privacy summary (OpenAI's program asks for
  a privacy notice before the first sign-in), and the "Continue with ChatGPT" button.
* **Waiting**: the browser is open and the player is finishing the sign-in there.
* **Signed in**: "Using ChatGPT plan", usage meters, the model picker and "Sign out".

OpenAI's wording rules for this page are kept as they are: the button says "Continue with
ChatGPT", the app uses its own name and no OpenAI logo, and the one-time welcome message
(``welcome.py``) is shown after the first sign-in.
"""

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.forms import (
    USAGE_URL,
    Card,
    WaitingSpinner,
    link_button,
    make_button,
    make_label,
    open_link,
    page_header,
    scrollable,
)
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.state import StateView, UsageView
from wow_coach.desktop.theme import SPACE, Colors, current_colors
from wow_coach.desktop.welcome import WelcomeDialog

SIGN_IN_BUTTON_TEXT: Final = "Continue with ChatGPT"  # OpenAI's required wording
PLAN_LINE: Final = "Using ChatGPT plan"  # OpenAI's required wording
SIGN_IN_PAGE_START: Final = (
    "https://auth.openai.com/"  # the only address we ever open from an event
)
RECOMMENDED_MODEL: Final = "Recommended (automatic)"

# What the page is doing about signing in.
IDLE: Final = "idle"
WAITING: Final = "waiting"

PRIVACY_SUMMARY: Final = (
    "Before you sign in: when you ask the coach, wow-coach sends your character's data, your "
    "questions, the recent conversation and the coach's notes (you can turn the notes off in "
    "Settings) to OpenAI, using your ChatGPT plan. Other players' names are hidden unless you "
    "allow them. Nothing else leaves this computer."
)
SIGNED_OUT_NOT_CONFIRMED: Final = (
    "You are signed out of wow-coach, but OpenAI did not confirm it. To be sure, disconnect "
    "wow-coach in your ChatGPT settings: open ChatGPT, go to Settings, and remove wow-coach "
    "from your connected apps."
)
BUSY_MESSAGE: Final = (
    "Your earlier sign-in is still open. You can finish it in your browser with the buttons "
    "below. If you leave it, it expires within 5 minutes, and then you can start again."
)
HIDE_TOOLTIP: Final = (
    "Hide this and go back. The sign-in page in your browser stays valid for a few minutes."
)
BROWSER_HINT: Final = (
    "OpenAI shows its own sign-in page in your browser. WoW Coach never sees your password."
)


def _style(c: Colors) -> str:
    """Page-specific styles: the status dot, the usage bars and the calm notices."""
    return f"""
QLabel#statusDot {{ background: {c.success}; border-radius: 5px; }}
QLabel#notice {{
    background: {c.surface_raised}; border: 1px solid {c.border}; border-radius: 8px;
    padding: 10px 12px;
}}
QLabel#problem {{
    background: {c.surface_raised}; border-left: 3px solid {c.warning};
    border-radius: 4px; padding: 10px 12px;
}}
QProgressBar#meter {{ background: {c.border}; border: none; border-radius: 3px; }}
QProgressBar#meter::chunk {{ background: {c.accent}; border-radius: 3px; }}
QProgressBar#meter[level="warn"]::chunk {{ background: {c.warning}; }}
QProgressBar#meter[level="full"]::chunk {{ background: {c.danger}; }}
"""


class ChatGPTPage(Page):
    """Your ChatGPT sign-in."""

    name = "chatgpt"
    title = "ChatGPT"

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(bridge, parent)
        self._phase = IDLE
        self._sign_in_url: str | None = None
        self._error = ""  # the last sign-in problem, shown until the next try
        self._models_requested = False
        self._welcome_shown = False  # shown at most once per run, even if closed with Esc
        self.welcome_dialog: WelcomeDialog | None = None
        self._welcome_waiting = False  # wanted, but the window is hidden (tray) for now

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE)
        column.addLayout(
            page_header("ChatGPT", "WoW Coach thinks with your own ChatGPT plan, nothing extra.")
        )
        self._problem = make_label("")
        self._problem.setObjectName("problem")
        self._notice = make_label("")
        self._notice.setObjectName("notice")
        column.addWidget(self._problem)
        column.addWidget(self._notice)
        self._signed_out_card = self._build_signed_out_card()
        self._waiting_card = self._build_waiting_card()
        self._signed_in_card = self._build_signed_in_card()
        for card in (self._signed_out_card, self._waiting_card, self._signed_in_card):
            column.addWidget(card)
        column.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(content))

        bridge.models_loaded.connect(self._on_models_loaded)
        bridge.signed_out.connect(self._on_signed_out)
        self.on_theme_changed()
        self._refresh_cards()

    # ---- building ------------------------------------------------------------------------

    def _build_signed_out_card(self) -> Card:
        card = Card("Get answers with your ChatGPT plan")
        card.body.addWidget(
            make_label(
                "Sign in once and the coach answers using the ChatGPT plan you already have. "
                "There is no extra cost beyond your plan, and you can sign out any time."
            )
        )
        card.body.addWidget(make_label(BROWSER_HINT, "muted"))
        card.body.addWidget(make_label(PRIVACY_SUMMARY, "small"))
        self._error_label = make_label("", "error")
        card.body.addWidget(self._error_label)

        row = QHBoxLayout()
        self.sign_in_button = make_button(
            SIGN_IN_BUTTON_TEXT,
            "primary",
            "Open OpenAI's sign-in page in your browser.",
        )
        self.sign_in_button.setDefault(True)
        self.sign_in_button.clicked.connect(self._start_sign_in)
        self.privacy_button = make_button(
            "What is sent?", "ghost", "Read in plain words what leaves this computer."
        )
        self.privacy_button.clicked.connect(lambda _checked=False: self.navigate.emit("privacy"))
        row.addWidget(self.sign_in_button)
        row.addWidget(self.privacy_button)
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _build_waiting_card(self) -> Card:
        card = Card()
        heading = QHBoxLayout()
        self.spinner = WaitingSpinner()
        heading.addWidget(self.spinner)
        heading.addWidget(make_label("Finish signing in in your browser...", "subtitle"), 1)
        card.body.addLayout(heading)
        card.body.addWidget(
            make_label(
                "A page from OpenAI should have opened. Sign in there and allow WoW Coach. "
                "This window continues by itself when you are done.",
                "muted",
            )
        )
        card.body.addWidget(
            make_label(
                "Nothing opened? Use the buttons below. Changed your mind? Press Hide this and "
                "just close the browser tab. An unfinished sign-in expires after a few minutes.",
                "small",
            )
        )
        row = QHBoxLayout()
        self.open_again_button = make_button(
            "Open the sign-in page again",
            "secondary",
            "Open OpenAI's sign-in page in your browser again.",
        )
        self.open_again_button.clicked.connect(self._open_sign_in_page)
        self.copy_link_button = make_button(
            "Copy link", "ghost", "Copy the sign-in link, to paste into another browser."
        )
        self.copy_link_button.clicked.connect(self._copy_sign_in_link)
        # Honest name: the core cannot cancel a running sign-in, this only hides the card.
        self.hide_button = make_button("Hide this", "ghost", HIDE_TOOLTIP)
        self.hide_button.clicked.connect(self._hide_waiting)
        row.addWidget(self.open_again_button)
        row.addWidget(self.copy_link_button)
        row.addStretch(1)
        row.addWidget(self.hide_button)
        card.body.addLayout(row)
        return card

    def _build_signed_in_card(self) -> Card:
        card = Card()
        status = QHBoxLayout()
        dot = QLabel()
        dot.setObjectName("statusDot")
        dot.setFixedSize(10, 10)
        status.addWidget(dot)
        status.addWidget(make_label(PLAN_LINE, "subtitle"), 1)
        self.manage_usage_button = link_button(
            "Manage usage", USAGE_URL, "Open your ChatGPT usage settings in the browser."
        )
        status.addWidget(self.manage_usage_button)
        card.body.addLayout(status)
        card.body.addWidget(
            make_label(
                "The coach's answers count toward your ChatGPT plan, and only the plan's "
                "own limits apply.",
                "muted",
            )
        )
        self.hour_used = make_label("")
        self.day_used = make_label("")
        card.body.addWidget(self.hour_used)
        card.body.addWidget(self.day_used)

        card.body.addWidget(make_label("Model", "subtitle"))
        self.model_box = QComboBox()
        self.model_box.setToolTip("Which model on your plan answers. Recommended picks for you.")
        self.model_box.setAccessibleName("Model")
        self.model_box.addItem(RECOMMENDED_MODEL, None)
        self.model_box.activated.connect(self._model_chosen)
        card.body.addWidget(self.model_box)
        self.model_note = make_label("", "small")
        card.body.addWidget(self.model_note)

        self.sign_out_button = make_button(
            "Sign out", "danger", "Forget the ChatGPT sign-in on this computer."
        )
        self.sign_out_button.clicked.connect(self._sign_out_clicked)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.sign_out_button)
        card.body.addLayout(row)
        return card

    # ---- the state -----------------------------------------------------------------------

    def show_state(self, state: StateView) -> None:
        """Redraw from the newest state."""
        if state.signed_in:
            self._phase = IDLE
            self._error = ""
            self._request_models_once()
        else:
            self._models_requested = False
            self._welcome_shown = False
        self._problem.setText(state.problem or "")
        self._problem.setVisible(bool(state.problem))
        self._refresh_cards(state.signed_in)
        self._show_usage(state.usage)
        self._show_chosen_model(state.settings.get("model"))
        self._welcome_waiting = state.signed_in and state.welcome_pending
        if self._welcome_waiting:
            self._show_welcome_when_visible()

    def _refresh_cards(self, signed_in: bool = False) -> None:
        """Show the card that fits: signed in, waiting for the browser, or signed out."""
        waiting = self._phase == WAITING and not signed_in
        self._signed_in_card.setVisible(signed_in)
        self._waiting_card.setVisible(waiting)
        self._signed_out_card.setVisible(not signed_in and not waiting)
        # The button keeps OpenAI's wording; the error and "try again" go above it.
        self._error_label.setText(f"{self._error} Please try again." if self._error else "")
        self._error_label.setVisible(bool(self._error))
        self.open_again_button.setEnabled(self._sign_in_url is not None)
        self.copy_link_button.setEnabled(self._sign_in_url is not None)

    def _set_notice(self, text: str) -> None:
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    def on_theme_changed(self) -> None:
        """Light or dark mode changed: restyle."""
        self.setStyleSheet(_style(current_colors()))
        self._set_notice(self._notice.text())

    # ---- live events ---------------------------------------------------------------------

    def on_event(self, kind: str, data: Mapping[str, object]) -> None:
        """React to the core's sign-in progress and sign-in errors."""
        if kind == "signin":
            self._on_signin_event(data)
        elif kind == "error" and self._phase == WAITING:
            message = data.get("message")
            self._phase = IDLE
            self._error = (
                message if isinstance(message, str) and message else ("The sign-in did not finish.")
            )
            self._refresh_cards()

    def _on_signin_event(self, data: Mapping[str, object]) -> None:
        progress = data.get("state")
        if progress == "waiting":
            url = data.get("url")
            # Only OpenAI's own sign-in page is ever opened from an event.
            if isinstance(url, str) and url.startswith(SIGN_IN_PAGE_START):
                self._sign_in_url = url
            self._phase = WAITING
            self._refresh_cards()
        elif progress == "signed_in":
            self._phase = IDLE
            self._sign_in_url = None
            self._set_notice("You're signed in. The coach now answers with your ChatGPT plan.")
            self._refresh_cards(signed_in=True)
        elif progress == "signed_out":
            self._phase = IDLE
            self._refresh_cards()

    # ---- signing in ----------------------------------------------------------------------

    def _start_sign_in(self) -> None:
        self._error = ""
        self._set_notice("")
        self._phase = WAITING
        if self.bridge.start_sign_in():
            self._sign_in_url = None  # the new sign-in sends its own address
        else:
            # An earlier sign-in still runs in the core (up to 5 minutes). Keep its address,
            # so "Open the sign-in page again" and "Copy link" keep working.
            self._set_notice(BUSY_MESSAGE)
        self._refresh_cards()

    def _open_sign_in_page(self) -> None:
        if self._sign_in_url is not None:
            open_link(self._sign_in_url)

    def _copy_sign_in_link(self) -> None:
        if self._sign_in_url is not None:
            QApplication.clipboard().setText(self._sign_in_url)
            self._set_notice("Link copied. Paste it into your browser's address bar.")

    def _hide_waiting(self) -> None:
        """Go back to the start. The address is kept: the browser page may still work."""
        self._phase = IDLE
        self._set_notice("")
        self._refresh_cards()

    # ---- the model -----------------------------------------------------------------------

    def _request_models_once(self) -> None:
        if not self._models_requested:
            self._models_requested = True
            self.bridge.load_models()

    def _on_models_loaded(self, models: object) -> None:
        """Fill the model picker with what the plan can use."""
        chosen = self.model_box.currentData()
        self.model_box.clear()
        self.model_box.addItem(RECOMMENDED_MODEL, None)
        found = models if isinstance(models, list) else []
        for model in found:
            if isinstance(model, Mapping) and isinstance(model.get("slug"), str):
                label = model.get("name")
                slug = str(model["slug"])
                self.model_box.addItem(label if isinstance(label, str) and label else slug, slug)
        self.model_note.setText(
            ""
            if self.model_box.count() > 1
            else "The model list could not be loaded. The coach picks one for you."
        )
        self._show_chosen_model(self.bridge.latest_state.settings.get("model", chosen))

    def _show_chosen_model(self, slug: object) -> None:
        """Select the saved model in the picker (a model not in the list is added)."""
        if self.model_box.hasFocus():
            return  # the player is choosing right now
        wanted = slug if isinstance(slug, str) and slug else None
        index = self.model_box.findData(wanted)
        if index < 0 and wanted is not None:
            self.model_box.addItem(wanted, wanted)
            index = self.model_box.count() - 1
        self.model_box.setCurrentIndex(max(index, 0))

    def _model_chosen(self, index: int) -> None:
        """Save the player's choice ("Recommended" is saved as no model at all)."""
        self.bridge.change_settings({"model": self.model_box.itemData(index)})

    def _show_usage(self, usage: UsageView) -> None:
        self.hour_used.setText(f"Questions in the last hour: {usage.last_hour}")
        self.day_used.setText(f"Questions today: {usage.last_day}")

    # ---- signing out ---------------------------------------------------------------------

    def _confirm_sign_out(self) -> bool:
        """Ask "Sign out?" and return True when the player agrees."""
        answer = QMessageBox.question(
            self,
            "Sign out of ChatGPT?",
            "WoW Coach will forget your ChatGPT sign-in on this computer. "
            "You can sign in again any time.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _sign_out_clicked(self) -> None:
        if self._confirm_sign_out():
            self.sign_out_button.setEnabled(False)  # one sign-out at a time
            self.bridge.sign_out()

    def _on_signed_out(self, confirmed: bool) -> None:
        """The sign-out finished; say plainly how it went."""
        self.sign_out_button.setEnabled(True)
        self._set_notice("Signed out." if confirmed else SIGNED_OUT_NOT_CONFIRMED)

    # ---- the welcome message -------------------------------------------------------------

    def _show_welcome_when_visible(self) -> None:
        """Show the welcome message now, or as soon as the window is shown.

        The app can start hidden in the tray at login; a dialog must not pop up and take
        focus then. So it waits for the window's Show event.
        """
        window = self.window()
        if window.isVisible():
            self._show_welcome_once()
        else:
            window.installEventFilter(self)  # installing it again changes nothing

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt name)
        """Watch the window for being shown, to show a welcome message that had to wait."""
        if event.type() == QEvent.Type.Show and self._welcome_waiting and watched is self.window():
            self._welcome_waiting = False
            QTimer.singleShot(0, self._show_welcome_if_visible)  # after the window has shown
        return super().eventFilter(watched, event)

    def _show_welcome_if_visible(self) -> None:
        if self.window().isVisible():
            self._show_welcome_once()

    def _show_welcome_once(self) -> None:
        """Show the welcome message, but never twice in a row and never stacked."""
        if self._welcome_shown:
            return
        self._welcome_shown = True
        dialog = WelcomeDialog(self.bridge, self.window())
        self.welcome_dialog = dialog
        dialog.open()  # does not block the window
