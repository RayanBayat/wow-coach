"""Tests for desktop notifications and read-aloud. No real program is ever run."""

import subprocess
from collections.abc import Mapping

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
ALL_PROGRAMS = {"notify-send", "spd-say", "osascript", "say", "powershell"}


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


class FakeProcess:
    def __init__(self) -> None:
        self.running = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False


class FakePopen:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str], str | None]] = []
        self.processes: list[FakeProcess] = []

    def __call__(
        self, argv: list[str], env: Mapping[str, str], stdin_text: str | None
    ) -> FakeProcess:
        self.calls.append((argv, dict(env), stdin_text))
        process = FakeProcess()
        self.processes.append(process)
        return process


def make(
    platform: str, have: set[str] | None = None, runner: FakeRunner | None = None
) -> tuple[SystemAlerts, FakeRunner, FakePopen]:
    programs = ALL_PROGRAMS if have is None else have
    runner = runner or FakeRunner()
    popen = FakePopen()
    system = SystemAlerts(
        platform=platform,
        which=lambda name: f"/bin/{name}" if name in programs else None,
        runner=runner,
        popen=popen,
    )
    return system, runner, popen


# --- exact commands ---


def test_linux_notify_command() -> None:
    system, runner, _ = make("linux")
    assert system.notify("Title", "Body")
    argv, env, timeout = runner.calls[0]
    assert argv == ["notify-send", "--app-name=wow-coach", "--", "Title", "Body"]
    assert env == {} and timeout == 5


def test_linux_speak_prefers_spd_say() -> None:
    system, _, popen = make("linux")
    assert system.speak("hello")
    assert popen.calls == [(["spd-say", "--", "hello"], {}, None)]


def test_linux_speak_falls_back_to_espeak_with_stdin() -> None:
    system, _, popen = make("linux", {"espeak-ng"})
    assert system.speak("hello")
    assert popen.calls == [(["espeak-ng", "--stdin"], {}, "hello")]


def test_macos_commands() -> None:
    system, runner, popen = make("darwin")
    assert system.notify("T", "B") and system.speak("hello")
    assert runner.calls[0][0] == [
        "osascript",
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
    assert popen.calls == [(["say", "-f", "-"], {}, "hello")]


def test_windows_commands_read_text_from_environment() -> None:
    system, runner, popen = make("win32")
    assert system.notify("T", "B") and system.speak("hello")
    argv, env, _ = runner.calls[0]
    assert argv[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert argv[4] == alerts.WINDOWS_NOTIFY_SCRIPT
    assert env == {"WOW_COACH_TITLE": "T", "WOW_COACH_TEXT": "B"}
    speak_argv, speak_env, speak_stdin = popen.calls[0]
    assert speak_argv[4] == alerts.WINDOWS_SPEAK_SCRIPT
    assert speak_env == {"WOW_COACH_TEXT": "hello"} and speak_stdin is None
    assert "SecurityElement]::Escape" in alerts.WINDOWS_NOTIFY_SCRIPT


# --- untrusted text ---


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
@pytest.mark.parametrize("nasty", NASTY)
def test_text_only_ever_travels_as_its_own_value(platform: str, nasty: str) -> None:
    system, runner, popen = make(platform)
    system.notify(nasty, nasty)
    system.speak(nasty)
    texts = {clean_text(nasty, limit) for limit in (60, 240, 600)}
    # Every argv item is a fixed word, a fixed script, or exactly the cleaned text.
    fixed_scripts = {alerts.WINDOWS_NOTIFY_SCRIPT, alerts.WINDOWS_SPEAK_SCRIPT, *alerts.MAC_SCRIPT}
    all_argv = [call[0] for call in runner.calls] + [call[0] for call in popen.calls]
    for argv in all_argv:
        for item in argv:
            if item in fixed_scripts or item.strip() in texts:
                continue
            # anything else is a short fixed option such as "-e" or "--app-name=wow-coach"
            assert item.startswith("-") or ("/" not in item and len(item) < 12), item
            assert not any(text and text in item for text in texts if len(text) > 3), item
    # The fixed scripts never contain the text.
    for script in fixed_scripts:
        assert all(text not in script for text in texts if len(text) > 3)


def test_leading_dash_is_not_an_option() -> None:
    system, runner, popen = make("linux")
    system.notify("-bad", "-worse")
    system.speak("-rf")
    assert runner.calls[0][0][2] == "--"
    assert popen.calls[0][0][:2] == ["spd-say", "--"]
    mac, mac_runner, _ = make("darwin")
    mac.notify("-bad", "-worse")
    assert mac_runner.calls[0][0][-3:] == ["--", " -bad", " -worse"]


def test_windows_text_only_in_env_values() -> None:
    system, runner, _ = make("win32")
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
    system, runner, popen = make("linux")
    system.notify("t" * 500, "b" * 500)
    system.speak("s" * 5000)
    argv = runner.calls[0][0]
    assert len(argv[-2]) == 60 and len(argv[-1]) == 240
    assert len(popen.calls[0][0][-1]) == 600


def test_empty_text_is_not_sent() -> None:
    system, runner, popen = make("linux")
    assert not system.notify("\x00", "") and not system.speak("\n\x07")
    assert not runner.calls and not popen.calls


# --- failures ---


def test_missing_programs_give_false() -> None:
    for platform in ("linux", "darwin", "win32", "plan9"):
        system, runner, popen = make(platform, set())
        assert not system.notify("t", "b") and not system.speak("x")
        assert not runner.calls and not popen.calls


def test_timeout_nonzero_and_oserror_give_false() -> None:
    timeout = subprocess.TimeoutExpired("notify-send", 5)
    for runner in (FakeRunner(error=timeout), FakeRunner(code=1), FakeRunner(error=OSError())):
        system, _, _ = make("linux", runner=runner)
        assert system.notify("t", "b") is False


def test_speak_failure_gives_false() -> None:
    def boom(*_: object) -> FakeProcess:
        raise OSError("no")

    system = SystemAlerts(platform="linux", which=lambda n: n, runner=FakeRunner(), popen=boom)
    assert system.speak("hi") is False


def test_failure_logs_never_contain_the_text(caplog: pytest.LogCaptureFixture) -> None:
    system, _, _ = make("linux", runner=FakeRunner(error=OSError("secret-text")))
    system.notify("secret-text", "secret-text")
    assert "notify failed: OSError" in caplog.text
    assert "secret-text" not in caplog.text


# --- one voice at a time, availability ---


def test_second_speak_stops_the_first() -> None:
    system, _, popen = make("linux")
    system.speak("one")
    system.speak("two")
    assert popen.processes[0].terminated and not popen.processes[1].terminated


def test_finished_speech_is_not_terminated() -> None:
    system, _, popen = make("linux")
    system.speak("one")
    popen.processes[0].running = False
    system.speak("two")
    assert not popen.processes[0].terminated


def test_available() -> None:
    assert make("linux")[0].available() == {"notify": True, "speak": True}
    assert make("linux", {"espeak-ng"})[0].available() == {"notify": False, "speak": True}
    assert make("darwin", set())[0].available() == {"notify": False, "speak": False}
    assert make("win32")[0].available() == {"notify": True, "speak": True}
