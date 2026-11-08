"""The contract every AI connection follows, plus a fake one for tests.

wow-coach talks to an AI through one small interface, ``Provider``, so the coach engine
never needs to know which AI it is. For now there is one real provider: the player's
ChatGPT plan through OpenAI's official "Sign in with ChatGPT" (``ai/chatgpt_plan.py``).
Tests use ``FakeProvider`` and never touch the network.

Tools
-----
An AI can also ask to use *tools* (look something up, read the player's notes). The types
for that are neutral: they do not belong to any one AI company, so ChatGPT, Gemini or
Claude can all plug in.

* ``ToolSpec``: what a tool is called, what it does and which arguments it takes.
* ``ToolCall``: the AI asking to use a tool.
* ``ToolResult``: what the tool answered.
* ``Replay``: an item the provider needs to see again in the next request. The caller keeps
  it and sends it back untouched, and never looks inside.
* ``WebSearch``: what the provider's own built-in web search looked up (for showing people).

The loop a caller runs (the coach engine does this)::

    messages = [...]                                  # Message items, oldest first
    while True:
        answer = provider.ask(messages, ..., tools=specs, web_search=True)
        if not answer.tool_calls:
            return answer.text                        # the final reply
        messages.extend(answer.replay)                # 1. keep what the provider needs back
        for call in answer.tool_calls:                # 2. run every tool it asked for
            messages.append(ToolResult(call.call_id, run_tool(call)))
        # 3. ask again; stop after a few rounds so a confused AI cannot loop forever

Every ``ToolResult`` must answer one ``ToolCall`` of the last answer (same ``call_id``).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from wow_coach.errors import WowCoachError

type Role = Literal["system", "user", "assistant"]


class AIError(WowCoachError):
    """Something went wrong talking to the AI. The message is a plain sentence for the player."""


class WebSearchUnavailable(AIError):  # noqa: N818
    """The provider refused the built-in web search. The caller can ask again without it."""


class NotSignedIn(AIError):  # noqa: N818  (reads better than NotSignedInError)
    """The player has not signed in (or the sign-in expired and could not be renewed)."""


class PlanLimitReached(AIError):  # noqa: N818
    """The ChatGPT plan's usage limit was reached."""

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
class ToolSpec:
    """A tool the AI may use.

    ``parameters`` is a JSON schema of type "object". Each property may carry
    "description", "minimum", "maximum" and "maxLength"; a property that is not listed in
    "required" is optional.
    """

    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """The AI asking to use a tool.

    When the AI's arguments are not valid JSON (or not an object), ``arguments`` is empty
    and ``arguments_error`` says why, so the caller can tell the AI instead of crashing.
    """

    call_id: str
    name: str
    arguments: dict[str, object] = field(default_factory=dict)
    arguments_error: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool answered, for the ``ToolCall`` with the same ``call_id``."""

    call_id: str
    output: str


@dataclass(frozen=True, slots=True)
class WebSearch:
    """What the provider's built-in web search did: the queries it ran and the pages it cited."""

    queries: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Replay:
    """An item the provider must see again in the next request (for example its reasoning).

    The caller never looks inside ``item``: it only keeps the items in order and sends them
    back (see the loop at the top of this file).
    """

    item: dict[str, object]


type ConversationItem = Message | ToolCall | ToolResult | Replay


@dataclass(frozen=True, slots=True)
class Answer:
    """The AI's reply.

    When ``tool_calls`` is not empty, the AI wants tools run before it can finish; ``text``
    may then be empty or partial. ``replay`` holds the items to send back with the results.
    """

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: tuple[ToolCall, ...] = ()
    web_searches: tuple[WebSearch, ...] = ()
    replay: tuple[Replay, ...] = ()


class Provider(Protocol):
    """An AI connection."""

    @property
    def name(self) -> str:
        """Who answers, for the player, e.g. "ChatGPT (your plan)"."""
        ...

    def ask(
        self,
        messages: Sequence[ConversationItem],
        *,
        model: str,
        max_output_tokens: int,
        json_schema: dict[str, object] | None = None,
        tools: Sequence[ToolSpec] = (),
        web_search: bool = False,
    ) -> Answer:
        """Send the conversation and return the reply.

        Args:
            messages: The conversation so far, oldest first. Besides ``Message`` it may hold
                ``Replay`` and ``ToolResult`` items from earlier rounds (see the loop in the
                module docstring) and ``ToolCall`` items.
            model: The model to use (one the provider lists).
            max_output_tokens: An upper limit for the reply's length.
            json_schema: When given, ask for a JSON reply that follows this schema (the
                final message; tool calls come before it).
            tools: Tools the AI may ask to use.
            web_search: Let the AI use the provider's own built-in web search.

        Raises:
            NotSignedIn: Not signed in, or the sign-in can't be renewed.
            PlanLimitReached: The plan's limit was reached.
            WebSearchUnavailable: ``web_search`` was refused; ask again without it.
            AIError: Any other problem, with a plain explanation.
        """
        ...

    def check(self) -> str:
        """Return "ok" if the provider can answer now, else a plain sentence saying why not."""
        ...


@dataclass(frozen=True, slots=True)
class FakeRequest:
    """Everything one ``FakeProvider.ask`` call was given."""

    messages: tuple[ConversationItem, ...]
    model: str
    tools: tuple[ToolSpec, ...]
    web_search: bool
    json_schema: dict[str, object] | None


@dataclass
class FakeProvider:
    """A provider for tests: returns the scripted replies in order and records every request.

    Each reply is a text, a ready-made ``Answer`` (for example one with ``tool_calls``), or
    an ``AIError`` to raise (for example ``WebSearchUnavailable``).
    """

    replies: list[str | Answer | AIError]
    name: str = "Fake AI"
    requests: list[tuple[tuple[ConversationItem, ...], str]] = field(default_factory=list)
    asks: list[FakeRequest] = field(default_factory=list)

    def ask(
        self,
        messages: Sequence[ConversationItem],
        *,
        model: str,
        max_output_tokens: int,
        json_schema: dict[str, object] | None = None,
        tools: Sequence[ToolSpec] = (),
        web_search: bool = False,
    ) -> Answer:
        """Return the next reply; raise ``AIError`` when none are left."""
        del max_output_tokens  # a fake ignores it
        self.requests.append((tuple(messages), model))
        self.asks.append(FakeRequest(tuple(messages), model, tuple(tools), web_search, json_schema))
        if not self.replies:
            raise AIError("The fake AI has no replies left.")
        reply = self.replies.pop(0)
        if isinstance(reply, AIError):
            raise reply
        if isinstance(reply, Answer):
            return reply
        return Answer(text=reply, model=model, usage=Usage(10, 20))

    def check(self) -> str:
        """Always ready."""
        return "ok"
