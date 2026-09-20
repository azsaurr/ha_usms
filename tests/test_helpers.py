"""Test the statistics helpers."""

from datetime import date, datetime

import pytest
from usms import BRUNEI_TZ


def _at(day: int, hour: int = 0) -> datetime:
    """Return a Brunei-local timestamp in August 2026."""
    return datetime(2026, 8, day, hour, tzinfo=BRUNEI_TZ)


def _recorder_rows(entries: list[tuple[datetime, float, float]]) -> list[dict]:
    """Return rows shaped the way the recorder hands them back (epoch starts)."""
    return [
        {"start": start.timestamp(), "state": state, "sum": total}
        for start, state, total in entries
    ]


def test_map_to_statistics_accumulates_and_sorts(helpers) -> None:
    """Test that statistics come out chronological with a running sum."""
    statistics = helpers.map_to_statistics(
        {_at(21, 2): 3.0, _at(21, 0): 1.0, _at(21, 1): 2.0}
    )

    assert [s["start"] for s in statistics] == [_at(21, 0), _at(21, 1), _at(21, 2)]
    assert [s["state"] for s in statistics] == [1.0, 2.0, 3.0]
    assert [s["sum"] for s in statistics] == [1.0, 3.0, 6.0]


def test_map_to_statistics_empty(helpers) -> None:
    """Test that no consumptions yields no statistics."""
    assert helpers.map_to_statistics({}) == []


def test_statistics_to_map_converts_epoch_starts(helpers) -> None:
    """Test that recorder epoch starts become Brunei-local datetimes."""
    rows = _recorder_rows([(_at(21, 0), 1.0, 1.0), (_at(21, 1), 2.0, 3.0)])

    assert helpers.statistics_to_map(rows) == {_at(21, 0): 1.0, _at(21, 1): 2.0}


def test_statistics_diff_returns_only_changes(helpers) -> None:
    """Test that unchanged rows are suppressed and new/changed rows returned."""
    old = _recorder_rows([(_at(21, 0), 1.0, 1.0), (_at(21, 1), 2.0, 3.0)])
    new = helpers.map_to_statistics({_at(21, 0): 1.0, _at(21, 1): 2.0, _at(21, 2): 9.0})

    diff = helpers.statistics_diff(old, new)

    assert [s["start"] for s in diff] == [_at(21, 2)]
    assert diff[0]["state"] == 9.0


def test_statistics_diff_is_idempotent(helpers) -> None:
    """Test that re-importing identical statistics produces nothing."""
    statistics = helpers.map_to_statistics({_at(21, 0): 1.0, _at(21, 1): 2.0})
    identical = _recorder_rows([(s["start"], s["state"], s["sum"]) for s in statistics])

    assert helpers.statistics_diff(identical, statistics) == []


def test_statistics_diff_detects_a_corrected_value(helpers) -> None:
    """Test that a revised reading for an existing hour is returned."""
    old = _recorder_rows([(_at(21, 0), 1.0, 1.0)])
    new = helpers.map_to_statistics({_at(21, 0): 5.0})

    assert helpers.statistics_diff(old, new)[0]["state"] == 5.0


def test_get_missing_days_flags_incomplete_days(helpers) -> None:
    """Test that a day with fewer than 24 hourly rows is reported missing."""
    complete = _recorder_rows([(_at(19, h), 1.0, 1.0) for h in range(24)])
    partial = _recorder_rows([(_at(20, h), 1.0, 1.0) for h in range(5)])

    missing = [d.date() for d in helpers.get_missing_days(complete + partial)]

    assert _at(20).date() in missing
    assert _at(19).date() not in missing


def test_get_missing_days_flags_absent_days(helpers) -> None:
    """Test that a day with no rows at all is reported missing."""
    complete = _recorder_rows([(_at(19, h), 1.0, 1.0) for h in range(24)])

    missing = [d.date() for d in helpers.get_missing_days(complete)]

    # 20 Aug onwards has no data, so every day up to yesterday is missing.
    assert _at(20).date() in missing


def test_get_missing_days_returns_aware_datetimes(helpers) -> None:
    """Test that missing days are tz-aware, so refetching targets the right day."""
    partial = _recorder_rows([(_at(20, h), 1.0, 1.0) for h in range(5)])

    assert all(d.tzinfo is not None for d in helpers.get_missing_days(partial))


def test_get_missing_days_empty(helpers) -> None:
    """Test that no statistics means nothing to backfill."""
    assert helpers.get_missing_days([]) == []


@pytest.mark.parametrize("readings", [1, 5, 23])
def test_get_missing_days_threshold(helpers, readings) -> None:
    """Test that any day short of a full 24 hours counts as missing."""
    partial = _recorder_rows([(_at(20, h), 1.0, 1.0) for h in range(readings)])

    assert _at(20).date() in [d.date() for d in helpers.get_missing_days(partial)]


def test_daily_change_map_reads_change(helpers) -> None:
    """Test that day-period rows collapse to a {date: consumption} map."""
    start = datetime(2026, 9, 1, tzinfo=BRUNEI_TZ).timestamp()
    rows = [
        {"start": start, "change": 90.0},
        {"start": start + 86400, "change": 100.0},
        {"start": start + 2 * 86400, "change": None},
    ]
    out = helpers.daily_change_map(rows)
    assert out[date(2026, 9, 1)] == 90.0
    assert out[date(2026, 9, 2)] == 100.0
    assert date(2026, 9, 3) not in out


def test_project_month_total_blends_and_scales(helpers) -> None:
    """Test a steady daily rate projects back to the expected month total."""
    daily = {date(2026, 9, d): 100.0 for d in range(1, 10)}
    now = datetime(2026, 9, 10, 12, 0, tzinfo=BRUNEI_TZ)
    projected, rate = helpers.project_month_total(daily, now)
    assert rate == 100.0
    assert projected == 3000.0


def test_project_month_total_needs_history(helpers) -> None:
    """Test the projection is None without at least one complete prior day."""
    now = datetime(2026, 9, 10, tzinfo=BRUNEI_TZ)
    assert helpers.project_month_total({}, now) is None
    assert helpers.project_month_total({date(2026, 9, 10): 40.0}, now) is None


def test_project_month_total_early_month_uses_trailing(helpers) -> None:
    """Test day-1 projection falls back to the trailing mean of prior days."""
    daily = {date(2026, 8, d): 80.0 for d in range(1, 31)}
    now = datetime(2026, 9, 1, tzinfo=BRUNEI_TZ)
    projected, rate = helpers.project_month_total(daily, now)
    assert rate == 80.0
    assert projected == 80.0 * 30
