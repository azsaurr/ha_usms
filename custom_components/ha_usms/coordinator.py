"""DataUpdateCoordinator for HA-USMS."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import tzdata  # needed to avoid blocking  # noqa: F401
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from usms import AsyncUSMSAccount, AsyncUSMSClient, USMSLoginError

from .const import DEFAULT_SCAN_INTERVAL, LOGGER
from .data import HAUSMSMeterData
from .helpers import (
    daily_change_map,
    get_daily_statistics,
    get_missing_days,
    get_sensor_statistics,
    map_to_statistics,
    migrate_legacy_statistics,
    project_month_total,
    statistics_diff,
    statistics_to_map,
)

if TYPE_CHECKING:
    from logging import Logger

    from homeassistant.core import HomeAssistant

    from .data import HAUSMSConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class HAUSMSDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: HAUSMSConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: HAUSMSConfigEntry,
        logger: Logger,
        name: str,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            config_entry=config_entry,
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    DEFAULT_SCAN_INTERVAL,
                )
            ),
        )

        # A dedicated client, NOT HA's shared one: the usms library pins the
        # session cookie as a default header and flips follow_redirects on the
        # client it is handed, which would otherwise leak onto every integration
        # sharing get_async_client().
        async_client = create_async_httpx_client(hass)
        async_client.timeout = 60

        username = config_entry.data[CONF_USERNAME]
        password = config_entry.data[CONF_PASSWORD]

        usms_client = AsyncUSMSClient(
            client=async_client,
            username=username,
            password=password,
        )
        self.account = AsyncUSMSAccount(session=usms_client)

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self.account.initialize()
        # One-time move of each meter's long-term statistics off the recorder
        # source (sensor.<id>) onto an external source (ha_usms:<id>). Safe to
        # run every startup: it no-ops once the external id exists, and it backs
        # up and verifies before removing anything.
        for meter in self.account.meters:
            await migrate_legacy_statistics(
                self.hass,
                legacy_statistic_id=f"sensor.{HAUSMSMeterData.from_meter(meter).unique_id}",
                new_metadata=HAUSMSMeterData.from_meter(meter).metadata,
            )

    async def _async_update_data(self) -> Any:  # noqa: PLR0912, PLR0915
        """Update data via library."""
        try:
            has_updates = self.account.is_update_due()
            if not has_updates:
                LOGGER.debug(
                    "USMS account %s is not due for an update", self.account.reg_no
                )
            else:
                LOGGER.debug(
                    "USMS account %s is due for an update", self.account.reg_no
                )

                has_updates = await self.account.refresh_data()
                if not has_updates:
                    # refresh_data() returns False both for "nothing new" and for
                    # a login failure the library swallowed. Disambiguate so a
                    # broken session raises reauth instead of silently freezing
                    # every value (which is how a 4-day outage went unnoticed).
                    if not await self.account.is_authenticated():
                        msg = "USMS session is no longer authenticated"
                        raise ConfigEntryAuthFailed(msg)  # noqa: TRY301
                    LOGGER.debug(
                        "USMS account %s has no new updates", self.account.reg_no
                    )
                else:
                    LOGGER.debug("USMS account %s has new updates", self.account.reg_no)

            is_first_run = self.data is None
            now = datetime.now().astimezone()

            # check for updates for every meter
            meters = []
            for meter in self.account.meters:
                # Debt and customer details live on the Top Up page, which is a
                # separate request, so only refetch when something may have moved.
                if is_first_run or has_updates:
                    await meter.fetch_payment_info()

                meter_data = HAUSMSMeterData.from_meter(meter)

                meter_data.last_refresh = self.account.last_refresh
                meter_data.next_refresh = now + self.update_interval

                # only check on first run or
                # only re-check if its still within the first 3 days of a new month and
                # there has been any updates
                if is_first_run or (
                    now.day < 3 and has_updates  # noqa: PLR2004
                ):
                    # get last month's total consumption and cost
                    LOGGER.debug(
                        "Fetching last month's consumptions for %s", meter_data.name
                    )
                    last_month_consumptions = (
                        await meter.get_previous_n_month_consumptions(n=1)
                    )
                    meter_data.last_month_total_consumption = (
                        meter.calculate_total_consumption(last_month_consumptions)
                    )
                    meter_data.last_month_total_cost = meter.calculate_total_cost(
                        last_month_consumptions
                    )
                # just use the data from the last run
                else:
                    prev_meter_data = self.get_meter_data_by_no(meter_data.no)
                    meter_data.last_month_total_consumption = (
                        prev_meter_data.last_month_total_consumption
                    )
                    meter_data.last_month_total_cost = (
                        prev_meter_data.last_month_total_cost
                    )

                # only check on first run or
                # only re-check if there has been any updates
                if is_first_run or has_updates:
                    # get this month's total consumption and cost
                    LOGGER.debug(
                        "Fetching this month's consumptions for %s", meter_data.name
                    )
                    this_month_consumptions = (
                        await meter.get_previous_n_month_consumptions(n=0)
                    )
                    meter_data.this_month_total_consumption = (
                        meter.calculate_total_consumption(this_month_consumptions)
                    )
                    meter_data.this_month_total_cost = meter.calculate_total_cost(
                        this_month_consumptions
                    )
                # just use the data from the last run
                else:
                    prev_meter_data = self.get_meter_data_by_no(meter_data.no)
                    meter_data.this_month_total_consumption = (
                        prev_meter_data.this_month_total_consumption
                    )
                    meter_data.this_month_total_cost = (
                        prev_meter_data.this_month_total_cost
                    )

                meter_data.new_statistics = []
                # only check if not on first run, and there has been any updates
                if not is_first_run and has_updates:
                    # get meter's old statistics
                    old_statistics = await get_sensor_statistics(
                        self.hass,
                        meter_data.statistic_id,
                    )

                    if meter.supports_hourly_consumptions:
                        LOGGER.debug(
                            "Fetching the last 2 days' consumptions for %s",
                            meter_data.name,
                        )
                        new_consumptions = (
                            await meter.get_last_n_days_hourly_consumptions(n=2)
                        )
                        # Try to find gaps in data
                        if old_statistics != []:
                            # Fetch statistics for each missing day
                            for date in get_missing_days(old_statistics):
                                day_statistics = await meter.fetch_hourly_consumptions(
                                    date
                                )
                                new_consumptions = {
                                    **new_consumptions,
                                    **day_statistics,
                                }
                    else:
                        # Water meters have no hourly report at all, so their
                        # statistics come from the daily series instead. Refetching
                        # both months also closes any gaps, so there is no separate
                        # missing-day pass.
                        LOGGER.debug(
                            "Fetching this and last month's daily consumptions for %s",
                            meter_data.name,
                        )
                        new_consumptions = {
                            **await meter.get_previous_n_month_consumptions(n=1),
                            **await meter.get_previous_n_month_consumptions(n=0),
                        }

                    # Already recorded statistics win over anything refetched
                    combined = {
                        **new_consumptions,
                        **statistics_to_map(old_statistics),
                    }
                    meter_data.new_statistics = statistics_diff(
                        old_statistics,
                        map_to_statistics(combined),
                    )

                await self._apply_projection(meter_data)

                meters.append(meter_data)
                LOGGER.debug("Finished fetching updates for %s", meter_data.name)

            return meters  # noqa: TRY300
        except USMSLoginError as exception:
            LOGGER.error(exception)
            raise ConfigEntryAuthFailed(exception) from exception
        except Exception as exception:
            LOGGER.error(exception)
            raise UpdateFailed(exception) from exception

    async def _apply_projection(self, meter_data: HAUSMSMeterData) -> None:
        """Fill in this month's consumption/cost/credit projection for a meter.

        Uses only this meter's own recorded daily history, so it is not tied to
        any particular account. Silently leaves the projection as None when
        there is not yet enough history.
        """
        daily = daily_change_map(
            await get_daily_statistics(self.hass, meter_data.statistic_id)
        )
        now = datetime.now().astimezone()
        result = project_month_total(daily, now)
        if result is None:
            return

        projected_total, daily_rate = result
        meter_data.projected_month_consumption = round(projected_total, 3)
        meter_data.projected_daily_consumption = round(daily_rate, 3)

        # Cost via the meter's own tiered tariff (residential USMS rates, shared
        # across all accounts; the library warns for non-residential meters).
        meter = next((m for m in self.account.meters if m.no == meter_data.no), None)
        if meter is not None:
            month_consumptions = {
                # calculate_total_cost only needs the summed consumption, so a
                # single synthetic point carrying the projected total is enough.
                now: projected_total,
            }
            meter_data.projected_month_cost = round(
                meter.calculate_total_cost(month_consumptions), 2
            )

        # Credit runway: remaining prepaid units divided by the projected rate.
        remaining = getattr(meter_data, "remaining_unit", None)
        if remaining is not None and daily_rate > 0:
            days_left = remaining / daily_rate
            meter_data.credit_runs_out_at = now + timedelta(days=days_left)

    def get_meter_data_by_no(self, meter_no: str) -> HAUSMSMeterData | None:
        """Return meter data by meter no."""
        try:
            for meter_data in self.data:
                if meter_data.no == meter_no:
                    return meter_data
        except IndexError:
            return None
