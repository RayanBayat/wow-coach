"""Choosing a character from the save file (shared by the CLI, the MCP server and the coach)."""

from wow_coach.savedvars import Character


def snapshot_time(character: Character) -> float:
    """When the character's snapshot was saved (0 if unknown)."""
    saved_at = character.snapshot.get("savedAt")
    return float(saved_at) if isinstance(saved_at, (int, float)) else 0.0


def pick_character(characters: dict[str, Character], wanted: str | None) -> Character | None:
    """Choose a character: the newest snapshot by default, else a case-insensitive match.

    ``wanted`` may be the bare name (``Testchar``) or the full key (``Testchar-Testrealm``).
    Returns None when nothing matches.
    """
    if not characters:
        return None
    if wanted is None:
        return max(characters.values(), key=snapshot_time)
    wanted_lower = wanted.strip().lower()
    for character in characters.values():
        bare_name = character.key.split("-", 1)[0]
        if wanted_lower in (character.key.lower(), bare_name.lower()):
            return character
    return None
