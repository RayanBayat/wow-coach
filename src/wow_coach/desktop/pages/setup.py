"""The Setup page: a friendly checklist that gets the game and the app ready.

Each item is a card with a status icon, one sentence and (when there is something to do) one
button. All disk work and downloads run in a background thread, so the window never waits; the
results come back as Qt signals. The checks and actions themselves live in ``setup_checks.py``
and ``shortcuts.py`` and know nothing about Qt.
"""

import importlib.metadata
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wow_coach.config import config_path
from wow_coach.desktop.bridge import CoreBridge, Runner, run_in_thread
from wow_coach.desktop.hotkey import GlobalHotkey, HotkeyState
from wow_coach.desktop.icons import icon
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.setup_checks import (
    ActionResult,
    Check,
    SetupReport,
    Status,
    change_game_folder,
    create_answers_folder,
    install_or_update_addon,
    make_report,
)
from wow_coach.desktop.shortcuts import (
    INSTALL_COMMAND,
    UNSTABLE_SENTENCE,
    ShortcutError,
    ShortcutFolders,
    ShortcutMaker,
    ShortcutState,
    default_folders,
    find_stable_program,
    is_supported,
    overlay_command,
)
from wow_coach.desktop.theme import SPACE, SPACE_LARGE, SPACE_SMALL, Colors, current_colors
from wow_coach.web import FetchBytes, PoliteFetcher, build_user_agent

_log = logging.getLogger(__name__)

STATUS_ICONS = {Status.OK: "ok", Status.ATTENTION: "attention", Status.PROBLEM: "problem"}
STATUS_ICON_SIZE = 26
KEYBINDING_SENTENCE = (
    'In WoW, open Options → Keybindings → HeroBridge and pick a key for "Save for the '
    'coach (reloads the interface)". Press it whenever you want me to see your latest progress. '
    "Not in the list? Quit WoW completely and start it again once: the game only finds new "
    "key bindings when it starts."
)
# What the shortcut menu is called: Windows calls it the Start menu, Linux an app menu.
MENU_NAME = "Start menu" if sys.platform == "win32" else "app menu"
NO_SHORTCUTS_SENTENCE = "Shortcuts are not available on macOS yet."

# The "Overlay hotkey" card: what it says when the key does not work by itself.
OVERLAY_INTRO = (
    "A key that shows or hides the coach on top of your game, so you can ask without leaving it."
)
OVERLAY_STEPS_KDE = (
    "To set the key by hand on KDE: open System Settings → Keyboard → Shortcuts, choose "
    "Add New → Command or Script, paste this command, then pick your key:"
)
OVERLAY_STEPS_LINUX = (
    "To set the key by hand: open your desktop's keyboard settings, add a custom shortcut, "
    "paste this command as its command, then pick your key:"
)
OVERLAY_STEPS_WINDOWS = (
    "Try another key in Settings. Or make a shortcut to this command and give it a "
    '"Shortcut key" in its Properties:'
)
OVERLAY_STEPS_MAC = (
    "macOS has no global hotkey here yet. The tray menu and the Overlay button work. You can "
    "make a key yourself with the Shortcuts app (a Run Shell Script action running this "
    "command); we have not tested that:"
)
OVERLAY_MENU_FIRST = (
    f"Tip: add WoW Coach to your {MENU_NAME} first (the {MENU_NAME.capitalize()} card above). "
    "That is how your "
    "desktop learns about the app. Then press Try again."
)
OVERLAY_UNSTABLE = "This program path may be temporary. Install WoW Coach once, as shown above."


def overlay_steps(platform: str, desktop: str) -> str:
    """The plain steps for adding the overlay key by hand on this system."""
    if platform == "win32":
        return OVERLAY_STEPS_WINDOWS
    if platform == "darwin":
        return OVERLAY_STEPS_MAC
    return OVERLAY_STEPS_KDE if "kde" in desktop.lower() else OVERLAY_STEPS_LINUX


def _style(c: Colors) -> str:
    """Styles only this page needs: the install command box."""
    return f"""
QLabel[role="command"] {{
    background: {c.surface_raised}; border: 1px solid {c.border}; border-radius: 8px;
    padding: 8px 10px; font-family: monospace;
}}
QLabel[role="cardtitle"] {{ font-weight: 600; }}
"""


@dataclass
class SetupServices:
    """Everything the page uses from the outside world (tests replace the parts)."""

    app_version: str
    config_file: Path
    download: FetchBytes
    shortcut_maker: ShortcutMaker | None  # None where shortcuts are not supported
    runner: Runner = run_in_thread
    program: Path | None = None  # the stable ``wow-coach-app`` program, or None
    platform: str = sys.platform
    desktop: str = ""  # the desktop's name, for example "KDE" (``$XDG_CURRENT_DESKTOP``)
    pick_folder: Callable[[QWidget], str] = lambda parent: QFileDialog.getExistingDirectory(
        parent, "Choose the _forever_ folder of World of Warcraft"
    )


def _download_from_web(url: str) -> bytes:
    """Download a file politely (made when used, in the background thread)."""
    return PoliteFetcher(build_user_agent()).fetch_bytes(url)


def real_services() -> SetupServices:
    """The services of the real app."""
    folders: ShortcutFolders | None = default_folders() if is_supported() else None
    maker = None
    if folders is not None:
        maker = ShortcutMaker(folders, program=find_stable_program())
    return SetupServices(
        app_version=importlib.metadata.version("wow-coach"),
        config_file=config_path(environ=os.environ),
        download=_download_from_web,
        shortcut_maker=maker,
        program=find_stable_program(),
        desktop=os.environ.get("XDG_CURRENT_DESKTOP", ""),
    )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What the page shows: the checks and which shortcuts exist."""

    report: SetupReport
    shortcuts: ShortcutState | None


class SetupCard(QFrame):
    """One checklist item: a status icon, a title, one sentence and an optional button."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self._icon_name = "info"
        self._icon_color_name = "info"
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        self._title = QLabel(title)
        self._title.setProperty("role", "cardtitle")
        self.sentence = QLabel()
        self.sentence.setWordWrap(True)
        self.sentence.setTextFormat(Qt.TextFormat.PlainText)  # paths and OS errors, never markup
        self.sentence.setProperty("role", "muted")
        self.sentence.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.command = QLabel(INSTALL_COMMAND)
        self.command.setProperty("role", "command")
        self.command.setWordWrap(True)
        self.command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.command.hide()
        self.button = QPushButton()
        self.button.setProperty("kind", "secondary")
        self.button.hide()

        text = QVBoxLayout()
        self.text_column = text  # cards with more to say add to it
        text.setSpacing(SPACE_SMALL // 2)
        text.addWidget(self._title)
        text.addWidget(self.sentence)
        text.addWidget(self.command)
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE_LARGE, SPACE, SPACE_LARGE, SPACE)
        row.setSpacing(SPACE)
        row.addWidget(self._status_icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        row.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

    def show_state(self, icon_name: str, sentence: str) -> None:
        """Set the status icon (``ok``, ``attention``, ``problem`` or ``info``) and sentence."""
        self._icon_name = icon_name
        self.sentence.setText(sentence)
        self.repaint_icon()

    def repaint_icon(self) -> None:
        """Draw the status icon in the current theme's color."""
        colors = current_colors()
        color = {
            "ok": colors.success,
            "attention": colors.warning,
            "problem": colors.danger,
        }.get(self._icon_name, colors.info)
        pixmap = icon(self._icon_name, color, STATUS_ICON_SIZE).pixmap(
            STATUS_ICON_SIZE, STATUS_ICON_SIZE
        )
        self._status_icon.setPixmap(pixmap)

    def show_button(self, text: str, tooltip: str, *, primary: bool = False) -> None:
        """Show the card's button with this label."""
        self.button.setText(text)
        self.button.setToolTip(tooltip)
        self.button.setProperty("kind", "primary" if primary else "secondary")
        self.button.style().unpolish(self.button)  # make Qt read the changed property
        self.button.style().polish(self.button)
        self.button.updateGeometry()  # the new text and style may need a different width
        self.button.show()


class OverlayHotkeyCard(SetupCard):
    """The "Overlay hotkey" card: whether the key works, and how to add it by hand if not.

    It reuses the card's command box and button: the box shows the command and the button
    copies it. A second button tries the automatic way again.
    """

    def __init__(self) -> None:
        super().__init__("Overlay hotkey")
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.TextFormat.PlainText)
        self.steps.setProperty("role", "muted")
        self.retry_button = QPushButton("Try again")
        self.retry_button.setProperty("kind", "secondary")
        self.retry_button.setToolTip("Ask your desktop for the key again.")
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setTextFormat(Qt.TextFormat.PlainText)
        self.tip.setProperty("role", "muted")
        self.text_column.insertWidget(2, self.steps)  # between the sentence and the command
        self.text_column.addWidget(self.tip)
        self.text_column.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignLeft)


class SetupPage(Page):
    """The checklist that gets the game, the addon and the shortcuts ready."""

    name = "setup"
    title = "Setup"

    # Results come from a background thread; signals bring them to the window's thread.
    _snapshot_ready = Signal(object)
    _action_finished = Signal(object)
    # The player pressed "Restart WoW Coach" (after changing the game folder).
    restart_requested = Signal()

    def __init__(
        self,
        bridge: CoreBridge,
        parent: QWidget | None = None,
        services: SetupServices | None = None,
    ) -> None:
        super().__init__(bridge, parent)
        self._services = services
        self._game_dir: Path | None = None
        self._snapshot: Snapshot | None = None
        self._busy = False
        self._hotkey: GlobalHotkey | None = None
        self._build()
        self.setStyleSheet(_style(current_colors()))
        self._snapshot_ready.connect(self._show_snapshot)
        self._action_finished.connect(self._on_action_finished)

    # ---- building ----------------------------------------------------------------------

    def _build(self) -> None:
        heading = QLabel(self.title)
        heading.setProperty("role", "title")
        intro = QLabel("Let's make sure WoW Coach and your game can talk to each other.")
        intro.setProperty("role", "muted")
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.hide()
        self.restart_button = QPushButton("Restart WoW Coach")
        self.restart_button.setProperty("kind", "primary")
        self.restart_button.setToolTip("Close WoW Coach and open it again, using the new folder.")
        self.restart_button.clicked.connect(self.restart_requested)
        self.restart_button.hide()

        self.game_card = SetupCard("Game folder")
        self.addon_card = SetupCard("HeroBridge addon")
        self.answers_card = SetupCard("Answers folder")
        self.key_card = SetupCard('"Save for the coach" key')
        self.key_card.show_state("info", KEYBINDING_SENTENCE)
        self.overlay_card = OverlayHotkeyCard()
        self.overlay_card.hide()  # shown once the app gives the page its hotkey
        self.menu_card = SetupCard(MENU_NAME.capitalize())
        self.login_card = SetupCard("Start with my computer")
        self.no_shortcuts = QLabel(NO_SHORTCUTS_SENTENCE)
        self.no_shortcuts.setProperty("role", "muted")

        self.game_card.button.clicked.connect(self._choose_folder)
        self.addon_card.button.clicked.connect(self._install_addon)
        self.answers_card.button.clicked.connect(self._create_answers)
        self.menu_card.button.clicked.connect(lambda: self._toggle_shortcut(at_login=False))
        self.login_card.button.clicked.connect(lambda: self._toggle_shortcut(at_login=True))
        self.overlay_card.button.clicked.connect(self._copy_overlay_command)
        self.overlay_card.retry_button.clicked.connect(self._retry_hotkey)

        column = QVBoxLayout()
        column.setSpacing(SPACE)
        column.addWidget(heading)
        column.addWidget(intro)
        column.addWidget(self.message)
        column.addWidget(self.restart_button, 0, Qt.AlignmentFlag.AlignLeft)
        for card in (self.game_card, self.addon_card, self.answers_card, self.key_card):
            column.addWidget(card)
        column.addWidget(self.menu_card)
        column.addWidget(self.login_card)
        column.addWidget(self.no_shortcuts)
        column.addWidget(self.overlay_card)
        column.addStretch(1)

        content = QWidget()
        content.setObjectName("page")
        content.setLayout(column)
        column.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.menu_card.show_state("info", "Checking…")
        self.login_card.show_state("info", "Checking…")
        for card in (self.game_card, self.addon_card, self.answers_card):
            card.show_state("info", "Checking…")
        self.no_shortcuts.hide()

    @property
    def services(self) -> SetupServices:
        """The outside-world parts (created on first use)."""
        if self._services is None:
            self._services = real_services()
        return self._services

    # ---- showing what the checks found ---------------------------------------------------

    def set_game_dir(self, game_dir: Path | None) -> None:
        """Tell the page which game folder the app is watching, and check everything."""
        self._game_dir = game_dir
        self.refresh()

    def refresh(self) -> None:
        """Run the checks in the background; the page redraws when they are done."""
        game_dir = self._game_dir
        services = self.services

        def work() -> None:
            report = make_report(game_dir, services.app_version)
            maker = services.shortcut_maker
            shortcuts = maker.state() if maker is not None else None
            self._snapshot_ready.emit(Snapshot(report, shortcuts))

        services.runner(work)

    def _show_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, Snapshot):
            return
        self._snapshot = snapshot
        report = snapshot.report
        self._show_check(self.game_card, report.game_folder)
        self.game_card.show_button(
            "Change…", "Choose the folder called _forever_ in your World of Warcraft folder."
        )
        self._show_addon(report)
        self._show_answers(report)
        self._show_shortcuts(snapshot.shortcuts)
        self._show_overlay_card()  # the tip depends on whether the menu entry exists
        self._apply_busy()

    def _show_check(self, card: SetupCard, check: Check) -> None:
        card.show_state(STATUS_ICONS[check.status], check.sentence)

    def _show_addon(self, report: SetupReport) -> None:
        card = self.addon_card
        self._show_check(card, report.addon)
        folder_ok = self._game_dir is not None and report.game_folder.status is Status.OK
        if not folder_ok or report.addon_is_link or report.addon.status is Status.OK:
            card.button.hide()
        elif report.addon_installed is None:
            card.show_button(
                "Install HeroBridge", "Download HeroBridge and put it in your game.", primary=True
            )
        else:
            card.show_button(
                "Update HeroBridge", "Replace HeroBridge with the matching version.", primary=True
            )

    def _show_answers(self, report: SetupReport) -> None:
        card = self.answers_card
        self._show_check(card, report.answers_folder)
        if (
            report.answers_folder.status is Status.PROBLEM
            and report.game_folder.status is Status.OK
        ):
            card.show_button(
                "Create it", "Make the folder where I put my answers for the game.", primary=True
            )
        else:
            card.button.hide()

    def _show_shortcuts(self, state: ShortcutState | None) -> None:
        maker = self.services.shortcut_maker
        supported = maker is not None and state is not None
        for card in (self.menu_card, self.login_card):
            card.setVisible(supported)
        self.no_shortcuts.setVisible(not supported)
        if maker is None or state is None:
            return
        cannot = maker.needs_stable_program
        for card in (self.menu_card, self.login_card):
            card.command.setVisible(cannot)
        if cannot:
            self.menu_card.show_state("attention", UNSTABLE_SENTENCE)
            self.login_card.show_state("attention", UNSTABLE_SENTENCE)
            self.menu_card.button.hide()
            self.login_card.button.hide()
            return
        self._show_toggle(
            self.menu_card,
            state.in_menu,
            on_text=f"WoW Coach is in your {MENU_NAME}.",
            off_text=f"Add WoW Coach to your {MENU_NAME}, so you can open it like any other app.",
            add=f"Add to my {MENU_NAME}",
            remove="Remove",
        )
        self._show_toggle(
            self.login_card,
            state.at_login,
            on_text="WoW Coach starts quietly in the tray when you log in.",
            off_text="Start WoW Coach when you log in, so it is ready when you play.",
            add="Start when I log in",
            remove="Stop starting",
        )

    def _show_toggle(
        self, card: SetupCard, is_on: bool, *, on_text: str, off_text: str, add: str, remove: str
    ) -> None:
        card.show_state("ok" if is_on else "info", on_text if is_on else off_text)
        if is_on:
            card.show_button(remove, "Remove this shortcut again.")
        else:
            card.show_button(add, "Make this shortcut. You can remove it later.", primary=True)

    # ---- the overlay hotkey card -----------------------------------------------------------

    def set_hotkey(self, hotkey: GlobalHotkey) -> None:
        """Tell the page which global hotkey the app uses, so the card can show how it is doing."""
        self._hotkey = hotkey
        hotkey.status_changed.connect(self._show_overlay_card)
        self._show_overlay_card()

    def overlay_command_text(self) -> str:
        """The command a keyboard shortcut runs to show or hide the overlay."""
        services = self.services
        return overlay_command(services.program, services.platform)

    def _show_overlay_card(self) -> None:
        card = self.overlay_card
        hotkey = self._hotkey
        if hotkey is None:
            return
        status = hotkey.status
        working = status.active
        waiting = status.state in (HotkeyState.STARTING, HotkeyState.OFF)
        icon_name = "ok" if working else "info" if waiting else "attention"
        card.show_state(icon_name, status.message or OVERLAY_INTRO)
        services = self.services
        card.steps.setText(overlay_steps(services.platform, services.desktop))
        card.command.setText(self.overlay_command_text())
        card.tip.setText(self._overlay_tip())
        by_hand = not working and not waiting
        for widget in (card.steps, card.command):
            widget.setVisible(by_hand)
        card.tip.setVisible(by_hand and bool(card.tip.text()))
        card.retry_button.setVisible(
            by_hand and not services.platform.startswith("darwin") and bool(hotkey.sequence)
        )
        card.show_button("Copy command", "Copy the command that shows or hides the overlay.")
        card.show()

    def _overlay_tip(self) -> str:
        """Extra advice: the menu entry first, or install the program first."""
        services = self.services
        snapshot = self._snapshot
        if services.program is None:
            return OVERLAY_UNSTABLE
        linux = services.platform.startswith("linux")
        if linux and snapshot is not None and snapshot.shortcuts is not None:
            return "" if snapshot.shortcuts.in_menu else OVERLAY_MENU_FIRST
        return ""

    def _copy_overlay_command(self) -> None:
        QApplication.clipboard().setText(self.overlay_command_text())
        self._show_message("Copied. Paste it as the command of a keyboard shortcut.", error=False)

    def _retry_hotkey(self) -> None:
        if self._hotkey is not None and self._hotkey.sequence:
            self._hotkey.register(self._hotkey.sequence)

    # ---- actions -------------------------------------------------------------------------

    def _choose_folder(self) -> None:
        chosen = self.services.pick_folder(self)
        if not chosen:
            return  # the player cancelled the dialog
        folder = Path(chosen)
        services = self.services

        def work() -> ActionResult:
            result = change_game_folder(folder, services.config_file)
            if result.ok:
                self._game_dir = folder
            return result

        self._run_action(work)

    def _install_addon(self) -> None:
        game_dir = self._game_dir
        services = self.services
        if game_dir is None:
            return
        self._run_action(
            lambda: install_or_update_addon(game_dir, services.app_version, services.download)
        )

    def _create_answers(self) -> None:
        game_dir = self._game_dir
        if game_dir is not None:
            self._run_action(lambda: create_answers_folder(game_dir))

    def _toggle_shortcut(self, *, at_login: bool) -> None:
        maker = self.services.shortcut_maker
        snapshot = self._snapshot
        if maker is None or snapshot is None or snapshot.shortcuts is None:
            return
        wanted = not (snapshot.shortcuts.at_login if at_login else snapshot.shortcuts.in_menu)

        def work() -> ActionResult:
            try:
                if at_login:
                    maker.set_at_login(wanted)
                else:
                    maker.set_in_menu(wanted)
            except ShortcutError as error:
                return ActionResult(False, str(error))
            return ActionResult(True, "Done.")

        self._run_action(work)

    def _run_action(self, work: Callable[[], ActionResult]) -> None:
        """Run one action in the background; buttons stay off until it is finished."""
        self._busy = True
        self._apply_busy()
        self._show_message("Working on it…", error=False)

        def job() -> None:
            try:
                result = work()
            except Exception as error:
                # A corrupt download (BadZipFile) or a slow PowerShell (TimeoutExpired) are not
                # our own error types. If one escaped, the finished signal would never fire and
                # every button would stay off for good. So catch everything, log it, say it.
                _log.exception("A Setup action failed")
                result = ActionResult(
                    False, f"That didn't work: {error}. Try again, or see Troubleshooting."
                )
            self._action_finished.emit(result)

        self.services.runner(job)

    def _on_action_finished(self, result: object) -> None:
        self._busy = False
        self.restart_button.hide()
        if isinstance(result, ActionResult):
            self._show_message(result.sentence, error=not result.ok)
            self.restart_button.setVisible(result.ok and result.needs_restart)
        self.refresh()

    def _apply_busy(self) -> None:
        for card in (
            self.game_card,
            self.addon_card,
            self.answers_card,
            self.menu_card,
            self.login_card,
        ):
            card.button.setEnabled(not self._busy)

    def _show_message(self, text: str, *, error: bool) -> None:
        self.message.setProperty("role", "error" if error else "muted")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        self.message.show()

    # ---- page hooks ----------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt's name
        """Check again whenever the page is shown (the player may have changed things)."""
        super().showEvent(event)
        if self._snapshot is not None and not self._busy:
            self.refresh()

    def on_theme_changed(self) -> None:
        """Redo the status icons and the page styles in the new colors."""
        self.setStyleSheet(_style(current_colors()))
        for card in (
            self.game_card,
            self.addon_card,
            self.answers_card,
            self.key_card,
            self.menu_card,
            self.login_card,
            self.overlay_card,
        ):
            card.repaint_icon()
