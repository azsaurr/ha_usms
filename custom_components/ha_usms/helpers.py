"""Helper functions for HA-USMS."""

from collections import Counter
from datetime import date as date_type
from datetime import datetime, timedelta
from itertools import accumulate

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from usms import BRUNEI_TZ

from .const import HOURS_PER_DAY, LOGGER


async def get_sensor_statistics(hass: HomeAssistant, statistic_id: str) -> list:
    """Return the sensor statistics for a given statistic_id."""
    LOGGER.debug(
        f"Retrieving statistics from recorder for statistic_id: {statistic_id}"
    )
    statistics = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime.fromtimestamp(0).astimezone(),
        None,
        [statistic_id],
        "hour",
        None,
        ["state", "sum"],
    )
    statistics = statistics.get(statistic_id, [])
    if statistics != []:
        LOGGER.debug(
            f"Retrieved statistics from recorder for statistic_id: {statistic_id}"
        )
    else:
        LOGGER.debug(f"No statistics recorded yet for statistic_id: {statistic_id}")
    return statistics


def statistics_to_map(statistics: list) -> dict[datetime, float]:
    """
    Return recorder statistics as a {start: state} mapping.

    The recorder hands back `start` as epoch seconds; keys are converted to
    Brunei-local timestamps so they line up with what the usms package returns.
    """
    return {
        datetime.fromtimestamp(statistic["start"], tz=BRUNEI_TZ): statistic["state"]
        for statistic in statistics
    }


def map_to_statistics(consumptions: dict[datetime, float]) -> list[dict]:
    """
    Return a {start: state} mapping as recorder statistics, with a running sum.

    Long-term statistics carry a cumulative `sum` alongside each `state`, so the
    mapping is walked in chronological order to accumulate it.
    """
    timestamps = sorted(consumptions)
    states = [consumptions[timestamp] for timestamp in timestamps]

    return [
        {"start": timestamp, "state": state, "sum": running_sum}
        for timestamp, state, running_sum in zip(
            timestamps, states, accumulate(states), strict=True
        )
    ]


def statistics_diff(old_statistics: list, new_statistics: list) -> list[dict]:
    """
    Return the statistics whose state or sum changed, or that are entirely new.

    `old_statistics` comes from the recorder and carries `start` as epoch seconds,
    while `new_statistics` is freshly built with datetime starts, so the old side is
    normalised before comparing.
    """
    old_by_start = {
        datetime.fromtimestamp(statistic["start"], tz=BRUNEI_TZ): (
            statistic.get("state"),
            statistic.get("sum"),
        )
        for statistic in old_statistics
    }

    return [
        statistic
        for statistic in new_statistics
        if old_by_start.get(statistic["start"])
        != (statistic["state"], statistic["sum"])
    ]


def get_missing_days(statistics: list) -> list[datetime]:
    """Return a list of days that have no, or incomplete, hourly statistics."""
    statistics_map = statistics_to_map(statistics)
    if not statistics_map:
        return []

    hours_per_day: Counter[date_type] = Counter(
        timestamp.date() for timestamp in statistics_map
    )

    day = min(statistics_map).date()
    last_day = (datetime.now(tz=BRUNEI_TZ) - timedelta(days=1)).date()

    missing_days = []
    while day <= last_day:
        if hours_per_day[day] < HOURS_PER_DAY:
            missing_days.append(
                datetime(day.year, day.month, day.day, tzinfo=BRUNEI_TZ)
            )
        day += timedelta(days=1)

    return missing_days
