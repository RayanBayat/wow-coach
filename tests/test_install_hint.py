"""The install command the app shows is pinned to the version that is running."""

import importlib.metadata

from wow_coach.desktop.shortcuts import INSTALL_COMMAND
from wow_coach.install_hint import REPOSITORY, install_command


def test_the_command_is_pinned_to_the_running_version() -> None:
    version = importlib.metadata.version("wow-coach")
    expected = f'uv tool install "wow-coach[desktop] @ git+{REPOSITORY}@v{version}"'
    assert install_command() == expected
    assert expected == INSTALL_COMMAND


def test_a_given_version_is_used_as_is() -> None:
    assert install_command("1.2.3").endswith('wow-coach@v1.2.3"')
