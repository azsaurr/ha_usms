"""DataUpdateCoordinator for HA-USMS."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from usms.exceptions.errors import USMSLoginError

from .const import LOGGER
from .data import HAUSMSMeterData
from .helpers import (
    consumptions_series_to_dataframe,
    dataframe_diff,
    dataframe_to_statistics,
    get_sensor_statistics,
    statistics_to_dataframe,
)

if TYPE_CHECKING:
    from .data import HAUSMSConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class HAUSMSDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: HAUSMSConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            account = self.config_entry.runtime_data.account
            meters = []
            # check if account is currently authenticated or not
            if not await account.is_authenticated():
                LOGGER.debug(f"USMS Account {account.user} is not logged in")

                # log in account if session has expired
                if await self.account.log_in():
                    LOGGER.debug(f"USMS Account {account.user} log in successfully")

            # check for updates for every meter
            for meter in account.meters:
                meter_name = f"{meter.get_type()} Meter {meter.get_no()}"
                if not meter.is_update_due():
                    LOGGER.debug(f"{meter_name} is not due for an update")
                    # continue  # noqa: ERA001
                else:
                    LOGGER.debug(f"{meter_name} is due for an update")

                if not await meter.refresh_data():
                    LOGGER.debug(f"{meter_name} has no new updates")
                    # continue  # noqa: ERA001
                else:
                    LOGGER.debug(f"{meter_name} has new updates")

                meter_data = HAUSMSMeterData.from_meter(meter)

                # get last month's total consumption and cost
                LOGGER.debug(
                    f"Fetching last month's consumptions for {meter_data.name}"
                )
                last_month_consumptions = await meter.get_previous_n_month_consumptions(
                    n=1
                )
                meter_data.last_month_total_consumption = (
                    meter.calculate_total_consumption(last_month_consumptions)
                )
                meter_data.last_month_total_cost = meter.calculate_total_cost(
                    last_month_consumptions
                )

                # get this month's total consumption and cost
                LOGGER.debug(
                    f"Fetching this month's consumptions for {meter_data.name}"
                )
                this_month_consumptions = await meter.get_previous_n_month_consumptions(
                    n=0
                )
                meter_data.this_month_total_consumption = (
                    meter.calculate_total_consumption(this_month_consumptions)
                )
                meter_data.this_month_total_cost = meter.calculate_total_cost(
                    this_month_consumptions
                )

                # get last 3 days of hourly consumptions
                LOGGER.debug(
                    f"Fetching the last 3 days' consumptions for {meter_data.name}"
                )
                last_3_days_hourly_consumptions = (
                    await meter.get_last_n_days_hourly_consumptions(n=3)
                )
                last_3_days_df = consumptions_series_to_dataframe(
                    last_3_days_hourly_consumptions
                )

                # get meter's old statistics
                old_statistics = await get_sensor_statistics(
                    self.hass,
                    f"sensor.{meter_data.unique_id}",
                )
                old_statistics_df = statistics_to_dataframe(old_statistics)

                # combine and replace last_3_days_df into old_statistics_df
                temp_statistics_df = old_statistics_df.combine_first(last_3_days_df)
                # calculate cumulative sum for the state column
                temp_statistics_df["sum"] = temp_statistics_df["state"].cumsum()

                # get new statistics only
                new_statistics_df = dataframe_diff(
                    old_statistics_df, temp_statistics_df
                )
                # convert statistics df to statistics list
                meter_data.new_statistics = dataframe_to_statistics(new_statistics_df)

                meters.append(meter_data)
                LOGGER.debug(f"Finished fetching updates for {meter_data.name}")

                return meters
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
