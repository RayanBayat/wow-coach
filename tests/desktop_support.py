"""Shared helpers for the desktop app's tests: a fake core and a runner that works at once.

Nothing here touches the network, the keychain or a real game folder. Each test builds a
``FakeCore``, changes ``raw_state`` to what it wants the window to show, and checks what the
window did (``asked``, ``changes``...).
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from wow_coach.app.events import EventBus
from wow_coach.app_settings import AppSettings, update_settings
from wow_coach.desktop.bridge import CoreBridge

KEY = "Testchar-Testrealm"


# The second copy in the one-copy tests: a small separate Python program. It must be a real
# second program: inside one program, the second copy's waiting would also stop the first copy
# from answering (Python runs one thread at a time), so the test would only show a timeout.
_SECOND_COPY_SCRIPT = """
import json, sys
from PySide6.QtCore import QCoreApplication
from wow_coach.desktop.single_instance import SingleInstance
name, environ, message = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3].encode()
app = QCoreApplication([])
print("won" if SingleInstance(name, environ=environ).claim(message) else "told")
"""


def start_second_copy(
    name: str, environ: Mapping[str, str], message: bytes = b"show"
) -> Callable[[], bool]:
    """Start a second copy of the app that sends ``message``; the returned function waits.

    The returned function gives what the second copy's ``claim`` said: True when it won the
    lock (it would have gone on running), False when it told the running copy and exited.
    The test lets Qt process events (``qtbot.waitSignal``) before calling it, so the first
    copy can answer.
    """
    child_environ = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    process = subprocess.Popen(  # noqa: S603 - our own interpreter and our own script
        [
            sys.executable,
            "-c",
            _SECOND_COPY_SCRIPT,
            name,
            json.dumps(dict(environ)),
            message.decode(),
        ],
        env=child_environ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def wait() -> bool:
        out, err = process.communicate(timeout=20)
        if process.returncode != 0:
            raise RuntimeError(f"the second copy failed: {err}")
        return out.strip().endswith("won")

    return wait


def run_now(work: Callable[[], None]) -> None:
    """A ``Runner`` that does the work at once, so tests need no waiting."""
    work()


def sample_answer(
    title: str = "Train your new spells", *, answered_at: int = 2_000
) -> dict[str, object]:
    """One answer dict, shaped like ``views.answer_to_json``."""
    return {
        "title": title,
        "steps": ["Hearth to Brill", "Visit the mage trainer"],
        "text": "At level 12 you can learn Frost Nova rank 2.",
        "warnings": [],
        "source": "ChatGPT",
        "answered_at": answered_at,
        "question": "What now?",
        "question_id": None,
    }


def sample_message(
    content: str,
    *,
    role: str = "user",
    message_id: str,
    seconds: int,
    source: str = "app",
    provider: str | None = None,
    answer: dict[str, object] | None = None,
) -> dict[str, object]:
    """One chat history message, shaped like ``views.message_to_json``."""
    moment = datetime.fromtimestamp(seconds, tz=UTC)
    return {
        "id": message_id,
        "at": moment.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "role": role,
        "content": content,
        "source": source,
        "provider": provider,
        "model": None,
        "answer": answer,
    }


def sample_state(**changes: object) -> dict[str, object]:
    """A full state dict, shaped like ``AppCore.state()``, with optional changes."""
    state: dict[str, object] = {
        "signed_in": True,
        "welcome_pending": False,
        "settings": {"notify": True},
        "characters": [KEY],
        "selected": KEY,
        "answers": [sample_answer()],
        "conversation": [],
        "open_questions": [],
        "usage": {"last_hour": 1, "last_day": 3},
        "last_save": 1_000,
        "alerts": {"notify": True},
        "problem": None,
    }
    state.update(changes)
    return state


@dataclass
class FakeCore:
    """Looks like ``AppCore`` to the bridge, and remembers what was asked of it."""

    raw_state: dict[str, object] = field(default_factory=sample_state)
    busy: bool = False
    open_result: str | None = None  # force what "Answer now" reports (for example "none")
    bus: EventBus = field(default_factory=EventBus)
    settings: AppSettings = field(default_factory=AppSettings)
    asked: list[tuple[str, str | None]] = field(default_factory=list)
    answered_open_for: list[str | None] = field(default_factory=list)
    state_reads: list[str | None] = field(default_factory=list)
    changes: list[dict[str, object]] = field(default_factory=list)
    sign_ins: int = 0
    sign_outs: int = 0
    welcome_dismissed: bool = False

    def state(self, wanted_character: str | None) -> dict[str, object]:
        self.state_reads.append(wanted_character)
        return self.raw_state

    def start_ask(self, question: str, character: str | None) -> bool:
        if self.busy:
            return False
        self.asked.append((question, character))
        return True

    def start_answer_open(self, character: str | None) -> str:
        if self.open_result is not None:
            return self.open_result
        if self.busy:
            return "busy"
        self.answered_open_for.append(character)
        return "started"

    def change_settings(self, changes: dict[str, object]) -> AppSettings:
        self.changes.append(changes)
        self.settings = update_settings(self.settings, changes)
        return self.settings

    def models(self) -> list[dict[str, str]]:
        return [{"slug": "gpt-test-terra", "name": "GPT Test Terra"}]

    def start_sign_in(self) -> bool:
        self.sign_ins += 1
        return True

    def sign_out(self) -> bool:
        self.sign_outs += 1
        return True

    def dismiss_welcome(self) -> None:
        self.welcome_dismissed = True


def make_bridge(core: FakeCore | None = None) -> tuple[CoreBridge, FakeCore]:
    """A bridge over a fake core whose slow work runs at once."""
    fake = core or FakeCore()
    return CoreBridge(fake, runner=run_now), fake
