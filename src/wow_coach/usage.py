"""A log of AI calls, and the player's own caps on how many calls are allowed.

Why: the player pays for the AI with their ChatGPT plan, and a coach that asks questions
by itself could use it up. So every call is written as one JSON line to ``usage.jsonl`` in
the data folder (time, model, tokens), and before each call we check two simple caps: calls
per hour and calls per day. Only counts are kept, never the questions or the answers.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from wow_coach.ai.base import PlanLimitReached, Usage

LOG_FILE_NAME = "usage.jsonl"
HOUR_SECONDS = 3600
DAY_SECONDS = 24 * HOUR_SECONDS

_log = logging.getLogger(__name__)

# One lock for the whole program, so two parallel calls can't both slip under a cap.
_LOCK = threading.Lock()


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
        with _LOCK:
            self._check_allowed_locked()

    def begin_call(self, model: str) -> None:
        """Check the caps, then count this call at once (before it is sent).

        Counting the ATTEMPT, not only the success, means a call that fails or breaks halfway
        still counts: it may have used some of the plan. The check and the count happen under
        one lock, so parallel calls can't both slip under a cap.

        Raises:
            PlanLimitReached: A cap is used up (nothing is counted then).
        """
        with _LOCK:
            self._check_allowed_locked()
            self._append(self._line(model, Usage(), tokens_only=False))

    def record_tokens(self, model: str, usage: Usage) -> None:
        """Add the token numbers of a call that ``begin_call`` already counted."""
        with _LOCK:
            self._append(self._line(model, usage, tokens_only=True))

    def record(self, model: str, usage: Usage) -> None:
        """Count one finished call together with its token numbers."""
        with _LOCK:
            self._append(self._line(model, usage, tokens_only=False))

    def calls_in_last(self, seconds: float) -> int:
        """How many calls were made in the last ``seconds`` seconds."""
        now = self._clock()
        return sum(1 for moment in self._call_times() if now - seconds < moment <= now)

    def _check_allowed_locked(self) -> None:
        times = self._call_times()
        now = self._clock()
        self._check_cap(times, now, HOUR_SECONDS, self._hour_cap, "hour")
        self._check_cap(times, now, DAY_SECONDS, self._day_cap, "day")

    def _line(self, model: str, usage: Usage, *, tokens_only: bool) -> dict[str, object]:
        line: dict[str, object] = {
            "at": datetime.fromtimestamp(self._clock(), UTC).isoformat(),
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        if tokens_only:
            line["tokens_only"] = True  # numbers for an earlier counted call: not a new call
        return line

    def _append(self, line: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(line) + "\n")

    def _check_cap(
        self, times: list[float], now: float, window: int, cap: int | None, name: str
    ) -> None:
        if cap is None:
            return
        if cap <= 0:
            raise PlanLimitReached(
                f"You set a limit of 0 AI calls per {name}, so no calls are allowed. "
                "You can change the limit in the wow-coach settings."
            )
        recent = sorted(moment for moment in times if now - window < moment <= now)
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
        """The time of every counted call. Damaged lines and future dates are skipped."""
        if not self._path.exists():
            return []
        times: list[float] = []
        limit = self._clock()
        # errors="replace": a damaged byte must not stop the coach from working
        text = self._path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            moment = _parse_line_time(line)
            if moment is not None and moment <= limit:
                times.append(moment)
        return times


def _parse_line_time(text: str) -> float | None:
    """The time of a line that counts as a call, else ``None`` (damaged or tokens-only)."""
    try:
        data = json.loads(text)
        if data.get("tokens_only") is True:
            return None
        return datetime.fromisoformat(data["at"]).timestamp()
    except ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError:
        _log.warning("Skipping a damaged line in the usage log.")
        return None
