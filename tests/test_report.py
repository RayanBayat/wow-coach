"""Tests for the pure Markdown formatting functions."""

import pytest

from wow_coach.report import (
    Table,
    format_age,
    format_history,
    format_money,
    format_status,
)

NOW = 1_000_000.0


@pytest.mark.parametrize(
    ("copper", "expected"),
    [
        (0, "0c"),
        (45, "45c"),
        (100, "1s"),
        (123, "1s 23c"),
        (12345, "1g 23s 45c"),
        (10_000, "1g"),
        (10_005, "1g 5c"),
        (5_000_000, "500g"),
    ],
)
def test_format_money(copper: int, expected: str) -> None:
    assert format_money(copper) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (-5, "just now"),
        (0, "just now"),
        (59, "just now"),
        (60, "1 min ago"),
        (300, "5 min ago"),
        (3599, "59 min ago"),
        (3600, "1 h ago"),
        (7300, "2 h ago"),
        (86_399, "23 h ago"),
        (86_400, "1 day ago"),
        (3 * 86_400 + 5, "3 days ago"),
    ],
)
def test_format_age(seconds: float, expected: str) -> None:
    assert format_age(seconds) == expected


FULL: Table = {
    "savedAt": NOW - 300,
    "reason": "coach",
    "name": "Testchar",
    "realm": "Realm",
    "race": "Undead",
    "class": "Mage",
    "level": 7,
    "xp": 250,
    "xpMax": 1000,
    "restedXP": 120,
    "money": 12345,
    "zone": "Tirisfal Glades",
    "subZone": "Brill",
    "x": 61.234,
    "y": 52.0,
    "hearth": "Brill",
    "bags": {"free": 10, "total": 16},
    "quests": [
        {"questID": 4001, "title": "Done Quest", "level": 5, "complete": True, "objectives": []},
        {
            "questID": 4002,
            "title": "Wolves",
            "level": 6,
            "complete": False,
            "objectives": [{"text": "3/8 Wolf Pelts", "done": False}],
        },
    ],
    "talents": {
        "unspent": 2,
        "trees": [{"name": "Fire", "spent": 3}, {"name": "Frost", "spent": 0}],
        "picked": [{"name": "Improved Fireball", "rank": 2, "maxRank": 5}],
    },
    "professions": [
        {"name": "Herbalism", "rank": 12, "maxRank": 75},
        {"name": "Language: Orcish", "rank": 1, "maxRank": 1},
    ],
    "gear": [
        {"slot": "Head", "name": "Cap", "itemLevel": 9, "quality": 2},
        {"slot": "Weapon", "name": "Staff", "itemLevel": 12, "quality": 5},
    ],
    "spells": ["Fireball", "Frostbolt"],
    "errors": ["talents: attempt to index nil"],
}


def test_full_status_contains_every_section() -> None:
    text = format_status(FULL, now=NOW)
    for expected in [
        "# Testchar: level 7 Undead Mage (Realm)",
        "Saved 5 min ago (coach)",
        "**XP:** 250/1000 (25%), rested XP 120",
        "**Gold:** 1g 23s 45c",
        "**Location:** Tirisfal Glades, Brill (61.2, 52.0)",
        "Hearth: Brill",
        "**Bags:** 10/16 slots free",
        "- [5] Done Quest (quest 4001), DONE (turn in)",
        "- [6] Wolves (quest 4002), 3/8 Wolf Pelts",
        "Unspent points: 2",
        "Points per tree: Fire 3, Frost 0",
        "Picked: Improved Fireball 2/5",
        "- Herbalism: 12/75",
        "- Head: Cap (item level 9, green)",
        "- Weapon: Staff (item level 12, orange)",
        "**Spells:** Fireball, Frostbolt",
        "**Addon read errors:**",
        "- talents: attempt to index nil",
    ]:
        assert expected in text
    assert "**Other skills:** Other: Language: Orcish" in text
    assert "stale" not in text


def test_stale_warning_after_30_minutes() -> None:
    text = format_status({"name": "A", "savedAt": NOW - 31 * 60}, now=NOW)
    assert "may be stale; type /coach in game to refresh" in text


def test_no_stale_warning_at_exactly_30_minutes() -> None:
    assert "stale" not in format_status({"name": "A", "savedAt": NOW - 30 * 60}, now=NOW)


@pytest.mark.parametrize(
    ("field", "empty", "missing_text"),
    [
        ("quests", [], "Quests"),
        ("quests", {}, "Quests"),
        ("talents", {}, "Talents"),
        ("professions", [], "Professions"),
        ("gear", {}, "Gear"),
        ("spells", [], "Spells"),
        ("errors", [], "errors"),
        ("bags", {}, "Bags"),
        ("money", None, "Gold"),
        ("xp", None, "XP"),
        ("zone", None, "Location"),
    ],
)
def test_empty_or_missing_sections_are_skipped(
    field: str, empty: object, missing_text: str
) -> None:
    snapshot: Table = {k: v for k, v in FULL.items() if k not in {"x", "y", "subZone", "hearth"}}
    snapshot[field] = empty  # type: ignore[assignment]
    if empty is None:
        del snapshot[field]
    assert missing_text not in format_status(snapshot, now=NOW)


def test_minimal_snapshot_does_not_crash() -> None:
    assert format_status({"name": "A", "savedAt": NOW}, now=NOW).startswith("# A")


def test_empty_snapshot_does_not_crash() -> None:
    assert "Unknown character" in format_status({}, now=NOW)


def test_only_low_rank_professions_hides_section() -> None:
    snapshot: Table = {"professions": [{"name": "Common", "rank": 1, "maxRank": 1}]}
    assert "Professions" not in format_status(snapshot, now=NOW)


def test_unknown_quality_and_nil_holes_are_tolerated() -> None:
    snapshot: Table = {"gear": [None, {"slot": "Back", "name": "Cloak", "quality": 9}]}
    assert "- Back: Cloak (quality 9)" in format_status(snapshot, now=NOW)


def test_quest_id_comes_first_among_the_tags() -> None:
    quest: Table = {"questID": 365, "title": "Fields of Grief", "zone": "Tirisfal Glades"}
    snapshot: Table = {"quests": [quest]}
    assert "- Fields of Grief (quest 365; Tirisfal Glades)" in format_status(snapshot, now=NOW)


def test_incomplete_quest_without_objectives() -> None:
    snapshot: Table = {"quests": [{"title": "Mystery", "level": 3}]}
    assert "- [3] Mystery" in format_status(snapshot, now=NOW)


def test_coordinates_without_zone() -> None:
    assert "(1.0, 2.0)" in format_status({"x": 1, "y": 2}, now=NOW)


HISTORY: list = [
    {"time": NOW - 7200, "text": "Reached level 6"},
    None,
    {"time": NOW - 300, "text": "Died in Brill"},
    {"time": NOW - 10, "kind": "login"},
]


def test_history_newest_first() -> None:
    assert format_history(HISTORY, limit=10, now=NOW).splitlines() == [
        "- just now: login",
        "- 5 min ago: Died in Brill",
        "- 2 h ago: Reached level 6",
    ]


def test_history_limit() -> None:
    assert len(format_history(HISTORY, limit=2, now=NOW).splitlines()) == 2


def test_history_empty() -> None:
    assert format_history([], limit=5, now=NOW) == "No history recorded yet."


def test_history_event_without_time() -> None:
    assert format_history([{"text": "Hello"}], limit=5, now=NOW) == "- unknown time: Hello"


# The skill list as the real game saved it on 2026-11-07 (each profession twice),
# plus the header ("category") each line sat under.
REAL_SKILLS: Table = {
    "professions": [
        {"name": "Frost", "rank": 1, "maxRank": 1, "category": "Class Skills"},
        {"name": "Mining", "rank": 3, "maxRank": 75, "category": "Professions"},
        {"name": "Mining", "rank": 3, "maxRank": 75, "category": "Professions"},
        {"name": "Tailoring", "rank": 1, "maxRank": 75, "category": "Professions"},
        {"name": "Tailoring", "rank": 1, "maxRank": 75, "category": "Professions"},
        {"name": "Cooking", "rank": 1, "maxRank": 75, "category": "Secondary Skills"},
        {"name": "Defense", "rank": 36, "maxRank": 40, "category": "Weapon Skills"},
        {"name": "Staves", "rank": 29, "maxRank": 40, "category": "Weapon Skills"},
        {"name": "Cloth", "rank": 1, "maxRank": 1, "category": "Armor Proficiencies"},
        {"name": "Language: Orcish", "rank": 300, "maxRank": 300, "category": "Languages"},
    ]
}


def test_professions_listed_once_each_with_secondary_skills() -> None:
    text = format_status(REAL_SKILLS, now=NOW)
    assert "**Professions:**\n- Mining: 3/75\n- Tailoring: 1/75\n- Cooking: 1/75" in text
    assert text.count("Mining") == 1


def test_weapon_skills_get_their_own_line() -> None:
    text = format_status(REAL_SKILLS, now=NOW)
    assert "**Weapon skills:** Defense 36/40, Staves 29/40" in text
    assert "- Defense" not in text


def test_languages_and_one_rank_skills_share_one_line() -> None:
    text = format_status(REAL_SKILLS, now=NOW)
    assert (
        "**Other skills:** Class Skills: Frost; Armor Proficiencies: Cloth; "
        "Languages: Language: Orcish 300/300"
    ) in text
    assert "- Language: Orcish" not in text  # not listed as a profession


def test_skill_with_unknown_category_counts_as_profession() -> None:
    snapshot: Table = {
        "professions": [{"name": "Lockpicking", "rank": 5, "maxRank": 75, "category": "Other"}]
    }
    assert "- Lockpicking: 5/75" in format_status(snapshot, now=NOW)


def test_only_weapon_skills_shows_no_professions_header() -> None:
    snapshot: Table = {
        "professions": [{"name": "Staves", "rank": 5, "maxRank": 40, "category": "Weapon Skills"}]
    }
    text = format_status(snapshot, now=NOW)
    assert "**Weapon skills:** Staves 5/40" in text
    assert "Professions" not in text


def test_old_snapshot_without_category_dedupes_by_name() -> None:
    snapshot: Table = {
        "professions": [
            {"name": "Mining", "rank": 3, "maxRank": 75},
            {"name": "Mining", "rank": 3, "maxRank": 75},
            {"name": "Defense", "rank": 36, "maxRank": 40},
        ]
    }
    text = format_status(snapshot, now=NOW)
    assert "**Professions:**\n- Mining: 3/75\n- Defense: 36/40" in text
    assert "Weapon skills" not in text


# A save the addon made after the game had unloaded the character (a real logout with
# addon 0.6.0 or older): level wrong, no XP needed, no gold, no bag slots.
UNLOADED_SAVE: Table = {
    "name": "Testchar",
    "level": 9,
    "savedAt": NOW - 60,
    "reason": "logout",
    "xp": 0,
    "xpMax": 0,
    "money": 0,
    "bags": {"free": 0, "total": 0},
}


def test_an_unloaded_save_gets_a_warning() -> None:
    text = format_status(UNLOADED_SAVE, now=NOW)
    assert "WARNING: this save is almost empty" in text
    assert "type /coach in game" in text


def test_a_max_level_character_needs_no_xp_and_is_not_unloaded() -> None:
    snapshot: Table = {"name": "Testchar", "level": 60, "xp": 0, "xpMax": 0, "savedAt": NOW}
    assert "almost empty" not in format_status(snapshot, now=NOW)


def test_a_kept_save_says_when_the_player_logged_out() -> None:
    snapshot: Table = {
        "name": "Testchar",
        "level": 7,
        "savedAt": NOW - 3600,
        "reason": "coach",
        "loggedOutAt": NOW - 600,
    }
    text = format_status(snapshot, now=NOW)
    assert "Logged out 10 min ago; this is the last full save, from before that." in text


def test_full_report_shows_gear_hints_after_the_bags() -> None:
    snapshot: Table = {
        **FULL,
        "professions": [
            {"name": "Cloth", "rank": 1, "maxRank": 1, "category": "Armor Proficiencies"}
        ],
        "bags": {
            "free": 10,
            "total": 16,
            "containers": [
                {
                    "bag": 0,
                    "items": [
                        {
                            "name": "Heavy Helm",
                            "type": "Armor",
                            "subType": "Plate",
                            "equipSlot": "Head",
                            "itemLevel": 9,
                        }
                    ],
                }
            ],
        },
    }
    text = format_status(snapshot, now=NOW)
    assert text.index("**Bags:**") < text.index("**Gear hints**")
    assert "Can't use: Heavy Helm" in text
