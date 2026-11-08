"""All icons of the desktop app, drawn by us as small SVG pictures (text, no image files).

Why SVG text: it stays sharp at any size, it can be painted in any color (so the icons follow
the light and dark themes) and it needs no files to ship. Every line icon is drawn on a 24 by
24 grid with round line ends, and the placeholder ``COLOR`` is replaced by the wanted color.
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

COLOR: Final = "COLOR"  # replaced by the real color when an icon is drawn

_LINE_START: Final = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    f'stroke="{COLOR}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
)

# The inside of each icon (what goes between the <svg> tags).
_SHAPES: Final[dict[str, str]] = {
    # A speech bubble with two lines of text.
    "coach": (
        '<path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-8l-5 4v-4H5a2 2 0 0 1-2-2V6'
        'a2 2 0 0 1 2-2z"/>'
        '<path d="M8 9h8M8 12.5h5"/>'
    ),
    # Three sliders.
    "settings": (
        '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/>'
        '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/>'
        '<circle cx="17" cy="17" r="2"/>'
    ),
    # A key.
    "chatgpt": ('<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/>'),
    # A wrench.
    "setup": '<path d="M15.5 4.5a4.2 4.2 0 0 0 4 6L10 20a2.1 2.1 0 0 1-3-3l9.5-9.5z"/>',
    # A shield with a tick.
    "privacy": (
        '<path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z"/>'
        '<path d="M8.5 12l2.5 2.5 4.5-5"/>'
    ),
    # Two arrows going round.
    "refresh": (
        '<path d="M20 11a8 8 0 0 0-14.5-4M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>'
    ),
    # A pin.
    "pin": ('<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>'),
    # A paper plane.
    "send": '<path d="M21 3L10 14M21 3l-7 18-4-7-7-4z"/>',
    # Status icons for the Setup page.
    "ok": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    "attention": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18l.01 0"/>',
    "problem": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
}

# The app icon: a gold compass rose on a dark rounded square. Drawn by us, not WoW's logo.
APP_ICON_SVG: Final = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#131820"/>'
    '<rect x="2" y="2" width="60" height="60" rx="12" fill="none" '
    'stroke="#283142" stroke-width="2"/>'
    '<circle cx="32" cy="32" r="21" fill="none" stroke="#e3b35a" stroke-width="2.5"/>'
    # The four long points (north is the brightest).
    '<path d="M32 8l6 18-6 6-6-6z" fill="#f0c370"/>'
    '<path d="M32 56l-6-18 6-6 6 6z" fill="#e3b35a"/>'
    '<path d="M8 32l18-6 6 6-6 6z" fill="#e3b35a"/>'
    '<path d="M56 32l-18 6-6-6 6-6z" fill="#e3b35a"/>'
    # The four short points between them.
    '<path d="M32 32l11-11M32 32l11 11M32 32L21 21M32 32l-11 11" '
    'stroke="#97a2b5" stroke-width="2" stroke-linecap="round"/>'
    '<circle cx="32" cy="32" r="3" fill="#131820"/>'
    "</svg>"
)

ICON_NAMES: Final = tuple(_SHAPES)


def icon_svg(name: str, color: str) -> str:
    """The SVG text of line icon ``name`` painted in ``color`` (like ``#e3b35a``).

    Raises:
        KeyError: If there is no icon with that name.
    """
    return f"{_LINE_START}{_SHAPES[name]}</svg>".replace(COLOR, color)


def _render(svg: str, size: int) -> QPixmap:
    """Draw SVG text into a transparent square picture of ``size`` pixels."""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(image)


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """A Qt icon for line icon ``name`` in ``color``, sharp at ``size`` pixels and double."""
    svg = icon_svg(name, color)
    result = QIcon()
    # Also draw a bigger copy, so the icon stays sharp on high-resolution screens.
    result.addPixmap(_render(svg, size * 2))
    result.addPixmap(_render(svg, size))
    return result


def app_icon() -> QIcon:
    """The app's icon (window, tray and shortcuts)."""
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(_render(APP_ICON_SVG, size))
    return result


def save_app_ico(target: Path) -> bool:
    """Write the app icon as a Windows ``.ico`` file (shortcuts need that format).

    Returns True when the file was written.
    """
    return _render(APP_ICON_SVG, 256).save(str(target), "ICO")
