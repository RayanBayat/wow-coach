"""The tool loop: ask the AI, run the tools it asks for, ask again until it has an answer.

This is the loop documented at the top of ``ai/base.py``. It never looks at which AI answers.

* At most ``MAX_ROUNDS`` rounds of tool calls. After that one last ask without tools makes
  sure there is always an answer.
* If the provider refuses its web search (``WebSearchUnavailable``), the same round is asked
  again without it and the search stays off for the rest of the question.
* If anything else goes wrong while tools are on, the whole question is asked once more the
  old way (no tools, no search), so the player still gets an answer. Problems that asking
  again cannot fix (not signed in, plan limit) are raised at once.
* Progress is reported through ``on_activity`` ("Searched the Warcraft Wiki for ...").
* The sources of the answer are collected here from what our own code saw (the web search's
  citations and the pages the tools read), never from the AI's words. See ``sources.py``.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from wow_coach.ai.base import (
    AIError,
    Answer,
    ConversationItem,
    NotSignedIn,
    PlanLimitReached,
    Provider,
    ToolCall,
    ToolResult,
    WebSearch,
    WebSearchUnavailable,
)
from wow_coach.engine.conversation import Lookup
from wow_coach.engine.sources import SourceCollector, SourceLink
from wow_coach.tools.base import CoachTool

MAX_ROUNDS: Final = 8
_log = logging.getLogger(__name__)
# Errors that asking again without tools cannot fix.
_NOT_RETRIED: Final = (NotSignedIn, PlanLimitReached)


@dataclass(frozen=True, slots=True)
class Activity:
    """One thing the coach is doing now, as a plain sentence. ``kind``: read, write or web."""

    text: str
    kind: str


type ActivityCallback = Callable[[Activity], None]


@dataclass(frozen=True, slots=True)
class AgentResult:
    """The final reply of the AI, with the sources it came from and what was looked up."""

    answer: Answer
    sources: tuple[SourceLink, ...] = ()
    lookups: tuple[Lookup, ...] = ()


class _Run:
    """The state of one question while its tools run."""

    def __init__(self, tools: Sequence[CoachTool], on_activity: ActivityCallback | None) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.sources = SourceCollector()
        self.lookups: list[Lookup] = []
        self._on_activity = on_activity

    def report(self, text: str, kind: str) -> None:
        """Remember a lookup and tell the listener. A failing listener never stops the answer."""
        self.lookups.append(Lookup(kind, text))
        if self._on_activity is None:
            return
        try:
            self._on_activity(Activity(text, kind))
        except Exception:
            _log.exception("An activity listener failed")

    def note_web_searches(self, searches: Sequence[WebSearch]) -> None:
        """Report what the provider's own web search did and keep the pages it cited."""
        for search in searches:
            for query in search.queries:
                self.report(f'Searched the web for "{" ".join(query.split())}"', "web")
            for url in search.sources:
                self.sources.add_cited(url)

    def run_tool(self, call: ToolCall) -> ToolResult:
        """Run one tool call. A mistake of the AI becomes a sentence it can read and fix."""
        tool = self.tools.get(call.name)
        if tool is None:
            known = ", ".join(sorted(self.tools)) or "none"
            return ToolResult(
                call.call_id, f"There is no tool called '{call.name}'. The tools you have: {known}."
            )
        if call.arguments_error:
            return ToolResult(
                call.call_id,
                f"Could not read the arguments for {call.name}: {call.arguments_error} "
                "Call it again with a valid JSON object.",
            )
        self.report(tool.describe(call.arguments), tool.kind)
        run = tool.run_with_sources(call.arguments)
        for source in run.sources:
            if run.only_listed:
                self.sources.add_listed(source.title, source.url)
            else:
                self.sources.add_read(source.title, source.url)
        return ToolResult(call.call_id, run.output)

    def result(self, answer: Answer) -> AgentResult:
        return AgentResult(answer, self.sources.links(), tuple(self.lookups))


def run_agent(
    provider: Provider,
    messages: Sequence[ConversationItem],
    *,
    model: str,
    max_output_tokens: int,
    json_schema: dict[str, object] | None,
    tools: Sequence[CoachTool],
    web_search: bool,
    on_activity: ActivityCallback | None = None,
) -> AgentResult:
    """Answer the conversation, using ``tools`` and the provider's web search when allowed.

    Raises the provider's ``AIError`` when even the plain fallback fails.
    """

    def ask_plain() -> AgentResult:
        reply = provider.ask(
            messages, model=model, max_output_tokens=max_output_tokens, json_schema=json_schema
        )
        return AgentResult(reply)

    if not tools and not web_search:
        return ask_plain()
    try:
        return _loop(
            provider,
            messages,
            model=model,
            max_output_tokens=max_output_tokens,
            json_schema=json_schema,
            run=_Run(tools, on_activity),
            web_search=web_search,
        )
    except _NOT_RETRIED:
        raise
    except AIError:
        _log.warning("Answering with tools failed; asking again without them", exc_info=True)
        return ask_plain()


def _loop(
    provider: Provider,
    messages: Sequence[ConversationItem],
    *,
    model: str,
    max_output_tokens: int,
    json_schema: dict[str, object] | None,
    run: _Run,
    web_search: bool,
) -> AgentResult:
    conversation: list[ConversationItem] = list(messages)
    specs = [tool.spec for tool in run.tools.values()]
    searching = web_search

    def ask(*, with_tools: bool) -> Answer:
        nonlocal searching
        use_search = searching and with_tools
        try:
            return provider.ask(
                conversation,
                model=model,
                max_output_tokens=max_output_tokens,
                json_schema=json_schema,
                tools=specs if with_tools else (),
                web_search=use_search,
            )
        except WebSearchUnavailable:
            if not use_search:
                raise
            searching = False  # stays off for the rest of this question
            return provider.ask(
                conversation,
                model=model,
                max_output_tokens=max_output_tokens,
                json_schema=json_schema,
                tools=specs if with_tools else (),
                web_search=False,
            )

    for _round in range(MAX_ROUNDS):
        answer = ask(with_tools=True)
        run.note_web_searches(answer.web_searches)
        if not answer.tool_calls:
            return run.result(answer)
        conversation.extend(answer.replay)
        conversation.extend(run.run_tool(call) for call in answer.tool_calls)
    # Too many rounds: one last ask without tools, so the player always gets an answer.
    answer = ask(with_tools=False)
    run.note_web_searches(answer.web_searches)
    return run.result(answer)
