"""Error types for wow-coach.

Every error this project raises on purpose inherits from `WowCoachError`, so callers
(like the MCP server) can catch one class and turn it into a friendly message.
"""


class WowCoachError(Exception):
    """Root of all wow-coach errors."""


class LuaParseError(WowCoachError):
    """The SavedVariables text is not valid Lua data."""


class CoachDataMissing(WowCoachError):  # noqa: N818  (name is part of the requested API)
    """The CoachLink data file was not found."""


class UnsupportedFormat(WowCoachError):  # noqa: N818
    """The data file has a formatVersion this reader does not understand."""


class GameFolderNotFound(WowCoachError):  # noqa: N818
    """The World of Warcraft: Forever folder (the one containing WTF/) could not be found."""


class NotesTooLarge(WowCoachError):  # noqa: N818
    """The coach notes the AI tried to save are bigger than the allowed size."""


class LookupFailed(WowCoachError):  # noqa: N818
    """A website did not give us an answer (timeout, network problem, error status)."""
