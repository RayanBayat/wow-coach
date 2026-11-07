"""Tests for turning Warcraft Wiki wikitext into readable plain text."""

import json
from pathlib import Path

from wow_coach.wikitext import clean_snippet, find_section, parse_wikitext

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"


def _fixture_wikitext(name: str) -> str:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    wikitext: str = data["parse"]["wikitext"]
    return wikitext


def test_clean_snippet_removes_match_markup_and_decodes_entities() -> None:
    raw = (
        '<span class="searchmatch">Abigail</span> Shiel&#039;s &lt;Trade&gt;' + chr(0xA0) + "vendor"
    )
    assert clean_snippet(raw) == "Abigail Shiel's <Trade> vendor"


def test_clean_snippet_collapses_whitespace() -> None:
    assert clean_snippet("a \n  b\t c") == "a b c"


def test_coordinates_template_becomes_zone_and_numbers() -> None:
    page = parse_wikitext("T", "Found at {{co|61|52|Tirisfal Glades}}.")
    assert "Found at Tirisfal Glades 61, 52." in page.sections[0].text


def test_links_become_their_text() -> None:
    page = parse_wikitext("T", "See [[Brill]] and [[Tirisfal Glades|the glades]] now.")
    assert page.sections[0].text == "See Brill and the glades now."


def test_file_and_category_links_are_dropped() -> None:
    page = parse_wikitext("T", "Hi [[File:Silver.png|14px]] there\n[[Category:Foo]]")
    assert page.sections[0].text == "Hi there"


def test_external_links_keep_their_label() -> None:
    page = parse_wikitext("T", "See [https://example.com the site] now.")
    assert page.sections[0].text == "See the site now."


def test_references_comments_and_html_are_removed() -> None:
    wikitext = "A<ref>book</ref> B<ref name=x />C<!-- hidden -->D<br>E <b>bold</b>"
    assert parse_wikitext("T", wikitext).sections[0].text == "A BCD E bold"


def test_bold_and_italic_marks_are_removed() -> None:
    assert parse_wikitext("T", "'''Bold''' and ''italic''").sections[0].text == "Bold and italic"


def test_unknown_templates_are_dropped_including_nested_ones() -> None:
    page = parse_wikitext("T", "Before {{Reflist|{{inner}}}} after")
    assert page.sections[0].text == "Before after"


def test_cost_template_becomes_gold_silver_copper() -> None:
    text = parse_wikitext("T", "{{cost|||25}} {{cost||1|24}} {{cost|5|2|}}").sections[0].text
    assert text == "25c 1s 24c 5g 2s"


def test_quantity_and_version_markers() -> None:
    text = parse_wikitext("T", "{{qty|5}} {{cw}} {{fw}}").sections[0].text
    assert text == "5x [Classic] [Forever]"


def test_bullet_lists_are_kept_as_dashes() -> None:
    page = parse_wikitext("T", "*One\n** Two\n#Three")
    assert page.sections[0].text == "- One\n- Two\n- Three"


def test_headings_split_sections_with_levels() -> None:
    page = parse_wikitext("T", "Intro\n==Sells==\nstuff\n===Retail===\nmore\n==Notes==\nlast")
    assert [(s.name, s.level) for s in page.sections] == [
        ("Introduction", 1),
        ("Sells", 2),
        ("Retail", 3),
        ("Notes", 2),
    ]
    assert page.sections[1].text == "stuff"


def test_find_section_includes_subsections_and_ignores_case() -> None:
    page = parse_wikitext("T", "Intro\n==Sells==\nstuff\n===Retail===\nmore\n==Notes==\nlast")
    found = find_section(page, "sells")
    assert found is not None
    assert "stuff" in found
    assert "more" in found
    assert "last" not in found
    assert find_section(page, "nothing") is None


def test_table_becomes_pipe_separated_rows() -> None:
    wikitext = (
        '{| class="x"\n|+ Retail\n! !! Item !! Cost\n|-\n| || [[Salt]] || {{cost|||50}}\n'
        "|-\n| {{qty|5}} || [[Simple Flour]] || {{cost|||25}}\n|}"
    )
    text = parse_wikitext("T", wikitext).sections[0].text
    assert text.splitlines() == [
        "Retail:",
        "Item | Cost",
        "Salt | 50c",
        "5x | Simple Flour | 25c",
    ]


def test_table_cell_attributes_are_dropped() -> None:
    wikitext = '{|\n|-\n| style="color:red" | Red || Plain\n|}'
    assert parse_wikitext("T", wikitext).sections[0].text == "Red | Plain"


def test_infobox_fields_are_extracted_and_cleaned() -> None:
    wikitext = (
        "{{Npcbox\n| name = Abigail Shiel\n| image = A.jpg\n| title = Trade Supplies\n"
        "| location = [[Brill]], [[Tirisfal Glades]]{{co|61|52|Tirisfal Glades}}\n"
        "| aggro = {{Aggro|-1|1}}\n}}\nBody text."
    )
    page = parse_wikitext("T", wikitext)
    assert page.infobox == [
        ("Name", "Abigail Shiel"),
        ("Title", "Trade Supplies"),
        ("Location", "Brill, Tirisfal Glades 61, 52"),
    ]
    assert page.sections[0].text == "Body text."


def test_banner_template_adds_a_version_note() -> None:
    page = parse_wikitext("T", "{{Forever only|NPC}}\nText")
    assert page.notes == ["Marked Forever-only on the wiki."]
    assert page.sections[0].text == "Text"


def test_other_banners() -> None:
    assert parse_wikitext("T", "{{Classic only}}").notes == ["Marked Classic-only on the wiki."]
    assert parse_wikitext("T", "{{Retail only}}").notes == ["Marked Retail-only on the wiki."]


def test_real_vendor_page() -> None:
    page = parse_wikitext("Abigail Shiel", _fixture_wikitext("parse_Abigail_Shiel.json"))
    assert ("Title", "Trade Supplies") in page.infobox
    assert ("Location", "Brill, Tirisfal Glades 61, 52") in page.infobox
    sells = find_section(page, "Sells")
    assert sells is not None
    assert "Coarse Thread | 10c" in sells
    assert "[Forever]:" in sells
    assert "Apprentice's Mining Pack | 25c" in sells
    assert "<" not in sells
    assert "{{" not in sells


def test_real_forever_npc_page() -> None:
    page = parse_wikitext("William Pickman", _fixture_wikitext("parse_William_Pickman.json"))
    assert page.notes == ["Marked Forever-only on the wiki."]
    assert ("Title", "Cooking Trainer") in page.infobox
    quests = find_section(page, "Quests")
    assert quests is not None
    assert "Camping 101: Cooking" in quests


def test_real_quest_page_lists_givers_with_coordinates() -> None:
    page = parse_wikitext(
        "Camping 101: Cooking", _fixture_wikitext("parse_Camping_101_Cooking.json")
    )
    assert ("Level", "6") in page.infobox
    assert ("Experience", "270") in page.infobox
    notes = find_section(page, "Notes")
    assert notes is not None
    assert "Horde Eleanor Shackleton, Tirisfal Glades (Forever) 57.3, 55.5" in notes


def test_real_item_page_with_data_template() -> None:
    page = parse_wikitext("Small Brown Pouch", _fixture_wikitext("parse_Small_Brown_Pouch.json"))
    assert ("Quality", "common") in page.infobox
    assert ("Ilvl", "2") in page.infobox
    assert "world drop" in page.sections[0].text
