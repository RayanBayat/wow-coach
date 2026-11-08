"""Choose which model on the player's ChatGPT plan answers.

The plan's models come in sizes, named by their last word: ``-sol`` (the largest), ``-terra``
(balanced) and ``-luna`` (small and fast). Every call uses some of the player's plan, so:

* Answers use a balanced model unless the player chose one. A real test (2026-11-08) showed a
  small model misreading the character's quest progress.
* Quick yes-or-no checks (should the coach speak up?) use the small model.
"""

from collections.abc import Sequence

BALANCED_SUFFIX = "-terra"
LARGE_SUFFIX = "-sol"
SMALL_SUFFIX = "-luna"


def _first_ending(available: Sequence[str], suffixes: Sequence[str]) -> str | None:
    for suffix in suffixes:
        for slug in available:
            if slug.endswith(suffix):
                return slug
    return None


def choose_model(available: Sequence[str], preferred: str | None) -> str | None:
    """The model for answers, or None when the plan lists none.

    The player's choice wins if the plan has it. Otherwise a balanced model, then a large
    one, then a small one, then the first one listed.
    """
    if preferred is not None and preferred in available:
        return preferred
    found = _first_ending(available, (BALANCED_SUFFIX, LARGE_SUFFIX, SMALL_SUFFIX))
    return found or (available[0] if available else None)


def choose_small_model(available: Sequence[str]) -> str | None:
    """The model for quick yes-or-no checks: small first, then balanced, then any."""
    found = _first_ending(available, (SMALL_SUFFIX, BALANCED_SUFFIX, LARGE_SUFFIX))
    return found or (available[0] if available else None)
