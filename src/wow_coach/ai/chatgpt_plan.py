"""Asks questions with the player's own ChatGPT plan (the ``Provider`` for "Sign in with ChatGPT").

How OpenAI wants the plan token used (docs read 2026-11-08, see
``docs/plans/chatgpt-signin-notes.md``):

* ``POST https://api.openai.com/v1/responses`` with ``Authorization: Bearer <access token>``.
* ``store`` must be ``false`` and ``stream`` must be ``true``: the answer arrives as a stream
  of small events, and only ``response.completed`` means success.
* Some fields are rejected, among them ``max_output_tokens`` and ``temperature``. System
  messages go in ``instructions``, not in ``input``.
* We never use ChatGPT's ``backend-api`` (the web page's private API).
"""

import json
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

import httpx2

from wow_coach.ai.base import AIError, Answer, Message, NotSignedIn, PlanLimitReached, Usage
from wow_coach.ai.chatgpt_signin import RESOURCE
from wow_coach.usage import UsageLog
from wow_coach.web import build_user_agent

PROVIDER_NAME = "ChatGPT (your plan)"
TIMEOUT = httpx2.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

STREAM_DEADLINE_SECONDS = 300.0  # one answer may take at most this long in total
MAX_LINE_CHARACTERS = 1_000_000  # one event line; a bigger one is not a real answer

# We can't send ``max_output_tokens``, so we cut the text ourselves. About 4 characters per token.
CHARACTERS_PER_TOKEN = 4

# Plain sentences for the error codes OpenAI documents. The server's own wording is never shown.
_ERROR_MESSAGES = {
    "subscription_sharing_user_not_eligible": (
        "Your ChatGPT plan can't be used with wow-coach. "
        "Plus and Pro plans are supported at the moment."
    ),
    "subscription_sharing_usage_unavailable": (
        "ChatGPT can't tell how much of your plan is left right now. Please try again later."
    ),
    "subscription_sharing_user_unavailable": (
        "ChatGPT can't be reached for your account right now. Please try again later."
    ),
    "subscription_sharing_route_not_supported": (
        "ChatGPT did not accept this kind of request. Please report this bug to wow-coach."
    ),
    "chatpass_v2_scope_not_authorized": (
        "Your ChatGPT sign-in is missing a permission. Sign out, then sign in again."
    ),
    "chatpass_v2_invalid_authorization_context": (
        "Your ChatGPT sign-in is not valid for this use. Sign out, then sign in again."
    ),
}
_USAGE_LIMIT_CODE = "subscription_sharing_usage_limit_exceeded"
_UNSUPPORTED_CODE = "subscription_sharing_unsupported_capability"
_INVALID_USER_CODE = "subscription_sharing_invalid_user"

LIMIT_MESSAGE = (
    "Usage limit reached. Review your plan or this app's limit in ChatGPT settings: "
    "https://chatgpt.com/settings/usage"
)

_SAFE_PARAM = re.compile(r"[A-Za-z0-9_.\[\]]{1,60}")


class TokenSource(Protocol):
    """What ``ChatGPTPlan`` needs from the sign-in: ``ChatGPTSignIn`` fits this shape.

    Tests hand in a tiny fake with the same two methods.
    """

    def access_token(self) -> str:
        """A valid access token. Raises ``NotSignedIn`` if there is none."""
        ...

    def refresh(self) -> str:
        """Get a new access token now. Raises ``NotSignedIn`` if that is impossible."""
        ...


@dataclass(frozen=True, slots=True)
class PlanModel:
    """One model the player's plan can use."""

    slug: str
    display_name: str


class _Unauthorized(Exception):  # noqa: N818
    """Internal signal: OpenAI answered 401 (the token may just have expired)."""


class ChatGPTPlan:
    """The ``Provider`` that uses the player's ChatGPT plan."""

    name = PROVIDER_NAME

    def __init__(
        self,
        tokens: TokenSource,
        *,
        transport: httpx2.BaseTransport | None = None,
        usage_log: UsageLog | None = None,
        base_url: str = RESOURCE,
    ) -> None:
        """Create the provider.

        Args:
            tokens: Gives access tokens (a ``ChatGPTSignIn``).
            transport: Replaces the real network (tests only).
            usage_log: When given, every call is checked against the caps and then recorded.
            base_url: The API address (only tests change it).
        """
        self._tokens = tokens
        self._usage_log = usage_log
        self._base_url = base_url.rstrip("/")
        self._client = httpx2.Client(
            transport=transport, timeout=TIMEOUT, headers={"User-Agent": build_user_agent()}
        )

    # -- the Provider contract -------------------------------------------------------------

    def ask(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_output_tokens: int,
        json_schema: dict[str, object] | None = None,
    ) -> Answer:
        """Send the conversation and return the reply (see ``Provider.ask``)."""
        if self._usage_log is not None:
            # Checks the caps and counts this ATTEMPT before sending, so a failed call counts too.
            self._usage_log.begin_call(model)
        body = build_request_body(messages, model=model, json_schema=json_schema)
        limit = max_output_tokens * CHARACTERS_PER_TOKEN
        text, usage = self._with_token_retry(lambda token: self._stream_answer(token, body, limit))
        if self._usage_log is not None:
            self._usage_log.record_tokens(model, usage)
        return Answer(text=text, model=model, usage=usage)

    def check(self) -> str:
        """Return "ok" if the plan can answer now, else a plain sentence saying why not."""
        try:
            models = self.list_models()
        except AIError as error:
            return str(error)
        if not models:
            return "Your ChatGPT plan lists no models for wow-coach to use."
        return "ok"

    # -- more than the contract ------------------------------------------------------------

    def list_models(self) -> list[PlanModel]:
        """The models the signed-in plan can use, in the order OpenAI gives them."""
        return self._with_token_retry(self._fetch_models)

    # -- talking to OpenAI -----------------------------------------------------------------

    def _with_token_retry[T](self, action: Callable[[str], T]) -> T:
        """Run ``action(token)``. On a 401, refresh the token once and try again."""
        try:
            return action(self._tokens.access_token())
        except _Unauthorized:
            pass
        try:
            return action(self._tokens.refresh())
        except _Unauthorized as error:
            raise NotSignedIn(
                "ChatGPT did not accept your sign-in. Please sign in again."
            ) from error

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _fetch_models(self, token: str) -> list[PlanModel]:
        try:
            response = self._client.get(f"{self._base_url}/models", headers=self._headers(token))
        except httpx2.HTTPError as error:
            raise _network_error(error) from error
        if response.status_code != 200:
            raise_for_error(response.status_code, _safe_json(response), response.headers)
        models = _safe_json(response).get("models")
        if not isinstance(models, list):
            raise AIError("ChatGPT sent a model list that wow-coach could not read.")
        return [
            PlanModel(slug=str(item["slug"]), display_name=str(item.get("display_name", "")))
            for item in models
            if isinstance(item, dict) and item.get("visibility") == "list" and "slug" in item
        ]

    def _stream_answer(self, token: str, body: dict[str, object], limit: int) -> tuple[str, Usage]:
        try:
            with self._client.stream(
                "POST", f"{self._base_url}/responses", json=body, headers=self._headers(token)
            ) as response:
                if response.status_code != 200:
                    response.read()
                    raise_for_error(response.status_code, _safe_json(response), response.headers)
                return read_stream(response.iter_lines(), limit)
        except httpx2.HTTPError as error:
            raise _network_error(error) from error


# ----------------------------------------------------------------------------------------
# Building the request and reading the answer.
# ----------------------------------------------------------------------------------------


def build_request_body(
    messages: Sequence[Message], *, model: str, json_schema: dict[str, object] | None
) -> dict[str, object]:
    """The JSON body for ``POST /v1/responses`` with the fields the plan route allows."""
    instructions = "\n\n".join(m.content for m in messages if m.role == "system")
    body: dict[str, object] = {
        "model": model,
        "input": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
        "store": False,  # required by the plan route
        "stream": True,  # required by the plan route
    }
    if instructions:
        body["instructions"] = instructions
    if json_schema is not None:
        # The standard Responses API option for JSON output. The sign-in docs don't mention
        # it (UNVERIFIED on this route), so a refusal is reported plainly, see raise_for_error.
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "wow_coach_answer",
                "schema": json_schema,
                "strict": False,
            }
        }
    return body


def read_stream(
    lines: Iterator[str],
    limit: int,
    *,
    deadline_seconds: float = STREAM_DEADLINE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, Usage]:
    """Read the server-sent events of one answer and return ``(text, usage)``.

    The text is cut to ``limit`` characters (we can't ask the server for a limit, see the
    module docstring). We still read on to the end, without keeping more text, because the
    final event holds the usage numbers. The whole read may take ``deadline_seconds`` at most.
    """
    stop_at = clock() + deadline_seconds
    parts: list[str] = []
    length = 0
    for event in _events(lines):
        if clock() > stop_at:
            raise AIError("ChatGPT took too long to finish the answer. Please try again.")
        kind = event.get("type")
        if kind == "response.output_text.delta":
            delta = str(event.get("delta", ""))[: max(0, limit - length)]
            parts.append(delta)
            length += len(delta)
        elif kind == "response.completed":
            return "".join(parts), _usage_from(event)
        elif kind == "response.failed":
            raise_for_error(None, _failed_body(event), {})
        elif kind == "error":
            raise_for_error(None, {"error": event}, {})
        elif kind == "response.incomplete":
            raise AIError("ChatGPT stopped before finishing the answer. Please try again.")
    if length >= limit > 0:
        return "".join(parts), Usage()  # cut by us, and the stream ended early: keep the text
    raise AIError("The connection to ChatGPT broke before the answer was finished.")


def _events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yield the JSON of every ``data:`` line of a server-sent-events stream."""
    for line in lines:
        if len(line) > MAX_LINE_CHARACTERS:
            raise AIError("ChatGPT sent an answer that is too large to read.")
        if not line.startswith("data:"):
            continue  # "event:" names, comments and blank separator lines
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        try:
            event = json.loads(payload)
        except ValueError, RecursionError:  # not JSON, or absurdly nested
            continue
        if isinstance(event, dict):
            yield event


def _usage_from(event: Mapping[str, Any]) -> Usage:
    response = event.get("response")
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return Usage()
    return Usage(
        input_tokens=_whole_number(usage.get("input_tokens")),
        output_tokens=_whole_number(usage.get("output_tokens")),
    )


def _whole_number(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _failed_body(event: Mapping[str, Any]) -> dict[str, Any]:
    """Turn a ``response.failed`` event into the same shape as an error response body."""
    response = event.get("response")
    error = response.get("error") if isinstance(response, dict) else None
    return {"error": error if isinstance(error, dict) else {}}


# ----------------------------------------------------------------------------------------
# Errors.
# ----------------------------------------------------------------------------------------


def raise_for_error(
    status: int | None, body: Mapping[str, Any], headers: Mapping[str, str]
) -> NoReturn:
    """Raise the right error for a failed call. Never includes the server's own text.

    ``status`` is ``None`` for an error that arrived inside the stream (``response.failed``).
    """
    error = body.get("error")
    code = str(error.get("code", "")) if isinstance(error, dict) else ""
    if status == 401 or code == _INVALID_USER_CODE:
        raise _Unauthorized
    if status == 429 or code == _USAGE_LIMIT_CODE:
        raise PlanLimitReached(LIMIT_MESSAGE, retry_after_seconds=_retry_after(headers))
    if code == _UNSUPPORTED_CODE:
        raise AIError(_unsupported_message(error))
    if code in _ERROR_MESSAGES:
        raise AIError(_ERROR_MESSAGES[code])
    if status is not None and status >= 500:
        raise AIError("ChatGPT is not available right now. Please try again later.")
    if status == 403:
        raise AIError("ChatGPT refused the request for your account or region.")
    where = f" (error {status})" if status is not None else ""
    raise AIError(f"ChatGPT could not answer{where}. Please try again later.")


def _unsupported_message(error: object) -> str:
    param = error.get("param") if isinstance(error, dict) else None
    if isinstance(param, str) and _SAFE_PARAM.fullmatch(param):
        return f"ChatGPT does not support the request setting '{param}' on your plan."
    return "ChatGPT does not support one of the request settings on your plan."


def _retry_after(headers: Mapping[str, str]) -> int | None:
    value = headers.get("retry-after")
    # isascii first: str.isdigit() is also true for digits like "²" that int() rejects
    if value is None or not (value.isascii() and value.isdigit() and len(value) <= 7):
        return None
    return int(value)


def _safe_json(response: httpx2.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _network_error(error: httpx2.HTTPError) -> AIError:
    if isinstance(error, httpx2.TimeoutException):
        return AIError("ChatGPT took too long to answer. Please try again.")
    return AIError("Could not reach ChatGPT. Check your internet connection.")
