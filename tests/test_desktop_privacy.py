"""The Privacy page."""

import pytest
from desktop_support import make_bridge
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from wow_coach.desktop.pages.privacy import PrivacyPage


def test_the_privacy_page_says_what_is_sent_and_what_stays(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    page = PrivacyPage(bridge)
    qtbot.addWidget(page)
    text = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "What stays on this computer" in text
    assert "What is sent to ChatGPT, and when" in text
    assert "Your question." in text
    assert "hidden from the AI unless you turn that on" in text
    assert "no server and no tracking" in text


def test_the_privacy_page_explains_the_coach_tools_and_the_claude_chats(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    page = PrivacyPage(bridge)
    qtbot.addWidget(page)
    text = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "Warcraft Wiki searches go to the Warcraft Wiki" in text
    assert "run by OpenAI as part of your ChatGPT plan" in text
    assert "last 20 versions" in text and ".history" in text
    assert "Claude coach" in text and "Use my Claude coach chats" in text


def test_the_privacy_page_links_to_the_full_notice_and_the_usage_page(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    bridge, _core = make_bridge()
    page = PrivacyPage(bridge)
    qtbot.addWidget(page)
    buttons = {b.text(): b for b in page.findChildren(QPushButton)}
    buttons["Read the full privacy notice"].click()
    buttons["Manage usage"].click()
    assert opened == [
        "https://github.com/RayanBayat/wow-coach/blob/main/docs/privacy.md",
        "https://chatgpt.com/settings/usage",
    ]
