"""Tests for the other sections of the status report: stats, buffs, spells, Legacy..."""

import pytest

from wow_coach.report import format_status
from wow_coach.report_details import (
    action_bars_section,
    auras_section,
    character_section,
    currencies_section,
    group_section,
    legacy_section,
    mounts_section,
    reputation_section,
    spells_section,
    stats_section,
)
from wow_coach.report_values import Table, format_time_span

NOW = 1_000_000.0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (40, "40 s"),
        (25 * 60, "25 min"),
        (4 * 3600 + 600, "4 h 10 min"),
        (2 * 86400 + 3 * 3600, "2 d 3 h"),
    ],
)
def test_format_time_span(seconds: float, expected: str) -> None:
    assert format_time_span(seconds) == expected


def test_character_section() -> None:
    snapshot: Table = {
        "faction": "Horde",
        "guild": {"name": "Brill Knitting Club", "rank": "Member"},
        "resting": True,
        "timePlayed": {"total": 7200, "thisLevel": 1800, "seenAt": NOW - 600},
        "achievementPoints": 10,
    }
    assert character_section(snapshot, NOW).splitlines() == [
        "**Faction:** Horde",
        "**Guild:** Brill Knitting Club (rank Member)",
        "**Resting:** yes (in an inn or a city, rested XP builds up)",
        "**Time played:** 2 h 0 min (this level 30 min, from /played 10 min ago)",
        "**Achievement points:** 10",
    ]


STATS: Table = {
    "stats": {
        "health": 150,
        "healthMax": 180,
        "power": 300,
        "powerMax": 345,
        "powerType": "MANA",
        "attributes": [{"name": "Stamina", "value": 23}, {"name": "Intellect", "value": 31}],
        "armor": 45,
        "resistances": [{"school": "Fire", "value": 0}, {"school": "Shadow", "value": 10}],
        "spellDamage": [{"school": "Fire", "value": 0}, {"school": "Frost", "value": 0}],
        "spellCrit": 1.6,
        "dodge": 4.25,
        "attackPower": 10,
        "manaRegen": 2.5,
        "manaRegenCasting": 0,
    }
}


def test_stats_section() -> None:
    assert stats_section(STATS).splitlines() == [
        "**Stats:**",
        "- Health: 150/180",
        "- Mana: 300/345",
        "- Stamina 23, Intellect 31",
        "- Armor: 45",
        "- Resistances: Shadow 10",
        "- Spell damage bonus: 0 (all schools)",
        "- spell crit 1.6%, dodge 4.2%, attack power 10",
        "- Mana regen per 5 s: 12.5 (while casting: 0)",
    ]


def test_different_spell_damage_per_school_is_listed() -> None:
    snapshot: Table = {
        "stats": {"spellDamage": [{"school": "Fire", "value": 5}, {"school": "Frost", "value": 0}]}
    }
    assert "- Spell damage bonus: Fire 5, Frost 0" in stats_section(snapshot)


def test_auras_section() -> None:
    snapshot: Table = {
        "auras": [
            {"name": "Arcane Intellect", "kind": "buff", "seconds": 1500},
            {"name": "Cozy Fire", "kind": "buff"},
            {"name": "Poison", "kind": "debuff", "stacks": 3, "seconds": 9},
        ]
    }
    assert auras_section(snapshot).splitlines()[1:] == [
        "- Arcane Intellect (buff, 25 min left)",
        "- Cozy Fire (buff)",
        "- Poison (debuff, 3 stacks, 9 s left)",
    ]


def test_spellbook_by_tab_with_ranks_and_passives() -> None:
    snapshot: Table = {
        "spells": ["Frostbolt", "Fireball"],
        "spellBook": [
            {"tab": "Frost", "name": "Frostbolt", "rank": "Rank 2"},
            {"tab": "Fire", "name": "Fireball"},
            {"tab": "General", "name": "Shadow Resistance", "passive": True},
        ],
    }
    assert spells_section(snapshot).splitlines() == [
        "**Spells:**",
        "- Frost: Frostbolt (Rank 2)",
        "- Fire: Fireball",
        "- Passive: Shadow Resistance",
    ]


def test_old_snapshot_spells_stay_one_line() -> None:
    assert (
        spells_section({"spells": ["Fireball", "Frostbolt"]}) == "**Spells:** Fireball, Frostbolt"
    )


def test_action_bars_are_numbered_per_bar() -> None:
    snapshot: Table = {
        "actionBars": [
            {"slot": 1, "name": "Frostbolt"},
            {"slot": 12, "name": "Hearthstone"},
            {"slot": 61, "name": "Sell Grays"},
        ]
    }
    assert action_bars_section(snapshot).splitlines()[1:] == [
        "- Main bar: 1 Frostbolt, 12 Hearthstone",
        "- Slots 61-72: 1 Sell Grays",
    ]


def test_reputation_section() -> None:
    snapshot: Table = {
        "reputations": [
            {"name": "Undercity", "standing": "Friendly", "value": 500, "max": 6000},
            {"name": "Scarlet Crusade", "standing": "Hated", "atWar": True},
            {"name": "Other", "collapsed": True},
        ]
    }
    assert reputation_section(snapshot).splitlines()[1:] == [
        "- Undercity: Friendly 500/6000",
        "- Scarlet Crusade: Hated (at war)",
        "- Other: collapsed in the reputation window, so not read",
    ]


def test_currencies_section() -> None:
    snapshot: Table = {"currencies": [{"name": "Legacy Token", "quantity": 3}]}
    assert currencies_section(snapshot) == "**Currencies:** Legacy Token 3"


def test_legacy_section() -> None:
    snapshot: Table = {
        "legacy": {
            "renown": 2,
            "points": 1,
            "perks": [{"tree": "Adventure", "name": "Quick Learner", "rank": 1, "maxRank": 1}],
            "challenges": [
                {
                    "name": "Untouchable",
                    "done": False,
                    "description": "Reach level 25 without dying.",
                },
                {"name": "Arcane Student", "done": True},
            ],
        }
    }
    assert legacy_section(snapshot).splitlines()[1:] == [
        "- reward track level 2, 1 Legacy points to spend",
        "- Perks: Quick Learner (Adventure, 1/1)",
        "- [ ] Untouchable: Reach level 25 without dying.",
        "- [x] Arcane Student",
    ]


def test_group_and_pet() -> None:
    snapshot: Table = {
        "group": {"kind": "party", "members": [{"name": "Ally", "level": 8, "class": "Priest"}]},
        "pet": {"name": "Wolfie", "level": 7, "family": "Wolf"},
    }
    assert group_section(snapshot).splitlines() == [
        "**Group:** party: Ally (level 8 Priest)",
        "**Pet:** Wolfie, level 7 Wolf",
    ]


def test_mounts_section() -> None:
    assert mounts_section({"mounts": ["Skeletal Horse"]}) == "**Mounts:** Skeletal Horse"


def test_new_sections_vanish_without_data() -> None:
    text = format_status({"name": "A", "level": 3}, now=NOW)
    for header in ("Stats", "Buffs", "Spells", "Action bars", "Reputation", "Legacy", "Mounts"):
        assert header not in text


def test_detail_sections_tolerate_junk_data() -> None:
    snapshot: Table = {
        "stats": {"attributes": [None, {"value": "x"}], "spellDamage": "?"},
        "auras": [None, {"seconds": "soon"}],
        "actionBars": [{"slot": "one"}],
        "reputations": [{"value": 5, "max": 0}],
        "legacy": {"perks": [{"rank": None}]},
        "group": {"members": None},
        "timePlayed": {"total": "long"},
    }
    text = format_status(snapshot, now=NOW)
    assert "**Reputation:**\n- ?: ?" in text
