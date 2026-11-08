"""Tests for the Warcraft Wiki lookups, using saved real responses instead of the network."""

import json
from collections.abc import Mapping
from pathlib import Path

from wow_coach.errors import LookupFailed
from wow_coach.web import Fetch
from wow_coach.wiki import answer_find_quest, answer_read_wiki_page, answer_search_wiki, page_url

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"


def _file(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetch:
    """Stands in for the network: returns one fixed body and remembers what was asked."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def __call__(self, url: str, params: Mapping[str, str]) -> str:
        self.calls.append((url, params))
        return self.body


def _failing_fetch(reason: str) -> Fetch:
    """A fetch that always fails the way a timed-out request would."""

    def fetch(_url: str, _params: Mapping[str, str]) -> str:
        raise LookupFailed(reason)

    return fetch


def test_page_url_uses_underscores_and_keeps_colons() -> None:
    assert page_url("Camping 101: Cooking") == "https://warcraft.wiki.gg/wiki/Camping_101:_Cooking"
    assert page_url("Gallows' End Tavern").endswith("Gallows'_End_Tavern")


def test_search_lists_titles_clean_snippets_and_urls() -> None:
    fetch = FakeFetch(_file("search_abigail.json"))
    text = answer_search_wiki("Abigail Shiel", 5, fetch)
    assert "1. Abigail Shiel: Abigail Shiel is a Forsaken trade supplies vendor" in text
    assert "https://warcraft.wiki.gg/wiki/Abigail_Shiel" in text
    assert "<span" not in text
    assert text.splitlines()[-1] == "Source: Warcraft Wiki (https://warcraft.wiki.gg), CC BY-SA 4.0"


def test_search_sends_the_query_limit_and_politeness_options() -> None:
    fetch = FakeFetch(_file("search_abigail.json"))
    answer_search_wiki("Abigail Shiel", 3, fetch)
    ((url, params),) = fetch.calls
    assert url == "https://warcraft.wiki.gg/api.php"
    assert params["srsearch"] == "Abigail Shiel"
    assert params["srlimit"] == "3"
    assert params["maxlag"] == "5"


def test_search_limit_is_kept_between_1_and_10() -> None:
    fetch = FakeFetch(_file("search_abigail.json"))
    answer_search_wiki("x", 99, fetch)
    answer_search_wiki("y", 0, fetch)
    assert [call[1]["srlimit"] for call in fetch.calls] == ["10", "1"]


def test_search_without_results() -> None:
    body = json.dumps({"query": {"search": []}})
    text = answer_search_wiki("zzzz", 5, FakeFetch(body))
    assert text.startswith("No wiki pages found for 'zzzz'.")


def test_search_with_blank_query() -> None:
    assert "Give me something to search for" in answer_search_wiki("  ", 5, FakeFetch(""))


def test_search_timeout_is_plain_text() -> None:
    text = answer_search_wiki("x", 5, _failing_fetch("timeout"))
    assert text == "Warcraft Wiki didn't answer (timeout). Try again or use web search."


def test_search_bad_reply_is_plain_text() -> None:
    text = answer_search_wiki("x", 5, FakeFetch("<html>oops</html>"))
    assert text.startswith("Warcraft Wiki didn't answer (unexpected reply).")


def test_read_page_shows_infobox_sections_and_source() -> None:
    fetch = FakeFetch(_file("parse_Abigail_Shiel.json"))
    text = answer_read_wiki_page("Abigail Shiel", None, 20_000, fetch)
    assert text.startswith("# Abigail Shiel\nPage: https://warcraft.wiki.gg/wiki/Abigail_Shiel")
    assert "- Title: Trade Supplies" in text
    assert "- Location: Brill, Tirisfal Glades 61, 52" in text
    assert "## Sells" in text
    assert "Coarse Thread | 10c" in text
    assert "[Forever]:" in text
    assert text.splitlines()[-1].startswith("Source: Warcraft Wiki (")
    assert "{{" not in text
    assert "References" not in text


def test_read_page_asks_for_redirects_and_wikitext() -> None:
    fetch = FakeFetch(_file("parse_Abigail_Shiel.json"))
    answer_read_wiki_page("abigail shiel", None, 6000, fetch)
    ((_, params),) = fetch.calls
    assert params["page"] == "abigail shiel"
    assert params["redirects"] == "1"
    assert params["prop"] == "wikitext"


def test_read_page_says_when_forever_only() -> None:
    text = answer_read_wiki_page(
        "William Pickman", None, 6000, FakeFetch(_file("parse_William_Pickman.json"))
    )
    assert "Marked Forever-only on the wiki." in text


def test_read_one_section() -> None:
    fetch = FakeFetch(_file("parse_Camping_101_Cooking.json"))
    text = answer_read_wiki_page("Camping 101: Cooking", "rewards", 6000, fetch)
    assert "270 XP" in text
    assert "Eleanor Shackleton" not in text
    assert "Section: Rewards" in text


def test_unknown_section_lists_the_real_ones() -> None:
    fetch = FakeFetch(_file("parse_Camping_101_Cooking.json"))
    text = answer_read_wiki_page("Camping 101: Cooking", "Loot", 6000, fetch)
    assert text.startswith("No section named 'Loot'")
    assert "Rewards" in text
    assert "Notes" in text


def test_long_page_is_cut_and_lists_sections() -> None:
    fetch = FakeFetch(_file("parse_Camping_101_Cooking.json"))
    text = answer_read_wiki_page("Camping 101: Cooking", None, 400, fetch)
    assert "Cut off at 400 characters" in text
    assert "Sections: " in text
    assert "Notes" in text


def test_missing_page_points_to_search() -> None:
    text = answer_read_wiki_page(
        "Nonexistent zzqq", None, 6000, FakeFetch(_file("parse_missing.json"))
    )
    assert text == "No page named 'Nonexistent zzqq'. Try search_wiki."


def test_read_page_timeout_is_plain_text() -> None:
    text = answer_read_wiki_page("X", None, 6000, _failing_fetch("timeout"))
    assert text == "Warcraft Wiki didn't answer (timeout). Try again or use web search."


def test_busy_wiki_is_reported() -> None:
    body = json.dumps({"error": {"code": "maxlag", "info": "waiting for a database server"}})
    text = answer_read_wiki_page("X", None, 6000, FakeFetch(body))
    assert text.startswith("Warcraft Wiki didn't answer (busy).")


def test_find_quest_names_the_page_whose_infobox_id_matched() -> None:
    fetch = FakeFetch(_file("search_quest_365.json"))
    text = answer_find_quest(365, fetch)
    assert "Quest 365" in text
    assert "1. Fields of Grief (Classic): the infobox id matched." in text
    assert "https://warcraft.wiki.gg/wiki/Fields_of_Grief_(Classic)" in text
    assert text.splitlines()[-1].startswith("Source: Warcraft Wiki (")


def test_find_quest_searches_the_quest_infobox_id_field() -> None:
    fetch = FakeFetch(_file("search_quest_365.json"))
    answer_find_quest(365, fetch)
    ((url, params),) = fetch.calls
    assert url == "https://warcraft.wiki.gg/api.php"
    assert params["list"] == "search"
    assert params["srsearch"] == 'insource:"id = 365" insource:Questbox'
    assert params["maxlag"] == "5"


def test_find_quest_lists_every_page_when_several_match() -> None:
    body = json.dumps(
        {
            "query": {
                "search": [
                    {"title": "Quest A", "snippet": '| <span class="searchmatch">id</span> = 7'},
                    {"title": "Quest B (Classic)", "snippet": "id = 7 and more text"},
                    {"title": "Other", "snippet": "mentions the number 7 only"},
                ]
            }
        }
    )
    text = answer_find_quest(7, FakeFetch(body))
    assert "1. Quest A: the infobox id matched." in text
    assert "2. Quest B (Classic): the infobox id matched." in text
    assert "3. Other: the id was not visible in the match; read the page to check." in text
    assert "More than one page" in text


def test_find_quest_with_no_match_says_so_without_guessing() -> None:
    text = answer_find_quest(987654, FakeFetch(_file("search_quest_none.json")))
    assert text.startswith("No quest page with infobox id 987654")
    assert "search_wiki" in text


def test_find_quest_timeout_is_plain_text() -> None:
    text = answer_find_quest(365, _failing_fetch("timeout"))
    assert text == "Warcraft Wiki didn't answer (timeout). Try again or use web search."


class RoutedFetch:
    """Answers each API action from its own saved body (``parse`` and ``expandtemplates``)."""

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies
        self.calls: list[Mapping[str, str]] = []

    def __call__(self, _url: str, params: Mapping[str, str]) -> str:
        self.calls.append(params)
        return self.bodies[params["action"]]


def _comprehend_scroll_fetch(expansion_body: str) -> RoutedFetch:
    return RoutedFetch(
        {"parse": _file("parse_Comprehend_Scroll.json"), "expandtemplates": expansion_body}
    )


def test_included_lists_are_filled_in_by_one_expandtemplates_request() -> None:
    fetch = _comprehend_scroll_fetch(_file("expandtemplates_scroll.json"))
    text = answer_read_wiki_page("Comprehend Scroll", None, 20_000, fetch)
    assert "- Scroll of Strength" in text
    assert "- Scroll of Reintegration" in text
    assert "[SoD Mage Scroll" not in text
    expand_calls = [call for call in fetch.calls if call["action"] == "expandtemplates"]
    assert len(expand_calls) == 1
    assert expand_calls[0]["maxlag"] == "5"
    assert "{{SoD Mage Scroll 10}}" in expand_calls[0]["text"]


def test_failed_expansion_leaves_the_template_name_in_brackets() -> None:
    fetch = _comprehend_scroll_fetch("not json")
    text = answer_read_wiki_page("Comprehend Scroll", None, 20_000, fetch)
    assert "[SoD Mage Scroll 10]" in text
    assert "Enciphered scrolls" in text


def test_expansion_with_the_wrong_number_of_pieces_is_ignored() -> None:
    body = json.dumps({"expandtemplates": {"wikitext": "just one piece"}})
    text = answer_read_wiki_page("Comprehend Scroll", None, 20_000, _comprehend_scroll_fetch(body))
    assert "[SoD Mage Scroll 10]" in text


def test_pages_without_unknown_templates_make_no_expansion_request() -> None:
    fetch = FakeFetch(_file("parse_Library_book.json"))
    text = answer_read_wiki_page("Library book", None, 20_000, fetch)
    assert "in Season of Discovery and Forever." in text
    assert [params["action"] for _, params in fetch.calls] == ["parse"]
