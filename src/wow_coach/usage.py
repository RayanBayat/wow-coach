"""A log of AI calls, so the app can show how many were made recently.

Every call is written as one JSON line to ``usage.jsonl`` in the data folder (time, model,
tokens). wow-coach sets no limit of its own: only the ChatGPT plan's own limit applies.
Only counts are kept, never the questions or the answers.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from wow_coach.ai.base import Usage

LOG_FILE_NAME = "usage.jsonl"
HOUR_SECONDS = 3600
DAY_SECONDS = 24 * HOUR_SECONDS

_log = logging.getLogger(__name__)

# One lock for the whole program, so two parallel writes can't mix their lines.
_LOCK = threading.Lock()


def usage_log_path(data_dir: Path) -> Path:
    """Where the usage log lives inside the data folder."""
    return data_dir / LOG_FILE_NAME


class UsageLog:
    """Writes one line per AI call and counts the recent ones."""

    def __init__(
        self,
        path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create the log.

        Args:
            path: The ``usage.jsonl`` file (created on the first call).
            clock: Returns the current time in seconds since 1970 (replaced in tests).
        """
        self._path = path
        self._clock = clock

    def begin_call(self, model: str) -> None:
        """Count this call at once (before it is sent).

        Counting the ATTEMPT, not only the success, means a call that fails or breaks halfway
        still counts: it may have used some of the plan.
        """
        with _LOCK:
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
