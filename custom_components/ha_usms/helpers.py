"""Helper functions for HA-USMS."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date as date_type
from datetime import datetime, timedelta
from functools import partial
from itertools import accumulate
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.helpers.recorder import get_instance
from usms import BRUNEI_TZ

from .const import HOURS_PER_DAY, LOGGER

if TYPE_CHECKING:
    from homeassistant.components.recorder.models.statistics import StatisticMetaData
    from homeassistant.core import HomeAssistant


async def get_sensor_statistics(hass: HomeAssistant, statistic_id: str) -> list:
    """Return the sensor statistics for a given statistic_id."""
    LOGGER.debug(
        "Retrieving statistics from recorder for statistic_id: %s", statistic_id
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
            "Retrieved statistics from recorder for statistic_id: %s", statistic_id
        )
    else:
        LOGGER.debug("No statistics recorded yet for statistic_id: %s", statistic_id)
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


def daily_change_map(statistics: list) -> dict[date_type, float]:
    """Return day-period recorder rows as a ``{date: consumption}`` mapping."""
    daily: dict[date_type, float] = {}
    for row in statistics:
        start = datetime.fromtimestamp(row["start"], tz=BRUNEI_TZ).date()
        change = row.get("change")
        if change is not None:
            daily[start] = change
    return daily


async def get_daily_statistics(
    hass: HomeAssistant,
    statistic_id: str,
    days: int = 45,
) -> list:
    """Return the last ``days`` of daily consumption for a statistic_id.

    ``change`` gives the consumption within each day (the delta of the
    cumulative sum), which is what the projection needs. A short window keeps
    this cheap to run every poll.
    """
    start = (datetime.now(tz=BRUNEI_TZ) - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    statistics = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        None,
        {statistic_id},
        "day",
        None,
        {"change"},
    )
    return statistics.get(statistic_id, [])


async def migrate_legacy_statistics(
    hass: HomeAssistant,
    legacy_statistic_id: str,
    new_metadata: StatisticMetaData,
) -> None:
    """Move a meter's long-term statistics from a recorder id to an external id.

    Copies every legacy hourly row to the new external ``statistic_id``, writes a
    JSON backup of the legacy rows first, verifies the copy, and only then clears
    the legacy series. Idempotent: it no-ops once the external id already exists,
    and it never deletes anything it has not first backed up and verified, so a
    failed run leaves the original data intact.
    """
    new_statistic_id = new_metadata["statistic_id"]

    existing = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={new_statistic_id})
    )

    legacy = await get_sensor_statistics(hass, legacy_statistic_id)
    if not legacy:
        return  # nothing to migrate

    if existing:
        # The external series already exists, but the legacy one is still here,
        # so a previous run copied without reaching the clear step. Finish the
        # job rather than returning early, which would otherwise strand the
        # legacy series - and the repair issue it causes - forever.
        migrated = await get_sensor_statistics(hass, new_statistic_id)
        if len(migrated) >= len(legacy):
            get_instance(hass).async_clear_statistics([legacy_statistic_id])
            LOGGER.info(
                "Cleared the legacy series %s; %s already holds %d rows",
                legacy_statistic_id,
                new_statistic_id,
                len(migrated),
            )
        else:
            LOGGER.warning(
                "%s holds %d of %d rows; leaving %s in place for a later retry",
                new_statistic_id,
                len(migrated),
                len(legacy),
                legacy_statistic_id,
            )
        return

    backup_dir = Path(hass.config.path("ha_usms", "statistics_backup"))
    await hass.async_add_executor_job(
        partial(backup_dir.mkdir, parents=True, exist_ok=True)
    )
    stamp = datetime.now(tz=BRUNEI_TZ).strftime("%Y%m%d-%H%M%S")
    backup_file = backup_dir / f"{legacy_statistic_id}-{stamp}.json"
    payload = json.dumps(
        {"statistic_id": legacy_statistic_id, "rows": legacy}, default=str, indent=2
    )
    await hass.async_add_executor_job(backup_file.write_text, payload)
    LOGGER.info(
        "Backed up %d legacy statistics rows for %s to %s",
        len(legacy),
        legacy_statistic_id,
        backup_file,
    )

    statistics = [
        {
            "start": datetime.fromtimestamp(row["start"], tz=BRUNEI_TZ),
            "state": row["state"],
            "sum": row["sum"],
        }
        for row in legacy
    ]
    async_add_external_statistics(hass, new_metadata, statistics)
    await get_instance(hass).async_block_till_done()

    migrated = await get_sensor_statistics(hass, new_statistic_id)
    if len(migrated) < len(legacy):
        LOGGER.error(
            "Migration of %s -> %s copied %d of %d rows; leaving the legacy "
            "series in place. Backup at %s",
            legacy_statistic_id,
            new_statistic_id,
            len(migrated),
            len(legacy),
            backup_file,
        )
        return

    get_instance(hass).async_clear_statistics([legacy_statistic_id])
    LOGGER.info(
        "Migrated %d rows %s -> %s and cleared the legacy series",
        len(migrated),
        legacy_statistic_id,
        new_statistic_id,
    )
