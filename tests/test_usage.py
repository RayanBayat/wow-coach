"""Tests for the usage log and the call caps."""

import json
import threading
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


def test_a_cap_of_zero_means_no_calls_not_a_crash(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_hour=0)
    with pytest.raises(PlanLimitReached, match="no calls are allowed"):
        log.check_allowed()
    with pytest.raises(PlanLimitReached):
        log.begin_call("m")
    assert not (tmp_path / "usage.jsonl").exists()


def test_begin_call_counts_the_attempt_and_tokens_lines_are_not_extra_calls(
    tmp_path: Path,
) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_hour=2, clock=Clock())
    log.begin_call("m")
    log.record_tokens("m", Usage(3, 4))
    assert log.calls_in_last(3600) == 1
    log.begin_call("m")  # a second attempt, whatever happens to it
    with pytest.raises(PlanLimitReached):
        log.begin_call("m")


def test_lines_dated_in_the_future_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    future = {"at": "2999-01-01T00:00:00+00:00", "model": "m"}
    path.write_text(json.dumps(future) + "\n")
    log = UsageLog(path, max_calls_per_hour=1, clock=Clock())
    log.check_allowed()  # the far-future line must not count
    assert log.calls_in_last(10**12) == 0


def test_undecodable_bytes_in_the_log_do_not_stop_the_coach(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_bytes(b"\xff\xfe broken \xff\n")
    log = UsageLog(path, max_calls_per_hour=1, clock=Clock())
    log.begin_call("m")
    with pytest.raises(PlanLimitReached):
        log.check_allowed()


def test_parallel_calls_cannot_slip_under_the_cap(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", max_calls_per_hour=3, clock=Clock())
    allowed: list[bool] = []

    def try_call() -> None:
        try:
            log.begin_call("m")
            allowed.append(True)
        except PlanLimitReached:
            allowed.append(False)

    threads = [threading.Thread(target=try_call) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert allowed.count(True) == 3
