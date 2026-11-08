"""Cleaning the "When the game saves" settings, including the old rules format."""

import json

from wow_coach.triggers.contract import TriggerSettings
from wow_coach.triggers.settings import trigger_settings_from_dict, trigger_settings_to_dict


def test_defaults_notify_and_stay_quiet_in_instances() -> None:
    settings = trigger_settings_from_dict({})
    assert settings == TriggerSettings(on_save="notify", quiet_in_instances=True)


def test_not_a_dict_gives_defaults() -> None:
    for junk in (None, 5, "x", [1]):
        assert trigger_settings_from_dict(junk) == TriggerSettings()


def test_each_choice_is_kept() -> None:
    for choice in ("off", "notify", "advice"):
        assert trigger_settings_from_dict({"on_save": choice}).on_save == choice


def test_wrong_values_fall_back() -> None:
    settings = trigger_settings_from_dict({"on_save": "shout", "quiet_in_instances": "yes"})
    assert settings == TriggerSettings()


def test_round_trip_through_json() -> None:
    settings = TriggerSettings(on_save="advice", quiet_in_instances=False)
    data = json.loads(json.dumps(trigger_settings_to_dict(settings)))
    assert trigger_settings_from_dict(data) == settings


# --- the old per-event rules ---


def test_old_rules_with_a_coach_event_become_advice() -> None:
    old = {"modes": {"asked": "coach", "died": "notify", "level_up": "coach"}}
    assert trigger_settings_from_dict(old).on_save == "advice"


def test_old_rules_with_only_notify_events_become_notify() -> None:
    old = {"modes": {"asked": "coach", "died": "notify", "level_up": "off"}}
    assert trigger_settings_from_dict(old).on_save == "notify"


def test_old_rules_with_everything_off_get_the_new_default() -> None:
    old = {"modes": {"asked": "coach", "died": "off", "timer": "off"}}
    assert trigger_settings_from_dict(old).on_save == "notify"


def test_old_rules_carry_the_quiet_switch_over_and_drop_the_rest() -> None:
    old = {
        "modes": {"died": "coach"},
        "quiet_in_instances": False,
        "every_minutes": 30,
        "cooldown_minutes": 15,
        "quiet_from_hour": 23,
        "quiet_to_hour": 7,
        "use_triage": True,
        "rules_text": "only if I die twice",
    }
    assert trigger_settings_from_dict(old) == TriggerSettings(
        on_save="advice", quiet_in_instances=False
    )


def test_junk_old_modes_do_not_break_loading() -> None:
    assert trigger_settings_from_dict({"modes": "nope"}) == TriggerSettings()
    assert trigger_settings_from_dict({"modes": {"died": 3}}) == TriggerSettings()


def test_the_new_choice_wins_over_old_modes() -> None:
    both = {"on_save": "off", "modes": {"died": "coach"}}
    assert trigger_settings_from_dict(both).on_save == "off"
