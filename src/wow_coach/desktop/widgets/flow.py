"""A layout that puts widgets side by side and wraps to a new row when the window is narrow.

Qt has no such layout built in. It is used for the quick-action chips, so they never get cut
off in a small window.
"""

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Left to right, top to bottom, like words in a paragraph."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt's method name
        """Add a layout item (Qt calls this from ``addWidget``)."""
        self._items.append(item)

    def count(self) -> int:
        """How many items there are."""
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt's method name
        """The item at ``index``, or None."""
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt's method name
        """Remove and return the item at ``index``."""
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt's method name
        """The layout does not ask for extra space."""
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt's method name
        """The height depends on the width (more rows when narrow)."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt's method name
        """The height needed at this width."""
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt's method name
        """Place the items inside ``rect``."""
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's method name
        """The size of the biggest item plus margins."""
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt's method name
        """Room for one item, plus the margins."""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins: QMargins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        """Lay the items out; return the height used. ``apply=False`` only measures."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        gap = self.spacing()
        for item in self._items:
            size = item.sizeHint()
            if x + size.width() > area.right() + 1 and row_height > 0:
                x = area.x()
                y += row_height + gap
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + gap
            row_height = max(row_height, size.height())
        return y + row_height - rect.y() + margins.bottom()
