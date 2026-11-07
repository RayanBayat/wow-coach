"""Smoke test: the package imports."""

import importlib.metadata

import wow_coach


def test_package_imports() -> None:
    assert wow_coach.__doc__ is not None


def test_installed_version_is_0_2_0() -> None:
    assert importlib.metadata.version("wow-coach") == "0.2.0"


def test_both_command_names_are_installed() -> None:
    names = {entry.name for entry in importlib.metadata.entry_points(group="console_scripts")}
    assert {"wow-coach", "wow-coach-mcp"} <= names
