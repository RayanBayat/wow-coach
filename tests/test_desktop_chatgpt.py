"""The ChatGPT page and the one-time welcome message."""

import pytest
from desktop_support import FakeCore, make_bridge, sample_state
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.chatgpt import (
    BUSY_MESSAGE,
    PLAN_LINE,
    SIGN_IN_BUTTON_TEXT,
    SIGNED_OUT_NOT_CONFIRMED,
    ChatGPTPage,
)
from wow_coach.desktop.state import read_state
from wow_coach.desktop.welcome import WELCOME_TEXT, WELCOME_TITLE

SIGN_IN_URL = "https://auth.openai.com/api/accounts/authorize?x=1"


def make_page(qtbot: QtBot, **state: object) -> tuple[ChatGPTPage, CoreBridge, FakeCore]:
    bridge, core = make_bridge()
    page = ChatGPTPage(bridge)
    qtbot.addWidget(page)
    page.show()
    page.show_state(read_state(sample_state(**state)))
    return page, bridge, core


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Collects every address the page tries to open (nothing really opens)."""
    urls: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url.toString()))
    return urls


# ---- signed out ------------------------------------------------------------------------


def test_signed_out_shows_the_required_button_text(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    assert SIGN_IN_BUTTON_TEXT == "Continue with ChatGPT"
    assert page.sign_in_button.text() == "Continue with ChatGPT"
    assert page.sign_in_button.isVisible()
    assert not page._signed_in_card.isVisible()


def test_the_privacy_button_asks_for_the_privacy_page(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    with qtbot.waitSignal(page.navigate) as signal:
        page.privacy_button.click()
    assert signal.args == ["privacy"]


def test_continue_starts_the_sign_in_and_shows_the_waiting_card(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, signed_in=False)
    page.sign_in_button.click()
    assert core.sign_ins == 1
    assert page._waiting_card.isVisible()
    assert not page._signed_out_card.isVisible()
    assert page.spinner.is_turning


def test_a_sign_in_that_is_already_open_is_explained(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, signed_in=False)
    core.start_sign_in = lambda: False  # type: ignore[method-assign]
    page.sign_in_button.click()
    assert page._notice.text() == BUSY_MESSAGE


# ---- waiting ---------------------------------------------------------------------------


def test_the_waiting_buttons_open_and_copy_the_sign_in_link(
    qtbot: QtBot, opened: list[str]
) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.sign_in_button.click()
    assert not page.open_again_button.isEnabled()  # no address yet
    page.on_event("signin", {"state": "waiting", "url": SIGN_IN_URL})
    assert page.open_again_button.isEnabled()
    page.open_again_button.click()
    assert opened == [SIGN_IN_URL]
    page.copy_link_button.click()
    assert QApplication.clipboard().text() == SIGN_IN_URL


def test_only_openai_sign_in_addresses_are_ever_opened(qtbot: QtBot, opened: list[str]) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.on_event("signin", {"state": "waiting", "url": "https://evil.example/login"})
    assert not page.open_again_button.isEnabled()
    page.open_again_button.click()
    assert opened == []


def test_hide_goes_back_to_the_start_and_does_not_claim_to_cancel(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.on_event("signin", {"state": "waiting", "url": SIGN_IN_URL})
    assert page.hide_button.text() == "Hide this"
    assert "few minutes" in page.hide_button.toolTip()
    page.hide_button.click()
    assert page._signed_out_card.isVisible()


def test_continue_again_while_the_first_sign_in_is_open_keeps_the_link(
    qtbot: QtBot, opened: list[str]
) -> None:
    page, _bridge, core = make_page(qtbot, signed_in=False)
    page.sign_in_button.click()
    page.on_event("signin", {"state": "waiting", "url": SIGN_IN_URL})
    page.hide_button.click()
    core.start_sign_in = lambda: False  # type: ignore[method-assign]
    page.sign_in_button.click()  # the core is still busy with the first sign-in
    assert page._waiting_card.isVisible()
    assert page.open_again_button.isEnabled()
    assert page.copy_link_button.isEnabled()
    page.open_again_button.click()
    assert opened == [SIGN_IN_URL]
    assert "5 minutes" in page._notice.text()


def test_an_error_while_waiting_is_shown_plainly_with_try_again(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.on_event("signin", {"state": "waiting", "url": SIGN_IN_URL})
    page.on_event("error", {"message": "<b>The sign-in was cancelled.</b>"})
    assert page._signed_out_card.isVisible()
    assert page._error_label.text() == "<b>The sign-in was cancelled.</b> Please try again."
    assert page._error_label.textFormat() == Qt.TextFormat.PlainText
    assert page.sign_in_button.text() == "Continue with ChatGPT"  # OpenAI's required wording


def test_an_error_when_not_signing_in_is_ignored_here(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.on_event("error", {"message": "Something else"})
    assert not page._error_label.isVisible()


def test_finishing_the_sign_in_shows_success_and_the_signed_in_card(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False)
    page.on_event("signin", {"state": "waiting", "url": SIGN_IN_URL})
    page.on_event("signin", {"state": "signed_in"})
    assert page._signed_in_card.isVisible()
    assert "signed in" in page._notice.text()


# ---- signed in -------------------------------------------------------------------------


def test_signed_in_shows_the_plan_line_and_manage_usage(qtbot: QtBot, opened: list[str]) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=True)
    assert PLAN_LINE == "Using ChatGPT plan"
    assert page._signed_in_card.isVisible()
    assert page.manage_usage_button.text() == "Manage usage"
    page.manage_usage_button.click()
    assert opened == ["https://chatgpt.com/settings/usage"]


def test_usage_is_plain_text_without_limits(qtbot: QtBot) -> None:
    usage = {"last_hour": 5, "last_day": 40}
    page, _bridge, _core = make_page(qtbot, usage=usage)
    assert page.hour_used.text() == "Questions in the last hour: 5"
    assert page.day_used.text() == "Questions today: 40"


def test_models_load_once_and_recommended_maps_to_no_model(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot)
    names = [page.model_box.itemText(i) for i in range(page.model_box.count())]
    assert names == ["Recommended (automatic)", "GPT Test Terra"]
    page.model_box.setCurrentIndex(1)
    page._model_chosen(1)
    assert core.changes[-1] == {"model": "gpt-test-terra"}
    page.model_box.setCurrentIndex(0)
    page._model_chosen(0)
    assert core.changes[-1] == {"model": None}
    assert core.settings.model is None


def test_the_saved_model_is_selected(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, settings={"model": "gpt-test-terra"})
    assert page.model_box.currentData() == "gpt-test-terra"


def test_a_failed_model_list_leaves_recommended_and_a_note(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot)
    page._on_models_loaded([])
    assert page.model_box.count() == 1
    assert "could not be loaded" in page.model_note.text()


def test_a_locked_keychain_problem_is_shown_calmly(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, signed_in=False, problem="Unlock your keychain.")
    assert page._problem.text() == "Unlock your keychain."
    assert page._problem.isVisible()
    page.show_state(read_state(sample_state(signed_in=False)))
    assert not page._problem.isVisible()


# ---- signing out -----------------------------------------------------------------------


def test_sign_out_asks_first(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _bridge, core = make_page(qtbot)
    monkeypatch.setattr(ChatGPTPage, "_confirm_sign_out", lambda _self: False)
    page.sign_out_button.click()
    assert core.sign_outs == 0


def test_a_confirmed_sign_out_says_signed_out(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _bridge, core = make_page(qtbot)
    monkeypatch.setattr(ChatGPTPage, "_confirm_sign_out", lambda _self: True)
    page.sign_out_button.click()
    assert core.sign_outs == 1
    assert page._notice.text() == "Signed out."


def test_an_unconfirmed_sign_out_explains_what_to_do(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _bridge, core = make_page(qtbot)
    core.sign_out = lambda: False  # type: ignore[method-assign]
    monkeypatch.setattr(ChatGPTPage, "_confirm_sign_out", lambda _self: True)
    page.sign_out_button.click()
    assert page._notice.text() == SIGNED_OUT_NOT_CONFIRMED
    assert "ChatGPT settings" in page._notice.text()


# ---- the welcome message ---------------------------------------------------------------


def test_the_welcome_dialog_has_the_required_wording(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, welcome_pending=True)
    dialog = page.welcome_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog.windowTitle() == "You're using your ChatGPT plan"
    assert WELCOME_TITLE == "You're using your ChatGPT plan"
    assert "Eligible usage in this app uses your ChatGPT plan." in WELCOME_TEXT
    assert dialog.got_it.text() == "Got it"
    assert dialog.got_it.isDefault()


def test_the_welcome_dialog_is_not_shown_when_nothing_is_pending(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, welcome_pending=False)
    assert page.welcome_dialog is None


def test_the_welcome_dialog_never_stacks(qtbot: QtBot) -> None:
    page, _bridge, _core = make_page(qtbot, welcome_pending=True)
    first = page.welcome_dialog
    page.show_state(read_state(sample_state(welcome_pending=True)))
    page.show_state(read_state(sample_state(welcome_pending=True)))
    assert page.welcome_dialog is first


def test_only_got_it_dismisses_for_good(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, welcome_pending=True)
    dialog = page.welcome_dialog
    assert dialog is not None
    dialog.got_it.click()
    assert core.welcome_dismissed is True
    assert not dialog.isVisible()


def test_escape_closes_the_dialog_without_dismissing(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, welcome_pending=True)
    dialog = page.welcome_dialog
    assert dialog is not None
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert core.welcome_dismissed is False
    # It does not pop up again in the same run, however often the state arrives.
    page.show_state(read_state(sample_state(welcome_pending=True)))
    assert page.welcome_dialog is dialog
    assert not dialog.isVisible()


def test_enter_presses_got_it(qtbot: QtBot) -> None:
    page, _bridge, core = make_page(qtbot, welcome_pending=True)
    dialog = page.welcome_dialog
    assert dialog is not None
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert core.welcome_dismissed is True


def test_the_welcome_dialog_links_to_manage_usage(qtbot: QtBot, opened: list[str]) -> None:
    page, _bridge, _core = make_page(qtbot, welcome_pending=True)
    dialog = page.welcome_dialog
    assert dialog is not None
    manage = [b for b in dialog.findChildren(QPushButton) if b.text() == "Manage usage"]
    assert len(manage) == 1
    manage[0].click()
    assert opened == ["https://chatgpt.com/settings/usage"]


def test_the_welcome_dialog_waits_while_the_window_is_hidden(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    page = ChatGPTPage(bridge)  # never shown: the app started hidden in the tray
    qtbot.addWidget(page)
    page.show_state(read_state(sample_state(welcome_pending=True)))
    assert page.welcome_dialog is None
    page.show()  # the player opens the window from the tray
    qtbot.waitUntil(lambda: page.welcome_dialog is not None, timeout=2000)
    assert page.welcome_dialog is not None
    assert page.welcome_dialog.isVisible()


def test_a_hidden_window_does_not_dismiss_the_welcome(qtbot: QtBot) -> None:
    bridge, core = make_bridge()
    page = ChatGPTPage(bridge)
    qtbot.addWidget(page)
    page.show_state(read_state(sample_state(welcome_pending=True)))
    assert core.welcome_dismissed is False
