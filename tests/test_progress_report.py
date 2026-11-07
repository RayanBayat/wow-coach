"""Tests for format_progress: the plain-words summary of the progress log."""

from wow_coach.report import Table, format_progress

NOW = 1_000_000.0
HOUR = 3600
DAY = 86_400


def point(seconds_ago: float, level: int, xp: int, money: int, sub_zone: str = "Brill") -> Table:
    return {
        "time": NOW - seconds_ago,
        "reason": "logout",
        "level": level,
        "xp": xp,
        "xpMax": 1000,
        "money": money,
        "zone": "Tirisfal Glades",
        "subZone": sub_zone,
        "questsDone": 0,
    }


def event(seconds_ago: float, kind: str) -> Table:
    return {"time": NOW - seconds_ago, "kind": kind, "text": kind}


# Three sessions. Session 1: 1 h, level 5. Session 2: 2 h, level 6. Session 3: 1 h, still 6.
PROGRESS: list = [
    point(3 * DAY, 5, 100, 5000),
    point(1 * DAY, 6, 200, 20_000),
    point(600, 6, 700, 30_000, "Deathknell"),
]
HISTORY: list = [
    event(3 * DAY + HOUR, "login"),
    event(1 * DAY + 2 * HOUR, "login"),
    event(600 + HOUR, "login"),
    event(2 * DAY, "quest"),  # between session 1 and 2
    event(5 * HOUR, "quest"),  # in session 3
    event(4 * HOUR, "quest"),
    event(2 * HOUR, "death"),
    event(40 * DAY, "death"),  # long before the window
]


def test_last_played_says_when_and_where() -> None:
    text = format_progress(PROGRESS, HISTORY, now=NOW)
    assert "**Last played:** 10 min ago, level 6 in Deathknell, Tirisfal Glades." in text


def test_week_summary_counts_sessions_gains_and_play_time() -> None:
    text = format_progress(PROGRESS, HISTORY, now=NOW)
    assert "**Last 7 days:** 3 play sessions, about 4 h of play" in text
    assert "- Levels: level 5 to 6 (+1)" in text
    # 5: 100 -> level 6 (900 left + 200) = 1100, then 200 -> 700 = 500.
    assert "- XP gained: about 1600" in text
    assert "- Gold: +2g 50s" in text
    assert "- XP per hour of play: about 400" in text
    assert "- Quests turned in: 3" in text
    assert "- Deaths: 1" in text


def test_a_short_window_only_counts_recent_sessions() -> None:
    text = format_progress(PROGRESS, HISTORY, now=NOW, days=2)
    assert "**Last 2 days:** 2 play sessions" in text
    # The gains start from the last point before the window (level 5, 100 XP).
    assert "- Levels: level 5 to 6 (+1)" in text
    assert "- XP gained: about 1600" in text


def test_one_day_uses_the_singular() -> None:
    text = format_progress(PROGRESS, HISTORY, now=NOW, days=1)
    assert "**Last 1 day:** 2 play sessions," in text


def test_since_the_previous_session() -> None:
    text = format_progress(PROGRESS, HISTORY, now=NOW)
    assert "**Since the previous session** (it ended 1 day ago, at level 6 in Brill" in text
    previous_block = text.split("**Since the previous session**")[1]
    assert "- Levels: still level 6" in previous_block
    assert "- XP gained: about 500" in previous_block
    assert "- Gold: +1g" in previous_block
    assert "- Quests turned in: 2" in previous_block
    assert "- Deaths: 1" in previous_block


def test_no_points_explains_how_to_get_some() -> None:
    text = format_progress([], [], now=NOW)
    assert "No progress recorded yet" in text
    assert "/coach" in text


def test_junk_points_are_ignored() -> None:
    text = format_progress([None, "x", {"level": 3}, {"time": "soon"}], [], now=NOW)  # type: ignore[list-item]
    assert "No progress recorded yet" in text


def test_a_single_point_is_handled() -> None:
    text = format_progress([point(HOUR, 3, 50, 100)], [], now=NOW)
    assert "**Last played:** 1 h ago, level 3 in Brill" in text
    assert "1 play session" in text
    assert "only play session recorded so far" in text
    assert "XP per hour" not in text  # no login known, so no play time to divide by


def test_old_play_gives_a_no_play_line() -> None:
    text = format_progress([point(30 * DAY, 3, 50, 100)], [], now=NOW)
    assert "**Last 7 days:** no play recorded." in text
    assert "**Last played:** 30 days ago" in text


def test_close_points_are_one_session() -> None:
    progress = [point(2 * HOUR, 3, 50, 100), point(2 * HOUR - 600, 3, 90, 100)]
    text = format_progress(progress, [event(3 * HOUR, "login")], now=NOW)
    assert "1 play session, about 1 h 10 min of play" in text
    assert "- XP gained: about 40" in text


def test_points_without_gold_or_xp_do_not_crash() -> None:
    bare: list = [{"time": NOW - 2 * HOUR}, {"time": NOW - HOUR, "level": 4}]
    text = format_progress(bare, [], now=NOW)
    assert "level unknown" in text or "level 4" in text
    assert "XP gained: about 0" in text


def test_gold_loss_has_a_minus() -> None:
    progress = [point(2 * HOUR, 3, 50, 5000), point(HOUR, 3, 60, 1000)]
    assert "- Gold: -40s" in format_progress(progress, [], now=NOW)
