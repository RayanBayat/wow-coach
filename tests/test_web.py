"""Tests for the polite web fetcher (no real network: a fake transport answers)."""

import httpx2
import pytest

from wow_coach.errors import LookupFailed
from wow_coach.web import PoliteFetcher

URL = "https://example.test/api.php"


class FakeClock:
    """A clock the test moves by hand; ``sleep`` moves it forward instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _fetcher(handler: httpx2.MockTransport, clock: FakeClock, ttl: float = 3600.0) -> PoliteFetcher:
    return PoliteFetcher(
        user_agent="wow-coach-test/0",
        transport=handler,
        clock=clock.time,
        sleep=clock.sleep,
        ttl_seconds=ttl,
        min_interval_seconds=0.5,
    )


def _ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, text=f"answer for {request.url.params.get('q')}")


def test_returns_the_response_text_and_sends_our_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers["user-agent"])
        return _ok(request)

    fetcher = _fetcher(httpx2.MockTransport(handler), FakeClock())
    assert fetcher(URL, {"q": "a"}) == "answer for a"
    assert seen == ["wow-coach-test/0"]


def test_same_request_is_served_from_cache() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return _ok(request)

    fetcher = _fetcher(httpx2.MockTransport(handler), FakeClock())
    fetcher(URL, {"q": "a"})
    fetcher(URL, {"q": "a"})
    assert len(calls) == 1


def test_cache_expires_after_the_ttl() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return _ok(request)

    clock = FakeClock()
    fetcher = _fetcher(httpx2.MockTransport(handler), clock, ttl=60.0)
    fetcher(URL, {"q": "a"})
    clock.now += 61
    fetcher(URL, {"q": "a"})
    assert len(calls) == 2


def test_requests_to_one_site_are_spaced_out() -> None:
    clock = FakeClock()
    fetcher = _fetcher(httpx2.MockTransport(_ok), clock)
    fetcher(URL, {"q": "a"})
    fetcher(URL, {"q": "b"})
    assert clock.sleeps == [pytest.approx(0.5)]


def test_no_waiting_when_enough_time_has_passed() -> None:
    clock = FakeClock()
    fetcher = _fetcher(httpx2.MockTransport(_ok), clock)
    fetcher(URL, {"q": "a"})
    clock.now += 5
    fetcher(URL, {"q": "b"})
    assert clock.sleeps == []


def test_timeout_becomes_lookup_failed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    fetcher = _fetcher(httpx2.MockTransport(handler), FakeClock())
    with pytest.raises(LookupFailed, match="timeout"):
        fetcher(URL, {"q": "a"})


def test_error_status_becomes_lookup_failed() -> None:
    fetcher = _fetcher(httpx2.MockTransport(lambda _: httpx2.Response(503)), FakeClock())
    with pytest.raises(LookupFailed, match="HTTP 503"):
        fetcher(URL, {"q": "a"})


def test_network_error_becomes_lookup_failed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    fetcher = _fetcher(httpx2.MockTransport(handler), FakeClock())
    with pytest.raises(LookupFailed, match="network"):
        fetcher(URL, {"q": "a"})


def test_failures_are_not_cached() -> None:
    answers = iter([httpx2.Response(500), httpx2.Response(200, text="fine")])
    fetcher = _fetcher(httpx2.MockTransport(lambda _: next(answers)), FakeClock())
    with pytest.raises(LookupFailed):
        fetcher(URL, {"q": "a"})
    assert fetcher(URL, {"q": "a"}) == "fine"
