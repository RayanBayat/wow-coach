"""``wow-coach app``: the desktop app when Qt is installed, the browser window otherwise."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from wow_coach import cli
from wow_coach.cli import main


class Calls:
    """What the fake desktop and browser windows were asked to do."""

    def __init__(self) -> None:
        self.desktop: list[tuple[Path | None, bool]] = []
        self.browser: list[tuple[Path, int, bool]] = []


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    recorded = Calls()

    def fake_run_desktop(*, wow_dir_flag: Path | None, start_hidden: bool = False) -> int:
        recorded.desktop.append((wow_dir_flag, start_hidden))
        return 0

    def fake_run_app(*, wow_dir: Path, port: int, open_in_browser: bool) -> None:
        recorded.browser.append((wow_dir, port, open_in_browser))

    fake_module = types.ModuleType("wow_coach.desktop.run")
    fake_module.run_desktop = fake_run_desktop  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "wow_coach.desktop.run", fake_module)
    monkeypatch.setattr(cli, "run_app", fake_run_app)
    return recorded


def pretend_qt(monkeypatch: pytest.MonkeyPatch, *, installed: bool) -> None:
    real = importlib.util.find_spec

    def fake_find_spec(name: str, package: str | None = None) -> object | None:
        if name == "PySide6":
            return object() if installed else None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)


@pytest.fixture
def game(tmp_path: Path) -> Path:
    (tmp_path / "WTF").mkdir()
    return tmp_path


def test_the_desktop_app_opens_when_qt_is_installed(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, game: Path
) -> None:
    pretend_qt(monkeypatch, installed=True)
    assert main(["app", "--wow-dir", str(game)]) == 0
    assert calls.desktop == [(game, False)]
    assert calls.browser == []


def test_the_desktop_app_opens_even_when_the_game_folder_is_missing(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, tmp_path: Path
) -> None:
    # The desktop app shows its own "I can't find your game" window, so the command must not
    # fail first. The folder is looked up inside the app.
    pretend_qt(monkeypatch, installed=True)
    missing = tmp_path / "not-there"
    assert main(["app", "--wow-dir", str(missing)]) == 0
    assert calls.desktop == [(missing, False)]


def test_the_browser_window_still_needs_the_game_folder(
    monkeypatch: pytest.MonkeyPatch,
    calls: Calls,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pretend_qt(monkeypatch, installed=True)
    assert main(["app", "--wow-dir", str(tmp_path / "not-there"), "--browser"]) == 1
    assert "does not exist" in capsys.readouterr().err
    assert calls.browser == []


def test_hidden_is_passed_to_the_desktop_app(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, game: Path
) -> None:
    pretend_qt(monkeypatch, installed=True)
    assert main(["app", "--wow-dir", str(game), "--hidden"]) == 0
    assert calls.desktop == [(game, True)]


def test_the_browser_flag_forces_the_browser_window(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, game: Path
) -> None:
    pretend_qt(monkeypatch, installed=True)
    assert main(["app", "--wow-dir", str(game), "--browser"]) == 0
    assert calls.desktop == []
    assert calls.browser == [(game, 0, True)]


def test_port_and_no_browser_keep_working_for_the_browser_window(
    monkeypatch: pytest.MonkeyPatch, calls: Calls, game: Path
) -> None:
    pretend_qt(monkeypatch, installed=True)
    assert main(["app", "--wow-dir", str(game), "--port", "8765", "--no-browser"]) == 0
    assert calls.desktop == []
    assert calls.browser == [(game, 8765, False)]


def test_without_qt_a_friendly_sentence_and_the_browser_window(
    monkeypatch: pytest.MonkeyPatch,
    calls: Calls,
    game: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pretend_qt(monkeypatch, installed=False)
    assert main(["app", "--wow-dir", str(game)]) == 0
    out = capsys.readouterr().out
    assert "The desktop app needs the desktop extra" in out
    assert (
        'uv tool install "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach"' in out
    )
    assert "Opening the browser window instead." in out
    assert calls.desktop == []
    assert calls.browser == [(game, 0, True)]


def test_the_browser_flag_without_qt_prints_no_hint(
    monkeypatch: pytest.MonkeyPatch,
    calls: Calls,
    game: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pretend_qt(monkeypatch, installed=False)
    assert main(["app", "--wow-dir", str(game), "--browser"]) == 0
    assert capsys.readouterr().out == ""
    assert len(calls.browser) == 1
