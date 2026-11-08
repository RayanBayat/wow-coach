"""ChatCoach with tools: settings, redaction, sources, lookups and activity (no network)."""

from collections.abc import Mapping
from pathlib import Path

from test_engine_support import GOOD_REPLY, KEY, NOW, World, make_world

from wow_coach.ai.base import AIError, Answer, FakeProvider, Replay, ToolCall, ToolResult, WebSearch
from wow_coach.app_settings import AppSettings
from wow_coach.engine.agent import Activity
from wow_coach.engine.coach import ChatCoach
from wow_coach.engine.conversation import Lookup, conversation_path, read_messages
from wow_coach.engine.sources import SourceLink

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"
PAGE_URL = "https://warcraft.wiki.gg/wiki/Abigail_Shiel"


def wiki_fetch(_url: str, params: Mapping[str, str]) -> str:
    """Answers like the wiki, from saved real replies."""
    name = "parse_Abigail_Shiel.json" if params["action"] == "parse" else "search_abigail.json"
    return (FIXTURES / name).read_text(encoding="utf-8")


def coach_with(
    world: World,
    provider: FakeProvider,
    settings: AppSettings | None = None,
    activity: list[tuple[str, Activity]] | None = None,
) -> ChatCoach:
    def on_activity(character_key: str, item: Activity) -> None:
        if activity is not None:
            activity.append((character_key, item))

    return ChatCoach(
        provider,
        model="test-luna",
        wow_dir=world.wow_dir,
        environ=world.environ,
        settings=settings or world.settings,
        now=lambda: float(NOW),
        fetch=wiki_fetch,
        on_activity=on_activity,
    )


def call(call_id: str, name: str, **arguments: object) -> Answer:
    item = Replay({"type": "function_call", "call_id": call_id})
    return Answer("", "m", tool_calls=(ToolCall(call_id, name, dict(arguments)),), replay=(item,))


def test_the_ai_is_offered_the_tools_and_web_search_by_default(tmp_path: Path) -> None:
    provider = FakeProvider([GOOD_REPLY])
    coach_with(make_world(tmp_path), provider).ask("hi")
    ask = provider.asks[0]
    assert ask.web_search is True
    assert {spec.name for spec in ask.tools} == {
        "character_status",
        "recent_history",
        "progress_summary",
        "read_coach_notes",
        "save_coach_notes",
        "save_player_notes",
        "search_wiki",
        "read_wiki_page",
        "find_quest",
    }
    system = ask.messages[0].content  # type: ignore[union-attr]
    assert "WHOLE updated text" in system


def test_a_tool_round_uses_the_real_tools_and_keeps_sources_and_lookups(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    provider = FakeProvider([call("c1", "read_wiki_page", title="Abigail Shiel"), GOOD_REPLY])
    activity: list[tuple[str, Activity]] = []
    reply = coach_with(world, provider, activity=activity).ask("Where is Abigail?")
    result = next(m for m in provider.asks[1].messages if isinstance(m, ToolResult))
    assert result.output.startswith("# Abigail Shiel")
    assert reply.sources == (SourceLink("Abigail Shiel", PAGE_URL),)
    assert reply.lookups == (Lookup("web", 'Read the Warcraft Wiki page "Abigail Shiel"'),)
    assert activity == [(KEY, Activity('Read the Warcraft Wiki page "Abigail Shiel"', "web"))]
    stored = read_messages(conversation_path(KEY, environ=world.environ))[-1].answer
    assert stored is not None
    assert stored.sources == reply.sources and stored.lookups == reply.lookups


def test_a_model_written_link_is_never_a_source(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    text = '{"title": "T", "steps": ["See https://evil.example/"], "text": "", "warnings": []}'
    reply = coach_with(world, FakeProvider([text])).ask("hi")
    assert reply.sources == ()


def test_web_citations_become_sources(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    search = WebSearch(("forever mage",), ("https://news.example/a", "file:///etc/passwd"))
    provider = FakeProvider([Answer(GOOD_REPLY, "m", web_searches=(search,))])
    reply = coach_with(world, provider).ask("hi")
    assert reply.sources == (SourceLink("", "https://news.example/a"),)
    assert reply.lookups == (Lookup("web", 'Searched the web for "forever mage"'),)


def test_other_players_names_are_hidden_from_tool_results(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    provider = FakeProvider([call("c1", "recent_history"), GOOD_REPLY])
    coach_with(world, provider).ask("What happened?")
    output = next(m for m in provider.asks[1].messages if isinstance(m, ToolResult)).output
    assert "Zandor" not in output and "Mirela" not in output
    assert "a player" in output


def test_save_tools_are_absent_when_saving_is_off(tmp_path: Path) -> None:
    provider = FakeProvider([GOOD_REPLY])
    coach_with(make_world(tmp_path), provider, AppSettings(save_notes=False)).ask("hi")
    names = {spec.name for spec in provider.asks[0].tools}
    assert "read_coach_notes" in names
    assert not {"save_coach_notes", "save_player_notes"} & names
    system = provider.asks[0].messages[0].content  # type: ignore[union-attr]
    assert "WHOLE updated text" not in system


def test_no_notes_tools_when_the_notes_are_not_shared(tmp_path: Path) -> None:
    provider = FakeProvider([GOOD_REPLY])
    coach_with(make_world(tmp_path), provider, AppSettings(send_coach_notes=False)).ask("hi")
    names = {spec.name for spec in provider.asks[0].tools}
    assert not {"read_coach_notes", "save_coach_notes", "save_player_notes"} & names
    assert "character_status" in names


def test_tools_off_is_the_old_plain_ask(tmp_path: Path) -> None:
    provider = FakeProvider([GOOD_REPLY])
    settings = AppSettings(use_tools=False, web_search=False)
    reply = coach_with(make_world(tmp_path), provider, settings).ask("hi")
    assert provider.asks[0].tools == () and provider.asks[0].web_search is False
    assert "cannot look things up" in provider.asks[0].messages[0].content  # type: ignore[union-attr]
    assert reply.sources == () and reply.lookups == ()


def test_web_search_can_be_off_while_tools_stay_on(tmp_path: Path) -> None:
    provider = FakeProvider([GOOD_REPLY])
    coach_with(make_world(tmp_path), provider, AppSettings(web_search=False)).ask("hi")
    assert provider.asks[0].web_search is False and provider.asks[0].tools


def test_a_failure_with_tools_still_answers_the_old_way(tmp_path: Path) -> None:
    provider = FakeProvider([AIError("tools broke"), GOOD_REPLY])
    reply = coach_with(make_world(tmp_path), provider).ask("hi")
    assert reply.answer.title == "Next steps"
    assert provider.asks[1].tools == ()
