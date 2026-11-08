"""Tests for the engine's small parts: model choice, answer parsing, redaction, conversation."""

import json
import os
import time
from pathlib import Path

import pytest
from test_engine_support import KEY, SAVE, make_world

from wow_coach.advice.contract import MAX_STEP_CHARS, MAX_STEPS, MAX_TEXT_CHARS
from wow_coach.engine import memory as memory_module
from wow_coach.engine.answer import ANSWER_SCHEMA, parse_answer
from wow_coach.engine.conversation import (
    MAX_FILE_BYTES,
    MAX_STORED_MESSAGES,
    Turn,
    append_turns,
    conversation_path,
    load_turns,
)
from wow_coach.engine.memory import LocalMemory
from wow_coach.engine.model import choose_model, choose_small_model
from wow_coach.engine.redact import looks_like_player_name, other_player_names, redact_names
from wow_coach.savedvars import find_saved_variables, load_characters

# ---- choose_model -------------------------------------------------------------------


def test_preferred_model_wins_when_available() -> None:
    assert choose_model(["a-luna", "b"], "b") == "b"


def test_answers_use_a_balanced_model_by_default() -> None:
    # The real plan lists -sol (largest), -terra (balanced) and -luna (small) models. A small
    # model gave a careless answer in a real test (2026-11-08), so answers use -terra first.
    plan = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6.1-terra", "gpt-6-luna"]
    assert choose_model(plan, None) == "gpt-6.1-terra"
    assert choose_model(plan, "gone") == "gpt-6.1-terra"
    assert choose_model(["big-sol", "x-luna"], None) == "big-sol"
    assert choose_model(["big", "x-luna"], None) == "x-luna"


def test_the_small_model_is_for_quick_yes_or_no_checks() -> None:
    assert choose_small_model(["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"]) == "gpt-6-luna"
    assert choose_small_model(["big-sol", "mid-terra"]) == "mid-terra"
    assert choose_small_model([]) is None


def test_first_listed_model_when_no_known_size() -> None:
    assert choose_model(["big", "bigger"], None) == "big"


def test_no_models_gives_none() -> None:
    assert choose_model([], "x") is None


# ---- parse_answer -------------------------------------------------------------------


def parse(reply: str):  # noqa: ANN201
    return parse_answer(reply, answered_at=5, source="ChatGPT (your plan)")


def test_good_json_is_read() -> None:
    answer = parse('{"title":"T","steps":["a","b"],"text":"x","warnings":["w"]}')
    assert (answer.title, answer.steps, answer.text, answer.warnings) == (
        "T",
        ("a", "b"),
        "x",
        ("w",),
    )
    assert answer.source == "ChatGPT (your plan)"
    assert answer.answered_at == 5


def test_json_in_a_code_fence_is_read() -> None:
    assert parse('```json\n{"title":"T","steps":["a"],"text":"","warnings":[]}\n```').title == "T"


def test_too_many_or_too_long_items_are_cut() -> None:
    steps = ["s" * 1000] * 9
    answer = parse(json.dumps({"title": "T", "steps": steps, "text": "x" * 9000, "warnings": []}))
    assert len(answer.steps) == MAX_STEPS
    assert all(len(step) == MAX_STEP_CHARS for step in answer.steps)
    assert len(answer.text) == MAX_TEXT_CHARS


def test_prose_falls_back_to_text() -> None:
    answer = parse("Just go to Brill.")
    assert (answer.title, answer.steps, answer.text) == ("Coach", (), "Just go to Brill.")


def test_fallback_text_is_cut() -> None:
    assert len(parse("y" * 9000).text) == MAX_TEXT_CHARS


def test_wrong_shapes_fall_back_without_crashing() -> None:
    replies = ["", "[]", "null", '{"title": 3}', '{"title":"T","steps":"one"}', '{"title":"T"}']
    replies += ['{"title":"","steps":["a"]}', '{"title":"T","steps":[1]}', "{" * 5000]
    for reply in replies:
        assert parse(reply).title == "Coach"


def test_schema_asks_for_all_four_fields() -> None:
    assert ANSWER_SCHEMA["required"] == ["title", "steps", "text", "warnings"]


# ---- redaction ----------------------------------------------------------------------


def test_names_come_from_group_mail_attackers_and_item_events(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    character = load_characters(find_saved_variables(world.wow_dir))[KEY]
    assert other_player_names(character) == {"Bobby", "Gorbo", "Zandor", "Mirela"}


def test_own_name_is_never_hidden(tmp_path: Path) -> None:
    save = SAVE.replace('"Bobby"', '"Testchar"')
    world = make_world(tmp_path, save=save)
    character = load_characters(find_saved_variables(world.wow_dir))[KEY]
    assert "Testchar" not in other_player_names(character)


def test_redact_whole_words_only() -> None:
    text = "Ann met Annex and Ann's pal, then Ann."
    assert redact_names(text, {"Ann"}) == "a player met Annex and a player's pal, then a player."


def test_redact_longest_name_first_and_short_names_are_case_sensitive() -> None:
    assert redact_names("Annabel and Ann", {"Ann", "Annabel"}) == "a player and a player"
    assert redact_names("Go to bo. Bo came.", {"Bo"}) == "Go to bo. a player came."


def test_redact_handles_special_characters_in_names() -> None:
    assert redact_names("hi a.b and axb", {"a.b"}) == "hi a player and axb"


def test_redact_with_no_names_changes_nothing() -> None:
    assert redact_names("Bobby", set()) == "Bobby"


def test_player_like_names() -> None:
    assert looks_like_player_name("Thrall")
    assert looks_like_player_name("Élodie")
    assert not looks_like_player_name("Auction House")
    assert not looks_like_player_name("Bob2")
    assert not looks_like_player_name("")


# ---- conversation -------------------------------------------------------------------


def test_conversation_path_is_file_safe(tmp_path: Path) -> None:
    path = conversation_path("A/b:c-Realm", environ={"WOW_COACH_DATA_DIR": str(tmp_path)})
    assert path.parent.name == "conversations"
    assert path.name == "A_b_c-Realm.jsonl"


def test_turns_are_saved_and_reloaded_oldest_first(tmp_path: Path) -> None:
    path = tmp_path / "c" / "x.jsonl"
    append_turns(path, [Turn("user", "q1"), Turn("assistant", "a1")])
    append_turns(path, [Turn("user", "q2"), Turn("assistant", "a2")])
    assert [t.content for t in load_turns(path)] == ["q1", "a1", "q2", "a2"]
    assert [t.content for t in load_turns(path, limit=2)] == ["q2", "a2"]


def test_only_the_newest_messages_are_stored(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    for number in range(MAX_STORED_MESSAGES + 10):
        append_turns(path, [Turn("user", f"q{number}")])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == MAX_STORED_MESSAGES
    assert json.loads(lines[-1])["content"] == f"q{MAX_STORED_MESSAGES + 9}"


def test_file_size_is_capped(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    for _ in range(60):
        append_turns(path, [Turn("assistant", "w" * 5000)])
    assert path.stat().st_size <= MAX_FILE_BYTES + 3000


def test_damaged_file_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    good = json.dumps({"role": "user", "content": "kept"})
    path.write_bytes(
        good.encode() + b'\nnot json\n{"role":"boss","content":"x"}\n[1]\n\xff\xfe\n'
        b'{"role":"user","content":5}\n'
    )
    assert [t.content for t in load_turns(path)] == ["kept"]
    append_turns(path, [Turn("assistant", "new")])  # rewrites the file cleanly
    assert [t.content for t in load_turns(path)] == ["kept", "new"]


def test_missing_file_gives_no_turns(tmp_path: Path) -> None:
    assert load_turns(tmp_path / "nope.jsonl") == []


def test_names_of_four_letters_or_more_match_in_any_case() -> None:
    text = "gorbo wrote GORBO and Gorbo"
    assert redact_names(text, {"Gorbo"}) == "a player wrote a player and a player"


def test_digits_belong_to_the_word() -> None:
    assert redact_names("Gorbo2 and Gorbo", {"Gorbo"}) == "Gorbo2 and a player"
    assert redact_names("Gorbo2 and Gorbo", {"Gorbo", "Gorbo2"}) == "a player and a player"


def test_cross_realm_names_are_found_and_both_forms_hidden(tmp_path: Path) -> None:
    save = SAVE.replace('["sender"] = "Gorbo"', '["sender"] = "Crossy-Stormrage"').replace(
        '["from"] = "Mirela"', '["from"] = "Zed-Hyjal"'
    )
    character = load_characters(find_saved_variables(make_world(tmp_path, save=save).wow_dir))[KEY]
    names = other_player_names(character)
    assert {"Crossy-Stormrage", "Crossy", "Zed-Hyjal", "Zed"} <= names
    assert redact_names("Crossy-Stormrage and Crossy", names) == "a player and a player"
    assert not looks_like_player_name("Auction House-Realm")


def test_killers_are_players_unless_they_are_known_monsters(tmp_path: Path) -> None:
    death = (
        '{ ["time"] = 1793899500, ["kind"] = "death", ["text"] = "Killing blow: %s", '
        '["killer"] = { ["name"] = "%s" }, ["attackers"] = { %s } },\n'
    )
    monster = '{ ["name"] = "Wolf", ["level"] = 3 }'
    events = death % ("Karnak", "Karnak", "") + death % ("Wolf", "Wolf", monster)
    save = SAVE.replace('["history"] = {\n', '["history"] = {\n' + events)
    character = load_characters(find_saved_variables(make_world(tmp_path, save=save).wow_dir))[KEY]
    names = other_player_names(character)
    assert "Karnak" in names and "Wolf" not in names
    assert "Scarlet Warrior" not in names  # several words: a monster, never a player name


def test_monster_killer_text_is_not_damaged(tmp_path: Path) -> None:
    """The addon leaves isPlayer out for monsters; they must not turn into "a player"."""
    event = (
        '{ ["time"] = 1793899500, ["kind"] = "death", ["text"] = "Killing blow: Hogger", '
        '["killer"] = { ["name"] = "Hogger" }, ["attackers"] = { { ["name"] = "Hogger" }, '
        '{ ["name"] = "Zandor", ["isPlayer"] = true } } },\n'
    )
    save = SAVE.replace('["history"] = {\n', '["history"] = {\n' + event)
    character = load_characters(find_saved_variables(make_world(tmp_path, save=save).wow_dir))[KEY]
    names = other_player_names(character)
    text = "How do I beat Hogger? Kill 0/10 Scarlet Warrior"
    assert redact_names(text, names) == text
    assert "Zandor" in names


def test_common_words_survive_but_exact_and_caps_spellings_are_hidden() -> None:
    names = {"Will", "Mage", "Frost", "Gorbo"}
    text = "What will I get? Mage trainer, frost bolt. Will said so. WILL! gorbo / GORBO / Gorbo"
    assert redact_names(text, names) == (
        "What will I get? a player trainer, frost bolt. a player said so. a player! "
        "a player / a player / a player"
    )


def test_own_characters_are_never_hidden(tmp_path: Path) -> None:
    save = SAVE.replace('["sender"] = "Gorbo"', '["sender"] = "Altchar"')
    character = load_characters(find_saved_variables(make_world(tmp_path, save=save).wow_dir))[KEY]
    assert "Altchar" in other_player_names(character)
    assert "Altchar" not in other_player_names(character, own=frozenset({"Testchar", "Altchar"}))


def test_the_old_names_file_is_deleted_and_not_read(tmp_path: Path) -> None:
    old = tmp_path / "hidden-names.json"
    old.write_text('{"Testchar-Testrealm": ["Hogger"]}')
    memory = LocalMemory(environ={"WOW_COACH_DATA_DIR": str(tmp_path)})
    assert not old.exists()
    assert memory.seen_names(KEY) == set()


def test_memory_trims_the_oldest_characters_to_fit_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(memory_module, "MAX_FILE_BYTES", 2000)
    memory = LocalMemory(environ={"WOW_COACH_DATA_DIR": str(tmp_path)})
    for number in range(10):
        memory.add_seen_names(f"Char{number}-R", {f"Name{number}{n:03}" for n in range(30)})
    assert (tmp_path / "hidden-names-v2.json").stat().st_size <= 2000
    assert memory.seen_names("Char9-R")  # the newest character is kept
    assert not memory.seen_names("Char0-R")


def test_memory_lock_is_removed_and_a_stale_lock_is_taken_over(tmp_path: Path) -> None:
    memory = LocalMemory(environ={"WOW_COACH_DATA_DIR": str(tmp_path)})
    lock = tmp_path / "answered-questions.json.lock"
    lock.write_text("")
    os.utime(lock, (1, 1))  # a very old lock: left by a crashed program
    memory.add_answered(KEY, "1-1")
    assert memory.answered_ids(KEY) == {"1-1"}
    assert not lock.exists()


def test_fence_removal_is_fast_on_pathological_replies() -> None:
    for reply in ("```" + " " * 3200, "```json" + "\n" * 3200 + "x", " " * 3200 + "```"):
        started = time.perf_counter()
        parse(reply)
        assert time.perf_counter() - started < 0.1


def test_memory_files_are_capped_atomic_and_tolerate_damage(tmp_path: Path) -> None:
    environ = {"WOW_COACH_DATA_DIR": str(tmp_path)}
    memory = LocalMemory(environ=environ)
    memory.add_seen_names(KEY, {f"Name{number}x" for number in range(300)})
    assert len(memory.seen_names(KEY)) == 200
    memory.add_answered(KEY, "1-1")
    assert memory.answered_ids(KEY) == {"1-1"}
    assert memory.answered_ids("Other-Realm") == set()
    (tmp_path / "answered-questions.json").write_bytes(b"\xff{{{")
    (tmp_path / "hidden-names-v2.json").write_text('{"a": 5, "b": [1, "ok"], "c": "x"}')
    assert memory.answered_ids(KEY) == set()
    assert memory.seen_names("b") == {"ok"}
    memory.add_answered(KEY, "2-1")  # a damaged file is simply replaced
    assert memory.answered_ids(KEY) == {"2-1"}
