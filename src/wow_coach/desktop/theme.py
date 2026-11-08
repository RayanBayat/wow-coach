"""Every color, size and style of the desktop app, in one place.

The app follows the computer's light or dark mode. Colors are named by what they are for
("surface", "muted", "accent"), never by their value, so a page never hard-codes a color.

How to style a widget:

* Most widgets look right without doing anything (the stylesheet below covers them).
* Buttons pick a look with a property: ``button.setProperty("kind", "primary")``. The kinds
  are "primary" (the main action, gold), "secondary" (outlined), "ghost" (text only),
  "chip" (a small rounded suggestion) and "danger".
* Text picks a look the same way: ``label.setProperty("role", "title")``. The roles are
  "title", "subtitle", "muted", "small" and "error".
* Panels with a background use ``setProperty("role", "card")`` (a ``QFrame``).
"""

from dataclasses import dataclass
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

# ---- sizes (pixels) -------------------------------------------------------------------

RADIUS: Final = 12  # rounded corners of cards and inputs
RADIUS_SMALL: Final = 8
RADIUS_PILL: Final = 14  # chips and status pills
SPACE: Final = 12  # the normal gap between things
SPACE_SMALL: Final = 6
SPACE_LARGE: Final = 20
SIDEBAR_WIDTH: Final = 200
BASE_FONT_POINTS: Final = 10.5

# ---- animation lengths (milliseconds) -------------------------------------------------

FADE_MS: Final = 180  # a new message fading in
SCROLL_MS: Final = 260  # the chat gliding to the newest message
PAGE_MS: Final = 140  # switching pages


@dataclass(frozen=True, slots=True)
class Colors:
    """One color scheme. Every value is a ``#rrggbb`` string."""

    background: str  # the window behind everything
    sidebar: str
    surface: str  # cards, the composer
    surface_raised: str  # the coach's chat bubbles, hovered rows
    border: str
    text: str
    muted: str  # secondary text
    accent: str  # gold: the main buttons, the selected page
    accent_hover: str
    on_accent: str  # text on a gold button
    player_bubble: str  # the player's own chat bubbles
    on_player_bubble: str
    success: str
    warning: str
    danger: str
    info: str


DARK: Final = Colors(
    background="#0f1218",
    sidebar="#131820",
    surface="#171d27",
    surface_raised="#1e2532",
    border="#283142",
    text="#e8ecf3",
    muted="#97a2b5",
    accent="#e3b35a",
    accent_hover="#f0c370",
    on_accent="#1c1405",
    player_bubble="#2c4a7c",
    on_player_bubble="#f3f6fb",
    success="#4fbf7f",
    warning="#e0a43a",
    danger="#e36868",
    info="#5aa9e6",
)

LIGHT: Final = Colors(
    background="#f5f6fa",
    sidebar="#eceff5",
    surface="#ffffff",
    surface_raised="#f0f2f7",
    border="#dbe0e9",
    text="#1b2230",
    muted="#5d6a7e",
    accent="#a8761a",
    accent_hover="#94670f",
    on_accent="#ffffff",
    player_bubble="#d9e6ff",
    on_player_bubble="#12254a",
    success="#25804f",
    warning="#9a6a07",
    danger="#b93a3a",
    info="#2b6fb3",
)


def current_colors() -> Colors:
    """The colors for the computer's current light or dark mode (dark when unknown)."""
    scheme = QGuiApplication.styleHints().colorScheme()
    return LIGHT if scheme == Qt.ColorScheme.Light else DARK


def apply_theme(app: QApplication) -> Colors:
    """Style the whole app for the current light or dark mode, and return the colors used.

    Call it once at start and again whenever the computer switches mode
    (``QGuiApplication.styleHints().colorSchemeChanged``).
    """
    colors = current_colors()
    app.setStyle("Fusion")  # the same clean base look on Linux, Windows and macOS
    app.setPalette(_palette(colors))
    font = QFont(app.font())
    font.setPointSizeF(BASE_FONT_POINTS)
    app.setFont(font)
    app.setStyleSheet(stylesheet(colors))
    return colors


def _palette(c: Colors) -> QPalette:
    """The Qt palette: used by the few things the stylesheet does not reach (menus, tooltips)."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.background,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.surface_raised,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.on_accent,
        QPalette.ColorRole.ToolTipBase: c.surface_raised,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Link: c.info,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    return palette


def stylesheet(c: Colors) -> str:
    """The app-wide Qt stylesheet (Qt's version of CSS) for one color scheme."""
    return f"""
QWidget {{ color: {c.text}; }}
QMainWindow, QWidget#page {{ background: {c.background}; }}
QWidget#sidebar {{ background: {c.sidebar}; border-right: 1px solid {c.border}; }}

QLabel[role="title"] {{ font-size: 17pt; font-weight: 600; }}
QLabel[role="subtitle"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {c.muted}; }}
QLabel[role="small"] {{ color: {c.muted}; font-size: 9pt; }}
QLabel[role="error"] {{ color: {c.danger}; }}

QFrame[role="card"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS}px;
}}

QPushButton {{
    background: {c.surface_raised}; color: {c.text}; border: 1px solid {c.border};
    border-radius: {RADIUS_SMALL}px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {c.muted}; }}
QPushButton:disabled {{ color: {c.muted}; }}
QPushButton[kind="primary"] {{
    background: {c.accent}; color: {c.on_accent}; border: none; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: {c.accent_hover}; }}
QPushButton[kind="primary"]:disabled {{ background: {c.border}; color: {c.muted}; }}
QPushButton[kind="secondary"] {{ background: transparent; border: 1px solid {c.accent}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {c.muted}; }}
QPushButton[kind="ghost"]:hover {{ color: {c.text}; }}
QPushButton[kind="chip"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS_PILL}px;
    padding: 5px 12px;
}}
QPushButton[kind="chip"]:hover {{ border-color: {c.accent}; color: {c.accent}; }}
QPushButton[kind="danger"] {{
    background: transparent; border: 1px solid {c.danger}; color: {c.danger};
}}

QPushButton[kind="nav"] {{
    background: transparent; border: none; border-radius: {RADIUS_SMALL}px;
    padding: 9px 12px; text-align: left; color: {c.muted};
}}
QPushButton[kind="nav"]:hover {{ background: {c.surface_raised}; color: {c.text}; }}
QPushButton[kind="nav"]:checked {{
    background: {c.surface_raised}; color: {c.accent}; font-weight: 600;
}}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS_SMALL}px;
    padding: 6px 8px; selection-background-color: {c.accent}; selection-color: {c.on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {c.accent};
}}
QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border}; }}

QCheckBox {{ spacing: 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QToolTip {{
    background: {c.surface_raised}; color: {c.text}; border: 1px solid {c.border};
    border-radius: 6px; padding: 4px 8px;
}}
"""
