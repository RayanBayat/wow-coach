"""The contract every AI connection follows, plus a fake one for tests.

wow-coach talks to an AI through one small interface, ``Provider``, so the coach engine
never needs to know which AI it is. For now there is one real provider: the player's
ChatGPT plan through OpenAI's official "Sign in with ChatGPT" (``ai/chatgpt_plan.py``).
Tests use ``FakeProvider`` and never touch the network.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from wow_coach.errors import WowCoachError

type Role = Literal["system", "user", "assistant"]


class AIError(WowCoachError):
    """Something went wrong talking to the AI. The message is a plain sentence for the player."""


class NotSignedIn(AIError):  # noqa: N818  (reads better than NotSignedInError)
    """The player has not signed in (or the sign-in expired and could not be renewed)."""


class PlanLimitReached(AIError):  # noqa: N818
    """The ChatGPT plan's usage limit (or the player's own cap) was reached."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class Message:
    """One message of a conversation."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    """How much of the plan one answer used, as the AI reported it (0 when unknown)."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Answer:
    """The AI's reply."""

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)


class Provider(Protocol):
    """An AI connection."""

    @property
    def name(self) -> str:
        """Who answers, for the player, e.g. "ChatGPT (your plan)"."""
        ...

    def ask(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_output_tokens: int,
        json_schema: dict[str, object] | None = None,
    ) -> Answer:
        """Send the conversation and return the reply.

        Args:
            messages: The conversation so far, oldest first.
            model: The model to use (one the provider lists).
            max_output_tokens: An upper limit for the reply's length.
            json_schema: When given, ask for a JSON reply that follows this schema.

        Raises:
            NotSignedIn: Not signed in, or the sign-in can't be renewed.
            PlanLimitReached: The plan's limit or the player's cap was reached.
            AIError: Any other problem, with a plain explanation.
        """
        ...

    def check(self) -> str:
        """Return "ok" if the provider can answer now, else a plain sentence saying why not."""
        ...


@dataclass
class FakeProvider:
    """A provider for tests: returns the given replies in order and records every request."""

    replies: list[str]
    name: str = "Fake AI"
    requests: list[tuple[tuple[Message, ...], str]] = field(default_factory=list)

    def ask(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_output_tokens: int,
        json_schema: dict[str, object] | None = None,
    ) -> Answer:
        """Return the next reply; raise ``AIError`` when none are left."""
        del max_output_tokens, json_schema  # a fake ignores them
        self.requests.append((tuple(messages), model))
        if not self.replies:
            raise AIError("The fake AI has no replies left.")
        return Answer(text=self.replies.pop(0), model=model, usage=Usage(10, 20))

    def check(self) -> str:
        """Always ready."""
        return "ok"
