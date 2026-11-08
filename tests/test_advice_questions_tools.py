"""Tests for open questions and the plain-text MCP tool answers."""

from pathlib import Path

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice
from wow_coach.advice.questions import open_questions
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.tools import answer_questions_from_game, answer_send_advice_to_game
from wow_coach.lua_table import LuaValue
from wow_coach.savedvars import Character

KEY = "Testchar-Testrealm"
NOW = 1794100300


def question(qid: str, text: str, asked_at: int) -> LuaValue:
    return {"id": qid, "text": text, "askedAt": asked_at}


def character(*questions: LuaValue) -> Character:
    return Character(key=KEY, snapshot={}, history=[], questions=list(questions))


def advice_answering(*ids: str) -> AdviceFile:
    answers = tuple(AdviceAnswer(1, "S", "t", question_id=i) for i in ids)
    return AdviceFile(1, {KEY: CharacterAdvice(1, answers)})


# ---- open_questions -----------------------------------------------------------------


def test_open_questions_without_an_advice_file() -> None:
    found = open_questions(character(question("1-1", "Hi?", 1), question("2-1", "Yo?", 2)), None)
    assert [q.id for q in found] == ["1-1", "2-1"]


def test_answered_questions_are_left_out() -> None:
    mine = character(question("1-1", "a", 1), question("2-1", "b", 2))
    assert [q.id for q in open_questions(mine, advice_answering("1-1"))] == ["2-1"]


def test_answers_of_other_characters_do_not_count() -> None:
    other = AdviceFile(1, {"Other-R": advice_answering("1-1").characters[KEY]})
    assert len(open_questions(character(question("1-1", "a", 1)), other)) == 1


def test_damaged_questions_are_skipped() -> None:
    mine = character(
        question("1-1", "fine", 1),
        "a string",
        {"id": 5, "text": "id not a string", "askedAt": 1},
        {"id": "x", "text": "", "askedAt": 1},
        {"id": "y", "text": "no time"},
        {"id": "z", "text": "bool time", "askedAt": True},
        question("1-1", "duplicate id", 3),
        None,
    )
    assert [q.text for q in open_questions(mine, None)] == ["fine"]


def test_no_questions_at_all() -> None:
    assert open_questions(Character(key=KEY, snapshot={}, history=[]), None) == []


def test_very_long_question_text_is_cut() -> None:
    found = open_questions(character(question("1-1", "x" * 5000, 1)), None)
    assert len(found[0].text) == 500


# ---- answer_questions_from_game ------------------------------------------------------


def test_listing_open_questions() -> None:
    mine = character(question("1794100000-1", "What next?", 1794100000))
    text = answer_questions_from_game(mine, None, NOW)
    assert "1794100000-1" in text and "What next?" in text
    assert "5 min ago" in text
    assert "send_advice_to_game" in text and "question_id" in text


def test_listing_when_there_are_none() -> None:
    text = answer_questions_from_game(character(), None, NOW)
    assert "no open questions" in text


def test_listing_when_all_are_answered() -> None:
    mine = character(question("1-1", "a", 1))
    assert "no open questions" in answer_questions_from_game(mine, advice_answering("1-1"), NOW)


# ---- answer_send_advice_to_game ------------------------------------------------------


def send(wow_dir: Path, **changes: object) -> str:
    fields: dict[str, object] = {
        "wow_dir": wow_dir,
        "character_key": KEY,
        "based_on_save": 1794100250,
        "title": "Next steps",
        "steps": ["Go to Brill."],
        "text": "",
        "warnings": [],
        "question_id": None,
        "source": "Claude Code coach",
        "now": NOW,
    }
    fields.update(changes)
    return answer_send_advice_to_game(**fields)  # type: ignore[arg-type]


def make_game(tmp_path: Path) -> Path:
    (tmp_path / "Interface" / "AddOns").mkdir(parents=True)
    return tmp_path


def advice_path(game: Path) -> Path:
    return game / "Interface" / "AddOns" / "CoachLink_Advice" / "Advice.lua"


def test_first_send_says_restart(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    reply = send(game)
    assert "full restart" in reply
    saved = read_advice_file(advice_path(game))
    assert saved is not None
    assert saved.characters[KEY].answers[0].title == "Next steps"
    assert saved.characters[KEY].based_on_save == 1794100250


def test_later_sends_say_reload_and_keep_old_answers(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    send(game, title="First")
    reply = send(game, title="Second")
    assert "/reload" in reply and "restart" not in reply
    saved = read_advice_file(advice_path(game))
    assert saved is not None
    assert [a.title for a in saved.characters[KEY].answers] == ["First", "Second"]


def test_question_is_filled_in_from_the_save(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    save_folder = game / "WTF" / "Account" / "ACC" / "SavedVariables"
    save_folder.mkdir(parents=True)
    (save_folder / "CoachLink.lua").write_text(
        'CoachLinkDB = {\n["formatVersion"] = 1,\n["characters"] = {\n["Testchar-Testrealm"] = {\n'
        '["snapshot"] = {},\n["questions"] = {\n'
        '{ ["id"] = "1794100000-1", ["text"] = "What next?", ["askedAt"] = 1794100000 },\n'
        "},\n},\n},\n}\n",
        encoding="utf-8",
    )
    reply = send(game, question_id="1794100000-1")
    assert "no open question" not in reply
    saved = read_advice_file(advice_path(game))
    assert saved is not None
    answer = saved.characters[KEY].answers[0]
    assert (answer.question_id, answer.question, answer.asked_at) == (
        "1794100000-1",
        "What next?",
        1794100000,
    )


def test_unknown_question_id_is_kept_with_a_note(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert "not a valid id" in send(game, question_id="nope")
    assert "no open question has the id 9-9" in send(game, question_id="9-9")
    saved = read_advice_file(advice_path(game))
    assert saved is not None
    assert all(a.question_id is None for a in saved.characters[KEY].answers)


def test_missing_title_or_content_is_a_plain_sentence(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert send(game, title="  ").startswith("Not sent")
    assert send(game, steps=[], text=" ").startswith("Not sent")
    assert not advice_path(game).exists()


def test_missing_game_folder_never_raises(tmp_path: Path) -> None:
    reply = send(tmp_path / "no-game")
    assert reply.startswith("Not sent")


def test_blank_source_gets_the_default(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    send(game, source="  ")
    saved = read_advice_file(advice_path(game))
    assert saved is not None
    assert saved.characters[KEY].answers[0].source == "Claude Code coach"


def test_long_text_is_cut_and_the_reply_says_so(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert "shortened" in send(game, text="x" * 5000)


def test_damaged_old_file_is_replaced(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    advice_path(game).parent.mkdir()
    advice_path(game).write_text("CoachLinkAdvice = {", encoding="utf-8")
    send(game)
    assert read_advice_file(advice_path(game)) is not None


def test_symlinked_folder_gives_a_sentence_not_an_error(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (game / "Interface" / "AddOns" / "CoachLink_Advice").symlink_to(outside)
    assert send(game).startswith("Not sent")
    assert list(outside.iterdir()) == []
