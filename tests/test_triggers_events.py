"""events_between: what changed between two saves."""

from wow_coach.lua_table import LuaValue
from wow_coach.savedvars import Character
from wow_coach.triggers.contract import Event
from wow_coach.triggers.events import events_between

NOW = 100_000


def save(
    snapshot: dict[str | int, LuaValue] | None = None,
    history: list[LuaValue] | None = None,
) -> Character:
    base: dict[str | int, LuaValue] = {
        "savedAt": NOW - 60,
        "level": 9,
        "zone": "Tirisfal Glades",
        "bags": {"free": 10, "total": 16},
        "talents": {"unspent": 0},
        "quests": [],
        "gear": [],
        "professions": [],
    }
    base.update(snapshot or {})
    return Character("Test-Realm", base, history or [])


def kinds(events: list[Event]) -> list[str]:
    return [event.kind for event in events]


def test_no_change_no_events() -> None:
    assert events_between(save(), save(), now=NOW) == []


def test_died_uses_death_text_and_keeps_the_player_name_out() -> None:
    death = {
        "time": NOW - 10,
        "kind": "death",
        "text": "Died in Brill (level 9). Attacked by 2 enemies: Bobby (level 9), "
        "Scarlet Friar (level 8). Killing blow: Bobby (melee, 45 damage). 40 s after coming back.",
        "attackers": [
            {"name": "Bobby", "level": 9, "isPlayer": True},
            {"name": "Scarlet Friar", "level": 8, "isPlayer": False},
        ],
        "killer": {"name": "Bobby", "spell": "melee"},
    }
    events = events_between(save(), save(history=[death]), now=NOW)
    assert kinds(events) == ["died"]
    summary = events[0].summary
    assert summary.startswith("Died in Brill (level 9). Attacked by")
    assert "Bobby" not in summary
    assert "a player" in summary
    assert "Scarlet Friar" in summary
    assert "Killing blow" not in summary
    assert events[0].at == NOW - 10
    assert events[0].character_key == "Test-Realm"


def test_old_death_is_not_reported_again() -> None:
    death = {"time": NOW - 500, "kind": "death", "text": "Died in Brill (level 9)"}
    assert events_between(save(), save(history=[death]), now=NOW) == []


def test_died_again_soon() -> None:
    death = {"time": NOW - 5, "kind": "death", "text": "Died in Brill", "secondsSinceRevive": 40}
    events = events_between(save(), save(history=[death]), now=NOW)
    assert kinds(events) == ["died", "died_again_soon"]
    assert "40 seconds" in events[1].summary


def test_level_up_from_a_rise() -> None:
    events = events_between(save(), save({"level": 10}), now=NOW)
    assert [(e.kind, e.summary) for e in events] == [("level_up", "Reached level 10.")]


def test_level_up_from_history_is_reported_once() -> None:
    level = {"time": NOW - 20, "kind": "level", "level": 10}
    events = events_between(save(), save({"level": 10}, [level]), now=NOW)
    assert kinds(events) == ["level_up"]


def test_quest_done() -> None:
    before = save({"quests": [{"questID": 5, "title": "Rude Awakening", "complete": False}]})
    after = save({"quests": [{"questID": 5, "title": "Rude Awakening", "complete": True}]})
    events = events_between(before, after, now=NOW)
    assert [(e.kind, e.summary) for e in events] == [
        ("quest_done", "Ready to turn in: Rude Awakening.")
    ]
    assert events_between(after, after, now=NOW) == []


def test_bags_nearly_full_only_when_it_gets_there() -> None:
    nearly = save({"bags": {"free": 2, "total": 16}})
    assert kinds(events_between(save(), nearly, now=NOW)) == ["bags_nearly_full"]
    fuller = save({"bags": {"free": 1, "total": 16}})
    assert events_between(nearly, fuller, now=NOW) == []


def test_new_zone() -> None:
    events = events_between(save(), save({"zone": "Undercity"}), now=NOW)
    assert [(e.kind, e.summary) for e in events] == [("new_zone", "Now in Undercity.")]


def test_talent_points() -> None:
    one = save({"talents": {"unspent": 1}})
    assert kinds(events_between(save(), one, now=NOW)) == ["talent_points"]
    assert events_between(one, one, now=NOW) == []


def _gear_snapshot(item_name: str) -> dict[str | int, LuaValue]:
    return {
        "professions": [{"name": "Cloth", "category": "Armor Proficiencies"}],
        "bags": {
            "free": 10,
            "total": 16,
            "containers": [
                {"items": [{"name": item_name, "type": "Armor", "subType": "Plate"}]},
            ],
        },
    }


def test_gear_hint_for_a_new_cant_use_line() -> None:
    events = events_between(save(), save(_gear_snapshot("Iron Helm")), now=NOW)
    assert [(e.kind, e.summary) for e in events] == [("gear_hint", "can't use yet: Iron Helm.")]
    same = save(_gear_snapshot("Iron Helm"))
    assert events_between(same, same, now=NOW) == []


def test_gear_hint_for_an_upgrade() -> None:
    robe: dict[str | int, LuaValue] = {
        "name": "Fine Robe",
        "equipSlot": "Chest",
        "itemLevel": 9,
        "type": "Armor",
    }
    snapshot: dict[str | int, LuaValue] = {
        "gear": [{"slot": "Chest", "name": "Old Robe", "itemLevel": 5}],
        "bags": {"free": 10, "total": 16, "containers": [{"items": [robe]}]},
    }
    events = events_between(save(), save(snapshot), now=NOW)
    assert [(e.kind, e.summary) for e in events] == [
        ("gear_hint", "Possible upgrade in your bags: Fine Robe.")
    ]


def test_durability_low_only_when_it_drops_under() -> None:
    fine = save({"gear": [{"slot": "Chest", "durability": 80, "durabilityMax": 100}]})
    worn = save({"gear": [{"slot": "Chest", "durability": 20, "durabilityMax": 100}]})
    events = events_between(fine, worn, now=NOW)
    assert [(e.kind, e.summary) for e in events] == [
        ("durability_low", "Worn gear needs repair: Chest 20%.")
    ]
    assert events_between(worn, worn, now=NOW) == []


def test_first_save_only_reports_recent_history() -> None:
    recent = {"time": NOW - 120, "kind": "death", "text": "Died in Brill (level 9)"}
    old = {"time": NOW - 3600, "kind": "death", "text": "Died in Brill (level 8)"}
    events = events_between(None, save(history=[old, recent]), now=NOW)
    assert [e.at for e in events] == [NOW - 120]


def test_first_save_has_no_snapshot_events() -> None:
    after = save({"level": 12, "bags": {"free": 1, "total": 16}, "talents": {"unspent": 3}})
    assert events_between(None, after, now=NOW) == []


def test_unloaded_save_gives_no_snapshot_events() -> None:
    unloaded = save({"bags": {"free": 0, "total": 0}, "zone": "Elsewhere"})
    assert events_between(save(), unloaded, now=NOW) == []


def test_garbage_does_not_crash() -> None:
    junk_history: list[LuaValue] = [
        None,
        "x",
        5,
        {"kind": "death"},
        {"kind": "death", "time": "soon"},
        {"kind": 7, "time": NOW},
        {"kind": "death", "time": NOW - 1, "text": 42, "attackers": "none", "killer": [1]},
    ]
    junk: dict[str | int, LuaValue] = {
        "savedAt": "yesterday",
        "level": "ten",
        "zone": 5,
        "bags": "full",
        "talents": [1],
        "quests": [None, "q", {"complete": True}, {"questID": "x", "complete": True}],
        "gear": [{"slot": "Head", "durability": "a", "durabilityMax": 0}, 3],
        "professions": "none",
    }
    events = events_between(save(), save(junk, junk_history), now=NOW)
    assert "died" in kinds(events)
    assert events_between(save(junk), save(junk, junk_history), now=NOW) is not None
    assert events_between(None, Character("X-Y", {}, []), now=NOW) == []


def test_summaries_are_short_single_lines() -> None:
    long_text = "Died in Brill\n(level 9). " + "Attacked by " + "Wolf, " * 200
    death = {"time": NOW - 1, "kind": "death", "text": long_text}
    summary = events_between(save(), save(history=[death]), now=NOW)[0].summary
    assert "\n" not in summary
    assert len(summary) <= 240
