"""The Coach page's own styles (Qt's version of CSS), built from the theme's colors.

The page sets this on itself, so it reaches every bubble and bar inside it, including the ones
added later. It only adds looks for the Coach page's own parts (picked by their object name);
the shared buttons and labels keep the look from ``theme.py``.
"""

from wow_coach.desktop.theme import RADIUS, RADIUS_PILL, RADIUS_SMALL, Colors


def with_alpha(color: str, alpha: float) -> str:
    """A ``#rrggbb`` color as ``rgba(...)`` with some transparency (0 = clear, 1 = solid)."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def chat_style(c: Colors) -> str:
    """The stylesheet for the whole Coach page."""
    return f"""
QFrame#coachBubble, QFrame#typingBubble {{
    background: {c.parchment}; border: 1px solid {c.parchment_edge}; border-radius: {RADIUS}px;
}}
QFrame#coachBubble QLabel {{ color: {c.on_parchment}; }}
QFrame#coachBubble QLabel[role="subtitle"] {{ color: {c.on_parchment}; }}
QFrame#coachBubble QLabel[role="muted"], QFrame#coachBubble QLabel[role="small"] {{
    color: {c.parchment_muted};
}}
QFrame#playerBubble {{
    background: {c.player_bubble}; border: 1px solid {with_alpha(c.info, 0.35)};
    border-radius: {RADIUS}px;
}}
QFrame#playerBubble QLabel {{ color: {c.on_player_bubble}; }}
QFrame#playerBubble QLabel[role="small"] {{ color: {c.on_player_bubble}; }}
QFrame#warningCallout {{
    background: {with_alpha(c.button, 0.12)}; border: none;
    border-left: 3px solid {c.button}; border-radius: {RADIUS_SMALL}px;
}}
QFrame#errorNotice {{
    background: {with_alpha(c.danger, 0.12)}; border: 1px solid {with_alpha(c.danger, 0.5)};
    border-radius: {RADIUS}px;
}}
QFrame#waitingNotice {{
    background: transparent; border: 1px dashed {c.border}; border-radius: {RADIUS}px;
}}
QFrame#problemBanner, QFrame#questionsBar {{
    background: {with_alpha(c.info, 0.12)}; border: 1px solid {with_alpha(c.info, 0.45)};
    border-radius: {RADIUS}px;
}}
QFrame#refreshBanner {{
    background: {with_alpha(c.accent, 0.12)}; border: 1px solid {with_alpha(c.accent, 0.5)};
    border-radius: {RADIUS}px;
}}
QFrame#refreshBanner[state="done"] {{
    background: {with_alpha(c.success, 0.14)}; border: 1px solid {with_alpha(c.success, 0.5)};
}}
QFrame#freshnessPill {{
    background: {c.surface_raised}; border: 1px solid {c.border}; border-radius: {RADIUS_PILL}px;
}}
QLabel[dot] {{ border-radius: 4px; background: {c.muted}; }}
QLabel[dot="success"] {{ background: {c.success}; }}
QLabel[dot="warning"] {{ background: {c.warning}; }}
QLabel[dot="muted"] {{ background: {c.muted}; }}
QFrame#composer {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS}px;
}}
QFrame#composer[focused="true"] {{ border-color: {c.trim}; }}
QPlainTextEdit#composerEdit {{
    background: transparent; border: none; padding: 4px 6px;
}}
QFrame#suggestionCard {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: {RADIUS}px;
}}
QFrame#suggestionCard:hover, QFrame#suggestionCard:focus {{ border-color: {c.accent}; }}
QFrame#suggestionCard[disabled="true"] {{ border-color: {c.border}; }}
"""
