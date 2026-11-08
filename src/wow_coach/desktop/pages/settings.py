"""The Settings page: answers, the coach speaking up by itself, limits and privacy choices.

There is no "Save" button. A change is saved about 0.4 seconds after the last one (so typing
a number does not save after every key), and a small "Saved" appears. A value that cannot
work (for example a timer of 3 minutes) is not saved; a plain message says what to fix.

While the player is editing, a new state from the core never overwrites their field.
"""

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wow_coach.app_settings import MAX_CALLS_PER_DAY_LIMIT, MAX_CALLS_PER_HOUR_LIMIT
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.forms import Card, ToggleRow, make_label, page_header, scrollable
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.state import StateView, UsageView
from wow_coach.desktop.theme import SPACE, Colors, current_colors
from wow_coach.triggers.settings import (
    MAX_COOLDOWN_MINUTES,
    MAX_RULES_CHARS,
    MAX_TIMER_MINUTES,
    MIN_TIMER_MINUTES,
)

SAVE_DELAY_MS: Final = 400  # wait this long after the last change before saving
SAVED_SHOWN_MS: Final = 2000  # how long "Saved" stays visible
LABEL_WIDTH: Final = 300  # the width of the label column in the form rows
NO_HOUR: Final = -1  # the "Off" position of a quiet-hours box

# The events the player can give a rule to, in the order shown (same words as the browser window).
TRIGGER_KINDS: Final = (
    ("died", "You die"),
    ("died_again_soon", "You die again soon after coming back"),
    ("level_up", "You level up"),
    ("quest_done", "A quest is ready to turn in"),
    ("bags_nearly_full", "Your bags are nearly full"),
    ("new_zone", "You enter a new zone"),
    ("talent_points", "You have unspent talent points"),
    ("gear_hint", "The coach spots a possible gear upgrade"),
    ("durability_low", "Your gear needs repair"),
    ("timer", "The timer goes off"),
)
MODE_CHOICES: Final = (
    ("off", "Off"),
    ("notify", "Notify me"),
    ("coach", "Ask the coach"),
)

TIMER_PROBLEM: Final = (
    f"The timer must be 0 (never) or between {MIN_TIMER_MINUTES} and {MAX_TIMER_MINUTES} "
    'minutes. Nothing in "Coach on its own" was saved yet.'
)
QUIET_PROBLEM: Final = (
    "Quiet hours need both a start and an end hour, or both set to Off. "
    'Nothing in "Coach on its own" was saved yet.'
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


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


class SettingsPage(Page):
    """Answers, the coach on its own, limits and privacy choices."""

    name = "settings"
    title = "Settings"

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(bridge, parent)
        self._loading = False  # True while the page fills its own fields (no saving then)
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
        column.addWidget(self.saved_label)
        column.addWidget(self.problem_label)

        column.addWidget(self._build_answers_card())
        column.addWidget(self._build_triggers_card())
        column.addWidget(self._build_limits_card())
        column.addWidget(self._build_privacy_card())
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

    def _spin(self, low: int, high: int, tooltip: str, suffix: str = "") -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSuffix(suffix)
        box.setToolTip(tooltip)
        box.setMinimumWidth(110)
        box.valueChanged.connect(self._edited)
        return box

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
        self.speak = self._toggle(
            card,
            "Read answers aloud",
            "The coach speaks each answer. Off by default.",
            "Read each answer aloud.",
        )
        return card

    def _build_triggers_card(self) -> Card:
        card = Card(
            "Coach on its own",
            'Every rule starts as Off: the coach only answers when you ask. "Notify me" '
            'shows a short note and uses nothing from your plan. "Ask the coach" gives '
            "advice and uses one call.",
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setVerticalSpacing(SPACE)
        self.mode_boxes: dict[str, QComboBox] = {}
        for kind, label in TRIGGER_KINDS:
            box = QComboBox()
            for mode, text in MODE_CHOICES:
                box.addItem(text, mode)
            box.setToolTip(f"What should happen when: {label.lower()}.")
            box.setAccessibleName(label)
            box.activated.connect(self._edited)
            self.mode_boxes[kind] = box
            form.addRow(self._buddy_label(label, box), box)
        card.body.addLayout(form)

        self.timer_minutes = self._spin(
            0,
            MAX_TIMER_MINUTES,
            "How often the timer goes off. 0 means never.",
            " min",
        )
        self.timer_minutes.setSpecialValueText("Never")
        self.timer_minutes.setSingleStep(5)
        self.cooldown = self._spin(
            0,
            MAX_COOLDOWN_MINUTES,
            "The least time between answers the coach starts itself.",
            " min",
        )
        timing = QFormLayout()
        timing.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        timing.setVerticalSpacing(SPACE)
        timing.addRow(
            self._buddy_label("Timer: ask the coach every", self.timer_minutes), self.timer_minutes
        )
        timing.addRow(
            self._buddy_label("Wait at least this long between answers", self.cooldown),
            self.cooldown,
        )
        card.body.addLayout(timing)
        card.body.addWidget(
            make_label(
                f"The timer can be Never, or {MIN_TIMER_MINUTES} to {MAX_TIMER_MINUTES} minutes. "
                "The wait between answers stops the coach from talking too much.",
                "small",
            )
        )

        self.quiet_instances = self._toggle(
            card,
            "Stay quiet in dungeons and raids",
            "No unasked notes or advice while you are in an instance.",
            "Keep the coach quiet inside dungeons and raids.",
        )
        self.quiet_from = self._hour_box("The hour quiet time starts.")
        self.quiet_to = self._hour_box("The hour quiet time ends.")
        quiet = QFormLayout()
        quiet.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        quiet.setVerticalSpacing(SPACE)
        quiet.addRow(self._buddy_label("Quiet hours from", self.quiet_from), self.quiet_from)
        quiet.addRow(self._buddy_label("Quiet hours until", self.quiet_to), self.quiet_to)
        card.body.addLayout(quiet)
        card.body.addWidget(
            make_label(
                "The hour of the day, from 0 to 23, on this computer's clock. Off means the "
                "coach is never quiet by the clock.",
                "small",
            )
        )

        self.use_triage = self._toggle(
            card,
            "Let a small AI decide what is worth the coach's time",
            "A small, fast model reads what happened and your own words below. It uses a "
            "little of your plan.",
            "Use a small AI to filter events before waking the coach.",
        )
        self.rules_text = QPlainTextEdit()
        self.rules_text.setPlaceholderText("For example: only if I die twice in 10 minutes")
        self.rules_text.setToolTip("Your own words: when should the coach speak up?")
        self.rules_text.setAccessibleName("In your own words, when should the coach speak up?")
        self.rules_text.setFixedHeight(72)
        self.rules_text.textChanged.connect(self._rules_text_edited)
        card.body.addWidget(
            self._buddy_label("In your own words: when should the coach speak up?", self.rules_text)
        )
        card.body.addWidget(self.rules_text)
        self.use_triage.check.toggled.connect(self.rules_text.setEnabled)
        return card

    def _hour_box(self, tooltip: str) -> QSpinBox:
        box = self._spin(NO_HOUR, 23, tooltip, ":00")
        box.setSpecialValueText("Off")
        return box

    def _buddy_label(self, text: str, field: QWidget) -> QLabel:
        """A label tied to ``field``, so a screen reader and the Alt+key shortcuts find it."""
        label = make_label(text)
        label.setMinimumWidth(LABEL_WIDTH)  # one tidy column for all the form rows
        label.setBuddy(field)
        return label

    def _build_limits_card(self) -> Card:
        card = Card(
            "Limits that protect your plan",
            "The most AI calls the coach may make. 0 means none at all: the coach can't "
            "answer until you raise it.",
        )
        self.max_hour = self._spin(
            0, MAX_CALLS_PER_HOUR_LIMIT, "The most AI calls in one hour.", " calls"
        )
        self.max_day = self._spin(
            0, MAX_CALLS_PER_DAY_LIMIT, "The most AI calls in one day.", " calls"
        )
        self.hour_used = make_label("", "small")
        self.day_used = make_label("", "small")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setVerticalSpacing(SPACE)
        form.addRow(self._buddy_label("Most calls per hour", self.max_hour), self.max_hour)
        form.addRow("", self.hour_used)
        form.addRow(self._buddy_label("Most calls per day", self.max_day), self.max_day)
        form.addRow("", self.day_used)
        card.body.addLayout(form)
        return card

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
        return card

    # ---- showing the state ---------------------------------------------------------------

    def show_state(self, state: StateView) -> None:
        """Fill the fields from the saved settings, unless the player is editing them."""
        self._show_usage(state.usage)
        self.notify.set_available(
            state.notify_available, "This computer can't show desktop notifications."
        )
        self.speak.set_available(state.speak_available, "This computer can't read aloud.")
        if self._save_timer.isActive():
            return  # the player has unsaved edits; never overwrite them
        self._loading = True
        try:
            self._fill(state.settings)
        finally:
            self._loading = False

    def _show_usage(self, usage: UsageView) -> None:
        self.hour_used.setText(f"Used in the last hour: {usage.last_hour}")
        self.day_used.setText(f"Used in the last day: {usage.last_day}")

    def _fill(self, settings: Mapping[str, object]) -> None:
        """Copy saved values into the fields the player is not using right now."""
        self._set_check(self.answer_games, settings.get("answer_questions_from_game"), True)
        self._set_check(self.notify, settings.get("notify"), True)
        self._set_check(self.speak, settings.get("speak"), False)
        self._set_check(self.share_names, settings.get("share_other_player_names"), False)
        self._set_check(self.send_notes, settings.get("send_coach_notes"), True)
        self._set_spin(self.max_hour, _as_int(settings.get("max_calls_per_hour"), 20))
        self._set_spin(self.max_day, _as_int(settings.get("max_calls_per_day"), 100))
        self._fill_triggers(_as_mapping(settings.get("triggers")))

    def _fill_triggers(self, rules: Mapping[str, object]) -> None:
        modes = _as_mapping(rules.get("modes"))
        for kind, box in self.mode_boxes.items():
            index = box.findData(modes.get(kind, "off"))
            if not box.hasFocus():
                box.setCurrentIndex(max(index, 0))
        self._set_spin(self.timer_minutes, _as_int(rules.get("every_minutes"), 0))
        self._set_spin(self.cooldown, _as_int(rules.get("cooldown_minutes"), 10))
        self._set_check(self.quiet_instances, rules.get("quiet_in_instances"), True)
        self._set_spin(self.quiet_from, _as_int(rules.get("quiet_from_hour"), NO_HOUR))
        self._set_spin(self.quiet_to, _as_int(rules.get("quiet_to_hour"), NO_HOUR))
        self._set_check(self.use_triage, rules.get("use_triage"), False)
        self.rules_text.setEnabled(self.use_triage.check.isChecked())
        text = rules.get("rules_text")
        changed = isinstance(text, str) and self.rules_text.toPlainText() != text
        if changed and not self.rules_text.hasFocus():
            self.rules_text.setPlainText(str(text))

    def _set_check(self, row: ToggleRow, value: object, default: bool) -> None:
        if not row.check.hasFocus():
            row.check.setChecked(value if isinstance(value, bool) else default)

    def _set_spin(self, box: QSpinBox, value: int) -> None:
        if not box.hasFocus():
            box.setValue(value)

    def on_theme_changed(self) -> None:
        """Light or dark mode changed: restyle."""
        self.setStyleSheet(_style(current_colors()))

    # ---- saving --------------------------------------------------------------------------

    def _edited(self, *_ignored: object) -> None:
        """A field changed: (re)start the short wait before saving."""
        if self._loading:
            return
        self._save_timer.start()

    def _rules_text_edited(self) -> None:
        """Keep the free text within its limit, then treat it like any other edit."""
        text = self.rules_text.toPlainText()
        if len(text) > MAX_RULES_CHARS:
            self.rules_text.setPlainText(text[:MAX_RULES_CHARS])
            return  # setPlainText fired this again with the short text
        self._edited()

    def save_now(self) -> None:
        """Save what the fields hold now, or explain what is wrong with them."""
        self._save_timer.stop()
        changes, problem = self._collect_changes()
        if changes:
            self.bridge.change_settings(changes)
            self.saved_label.show()
            self._saved_timer.start()
        self.problem_label.setText(problem or "")
        self.problem_label.setVisible(problem is not None)
        if problem is not None:
            self.saved_label.hide()

    def _collect_changes(self) -> tuple[dict[str, object], str | None]:
        """What to save, and a plain message when the trigger rules cannot be saved."""
        changes: dict[str, object] = {
            "answer_questions_from_game": self.answer_games.check.isChecked(),
            "notify": self.notify.check.isChecked(),
            "speak": self.speak.check.isChecked(),
            "max_calls_per_hour": self.max_hour.value(),
            "max_calls_per_day": self.max_day.value(),
            "share_other_player_names": self.share_names.check.isChecked(),
            "send_coach_notes": self.send_notes.check.isChecked(),
        }
        problem = self._trigger_problem()
        if problem is None:
            changes["triggers"] = self._trigger_values()
        return changes, problem

    def _trigger_problem(self) -> str | None:
        """A plain message when the trigger fields hold something that cannot work."""
        minutes = self.timer_minutes.value()
        if minutes != 0 and not MIN_TIMER_MINUTES <= minutes <= MAX_TIMER_MINUTES:
            return TIMER_PROBLEM
        if (self.quiet_from.value() == NO_HOUR) != (self.quiet_to.value() == NO_HOUR):
            return QUIET_PROBLEM
        return None

    def _trigger_values(self) -> dict[str, object]:
        def hour(box: QSpinBox) -> int | None:
            return None if box.value() == NO_HOUR else box.value()

        return {
            "modes": {kind: box.currentData() for kind, box in self.mode_boxes.items()},
            "every_minutes": self.timer_minutes.value(),
            "cooldown_minutes": self.cooldown.value(),
            "quiet_in_instances": self.quiet_instances.check.isChecked(),
            "quiet_from_hour": hour(self.quiet_from),
            "quiet_to_hour": hour(self.quiet_to),
            "use_triage": self.use_triage.check.isChecked(),
            "rules_text": self.rules_text.toPlainText(),
        }
