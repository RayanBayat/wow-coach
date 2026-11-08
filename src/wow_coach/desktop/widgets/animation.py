"""Tiny animations shared by the Coach page: fading a widget in or out, gliding a scrollbar.

Every animation is owned by the widget it moves, so nothing is cleaned up by hand and an
animation can never outlive its widget.
"""

from collections.abc import Callable

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QScrollBar, QWidget

from wow_coach.desktop.theme import FADE_MS, SCROLL_MS


def remove_effect(widget: QWidget) -> None:
    """Take off a widget's graphics effect (PySide's stubs forget that None is allowed)."""
    widget.setGraphicsEffect(None)  # type: ignore[arg-type]


def fade(
    widget: QWidget,
    *,
    start: float,
    end: float,
    on_done: Callable[[], None] | None = None,
    duration: int = FADE_MS,
) -> QPropertyAnimation:
    """Fade ``widget`` from ``start`` to ``end`` opacity (0 = invisible, 1 = solid).

    The opacity effect is removed again when the widget is solid, because text drawn through
    an effect is a little blurry.
    """
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(start)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def finished() -> None:
        if end >= 1.0:
            remove_effect(widget)
        if on_done is not None:
            on_done()

    animation.finished.connect(finished)
    animation.start()
    return animation


def fade_in(widget: QWidget) -> QPropertyAnimation:
    """Fade a new widget in."""
    return fade(widget, start=0.0, end=1.0)


def glide(bar: QScrollBar, target: int) -> QPropertyAnimation:
    """Scroll smoothly to ``target`` instead of jumping.

    The animation deletes itself when it stops, so finished glides do not pile up.
    """
    animation = QPropertyAnimation(bar, b"value", bar)
    animation.setDuration(SCROLL_MS)
    animation.setStartValue(bar.value())
    animation.setEndValue(target)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation
