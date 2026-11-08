"""The one-line command that installs the WoW Coach app, pinned to this very version.

The app shows it when something is missing (the desktop extra, a stable install for the
shortcuts). Pinning it to the running version gives the player the same release they have,
not whatever is newest on the repository's main branch.
"""

import importlib.metadata
from typing import Final

REPOSITORY: Final = "https://github.com/RayanBayat/wow-coach"


def install_command(version: str | None = None) -> str:
    """``uv tool install "wow-coach[desktop] @ git+<repository>@vX.Y.Z"`` for this version.

    Args:
        version: The version to pin; by default the version of wow-coach that is running.
            Without a known version the command installs the newest one.
    """
    found = version or _running_version()
    pin = f"@v{found}" if found else ""
    return f'uv tool install "wow-coach[desktop] @ git+{REPOSITORY}{pin}"'


def _running_version() -> str | None:
    try:
        return importlib.metadata.version("wow-coach")
    except importlib.metadata.PackageNotFoundError:
        return None  # running from a source folder that was never installed
