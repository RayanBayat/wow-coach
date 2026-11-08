""" "App size": a smaller or bigger WoW Coach, applied when the app starts."""

import json
import os
from pathlib import Path

import pytest
from desktop_support import make_bridge, sample_state
from pytestqt.qtbot import QtBot

from wow_coach.app_settings import (
    DEFAULT_UI_SCALE,
    AppSettings,
    settings_from_dict,
    settings_path,
    settings_to_dict,
)
from wow_coach.desktop.pages.settings import SettingsPage
from wow_coach.desktop.run import apply_saved_size
from wow_coach.desktop.state import read_state


@pytest.mark.parametrize(
    ("saved", "expected"),
    [(80, 80), (130, 130), (85, DEFAULT_UI_SCALE), (True, DEFAULT_UI_SCALE), ("90", 100)],
)
def test_only_the_offered_sizes_are_kept(saved: object, expected: int) -> None:
    assert settings_from_dict({"ui_scale": saved}).ui_scale == expected


def test_an_old_settings_file_without_a_size_is_normal_size() -> None:
    assert settings_from_dict({"notify": True}).ui_scale == DEFAULT_UI_SCALE


def write_settings(scale: int) -> None:
    path = settings_path(environ=os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = settings_to_dict(AppSettings(ui_scale=scale))
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_smaller_size_tells_qt_before_it_starts() -> None:
    write_settings(80)
    qt_environ: dict[str, str] = {}
    apply_saved_size(qt_environ, os.environ)
    assert qt_environ == {"QT_SCALE_FACTOR": "0.8"}


def test_normal_size_changes_nothing_and_the_players_own_choice_wins() -> None:
    write_settings(100)
    qt_environ: dict[str, str] = {}
    apply_saved_size(qt_environ, os.environ)
    assert qt_environ == {}
    write_settings(70)
    own = {"QT_SCALE_FACTOR": "1.5"}
    apply_saved_size(own, os.environ)
    assert own == {"QT_SCALE_FACTOR": "1.5"}


def test_choosing_a_size_saves_it_and_offers_a_restart(qtbot: QtBot, tmp_path: Path) -> None:
    del tmp_path
    bridge, core = make_bridge()
    page = SettingsPage(bridge)
    qtbot.addWidget(page)
    page.show()
    page.show_state(read_state(sample_state()))
    assert page.restart_button.isHidden()
    page.scale_box.setCurrentIndex(page.scale_box.findData(80))
    page.save_now()
    assert core.changes[-1].get("ui_scale") == 80
    assert not page.restart_button.isHidden()
    with qtbot.waitSignal(page.restart_requested):
        page.restart_button.click()
