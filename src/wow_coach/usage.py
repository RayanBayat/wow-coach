"""A log of AI calls, and the player's own caps on how many calls are allowed.

Why: the player pays for the AI with their ChatGPT plan, and a coach that asks questions
by itself could use it up. So every call is written as one JSON line to ``usage.jsonl`` in
the data folder (time, model, tokens), and before each call we check two simple caps: calls
per hour and calls per day. Only counts are kept, never the questions or the answers.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from wow_coach.ai.base import PlanLimitReached, Usage

LOG_FILE_NAME = "usage.jsonl"
HOUR_SECONDS = 3600
DAY_SECONDS = 24 * HOUR_SECONDS

_log = logging.getLogger(__name__)


def usage_log_path(data_dir: Path) -> Path:
    """Where the usage log lives inside the data folder."""
    return data_dir / LOG_FILE_NAME


class UsageLog:
    """Writes one line per AI call and enforces the caps."""

    def __init__(
        self,
        path: Path,
        *,
        max_calls_per_hour: int | None = None,
        max_calls_per_day: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create the log.

        Args:
            path: The ``usage.jsonl`` file (created on the first call).
            max_calls_per_hour: Most calls in the last 60 minutes; ``None`` means no cap.
            max_calls_per_day: Most calls in the last 24 hours; ``None`` means no cap.
            clock: Returns the current time in seconds since 1970 (replaced in tests).
        """
        self._path = path
        self._hour_cap = max_calls_per_hour
        self._day_cap = max_calls_per_day
        self._clock = clock

    def check_allowed(self) -> None:
        """Raise ``PlanLimitReached`` if one more call would go over a cap."""
        times = self._call_times()
        now = self._clock()
        self._check_cap(times, now, HOUR_SECONDS, self._hour_cap, "hour")
        self._check_cap(times, now, DAY_SECONDS, self._day_cap, "day")

    def record(self, model: str, usage: Usage) -> None:
        """Add one line for a finished call."""
        line = {
            "at": datetime.fromtimestamp(self._clock(), UTC).isoformat(),
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(line) + "\n")

    def calls_in_last(self, seconds: float) -> int:
        """How many calls were made in the last ``seconds`` seconds."""
        limit = self._clock() - seconds
        return sum(1 for moment in self._call_times() if moment > limit)

    def _check_cap(
        self, times: list[float], now: float, window: int, cap: int | None, name: str
    ) -> None:
        if cap is None:
            return
        recent = sorted(moment for moment in times if moment > now - window)
        if len(recent) < cap:
            return
        # The cap frees up when the oldest call that still counts leaves the window.
        wait = max(1, int(recent[len(recent) - cap] + window - now) + 1)
        raise PlanLimitReached(
            f"You set a limit of {cap} AI calls per {name}, and it is used up. "
            "You can change the limit in the wow-coach settings.",
            retry_after_seconds=wait,
        )

    def _call_times(self) -> list[float]:
        """The time of every logged call. Damaged lines are skipped, not fatal."""
        if not self._path.exists():
            return []
        times: list[float] = []
        for text in self._path.read_text(encoding="utf-8").splitlines():
            moment = _parse_line_time(text)
            if moment is not None:
                times.append(moment)
        return times


def _parse_line_time(text: str) -> float | None:
    try:
        return datetime.fromisoformat(json.loads(text)["at"]).timestamp()
    except ValueError, KeyError, TypeError:
        _log.warning("Skipping a damaged line in the usage log.")
        return None
