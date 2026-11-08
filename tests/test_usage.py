"""Tests for the usage log."""

import json
import threading
from pathlib import Path

from wow_coach.ai.base import Usage
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


def test_many_calls_are_never_refused_by_wow_coach_itself(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", clock=Clock())
    for _ in range(500):
        log.begin_call("m")
    assert log.calls_in_last(3600) == 500


def test_begin_call_counts_the_attempt_and_tokens_lines_are_not_extra_calls(
    tmp_path: Path,
) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", clock=Clock())
    log.begin_call("m")
    log.record_tokens("m", Usage(3, 4))
    assert log.calls_in_last(3600) == 1
    log.begin_call("m")  # a second attempt, whatever happens to it
    assert log.calls_in_last(3600) == 2


def test_lines_dated_in_the_future_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    future = {"at": "2999-01-01T00:00:00+00:00", "model": "m"}
    path.write_text(json.dumps(future) + "\n")
    log = UsageLog(path, clock=Clock())
    assert log.calls_in_last(10**12) == 0


def test_undecodable_bytes_in_the_log_do_not_stop_the_coach(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_bytes(b"\xff\xfe broken \xff\n")
    log = UsageLog(path, clock=Clock())
    log.begin_call("m")
    assert log.calls_in_last(3600) == 1


def test_parallel_calls_are_all_counted(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl", clock=Clock())
    threads = [threading.Thread(target=log.begin_call, args=("m",)) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert log.calls_in_last(3600) == 12
