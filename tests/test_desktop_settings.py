"""The Settings page: filling, auto-saving, validating and not overwriting edits."""

from desktop_support import FakeCore, make_bridge, sample_state
from pytestqt.qtbot import QtBot

from wow_coach.app_settings import AppSettings, settings_to_dict
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.settings import QUIET_PROBLEM, TIMER_PROBLEM, SettingsPage
from wow_coach.desktop.state import read_state
from wow_coach.triggers.contract import TriggerSettings


def make_page(qtbot: QtBot, **state: object) -> tuple[SettingsPage, CoreBridge, FakeCore]:
    bridge, core = make_bridge()
    page = SettingsPage(bridge)
    qtbot.addWidget(page)
    page.show()
    page.show_state(read_state(sample_state(**state)))
    return page, bridge, core


def settings_state(settings: AppSettings) -> dict[str, object]:
    return {"settings": settings_to_dict(settings)}


# ---- filling ---------------------------------------------------------------------------


def test_the_fields_show_the_saved_settings(qtbot: QtBot) -> None:
    saved = AppSettings(
        share_other_player_names=True,
        send_coach_notes=False,
        triggers=TriggerSettings(
            modes={**TriggerSettings().modes, "died": "notify"},
            every_minutes=30,
            cooldown_minutes=15,
            quiet_from_hour=23,
            quiet_to_hour=7,
            use_triage=True,
            rules_text="only if I die twice",
        ),
    )
    page, _bridge, _core = make_page(qtbot, **settings_state(saved))
    assert page.share_names.check.isChecked()
    assert not page.send_notes.check.isChecked()
    assert page.mode_boxes["died"].currentData() == "notify"
    assert page.mode_boxes["level_up"].currentData() == "off"
    assert page.timer_minutes.value() == 30
    assert page.cooldown.value() == 15
    assert (page.quiet_from.value(), page.quiet_to.value()) == (23, 7)
    assert page.use_triage.check.isChecked()
    assert page.rules_text.isEnabled()
    assert page.rules_text.toPlainText() == "only if I die twice"


def test_filling_the_fields_does_not_save_anything(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, **settings_state(AppSettings(send_coach_notes=False)))
    assert not page._save_timer.isActive()
    assert core.changes == []


def test_notify_is_disabled_when_the_computer_cannot(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, alerts={"notify": False})
    assert not page.notify.check.isEnabled()
    assert "can't" in page.notify.description.text()
    page.show_state(read_state(sample_state()))
    assert page.notify.check.isEnabled()


# ---- saving ----------------------------------------------------------------------------


def test_a_change_saves_after_the_wait_not_at_once(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.cooldown.setValue(55)
    assert core.changes == []
    assert page._save_timer.isActive()
    page._save_timer.timeout.emit()  # what the timer does after 400 ms
    assert core.settings.triggers.cooldown_minutes == 55
    assert page.saved_label.isVisible()


def test_the_real_timer_saves_by_itself(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.share_names.check.setChecked(True)
    qtbot.waitUntil(lambda: bool(core.changes), timeout=3000)
    assert core.settings.share_other_player_names is True


def test_many_quick_changes_save_once(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    for value in (21, 22, 23):
        page.cooldown.setValue(value)
    page._save_timer.timeout.emit()
    assert len(core.changes) == 1
    assert core.settings.triggers.cooldown_minutes == 23


def test_trigger_rules_are_saved_in_the_core_s_shape(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.mode_boxes["died"].setCurrentIndex(2)
    page.timer_minutes.setValue(30)
    page.quiet_from.setValue(22)
    page.quiet_to.setValue(6)
    page.use_triage.check.setChecked(True)
    page.rules_text.setPlainText("only if I die twice")
    page.save_now()
    rules = core.settings.triggers
    assert rules.modes["died"] == "coach"
    assert rules.every_minutes == 30
    assert (rules.quiet_from_hour, rules.quiet_to_hour) == (22, 6)
    assert rules.use_triage is True
    assert rules.rules_text == "only if I die twice"


def test_a_timer_of_a_few_minutes_is_not_saved_and_says_why(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.timer_minutes.setValue(3)
    page.share_names.check.setChecked(True)
    page.save_now()
    assert page.problem_label.text() == TIMER_PROBLEM
    assert page.problem_label.isVisible()
    assert core.settings.triggers.every_minutes == 0  # the bad rules were not saved
    assert core.settings.share_other_player_names is True  # the rest was


def test_half_set_quiet_hours_are_not_saved(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.quiet_from.setValue(23)
    page.save_now()
    assert page.problem_label.text() == QUIET_PROBLEM
    assert core.settings.triggers.quiet_from_hour is None


def test_fixing_the_problem_clears_the_message(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page.timer_minutes.setValue(3)
    page.save_now()
    page.timer_minutes.setValue(10)
    page.save_now()
    assert not page.problem_label.isVisible()


def test_the_free_text_is_cut_to_its_limit(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page.rules_text.setPlainText("x" * 600)
    assert len(page.rules_text.toPlainText()) == 500


# ---- not overwriting edits -------------------------------------------------------------


def test_a_new_state_does_not_overwrite_an_unsaved_edit(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page.cooldown.setValue(55)  # not saved yet
    newer = settings_state(AppSettings(triggers=TriggerSettings(cooldown_minutes=7)))
    page.show_state(read_state(sample_state(**newer)))
    assert page.cooldown.value() == 55


def test_a_new_state_updates_fields_that_are_not_being_edited(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    newer = settings_state(AppSettings(triggers=TriggerSettings(cooldown_minutes=7)))
    page.show_state(read_state(sample_state(**newer)))
    assert page.cooldown.value() == 7


def test_the_focused_field_is_left_alone(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page.activateWindow()
    page.cooldown.setFocus()
    qtbot.waitUntil(page.cooldown.hasFocus)
    page.cooldown.setValue(88)
    page._save_timer.stop()  # as if the edit had just been saved
    newer = settings_state(AppSettings(triggers=TriggerSettings(cooldown_minutes=5)))
    page.show_state(read_state(sample_state(**newer)))
    assert page.cooldown.value() == 88


# ---- not saving before the settings are known ------------------------------------------


def make_unloaded_page(qtbot: QtBot) -> tuple[SettingsPage, FakeCore]:
    """A page that has not yet received a state with settings."""
    bridge, core = make_bridge()
    page = SettingsPage(bridge)
    qtbot.addWidget(page)
    page.show()
    return page, core


def test_the_fields_are_disabled_until_the_settings_arrive(qtbot: QtBot) -> None:
    page, _core = make_unloaded_page(qtbot)
    assert not page.form.isEnabled()
    assert page.loading_label.isVisible()
    page.show_state(read_state(sample_state()))
    assert page.form.isEnabled()
    assert not page.loading_label.isVisible()


def test_a_state_without_settings_changes_nothing(qtbot: QtBot) -> None:
    page, _core = make_unloaded_page(qtbot)
    page.show_state(read_state(sample_state(settings={})))
    assert not page.form.isEnabled()
    assert page.loading_label.isVisible()


def test_a_failed_read_keeps_the_values_already_shown(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, **settings_state(AppSettings(send_coach_notes=False)))
    page.show_state(read_state(sample_state(settings={})))
    assert not page.send_notes.check.isChecked()
    assert page.form.isEnabled()


def test_saving_before_the_settings_arrive_sends_nothing(qtbot: QtBot) -> None:
    page, core = make_unloaded_page(qtbot)
    page.save_now()
    assert core.changes == []


def test_one_edit_saves_only_that_field(qtbot: QtBot) -> None:
    saved = AppSettings(send_coach_notes=False)
    page, _bridge, core = make_page(qtbot, **settings_state(saved))
    page.share_names.check.setChecked(True)
    page.save_now()
    assert core.changes == [{"share_other_player_names": True}]


def test_a_trigger_edit_sends_only_the_changed_rule_fields(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.cooldown.setValue(25)
    page.save_now()
    assert core.changes == [{"triggers": {"cooldown_minutes": 25}}]


def test_the_same_edit_is_not_sent_twice(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.share_names.check.setChecked(True)
    page.save_now()
    page.send_notes.check.setChecked(False)
    page.save_now()
    assert core.changes == [{"share_other_player_names": True}, {"send_coach_notes": False}]
