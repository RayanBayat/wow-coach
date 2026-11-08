"""A release must not ship stale version numbers.

Several places repeat the version: the addon file, the Claude Code agent, and the docs
(``...wow-coach@v0.5.0``). These tests compare them all with the version in pyproject.toml.
"""

import re
import tomllib
from pathlib import Path

from wow_coach.assets import AGENT_PATH, read_asset_text

ROOT = Path(__file__).parent.parent
PIN = re.compile(r"wow-coach@(v[0-9][^\s\"',)`]*)")


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_addon_version_matches_the_project() -> None:
    toc = (ROOT / "addon" / "HeroBridge" / "HeroBridge.toc").read_text(encoding="utf-8")
    match = re.search(r"^## Version:\s*(\S+)", toc, re.MULTILINE)
    assert match is not None
    assert match.group(1) == project_version()


def test_agent_file_pins_this_release() -> None:
    text = read_asset_text(AGENT_PATH)
    pins = set(PIN.findall(text))
    assert pins == {f"v{project_version()}"}


def test_agent_frontmatter_has_what_claude_code_expects() -> None:
    # We avoid a YAML library (one more dependency) and check the lines that matter.
    text = read_asset_text(AGENT_PATH)
    assert text.startswith("---\nname: wow-coach\n")
    header = text.split("\n---\n", 1)[0]
    for line in (
        "skills:",
        "  - wow-coach",
        "mcpServers:",
        "      type: stdio",
        "      command: uvx",
    ):
        assert line in header.splitlines()
    assert 'initialPrompt: "Start my WoW coaching session."' in header
    assert "color: purple" in header
    assert '"wow-coach", "mcp"]' in header
    assert "tools:" not in header  # no tools line: the agent keeps every tool


def test_every_pin_in_the_docs_and_skill_is_this_release() -> None:
    files = [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / "src" / "wow_coach" / "assets").rglob("*.md"),
    ]
    stale: list[str] = []
    for path in files:
        if path.name == "CHANGELOG.md":
            continue  # the changelog talks about old versions on purpose
        for pin in PIN.findall(path.read_text(encoding="utf-8")):
            if pin != f"v{project_version()}":
                stale.append(f"{path.name}: {pin}")
    assert stale == []
