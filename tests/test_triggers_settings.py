"""Cleaning the trigger rules, and the state file."""

import json
from pathlib import Path

from wow_coach.triggers.contract import EVENT_KINDS, Decision, Event, TriggerSettings
from wow_coach.triggers.settings import trigger_settings_from_dict, trigger_settings_to_dict
from wow_coach.triggers.state import (
    TriggerState,
    load_state,
    record_decisions,
    save_state,
    state_path,
)


def test_defaults_are_manual_only() -> None:
    settings = trigger_settings_from_dict({})
    assert settings == TriggerSettings()
    assert settings.modes["asked"] == "coach"
    assert all(settings.modes[kind] == "off" for kind in EVENT_KINDS if kind != "asked")


def test_not_a_dict_gives_defaults() -> None:
    for junk in (None, 5, "x", [1]):
        assert trigger_settings_from_dict(junk) == TriggerSettings()


def test_modes_are_cleaned() -> None:
    settings = trigger_settings_from_dict(
        {"modes": {"died": "notify", "level_up": "shout", "bogus": "coach", "new_zone": 3}}
    )
    assert settings.modes["died"] == "notify"
    assert settings.modes["level_up"] == "off"
    assert settings.modes["new_zone"] == "off"
    assert "bogus" not in settings.modes


def test_asked_is_always_coach() -> None:
    assert trigger_settings_from_dict({"modes": {"asked": "off"}}).modes["asked"] == "coach"


def test_numbers_are_clamped() -> None:
    low = trigger_settings_from_dict(
        {"cooldown_minutes": -5, "every_minutes": 2, "quiet_from_hour": -1, "quiet_to_hour": 24}
    )
    assert (low.cooldown_minutes, low.every_minutes) == (0, 5)
    assert (low.quiet_from_hour, low.quiet_to_hour) == (None, None)
    high = trigger_settings_from_dict(
        {"cooldown_minutes": 9999, "every_minutes": 9999, "quiet_from_hour": 23, "quiet_to_hour": 0}
    )
    assert (high.cooldown_minutes, high.every_minutes) == (240, 240)
    assert (high.quiet_from_hour, high.quiet_to_hour) == (23, 0)
    assert trigger_settings_from_dict({"every_minutes": 0}).every_minutes == 0
    assert trigger_settings_from_dict({"every_minutes": -3}).every_minutes == 0


def test_wrong_types_fall_back() -> None:
    settings = trigger_settings_from_dict(
        {
            "cooldown_minutes": "ten",
            "every_minutes": True,
            "quiet_in_instances": "yes",
            "use_triage": 1,
            "quiet_from_hour": 7.5,
            "rules_text": 5,
        }
    )
    assert settings == TriggerSettings()


def test_rules_text_is_cut_and_stripped_of_control_characters() -> None:
    settings = trigger_settings_from_dict({"rules_text": "a\x00b\nc" + "x" * 600})
    assert len(settings.rules_text) == 500
    assert settings.rules_text.startswith("a b c")
    assert all(ord(c) >= 32 for c in settings.rules_text)


def test_round_trip_through_json() -> None:
    settings = trigger_settings_from_dict(
        {
            "modes": {"died": "coach"},
            "cooldown_minutes": 5,
            "quiet_from_hour": 23,
            "quiet_to_hour": 7,
        }
    )
    data = json.loads(json.dumps(trigger_settings_to_dict(settings)))
    assert trigger_settings_from_dict(data) == settings


# --- state file ---


def test_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "triggers-state.json"
    state = TriggerState(last_coach_at={"A-B": 100}, last_timer_at=200)
    save_state(path, state)
    assert load_state(path) == state
    assert list(path.parent.glob("*.part")) == []


def test_state_path_is_in_the_data_folder(tmp_path: Path) -> None:
    path = state_path(environ={"WOW_COACH_DATA_DIR": str(tmp_path / "wow-coach")})
    assert path.name == "triggers-state.json"
    assert path.parent.parent == tmp_path


def test_missing_or_damaged_state_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    assert load_state(path) == TriggerState()
    for text in ("{not json", "[1, 2]", '"x"', "\x00\x01", '{"last_coach_at": 5}'):
        path.write_text(text, encoding="utf-8")
        assert load_state(path) == TriggerState()
    path.write_bytes(b"\xff\xfe\xfa")
    assert load_state(path) == TriggerState()


def test_bad_values_in_state_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    data = {"last_coach_at": {"A-B": 50, "C-D": "x", "E-F": -1, "G-H": True}, "last_timer_at": "no"}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_state(path) == TriggerState(last_coach_at={"A-B": 50}, last_timer_at=0)


def _decision(kind: str, action: str) -> Decision:
    event = Event(kind, "A-B", 1, "x")  # type: ignore[arg-type]
    return Decision(event, action, "r")  # type: ignore[arg-type]


def test_record_decisions() -> None:
    state = TriggerState()
    after = record_decisions(state, [_decision("died", "coach")], now=500)
    assert after.last_coach_at == {"A-B": 500}
    asked_and_notified = [_decision("asked", "coach"), _decision("died", "notify")]
    assert record_decisions(state, asked_and_notified, now=500) == state
    after = record_decisions(state, [_decision("timer", "notify")], now=500)
    assert after.last_timer_at == 500
    after = record_decisions(state, [_decision("timer", "off")], now=500)
    assert after.last_timer_at == 0
