"""Tests for the commands that use wow-coach's own coach: signin, signout, ask."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from wow_coach import cli
from wow_coach.advice.contract import AdviceAnswer
from wow_coach.ai.base import AIError
from wow_coach.cli import main
from wow_coach.engine.contract import CoachReply
from wow_coach.engine.sources import SourceLink


@dataclass
class FakeAccount:
    subject: str = "user-1"
    email: str | None = "player@example.com"


class FakeSignIn:
    def __init__(self, *, signed_in: bool = False, revoke_ok: bool = True) -> None:
        self.is_signed_in = signed_in
        self.revoke_ok = revoke_ok
        self.urls: list[str] = []

    def sign_in(self, on_url: object = None) -> FakeAccount:
        if callable(on_url):
            on_url("https://auth.openai.com/authorize?fake")
        self.is_signed_in = True
        return FakeAccount()

    def sign_out(self) -> bool:
        self.is_signed_in = False
        return self.revoke_ok


class FakeCoach:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None]] = []

    def ask(self, question: str, *, character: str | None = None) -> CoachReply:
        self.asked.append((question, character))
        answer = AdviceAnswer(
            answered_at=1,
            source="ChatGPT (your plan)",
            title="Next steps",
            steps=("Spend your talent point.", "Go to the murlocs."),
            text="Both quests need murlocs.",
            warnings=("Pull one at a time.",),
        )
        return CoachReply(
            "Testchar-Testrealm", answer, True, "In the game after your next /reload."
        )

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        del character  # the fake has no open questions
        return []


def test_signin_opens_openai_and_says_the_plan_is_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSignIn()
    monkeypatch.setattr(cli, "build_sign_in", lambda *_: fake)
    assert main(["signin"]) == 0
    out = capsys.readouterr().out
    assert "Signed in as player@example.com." in out
    assert "You're using your ChatGPT plan." in out
    assert "https://chatgpt.com/settings/usage" in out
    assert "https://auth.openai.com/authorize?fake" in out  # in case the browser didn't open
    # OpenAI's terms: a privacy notice before any data is processed, so it comes first.
    assert out.index("Privacy notice:") < out.index("Signed in")
    assert "docs/privacy.md" in out


def test_signout_reports_when_the_revoke_was_not_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_sign_in", lambda *_: FakeSignIn(revoke_ok=False))
    assert main(["signout"]) == 0
    assert "did not confirm" in capsys.readouterr().out


def test_ask_prints_the_answer_and_where_else_it_shows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    coach = FakeCoach()
    monkeypatch.setattr(cli, "build_coach", lambda **_: coach)
    assert main(["ask", "What", "next?", "--character", "Testchar"]) == 0
    out = capsys.readouterr().out
    assert coach.asked == [("What next?", "Testchar")]
    assert "Next steps" in out
    assert "1. Spend your talent point." in out
    assert "2. Go to the murlocs." in out
    assert "Watch out: Pull one at a time." in out
    assert "ChatGPT (your plan)" in out
    assert "/reload" in out


def test_ask_without_a_question_explains(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ask"]) == 2
    assert "question" in capsys.readouterr().err


def test_an_ai_problem_is_one_plain_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(**_: object) -> FakeCoach:
        raise AIError("Your ChatGPT plan's limit is reached for now.")

    monkeypatch.setattr(cli, "build_coach", broken)
    assert main(["ask", "hi"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "wow-coach: Your ChatGPT plan's limit is reached for now."
    assert "Traceback" not in captured.err


def test_app_opens_the_window_for_the_game_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "WTF").mkdir()
    started: list[tuple[Path, int, bool]] = []

    def fake_run_app(*, wow_dir: Path, port: int, open_in_browser: bool) -> None:
        started.append((wow_dir, port, open_in_browser))

    monkeypatch.setattr(cli, "run_app", fake_run_app)
    assert main(["app", "--wow-dir", str(tmp_path), "--port", "8765", "--no-browser"]) == 0
    assert started == [(tmp_path, 8765, False)]


def test_ask_prints_a_sources_list_when_there_are_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Sourced(FakeCoach):
        def ask(self, question: str, *, character: str | None = None) -> CoachReply:
            plain = super().ask(question, character=character)
            return CoachReply(
                plain.character_key,
                plain.answer,
                plain.written_to_game,
                plain.note,
                sources=(
                    SourceLink("Abigail Shiel", "https://warcraft.wiki.gg/wiki/Abigail_Shiel"),
                    SourceLink("", "https://news.example/a"),
                ),
            )

    monkeypatch.setattr(cli, "build_coach", lambda **_: Sourced())
    assert main(["ask", "hi"]) == 0
    out = capsys.readouterr().out
    assert "Sources:" in out
    assert "- Abigail Shiel: https://warcraft.wiki.gg/wiki/Abigail_Shiel" in out
    assert "- https://news.example/a" in out


def test_ask_prints_no_sources_heading_without_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_coach", lambda **_: FakeCoach())
    assert main(["ask", "hi"]) == 0
    assert "Sources:" not in capsys.readouterr().out
