"""Turn Warcraft Wiki "wikitext" (the wiki's source markup) into readable plain text.

The wiki is MediaWiki. A page's source looks like::

    {{Npcbox | name = Abigail Shiel | location = [[Brill]]{{co|61|52|Tirisfal Glades}} }}
    '''Abigail Shiel''' is a [[vendor]].
    ==Sells==
    {| ... a table ... |}

Everything here is pure text in, text out (no network), so it is easy to test. We do not try
to be a full MediaWiki parser. We handle the parts that matter for coaching (info boxes,
coordinates, prices, tables, sections, version labels) and drop the rest.
"""

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass

# Info-box templates hold the key facts (name, level, location). They are named ``Npcbox``,
# ``Questbox`` and so on, or ``#data:Itemtip`` for items.
INFOBOX_NAME = re.compile(r"(?i)^(#data:itemtip|[a-z ]*box)$")
# Fields that are not useful to read as text.
SKIPPED_INFOBOX_FIELDS = {"image", "icon", "aggro", "sellprice", "itemid"}
# Banner templates at the top of a page, and the version they mark.
BANNERS = {"forever only": "Forever", "classic only": "Classic", "retail only": "Retail"}
# Short templates that stand for a game version in tables and lists.
VERSION_LABELS = {
    "cw": "[Classic]",
    "fw": "[Forever]",
    "rw": "[Retail]",
    "sod-inline": "[SoD]",
    "forever-inline": "[Forever]",
}
# ``{{g|key}}`` prints a game name. These are the keys seen on Forever-related pages; the full
# list lives in Template:Game on the wiki. An unlisted key is printed as it was written.
GAME_NAMES = {
    "forever": "Forever",
    "wowf": "Forever",
    "sod": "Season of Discovery",
    "som": "Season of Mastery",
    "hardcore": "Classic Hardcore",
    "hc": "Classic Hardcore",
    "classic": "Classic",
    "era": "Classic",
    "cera": "Classic",
    "classic era": "Classic",
    "wowc": "Classic",
    "retail": "Midnight",
    "mid": "Midnight",
    "midnight": "Midnight",
    "tww": "The War Within",
    "df": "Dragonflight",
    "sl": "Shadowlands",
    "bfa": "Battle for Azeroth",
    "legion": "Legion",
    "wod": "Warlords of Draenor",
    "mop": "Mists of Pandaria",
    "cata": "Cataclysm",
    "wotlk": "Wrath of the Lich King",
    "wrath": "Wrath of the Lich King",
    "tbc": "The Burning Crusade",
    "bc": "The Burning Crusade",
    "vanilla": "World of Warcraft",
    "wow": "World of Warcraft",
    "mopc": "Mists of Pandaria Classic",
    "catac": "Cataclysm Classic",
    "wotlkc": "Wrath of the Lich King Classic",
    "wrathc": "Wrath of the Lich King Classic",
    "bcc": "Burning Crusade Classic",
}
# Templates that are page furniture, not content: navigation boxes, link lists, references,
# banners about patches or seasons. An unknown template is dropped instead of being shown in
# brackets when its name contains one of NOISE_PARTS anywhere ("Classfooter"), or one of the
# short NOISE_WORDS as a whole word ("Main" yes, "Domain" no).
NOISE_PARTS = (
    "footer",
    "navbox",
    "elinks",
    "reflist",
    "references",
    "documentation",
    "patchbranch",
    "defaultsort",
    "sidebar",
    "hatnote",
    "see also",
)
NOISE_WORDS = ("nav", "season", "stub", "main")
# Plain words some templates stand for.
WORD_TEMPLATES = {"alliance": "Alliance", "horde": "Horde", "questfinish": "(turn-in)"}

# ``{{C|Zone}}{{Co|x|y|Zone}}`` would print the zone twice. ``{{co}}`` puts this marker in front
# of its zone so ``_merge_repeated_zone`` can remove the repeat afterwards.
ZONE_MARK = "\x01"
REPEATED_ZONE = re.compile(r"([^,\n\x01]*?)\x01\1")

INNERMOST_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
REFERENCE = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")
INTERNAL_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[https?://\S+\s+([^\]]*)\]|\[https?://\S+\]")
LIST_MARK = re.compile(r"^[*#:;]+\s*")
INTRO_NAME = "Introduction"


@dataclass(frozen=True)
class WikiSection:
    """One part of a page: its heading name, heading level (1 = intro, 2 = ``==``) and text."""

    name: str
    level: int
    text: str


@dataclass(frozen=True)
class WikiPage:
    """A parsed wiki page.

    Attributes:
        title: The page title.
        notes: Version warnings, for example "Marked Forever-only on the wiki.".
        infobox: ``(label, value)`` pairs from the page's info box.
        sections: The page body in order. The first one is the intro.
    """

    title: str
    notes: list[str]
    infobox: list[tuple[str, str]]
    sections: list[WikiSection]


def clean_snippet(raw: str) -> str:
    """Turn a search-result snippet (HTML with match highlights) into one plain line."""
    without_tags = HTML_TAG.sub("", raw)
    return " ".join(html.unescape(without_tags).split())


def _split_arguments(body: str) -> list[str]:
    """Split a template body on ``|``, ignoring bars inside ``[[links]]`` and ``{{templates}}``."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(body):
        two = body[index : index + 2]
        if two in ("[[", "{{"):
            depth += 1
            current.append(two)
            index += 2
        elif two in ("]]", "}}") and depth > 0:
            depth -= 1
            current.append(two)
            index += 2
        elif body[index] == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            index += 1
        else:
            current.append(body[index])
            index += 1
    parts.append("".join(current))
    return parts


def _money(arguments: list[str]) -> str:
    """Render ``{{cost|gold|silver|copper}}`` (empty parts are left out)."""
    units = ("g", "s", "c")
    padded = [*arguments, "", "", ""][:3]
    # ``{{cost|||25}}`` has three slots with only copper filled, so the slot order is fixed.
    pieces = [
        f"{value.strip()}{unit}" for value, unit in zip(padded, units, strict=True) if value.strip()
    ]
    return " ".join(pieces)


def _known_expansion(name: str, parts: list[str]) -> str | None:
    """Return the text of a template we understand, or None when we do not know it."""
    arguments = [part.strip() for part in parts[1:]]
    if name == "co" and len(arguments) >= 3:
        return f"{ZONE_MARK}{arguments[2]} {arguments[0]}, {arguments[1]}"
    if name in ("c", "f") and arguments:
        return arguments[0]
    if name == "g":
        key = arguments[0] if arguments else ""
        return GAME_NAMES.get(key.lower(), key)
    if name == "cost":
        return _money(parts[1:])
    if name == "qty" and arguments:
        return f"{arguments[0]}x"
    if name == "ware" and arguments:
        return f"({arguments[0]})"
    if name in VERSION_LABELS:
        return VERSION_LABELS[name]
    if name in WORD_TEMPLATES:
        return WORD_TEMPLATES[name]
    if name.startswith("patch "):
        notes = [a.removeprefix("note=") for a in arguments if a.startswith("note=")]
        return f"{parts[0].strip()}: {' '.join(notes)}" if notes else parts[0].strip()
    return None


def _is_noise(name: str) -> bool:
    """True for templates that are page furniture (see ``NOISE_PARTS``) or parser functions."""
    if name.startswith("#") or any(part in name for part in NOISE_PARTS):
        return True
    return any(re.search(rf"\b{re.escape(word)}\b", name) for word in NOISE_WORDS)


def _last_plain_argument(parts: list[str]) -> str:
    """The last argument without ``name=``, or an empty string when there is none."""
    plain = [part.strip() for part in parts[1:] if "=" not in part and part.strip()]
    return plain[-1] if plain else ""


def _expand_template(body: str) -> str:
    """Return the plain text a single (already flattened) template stands for.

    Unknown templates should not make text vanish: they leave their last plain argument,
    or their name in brackets, so the reader can see that something was there.
    """
    parts = _split_arguments(body)
    name = parts[0].strip().lower()
    known = _known_expansion(name, parts)
    if known is not None:
        return known
    if _is_noise(name):
        return ""
    return _last_plain_argument(parts) or f"[{parts[0].strip()}]"


def find_unresolved_templates(text: str) -> list[str]:
    """List the templates that would show up as ``[Name]``: the wiki can expand these.

    Only outermost templates are considered, each listed once, in page order. Banners and
    info boxes are skipped because the parser reads those itself.
    """
    found: list[str] = []
    for start, end in _find_top_level_templates(text):
        source = text[start:end]
        parts = _split_arguments(source[2:-2])
        name = parts[0].strip().lower()
        if _known_expansion(name, parts) is not None or _is_noise(name):
            continue
        if name in BANNERS or INFOBOX_NAME.match(name) or _last_plain_argument(parts):
            continue
        if source not in found:
            found.append(source)
    return found


def _expand_templates(text: str) -> str:
    """Replace templates from the inside out until none are left."""
    previous = None
    while previous != text:
        previous = text
        text = INNERMOST_TEMPLATE.sub(lambda match: _expand_template(match.group(1)), text)
    return text


def _merge_repeated_zone(text: str) -> str:
    """Remove a zone name that a ``{{C}}`` and a ``{{Co}}`` template both printed."""
    return REPEATED_ZONE.sub(r"\1", text).replace(ZONE_MARK, "")


def _clean_inline(text: str) -> str:
    """Clean links, markup and HTML in a piece of text (templates must already be gone)."""

    def link_text(match: re.Match[str]) -> str:
        target, _, label = match.group(1).partition("|")
        if re.match(r"(?i)^(file|image|category):", target.strip()):
            return ""
        return (label.rsplit("|", 1)[-1] if label else target).strip()

    text = INTERNAL_LINK.sub(link_text, text)
    text = EXTERNAL_LINK.sub(lambda match: match.group(1) or "", text)
    text = HTML_TAG.sub("", text.replace("<br>", " ").replace("<br />", " "))
    text = text.replace("'''", "").replace("''", "").replace("__NOTOC__", "")
    return _merge_repeated_zone(html.unescape(text))


def _find_top_level_templates(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` of each template that is not inside another template."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = 0
    index = 0
    while index < len(text) - 1:
        two = text[index : index + 2]
        if two == "{{":
            if depth == 0:
                start = index
            depth += 1
            index += 2
        elif two == "}}" and depth > 0:
            depth -= 1
            index += 2
            if depth == 0:
                spans.append((start, index))
        else:
            index += 1
    return spans


def _extract_leading_templates(text: str) -> tuple[str, list[str], list[tuple[str, str]]]:
    """Pull banners and info boxes out of the top of the page.

    Returns the remaining text, version notes and info-box fields. Only templates before
    the first heading are considered, which is where the wiki puts them.
    """
    first_heading = re.search(r"(?m)^=", text)
    limit = first_heading.start() if first_heading else len(text)
    notes: list[str] = []
    fields: list[tuple[str, str]] = []
    removals: list[tuple[int, int]] = []
    for start, end in _find_top_level_templates(text):
        if start >= limit:
            break
        body = text[start + 2 : end - 2]
        name = _split_arguments(body)[0].strip()
        if name.lower() in BANNERS:
            notes.append(f"Marked {BANNERS[name.lower()]}-only on the wiki.")
            removals.append((start, end))
        elif INFOBOX_NAME.match(name):
            fields.extend(_infobox_fields(body))
            removals.append((start, end))
    for start, end in reversed(removals):
        text = text[:start] + text[end:]
    return text, notes, fields


def _infobox_fields(body: str) -> list[tuple[str, str]]:
    """Read ``key = value`` arguments of an info box as cleaned ``(Label, value)`` pairs."""
    fields: list[tuple[str, str]] = []
    for argument in _split_arguments(body)[1:]:
        key, equals, value = argument.partition("=")
        key = key.strip().lower()
        if not equals or not key or key in SKIPPED_INFOBOX_FIELDS:
            continue
        cleaned = " ".join(_clean_inline(_expand_templates(value)).split())
        if cleaned:
            fields.append((key.capitalize(), cleaned))
    return fields


def _table_to_text(lines: list[str]) -> list[str]:
    """Turn the lines of one wikitext table into ``a | b | c`` rows (caption first)."""
    output: list[str] = []
    row: list[str] = []

    def finish_row() -> None:
        cells = [cell for cell in row if cell]
        if cells:
            output.append(" | ".join(cells))
        row.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|+"):
            caption = " ".join(stripped[2:].split())
            if caption:
                output.append(f"{caption}:")
        elif stripped.startswith("|-"):
            finish_row()
        elif stripped[:1] in ("|", "!"):
            for cell in re.split(r"\|\||!!", stripped[1:]):
                row.append(_clean_cell(cell))
    finish_row()
    return output


def _clean_cell(cell: str) -> str:
    """Drop ``style="..." |`` attributes from a table cell and tidy the spaces."""
    text = _clean_inline(cell)
    if "|" in text and "=" in text.split("|", 1)[0]:
        text = text.split("|", 1)[1]
    return " ".join(text.split())


def _convert_body(text: str) -> list[str]:
    """Turn body lines (tables, lists, paragraphs) into clean lines of plain text."""
    output: list[str] = []
    table: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.lstrip().startswith("{|"):
            table = []
        elif table is not None and line.lstrip().startswith("|}"):
            output.extend(_table_to_text(table))
            table = None
        elif table is not None:
            table.append(line)
        else:
            output.append(_convert_line(line))
    return output


def _convert_line(line: str) -> str:
    """Clean one ordinary line; list marks become ``- ``."""
    is_list_item = line[:1] in ("*", "#", ":", ";")
    cleaned = " ".join(_clean_inline(LIST_MARK.sub("", line)).split())
    if is_list_item and cleaned:
        return f"- {cleaned}"
    return cleaned


def _tidy_blank_lines(lines: list[str]) -> str:
    """Join lines, keeping at most one blank line in a row and none at the ends."""
    result: list[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return "\n".join(result).strip()


def parse_wikitext(
    title: str, wikitext: str, expansions: Mapping[str, str] | None = None
) -> WikiPage:
    """Parse a page's source into notes, info box fields and plain-text sections.

    ``expansions`` maps a template's source text to what the wiki expanded it into (see
    ``find_unresolved_templates``). Those templates are replaced before anything else.
    """
    text = REFERENCE.sub("", COMMENT.sub("", wikitext))
    for source, expanded in (expansions or {}).items():
        text = text.replace(source, expanded)
    text, notes, infobox = _extract_leading_templates(text)
    text = _expand_templates(text)
    sections: list[WikiSection] = []
    name, level = INTRO_NAME, 1
    buffer: list[str] = []

    def close_section() -> None:
        body = _tidy_blank_lines(_convert_body("\n".join(buffer)))
        if body or sections:
            sections.append(WikiSection(name, level, body))

    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            close_section()
            name = " ".join(_clean_inline(heading.group(2)).split())
            level = len(heading.group(1))
            buffer = []
        else:
            buffer.append(line)
    close_section()
    if not sections:
        sections.append(WikiSection(INTRO_NAME, 1, ""))
    return WikiPage(title=title, notes=notes, infobox=infobox, sections=sections)


def find_section(page: WikiPage, wanted: str) -> str | None:
    """Return the text of the section called ``wanted`` (case-insensitive), with its subsections.

    The text starts with the section heading. Returns None when there is no such section.
    """
    target = wanted.strip().lower()
    for index, section in enumerate(page.sections):
        if section.name.lower() != target:
            continue
        pieces = [section.text]
        for later in page.sections[index + 1 :]:
            if later.level <= section.level:
                break
            pieces.append(f"{'#' * later.level} {later.name}\n{later.text}")
        return "\n\n".join(piece for piece in pieces if piece)
    return None
