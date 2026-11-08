"""The Settings page: answers, what the coach says after a save, and privacy choices.

There is no "Save" button. A change is saved about 0.4 seconds after the last one (so typing
a number does not save after every key), and a small "Saved" appears.

While the player is editing, a new state from the core never overwrites their field.

Until the first state that really holds the saved settings arrives, every field is disabled
under a "Loading your settings..." line: the fields hold only Qt defaults (0, unchecked) then,
and saving those would wipe the player's real settings. Only the fields the player actually
changed are ever saved.
"""

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.forms import Card, ToggleRow, make_label, page_header, scrollable
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.state import StateView
from wow_coach.desktop.theme import SPACE, Colors, current_colors

SAVE_DELAY_MS: Final = 400  # wait this long after the last change before saving
SAVED_SHOWN_MS: Final = 2000  # how long "Saved" stays visible
LABEL_WIDTH: Final = 300  # the width of the label column in the form rows
LOADING_TEXT: Final = "Loading your settings\u2026"

# The saved fields that are not "when the game saves" (those travel in one "triggers" dict).
SIMPLE_KEYS: Final = (
    "answer_questions_from_game",
    "notify",
    "share_other_player_names",
    "send_coach_notes",
    "use_claude_chats",
    "use_tools",
    "web_search",
    "save_notes",
    "show_lookups",
)
# The coach-tools switches are all on until the player turns one off.
TOOL_KEYS: Final = ("use_tools", "web_search", "save_notes", "show_lookups")

# The choices for "When the game saves", with the words the player sees (same as the browser).
ON_SAVE_CHOICES: Final = (
    ("off", "Off"),
    ("notify", "Tell me what's worth knowing"),
    ("advice", "Tell me and add the coach's advice"),
)


def _style(c: Colors) -> str:
    """Page-specific styles: the small "Saved" note and the problem message."""
    return f"""
QLabel#saved {{ color: {c.success}; font-weight: 600; }}
QLabel#problem {{
    background: {c.surface_raised}; border-left: 3px solid {c.warning};
    border-radius: 4px; padding: 8px 12px;
}}
"""


def _as_int(value: object, default: int) -> int:
    """``value`` as a whole number (a bool is not a number), else ``default``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _as_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


class SettingsPage(Page):
    """Answers, what the coach says after a save, and privacy choices."""

    name = "settings"
    title = "Settings"

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(bridge, parent)
        self._loading = False  # True while the page fills its own fields (no saving then)
        self._settings_loaded = False  # True once a state really held the saved settings
        self._saved_values: dict[str, object] = {}  # what the core has saved, to spot edits
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_now)
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.setInterval(SAVED_SHOWN_MS)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE)
        column.addLayout(page_header("Settings", "Changes are saved for you as you make them."))
        self.saved_label = make_label("Saved")
        self.saved_label.setObjectName("saved")
        self.problem_label = make_label("")
        self.problem_label.setObjectName("problem")
        self._saved_timer.timeout.connect(self.saved_label.hide)
        self.saved_label.hide()
        self.problem_label.hide()
        self.loading_label = make_label(LOADING_TEXT, "muted")
        column.addWidget(self.saved_label)
        column.addWidget(self.problem_label)
        column.addWidget(self.loading_label)

        # All the cards live in one widget, so they can be disabled together while loading.
        self.form = QWidget()
        form_column = QVBoxLayout(self.form)
        form_column.setContentsMargins(0, 0, 0, 0)
        form_column.setSpacing(SPACE)
        form_column.addWidget(self._build_answers_card())
        form_column.addWidget(self._build_tools_card())
        form_column.addWidget(self._build_triggers_card())
        form_column.addWidget(self._build_privacy_card())
        self.form.setEnabled(False)
        column.addWidget(self.form)
        column.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(content))
        self.on_theme_changed()

    # ---- building ------------------------------------------------------------------------

    def _toggle(self, card: Card, text: str, description: str, tooltip: str) -> ToggleRow:
        """Add a check box row to ``card``; any change schedules a save."""
        row = ToggleRow(text, description, tooltip)
        row.check.toggled.connect(self._edited)
        card.body.addWidget(row)
        return row

    def _build_answers_card(self) -> Card:
        card = Card("Answers")
        self.answer_games = self._toggle(
            card,
            "Answer questions typed in the game",
            "When you ask in the game's Coach panel, the answer appears there by itself.",
            "Answer the questions you type in the game as soon as the game saves them.",
        )
        self.notify = self._toggle(
            card,
            "Show a notification when an answer is ready",
            "A small message on your desktop, so you can stay in the game.",
            "Show a desktop notification for each answer.",
        )
        return card

    def _build_tools_card(self) -> Card:
        card = Card(
            "Coach tools",
            "While answering, the coach can look things up the way your Claude coach does. "
            "Under each answer you see where it looked, with links to the pages it used.",
        )
        self.use_tools = self._toggle(
            card,
            "Let the coach look things up (your status, notes, the Warcraft Wiki)",
            "The coach reads your character's data and notes, and searches and reads "
            "Warcraft Wiki pages, instead of guessing.",
            "Give the coach tools to read your data and the Warcraft Wiki while it answers.",
        )
        self.web_search = self._toggle(
            card,
            "Let the coach search the web too",
            "OpenAI runs the search as part of your ChatGPT plan. Only the search words "
            "leave this computer.",
            "Let the coach use OpenAI's web search for things the wiki does not have.",
        )
        self.save_notes = self._toggle(
            card,
            "Let the coach update your notebook",
            "It can save your goals and progress in your notes. Your last 20 versions are "
            "kept, so a mistake can be undone.",
            "Let the coach save your player notes and the character journal.",
        )
        self.show_lookups = self._toggle(
            card,
            "Show what the coach looked up",
            "A line while it works, and a list under each answer.",
            "Show the coach's lookups in the chat.",
        )
        return card

    def _build_triggers_card(self) -> Card:
        card = Card(
            "Coach on its own",
            "The game only shares your character when it saves (a /reload, logging out, or "
            "the Save for the coach key), so this happens right after a save, never live. "
            "Worth knowing is worked out here from what changed since the last save, "
            "for free: a level-up, nearly full bags, a finished quest, a death, unspent "
            "talent points, worn gear, a new zone.",
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setVerticalSpacing(SPACE)
        self.on_save_box = QComboBox()
        for choice, text in ON_SAVE_CHOICES:
            self.on_save_box.addItem(text, choice)
        self.on_save_box.setToolTip(
            "What the coach does after the game saves. The advice choice uses one call of "
            "your plan per save, at most."
        )
        self.on_save_box.setAccessibleName("When the game saves")
        self.on_save_box.activated.connect(self._edited)
        form.addRow(self._buddy_label("When the game saves", self.on_save_box), self.on_save_box)
        card.body.addLayout(form)

        self.quiet_instances = self._toggle(
            card,
            "Stay quiet in dungeons and raids",
            "No unasked notes or advice while you are in an instance.",
            "Keep the coach quiet inside dungeons and raids.",
        )
        return card

    def _buddy_label(self, text: str, field: QWidget) -> QLabel:
        """A label tied to ``field``, so a screen reader and the Alt+key shortcuts find it."""
        label = make_label(text)
        label.setMinimumWidth(LABEL_WIDTH)  # one tidy column for all the form rows
        label.setBuddy(field)
        return label

    def _build_privacy_card(self) -> Card:
        card = Card("Privacy")
        self.share_names = self._toggle(
            card,
            "Share other players' names with the AI",
            "Off: names of group members, mail senders and so on are replaced by "
            '"a player" before anything leaves this computer.',
            "Send other players' names to the AI. Off is the private choice.",
        )
        self.send_notes = self._toggle(
            card,
            "Send my coach notes",
            "Your own notes and the character journal help the coach remember your goals. "
            "Off: they stay on this computer, and answers fit you a little less.",
            "Send your notes and the character journal with each question.",
        )
        self.use_claude_chats = self._toggle(
            card,
            "Use my Claude coach chats",
            "Show your chats with your Claude coach here and let the coach read them, so it "
            "knows what you already talked about. Off: they are not imported or sent.",
            "Import your Claude Code coach chats and use them as context.",
        )
        return card

    # ---- showing the state ---------------------------------------------------------------

    def show_state(self, state: StateView) -> None:
        """Fill the fields from the saved settings, unless the player is editing them."""
        self.notify.set_available(
            state.notify_available, "This computer can't show desktop notifications."
        )
        if not state.settings:
            return  # nothing read yet, or a failed read: keep what the fields already show
        if self._save_timer.isActive():
            return  # the player has unsaved edits; never overwrite them
        self._loading = True
        try:
            self._fill(state.settings)
        finally:
            self._loading = False
        self._saved_values = self._values_from(state.settings)
        if not self._settings_loaded:
            self._settings_loaded = True
            self.form.setEnabled(True)
            self.loading_label.hide()

    def _fill(self, settings: Mapping[str, object]) -> None:
        """Copy saved values into the fields the player is not using right now."""
        self._set_check(self.answer_games, settings.get("answer_questions_from_game"), True)
        self._set_check(self.notify, settings.get("notify"), True)
        self._set_check(self.share_names, settings.get("share_other_player_names"), False)
        self._set_check(self.send_notes, settings.get("send_coach_notes"), True)
        self._set_check(self.use_claude_chats, settings.get("use_claude_chats"), True)
        for key in TOOL_KEYS:
            self._set_check(getattr(self, key), settings.get(key), True)
        self._fill_triggers(_as_mapping(settings.get("triggers")))

    def _fill_triggers(self, rules: Mapping[str, object]) -> None:
        index = self.on_save_box.findData(rules.get("on_save", "notify"))
        if not self.on_save_box.hasFocus():
            self.on_save_box.setCurrentIndex(max(index, 0))
        self._set_check(self.quiet_instances, rules.get("quiet_in_instances"), True)

    def _set_check(self, row: ToggleRow, value: object, default: bool) -> None:
        if not row.check.hasFocus():
            row.check.setChecked(value if isinstance(value, bool) else default)

    def on_theme_changed(self) -> None:
        """Light or dark mode changed: restyle."""
        self.setStyleSheet(_style(current_colors()))

    # ---- saving --------------------------------------------------------------------------

    def _edited(self, *_ignored: object) -> None:
        """A field changed: (re)start the short wait before saving."""
        if self._loading:
            return
        self._save_timer.start()

    def save_now(self) -> None:
        """Save what the fields hold now, or explain what is wrong with them."""
        self._save_timer.stop()
        changes = self._collect_changes()
        if changes:
            self.bridge.change_settings(changes)
            self._remember_saved(changes)
            self.saved_label.show()
            self._saved_timer.start()

    def _remember_saved(self, changes: Mapping[str, object]) -> None:
        """Note what was just saved, so the next edit only sends what is new."""
        for key, value in changes.items():
            if key == "triggers":
                old_rules = _as_mapping(self._saved_values.get("triggers"))
                self._saved_values["triggers"] = {**old_rules, **_as_mapping(value)}
            else:
                self._saved_values[key] = value

    def _collect_changes(self) -> dict[str, object]:
        """Only the fields the player changed.

        Saving just the changed fields means one edit can never overwrite a setting the
        player did not touch. ``update_settings`` keeps every field that is left out.
        """
        if not self._settings_loaded:
            return {}  # the fields do not show the saved settings yet
        now = self._current_values()
        changes = {key: now[key] for key in SIMPLE_KEYS if now[key] != self._saved_values.get(key)}
        rules = _as_mapping(now["triggers"])
        old_rules = _as_mapping(self._saved_values.get("triggers"))
        changed_rules = {k: v for k, v in rules.items() if v != old_rules.get(k)}
        if changed_rules:
            changes["triggers"] = changed_rules
        return changes

    def _current_values(self) -> dict[str, object]:
        """What the fields hold now, in the shape the core saves."""
        return {
            "answer_questions_from_game": self.answer_games.check.isChecked(),
            "notify": self.notify.check.isChecked(),
            "share_other_player_names": self.share_names.check.isChecked(),
            "send_coach_notes": self.send_notes.check.isChecked(),
            "use_claude_chats": self.use_claude_chats.check.isChecked(),
            **{key: getattr(self, key).check.isChecked() for key in TOOL_KEYS},
            "triggers": self._trigger_values(),
        }

    def _values_from(self, settings: Mapping[str, object]) -> dict[str, object]:
        """The saved ``settings`` in the same shape as ``_current_values`` (same defaults)."""
        rules = _as_mapping(settings.get("triggers"))
        return {
            "answer_questions_from_game": _as_bool(
                settings.get("answer_questions_from_game"), True
            ),
            "notify": _as_bool(settings.get("notify"), True),
            "share_other_player_names": _as_bool(settings.get("share_other_player_names"), False),
            "send_coach_notes": _as_bool(settings.get("send_coach_notes"), True),
            "use_claude_chats": _as_bool(settings.get("use_claude_chats"), True),
            **{key: _as_bool(settings.get(key), True) for key in TOOL_KEYS},
            "triggers": {
                "on_save": rules.get("on_save", "notify"),
                "quiet_in_instances": _as_bool(rules.get("quiet_in_instances"), True),
            },
        }

    def _trigger_values(self) -> dict[str, object]:
        return {
            "on_save": self.on_save_box.currentData(),
            "quiet_in_instances": self.quiet_instances.check.isChecked(),
        }
