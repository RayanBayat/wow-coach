"""Tests for the companion's settings file."""

from pathlib import Path

import pytest

from wow_coach.app_settings import (
    DEFAULTS,
    AppSettings,
    load_settings,
    save_settings,
    settings_from_dict,
    settings_path,
    update_settings,
)


def test_a_missing_file_gives_the_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "settings.json") == DEFAULTS


def test_defaults_protect_the_plan_and_privacy() -> None:
    assert DEFAULTS.speak is False
    assert DEFAULTS.share_other_player_names is False
    assert DEFAULTS.max_calls_per_hour == 20
    assert DEFAULTS.max_calls_per_day == 100


def test_save_then_load_gives_the_same_settings(tmp_path: Path) -> None:
    path = tmp_path / "data" / "settings.json"
    chosen = AppSettings(model="gpt-6-luna", speak=True, max_calls_per_hour=5)
    save_settings(path, chosen)
    assert load_settings(path) == chosen
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]  # no temp file left


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"speak": "yes"}', "{" * 5000])
def test_a_damaged_file_never_breaks_anything(tmp_path: Path, text: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")
    assert load_settings(path) == DEFAULTS


def test_bad_values_fall_back_one_by_one() -> None:
    settings = settings_from_dict(
        {
            "model": "gpt-6-luna; rm -rf /",
            "notify": False,
            "max_calls_per_hour": -3,
            "max_calls_per_day": 10**9,
            "speak": 1,  # not a real bool
        }
    )
    assert settings.model is None
    assert settings.notify is False
    assert settings.max_calls_per_hour == 0
    assert settings.max_calls_per_day == 2000
    assert settings.speak is False


def test_update_applies_good_changes_and_keeps_old_values_for_bad_ones() -> None:
    start = AppSettings(model="gpt-6-luna", max_calls_per_hour=7)
    changed = update_settings(start, {"speak": True, "max_calls_per_hour": "lots", "x": 1})
    assert changed.speak is True
    assert changed.max_calls_per_hour == 7
    assert changed.model == "gpt-6-luna"


def test_the_file_lives_in_the_data_folder(tmp_path: Path) -> None:
    environ = {"XDG_DATA_HOME": str(tmp_path), "LOCALAPPDATA": str(tmp_path)}
    assert settings_path(environ=environ).name == "settings.json"


def test_trigger_rules_are_saved_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    start = update_settings(
        DEFAULTS, {"triggers": {"modes": {"died": "notify"}, "every_minutes": 30}}
    )
    save_settings(path, start)
    loaded = load_settings(path)
    assert loaded.triggers.modes["died"] == "notify"
    assert loaded.triggers.every_minutes == 30
    assert loaded.triggers.modes["asked"] == "coach"  # always: the player asked


def test_a_partial_trigger_change_keeps_the_other_rules() -> None:
    start = update_settings(DEFAULTS, {"triggers": {"cooldown_minutes": 5, "use_triage": True}})
    changed = update_settings(start, {"triggers": {"use_triage": False}})
    assert changed.triggers.cooldown_minutes == 5
    assert changed.triggers.use_triage is False


def test_by_default_the_coach_only_answers_when_asked() -> None:
    modes = DEFAULTS.triggers.modes
    assert {kind for kind, mode in modes.items() if mode != "off"} == {"asked"}
