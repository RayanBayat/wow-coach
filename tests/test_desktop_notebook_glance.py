"""The "At a glance" card: it shows a summary, never reads files, and can open the notebook."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from wow_coach.desktop.notebook_summary import NotebookSummary
from wow_coach.desktop.widgets.notebook_glance import EMPTY, NotebookGlance

SUMMARY = NotebookSummary(
    goal="Reach level 20",
    next_steps=("Train spells", "Buy a bag"),
    where="Silverpine Forest",
    choices=("Spec: Frost",),
    latest="Reached level 12.",
)


def shown(card: NotebookGlance) -> list[str]:
    return [label.text() for label in card.findChildren(QLabel)]


def test_it_shows_every_part_of_the_summary(qtbot: QtBot) -> None:
    card = NotebookGlance()
    qtbot.addWidget(card)
    card.show_summary(SUMMARY)
    texts = shown(card)
    assert "At a glance" in texts
    assert "Reach level 20" in texts
    assert "1. Train spells\n2. Buy a bag" in texts
    assert {"Silverpine Forest", "Spec: Frost", "Reached level 12."} <= set(texts)
    assert EMPTY not in texts


def test_an_empty_summary_shows_the_friendly_message(qtbot: QtBot) -> None:
    card = NotebookGlance()
    qtbot.addWidget(card)
    assert EMPTY in shown(card)
    card.show_summary(SUMMARY)
    card.show_summary(NotebookSummary())
    assert EMPTY in shown(card)
    assert "Reach level 20" not in shown(card)


def test_the_button_emits_open_requested(qtbot: QtBot) -> None:
    card = NotebookGlance()
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.open_requested, timeout=1000):
        card.open_button.click()


def test_the_card_is_narrow_and_plain_text_only(qtbot: QtBot) -> None:
    card = NotebookGlance()
    qtbot.addWidget(card)
    card.show_summary(NotebookSummary(goal="<b>bold</b> <a href='x'>link</a>"))
    assert card.maximumWidth() <= 320
    labels = card.findChildren(QLabel)
    assert all(label.textFormat() is Qt.TextFormat.PlainText for label in labels)
    assert "<b>bold</b> <a href='x'>link</a>" in shown(card)
