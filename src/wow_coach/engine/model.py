"""Choose which model on the player's ChatGPT plan answers."""

from collections.abc import Sequence

SMALL_MODEL_SUFFIX = "-luna"  # the small, fast models on the plan: cheap for the player's limit


def choose_model(available: Sequence[str], preferred: str | None) -> str | None:
    """The model to use, or None when the plan lists none.

    The player's choice wins if the plan has it. Otherwise the first small model
    (a slug ending in ``-luna``), otherwise the first one listed.
    """
    if preferred is not None and preferred in available:
        return preferred
    for slug in available:
        if slug.endswith(SMALL_MODEL_SUFFIX):
            return slug
    return available[0] if available else None
