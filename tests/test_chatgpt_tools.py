"""Tests for tools and web search in the ChatGPT plan provider (fake API, no network)."""

import json

import httpx2
import pytest
from test_chatgpt_plan import Api, completed, delta, make, sse, stream_response

from wow_coach.ai.base import (
    AIError,
    Message,
    Replay,
    ToolCall,
    ToolResult,
    ToolSpec,
    WebSearchUnavailable,
)
from wow_coach.ai.chatgpt_plan import ChatGPTPlan, build_request_body, input_items, strict_schema
from wow_coach.ai.chatgpt_plan import read_response as read_response_lines

SPEC = ToolSpec(
    "search_wiki",
    "Search the wiki.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "maxLength": 200, "description": "What to find."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "required": ["query"],
    },
)
REASONING = {"type": "reasoning", "id": "rs_1", "encrypted_content": "SECRET-BLOB", "summary": []}


def item_done(item: dict[str, object]) -> dict[str, object]:
    return {"type": "response.output_item.done", "item": item}


def function_call(arguments: object, call_id: str = "call_1") -> dict[str, object]:
    return {
        "type": "function_call",
        "name": "search_wiki",
        "arguments": arguments,
        "call_id": call_id,
        "status": "completed",
    }


def lines_of(*events: dict[str, object]) -> list[str]:
    return sse(*events).decode().splitlines()


def read(*events: dict[str, object]):  # noqa: ANN201
    return read_response_lines(iter(lines_of(*events)), 1000)


# ---- the request ----------------------------------------------------------------------


def test_function_tools_are_strict_and_ask_for_encrypted_reasoning() -> None:
    body = build_request_body([Message("user", "hi")], model="m", json_schema=None, tools=[SPEC])
    [tool] = body["tools"]  # type: ignore[misc]
    assert tool["type"] == "function" and tool["name"] == "search_wiki"
    assert tool["strict"] is True
    parameters = tool["parameters"]
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == ["query", "limit"]  # strict: every property is required
    assert parameters["properties"]["limit"]["type"] == ["integer", "null"]  # ... optional = null
    assert parameters["properties"]["query"]["type"] == "string"
    assert parameters["properties"]["query"]["description"] == "What to find."
    for refused in ("maxLength", "minimum", "maximum", "default"):
        assert refused not in json.dumps(parameters)
    assert body["include"] == ["reasoning.encrypted_content"]


def test_web_search_is_the_built_in_tool() -> None:
    body = build_request_body([Message("user", "hi")], model="m", json_schema=None, web_search=True)
    assert body["tools"] == [{"type": "web_search"}]
    assert body["include"] == ["reasoning.encrypted_content"]


def test_without_tools_the_request_has_no_tool_fields() -> None:
    body = build_request_body([Message("user", "hi")], model="m", json_schema=None)
    assert "tools" not in body and "include" not in body


def test_json_schema_still_works_next_to_tools() -> None:
    schema: dict[str, object] = {"type": "object"}
    body = build_request_body(
        [Message("user", "hi")], model="m", json_schema=schema, tools=[SPEC], web_search=True
    )
    assert body["text"]["format"]["schema"] == schema  # type: ignore[index]
    assert len(body["tools"]) == 2  # type: ignore[arg-type]


def test_strict_schema_leaves_the_original_alone() -> None:
    before = json.dumps(SPEC.parameters)
    strict_schema(SPEC.parameters)
    assert json.dumps(SPEC.parameters) == before


def test_input_items_send_replays_as_they_are_and_results_as_outputs() -> None:
    call = function_call('{"query": "x"}')
    items = input_items(
        [
            Message("system", "Be brief."),
            Message("user", "Q"),
            Replay(REASONING),
            Replay(call),
            ToolCall("call_1", "search_wiki", {"query": "x"}),  # already inside the Replay
            ToolResult("call_1", "found it"),
        ]
    )
    assert items == [
        {"role": "user", "content": "Q"},
        REASONING,
        call,
        {"type": "function_call_output", "call_id": "call_1", "output": "found it"},
    ]


def test_a_tool_call_without_a_replay_becomes_a_function_call_item() -> None:
    [item] = input_items([ToolCall("c9", "search_wiki", {"query": "x"})])
    assert item == {
        "type": "function_call",
        "call_id": "c9",
        "name": "search_wiki",
        "arguments": '{"query": "x"}',
    }


# ---- reading the answer ---------------------------------------------------------------


def test_function_calls_become_tool_calls_and_are_kept_for_replay_in_order() -> None:
    call = function_call('{"query": "Forsaken hides", "limit": 3}')
    result = read(item_done(REASONING), item_done(call), completed())
    assert result.tool_calls == [
        ToolCall("call_1", "search_wiki", {"query": "Forsaken hides", "limit": 3})
    ]
    assert [r.item for r in result.replay] == [REASONING, call]
    assert result.text == ""


@pytest.mark.parametrize(
    ("arguments", "why"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ("x" * 300_000, "far too long"),
    ],
)
def test_bad_arguments_become_an_empty_dict_and_a_note(arguments: str, why: str) -> None:
    [call] = read(item_done(function_call(arguments)), completed()).tool_calls
    assert call.arguments == {} and why in call.arguments_error


def test_empty_or_missing_arguments_are_just_no_arguments() -> None:
    [first, second] = read(
        item_done(function_call("")), item_done(function_call(None, "call_2")), completed()
    ).tool_calls
    assert first.arguments == {} and first.arguments_error == ""
    assert second.arguments == {} and second.arguments_error == ""


def test_web_searches_collect_queries_and_cited_urls() -> None:
    search = {
        "type": "web_search_call",
        "status": "completed",
        "action": {"type": "search", "queries": ["wow forever hides", "forsaken quest"]},
    }
    cite = {"type": "url_citation", "url": "https://example.test/a", "title": "A"}
    result = read(
        item_done(search),
        delta("Answer."),
        {"type": "response.output_text.annotation.added", "annotation": cite},
        {"type": "response.output_text.annotation.added", "annotation": cite},  # repeated
        {
            "type": "response.output_text.annotation.added",
            "annotation": {"type": "file_citation", "file_id": "f"},
        },
        completed(),
    )
    assert result.text == "Answer."
    [found] = result.web_searches
    assert found.queries == ("wow forever hides", "forsaken quest")
    assert found.sources == ("https://example.test/a",)
    assert result.replay == []  # searches are not replayed


def test_citations_in_the_final_message_item_count_too() -> None:
    message = {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": "x",
                "annotations": [{"type": "url_citation", "url": "https://example.test/b"}],
            }
        ],
    }
    [found] = read(item_done(message), completed()).web_searches
    assert found.queries == () and found.sources == ("https://example.test/b",)


def test_odd_items_do_not_break_a_finished_answer() -> None:
    result = read(item_done({"type": "something_new"}), item_done("nope"), delta("ok"), completed())  # type: ignore[arg-type]
    assert result.text == "ok" and result.replay == [] and result.tool_calls == []


def test_a_flood_of_tool_calls_is_refused() -> None:
    events = [item_done(function_call("{}", f"c{n}")) for n in range(70)]
    with pytest.raises(AIError, match="more tool requests"):
        read(*events, completed())


# ---- through the provider -------------------------------------------------------------


def test_ask_returns_tool_calls_and_replay_and_sends_tools() -> None:
    call = function_call('{"query": "x"}')
    api = Api(stream_response(sse(item_done(REASONING), item_done(call), completed())))
    answer = make(api).ask(
        [Message("user", "q")], model="m1", max_output_tokens=100, tools=[SPEC], web_search=True
    )
    assert answer.tool_calls[0].name == "search_wiki"
    assert [r.item for r in answer.replay] == [REASONING, call]
    sent = json.loads(api.requests[0].content)
    assert [t["type"] for t in sent["tools"]] == ["function", "web_search"]


def test_the_second_request_carries_replay_and_results() -> None:
    call = function_call('{"query": "x"}')
    api = Api(
        stream_response(sse(item_done(REASONING), item_done(call), completed())),
        stream_response(sse(delta("Final."), completed())),
    )
    plan: ChatGPTPlan = make(api)
    messages: list[Message | Replay | ToolResult] = [Message("user", "q")]
    first = plan.ask(messages, model="m1", max_output_tokens=100, tools=[SPEC])
    messages.extend(first.replay)
    messages.append(ToolResult("call_1", "the page text"))
    second = plan.ask(messages, model="m1", max_output_tokens=100, tools=[SPEC])
    assert second.text == "Final."
    sent = json.loads(api.requests[1].content)
    assert sent["input"][1:] == [
        REASONING,
        call,
        {"type": "function_call_output", "call_id": "call_1", "output": "the page text"},
    ]


def test_a_refused_tools_setting_with_web_search_is_web_search_unavailable() -> None:
    body = {"error": {"code": "subscription_sharing_unsupported_capability", "param": "tools[1]"}}
    plan = make(Api(httpx2.Response(400, json=body)))
    with pytest.raises(WebSearchUnavailable):
        plan.ask([Message("user", "q")], model="m", max_output_tokens=5, web_search=True)


def test_a_refused_tools_setting_without_web_search_stays_a_plain_error() -> None:
    body = {"error": {"code": "subscription_sharing_unsupported_capability", "param": "tools[0]"}}
    plan = make(Api(httpx2.Response(400, json=body)))
    with pytest.raises(AIError) as caught:
        plan.ask([Message("user", "q")], model="m", max_output_tokens=5, tools=[SPEC])
    assert not isinstance(caught.value, WebSearchUnavailable)


def test_other_refusals_with_web_search_stay_as_they_are() -> None:
    body = {
        "error": {"code": "subscription_sharing_unsupported_capability", "param": "text.format"}
    }
    plan = make(Api(httpx2.Response(400, json=body)))
    with pytest.raises(AIError, match=r"'text\.format'") as caught:
        plan.ask([Message("user", "q")], model="m", max_output_tokens=5, web_search=True)
    assert not isinstance(caught.value, WebSearchUnavailable)
