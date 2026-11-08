"""Tests for the tool loop (``engine/agent.py``), using FakeProvider and small fake tools."""

from collections.abc import Mapping

import pytest

from wow_coach.ai.base import (
    AIError,
    Answer,
    ConversationItem,
    FakeProvider,
    Message,
    NotSignedIn,
    Replay,
    ToolCall,
    ToolResult,
    ToolSpec,
    WebSearch,
    WebSearchUnavailable,
)
from wow_coach.engine.agent import MAX_ROUNDS, Activity, AgentResult, run_agent
from wow_coach.engine.conversation import Lookup
from wow_coach.engine.sources import SourceLink
from wow_coach.tools.base import CoachTool, ToolKind, ToolSource

QUESTION = [Message("system", "rules"), Message("user", "what next?")]
WIKI = "https://warcraft.wiki.gg/wiki/Abigail_Shiel"


def make_tool(
    name: str,
    output: str,
    *,
    kind: ToolKind = "read",
    sources: tuple[ToolSource, ...] = (),
    only_listed: bool = False,
) -> CoachTool:
    return CoachTool(
        spec=ToolSpec(name, "does a thing", {"type": "object", "properties": {}, "required": []}),
        kind=kind,
        handler=lambda _args: output,
        describer=lambda _args: f"Used {name}",
        sourcer=(lambda _text: sources) if sources else None,
        only_listed=only_listed,
    )


def ask_for(*calls: ToolCall, searches: tuple[WebSearch, ...] = ()) -> Answer:
    replay = tuple(Replay({"type": "function_call", "call_id": c.call_id}) for c in calls)
    return Answer("", "m", tool_calls=calls, web_searches=searches, replay=replay)


def final(text: str = "done", *, searches: tuple[WebSearch, ...] = ()) -> Answer:
    return Answer(text, "m", web_searches=searches)


def run(
    provider: FakeProvider,
    tools: list[CoachTool],
    *,
    web_search: bool = True,
    seen: list[Activity] | None = None,
) -> AgentResult:
    def on_activity(activity: Activity) -> None:
        if seen is not None:
            seen.append(activity)

    return run_agent(
        provider,
        QUESTION,
        model="m",
        max_output_tokens=100,
        json_schema={"type": "object"},
        tools=tools,
        web_search=web_search,
        on_activity=on_activity,
    )


def kinds_of(items: tuple[ConversationItem, ...]) -> list[str]:
    return [type(item).__name__ for item in items]


def test_a_two_round_loop_runs_the_tool_and_returns_the_final_answer() -> None:
    provider = FakeProvider([ask_for(ToolCall("c1", "status")), final("hello")])
    seen: list[Activity] = []
    result = run(provider, [make_tool("status", "LEVEL 7")], seen=seen)
    assert result.answer.text == "hello"
    assert len(provider.asks) == 2
    first, second = provider.asks
    assert [spec.name for spec in first.tools] == ["status"] and first.web_search
    assert first.json_schema == {"type": "object"}
    # Round two holds the question, the provider's replay item and the tool's result.
    assert kinds_of(second.messages) == ["Message", "Message", "Replay", "ToolResult"]
    assert second.messages[-1] == ToolResult("c1", "LEVEL 7")
    assert seen == [Activity("Used status", "read")]
    assert result.lookups == (Lookup("read", "Used status"),)


def test_an_unknown_tool_and_bad_arguments_become_sentences_for_the_ai() -> None:
    provider = FakeProvider(
        [
            ask_for(
                ToolCall("c1", "nope"),
                ToolCall("c2", "status", arguments_error="The arguments were not valid JSON."),
            ),
            final(),
        ]
    )
    result = run(provider, [make_tool("status", "x")])
    results = [m for m in provider.asks[1].messages if isinstance(m, ToolResult)]
    assert "no tool called 'nope'" in results[0].output and "status" in results[0].output
    assert "not valid JSON" in results[1].output
    assert result.lookups == ()  # nothing was looked up


def test_the_round_cap_forces_a_final_answer_without_tools() -> None:
    calls = [ask_for(ToolCall(f"c{n}", "status")) for n in range(MAX_ROUNDS)]
    provider = FakeProvider([*calls, final("forced")])
    result = run(provider, [make_tool("status", "x")])
    assert result.answer.text == "forced"
    assert len(provider.asks) == MAX_ROUNDS + 1
    assert provider.asks[-1].tools == () and provider.asks[-1].web_search is False
    assert all(ask.tools for ask in provider.asks[:-1])


def test_web_search_unavailable_retries_the_round_and_stays_off() -> None:
    provider = FakeProvider(
        [
            WebSearchUnavailable("no search"),
            ask_for(ToolCall("c1", "status")),
            final("ok"),
        ]
    )
    result = run(provider, [make_tool("status", "x")])
    assert result.answer.text == "ok"
    assert [ask.web_search for ask in provider.asks] == [True, False, False]
    assert all(ask.tools for ask in provider.asks)  # the tools stayed on


def test_another_failure_with_tools_falls_back_to_the_old_way_once() -> None:
    provider = FakeProvider([AIError("boom"), final("plain")])
    result = run(provider, [make_tool("status", "x")])
    assert result.answer.text == "plain"
    assert provider.asks[1].tools == () and provider.asks[1].web_search is False
    assert provider.asks[1].messages == tuple(QUESTION)  # the question, nothing else
    assert result.sources == () and result.lookups == ()


def test_the_fallback_only_happens_once() -> None:
    provider = FakeProvider([AIError("one"), AIError("two")])
    with pytest.raises(AIError, match="two"):
        run(provider, [make_tool("status", "x")])


def test_a_failure_in_a_later_round_also_falls_back_to_the_old_way() -> None:
    provider = FakeProvider([ask_for(ToolCall("c1", "status")), AIError("boom"), final("plain")])
    result = run(provider, [make_tool("status", "x")])
    assert result.answer.text == "plain"
    assert provider.asks[2].messages == tuple(QUESTION)
    assert result.lookups == ()


def test_not_signed_in_is_not_retried() -> None:
    provider = FakeProvider([NotSignedIn("sign in"), final("never")])
    with pytest.raises(NotSignedIn):
        run(provider, [make_tool("status", "x")])
    assert len(provider.asks) == 1


def test_with_nothing_turned_on_it_is_a_single_plain_ask() -> None:
    provider = FakeProvider([final("plain")])
    result = run(provider, [], web_search=False)
    assert result.answer.text == "plain" and len(provider.asks) == 1
    assert provider.asks[0].tools == () and provider.asks[0].web_search is False


def test_only_web_search_without_tools_still_works() -> None:
    search = WebSearch(("bears",), ("https://example.com/bears",))
    provider = FakeProvider([final("ok", searches=(search,))])
    result = run(provider, [], web_search=True)
    assert provider.asks[0].web_search is True and provider.asks[0].tools == ()
    assert result.sources == (SourceLink("", "https://example.com/bears"),)


def test_web_searches_are_reported_and_their_citations_are_sources() -> None:
    search = WebSearch(("forever mage talents",), ("https://a.example/x", "javascript:alert(1)"))
    provider = FakeProvider([final("ok", searches=(search,))])
    seen: list[Activity] = []
    result = run(provider, [make_tool("status", "x")], seen=seen)
    assert seen == [Activity('Searched the web for "forever mage talents"', "web")]
    assert result.lookups == (Lookup("web", 'Searched the web for "forever mage talents"'),)
    assert result.sources == (SourceLink("", "https://a.example/x"),)


def test_sources_come_from_pages_read_and_citations_never_from_the_models_words() -> None:
    page = make_tool("read_page", "text", kind="web", sources=(ToolSource("Abigail Shiel", WIKI),))
    listing = make_tool(
        "find",
        "list",
        kind="web",
        sources=(ToolSource("Other", "https://warcraft.wiki.gg/wiki/Other"),),
        only_listed=True,
    )
    cited = WebSearch(("q",), ("https://news.example/a",))
    provider = FakeProvider(
        [
            ask_for(ToolCall("c1", "find"), ToolCall("c2", "read_page")),
            final("see https://evil.example/ for more", searches=(cited,)),
        ]
    )
    result = run(provider, [page, listing])
    assert result.sources == (
        SourceLink("Abigail Shiel", WIKI),
        SourceLink("", "https://news.example/a"),
    )  # the listed page is left out because a page was read; the model's own link is ignored


def test_a_page_that_was_only_listed_is_a_source_when_nothing_was_read() -> None:
    listing = make_tool(
        "find", "list", kind="web", sources=(ToolSource("Quest", WIKI),), only_listed=True
    )
    provider = FakeProvider([ask_for(ToolCall("c1", "find")), final()])
    assert run(provider, [listing]).sources == (SourceLink("Quest", WIKI),)


def test_unsafe_tool_sources_are_dropped() -> None:
    page = make_tool(
        "read_page",
        "t",
        kind="web",
        sources=(ToolSource("x", "file:///etc/passwd"), ToolSource("y", "javascript:1")),
    )
    provider = FakeProvider([ask_for(ToolCall("c1", "read_page")), final()])
    assert run(provider, [page]).sources == ()


def test_activity_is_reported_before_the_tool_runs_in_order() -> None:
    order: list[str] = []

    def handler(_args: dict[str, object]) -> str:
        order.append("ran")
        return "x"

    tool = CoachTool(
        spec=ToolSpec("status", "d", {"type": "object", "properties": {}, "required": []}),
        kind="read",
        handler=handler,
        describer=lambda _args: "Read it",
    )
    provider = FakeProvider([ask_for(ToolCall("c1", "status")), final()])
    run_agent(
        provider,
        QUESTION,
        model="m",
        max_output_tokens=100,
        json_schema=None,
        tools=[tool],
        web_search=False,
        on_activity=lambda activity: order.append(activity.text),
    )
    assert order == ["Read it", "ran"]


def test_tool_arguments_reach_the_describer() -> None:
    seen_args: list[Mapping[str, object]] = []

    def describe(args: Mapping[str, object]) -> str:
        seen_args.append(args)
        return "Looked"

    tool = CoachTool(
        spec=ToolSpec("find", "d", {"type": "object", "properties": {}, "required": []}),
        kind="web",
        handler=lambda _args: "x",
        describer=describe,
    )
    provider = FakeProvider([ask_for(ToolCall("c1", "find", {})), final()])
    run(provider, [tool])
    assert seen_args == [{}]
