"""Tests for the engine's small parts: model choice, answer parsing, redaction, conversation."""

import json
from pathlib import Path

from test_engine_support import KEY, SAVE, make_world

from wow_coach.advice.contract import MAX_STEP_CHARS, MAX_STEPS, MAX_TEXT_CHARS
from wow_coach.engine.answer import ANSWER_SCHEMA, parse_answer
from wow_coach.engine.conversation import (
    MAX_FILE_BYTES,
    MAX_STORED_MESSAGES,
    Turn,
    append_turns,
    conversation_path,
    load_turns,
)
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


def test_redact_longest_name_first_and_is_case_sensitive() -> None:
    assert redact_names("Annabel and Ann", {"Ann", "Annabel"}) == "a player and a player"
    assert redact_names("I will go. Will came.", {"Will"}) == "I will go. a player came."


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
