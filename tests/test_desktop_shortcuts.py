"""Shortcuts: .desktop files, autostart, Windows .lnk commands and the stable-program rule.

PowerShell is never run: the Windows tests use a fake runner and only look at the command.
"""

from collections.abc import Mapping
from pathlib import Path

import pytest

from wow_coach.desktop import shortcuts
from wow_coach.desktop.shortcuts import (
    ShortcutError,
    ShortcutFolders,
    ShortcutMaker,
    default_folders,
    desktop_entry_text,
    find_stable_program,
    is_supported,
    is_temporary_program,
    overlay_command,
    quote_exec_argument,
    windows_link_command,
)


def make_folders(root: Path) -> ShortcutFolders:
    return ShortcutFolders(root / "apps", root / "autostart", root / "icons" / "wow-coach.svg")


def make_program(root: Path, name: str = "wow-coach-app") -> Path:
    program = root / "bin" / name
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("#!/bin/sh\n")
    return program


# ---- .desktop content and escaping ---------------------------------------------------------


def test_plain_arguments_are_not_quoted() -> None:
    assert quote_exec_argument("/home/me/.local/bin/wow-coach") == "/home/me/.local/bin/wow-coach"


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("/home/my dir/wow-coach", '"/home/my dir/wow-coach"'),
        ('/a/"b"', '"/a/\\"b\\""'),
        ("/a/$HOME", '"/a/\\$HOME"'),
        ("/a/`x`", '"/a/\\`x\\`"'),
        ("C:\\Tools\\wow coach", '"C:\\\\Tools\\\\wow coach"'),
        ("100%", "100%%"),
    ],
)
def test_exec_arguments_are_escaped_per_the_spec(argument: str, expected: str) -> None:
    assert quote_exec_argument(argument) == expected


def test_a_line_break_in_an_argument_is_refused() -> None:
    with pytest.raises(ValueError, match="control"):
        quote_exec_argument("a\nb")


def test_the_desktop_file_content(tmp_path: Path) -> None:
    program = Path("/home/me/my tools/wow-coach-app")
    text = desktop_entry_text(program, ("--hidden",), tmp_path / "wow-coach.svg")
    lines = text.splitlines()
    assert lines[0] == "[Desktop Entry]"
    assert "Type=Application" in lines
    assert "Name=WoW Coach" in lines
    # Quoted for the Exec rules, then every backslash doubled for the file format.
    assert 'Exec="/home/me/my tools/wow-coach-app" --hidden' in lines
    assert f"Icon={tmp_path / 'wow-coach.svg'}" in lines
    assert "Terminal=false" in lines


def test_backslashes_are_doubled_in_the_file() -> None:
    text = desktop_entry_text(Path('/a/"b"/wow-coach-app'), ("app",), Path("/i.svg"))
    assert 'Exec="/a/\\\\"b\\\\"/wow-coach-app" app' in text.splitlines()


# ---- adding and removing on Linux ------------------------------------------------------------


def test_adding_the_menu_entry_writes_the_launcher_and_the_icon(tmp_path: Path) -> None:
    folders = make_folders(tmp_path)
    program = make_program(tmp_path)
    maker = ShortcutMaker(folders, program=program, platform="linux")
    assert not maker.state().in_menu
    maker.set_in_menu(True)
    launcher = folders.menu_dir / "wow-coach.desktop"
    assert f"Exec={program}\n" in launcher.read_text()
    assert folders.icon_file.read_text().startswith("<svg")
    assert maker.state().in_menu
    maker.set_in_menu(False)
    assert not launcher.exists()
    assert not maker.state().in_menu


def test_autostart_toggles_and_starts_hidden(tmp_path: Path) -> None:
    folders = make_folders(tmp_path)
    program = make_program(tmp_path)
    maker = ShortcutMaker(folders, program=program, platform="linux")
    maker.set_at_login(True)
    entry = folders.autostart_dir / "wow-coach.desktop"
    assert f"Exec={program} --hidden" in entry.read_text()
    assert maker.state().at_login
    assert not maker.state().in_menu
    maker.set_at_login(False)
    assert not entry.exists()
    maker.set_at_login(False)  # removing twice is fine


def test_removing_never_needs_a_stable_program(tmp_path: Path) -> None:
    folders = make_folders(tmp_path)
    maker = ShortcutMaker(folders, program=None, platform="linux")
    maker.set_in_menu(False)  # nothing to remove, no error


# ---- the stable program rule -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/home/me/.cache/uv/archive-v0/abc123/bin/wow-coach",
        "/home/me/.cache/uv/builds-v0/.tmpX/bin/wow-coach",
        "C:/Users/me/AppData/Local/uv/cache/archive-v0/x/Scripts/wow-coach.exe",
        "/Users/me/Library/Caches/uv/archive-v0/x/bin/wow-coach",
    ],
)
def test_cache_paths_are_temporary(path: str) -> None:
    assert is_temporary_program(Path(path))


def test_normal_paths_are_stable() -> None:
    assert not is_temporary_program(Path("/home/me/.local/bin/wow-coach"))
    assert not is_temporary_program(Path("/home/me/.local/share/uv/tools/wow-coach/bin/wow-coach"))


def test_a_program_in_a_temp_root_is_temporary(tmp_path: Path) -> None:
    program = make_program(tmp_path)
    assert is_temporary_program(program, [tmp_path])
    assert not is_temporary_program(program, [])


def python_in(root: Path) -> str:
    """A pretend ``sys.executable`` inside an environment folder (``root/bin``)."""
    return str(root / "bin" / "python")


def test_the_program_of_the_running_environment_is_used(tmp_path: Path) -> None:
    program = make_program(tmp_path / "env")
    found = find_stable_program(
        which=lambda _name: None, executable=python_in(tmp_path / "env"), temp_roots=[]
    )
    assert found == program


def test_another_install_on_the_path_is_not_used(tmp_path: Path) -> None:
    # The wow-coach-app on the PATH may be an old copy without Qt; the running one wins.
    mine = make_program(tmp_path / "env")
    other = make_program(tmp_path / "other")
    found = find_stable_program(
        which=lambda _name: str(other), executable=python_in(tmp_path / "env"), temp_roots=[]
    )
    assert found == mine


def test_another_install_is_never_chosen_when_this_one_has_no_program(tmp_path: Path) -> None:
    other = make_program(tmp_path / "other")
    (tmp_path / "env" / "bin").mkdir(parents=True)
    found = find_stable_program(
        which=lambda _name: str(other), executable=python_in(tmp_path / "env"), temp_roots=[]
    )
    assert found is None


def test_a_path_link_into_this_environment_is_accepted(tmp_path: Path) -> None:
    # "uv tool install" puts a link on the PATH that points into the tool's own environment.
    # Only the path link exists as a candidate here: the environment has no script of its own
    # under the python's folder, but the link resolves to a script next to it.
    real = make_program(tmp_path / "env")
    link = tmp_path / "local-bin" / "wow-coach-app"
    link.parent.mkdir()
    link.symlink_to(real)
    found = find_stable_program(
        which=lambda _name: str(link), executable=python_in(tmp_path / "env"), temp_roots=[]
    )
    assert found in (real, link)


def test_the_windows_program_has_the_exe_suffix(tmp_path: Path) -> None:
    scripts = tmp_path / "env" / "bin"
    scripts.mkdir(parents=True)
    exe = scripts / "wow-coach-app.exe"
    exe.write_text("")
    found = find_stable_program(
        which=lambda _name: None,
        executable=str(scripts / "python.exe"),
        platform="win32",
        temp_roots=[],
    )
    assert found == exe


def test_a_cache_program_is_refused(tmp_path: Path) -> None:
    cache = tmp_path / ".cache" / "uv" / "archive-v0" / "abc"
    make_program(cache)
    assert (
        find_stable_program(which=lambda _n: None, executable=python_in(cache), temp_roots=[])
        is None
    )


def test_a_program_in_a_temp_root_is_refused(tmp_path: Path) -> None:
    make_program(tmp_path / "env")
    found = find_stable_program(
        which=lambda _n: None, executable=python_in(tmp_path / "env"), temp_roots=[tmp_path]
    )
    assert found is None


def test_no_stable_program_means_no_file_is_written_and_the_command_is_shown(
    tmp_path: Path,
) -> None:
    folders = make_folders(tmp_path)
    maker = ShortcutMaker(folders, program=None, platform="linux")
    assert maker.needs_stable_program
    with pytest.raises(ShortcutError, match="uv tool install"):
        maker.set_in_menu(True)
    with pytest.raises(ShortcutError):
        maker.set_at_login(True)
    assert not folders.menu_dir.exists()
    assert not folders.autostart_dir.exists()
    assert not folders.icon_file.exists()
    assert shortcuts.INSTALL_COMMAND.startswith("uv tool install")


# ---- Windows ------------------------------------------------------------------------------------


def test_windows_link_command_passes_paths_only_through_the_environment() -> None:
    link = Path("C:/Users/me/Start Menu/Programs/WoW Coach.lnk")
    program = Path("C:/Users/me/.local/bin/wow-coach-app.exe")
    command, env = windows_link_command("powershell.exe", link, program, ("app",), Path("C:/i.ico"))
    assert command[0] == "powershell.exe"
    assert command[1:4] == ["-NoProfile", "-NonInteractive", "-Command"]
    assert command[4] == shortcuts.WINDOWS_LINK_SCRIPT
    for text in (str(link), str(program), "C:/i.ico"):
        assert text not in command[4]
    assert env[shortcuts.LINK_VARIABLE] == str(link)
    assert env[shortcuts.TARGET_VARIABLE] == str(program)
    assert env[shortcuts.ARGUMENTS_VARIABLE] == "app"
    assert env[shortcuts.ICON_VARIABLE] == "C:/i.ico"


def test_windows_shortcuts_are_made_through_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = make_folders(tmp_path)
    calls: list[tuple[list[str], Mapping[str, str]]] = []

    def runner(argv: list[str], env: Mapping[str, str], _timeout: float) -> int:
        calls.append((argv, env))
        return 0

    icons_written: list[Path] = []

    def write_ico(target: Path) -> bool:
        icons_written.append(target)
        return True

    maker = ShortcutMaker(
        folders,
        program=Path("C:/tools/wow-coach-app.exe"),
        platform="win32",
        environ={},
        runner=runner,
        write_ico=write_ico,
    )
    monkeypatch.setattr(shortcuts, "find_powershell", lambda *_args, **_kw: "powershell.exe")
    maker.set_at_login(True)
    assert len(calls) == 1
    argv, env = calls[0]
    assert argv[0] == "powershell.exe"
    assert env[shortcuts.LINK_VARIABLE] == str(folders.autostart_dir / "WoW Coach.lnk")
    assert env[shortcuts.ARGUMENTS_VARIABLE] == "--hidden"
    assert icons_written == [folders.icon_file]


def test_a_failing_powershell_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts, "find_powershell", lambda *_args, **_kw: "powershell.exe")
    maker = ShortcutMaker(
        make_folders(tmp_path),
        program=Path("C:/tools/wow-coach-app.exe"),
        platform="win32",
        runner=lambda _argv, _env, _timeout: 1,
        write_ico=lambda _target: True,
    )
    with pytest.raises(ShortcutError, match="try again"):
        maker.set_in_menu(True)


def test_no_powershell_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts, "find_powershell", lambda *_args, **_kw: None)
    maker = ShortcutMaker(
        make_folders(tmp_path), program=Path("C:/tools/wow-coach-app.exe"), platform="win32"
    )
    with pytest.raises(ShortcutError, match="PowerShell"):
        maker.set_in_menu(True)


def test_find_powershell_prefers_the_system_copy(tmp_path: Path) -> None:
    system_copy = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    system_copy.parent.mkdir(parents=True)
    system_copy.write_text("")
    found = shortcuts.find_powershell({"SYSTEMROOT": str(tmp_path)}, which=lambda _n: "other")
    assert found == str(system_copy)
    assert shortcuts.find_powershell({}, which=lambda _n: "other") == "other"


# ---- where things live --------------------------------------------------------------------------


def test_linux_folders_follow_the_xdg_variables(tmp_path: Path) -> None:
    folders = default_folders({"XDG_DATA_HOME": "/d", "XDG_CONFIG_HOME": "/c"}, "linux", tmp_path)
    assert folders is not None
    assert folders.menu_dir == Path("/d/applications")
    assert folders.autostart_dir == Path("/c/autostart")
    assert folders.icon_file == Path("/d/icons/hicolor/scalable/apps/wow-coach.svg")


def test_linux_folders_default_to_the_home_folder(tmp_path: Path) -> None:
    folders = default_folders({}, "linux", tmp_path)
    assert folders is not None
    assert folders.menu_dir == tmp_path / ".local" / "share" / "applications"
    assert folders.autostart_dir == tmp_path / ".config" / "autostart"


def test_windows_folders(tmp_path: Path) -> None:
    folders = default_folders({"APPDATA": "/r", "LOCALAPPDATA": "/l"}, "win32", tmp_path)
    assert folders is not None
    assert folders.autostart_dir == Path("/r/Microsoft/Windows/Start Menu/Programs/Startup")
    assert folders.icon_file == Path("/l/wow-coach/wow-coach.ico")


def test_macos_is_not_supported(tmp_path: Path) -> None:
    assert default_folders({}, "darwin", tmp_path) is None
    assert not is_supported("darwin")
    assert is_supported("linux")
    assert is_supported("win32")


def test_the_overlay_command_uses_the_stable_program() -> None:
    program = Path("/home/me/.local/bin/wow-coach-app")
    assert overlay_command(program, "linux") == "/home/me/.local/bin/wow-coach-app --toggle-overlay"


def test_the_overlay_command_quotes_for_the_system() -> None:
    spaced = Path("/home/my name/wow-coach-app")
    assert overlay_command(spaced, "linux") == "'/home/my name/wow-coach-app' --toggle-overlay"
    windows = Path("C:/Users/My Name/wow-coach-app.exe")
    expected = '"C:/Users/My Name/wow-coach-app.exe" --toggle-overlay'
    assert overlay_command(windows, "win32") == expected


def test_the_overlay_command_without_a_stable_program_is_the_bare_name() -> None:
    assert overlay_command(None, "linux") == "wow-coach-app --toggle-overlay"
