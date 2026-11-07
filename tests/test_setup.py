"""Tests for ``wow-coach setup`` (fake folders, fake downloads, fake keyboard)."""

import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from wow_coach.assets import AGENT_PATH, SKILL_PATH, read_asset
from wow_coach.config import config_path, load_saved_wow_dir
from wow_coach.errors import LookupFailed
from wow_coach.setup import RELEASE_URL, SetupChoices, SetupWorld, run_setup

VERSION = "9.9.9"
NO_CHOICES = SetupChoices(wow_dir_flag=None, assume_yes=False, claude_code=False, skip_addon=False)


def make_zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def addon_zip(version: str = VERSION) -> bytes:
    return make_zip(
        {
            "CoachLink/CoachLink.toc": f"## Title: CoachLink\n## Version: {version}\n",
            "CoachLink/CoachLink.lua": "-- addon code\n",
        }
    )


class Session:
    """One fake computer: a game folder, a home folder, a data folder and a keyboard."""

    def __init__(self, root: Path, answers: list[str] | None = None) -> None:
        self.game = root / "game"
        (self.game / "WTF").mkdir(parents=True)
        self.home = root / "home"
        self.home.mkdir()
        self.environ = {
            "WOW_COACH_CONFIG_FILE": str(root / "data" / "config.json"),
            "WOW_COACH_NOTES_FILE": str(root / "data" / "coach-notes.md"),
        }
        self.out = io.StringIO()
        self.downloaded: list[str] = []
        self.zip_bytes = addon_zip()
        self.download_error: Exception | None = None
        self.answers = list(answers or [])
        self.questions: list[str] = []

    def download(self, url: str) -> bytes:
        self.downloaded.append(url)
        if self.download_error is not None:
            raise self.download_error
        return self.zip_bytes

    def ask(self, question: str) -> str:
        self.questions.append(question)
        return self.answers.pop(0) if self.answers else ""

    def world(self, candidates: list[Path] | None = None, interactive: bool = True) -> SetupWorld:
        return SetupWorld(
            environ=self.environ,
            candidates=[self.game] if candidates is None else candidates,
            home=self.home,
            package_version=VERSION,
            download=self.download,
            ask=self.ask,
            interactive=interactive,
            now=1_000_000.0,
            out=self.out,
        )

    def run(self, choices: SetupChoices = NO_CHOICES, **world_options: object) -> tuple[int, str]:
        world = self.world(**world_options)  # type: ignore[arg-type]
        code = run_setup(choices, world)
        return code, self.out.getvalue()

    @property
    def addon(self) -> Path:
        return self.game / "Interface" / "AddOns" / "CoachLink"


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(tmp_path)


def test_fresh_setup_installs_everything_and_remembers_the_folder(session: Session) -> None:
    code, text = session.run()
    assert code == 0
    assert (session.addon / "CoachLink.toc").is_file()
    assert session.downloaded == [RELEASE_URL.format(v=VERSION)]
    assert load_saved_wow_dir(config_path(environ=session.environ)) == session.game
    assert "# Player notes" in Path(session.environ["WOW_COACH_NOTES_FILE"]).read_text("utf-8")
    assert "quit WoW completely" in text
    assert "PROBLEM" not in text
    assert "Setup finished. No problems." in text
    assert "Step 1 of 5" in text
    assert "Step 5 of 5" in text


def test_fresh_setup_does_not_contradict_itself(session: Session) -> None:
    # No save file exists yet on a new install; that must not read like a failure.
    _, text = session.run()
    assert "Fix the problem above" not in text
    assert "normal on a new install" in text


def test_second_run_changes_nothing_and_downloads_nothing(session: Session) -> None:
    session.run()
    session.downloaded.clear()
    code, text = session.run()
    assert code == 0
    assert session.downloaded == []
    assert f"CoachLink {VERSION} is already installed" in text
    assert "did not touch it" in text


def test_older_addon_is_replaced_and_the_old_copy_removed(session: Session) -> None:
    session.addon.mkdir(parents=True)
    (session.addon / "CoachLink.toc").write_text("## Version: 0.1.0\n", encoding="utf-8")
    (session.addon / "stale.lua").write_text("old", encoding="utf-8")
    code, _ = session.run()
    assert code == 0
    assert "Version: 9.9.9" in (session.addon / "CoachLink.toc").read_text("utf-8")
    assert not (session.addon / "stale.lua").exists()
    leftovers = [item.name for item in session.addon.parent.iterdir()]
    assert leftovers == ["CoachLink"]


def test_a_linked_addon_is_left_alone(session: Session, tmp_path: Path) -> None:
    developer_copy = tmp_path / "dev" / "CoachLink"
    developer_copy.mkdir(parents=True)
    session.addon.parent.mkdir(parents=True)
    try:
        session.addon.symlink_to(developer_copy, target_is_directory=True)
    except OSError:
        pytest.skip("this system does not allow creating symbolic links")
    code, text = session.run()
    assert code == 0
    assert "is a link" in text
    assert session.downloaded == []


@pytest.mark.parametrize(
    "bad_name", ["../evil.lua", "CoachLink/../../evil.lua", "/abs/evil.lua", "Other/x.lua"]
)
def test_unsafe_zip_is_refused_and_nothing_is_written(session: Session, bad_name: str) -> None:
    session.zip_bytes = make_zip({"CoachLink/CoachLink.toc": "## Version: 9.9.9\n", bad_name: "x"})
    code, text = session.run()
    assert code == 1
    assert "unsafe entry" in text
    assert not session.addon.exists()
    assert not (session.game.parent / "evil.lua").exists()
    assert [item.name for item in (session.game / "Interface" / "AddOns").iterdir()] == []


def test_zip_without_the_toc_file_is_refused(session: Session) -> None:
    session.zip_bytes = make_zip({"CoachLink/CoachLink.lua": "x"})
    code, text = session.run()
    assert code == 1
    assert "CoachLink.toc" in text


def test_not_a_zip_is_refused(session: Session) -> None:
    session.zip_bytes = b"<html>not a zip</html>"
    code, text = session.run()
    assert code == 1
    assert "not a valid zip" in text


def test_failed_download_explains_the_manual_install(session: Session) -> None:
    session.download_error = LookupFailed("network error")
    code, text = session.run()
    assert code == 1
    assert "PROBLEM" in text
    assert "install-the-addon.md" in text
    assert "network error" in text


def test_failed_swap_keeps_the_old_addon_working(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.addon.mkdir(parents=True)
    (session.addon / "CoachLink.toc").write_text("## Version: 0.1.0\n", encoding="utf-8")
    real_rename = Path.rename

    def failing_rename(self: Path, target: Path) -> Path:
        if self.name == "CoachLink" and self.parent.name == ".CoachLink-new":
            raise PermissionError("pretend the folder is locked")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)
    code, text = session.run()
    assert code == 1
    assert "PROBLEM" in text
    assert "Version: 0.1.0" in (session.addon / "CoachLink.toc").read_text("utf-8")


def test_skip_addon_installs_no_addon(session: Session) -> None:
    code, text = session.run(replace(NO_CHOICES, skip_addon=True))
    assert code == 0
    assert not session.addon.exists()
    assert "--skip-addon" in text


def test_existing_notebook_is_never_overwritten(session: Session) -> None:
    notebook = Path(session.environ["WOW_COACH_NOTES_FILE"])
    notebook.parent.mkdir(parents=True)
    notebook.write_text("my precious notes", encoding="utf-8")
    session.run()
    assert notebook.read_text("utf-8") == "my precious notes"


def test_game_not_found_asks_for_the_path_and_validates_it(session: Session) -> None:
    pasted = f'  "{session.game}"  '  # Windows "Copy as path" adds quotes
    session.answers = [str(session.game.parent / "nowhere"), pasted]
    code, text = session.run(candidates=[])
    assert code == 0
    assert "has no WTF folder" in text
    assert load_saved_wow_dir(config_path(environ=session.environ)) == session.game
    assert len(session.questions) == 2


def test_game_not_found_with_yes_stops_without_asking(session: Session) -> None:
    code, text = session.run(replace(NO_CHOICES, assume_yes=True), candidates=[])
    assert code == 1
    assert session.questions == []
    assert "PROBLEM" in text
    assert "Stopped" in text


def test_game_not_found_and_player_gives_up(session: Session) -> None:
    session.answers = [""]
    code, text = session.run(candidates=[])
    assert code == 1
    assert "no game folder chosen" in text


def test_wow_dir_flag_without_wtf_is_a_problem(session: Session, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    code, text = session.run(replace(NO_CHOICES, wow_dir_flag=empty))
    assert code == 1
    assert "no WTF folder" in text


def test_saved_folder_is_used_on_the_next_run(session: Session) -> None:
    session.run()
    code, text = session.run(candidates=[])  # auto-detect would find nothing now
    assert code == 0
    assert "saved setting" in text


def read_claude_files(home: Path) -> tuple[Path, Path]:
    return home / ".claude" / "agents" / "wow-coach.md", (
        home / ".claude" / "skills" / "wow-coach" / "SKILL.md"
    )


def test_claude_code_flag_installs_agent_and_skill(session: Session) -> None:
    code, text = session.run(replace(NO_CHOICES, claude_code=True))
    agent, skill = read_claude_files(session.home)
    assert code == 0
    assert agent.read_bytes() == read_asset(AGENT_PATH)
    assert skill.read_bytes() == read_asset(SKILL_PATH)
    assert "claude --agent wow-coach" in text


def test_different_claude_file_is_backed_up_before_replacing(session: Session) -> None:
    agent, _ = read_claude_files(session.home)
    agent.parent.mkdir(parents=True)
    agent.write_text("my own agent", encoding="utf-8")
    session.run(replace(NO_CHOICES, claude_code=True))
    assert agent.with_name("wow-coach.md.bak").read_text("utf-8") == "my own agent"
    assert agent.read_bytes() == read_asset(AGENT_PATH)


def test_linked_claude_file_is_left_alone(session: Session, tmp_path: Path) -> None:
    agent, _ = read_claude_files(session.home)
    agent.parent.mkdir(parents=True)
    real = tmp_path / "dev-agent.md"
    real.write_text("developer agent", encoding="utf-8")
    try:
        agent.symlink_to(real)
    except OSError:
        pytest.skip("this system does not allow creating symbolic links")
    _, text = session.run(replace(NO_CHOICES, claude_code=True))
    assert real.read_text("utf-8") == "developer agent"
    assert "is a link" in text


def test_claude_is_not_installed_without_consent_or_flag(session: Session) -> None:
    (session.home / ".claude").mkdir()
    session.answers = ["n"]
    session.run()
    assert not read_claude_files(session.home)[0].exists()
    assert any("Claude Code found" in question for question in session.questions)


def test_interactive_yes_installs_claude_files(session: Session) -> None:
    (session.home / ".claude").mkdir()
    session.answers = [""]  # Enter means yes
    session.run()
    assert read_claude_files(session.home)[0].is_file()


def test_yes_flag_does_not_install_claude_without_the_claude_code_flag(session: Session) -> None:
    (session.home / ".claude").mkdir()
    session.run(replace(NO_CHOICES, assume_yes=True))
    assert not read_claude_files(session.home)[0].exists()
    assert session.questions == []


def test_nothing_is_written_outside_the_allowed_places(session: Session, tmp_path: Path) -> None:
    session.run(replace(NO_CHOICES, claude_code=True))
    top_level = {item.name for item in tmp_path.iterdir()}
    assert top_level == {"game", "home", "data"}


def test_setup_transcript_is_plain_words(session: Session) -> None:
    _, text = session.run(replace(NO_CHOICES, claude_code=True))
    print(text)  # shown with pytest -s; copied into the release notes
    assert text.count("OK:") >= 5
