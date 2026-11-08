"""Tests for the list of sources an answer shows."""

import pytest

from wow_coach.engine.sources import MAX_SOURCES, SourceCollector, SourceLink, is_web_url


@pytest.mark.parametrize(
    "url",
    ["https://warcraft.wiki.gg/wiki/Abigail_Shiel", "http://example.com/a?b=1#c"],
)
def test_web_links_are_accepted(url: str) -> None:
    assert is_web_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "data:text/html,hi",
        "https://",
        "//example.com/x",
        "example.com",
        "https://exa mple.com/",
        "https://example.com/\nx",
        "",
        "https://example.com/" + "a" * 3000,
    ],
)
def test_other_links_are_refused(url: str) -> None:
    assert not is_web_url(url)


def test_pages_that_were_read_come_first_in_order_and_without_repeats() -> None:
    collector = SourceCollector()
    collector.add_read("Page A", "https://a.example/")
    collector.add_cited("https://b.example/x")
    collector.add_read("Page A again", "https://a.example/")  # same address: kept once
    collector.add_read("Page C", "https://c.example/")
    assert collector.links() == (
        SourceLink("Page A", "https://a.example/"),
        SourceLink("", "https://b.example/x"),
        SourceLink("Page C", "https://c.example/"),
    )


def test_listed_pages_count_only_when_nothing_was_read() -> None:
    collector = SourceCollector()
    collector.add_listed("Listed", "https://l.example/")
    assert collector.links() == (SourceLink("Listed", "https://l.example/"),)
    collector.add_read("Read", "https://r.example/")
    assert collector.links() == (SourceLink("Read", "https://r.example/"),)


def test_unsafe_links_never_get_in() -> None:
    collector = SourceCollector()
    collector.add_read("x", "javascript:alert(1)")
    collector.add_cited("file:///etc/passwd")
    collector.add_listed("y", "data:text/html,hi")
    assert collector.links() == ()


def test_at_most_eight_sources() -> None:
    collector = SourceCollector()
    for number in range(20):
        collector.add_cited(f"https://example.com/{number}")
    assert len(collector.links()) == MAX_SOURCES == 8
    assert collector.links()[0].url == "https://example.com/0"
