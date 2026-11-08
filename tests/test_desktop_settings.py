"""The Settings page: filling, auto-saving, validating and not overwriting edits."""

from desktop_support import FakeCore, make_bridge, sample_state
from PySide6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot

from wow_coach.app_settings import AppSettings, settings_to_dict
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.settings import SettingsPage
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
        triggers=TriggerSettings(on_save="advice", quiet_in_instances=False),
    )
    page, _bridge, _core = make_page(qtbot, **settings_state(saved))
    assert page.share_names.check.isChecked()
    assert not page.send_notes.check.isChecked()
    assert page.on_save_box.currentData() == "advice"
    assert not page.quiet_instances.check.isChecked()


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
    page.on_save_box.setCurrentIndex(0)
    page._edited()
    assert core.changes == []
    assert page._save_timer.isActive()
    page._save_timer.timeout.emit()  # what the timer does after 400 ms
    assert core.settings.triggers.on_save == "off"
    assert page.saved_label.isVisible()


def test_the_real_timer_saves_by_itself(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.share_names.check.setChecked(True)
    qtbot.waitUntil(lambda: bool(core.changes), timeout=3000)
    assert core.settings.share_other_player_names is True


def test_many_quick_changes_save_once(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    for index in (0, 1, 2):
        page.on_save_box.setCurrentIndex(index)
        page._edited()
    page._save_timer.timeout.emit()
    assert len(core.changes) == 1
    assert core.settings.triggers.on_save == "advice"


def test_the_choice_is_saved_in_the_core_s_shape(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.on_save_box.setCurrentIndex(2)
    page.quiet_instances.check.setChecked(False)
    page.save_now()
    assert core.settings.triggers == TriggerSettings(on_save="advice", quiet_in_instances=False)


# ---- not overwriting edits -------------------------------------------------------------


def test_a_new_state_does_not_overwrite_an_unsaved_edit(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page.quiet_instances.check.setChecked(False)  # not saved yet
    newer = settings_state(AppSettings(triggers=TriggerSettings(quiet_in_instances=True)))
    page.show_state(read_state(sample_state(**newer)))
    assert not page.quiet_instances.check.isChecked()


def test_a_new_state_updates_fields_that_are_not_being_edited(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    newer = settings_state(AppSettings(triggers=TriggerSettings(on_save="off")))
    page.show_state(read_state(sample_state(**newer)))
    assert page.on_save_box.currentData() == "off"


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


def test_a_trigger_edit_sends_only_the_changed_field(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.on_save_box.setCurrentIndex(2)
    page.save_now()
    assert core.changes == [{"triggers": {"on_save": "advice"}}]


def test_the_same_edit_is_not_sent_twice(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.share_names.check.setChecked(True)
    page.save_now()
    page.send_notes.check.setChecked(False)
    page.save_now()
    assert core.changes == [{"share_other_player_names": True}, {"send_coach_notes": False}]


def test_the_claude_chats_toggle_shows_and_saves_the_setting(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, **settings_state(AppSettings(use_claude_chats=False)))
    assert not page.use_claude_chats.check.isChecked()
    page.use_claude_chats.check.setChecked(True)
    page.save_now()
    assert core.changes == [{"use_claude_chats": True}]


# ---- the overlay card ------------------------------------------------------------------


def test_the_overlay_fields_show_the_saved_values(qtbot: QtBot) -> None:
    saved = AppSettings(overlay_opacity=70, overlay_hotkey="Ctrl+Alt+F9")
    page, _bridge, _core = make_page(qtbot, **settings_state(saved))
    assert page.opacity_slider.value() == 70
    assert page.opacity_value.text() == "70 %"
    assert page.hotkey_edit.keySequence().toString() == "Ctrl+Alt+F9"


def test_old_settings_without_overlay_values_show_the_defaults(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, settings={"notify": True})
    assert page.opacity_slider.value() == 92
    assert page.hotkey_edit.keySequence().toString() == "Ctrl+Shift+Space"
    assert core.changes == []  # filling never saves


def test_the_slider_only_allows_60_to_100(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    assert (page.opacity_slider.minimum(), page.opacity_slider.maximum()) == (60, 100)


def test_moving_the_slider_saves_only_the_opacity(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.opacity_slider.setValue(75)
    page.save_now()
    assert core.changes == [{"overlay_opacity": 75}]
    assert core.settings.overlay_opacity == 75


def test_choosing_a_new_key_saves_it(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+F9"))
    page.save_now()
    assert core.changes == [{"overlay_hotkey": "Ctrl+Alt+F9"}]
    assert core.settings.overlay_hotkey == "Ctrl+Alt+F9"


def test_clearing_the_key_box_does_not_save_an_empty_key(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    page.hotkey_edit.clear()
    page.save_now()
    assert core.changes == []
