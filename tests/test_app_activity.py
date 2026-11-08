"""The core publishes what the coach is doing, and the sources and lookups of an answer."""

from collections.abc import Callable
from pathlib import Path

from test_app_support import KEY, FakeCoach, make_answer, make_rig

from wow_coach.app.core import AppCore
from wow_coach.engine.agent import Activity
from wow_coach.engine.contract import CoachReply
from wow_coach.engine.conversation import Lookup
from wow_coach.engine.sources import SourceLink


class ChattyCoach(FakeCoach):
    """A fake coach that reports an activity while it works, like the real one."""

    listener: Callable[[str, Activity], None] | None = None

    def set_activity_listener(self, listener: Callable[[str, Activity], None]) -> None:
        self.listener = listener


def test_the_core_hands_the_coach_a_listener_that_publishes_activity_events(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    coach = ChattyCoach(rig.wow_dir)
    core = AppCore(
        coach=coach,
        signin=rig.signin,
        alerts=rig.alerts,
        list_models=lambda: [],
        settings_file=rig.settings_file,
        wow_dir=rig.wow_dir,
        usage=rig.core._usage,
    )
    mailbox = core.bus.subscribe()
    assert coach.listener is not None
    coach.listener(KEY, Activity('Searched the Warcraft Wiki for "bears"', "web"))
    event = mailbox.get(timeout=1)
    assert event is not None and event.kind == "activity"
    assert event.data == {
        "character": KEY,
        "text": 'Searched the Warcraft Wiki for "bears"',
        "kind": "web",
    }


def test_a_coach_without_a_listener_setter_is_fine(tmp_path: Path) -> None:
    make_rig(tmp_path)  # FakeCoach has no set_activity_listener: building the core works


def test_a_finished_answer_event_carries_sources_and_lookups(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    mailbox = rig.core.bus.subscribe()
    reply = CoachReply(
        KEY,
        make_answer("Hi", 1_794_000_000),
        True,
        "note",
        sources=(SourceLink("Abigail Shiel", "https://warcraft.wiki.gg/wiki/Abigail_Shiel"),),
        lookups=(Lookup("web", "Read the Warcraft Wiki page"),),
    )
    rig.core.publish_reply(reply)
    event = mailbox.get(timeout=1)
    assert event is not None and event.kind == "answer"
    assert event.data["sources"] == [
        {"title": "Abigail Shiel", "url": "https://warcraft.wiki.gg/wiki/Abigail_Shiel"}
    ]
    assert event.data["lookups"] == [{"kind": "web", "text": "Read the Warcraft Wiki page"}]


def test_an_answer_without_sources_has_empty_lists(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    mailbox = rig.core.bus.subscribe()
    rig.core.publish_reply(CoachReply(KEY, make_answer("Hi", 1_794_000_000), True, "n"))
    event = mailbox.get(timeout=1)
    assert event is not None
    assert event.data["sources"] == [] and event.data["lookups"] == []
