"""The quick-action chips under the Coach page's header, defined as plain data.

Adding a chip means adding one entry to ``QUICK_ACTIONS``. Each chip either sends its
question to the coach straight away, or (``fills_composer``) only puts it in the text box so
the player can finish it, with the cursor in the gap between two spaces.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class QuickAction:
    """One chip."""

    label: str  # the words on the chip
    question: str  # what is sent to the coach (or put in the text box)
    tooltip: str  # one sentence: what clicking does
    fills_composer: bool = False  # True: do not send, let the player finish the sentence

    @property
    def cursor_position(self) -> int:
        """Where the cursor goes when the question fills the text box: in the double space."""
        gap = self.question.find("  ")
        return len(self.question) if gap < 0 else gap + 1


QUICK_ACTIONS: Final = (
    QuickAction(
        "What next?",
        "What should I do next with my character right now?",
        "Ask your coach what to do next, based on your character right now.",
    ),
    QuickAction(
        "Check my gear",
        "Look at my gear. What should I upgrade, repair or replace first?",
        "Your coach looks at what you wear and what is in your bags.",
    ),
    QuickAction(
        "Spells to train",
        "Which new spells or abilities can I learn at my level, and where do I go to train them?",
        "Find out which spells you can learn now and where to get them.",
    ),
    QuickAction(
        "Plan my session",
        "Plan my next hour of play. What should I do, in what order?",
        "Get a short plan for the next hour of play.",
    ),
    QuickAction(
        "Why did I die?",
        "Why did I die just now, and how can I avoid it next time?",
        "Your coach looks at what happened and how to stay alive.",
    ),
    QuickAction(
        "Make gold",
        "How can I make gold at my level right now?",
        "Ideas for earning gold that fit your level and professions.",
    ),
    QuickAction(
        "Explain a word",
        "What does  mean?",
        "Type a game word you do not know and your coach explains it.",
        fills_composer=True,
    ),
)

# The three big cards of the welcome screen (labels of the actions above).
SUGGESTION_LABELS: Final = ("What next?", "Check my gear", "Plan my session")


def suggestions() -> list[QuickAction]:
    """The actions shown as big cards when the chat is empty."""
    return [action for action in QUICK_ACTIONS if action.label in SUGGESTION_LABELS]
