"""The Claude Code files that ship inside the wow-coach package.

They live in ``src/wow_coach/assets/`` so that ``pip`` and ``uvx`` installs carry them along,
and ``wow-coach setup --claude-code`` can copy them to the player's ``~/.claude`` folder.
"""

import importlib.resources

AGENT_PATH = "agents/wow-coach.md"
SKILL_PATH = "skills/wow-coach/SKILL.md"


def read_asset(relative_path: str) -> bytes:
    """The bytes of a packaged file, for example ``read_asset(SKILL_PATH)``."""
    resource = importlib.resources.files("wow_coach") / "assets"
    for part in relative_path.split("/"):
        resource = resource / part
    return resource.read_bytes()


def notebook_template() -> str:
    """The empty coach notebook, taken from the template at the end of the skill."""
    skill = read_asset(SKILL_PATH).decode("utf-8")
    after_heading = skill.split("## Notebook template", 1)[1]
    fence_start = "```markdown\n"
    body = after_heading.split(fence_start, 1)[1]
    return body.split("\n```", 1)[0] + "\n"
