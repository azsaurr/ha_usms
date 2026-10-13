"""Helper functions for HA-USMS."""

from __future__ import annotations

import asyncio
import json
from bisect import bisect_left
from collections import Counter
from datetime import date as date_type
from datetime import datetime, timedelta
from functools import partial
from itertools import accumulate, pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance
from usms import BRUNEI_TZ

from .const import DOMAIN, HOURS_PER_DAY, LOGGER

if TYPE_CHECKING:
    from homeassistant.components.recorder.models.statistics import StatisticMetaData
    from homeassistant.core import HomeAssistant, State
    from usms.models.tariff import USMSTariff

    from .data import HAUSMSMeterData


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


def cost_statistics(consumption_statistics: list, tariff: USMSTariff) -> list[dict]:
    """
    Return the cost of each consumption statistic, with a running sum, in B$.

    USMS tariffs are tiered on the calendar month's total, so each period is priced
    by where the month's running consumption stands when it happens: an hour that
    carries the month past 600 kWh is charged partly at each tier. The running
    consumption resets at the start of every month (Brunei time); the cost sum does
    not, as a long-term statistic's sum never decreases.

    `consumption_statistics` are recorder rows (epoch `start`, per-period `state`).
    """
    statistics: list[dict] = []
    month = None
    consumed = 0.0
    total_cost = 0.0

    for row in sorted(consumption_statistics, key=lambda row: row["start"]):
        start = datetime.fromtimestamp(row["start"], tz=BRUNEI_TZ)
        if (start.year, start.month) != month:
            month = (start.year, start.month)
            consumed = 0.0

        consumption = row.get("state") or 0.0
        cost = tariff.cost_between(consumed, consumed + consumption)
        consumed += consumption
        total_cost += cost
        statistics.append({"start": start, "state": cost, "sum": total_cost})

    return statistics


type CreditReading = tuple[datetime, float, float]
"""A meter reading: when USMS last updated it, its credit (B$) and its units."""


# Since October 2026 USMS reports "Last Updated" as a bare date for electricity
# meters too, which parses to midnight. A last_update this far behind the moment
# Home Assistant recorded the state is taken to be one of those.
DATE_ONLY_THRESHOLD = timedelta(hours=2)

# How long after USMS's own reading Home Assistant typically records it (median
# 26 minutes, measured while last_update still carried a time); used instead of a
# date-only last_update.
READING_LAG = timedelta(minutes=30)


def credit_readings(states: list[State]) -> list[CreditReading]:
    """
    Return the meter's distinct credit readings, oldest first, from sensor history.

    The meter sensor records USMS's `last_update`, `credit` and `unit` as attributes
    on every state. One reading per hour is kept: USMS updates hourly, and a reading
    covers every consumption hour that starts before its own hour (measured against
    the meter's unit counter), so two readings within an hour describe the same span.

    When `last_update` is only a date, the reading is placed by when Home Assistant
    recorded it instead. Misplacing one by an hour moves cost between neighbouring
    hours but never changes a span's total, which is the credit actually lost.
    """
    by_hour: dict[datetime, CreditReading] = {}
    for state in states:
        attributes = state.attributes
        last_update, credit, unit = (
            attributes.get("last_update"),
            attributes.get("credit"),
            attributes.get("unit"),
        )
        if last_update is None or credit is None or unit is None:
            continue
        if isinstance(last_update, str):
            last_update = datetime.fromisoformat(last_update)

        recorded = state.last_updated
        if recorded - last_update > DATE_ONLY_THRESHOLD:
            last_update = recorded - READING_LAG

        hour = last_update.astimezone(BRUNEI_TZ).replace(
            minute=0, second=0, microsecond=0
        )
        by_hour[hour] = (hour, float(credit), float(unit))
    return [by_hour[hour] for hour in sorted(by_hour)]


def _statistic_period(starts: list[datetime]) -> timedelta:
    """Return how long each statistic row covers: an hour, or a day for water."""
    gaps = Counter(later - earlier for earlier, later in pairwise(starts))
    return gaps.most_common(1)[0][0] if gaps else timedelta(hours=1)


def charged_cost_statistics(
    consumption_statistics: list,
    readings: list[CreditReading],
    tariff: USMSTariff,
    stored_costs: list | None = None,
) -> list[dict]:
    """
    Return what each consumption statistic actually cost, with a running sum, in B$.

    USMS is prepaid: a top-up buys units priced on the tariff tiers, counted over
    the calendar month's purchases, and the meter spends units oldest first. So what
    an hour costs depends on when earlier top-ups happened, and the authority is the
    meter's own credit balance. Between two readings the cost is the credit it lost;
    across a top-up, where credit rises, it is the units used times the credit per
    unit just before (the oldest units, which are spent first). Each span's cost is
    shared among its consumption rows by their consumption.

    Rows no reading covers fall back to `cost_statistics`' tariff estimate: history
    from before credit was recorded, and the newest hours, until the next reading
    arrives and corrects them. Rows older than the earliest reading keep their value
    in `stored_costs` when there is one, so the recorder purging old states never
    turns a charged cost back into an estimate.
    """
    rows = sorted(consumption_statistics, key=lambda row: row["start"])
    if not rows:
        return []

    starts = [datetime.fromtimestamp(row["start"], tz=BRUNEI_TZ) for row in rows]
    consumption = [row.get("state") or 0.0 for row in rows]
    period = _statistic_period(starts)
    estimates = [statistic["state"] for statistic in cost_statistics(rows, tariff)]

    charged = [0.0] * len(rows)
    covered = [0.0] * len(rows)  # fraction of each row's period that readings explain

    for (since, credit_before, units_before), (
        until,
        credit_after,
        units_after,
    ) in pairwise(readings):
        # Each overlapping row's share: the fraction of its period inside this span.
        shares = {}
        for index in range(
            bisect_left(starts, since - period), bisect_left(starts, until)
        ):
            overlap = min(starts[index] + period, until) - max(starts[index], since)
            if overlap > timedelta(0):
                shares[index] = overlap / period

        if not shares:
            continue

        used = sum(consumption[index] * share for index, share in shares.items())
        if units_after > units_before:  # a top-up landed in this span
            if units_before <= 0:
                continue  # no price to go on; leave these rows to the estimate
            cost = used * credit_before / units_before
        else:
            cost = max(credit_before - credit_after, 0.0)

        for index, share in shares.items():
            covered[index] += share
            if used > 0:
                charged[index] += cost * consumption[index] * share / used

    earliest_reading = readings[0][0] if readings else None
    stored = statistics_to_map(stored_costs or [])

    statistics: list[dict] = []
    total_cost = 0.0
    for index, start in enumerate(starts):
        uncovered = max(0.0, 1.0 - covered[index])
        cost = charged[index] + estimates[index] * uncovered
        if (earliest_reading is None or start < earliest_reading) and start in stored:
            cost = stored[start]
        total_cost += cost
        statistics.append({"start": start, "state": cost, "sum": total_cost})

    return statistics


# One sync at a time per meter: the coordinator and the buttons can both trigger
# one, and two interleaved diffs would each write rows the other then rewrites.
_cost_sync_locks: dict[str, asyncio.Lock] = {}


async def async_sync_cost_statistics(
    hass: HomeAssistant, meter_data: HAUSMSMeterData
) -> None:
    """
    Bring a meter's cost statistic in line with its consumption and credit history.

    The whole cost series is rebuilt and only the rows that differ are written, so
    this is cheap when nothing changed, fills the full history on first run, and
    corrects any span whose consumption was backfilled or whose reading just landed.
    """
    tariff = meter_data.tariff
    if tariff is None:
        return

    lock = _cost_sync_locks.setdefault(meter_data.cost_statistic_id, asyncio.Lock())
    async with lock:
        # Consumption may have just been queued for import; read it once committed.
        await get_instance(hass).async_block_till_done()

        consumption = await get_sensor_statistics(hass, meter_data.statistic_id)
        if not consumption:
            return

        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, meter_data.unique_id
        )
        states: list = []
        if entity_id is not None:
            # Not state_changes_during_period: that skips attribute-only updates,
            # and the credit can move while the remaining units read the same.
            history = await get_instance(hass).async_add_executor_job(
                partial(
                    get_significant_states,
                    hass,
                    datetime.fromtimestamp(0, tz=BRUNEI_TZ),
                    entity_ids=[entity_id],
                    significant_changes_only=False,
                )
            )
            states = history.get(entity_id, [])

        old_costs = await get_sensor_statistics(hass, meter_data.cost_statistic_id)
        costs = charged_cost_statistics(
            consumption, credit_readings(states), tariff, old_costs
        )
        changed = statistics_diff(old_costs, costs)
        if not changed:
            return

        LOGGER.info(
            "Importing %d cost statistics for %s",
            len(changed),
            meter_data.cost_statistic_id,
        )
        async_add_external_statistics(hass, meter_data.cost_metadata, changed)


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
