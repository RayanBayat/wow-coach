"""Look things up on the Warcraft Wiki (warcraft.wiki.gg) through its official MediaWiki API.

Two lookups, both returning short plain text that ends with a ``Source:`` line:

* ``answer_search_wiki``: find page titles for a question.
* ``answer_read_wiki_page``: read one page (or one section of it) as plain text.

The wiki's text is licensed CC BY-SA 4.0, so every answer carries the page link and the
license name. The network is reached only through the ``fetch`` argument, so tests pass a
fake one.
"""

import json
from urllib.parse import quote

from wow_coach.errors import LookupFailed
from wow_coach.web import Fetch
from wow_coach.wikitext import WikiPage, clean_snippet, find_section, parse_wikitext

WIKI_HOME = "https://warcraft.wiki.gg"
API_URL = f"{WIKI_HOME}/api.php"
SOURCE_LINE = f"Source: Warcraft Wiki ({WIKI_HOME}), CC BY-SA 4.0"
# Asks the wiki to refuse us when its servers are busy, instead of piling on (MediaWiki etiquette).
MAX_LAG_SECONDS = "5"
MAX_SEARCH_RESULTS = 10
# Sections with no text (References, External links) are not worth listing.
DEFAULT_MAX_CHARS = 6000


def page_url(title: str) -> str:
    """The web address of a wiki page, for example ``.../wiki/Camping_101:_Cooking``."""
    return f"{WIKI_HOME}/wiki/{quote(title.replace(' ', '_'), safe=':/(),!' + chr(39))}"


def _didnt_answer(reason: str) -> str:
    return f"Warcraft Wiki didn't answer ({reason}). Try again or use web search."


def _ask(fetch: Fetch, params: dict[str, str]) -> dict[str, object]:
    """Call the wiki API and return its JSON, or raise ``LookupFailed`` with a short reason."""
    body = fetch(API_URL, {**params, "format": "json", "maxlag": MAX_LAG_SECONDS})
    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise LookupFailed("unexpected reply") from error
    if not isinstance(data, dict):
        raise LookupFailed("unexpected reply")
    return data


def answer_search_wiki(query: str, limit: int, fetch: Fetch) -> str:
    """Text for the ``search_wiki`` tool: matching page titles, snippets and links."""
    if not query.strip():
        return "Give me something to search for."
    count = min(max(limit, 1), MAX_SEARCH_RESULTS)
    try:
        data = _ask(
            fetch,
            {"action": "query", "list": "search", "srsearch": query, "srlimit": str(count)},
        )
    except LookupFailed as error:
        return _didnt_answer(str(error))
    results = _search_results(data)
    if results is None:
        return _didnt_answer("unexpected reply")
    if not results:
        return f"No wiki pages found for {query!r}. Try other words or use web search."
    lines = [f"Warcraft Wiki results for {query!r}:"]
    for number, result in enumerate(results, start=1):
        title = str(result.get("title", ""))
        snippet = clean_snippet(str(result.get("snippet", "")))
        lines.append(f"{number}. {title}: {snippet}")
        lines.append(f"   {page_url(title)}")
    lines.append(SOURCE_LINE)
    return "\n".join(lines)


def _search_results(data: dict[str, object]) -> list[dict[str, object]] | None:
    """Dig the result list out of the API reply (None if the reply has another shape)."""
    query = data.get("query")
    if not isinstance(query, dict):
        return None
    results = query.get("search")
    if not isinstance(results, list):
        return None
    return [item for item in results if isinstance(item, dict)]


def answer_read_wiki_page(title: str, section: str | None, max_chars: int, fetch: Fetch) -> str:
    """Text for the ``read_wiki_page`` tool: a page (or one section) as plain text."""
    try:
        data = _ask(
            fetch,
            {
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "formatversion": "2",
                "redirects": "1",
            },
        )
    except LookupFailed as error:
        return _didnt_answer(str(error))
    error_info = data.get("error")
    if isinstance(error_info, dict):
        return _api_error_text(title, str(error_info.get("code", "")))
    parsed = data.get("parse")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("wikitext"), str):
        return _didnt_answer("unexpected reply")
    real_title = str(parsed.get("title", title))
    page = parse_wikitext(real_title, str(parsed["wikitext"]))
    if section:
        return _render_section(page, section, max_chars)
    return _render_page(page, max_chars)


def _api_error_text(title: str, code: str) -> str:
    if code == "missingtitle":
        return f"No page named {title!r}. Try search_wiki."
    if code == "maxlag":
        return _didnt_answer("busy")
    return _didnt_answer(f"error {code or 'unknown'}")


def _header(page: WikiPage) -> list[str]:
    return [f"# {page.title}", f"Page: {page_url(page.title)}"]


def _readable_section_names(page: WikiPage) -> list[str]:
    return [section.name for section in page.sections if section.text]


def _render_page(page: WikiPage, max_chars: int) -> str:
    lines = _header(page)
    lines.extend(f"Note: {note}" for note in page.notes)
    if page.infobox:
        lines.append("\n## Infobox")
        lines.extend(f"- {label}: {value}" for label, value in page.infobox)
    for section in page.sections:
        if not section.text:
            continue
        if section.level > 1:
            lines.append(f"\n{'#' * section.level} {section.name}")
        else:
            lines.append("")
        lines.append(section.text)
    body = "\n".join(lines)
    names = ", ".join(_readable_section_names(page))
    cut_note = f"Sections: {names}. Call again with section=NAME to read just one."
    return _finish(body, max_chars, cut_note)


def _render_section(page: WikiPage, wanted: str, max_chars: int) -> str:
    found = find_section(page, wanted)
    names = ", ".join(_readable_section_names(page))
    if found is None:
        return f"No section named {wanted!r} on {page.title!r}. Sections: {names}."
    lines = [*_header(page), *(f"Note: {note}" for note in page.notes)]
    lines.append(f"Section: {wanted.strip().title()}\n")
    lines.append(found)
    return _finish("\n".join(lines), max_chars, f"Other sections: {names}.")


def _finish(body: str, max_chars: int, cut_note: str) -> str:
    """Cut the text at a line break near ``max_chars`` and add the source line."""
    if len(body) > max_chars:
        cut = body[:max_chars].rsplit("\n", 1)[0]
        body = f"{cut}\n\n[Cut off at {max_chars} characters. {cut_note}]"
    return f"{body}\n\n{SOURCE_LINE}"
