"""DataUpdateCoordinator for HA-USMS."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from usms import AsyncUSMSAccount
from usms.exceptions.errors import USMSLoginError

from .const import DEFAULT_SCAN_INTERVAL, LOGGER
from .data import HAUSMSMeterData
from .helpers import (
    consumptions_series_to_dataframe,
    dataframe_diff,
    dataframe_to_statistics,
    get_missing_days,
    get_sensor_statistics,
    statistics_to_dataframe,
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
        self.account = AsyncUSMSAccount(
            config_entry.data[CONF_USERNAME],
            config_entry.data[CONF_PASSWORD],
        )

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self.account.initialize()

    async def _async_update_data(self) -> Any:  # noqa: PLR0912, PLR0915
        """Update data via library."""
        try:
            has_updates = self.account.is_update_due()
            if not has_updates:
                LOGGER.debug(
                    f"USMS account {self.account.username} is not due for an update"
                )
            else:
                LOGGER.debug(
                    f"USMS account {self.account.username} is due for an update"
                )

                has_updates = await self.account.refresh_data()
                if not has_updates:
                    LOGGER.debug(
                        f"USMS account {self.account.username} has no new updates"
                    )
                else:
                    LOGGER.debug(
                        f"USMS account {self.account.username} has new updates"
                    )

            is_first_run = self.data is None
            now = datetime.now().astimezone()

            # check for updates for every meter
            meters = []
            for meter in self.account.get_meters():
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
                        f"Fetching last month's consumptions for {meter_data.name}"
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
                        f"Fetching this month's consumptions for {meter_data.name}"
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
                    # get last 2 days of hourly consumptions
                    LOGGER.debug(
                        f"Fetching the last 2 days' consumptions for {meter_data.name}"
                    )
                    new_hourly_consumptions = (
                        await meter.get_last_n_days_hourly_consumptions(n=2)
                    )

                    # get meter's old statistics
                    old_statistics = await get_sensor_statistics(
                        self.hass,
                        f"sensor.{meter_data.unique_id}",
                    )
                    old_statistics_df = statistics_to_dataframe(old_statistics)

                    # Try to find gaps in data
                    if old_statistics != []:
                        # Fetch statistics for each missing day
                        for date in await get_missing_days(statistics=old_statistics):
                            day_statistics = await meter.fetch_hourly_consumptions(date)
                            new_hourly_consumptions = day_statistics.combine_first(
                                new_hourly_consumptions
                            )

                    new_hourly_consumptions_df = consumptions_series_to_dataframe(
                        new_hourly_consumptions
                    )

                    # combine new_hourly_consumptions_df into old_statistics_df
                    temp_statistics_df = old_statistics_df.combine_first(
                        new_hourly_consumptions_df
                    )
                    # calculate cumulative sum for the state column
                    temp_statistics_df["sum"] = temp_statistics_df["state"].cumsum()

                    # get new statistics only
                    new_statistics_df = dataframe_diff(
                        old_statistics_df, temp_statistics_df
                    )
                    # convert statistics df to statistics list
                    meter_data.new_statistics = dataframe_to_statistics(
                        new_statistics_df
                    )

                meters.append(meter_data)
                LOGGER.debug(f"Finished fetching updates for {meter_data.name}")

            return meters  # noqa: TRY300
        except USMSLoginError as exception:
            LOGGER.error(exception)
            raise ConfigEntryAuthFailed(exception) from exception
        except Exception as exception:
            LOGGER.error(exception)
            raise UpdateFailed(exception) from exception

    def get_meter_data_by_no(self, meter_no: str) -> HAUSMSMeterData | None:
        """Return meter data by meter no."""
        try:
            for meter_data in self.data:
                if meter_data.no == meter_no:
                    return meter_data
        except IndexError:
            return None
