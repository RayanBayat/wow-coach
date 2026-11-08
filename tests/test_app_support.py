"""Shared helpers for the coach-window tests: fakes, a fake game folder and a small client.

Nothing here touches the network, the keychain or a real game folder.
"""

import http.client
import json
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice
from wow_coach.advice.serialize import advice_to_lua
from wow_coach.ai.chatgpt_plan import PlanModel
from wow_coach.app.core import AppCore
from wow_coach.app.events import Mailbox
from wow_coach.app.server import CoachServer
from wow_coach.engine.contract import CoachReply
from wow_coach.server import advice_file_path

KEY = "Testchar-Testrealm"


# ---- a fake game folder --------------------------------------------------------------


def write_save(
    wow_dir: Path,
    *questions: tuple[str, str],
    mtime: int = 1_000,
    deaths_at: tuple[int, ...] = (),
    levels_at: tuple[int, ...] = (),
    in_instance: bool = False,
    zone: str = "Tirisfal Glades",
    reason: str = "ask",
) -> Path:
    """Write a CoachLink.lua with one character, its (id, text) questions and some deaths."""
    instance = '["instance"] = {["name"] = "Deadmines"},\n' if in_instance else ""
    deaths = "".join(
        f'{{["time"] = {t}, ["kind"] = "death", ["text"] = "Died in Brill (level 8)."}},\n'
        for t in deaths_at
    ) + "".join(f'{{["time"] = {t}, ["kind"] = "level"}},\n' for t in levels_at)
    folder = wow_dir / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True, exist_ok=True)
    asked = "".join(
        f'{{["id"] = "{qid}", ["text"] = "{text}", ["askedAt"] = {i + 1}}},\n'
        for i, (qid, text) in enumerate(questions)
    )
    path = folder / "CoachLink.lua"
    path.write_text(
        'CoachLinkDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
        f'["{KEY}"] = {{\n["snapshot"] = {{\n["name"] = "Testchar",\n["level"] = 8,\n'
        f'["savedAt"] = {mtime},\n["reason"] = "{reason}",\n["zone"] = "{zone}",\n{instance}}},\n'
        f'["questions"] = {{\n{asked}}},\n'
        f'["history"] = {{\n{deaths}}},\n'
        "},\n},\n}\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def make_answer(title: str, answered_at: int, question_id: str | None = None) -> AdviceAnswer:
    return AdviceAnswer(
        answered_at=answered_at,
        source="Test coach",
        title=title,
        steps=("Do this", "Then that"),
        text="Some words.",
        warnings=("Careful",),
        question_id=question_id,
        question="What now?" if question_id else None,
    )


def write_advice_file(
    wow_dir: Path, answers: list[AdviceAnswer], answered_ids: tuple[str, ...] = (), mtime: int = 0
) -> Path:
    """Write Advice.lua for KEY. ``mtime`` > 0 sets its change time (to be sure it differs)."""
    path = advice_file_path(wow_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = CharacterAdvice(based_on_save=1, answers=tuple(answers), answered_ids=answered_ids)
    path.write_text(advice_to_lua(AdviceFile(written_at=1, characters={KEY: entry})), "utf-8")
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


# ---- fakes for the three contracts -----------------------------------------------------


@dataclass
class FakeCoach:
    """Stands in for the engine. ``error`` is raised by every call when set."""

    wow_dir: Path
    error: Exception | None = None
    gate: threading.Event | None = None  # when set, calls wait for it (to test "busy")
    asked: list[str] = field(default_factory=list)
    answered_calls: list[str | None] = field(default_factory=list)
    clock: int = 5_000
    reply_nothing: bool = False  # answer_open_questions finds everything already answered
    during_call: Callable[[], None] | None = None  # runs in the middle of a call

    def _reply(self, title: str, question_id: str | None) -> CoachReply:
        answer = make_answer(title, self.clock, question_id)
        self.clock += 1
        # Like the real engine, write the answer into Advice.lua.
        advice = write_advice_file(
            self.wow_dir, [answer], answered_ids=(question_id,) if question_id else ()
        )
        os.utime(advice, (self.clock, self.clock))
        return CoachReply(KEY, answer, True, "In the game after your next /reload.")

    def ask(self, question: str, *, character: str | None = None) -> CoachReply:
        del character
        if self.gate is not None:
            self.gate.wait(5)
        if self.error is not None:
            raise self.error
        self.asked.append(question)
        return self._reply("Answer to " + question, None)

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        self.answered_calls.append(character)
        if self.error is not None:
            raise self.error
        if self.reply_nothing:
            return []
        return [self._reply("Open answer", "1-1")]


class FakeSignIn:
    def __init__(self, signed_in: bool = True) -> None:
        self.signed_in = signed_in
        self.sign_ins = 0
        self.revoke_ok = True

    @property
    def is_signed_in(self) -> bool:
        return self.signed_in

    def sign_in(self, on_url: Callable[[str], None] | None = None) -> object:
        self.sign_ins += 1
        if on_url is not None:
            on_url("https://auth.openai.com/authorize?x=1")
        self.signed_in = True
        return object()

    def sign_out(self) -> bool:
        self.signed_in = False
        return self.revoke_ok


class FakeAlerts:
    def __init__(self) -> None:
        self.notified: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> bool:
        self.notified.append((title, body))
        return True

    def available(self) -> dict[str, bool]:
        return {"notify": True}


class FakeUsage:
    def calls_in_last(self, seconds: float) -> int:
        return 2 if seconds <= 3600 else 7


def fake_models() -> list[PlanModel]:
    return [PlanModel("gpt-small", "Small and fast"), PlanModel("gpt-big", "Big")]


@dataclass
class Rig:
    """Everything one test needs."""

    core: AppCore
    coach: FakeCoach
    signin: FakeSignIn
    alerts: FakeAlerts
    wow_dir: Path
    settings_file: Path


def make_rig(
    tmp_path: Path,
    *,
    signed_in: bool = True,
    claude_projects_dir: Path | None = None,
) -> Rig:
    wow_dir = tmp_path / "wow"
    wow_dir.mkdir()
    write_save(wow_dir)
    coach = FakeCoach(wow_dir)
    signin = FakeSignIn(signed_in)
    alerts = FakeAlerts()
    settings_file = tmp_path / "data" / "settings.json"
    core = AppCore(
        coach=coach,
        signin=signin,
        alerts=alerts,
        list_models=fake_models,
        settings_file=settings_file,
        wow_dir=wow_dir,
        usage=FakeUsage(),
        claude_projects_dir=claude_projects_dir,
    )
    return Rig(core, coach, signin, alerts, wow_dir, settings_file)


def wait_for_event(mailbox: Mailbox, kind: str, timeout: float = 5.0) -> dict[str, object]:
    """The data of the next event of this kind (others are skipped)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = mailbox.get(timeout=0.2)
        except queue.Empty:
            continue
        if event is not None and event.kind == kind:
            return event.data
    raise AssertionError(f"no {kind!r} event arrived")


# ---- a tiny HTTP client ---------------------------------------------------------------


class Client:
    """Talks to a running CoachServer like the page does."""

    def __init__(self, server: CoachServer) -> None:
        self.server = server
        self.session: str | None = None

    def request(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        headers: dict[str, str] | None = None,
        start_header: bool = True,
        host: str | None = None,
        with_session: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        sent = {"Host": host or self.server.host_header}
        if method == "POST":
            sent["Content-Type"] = "application/json"
            if start_header:
                sent["X-Wow-Coach"] = "1"
        if with_session and self.session:
            sent["X-Wow-Coach-Session"] = self.session
        sent.update(headers or {})
        data = None if body is None else json.dumps(body)
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, {k.lower(): v for k, v in response.getheaders()}, payload)
        connection.close()
        return result

    def json(
        self, method: str, path: str, body: object = None, **kwargs: object
    ) -> tuple[int, dict]:  # type: ignore[type-arg]
        status, _, payload = self.request(method, path, body, **kwargs)  # type: ignore[arg-type]
        return status, json.loads(payload or b"{}")

    def sign_in_page(self) -> None:
        """Do what the page does: trade the token from the start link for the session secret."""
        token = self.server.start_url().split("#", 1)[1]
        status, body = self.json("POST", "/api/session", {"token": token})
        assert status == 200
        self.session = body["session"]
