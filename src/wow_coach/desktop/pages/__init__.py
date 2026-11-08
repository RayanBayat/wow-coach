"""The pages of the desktop app, in sidebar order."""

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.pages.chatgpt import ChatGPTPage
from wow_coach.desktop.pages.coach import CoachPage
from wow_coach.desktop.pages.notebook import NotebookPage
from wow_coach.desktop.pages.privacy import PrivacyPage
from wow_coach.desktop.pages.settings import SettingsPage
from wow_coach.desktop.pages.setup import SetupPage


def build_pages(bridge: CoreBridge) -> list[Page]:
    """Create every page, in the order the sidebar lists them."""
    return [
        CoachPage(bridge),
        NotebookPage(bridge),
        SettingsPage(bridge),
        ChatGPTPage(bridge),
        SetupPage(bridge),
        PrivacyPage(bridge),
    ]
