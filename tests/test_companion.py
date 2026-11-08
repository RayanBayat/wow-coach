"""Tests for putting the coach together (companion.py)."""

from pathlib import Path
from typing import ClassVar

from wow_coach.app_settings import AppSettings, save_settings
from wow_coach.companion import LiveCoach


class FakeModel:
    def __init__(self, slug: str) -> None:
        self.slug = slug


class FakePlan:
    def __init__(self) -> None:
        self.model_lists = 0

    def list_models(self) -> list[FakeModel]:
        self.model_lists += 1
        return [FakeModel("gpt-6-sol"), FakeModel("gpt-6-terra"), FakeModel("gpt-6-luna")]


class FakeChatCoach:
    made: ClassVar[list[dict[str, object]]] = []

    def __init__(self, plan: object, **options: object) -> None:
        del plan  # the fake never calls the AI
        FakeChatCoach.made.append(options)

    def ask(self, question: str, *, character: str | None = None) -> str:
        del character
        return f"answer to {question}"

    def answer_open_questions(self, *, character: str | None = None) -> list[str]:
        del character
        return []


def test_live_coach_reads_the_settings_before_every_answer(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    plan = FakePlan()
    FakeChatCoach.made.clear()
    coach = LiveCoach(
        plan,  # type: ignore[arg-type]  # a fake with the same methods
        wow_dir=tmp_path,
        environ={},
        settings_file=settings_file,
        make_coach=FakeChatCoach,  # type: ignore[arg-type]
    )
    coach.ask("first")
    save_settings(settings_file, AppSettings(share_other_player_names=True, model="gpt-6-sol"))
    coach.ask("second")
    coach.ask("third")
    first, second, third = FakeChatCoach.made
    assert first["model"] == "gpt-6-terra"  # no choice yet: a balanced one
    assert second["model"] == "gpt-6-sol"  # the player's new choice
    settings = second["settings"]
    assert isinstance(settings, AppSettings) and settings.share_other_player_names is True
    assert third["model"] == "gpt-6-sol"
    assert plan.model_lists == 2  # fetched again only when the choice changed
