"""Tests for the neutral AI types and the fake provider."""

import pytest

from wow_coach.ai.base import (
    AIError,
    Answer,
    FakeProvider,
    Message,
    Provider,
    Replay,
    ToolCall,
    ToolResult,
    ToolSpec,
    WebSearch,
    WebSearchUnavailable,
)

SPEC = ToolSpec("lookup", "Looks something up.", {"type": "object", "properties": {}})


def test_new_answer_fields_default_to_empty() -> None:
    answer = Answer(text="hi", model="m")
    assert answer.tool_calls == () and answer.web_searches == () and answer.replay == ()


def test_a_tool_call_without_arguments_has_none_and_no_error() -> None:
    call = ToolCall("c1", "lookup")
    assert call.arguments == {} and call.arguments_error == ""


def test_web_search_unavailable_is_a_plain_ai_error() -> None:
    assert issubclass(WebSearchUnavailable, AIError)


def test_the_fake_is_still_a_provider_and_still_returns_texts() -> None:
    fake: Provider = FakeProvider(["one", "two"])
    assert fake.ask([Message("user", "q")], model="m", max_output_tokens=5).text == "one"
    assert fake.ask([Message("user", "q")], model="m", max_output_tokens=5).text == "two"


def test_the_fake_returns_scripted_answers_and_records_what_it_was_sent() -> None:
    asking = Answer("", "m", tool_calls=(ToolCall("c1", "lookup", {"q": "x"}),))
    fake = FakeProvider([asking, "done"])
    first = fake.ask(
        [Message("user", "q")], model="m", max_output_tokens=5, tools=[SPEC], web_search=True
    )
    assert first is asking
    second = fake.ask(
        [Message("user", "q"), Replay({"type": "reasoning"}), ToolResult("c1", "result")],
        model="m",
        max_output_tokens=5,
        tools=[SPEC],
    )
    assert second.text == "done"
    assert fake.asks[0].tools == (SPEC,) and fake.asks[0].web_search is True
    assert fake.asks[1].web_search is False
    assert fake.asks[1].messages[-1] == ToolResult("c1", "result")
    assert fake.requests[1][1] == "m"  # the older record still works


def test_the_fake_can_raise_a_scripted_error() -> None:
    fake = FakeProvider([WebSearchUnavailable("no search"), "fine"])
    with pytest.raises(WebSearchUnavailable):
        fake.ask([], model="m", max_output_tokens=1, web_search=True)
    assert fake.ask([], model="m", max_output_tokens=1).text == "fine"


def test_an_empty_script_is_an_error() -> None:
    with pytest.raises(AIError):
        FakeProvider([]).ask([], model="m", max_output_tokens=1)


def test_web_search_keeps_queries_and_sources() -> None:
    search = WebSearch(("a",), ("https://x.test",))
    assert search.queries == ("a",) and search.sources == ("https://x.test",)
