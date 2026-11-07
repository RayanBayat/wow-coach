"""Smoke test: the package imports."""

import importlib.metadata
import tomllib
from pathlib import Path

import wow_coach
from wow_coach.web import build_user_agent

ROOT = Path(__file__).parent.parent


def test_package_imports() -> None:
    assert wow_coach.__doc__ is not None


def test_installed_version_is_the_one_in_pyproject() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert importlib.metadata.version("wow-coach") == data["project"]["version"]


def test_both_command_names_are_installed() -> None:
    names = {entry.name for entry in importlib.metadata.entry_points(group="console_scripts")}
    assert {"wow-coach", "wow-coach-mcp"} <= names


def test_wiki_user_agent_names_the_program_and_the_project() -> None:
    agent = build_user_agent()
    assert agent.startswith(f"wow-coach/{importlib.metadata.version('wow-coach')} ")
    assert "https://github.com/RayanBayat/wow-coach" in agent
