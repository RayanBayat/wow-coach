"""The Settings page's "Coach tools" card."""

import pytest
from desktop_support import FakeCore, make_bridge, sample_state
from pytestqt.qtbot import QtBot

from wow_coach.app_settings import AppSettings, settings_to_dict
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.settings import SettingsPage
from wow_coach.desktop.state import read_state


def make_page(qtbot: QtBot, **state: object) -> tuple[SettingsPage, CoreBridge, FakeCore]:
    bridge, core = make_bridge()
    page = SettingsPage(bridge)
    qtbot.addWidget(page)
    page.show()
    page.show_state(read_state(sample_state(**state)))
    return page, bridge, core


def test_the_card_shows_the_saved_tool_settings(qtbot: QtBot) -> None:
    saved = AppSettings(use_tools=False, web_search=False, save_notes=False, show_lookups=False)
    page, _bridge, _core = make_page(qtbot, settings=settings_to_dict(saved))
    for row in (page.use_tools, page.web_search, page.save_notes, page.show_lookups):
        assert not row.check.isChecked()


def test_the_defaults_are_all_on_and_worded_for_players(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, settings={"notify": True})
    assert page.use_tools.check.isChecked() and page.web_search.check.isChecked()
    assert page.save_notes.check.isChecked() and page.show_lookups.check.isChecked()
    assert "look things up" in page.use_tools.check.text()
    assert "search the web" in page.web_search.check.text()
    assert "update your notebook" in page.save_notes.check.text()
    assert "Show what the coach looked up" in page.show_lookups.check.text()
    assert core.changes == []  # filling saves nothing


@pytest.mark.parametrize("name", ["use_tools", "web_search", "save_notes", "show_lookups"])
def test_each_toggle_saves_only_itself(qtbot: QtBot, name: str) -> None:
    page, _bridge, core = make_page(qtbot, settings=settings_to_dict(AppSettings()))
    getattr(page, name).check.setChecked(False)
    page.save_now()
    assert core.changes == [{name: False}]
