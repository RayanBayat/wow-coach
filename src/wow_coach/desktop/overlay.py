"""The overlay: the Coach page as a see-through panel on top of the game.

The player presses a key (or uses the tray menu, or the Overlay button) and the coach appears
over the game; Esc or the same key hides it again, and the keyboard goes back to the game.

What this is, and is not:

* It is **one ordinary window of this program**: frameless, always on top, see-through. It
  never touches the game. No keys are sent to the game, nothing is read from it, and the
  game is not asked to do anything.
* It does **not** make a second copy of the Coach page. While the overlay is shown, the one
  ``CoachPage`` is moved into the panel (the main window shows a note in its place), and when
  the overlay hides it is moved back. So there is one chat, one set of buttons and one set of
  logic.
* It never steals the keyboard by itself. It takes the keyboard only when the player asks for
  it (hotkey, tray menu or button), so the player can type at once.

This file has two classes: ``OverlayPanel`` (the window) and ``OverlayController`` (shows and
hides it, moves the page, and keeps the hotkey and the settings in step).
"""

from typing import Final

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wow_coach.app_settings import (
    DEFAULT_OVERLAY_OPACITY,
    MAX_OVERLAY_OPACITY,
    MIN_OVERLAY_OPACITY,
    AppSettings,
    settings_from_dict,
)
from wow_coach.desktop.hotkey import GlobalHotkey, HotkeyStatus
from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.pages.coach import CoachPage
from wow_coach.desktop.state import StateView
from wow_coach.desktop.theme import RADIUS, SPACE_SMALL, current_colors
from wow_coach.desktop.widgets.bubbles import plain_label

DEFAULT_SIZE: Final = (520, 720)
MINIMUM_SIZE: Final = (380, 440)
EDGE_MARGIN: Final = 24  # distance from the screen edge for the first position
RESIZE_BORDER: Final = 8  # the strip along the edges and corners that can be dragged to resize
SIZE_KEY: Final = "overlay/size"
POSITION_KEY: Final = "overlay/position"

# The words under the buttons, with the hotkey filled in.
HINT_WITH_KEY: Final = "Press {key} anywhere to show or hide the overlay."
HINT_WITHOUT_KEY: Final = (
    "Use the tray menu or this button. To get a key for it, see the Overlay hotkey card in Setup."
)


def default_settings() -> QSettings:
    """Where the overlay remembers its size and place (the player's own settings)."""
    return QSettings("wow-coach", "desktop")


def clean_opacity(percent: object) -> int:
    """``percent`` if it is a whole number from 60 to 100, else the default."""
    if isinstance(percent, bool) or not isinstance(percent, int):
        return DEFAULT_OVERLAY_OPACITY
    in_range = MIN_OVERLAY_OPACITY <= percent <= MAX_OVERLAY_OPACITY
    return percent if in_range else DEFAULT_OVERLAY_OPACITY


class _TopBar(QFrame):
    """The slim bar at the top: a handle to drag the panel by, and two buttons."""

    drag_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayBar")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        title = plain_label("WoW Coach", "small")
        title.setToolTip("Drag here to move the overlay.")
        self.open_app = QPushButton("Open the full app")
        self.open_app.setProperty("kind", "ghost")
        self.open_app.setCursor(Qt.CursorShape.ArrowCursor)
        self.open_app.setToolTip("Hide the overlay and open the full WoW Coach window.")
        self.hide_button = QPushButton("Hide")
        self.hide_button.setProperty("kind", "ghost")
        self.hide_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_button.setToolTip("Hide the overlay (Esc does the same).")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE_SMALL, 0, SPACE_SMALL, 0)
        row.setSpacing(SPACE_SMALL)
        row.addWidget(title, 1)
        row.addWidget(self.open_app)
        row.addWidget(self.hide_button)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Start moving the whole panel when the left button goes down on the bar."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_requested.emit()
        super().mousePressEvent(event)


class OverlayPanel(QWidget):
    """The see-through, always-on-top window that holds the Coach page."""

    # The player wants the panel gone (Hide button, Esc).
    hide_requested = Signal()
    # The player pressed "Open the full app".
    open_app_requested = Signal()
    # The panel is no longer on screen, however that happened.
    hidden = Signal()

    def __init__(self, settings: QSettings | None = None) -> None:
        # A Tool window has no taskbar entry; the other two flags are what lets it float over
        # the game and removes the frame (the page draws its own look).
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._settings = settings if settings is not None else default_settings()
        self.setWindowTitle("WoW Coach overlay")
        self.setObjectName("overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # On macOS a Tool window would vanish whenever another app is in front, which is
        # exactly when the overlay is wanted.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setMouseTracking(True)
        self.setMinimumSize(*MINIMUM_SIZE)
        # The Coach page paints an opaque background. Inside the panel it must be see-through,
        # so only the panel's own rounded background shows.
        self.setStyleSheet("QWidget#page { background: transparent; }")
        self._opacity_percent = DEFAULT_OVERLAY_OPACITY
        self.set_opacity_percent(DEFAULT_OVERLAY_OPACITY)

        self.bar = _TopBar()
        self.bar.setFixedHeight(34)
        self.bar.drag_requested.connect(self._start_move)
        self.bar.open_app.clicked.connect(self.open_app_requested)
        self.bar.hide_button.clicked.connect(self.hide_requested)
        self._column = QVBoxLayout(self)
        # The margin around the content is the strip the player can grab to resize.
        self._column.setContentsMargins(RESIZE_BORDER, RESIZE_BORDER, RESIZE_BORDER, RESIZE_BORDER)
        self._column.setSpacing(0)
        self._column.addWidget(self.bar)
        self._page: Page | None = None

    # ---- the page -----------------------------------------------------------------------

    def adopt(self, page: Page) -> None:
        """Put the page into the panel (it leaves wherever it was)."""
        if self._page is page:
            return
        self._page = page
        self._column.addWidget(page, 1)
        page.show()  # moving a widget to a new parent hides it

    def release(self) -> Page | None:
        """Take the page out again and return it, so the main window can have it back."""
        page, self._page = self._page, None
        if page is not None:
            self._column.removeWidget(page)
            page.setParent(None)
        return page

    @property
    def page(self) -> Page | None:
        """The page now in the panel, if any."""
        return self._page

    # ---- opacity ------------------------------------------------------------------------

    def set_opacity_percent(self, percent: object) -> None:
        """Make the whole panel this solid (60-100 %). A bad value gives the default."""
        self._opacity_percent = clean_opacity(percent)
        self.setWindowOpacity(self._opacity_percent / 100)

    @property
    def opacity_percent(self) -> int:
        """How solid the panel is, in percent."""
        return self._opacity_percent

    # ---- showing and hiding -------------------------------------------------------------

    def show_for_typing(self) -> None:
        """Show the panel where it was last, in front, and give it the keyboard.

        Only called when the player asked for the overlay. The window manager decides who
        gets the keyboard back when the panel hides, so the game gets it back by itself.
        """
        self.resize(self._start_size())
        self.move(self._start_position())
        self.show()
        self.raise_()
        self.activateWindow()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt's method name
        """Remember where the panel was, and tell the controller it is gone."""
        self.remember_geometry()
        self.hidden.emit()
        super().hideEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's method name
        """Esc hides the overlay (a key the page does not use travels up to here)."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide_requested.emit()
            return
        super().keyPressEvent(event)

    # ---- size and place -----------------------------------------------------------------

    def _target_screen_area(self) -> QRect:
        """The usable area of the screen the mouse is on (the one the player is looking at)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _start_size(self) -> QSize:
        area = self._target_screen_area()
        saved = self._settings.value(SIZE_KEY)
        wanted = saved if isinstance(saved, QSize) else QSize(*DEFAULT_SIZE)
        return QSize(
            max(MINIMUM_SIZE[0], min(wanted.width(), area.width() - 2 * EDGE_MARGIN)),
            max(MINIMUM_SIZE[1], min(wanted.height(), area.height() - 2 * EDGE_MARGIN)),
        )

    def _start_position(self) -> QPoint:
        saved = self._settings.value(POSITION_KEY)
        if isinstance(saved, QPoint) and QGuiApplication.screenAt(saved) is not None:
            return saved
        # The first time: the right part of the screen, where the game's side panels are.
        area = self._target_screen_area()
        size = self._start_size()
        return QPoint(
            area.right() - size.width() - EDGE_MARGIN,
            area.top() + max(EDGE_MARGIN, (area.height() - size.height()) // 2),
        )

    def remember_geometry(self) -> None:
        """Save the size and place, so the overlay comes back the same."""
        self._settings.setValue(SIZE_KEY, self.size())
        self._settings.setValue(POSITION_KEY, self.pos())
        self._settings.sync()

    # ---- drawing, moving, resizing ------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802, ARG002 - Qt's signature
        """Draw the rounded, game-style background (the window itself is see-through)."""
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors.background))
        painter.setPen(QColor(colors.trim))
        inner = self.rect().adjusted(
            RESIZE_BORDER // 2, RESIZE_BORDER // 2, -RESIZE_BORDER // 2, -RESIZE_BORDER // 2
        )
        painter.drawRoundedRect(inner, RADIUS, RADIUS)

    def _edges_at(self, position: QPointF) -> Qt.Edge:
        """Which edges of the panel the mouse is on (none in the middle)."""
        edges = Qt.Edge(0)
        if position.x() <= RESIZE_BORDER:
            edges |= Qt.Edge.LeftEdge
        if position.x() >= self.width() - RESIZE_BORDER:
            edges |= Qt.Edge.RightEdge
        if position.y() <= RESIZE_BORDER:
            edges |= Qt.Edge.TopEdge
        if position.y() >= self.height() - RESIZE_BORDER:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Show a resize arrow over the edges and corners."""
        edges = self._edges_at(event.position())
        horizontal = Qt.Edge.LeftEdge | Qt.Edge.RightEdge
        vertical = Qt.Edge.TopEdge | Qt.Edge.BottomEdge
        diagonal_back = {Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge}
        if not edges:
            self.unsetCursor()
        elif edges in diagonal_back:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges & horizontal and edges & vertical:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & horizontal:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Start a resize when the left button goes down on an edge or corner."""
        edges = self._edges_at(event.position())
        handle = self.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and edges and handle is not None:
            handle.startSystemResize(edges)  # the window system does the dragging
            return
        super().mousePressEvent(event)

    def _start_move(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()  # the window system does the dragging


class OverlayController(QObject):
    """Shows and hides the overlay and keeps the hotkey and settings in step."""

    # The hint under the buttons changed (the hotkey, or whether it works).
    hint_changed = Signal(str)

    def __init__(
        self,
        window: MainWindow,
        hotkey: GlobalHotkey,
        panel: OverlayPanel | None = None,
    ) -> None:
        """Create it.

        Args:
            window: The main window (the Coach page lives there when the overlay is hidden).
            hotkey: The global hotkey for this system (a fake in tests).
            panel: The overlay window (default: a new one).
        """
        super().__init__()
        self._window = window
        self._hotkey = hotkey
        self.panel = panel if panel is not None else OverlayPanel()
        self._page = self._find_page()
        self._showing = False
        self.panel.hide_requested.connect(self.hide_overlay)
        self.panel.hidden.connect(self._on_panel_hidden)
        self.panel.open_app_requested.connect(self.open_full_app)
        window.page_wanted_back.connect(self.hide_overlay)
        hotkey.activated.connect(self.toggle)
        hotkey.status_changed.connect(self._emit_hint)
        if self._page is not None:
            self._page.overlay_requested.connect(self.toggle)
            self._page.navigate.connect(self._on_page_navigate)
            self.hint_changed.connect(self._page.set_overlay_hint)

    def _find_page(self) -> CoachPage | None:
        for page in self._window.pages:
            if isinstance(page, CoachPage):
                return page
        return None

    # ---- settings and the hotkey ---------------------------------------------------------

    def start(self, settings: AppSettings) -> None:
        """Use the saved settings: set the opacity and start listening for the key."""
        self.apply(settings)

    def on_state(self, state: object) -> None:
        """A new state arrived: follow any change of the overlay settings."""
        if isinstance(state, StateView) and state.settings:
            self.apply(settings_from_dict(state.settings))

    def apply(self, settings: AppSettings) -> None:
        """Take over the overlay opacity and hotkey (the hotkey restarts only if it changed)."""
        self.panel.set_opacity_percent(settings.overlay_opacity)
        if settings.overlay_hotkey != self._hotkey.sequence:
            self._hotkey.register(settings.overlay_hotkey)
        self._emit_hint()

    @property
    def hotkey(self) -> GlobalHotkey:
        """The global hotkey (the Setup page shows its status)."""
        return self._hotkey

    def hint(self) -> str:
        """One sentence about how to open the overlay, for tooltips."""
        status: HotkeyStatus = self._hotkey.status
        if status.active and self._hotkey.sequence:
            return HINT_WITH_KEY.format(key=self._hotkey.sequence)
        return HINT_WITHOUT_KEY

    def _emit_hint(self) -> None:
        self.hint_changed.emit(self.hint())

    # ---- showing and hiding -------------------------------------------------------------

    @property
    def is_shown(self) -> bool:
        """True while the overlay is on screen."""
        return self._showing

    def toggle(self) -> None:
        """Show the overlay if it is hidden, hide it if it is shown."""
        if self._showing:
            self.hide_overlay()
        else:
            self.show_overlay()

    def show_overlay(self) -> None:
        """Move the Coach page into the panel, show the panel and focus the question box."""
        page = self._page
        if self._showing or page is None:
            return
        taken = self._window.take_page(page.name)
        if taken is None:
            return
        self._showing = True
        page.set_in_overlay(True)
        self.panel.adopt(taken)
        self.panel.show_for_typing()
        page.focus_composer()

    def hide_overlay(self) -> None:
        """Hide the panel. The page goes back to the main window by itself (see below)."""
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self._on_panel_hidden()  # shown flag set but the window never appeared

    def _on_panel_hidden(self) -> None:
        """The panel is gone (by any route): give the page back to the main window."""
        if not self._showing:
            return
        self._showing = False
        page = self.panel.release()
        if page is not None:
            self._window.return_page(page)
        if self._page is not None:
            self._page.set_in_overlay(False)

    def open_full_app(self) -> None:
        """Hide the overlay and bring the main window to the front."""
        self.hide_overlay()
        self._window.bring_to_front()

    def _on_page_navigate(self, _name: str) -> None:
        """A button on the page (for example "Sign in") wants another page: that needs the app."""
        if self._showing:
            self.open_full_app()

    def close(self) -> None:
        """The app is closing: hide the panel and let go of the hotkey."""
        self.hide_overlay()
        self._hotkey.unregister()
