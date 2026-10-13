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
    async_sync_cost_statistics,
    daily_change_map,
    get_daily_statistics,
    get_missing_days,
    get_sensor_statistics,
    map_to_statistics,
    migrate_legacy_statistics,
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
        # Move each meter's long-term statistics off the recorder source
        # (sensor.<id>) onto an external one (ha_usms:<id>). Deliberately a
        # background task rather than awaited here: verifying the copy means
        # waiting for a recorder commit, and `commit_interval` is configurable
        # (300 s is common), which would otherwise stall - and then cancel -
        # config entry setup. Safe to run every startup: it no-ops once the
        # external id exists, and it backs up and verifies before removing
        # anything.
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_migrate_statistics(),
            name="ha_usms_statistics_migration",
        )

    async def _async_migrate_statistics(self) -> None:
        """
        Migrate every meter's legacy statistics, then bring its cost series up to date.

        The cost sync runs here, after the migration, because it reads the external
        consumption series the migration produces. On the first run it builds the
        whole cost history; after that it finds nothing to write.
        """
        for meter in self.account.meters:
            meter_data = HAUSMSMeterData.from_meter(meter)
            try:
                await migrate_legacy_statistics(
                    self.hass,
                    legacy_statistic_id=f"sensor.{meter_data.unique_id}",
                    new_metadata=meter_data.metadata,
                )
            except Exception:  # noqa: BLE001 - a migration must never take the integration down
                # The legacy series is left untouched and retried on restart.
                LOGGER.exception(
                    "Statistics migration failed for %s; the legacy series is "
                    "unchanged and will be retried on the next restart",
                    meter_data.name,
                )
            try:
                await async_sync_cost_statistics(self.hass, meter_data)
            except Exception:  # noqa: BLE001 - cost is derived data; never fatal
                LOGGER.exception("Cost statistics sync failed for %s", meter_data.name)

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
                    # broken session is reported instead of silently freezing
                    # every value (which is how a 4-day outage went unnoticed).
                    # Logging in again surfaces the real reason: USMSLoginError
                    # (wrong password) becomes reauth below, while
                    # USMSCaptchaError - credentials fine, captcha unsolved - is
                    # only an UpdateFailed and is retried on the next poll.
                    if not await self.account.is_authenticated():
                        await self.account.session.authenticate()
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

        The maths, the tariff pricing and the credit runway all live in the usms
        library; Home Assistant only supplies the daily history, which comes from
        the recorder rather than from refetching USMS.
        """
        meter = next((m for m in self.account.meters if m.no == meter_data.no), None)
        if meter is None:
            return

        daily = daily_change_map(
            await get_daily_statistics(self.hass, meter_data.statistic_id)
        )
        projection = meter.project_month(daily, datetime.now().astimezone())
        if projection is None:
            return

        meter_data.projected_month_consumption = projection.total_consumption
        meter_data.projected_daily_consumption = projection.daily_rate
        meter_data.projected_month_cost = projection.total_cost
        meter_data.credit_runs_out_at = projection.credit_runs_out_at

    def get_meter_data_by_no(self, meter_no: str) -> HAUSMSMeterData | None:
        """Return meter data by meter no."""
        try:
            for meter_data in self.data:
                if meter_data.no == meter_no:
                    return meter_data
        except IndexError:
            return None
