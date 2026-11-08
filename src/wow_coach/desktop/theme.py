"""Every color, size and style of the desktop app, in one place.

The look is inspired by fantasy game menus like World of Warcraft's: dark stone and leather,
gold trim, red buttons with gold letters, and the coach's answers on parchment. Everything is
our own: the colors are plain values, the heading font is Cinzel (free, SIL Open Font License,
``assets/fonts/``), and no picture or font from Blizzard is used.

Colors are named by what they are for ("surface", "muted", "accent"), never by their value, so
a page never hard-codes a color.

How to style a widget:

* Most widgets look right without doing anything (the stylesheet below covers them).
* Buttons pick a look with a property: ``button.setProperty("kind", "primary")``. The kinds
  are "primary" (the main action: red with gold letters), "secondary" (gold outline),
  "ghost" (text only), "chip" (a small rounded suggestion) and "danger".
* Text picks a look the same way: ``label.setProperty("role", "title")``. The roles are
  "title" and "subtitle" (gold, in the heading font), "muted", "small" and "error".
* Panels with a background use ``setProperty("role", "card")`` (a ``QFrame``).

The small arrow and check-mark pictures used by drop-downs, number boxes and check boxes are
SVG files in ``assets/``. Qt finds them through the search path ``wowcoach:``; ``apply_theme``
sets it up and loads the heading font.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QDir
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

# ---- sizes (pixels) -------------------------------------------------------------------

RADIUS: Final = 8  # rounded corners of cards and inputs (game frames are only a bit round)
RADIUS_SMALL: Final = 6
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

# ---- pictures and fonts ---------------------------------------------------------------

# The folder with the theme's small pictures and fonts, and the name stylesheets use for it.
ASSETS_FOLDER: Final = Path(__file__).parent / "assets"
ASSETS_SEARCH_PATH: Final = "wowcoach"
HEADING_FONT_FILE: Final = ASSETS_FOLDER / "fonts" / "Cinzel.ttf"
HEADING_FONT: Final = "Cinzel"  # titles and headings; body text keeps the computer's own font


@dataclass(frozen=True, slots=True)
class Colors:
    """The color scheme. Every value is a ``#rrggbb`` string."""

    background: str  # the window behind everything
    sidebar: str
    surface: str  # cards, the composer
    surface_raised: str  # hovered rows, the selected page
    border: str  # bronze lines around cards and inputs
    trim: str  # brighter gold-bronze trim on important frames
    text: str
    muted: str  # secondary text
    accent: str  # gold: headings, the selected page, focus
    accent_hover: str
    on_accent: str  # text on a gold background
    button: str  # the main buttons: red, top of the gradient
    button_low: str  # the bottom of the red gradient
    button_hover: str
    on_button: str  # gold letters on a red button
    parchment: str  # the coach's answers
    on_parchment: str  # ink on parchment
    parchment_muted: str  # faded ink (times, sources)
    parchment_edge: str
    player_bubble: str  # the player's own chat bubbles
    on_player_bubble: str
    success: str
    warning: str
    danger: str
    info: str
    name: str = "wow"  # picks the matching pictures in ``assets/``


WOW: Final = Colors(
    background="#0d0b08",
    sidebar="#13100b",
    surface="#1b1610",
    surface_raised="#271f15",
    border="#4a3b22",
    trim="#a07c34",
    text="#f1e6cf",
    muted="#b09f7d",
    accent="#ffd100",
    accent_hover="#ffe066",
    on_accent="#1a1206",
    button="#9e2118",
    button_low="#5c0f0a",
    button_hover="#bb2b1f",
    on_button="#ffd100",
    parchment="#ecdcb4",
    on_parchment="#2b1c0b",
    parchment_muted="#6e5634",
    parchment_edge="#b8954f",
    player_bubble="#12263d",
    on_player_bubble="#dce9ff",
    success="#46d35a",
    warning="#ff9d2e",
    danger="#ec4a36",
    info="#55aaff",
)
# The app has one look. ``DARK`` is the old name some code and tests still use.
DARK: Final = WOW


def current_colors() -> Colors:
    """The colors in use (the app always uses the game-style scheme)."""
    return WOW


def apply_theme(app: QApplication) -> Colors:
    """Style the whole app and return the colors used. Safe to call more than once."""
    colors = current_colors()
    QDir.setSearchPaths(ASSETS_SEARCH_PATH, [str(ASSETS_FOLDER)])
    load_heading_font()
    app.setStyle("Fusion")  # the same base look on Linux, Windows and macOS
    app.setPalette(_palette(colors))
    font = QFont(app.font())
    font.setPointSizeF(BASE_FONT_POINTS)
    app.setFont(font)
    app.setStyleSheet(stylesheet(colors))
    return colors


def load_heading_font() -> bool:
    """Make the heading font available to the app. False when it could not be loaded.

    Without it, Qt simply uses a serif font from the computer, so nothing breaks.
    """
    if HEADING_FONT in QFontDatabase.families():
        return True
    return QFontDatabase.addApplicationFont(str(HEADING_FONT_FILE)) != -1


def heading_font(points: float, *, bold: bool = True) -> QFont:
    """A font in the heading style, for widgets that paint their own text."""
    font = QFont(HEADING_FONT)
    font.setStyleHint(QFont.StyleHint.Serif)
    font.setPointSizeF(points)
    font.setBold(bold)
    return font


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


def asset_url(picture: str, c: Colors) -> str:
    """The stylesheet address of one of the theme's pictures, for example "chevron-down"."""
    return f"{ASSETS_SEARCH_PATH}:{picture}-{c.name}.svg"


def red_gradient(top: str, bottom: str) -> str:
    """A top-to-bottom gradient, the way the game's red buttons are shaded."""
    return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom})"


def stylesheet(c: Colors) -> str:
    """The app-wide Qt stylesheet (Qt's version of CSS)."""
    heading = f'"{HEADING_FONT}", serif'
    return f"""
QWidget {{ color: {c.text}; }}
QMainWindow, QWidget#page {{ background: {c.background}; }}
QWidget#sidebar {{ background: {c.sidebar}; border-right: 1px solid {c.trim}; }}

QLabel[role="title"] {{
    font-family: {heading}; font-size: 19pt; font-weight: 700; color: {c.accent};
}}
QLabel[role="subtitle"] {{
    font-family: {heading}; font-size: 12pt; font-weight: 700; color: {c.accent};
}}
QLabel[role="muted"] {{ color: {c.muted}; }}
QLabel[role="small"] {{ color: {c.muted}; font-size: 9pt; }}
QLabel[role="error"] {{ color: {c.danger}; }}

QFrame[role="card"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-top-color: {c.trim};
    border-radius: {RADIUS}px;
}}

QPushButton {{
    background: {c.surface_raised}; color: {c.text}; border: 1px solid {c.border};
    border-radius: {RADIUS_SMALL}px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {c.trim}; }}
QPushButton:disabled {{ color: {c.muted}; }}
QPushButton[kind="primary"] {{
    background: {red_gradient(c.button, c.button_low)}; color: {c.on_button};
    border: 1px solid {c.trim}; font-weight: 700;
}}
QPushButton[kind="primary"]:hover {{
    background: {red_gradient(c.button_hover, c.button)}; border-color: {c.accent};
}}
QPushButton[kind="primary"]:pressed {{ background: {red_gradient(c.button_low, c.button)}; }}
QPushButton[kind="primary"]:disabled {{
    background: {c.surface_raised}; color: {c.muted}; border-color: {c.border};
}}
QPushButton[kind="secondary"] {{
    background: transparent; border: 1px solid {c.trim}; color: {c.accent};
}}
QPushButton[kind="secondary"]:hover {{ border-color: {c.accent}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {c.muted}; }}
QPushButton[kind="ghost"]:hover {{ color: {c.accent}; }}
QPushButton[kind="chip"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS_PILL}px;
    padding: 5px 12px;
}}
QPushButton[kind="chip"]:hover {{ border-color: {c.trim}; color: {c.accent}; }}
QPushButton[kind="danger"] {{
    background: transparent; border: 1px solid {c.danger}; color: {c.danger};
}}

QPushButton[kind="nav"] {{
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 0px; padding: 9px 12px; text-align: left; color: {c.muted};
}}
QPushButton[kind="nav"]:hover {{ background: {c.surface_raised}; color: {c.text}; }}
QPushButton[kind="nav"]:checked {{
    background: {c.surface_raised}; color: {c.accent}; font-weight: 700;
    border-left: 3px solid {c.accent};
}}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS_SMALL}px;
    padding: 6px 8px; selection-background-color: {c.accent}; selection-color: {c.on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {c.trim};
}}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none;
}}
QComboBox::down-arrow {{ image: url({asset_url("chevron-down", c)}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {c.surface}; border: 1px solid {c.trim}; padding: 4px; outline: none;
    selection-background-color: {c.surface_raised}; selection-color: {c.accent};
}}

QSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 24px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {RADIUS_SMALL}px; }}
QSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: {RADIUS_SMALL}px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c.surface_raised}; }}
QSpinBox::up-arrow {{ image: url({asset_url("chevron-up", c)}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({asset_url("chevron-down", c)}); width: 10px; height: 10px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {c.trim}; border-radius: 4px;
    background: {c.surface};
}}
QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
QCheckBox::indicator:checked {{
    background: {c.accent}; border-color: {c.accent}; image: url({asset_url("check", c)});
}}
QCheckBox::indicator:disabled {{ border-color: {c.border}; background: {c.surface_raised}; }}

QProgressBar {{
    background: {c.surface_raised}; border: 1px solid {c.border}; border-radius: 4px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 3px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {c.trim}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QToolTip {{
    background: {c.surface_raised}; color: {c.text}; border: 1px solid {c.trim};
    border-radius: 4px; padding: 4px 8px;
}}
QMenu {{ background: {c.surface}; border: 1px solid {c.trim}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c.surface_raised}; color: {c.accent}; }}
QDialog {{ background: {c.background}; }}
"""
