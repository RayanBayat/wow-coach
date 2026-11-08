"""Tests for the item sections of the status report: gear, bags, bank, mail, recipes."""

from wow_coach.report import format_status
from wow_coach.report_gear_hints import gear_hints_section
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


# ---------------------------------------------------------------------------
# Gear hints (made-up mage, level 10)
# ---------------------------------------------------------------------------


def _bag_item(name: str, kind: str, sub_kind: str, slot: str, level: int, **extra: object) -> Table:
    item: Table = {
        "name": name,
        "type": kind,
        "subType": sub_kind,
        "equipSlot": slot,
        "itemLevel": level,
        "quality": 1,
        "requiredLevel": 1,
    }
    item.update(extra)  # type: ignore[arg-type]
    return item


def _mage(bag_items: list[Table], **changes: object) -> Table:
    """A level 10 mage who wears a staff, has no wand, and carries ``bag_items``."""
    snapshot: Table = {
        "level": 10,
        "professions": [
            {"name": "Staves", "rank": 5, "maxRank": 50, "category": "Weapon Skills"},
            {"name": "Wands", "rank": 5, "maxRank": 50, "category": "Weapon Skills"},
            {"name": "Cloth", "rank": 1, "maxRank": 1, "category": "Armor Proficiencies"},
        ],
        "gear": [
            {"slot": "Main hand", "name": "Worn Staff", "itemLevel": 5, "quality": 1},
            {"slot": "Back", "name": "Worn Cloak", "itemLevel": 8, "quality": 2},
            {"slot": "Waist", "name": "Worn Belt", "itemLevel": 9, "quality": 2},
            {"slot": "Ring 1", "name": "Worn Ring", "itemLevel": 9, "quality": 2},
            {"slot": "Ring 2", "name": "Worn Ring B", "itemLevel": 9, "quality": 2},
        ],
        "bags": {"containers": [{"bag": 0, "items": bag_items}]},
    }
    snapshot.update(changes)  # type: ignore[arg-type]
    return snapshot


MAIL_BELT = _bag_item("Clasped Belt", "Armor", "Mail", "Waist", 8)
PRACTICE_WAND = _bag_item("Practice Wand", "Weapon", "Wands", "Ranged", 6)


def test_armor_without_proficiency_is_flagged() -> None:
    text = gear_hints_section(_mage([MAIL_BELT]))
    assert text.startswith("**Gear hints**")
    assert "- Can't use: Clasped Belt (armor type Mail" in text


def test_weapon_without_skill_says_a_weapon_master_may_teach_it() -> None:
    axe = _bag_item("Rusty Axe", "Weapon", "One-Handed Axes", "One-Hand", 3)
    text = gear_hints_section(_mage([axe]))
    assert "Rusty Axe" in text
    assert "no Axes weapon skill" in text
    assert "weapon master" in text


def test_empty_wand_slot_is_a_possible_upgrade() -> None:
    text = gear_hints_section(_mage([PRACTICE_WAND]))
    assert (
        "- Possible upgrade: Practice Wand (item level 6) for the empty Ranged (wand) slot" in text
    )


def test_higher_item_level_is_a_possible_upgrade() -> None:
    staff = _bag_item("Fine Staff", "Weapon", "Staves", "Two-Hand", 9)
    text = gear_hints_section(_mage([staff]))
    assert "Fine Staff (item level 9) for Main hand: Worn Staff (item level 5)" in text


def test_lower_item_level_gives_no_hint() -> None:
    cloak = _bag_item("Battered Cloak", "Armor", "Cloth", "Back", 5)
    staff = _bag_item("Bent Staff", "Weapon", "Staves", "Two-Hand", 2)
    assert gear_hints_section(_mage([cloak, staff])) == ""


def test_miscellaneous_items_are_never_flagged() -> None:
    pick = _bag_item("Mining Pick", "Weapon", "Miscellaneous", "Main Hand", 4)
    ring = _bag_item("Plain Ring", "Armor", "Miscellaneous", "Finger", 3)
    assert gear_hints_section(_mage([pick, ring])) == ""


def test_gray_worn_item_is_replaced_by_a_better_quality_one() -> None:
    gray = {"slot": "Back", "name": "Rag", "itemLevel": 12, "quality": 0}
    cloak = _bag_item("Plain Cloak", "Armor", "Cloth", "Back", 3)
    text = gear_hints_section(_mage([cloak], gear=[gray]))
    assert "Plain Cloak (item level 3) for Back: Rag (item level 12, gray)" in text


def test_item_that_needs_a_higher_level_says_so() -> None:
    staff = _bag_item("Fine Staff", "Weapon", "Staves", "Two-Hand", 20, requiredLevel=14)
    assert "Fine Staff (item level 20, needs level 14)" in gear_hints_section(_mage([staff]))


def test_rings_are_compared_with_the_weaker_worn_ring() -> None:
    gear = [
        {"slot": "Ring 1", "name": "Good Ring", "itemLevel": 20, "quality": 2},
        {"slot": "Ring 2", "name": "Weak Ring", "itemLevel": 4, "quality": 2},
    ]
    ring = _bag_item("New Ring", "Armor", "Miscellaneous", "Finger", 9)
    text = gear_hints_section(_mage([ring], gear=gear))
    assert "New Ring (item level 9) for Ring 2: Weak Ring (item level 4)" in text


def test_missing_item_levels_make_no_upgrade_claim() -> None:
    worn = [{"slot": "Back", "name": "Worn Cloak", "quality": 2}]  # no item level
    cloak = _bag_item("Plain Cloak", "Armor", "Cloth", "Back", 30)
    assert gear_hints_section(_mage([cloak], gear=worn)) == ""


def test_no_proficiency_lines_means_no_check() -> None:
    old_save = _mage([MAIL_BELT], professions=[])
    assert gear_hints_section(old_save) == ""


def test_armor_check_skipped_when_only_weapon_skills_are_known() -> None:
    only_weapons = [{"name": "Staves", "rank": 5, "maxRank": 50, "category": "Weapon Skills"}]
    assert gear_hints_section(_mage([MAIL_BELT], professions=only_weapons)) == ""


def test_section_is_empty_without_bags() -> None:
    assert gear_hints_section({"level": 5}) == ""


def test_the_example_character_gets_exactly_two_hints() -> None:
    items = [
        MAIL_BELT,
        PRACTICE_WAND,
        _bag_item("Bent Staff", "Weapon", "Staves", "Two-Hand", 2),
        _bag_item("Mining Pick", "Weapon", "Miscellaneous", "Main Hand", 4),
        _bag_item("Battered Cloak", "Armor", "Cloth", "Back", 5),
    ]
    text = gear_hints_section(_mage(items))
    assert text.count("\n- ") == 2
    assert "Clasped Belt" in text and "Practice Wand" in text


def test_gear_hints_follow_the_bags_in_the_full_report() -> None:
    snapshot = {
        **_mage([PRACTICE_WAND]),
        "bags": {"free": 1, "total": 2, "containers": [{"bag": 0, "items": [PRACTICE_WAND]}]},
    }
    text = format_status(snapshot, now=NOW)
    assert text.index("**Bags:**") < text.index("**Gear hints**") < text.index("**Bank")
