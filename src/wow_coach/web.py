"""A polite way to fetch web pages: identifies itself, caches answers and spaces requests out.

Why: the sites we read (the Warcraft Wiki) are run by volunteers and fans. We say who we are
in the ``User-Agent`` header, remember answers for an hour so repeated questions cost them
nothing, and never send more than about two requests per second to one site.
"""

import importlib.metadata
import threading
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

import httpx2

from wow_coach.errors import LookupFailed

# A fetch function takes a URL plus query parameters and returns the response body as text.
# Tests pass a fake one, so they never touch the network.
Fetch = Callable[[str, Mapping[str, str]], str]

DEFAULT_TTL_SECONDS = 3600.0
DEFAULT_MIN_INTERVAL_SECONDS = 0.5  # at most two requests per second per site
REQUEST_TIMEOUT_SECONDS = 10.0


def build_user_agent() -> str:
    """Text that tells a website who is asking, for example ``wow-coach/0.3.0 (+https://...)``."""
    version = importlib.metadata.version("wow-coach")
    return f"wow-coach/{version} (+https://github.com/RayanBayat/wow-coach)"


class PoliteFetcher:
    """Callable that fetches a URL with caching and a per-site rate limit."""

    def __init__(
        self,
        user_agent: str,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    ) -> None:
        """Create a fetcher.

        Args:
            user_agent: Text that tells the website who is asking.
            transport: Replaces the real network (tests only).
            clock: Returns the current time in seconds (replaced in tests).
            sleep: Waits for some seconds (replaced in tests).
            ttl_seconds: How long an answer stays in the cache.
            min_interval_seconds: Least time between two requests to the same site.
        """
        self._client = httpx2.Client(
            headers={"User-Agent": user_agent},
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=True,
        )
        self._clock = clock
        self._sleep = sleep
        self._ttl = ttl_seconds
        self._min_interval = min_interval_seconds
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, str]] = {}
        self._last_request: dict[str, float] = {}
        # One request at a time: simple, and it is the polite thing to do anyway.
        self._lock = threading.Lock()

    def __call__(self, url: str, params: Mapping[str, str]) -> str:
        """Return the body of ``url`` (cached if fresh). Raises ``LookupFailed`` on problems."""
        key = (url, tuple(sorted(params.items())))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and self._clock() - cached[0] < self._ttl:
                return cached[1]
            self._wait_for_turn(urlsplit(url).netloc)
            body = self._download(url, params)
            self._cache[key] = (self._clock(), body)
            return body

    def _wait_for_turn(self, site: str) -> None:
        """Sleep if the last request to this site was too recent, then note the new time."""
        last = self._last_request.get(site)
        if last is not None:
            wait = self._min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[site] = self._clock()

    def _download(self, url: str, params: Mapping[str, str]) -> str:
        try:
            response = self._client.get(url, params=dict(params))
            response.raise_for_status()
        except httpx2.TimeoutException as error:
            raise LookupFailed("timeout") from error
        except httpx2.HTTPStatusError as error:
            raise LookupFailed(f"HTTP {error.response.status_code}") from error
        except httpx2.TransportError as error:
            raise LookupFailed("network error") from error
        return response.text
