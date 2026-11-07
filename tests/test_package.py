"""Smoke test: the package imports."""

import importlib.metadata

import wow_coach
from wow_coach.web import build_user_agent


def test_package_imports() -> None:
    assert wow_coach.__doc__ is not None


def test_installed_version_is_0_3_0() -> None:
    assert importlib.metadata.version("wow-coach") == "0.3.0"


def test_both_command_names_are_installed() -> None:
    names = {entry.name for entry in importlib.metadata.entry_points(group="console_scripts")}
    assert {"wow-coach", "wow-coach-mcp"} <= names


def test_wiki_user_agent_names_the_program_and_the_project() -> None:
    agent = build_user_agent()
    assert agent.startswith("wow-coach/0.3.0 ")
    assert "https://github.com/RayanBayat/wow-coach" in agent
