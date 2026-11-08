"""What the coach window needs from the rest of wow-coach (0.9.0+).

The window (``app/server.py`` and its page) is built against these small interfaces, so
it can be tested with fakes and never needs the network, the game or the keychain.
The real objects are ``engine.Coach``, ``ai.chatgpt_signin.ChatGPTSignIn`` and
``alerts.SystemAlerts``.
"""

from collections.abc import Callable
from typing import Protocol


class SignIn(Protocol):
    """The ChatGPT sign-in, as the window sees it."""

    @property
    def is_signed_in(self) -> bool:
        """True when a saved sign-in exists."""
        ...

    def sign_in(self, on_url: Callable[[str], None] | None = None) -> object:
        """Open OpenAI's page in the browser and wait for the player to approve."""
        ...

    def sign_out(self) -> bool:
        """Revoke and forget the sign-in; False if OpenAI did not confirm the revoke."""
        ...


class Alerts(Protocol):
    """Telling the player outside the game that an answer is ready."""

    def notify(self, title: str, body: str) -> bool:
        """Show a desktop notification; False when this computer can't."""
        ...

    def speak(self, text: str) -> bool:
        """Read the text aloud; False when this computer can't."""
        ...
