"""Test the statistics helpers."""

from datetime import date, datetime, timedelta

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


def test_cost_statistics_prices_each_hour_at_the_months_tier(helpers) -> None:
    """Test that hours are priced at 0.01 until 600 kWh, then 0.08, split in between."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows(
        [(_at(1, 0), 595.0, 595.0), (_at(1, 1), 10.0, 605.0), (_at(1, 2), 1.0, 606.0)]
    )

    costs = helpers.cost_statistics(rows, TARIFFS["ELECTRIC"])

    assert [c["start"] for c in costs] == [_at(1, 0), _at(1, 1), _at(1, 2)]
    assert [c["state"] for c in costs] == pytest.approx(
        [5.95, 5 * 0.01 + 5 * 0.08, 0.08]
    )
    assert costs[-1]["sum"] == pytest.approx(5.95 + 0.45 + 0.08)


def test_cost_statistics_resets_the_tier_each_month_but_not_the_sum(helpers) -> None:
    """Test that a new month starts back at the cheapest tier, the sum carrying on."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    september = datetime(2026, 9, 30, 23, tzinfo=BRUNEI_TZ)
    october = datetime(2026, 10, 1, 0, tzinfo=BRUNEI_TZ)
    rows = _recorder_rows([(september, 700.0, 700.0), (october, 100.0, 800.0)])

    costs = helpers.cost_statistics(rows, TARIFFS["ELECTRIC"])

    assert costs[0]["state"] == pytest.approx(600 * 0.01 + 100 * 0.08)
    assert costs[1]["state"] == pytest.approx(100 * 0.01)  # October starts at tier 1
    assert costs[1]["sum"] == pytest.approx(costs[0]["state"] + 1.0)


def test_cost_statistics_sorts_rows_and_tolerates_missing_states(helpers) -> None:
    """Test that rows are priced in time order and a None state costs nothing."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1, 1), 1.0, 0.0), (_at(1, 0), None, 0.0)])

    costs = helpers.cost_statistics(rows, TARIFFS["ELECTRIC"])

    assert [c["start"] for c in costs] == [_at(1, 0), _at(1, 1)]
    assert [c["state"] for c in costs] == pytest.approx([0.0, 0.01])


def test_cost_statistics_uses_the_water_tariff(helpers) -> None:
    """Test that water is priced on its own tiers (0.11 to 54.54 m³, then 0.44)."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1), 50.0, 50.0), (_at(2), 10.0, 60.0)])

    costs = helpers.cost_statistics(rows, TARIFFS["WATER"])

    assert costs[0]["state"] == pytest.approx(50 * 0.11)
    assert costs[1]["state"] == pytest.approx(4.54 * 0.11 + 5.46 * 0.44)


def test_cost_statistics_rebuilt_from_the_same_rows_is_identical(helpers) -> None:
    """
    Test that recomputing gives bit-identical rows, so the diff writes nothing.

    The sync rebuilds the whole series every time and relies on statistics_diff to
    skip unchanged rows; any float wobble would rewrite the full history hourly.
    """
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows(
        [(_at(d, h), 1.37 + h / 100, 0.0) for d in (1, 2) for h in range(24)]
    )
    first = helpers.cost_statistics(rows, TARIFFS["ELECTRIC"])
    stored = [
        {"start": c["start"].timestamp(), "state": c["state"], "sum": c["sum"]}
        for c in first
    ]

    assert (
        helpers.statistics_diff(
            stored, helpers.cost_statistics(rows, TARIFFS["ELECTRIC"])
        )
        == []
    )


class _State:
    """A stand-in for a recorder State: attributes plus when it was recorded."""

    def __init__(self, recorded: datetime | None = None, **attributes: object) -> None:
        self.attributes = attributes
        # Recorded shortly after USMS's reading unless a test says otherwise.
        last_update = attributes.get("last_update")
        self.last_updated = recorded or (
            datetime.fromisoformat(last_update) + timedelta(minutes=26)
            if isinstance(last_update, str)
            else _at(1)
        )


def test_credit_readings_keeps_one_per_hour_and_skips_incomplete(helpers) -> None:
    """Test that readings are hourly, parsed from ISO strings, and need all fields."""
    states = [
        _State(last_update="2026-08-01T10:15:00+08:00", credit=5.0, unit=50.0),
        _State(last_update="2026-08-01T10:30:00+08:00", credit=4.9, unit=49.0),
        _State(last_update="2026-08-01T09:15:00+08:00", credit=6.0, unit=60.0),
        _State(credit=1.0, unit=1.0),  # unavailable states carry no last_update
    ]

    readings = helpers.credit_readings(states)

    assert readings == [(_at(1, 9), 6.0, 60.0), (_at(1, 10), 4.9, 49.0)]


def test_credit_readings_place_date_only_updates_by_record_time(helpers) -> None:
    """
    Test that a date-only last_update is replaced by when the state was recorded.

    USMS now reports "13/10/2026" for electricity; taken literally, every reading
    of the day would collapse onto midnight.
    """
    states = [
        _State(
            _at(13, 12) + timedelta(minutes=50),
            last_update="2026-08-13T00:00:00+08:00",
            credit=5.0,
            unit=50.0,
        ),
        _State(
            _at(13, 17) + timedelta(minutes=13),
            last_update="2026-08-13T00:00:00+08:00",
            credit=4.0,
            unit=40.0,
        ),
    ]

    readings = helpers.credit_readings(states)

    assert readings == [(_at(13, 12), 5.0, 50.0), (_at(13, 16), 4.0, 40.0)]


def test_charged_cost_shares_a_credit_drop_by_consumption(helpers) -> None:
    """Test that a span's credit loss is split across its hours by their kWh."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1, 0), 1.0, 0.0), (_at(1, 1), 3.0, 0.0)])
    readings = [(_at(1, 0), 10.0, 100.0), (_at(1, 2), 9.6, 96.0)]

    costs = helpers.charged_cost_statistics(rows, readings, TARIFFS["ELECTRIC"])

    assert [c["state"] for c in costs] == pytest.approx([0.1, 0.3])
    assert costs[-1]["sum"] == pytest.approx(0.4)


def test_charged_cost_prices_a_top_up_span_at_the_oldest_units(helpers) -> None:
    """Test that across a top-up the hour costs units used x credit per unit before."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1, 0), 2.0, 0.0)])
    # 10 units left worth B$1.00 (0.10 each), then a top-up lands.
    readings = [(_at(1, 0), 1.0, 10.0), (_at(1, 1), 200.8, 2825.0)]

    costs = helpers.charged_cost_statistics(rows, readings, TARIFFS["ELECTRIC"])

    assert costs[0]["state"] == pytest.approx(2.0 * 0.10)


def test_charged_cost_estimates_hours_no_reading_covers(helpers) -> None:
    """Test that hours before the first and after the last reading use the tariff."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows(
        [(_at(1, 0), 1.0, 0.0), (_at(1, 1), 1.0, 0.0), (_at(1, 2), 1.0, 0.0)]
    )
    readings = [(_at(1, 1), 10.0, 100.0), (_at(1, 2), 9.5, 99.0)]

    costs = helpers.charged_cost_statistics(rows, readings, TARIFFS["ELECTRIC"])

    assert [c["state"] for c in costs] == pytest.approx([0.01, 0.5, 0.01])


def test_charged_cost_keeps_stored_costs_older_than_any_reading(helpers) -> None:
    """
    Test that purged history does not turn a charged cost back into an estimate.

    Once the recorder drops old states, the earliest reading moves forward; rows
    before it must keep the value already stored, not fall back to the tariff.
    """
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1, 0), 1.0, 0.0), (_at(1, 1), 1.0, 0.0)])
    stored = _recorder_rows([(_at(1, 0), 0.25, 0.25)])
    readings = [(_at(1, 1), 10.0, 100.0), (_at(1, 2), 9.9, 99.0)]

    costs = helpers.charged_cost_statistics(rows, readings, TARIFFS["ELECTRIC"], stored)

    assert [c["state"] for c in costs] == pytest.approx([0.25, 0.1])
    assert costs[-1]["sum"] == pytest.approx(0.35)


def test_charged_cost_fills_daily_rows_from_hourly_readings(helpers) -> None:
    """Test that a water meter's daily row collects every span's cost in its day."""
    from usms.config.constants import TARIFFS  # noqa: PLC0415

    rows = _recorder_rows([(_at(1), 2.0, 0.0), (_at(2), 2.0, 0.0)])
    readings = [(_at(1) + timedelta(hours=h), 10.0 - 0.01 * h, 50.0) for h in range(25)]

    costs = helpers.charged_cost_statistics(rows, readings, TARIFFS["WATER"])

    assert costs[0]["state"] == pytest.approx(0.24)  # 24 hourly drops of B$0.01
    assert costs[1]["state"] == pytest.approx(2.0 * 0.11)  # no readings: estimate


def test_month_cost_totals_sums_brunei_calendar_months(helpers) -> None:
    """Test that rows are totalled into last and this month, by Brunei time."""
    rows = _recorder_rows(
        [
            (datetime(2026, 9, 1, 0, tzinfo=BRUNEI_TZ), 1.25, 0.0),
            (datetime(2026, 9, 30, 23, tzinfo=BRUNEI_TZ), 0.75, 0.0),
            (datetime(2026, 10, 1, 0, tzinfo=BRUNEI_TZ), 0.5, 0.0),
            (datetime(2026, 8, 31, 23, tzinfo=BRUNEI_TZ), 9.0, 0.0),  # two months ago
        ]
    )

    last, this = helpers.month_cost_totals(
        rows, datetime(2026, 10, 13, tzinfo=BRUNEI_TZ)
    )

    assert (last, this) == (2.0, 0.5)


def test_month_cost_totals_is_none_for_a_month_without_rows(helpers) -> None:
    """Test that "no rows" is None, distinct from a month that cost nothing."""
    rows = _recorder_rows([(datetime(2026, 10, 1, tzinfo=BRUNEI_TZ), 0.0, 0.0)])

    last, this = helpers.month_cost_totals(
        rows, datetime(2026, 10, 13, tzinfo=BRUNEI_TZ)
    )

    assert (last, this) == (None, 0.0)
