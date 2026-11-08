"""Tests for desktop notifications. No real program is ever run."""

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from wow_coach import alerts
from wow_coach.alerts import SystemAlerts, clean_text

NASTY = [
    'it\'s "quoted" $(rm -rf ~) `id` ; | & > x',
    "line one\nline two\r\n",
    "-rf --version",
    'say "hi" end run',
    "$env:USERPROFILE; Remove-Item *",
    "<toast><text>x</text></toast>",
]
ALL_PROGRAMS = {"notify-send", "osascript", "powershell"}


class FakeRunner:
    def __init__(self, code: int = 0, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, str], float]] = []
        self.code = code
        self.error = error

    def __call__(self, argv: list[str], env: Mapping[str, str], timeout: float) -> int:
        self.calls.append((argv, dict(env), timeout))
        if self.error:
            raise self.error
        return self.code


def make(
    platform: str, have: set[str] | None = None, runner: FakeRunner | None = None
) -> tuple[SystemAlerts, FakeRunner]:
    programs = ALL_PROGRAMS if have is None else have
    runner = runner or FakeRunner()
    system = SystemAlerts(
        platform=platform,
        which=lambda name: f"/bin/{name}" if name in programs else None,
        runner=runner,
        environ={},  # no SYSTEMROOT: the fake `which` decides, on every real system
    )
    return system, runner


# --- exact commands ---


def test_linux_notify_command() -> None:
    system, runner = make("linux")
    assert system.notify("Title", "Body")
    argv, env, timeout = runner.calls[0]
    assert argv == ["/bin/notify-send", "--app-name=wow-coach", "--", "Title", "Body"]
    assert env == {} and timeout == 5


def test_macos_commands() -> None:
    system, runner = make("darwin")
    assert system.notify("T", "B")
    assert runner.calls[0][0] == [
        "/bin/osascript",
        "-e",
        "on run argv",
        "-e",
        "display notification (item 2 of argv) with title (item 1 of argv)",
        "-e",
        "end run",
        "--",
        "T",
        "B",
    ]


def test_windows_commands_read_text_from_environment() -> None:
    system, runner = make("win32")
    assert system.notify("T", "B")
    argv, env, _ = runner.calls[0]
    assert argv[:4] == ["/bin/powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert argv[4] == alerts.WINDOWS_NOTIFY_SCRIPT
    assert env == {"WOW_COACH_TITLE": "T", "WOW_COACH_TEXT": "B"}
    assert "SecurityElement]::Escape" in alerts.WINDOWS_NOTIFY_SCRIPT


# --- untrusted text ---


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
@pytest.mark.parametrize("nasty", NASTY)
def test_text_only_ever_travels_as_its_own_value(platform: str, nasty: str) -> None:
    system, runner = make(platform)
    system.notify(nasty, nasty)
    texts = {clean_text(nasty, limit) for limit in (60, 240)}
    texts |= {alerts.escape_markup(nasty, limit) for limit in (60, 240)}
    # Every argv item is a fixed word, a fixed script, or exactly the cleaned text.
    fixed_scripts = {alerts.WINDOWS_NOTIFY_SCRIPT, *alerts.MAC_SCRIPT}
    for argv in [call[0] for call in runner.calls]:
        for item in argv:
            if item in fixed_scripts or item.strip() in texts or item.startswith("/bin/"):
                continue
            # anything else is a short fixed option such as "-e" or "--app-name=wow-coach"
            assert item.startswith("-") or ("/" not in item and len(item) < 12), item
            assert not any(text and text in item for text in texts if len(text) > 3), item
    # The fixed scripts never contain the text.
    for script in fixed_scripts:
        assert all(text not in script for text in texts if len(text) > 3)


def test_leading_dash_is_not_an_option() -> None:
    system, runner = make("linux")
    system.notify("-bad", "-worse")
    assert runner.calls[0][0][2] == "--"
    mac, mac_runner = make("darwin")
    mac.notify("-bad", "-worse")
    assert mac_runner.calls[0][0][-3:] == ["--", " -bad", " -worse"]


def test_windows_text_only_in_env_values() -> None:
    system, runner = make("win32")
    text = "$env:X'; calc; '<toast>"
    system.notify(text, text)
    argv, env, _ = runner.calls[0]
    assert all(text not in item for item in argv)
    assert env["WOW_COACH_TEXT"] == text


def test_clean_text_strips_controls_and_caps_length() -> None:
    assert clean_text("a\x00b\x1b[31mc‮d\x7f", 99) == "ab[31mcd"
    assert clean_text("a\nb\tc  d", 99) == "a b c  d"
    assert clean_text("x" * 1000, 60) == "x" * 60


def test_length_caps() -> None:
    system, runner = make("linux")
    system.notify("t" * 500, "b" * 500)
    argv = runner.calls[0][0]
    assert len(argv[-2]) == 60 and len(argv[-1]) == 240


def test_empty_text_is_not_sent() -> None:
    system, runner = make("linux")
    assert not system.notify("\x00", "")
    assert not runner.calls


# --- failures ---


def test_missing_programs_give_false() -> None:
    for platform in ("linux", "darwin", "win32", "plan9"):
        system, runner = make(platform, set())
        assert not system.notify("t", "b")
        assert not runner.calls


def test_timeout_nonzero_and_oserror_give_false() -> None:
    timeout = subprocess.TimeoutExpired("notify-send", 5)
    for runner in (FakeRunner(error=timeout), FakeRunner(code=1), FakeRunner(error=OSError())):
        system, _ = make("linux", runner=runner)
        assert system.notify("t", "b") is False


def test_failure_logs_never_contain_the_text(caplog: pytest.LogCaptureFixture) -> None:
    system, _ = make("linux", runner=FakeRunner(error=OSError("secret-text")))
    system.notify("secret-text", "secret-text")
    assert "notify failed: OSError" in caplog.text
    assert "secret-text" not in caplog.text


# --- availability ---


def test_available() -> None:
    assert make("linux")[0].available() == {"notify": True}
    assert make("linux", set())[0].available() == {"notify": False}
    assert make("win32")[0].available() == {"notify": True}


def test_linux_notification_text_is_escaped_so_it_is_not_markup() -> None:
    system, runner = make("linux")
    system.notify('<b>Hi</b> & <a href="x">C</a>', '<img src="x"> A&B')
    argv = runner.calls[0][0]
    assert argv[-2] == '&lt;b&gt;Hi&lt;/b&gt; &amp; &lt;a href="x"&gt;C&lt;/a&gt;'
    assert argv[-1] == '&lt;img src="x"&gt; A&amp;B'
    assert "<" not in argv[-2] + argv[-1]


def test_escaped_cut_never_splits_an_entity() -> None:
    system, runner = make("linux")
    system.notify("&" * 100, "<" * 500)
    title, body = runner.calls[0][0][-2:]
    assert title == "&amp;" * 12 and len(title) <= 60
    assert body == "&lt;" * 60 and len(body) <= 240


def test_programs_run_by_resolved_path_not_bare_name() -> None:
    for platform in ("linux", "darwin", "win32"):
        system = SystemAlerts(
            platform=platform,
            which=lambda name: f"/found/{name}",
            runner=FakeRunner(),
            environ={},
        )
        command = system._notify_command("t", "b")
        assert command is not None and command[0][0].startswith("/found/")


def test_windows_prefers_the_system32_powershell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    del monkeypatch  # SYSTEMROOT is given directly, not through the real environment
    system = SystemAlerts(
        platform="win32",
        which=lambda name: f"/bin/{name}",
        runner=(runner := FakeRunner()),
        environ={"SYSTEMROOT": str(tmp_path)},
    )
    system.notify("t", "b")
    assert runner.calls[0][0][0] == str(exe)
