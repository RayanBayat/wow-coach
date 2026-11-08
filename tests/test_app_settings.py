"""Tests for the companion's settings file."""

import json
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
from wow_coach.triggers.contract import TriggerSettings


def test_a_missing_file_gives_the_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "settings.json") == DEFAULTS


def test_defaults_protect_the_plan_and_privacy() -> None:
    assert DEFAULTS.share_other_player_names is False


def test_save_then_load_gives_the_same_settings(tmp_path: Path) -> None:
    path = tmp_path / "data" / "settings.json"
    chosen = AppSettings(model="gpt-6-luna", notify=False)
    save_settings(path, chosen)
    assert load_settings(path) == chosen
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]  # no temp file left


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"notify": "yes"}', "{" * 5000])
def test_a_damaged_file_never_breaks_anything(tmp_path: Path, text: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")
    assert load_settings(path) == DEFAULTS


def test_bad_values_fall_back_one_by_one() -> None:
    settings = settings_from_dict(
        {
            "model": "gpt-6-luna; rm -rf /",
            "notify": 1,  # not a real bool
        }
    )
    assert settings.model is None
    assert settings.notify is True


def test_update_applies_good_changes_and_keeps_old_values_for_bad_ones() -> None:
    start = AppSettings(model="gpt-6-luna")
    changed = update_settings(start, {"notify": False, "x": 1})
    assert changed.notify is False
    assert changed.model == "gpt-6-luna"


def test_the_file_lives_in_the_data_folder(tmp_path: Path) -> None:
    environ = {"WOW_COACH_DATA_DIR": str(tmp_path)}
    assert settings_path(environ=environ).name == "settings.json"


def test_the_save_choice_is_saved_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(path, update_settings(DEFAULTS, {"triggers": {"on_save": "advice"}}))
    assert load_settings(path).triggers.on_save == "advice"


def test_an_old_settings_file_with_the_old_rules_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    old_rules = {
        "modes": {"asked": "coach", "died": "notify", "level_up": "coach"},
        "every_minutes": 30,
        "cooldown_minutes": 15,
        "quiet_in_instances": False,
        "quiet_from_hour": 23,
        "quiet_to_hour": 7,
        "use_triage": True,
        "rules_text": "only if I die twice",
    }
    path.write_text(json.dumps({"notify": False, "triggers": old_rules}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.notify is False
    assert loaded.triggers == TriggerSettings(on_save="advice", quiet_in_instances=False)


def test_a_partial_trigger_change_keeps_the_other_rules() -> None:
    start = update_settings(
        DEFAULTS, {"triggers": {"on_save": "advice", "quiet_in_instances": False}}
    )
    changed = update_settings(start, {"triggers": {"quiet_in_instances": True}})
    assert changed.triggers.on_save == "advice"
    assert changed.triggers.quiet_in_instances is True


def test_by_default_the_coach_tells_what_is_worth_knowing_without_ai() -> None:
    assert DEFAULTS.triggers.on_save == "notify"
    assert DEFAULTS.triggers.quiet_in_instances is True
