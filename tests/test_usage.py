"""Tests for the usage log and the call caps."""

import json
from pathlib import Path

import pytest

from wow_coach.ai.base import PlanLimitReached, Usage
from wow_coach.usage import UsageLog, usage_log_path


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def test_record_writes_one_json_line_per_call(tmp_path: Path) -> None:
    log = UsageLog(usage_log_path(tmp_path / "data"), clock=Clock())
    log.record("gpt-x", Usage(5, 7))
    log.record("gpt-y", Usage())
    lines = (tmp_path / "data" / "usage.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert (first["model"], first["input_tokens"], first["output_tokens"]) == ("gpt-x", 5, 7)


def test_log_holds_only_counts_never_text(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", clock=Clock())
    log.record("gpt-x", Usage(1, 1))
    line = json.loads((tmp_path / "usage.jsonl").read_text())
    assert set(line) == {"at", "model", "input_tokens", "output_tokens"}


def test_no_caps_means_always_allowed(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", clock=Clock())
    for _ in range(50):
        log.record("m", Usage())
    log.check_allowed()


def test_hour_cap_stops_and_says_when_to_retry(tmp_path: Path) -> None:
    clock = Clock()
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_hour=2, clock=clock)
    log.record("m", Usage())
    clock.now += 600
    log.record("m", Usage())
    with pytest.raises(PlanLimitReached) as caught:
        log.check_allowed()
    assert "2 AI calls per hour" in str(caught.value)
    # The first call leaves the one-hour window 3000 seconds from now.
    assert caught.value.retry_after_seconds == 3001


def test_cap_frees_up_when_old_calls_age_out(tmp_path: Path) -> None:
    clock = Clock()
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_hour=1, clock=clock)
    log.record("m", Usage())
    clock.now += 3601
    log.check_allowed()
    assert log.calls_in_last(3600) == 0


def test_day_cap(tmp_path: Path) -> None:
    clock = Clock()
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_day=3, clock=clock)
    for _ in range(3):
        log.record("m", Usage())
        clock.now += 4000  # spread out, so no hour cap would matter
    with pytest.raises(PlanLimitReached, match="per day"):
        log.check_allowed()


def test_damaged_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_text("not json\n{}\n")
    log = UsageLog(path, max_calls_per_hour=1, clock=Clock())
    log.check_allowed()
    log.record("m", Usage())
    with pytest.raises(PlanLimitReached):
        log.check_allowed()
