"""The Privacy page: what wow-coach keeps on this computer, what it sends, and when.

The words follow ``docs/privacy.md`` (the full notice). Nothing here makes a promise that
notice does not make.
"""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.forms import (
    PRIVACY_URL,
    USAGE_URL,
    Card,
    link_button,
    make_label,
    page_header,
    scrollable,
)
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.theme import SPACE, SPACE_SMALL

STAYS_HERE = (
    "Your settings, your usage counts (only numbers, never your questions) and the "
    "coach's answers in the game's addon folder.",
    "Your ChatGPT sign-in, in your computer's password store. It is never kept in a plain file.",
    "WoW Coach has no server and no tracking. Its author receives none of your data.",
)
SENT_TO_CHATGPT = (
    "Your character's data from the game (the report of its latest save).",
    "Your question.",
    "The last few messages of the conversation.",
    "The coach's notes: your own notes and the character journal. You can turn this off in "
    "Settings.",
)
CLAUDE_CHATS = (
    "Your chats with your Claude coach are copied from this computer into the coach's chat "
    "history. They are sent to ChatGPT as part of the recent conversation, unless you turn "
    'off "Use my Claude coach chats" in Settings.'
)
TOOLS_SEND = (
    "Warcraft Wiki searches go to the Warcraft Wiki (warcraft.wiki.gg). It sees the words "
    "the coach looks up.",
    "Web searches are run by OpenAI as part of your ChatGPT plan. Only the search words and "
    "what the search finds are involved.",
    "What the coach reads from your character data and notes is sent to ChatGPT with the "
    "answer. Sections of your notes about your computer are never read by the coach.",
    "When the coach saves your notes, they stay on this computer. The last 20 versions are "
    "kept in a .history folder next to them, so a mistake can be undone.",
)
YOUR_CHOICES = (
    "Don't sign in: then nothing is sent to OpenAI at all.",
    "Sign out any time on the ChatGPT page. You can also disconnect WoW Coach in your "
    "ChatGPT settings.",
    "Other players' names are hidden from the AI unless you turn that on in Settings.",
    'Turn off "Send my coach notes" in Settings to keep your notes on this computer.',
    'Turn off the "Coach tools" in Settings to stop lookups, web searches and note saving.',
)


def bullet_list(card: Card, items: tuple[str, ...]) -> None:
    """Add ``items`` to ``card`` as a simple list with round bullets."""
    for item in items:
        card.body.addWidget(make_label(f"•  {item}"))


class PrivacyPage(Page):
    """What wow-coach sends, and where."""

    name = "privacy"
    title = "Privacy"

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(bridge, parent)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE)
        column.addLayout(
            page_header(
                "Privacy",
                "Your game stays on your computer. Here is what is shared, with whom, and when.",
            )
        )

        stays = Card("What stays on this computer")
        bullet_list(stays, STAYS_HERE)
        column.addWidget(stays)

        sent = Card(
            "What is sent to ChatGPT, and when",
            "Only when you ask the coach, and only after you have signed in with ChatGPT. "
            "It goes to OpenAI and uses your ChatGPT plan:",
        )
        bullet_list(sent, SENT_TO_CHATGPT)
        sent.body.addWidget(
            make_label(
                "WoW Coach asks OpenAI not to store these requests. Other AI apps you connect "
                "to wow-coach, such as Claude Code, receive what they read. That is between "
                "you and their company.",
                "small",
            )
        )
        sent.body.addWidget(make_label(CLAUDE_CHATS, "small"))
        column.addWidget(sent)

        tools = Card(
            "What the coach's tools send, and where",
            "While answering, the coach can look things up. You can see each lookup under "
            "the answer, and turn the tools off in Settings.",
        )
        bullet_list(tools, TOOLS_SEND)
        column.addWidget(tools)

        choices = Card("You are in charge")
        bullet_list(choices, YOUR_CHOICES)
        column.addWidget(choices)

        links = QHBoxLayout()
        links.setSpacing(SPACE_SMALL)
        links.addWidget(
            link_button(
                "Read the full privacy notice",
                PRIVACY_URL,
                "Open the complete privacy notice on GitHub.",
                "secondary",
            )
        )
        links.addWidget(
            link_button(
                "Manage usage",
                USAGE_URL,
                "Open your ChatGPT usage settings in the browser.",
            )
        )
        links.addStretch(1)
        column.addLayout(links)
        column.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(content))
