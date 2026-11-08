"""The sources shown under an answer: the web pages it really came from.

Rule: a source is never a link the AI wrote in its text. Only two things count, and both are
found by our own code:

* the pages the AI's built-in web search cited, and
* the Warcraft Wiki pages our tools actually read.

A search that only *listed* pages is a weaker source: it counts only when nothing was read.
Every link must be a plain ``http`` or ``https`` address, so a ``javascript:`` or ``file:``
link can never reach a button in the window.
"""

from dataclasses import dataclass, field
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_SOURCES: Final = 8
MAX_URL_CHARS: Final = 2_000
MAX_TITLE_CHARS: Final = 200


@dataclass(frozen=True, slots=True)
class SourceLink:
    """One source: where to read more. ``title`` may be empty (the window then shows the site)."""

    title: str
    url: str


def is_web_url(url: str) -> bool:
    """True for a plain ``http`` or ``https`` address with a host and no spaces or controls."""
    if not url or len(url) > MAX_URL_CHARS:
        return False
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host)


def without_tracking(url: str) -> str:
    """The address without tracking tags such as ``utm_source=openai`` (the page is the same)."""
    parts = urlsplit(url)
    kept = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")]  # fmt: skip
    return urlunsplit(parts._replace(query=urlencode(kept)))


@dataclass
class SourceCollector:
    """Collects sources while the coach works, then gives the final list."""

    _used: dict[str, str] = field(default_factory=dict)  # link -> title, in the order used
    _listed: dict[str, str] = field(default_factory=dict)

    def add_read(self, title: str, url: str) -> None:
        """A page a tool read, or the title of a page the web search cited."""
        self._add(self._used, title, url)

    def add_cited(self, url: str) -> None:
        """A page the web search cited (it has no title)."""
        self._add(self._used, "", url)

    def add_listed(self, title: str, url: str) -> None:
        """A page that only appeared in a list of search results."""
        self._add(self._listed, title, url)

    @staticmethod
    def _add(target: dict[str, str], title: str, url: str) -> None:
        if not is_web_url(url):
            return
        url = without_tracking(url)
        short = " ".join(title.split())[:MAX_TITLE_CHARS]
        if url not in target or (short and not target[url]):  # a title fills a missing one
            target[url] = short

    def links(self) -> tuple[SourceLink, ...]:
        """The sources to show: pages used, else pages listed; no repeats; at most eight."""
        chosen = self._used or self._listed
        return tuple(SourceLink(title, url) for url, title in chosen.items())[:MAX_SOURCES]
