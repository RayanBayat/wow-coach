"""Tests for the item sections of the status report: gear, bags, bank, mail, recipes."""

from wow_coach.report import format_status
from wow_coach.report_items import (
    bags_section,
    bank_section,
    gear_section,
    mail_section,
    recipes_section,
)
from wow_coach.report_values import Table

NOW = 1_000_000.0

LINEN: Table = {
    "name": "Linen Cloth",
    "count": 5,
    "quality": 1,
    "type": "Tradeskill",
    "subType": "Cloth",
    "sellPrice": 13,
    "itemLevel": 5,
}
JUNK: Table = {"name": "Rabbit's Foot", "count": 2, "quality": 0, "type": "Junk", "sellPrice": 4}
CLOAK: Table = {
    "name": "Frayed Cloak",
    "quality": 2,
    "itemLevel": 7,
    "equipSlot": "Back",
    "requiredLevel": 5,
    "stats": ["+1 Stamina"],
    "type": "Armor",
    "subType": "Cloth",
    "sellPrice": 30,
    "bound": True,
}
HEARTHSTONE: Table = {"name": "Hearthstone", "quality": 1, "noValue": True, "bound": True}

BAGS: Table = {
    "bags": {
        "free": 15,
        "total": 40,
        "containers": [
            {
                "bag": 0,
                "name": "Backpack",
                "slots": 16,
                "free": 12,
                "items": [LINEN, {**LINEN, "count": 3}, JUNK, HEARTHSTONE],
            },
            {"bag": 1, "slots": 6, "free": 5, "items": [CLOAK]},
        ],
    }
}


def test_bags_keep_the_old_summary_line() -> None:
    assert bags_section(BAGS).startswith("**Bags:** 15/40 slots free")


def test_bags_list_each_container() -> None:
    assert "Bags: Backpack 16 slots (12 free), bag 1 6 slots (5 free)" in bags_section(BAGS)


def test_stacks_of_one_item_are_added_up() -> None:
    assert "- Linen Cloth x8 (white, Tradeskill / Cloth, sells for 13c each)" in bags_section(BAGS)


def test_item_level_only_for_things_you_wear() -> None:
    text = bags_section(BAGS)
    assert "item level 5" not in text  # the cloth
    assert "- Frayed Cloak (item level 7, green, Back, needs level 5, +1 Stamina," in text


def test_junk_value_adds_up_the_gray_items() -> None:
    assert "Gray (junk) items sell for 8c in total" in bags_section(BAGS)


def test_no_value_and_soulbound_flags() -> None:
    assert "- Hearthstone (white, vendors won't buy it, soulbound)" in bags_section(BAGS)


def test_old_bags_without_containers_show_only_the_summary() -> None:
    assert bags_section({"bags": {"free": 3, "total": 16}}) == "**Bags:** 3/16 slots free"


def test_gear_shows_durability_and_stats() -> None:
    snapshot: Table = {
        "gear": [{**CLOAK, "slot": "Back", "durability": 20, "durabilityMax": 25}],
    }
    line = gear_section(snapshot).splitlines()[1]
    assert line == (
        "- Back: Frayed Cloak (item level 7, green, needs level 5, +1 Stamina, durability 20/25)"
    )


def test_old_gear_without_slot_still_shows_its_item_level() -> None:
    snapshot: Table = {"gear": [{"slot": "Head", "name": "Cap", "itemLevel": 9, "quality": 2}]}
    assert "- Head: Cap (item level 9, green)" in gear_section(snapshot)


def test_bank_seen_earlier_says_when() -> None:
    snapshot: Table = {
        "bank": {
            "seenAt": NOW - 2 * 3600,
            "containers": [
                {"name": "Bank Tab 1", "slots": 28, "free": 27, "items": [LINEN]},
                {"name": "Warband", "slots": 98, "free": 98, "account": True, "items": []},
            ],
        }
    }
    text = bank_section(snapshot, NOW)
    assert text.startswith(
        "**Bank** (seen 2 h ago): Bank Tab 1 28 slots (27 free), "
        "Warband [account bank] 98 slots (98 free)"
    )
    assert "- Linen Cloth x5" in text


def test_empty_bank_says_so() -> None:
    snapshot: Table = {"bank": {"seenAt": NOW, "containers": []}}
    assert bank_section(snapshot, NOW).endswith("- (empty)")


def test_bank_never_seen_explains_how_to_add_it() -> None:
    assert "open the bank once" in bank_section(BAGS, NOW)


def test_old_snapshot_has_no_bank_line() -> None:
    assert bank_section({"bags": {"free": 1, "total": 16}}, NOW) == ""


def test_mail_lists_each_letter() -> None:
    snapshot: Table = {
        "mail": {
            "seenAt": NOW - 60,
            "letters": [
                {
                    "sender": "Auction House",
                    "subject": "Auction successful",
                    "money": 1500,
                    "cod": 0,
                    "daysLeft": 29,
                    "items": [{"name": "Copper Ore", "count": 4}],
                }
            ],
        }
    }
    assert mail_section(snapshot, NOW) == (
        "**Mail** (seen 1 min ago): 1 letter\n"
        "- Auction successful (from Auction House, 15s attached, items: Copper Ore x4, "
        "29 days left)"
    )


def test_recipes_with_colors() -> None:
    snapshot: Table = {
        "recipes": [
            {
                "profession": "Tailoring",
                "rank": 23,
                "maxRank": 75,
                "seenAt": NOW - 600,
                "recipes": [
                    {"name": "Bolt of Linen Cloth", "color": "orange"},
                    {"name": "Linen Cloak"},
                ],
            }
        ]
    }
    lines = recipes_section(snapshot, NOW).splitlines()
    assert lines[0].startswith("**Recipes** (orange = sure skill-up")
    assert lines[1:] == [
        "- Tailoring 23/75, 2 recipes (seen 10 min ago):",
        "  - Bolt of Linen Cloth (orange)",
        "  - Linen Cloak",
    ]


def test_item_sections_tolerate_junk_data() -> None:
    snapshot: Table = {
        "bags": {"free": 1, "total": 2, "containers": [None, {"items": [None, {"count": "x"}]}]},
        "bank": {"containers": "nope"},
        "mail": {"letters": [None]},
        "recipes": [{"recipes": None}],
        "gear": [{"durability": "worn"}],
    }
    text = format_status(snapshot, now=NOW)
    assert "**Bags:** 1/2 slots free" in text
    assert "seen at an unknown time" in text
