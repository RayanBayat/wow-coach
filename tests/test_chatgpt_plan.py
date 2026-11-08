"""Tests for the ChatGPT plan provider, against a fake model API (no real network)."""

import json
import logging
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from wow_coach.ai.base import AIError, Message, NotSignedIn, PlanLimitReached, Provider, Usage
from wow_coach.ai.chatgpt_plan import ChatGPTPlan, PlanModel, read_stream
from wow_coach.usage import UsageLog

BASE = "https://api.openai.test/v1"
TOKEN_1 = "access-token-SECRET-1"  # noqa: S105
TOKEN_2 = "access-token-SECRET-2"  # noqa: S105
SERVER_TEXT = "internal-server-detail-do-not-show"


class FakeTokens:
    """Stands in for the sign-in: hands out TOKEN_1, then TOKEN_2 after a refresh."""

    def __init__(self, *, can_refresh: bool = True) -> None:
        self.current = TOKEN_1
        self.refreshes = 0
        self._can_refresh = can_refresh

    def access_token(self) -> str:
        return self.current

    def refresh(self) -> str:
        self.refreshes += 1
        if not self._can_refresh:
            raise NotSignedIn("Your ChatGPT sign-in has ended. Please sign in again.")
        self.current = TOKEN_2
        return self.current


def sse(*events: dict[str, object]) -> bytes:
    """Encode events as a server-sent-events stream."""
    text = ""
    for event in events:
        text += f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
    return text.encode()


def delta(text: str) -> dict[str, object]:
    return {"type": "response.output_text.delta", "delta": text}


def completed(input_tokens: int = 11, output_tokens: int = 7) -> dict[str, object]:
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    return {"type": "response.completed", "response": {"usage": usage}}


HAPPY = sse(delta("A game "), delta("about heroes."), completed())

type Handler = Callable[[httpx2.Request], httpx2.Response]


class Api:
    """A fake model API that records requests and answers with a script."""

    def __init__(self, *answers: httpx2.Response | Handler) -> None:
        self.requests: list[httpx2.Request] = []
        self._answers = list(answers)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        return answer(request) if callable(answer) else answer


def stream_response(content: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=content, headers={"content-type": "text/event-stream"})


def make(
    api: Api, tokens: FakeTokens | None = None, usage_log: UsageLog | None = None
) -> ChatGPTPlan:
    return ChatGPTPlan(
        tokens or FakeTokens(), transport=api.transport(), usage_log=usage_log, base_url=BASE
    )


def ask(plan: ChatGPTPlan, schema: dict[str, object] | None = None) -> str:
    messages = [Message("system", "Be brief."), Message("user", "What is WoW?")]
    return plan.ask(messages, model="m1", max_output_tokens=100, json_schema=schema).text


# ---- the request ----------------------------------------------------------------------


def test_it_is_a_provider() -> None:
    plan: Provider = make(Api(stream_response(HAPPY)))
    assert plan.name == "ChatGPT (your plan)"


def test_request_follows_the_plan_rules() -> None:
    api = Api(stream_response(HAPPY))
    assert ask(make(api)) == "A game about heroes."
    request = api.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/responses"
    assert request.headers["authorization"] == f"Bearer {TOKEN_1}"
    body = json.loads(request.content)
    assert body["model"] == "m1"
    assert body["store"] is False
    assert body["stream"] is True
    assert body["instructions"] == "Be brief."  # system text goes here ...
    assert body["input"] == [{"role": "user", "content": "What is WoW?"}]  # ... not in input
    for rejected in ("max_output_tokens", "temperature", "metadata", "user", "background"):
        assert rejected not in body
    assert "text" not in body


def test_json_schema_becomes_the_text_format() -> None:
    api = Api(stream_response(HAPPY))
    schema: dict[str, object] = {"type": "object", "properties": {"steps": {"type": "array"}}}
    ask(make(api), schema)
    body = json.loads(api.requests[0].content)
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["schema"] == schema


def test_answer_has_text_model_and_usage() -> None:
    plan = make(Api(stream_response(HAPPY)))
    answer = plan.ask([Message("user", "hi")], model="m1", max_output_tokens=100)
    assert (answer.text, answer.model) == ("A game about heroes.", "m1")
    assert answer.usage == Usage(11, 7)


def test_long_answers_are_cut_because_the_server_cannot_be_told_a_limit() -> None:
    long = sse(delta("a" * 30), delta("b" * 30), delta("c" * 30), completed())
    plan = make(Api(stream_response(long)))
    answer = plan.ask([Message("user", "hi")], model="m1", max_output_tokens=10)  # 40 characters
    assert answer.text == "a" * 30 + "b" * 10
    assert answer.usage == Usage(11, 7)  # the usage numbers still arrive in the last event


def test_missing_usage_numbers_count_as_zero() -> None:
    stream = sse(delta("x"), {"type": "response.completed", "response": {}})
    plan = make(Api(stream_response(stream)))
    answer = plan.ask([Message("user", "hi")], model="m1", max_output_tokens=100)
    assert answer.usage == Usage(0, 0)


# ---- the usage log --------------------------------------------------------------------


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_calls_are_counted_and_never_refused_by_us(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    api = Api(lambda _request: stream_response(HAPPY))
    plan = make(api, usage_log=log)
    ask(plan)
    call, tokens = _lines(tmp_path / "usage.jsonl")
    assert "tokens_only" not in call
    assert (tokens["tokens_only"], tokens["input_tokens"], tokens["output_tokens"]) == (True, 11, 7)
    for _ in range(30):  # many more calls than the old default limit of 20 an hour
        ask(plan)
    assert len(api.requests) == 31  # every call reached the network
    assert log.calls_in_last(3600) == 31


def test_failed_calls_still_count_as_attempts(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    plan = make(Api(httpx2.Response(500)), usage_log=log)
    for _ in range(2):
        with pytest.raises(AIError):
            ask(plan)
    assert log.calls_in_last(3600) == 2


def test_a_cut_answer_still_records_its_usage_when_the_stream_reports_it(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    long = sse(delta("a" * 100), completed(5, 40))
    plan = make(Api(stream_response(long)), usage_log=log)
    answer = plan.ask([Message("user", "hi")], model="m1", max_output_tokens=10)
    assert answer.text == "a" * 40
    assert answer.usage == Usage(5, 40)
    assert _lines(tmp_path / "usage.jsonl")[-1]["output_tokens"] == 40


def test_an_error_event_in_the_stream_is_mapped() -> None:
    limit = {"type": "error", "code": "subscription_sharing_usage_limit_exceeded"}
    with pytest.raises(PlanLimitReached):
        ask(make(Api(stream_response(sse(limit)))))
    other = {"type": "error", "code": "weird", "message": SERVER_TEXT}
    with pytest.raises(AIError) as caught:
        ask(make(Api(stream_response(sse(other)))))
    assert SERVER_TEXT not in str(caught.value)


def test_a_stream_that_takes_too_long_is_stopped() -> None:
    times = iter([0.0, 1.0, 999.0, 1000.0])
    lines = iter(HAPPY.decode().splitlines())
    with pytest.raises(AIError, match="took too long"):
        read_stream(lines, 1000, deadline_seconds=10, clock=lambda: next(times))


def test_a_huge_line_is_refused() -> None:
    with pytest.raises(AIError, match="too large"):
        read_stream(iter(["data: " + "x" * 2_000_000]), 1000)


def test_absurdly_nested_event_json_is_skipped_not_a_crash() -> None:
    lines = iter(["data: " + "[" * 300_000, *HAPPY.decode().splitlines()])
    assert read_stream(lines, 1000)[0] == "A game about heroes."


@pytest.mark.parametrize("value", ["²", "١٢٣", "12345678", "-5", "1.5", ""])
def test_a_strange_retry_after_is_ignored(value: str) -> None:
    api = Api(httpx2.Response(429, headers={"Retry-After": value.encode("utf-8")}))
    with pytest.raises(PlanLimitReached) as caught:
        ask(make(api))
    assert caught.value.retry_after_seconds is None


# ---- errors ---------------------------------------------------------------------------


def test_401_refreshes_once_and_retries_with_the_new_token() -> None:
    api = Api(httpx2.Response(401, json={"detail": SERVER_TEXT}), stream_response(HAPPY))
    tokens = FakeTokens()
    assert ask(make(api, tokens)) == "A game about heroes."
    assert tokens.refreshes == 1
    assert [r.headers["authorization"] for r in api.requests] == [
        f"Bearer {TOKEN_1}",
        f"Bearer {TOKEN_2}",
    ]


def test_two_401s_mean_not_signed_in() -> None:
    api = Api(httpx2.Response(401))
    tokens = FakeTokens()
    with pytest.raises(NotSignedIn):
        ask(make(api, tokens))
    assert tokens.refreshes == 1  # refreshed once, not in a loop
    assert len(api.requests) == 2


def test_401_with_a_failed_refresh_is_not_signed_in() -> None:
    with pytest.raises(NotSignedIn):
        ask(make(Api(httpx2.Response(401)), FakeTokens(can_refresh=False)))


def test_429_is_a_plan_limit_with_retry_after() -> None:
    api = Api(httpx2.Response(429, headers={"Retry-After": "120"}, json={"detail": SERVER_TEXT}))
    with pytest.raises(PlanLimitReached) as caught:
        ask(make(api))
    assert caught.value.retry_after_seconds == 120
    assert "Usage limit reached" in str(caught.value)
    assert "chatgpt.com/settings/usage" in str(caught.value)
    assert SERVER_TEXT not in str(caught.value)


def test_429_without_retry_after_has_no_reset_time() -> None:
    with pytest.raises(PlanLimitReached) as caught:
        ask(make(Api(httpx2.Response(429))))
    assert caught.value.retry_after_seconds is None


def test_usage_limit_code_inside_the_stream_is_a_plan_limit() -> None:
    failed: dict[str, object] = {
        "type": "response.failed",
        "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
    }
    with pytest.raises(PlanLimitReached):
        ask(make(Api(stream_response(sse(delta("par"), failed)))))


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_a_plain_sentence_never_the_raw_response(status: int) -> None:
    api = Api(httpx2.Response(status, json={"detail": SERVER_TEXT}))
    with pytest.raises(AIError) as caught:
        ask(make(api))
    assert not isinstance(caught.value, NotSignedIn | PlanLimitReached)
    assert "try again later" in str(caught.value)
    assert SERVER_TEXT not in str(caught.value)


def test_unsupported_setting_names_the_parameter() -> None:
    body = {
        "error": {"code": "subscription_sharing_unsupported_capability", "param": "text.format"}
    }
    with pytest.raises(AIError, match=r"'text\.format'"):
        ask(make(Api(httpx2.Response(400, json=body))))


def test_unsupported_setting_does_not_echo_a_strange_parameter() -> None:
    body = {
        "error": {"code": "subscription_sharing_unsupported_capability", "param": SERVER_TEXT * 5}
    }
    with pytest.raises(AIError) as caught:
        ask(make(Api(httpx2.Response(400, json=body))))
    assert SERVER_TEXT not in str(caught.value)


def test_not_eligible_is_explained() -> None:
    body = {"error": {"code": "subscription_sharing_user_not_eligible", "message": SERVER_TEXT}}
    with pytest.raises(AIError, match="can't be used") as caught:
        ask(make(Api(httpx2.Response(403, json=body))))
    assert SERVER_TEXT not in str(caught.value)


def test_an_error_body_that_is_not_json_is_fine() -> None:
    with pytest.raises(AIError, match="could not answer"):
        ask(make(Api(httpx2.Response(418, text=SERVER_TEXT))))


def test_a_stream_that_stops_early_is_an_error() -> None:
    with pytest.raises(AIError, match="broke"):
        ask(make(Api(stream_response(sse(delta("half"))))))


def test_incomplete_is_an_error() -> None:
    with pytest.raises(AIError, match="stopped before"):
        ask(make(Api(stream_response(sse(delta("half"), {"type": "response.incomplete"})))))


def test_network_problems_are_plain_sentences() -> None:
    def connect_error(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(AIError, match="Could not reach"):
        ask(make(Api(connect_error)))
    with pytest.raises(AIError, match="took too long"):
        ask(make(Api(timeout)))


def test_not_signed_in_from_the_token_source_passes_through() -> None:
    class Nobody:
        def access_token(self) -> str:
            raise NotSignedIn("Sign in first.")

        def refresh(self) -> str:
            raise NotSignedIn("Sign in first.")

    plan = ChatGPTPlan(Nobody(), transport=Api(httpx2.Response(200)).transport(), base_url=BASE)
    with pytest.raises(NotSignedIn):
        ask(plan)


def test_garbled_event_lines_are_skipped() -> None:
    lines = iter(["data: not json", ": comment", "data: [1]", *HAPPY.decode().splitlines()])
    assert read_stream(lines, 1000)[0] == "A game about heroes."


# ---- models and check -------------------------------------------------------------------


MODELS = {
    "models": [
        {"slug": "big", "display_name": "Big", "visibility": "list"},
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
        {"slug": "small", "display_name": "Small", "visibility": "list"},
    ]
}


def test_list_models_keeps_listed_ones_in_server_order() -> None:
    api = Api(httpx2.Response(200, json=MODELS))
    assert make(api).list_models() == [PlanModel("big", "Big"), PlanModel("small", "Small")]
    assert api.requests[0].method == "GET"
    assert str(api.requests[0].url) == f"{BASE}/models"
    assert api.requests[0].headers["authorization"] == f"Bearer {TOKEN_1}"


def test_list_models_refreshes_on_401_too() -> None:
    api = Api(httpx2.Response(401), httpx2.Response(200, json=MODELS))
    tokens = FakeTokens()
    assert len(make(api, tokens).list_models()) == 2
    assert tokens.refreshes == 1


def test_list_models_with_an_unreadable_answer() -> None:
    with pytest.raises(AIError, match="could not read"):
        make(Api(httpx2.Response(200, json={"oops": 1}))).list_models()


def test_check_says_ok_or_why_not() -> None:
    assert make(Api(httpx2.Response(200, json=MODELS))).check() == "ok"
    assert "no models" in make(Api(httpx2.Response(200, json={"models": []}))).check()
    assert "not available" in make(Api(httpx2.Response(503))).check()


# ---- secrets ---------------------------------------------------------------------------


def test_no_token_appears_in_logs_or_error_messages(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []
    for answer in (httpx2.Response(401), httpx2.Response(429), httpx2.Response(500)):
        with pytest.raises(AIError) as caught:
            ask(make(Api(answer)))
        seen.append(str(caught.value))
    ask(make(Api(stream_response(HAPPY))))
    text = caplog.text + "\n".join(seen)
    assert TOKEN_1 not in text
    assert TOKEN_2 not in text
