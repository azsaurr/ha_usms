"""Button platform for HA-USMS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.components.recorder.statistics import async_import_statistics
from slugify import slugify
from usms.utils.helpers import new_consumptions_dataframe

from .const import LOGGER
from .entity import HAUSMSEntity
from .helpers import (
    consumptions_series_to_dataframe,
    dataframe_diff,
    dataframe_to_statistics,
    get_missing_days,
    get_sensor_statistics,
    statistics_to_dataframe,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import HAUSMSDataUpdateCoordinator
    from .data import HAUSMSConfigEntry, HAUSMSMeterData


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: HAUSMSConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator: HAUSMSDataUpdateCoordinator = entry.runtime_data.coordinator

    buttons = []
    for meter_data in coordinator.data:
        buttons.append(
            HAUSMSMeterDownloadStatisticsButton(
                coordinator,
                meter_data,
            )
        )
        buttons.append(
            HAUSMSMeterRecalculateStatisticsButton(
                coordinator,
                meter_data,
            )
        )
        buttons.append(
            HAUSMSMeterDownloadMissingStatisticsButton(
                coordinator,
                meter_data,
            )
        )
    async_add_entities(buttons)


class HAUSMSMeterDownloadStatisticsButton(HAUSMSEntity, ButtonEntity):
    """Implementation of a button."""

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialise button."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    async def async_press(self) -> None:
        """Press the button."""
        # get all hourly consumptions
        LOGGER.info(
            f"Fetching all consumptions history for {self.meter_data.name}, please wait..."  # noqa: E501
        )
        hourly_consumptions = await self.meter_data.get_all_hourly_consumptions()
        # rename index and column, and convert to dataframe
        hourly_consumptions_df = consumptions_series_to_dataframe(hourly_consumptions)
        # calculate sum column
        hourly_consumptions_df["sum"] = hourly_consumptions_df["state"].cumsum()
        # convert to statistics list
        hourly_consumptions_statistics = dataframe_to_statistics(hourly_consumptions_df)

        await self.hass.async_add_executor_job(
            async_import_statistics,
            self.hass,
            self.meter_data.metadata,
            hourly_consumptions_statistics,
        )
        LOGGER.info(
            f"Finished downloading all consumptions history for {self.meter_data.name}"
        )

    @property
    def device_class(self) -> ButtonDeviceClass:
        """Return the class of this button."""
        return ButtonDeviceClass.UPDATE

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return f"{self.meter_data.name} Download Statistics"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return slugify(self.name, separator="_")


class HAUSMSMeterRecalculateStatisticsButton(HAUSMSEntity, ButtonEntity):
    """Implementation of a button."""

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialise button."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    async def async_press(self) -> None:
        """Press the button."""
        # get meter's old statistics
        statistics = await get_sensor_statistics(
            self.hass,
            self.meter_data.statistic_id,
        )

        if statistics == []:
            LOGGER.error(f"No statistics found for {self.meter_data.statistic_id}")
            return

        # convert to dataframe
        statistics_df = statistics_to_dataframe(statistics)
        # calculate sum column
        statistics_df["sum"] = statistics_df["state"].cumsum()
        # convert back to statistics list
        new_statistics = dataframe_to_statistics(statistics_df)

        await self.hass.async_add_executor_job(
            async_import_statistics,
            self.hass,
            self.meter_data.metadata,
            new_statistics,
        )
        LOGGER.info(
            f"Finished recalculating statistics for {self.meter_data.statistic_id}"
        )

    @property
    def device_class(self) -> ButtonDeviceClass:
        """Return the class of this button."""
        return ButtonDeviceClass.RESTART

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return f"{self.meter_data.name} Recalculate Statistics"

    @property
    def unique_id(self) -> str:
        """Return unique id of the button."""
        return slugify(self.name, separator="_")


class HAUSMSMeterDownloadMissingStatisticsButton(HAUSMSEntity, ButtonEntity):
    """Implementation of a button."""

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialise button."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    async def async_press(self) -> None:
        """Press the button."""
        # get meter's old statistics
        old_statistics = await get_sensor_statistics(
            self.hass,
            self.meter_data.statistic_id,
        )
        if old_statistics == []:
            LOGGER.error(f"No statistics found for {self.meter_data.statistic_id}")
            return

        # convert to dataframe
        old_statistics_df = statistics_to_dataframe(old_statistics)

        # Fetch statistics for each missing day
        missing_statistics = new_consumptions_dataframe(self.meter_data.unit, "h")[
            self.meter_data.unit
        ]
        for date in await get_missing_days(statistics=old_statistics):
            day_statistics = await self.meter_data.fetch_hourly_consumptions(date)
            missing_statistics = day_statistics.combine_first(missing_statistics)
        missing_statistics_df = consumptions_series_to_dataframe(missing_statistics)

        # combine and replace new_statistics_df into old_statistics_df
        temp_statistics_df = old_statistics_df.combine_first(missing_statistics_df)
        # calculate cumulative sum for the state column
        temp_statistics_df["sum"] = temp_statistics_df["state"].cumsum()
        # get new statistics only
        new_statistics_df = dataframe_diff(old_statistics_df, temp_statistics_df)
        # convert back to statistics list
        new_statistics = dataframe_to_statistics(new_statistics_df)

        await self.hass.async_add_executor_job(
            async_import_statistics,
            self.hass,
            self.meter_data.metadata,
            new_statistics,
        )
        LOGGER.info(
            f"Finished downloading missing statistics for {self.meter_data.statistic_id}"  # noqa: E501
        )

    @property
    def device_class(self) -> ButtonDeviceClass:
        """Return the class of this button."""
        return ButtonDeviceClass.UPDATE

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return f"{self.meter_data.name} Download Missing Statistics"

    @property
    def unique_id(self) -> str:
        """Return unique id of the button."""
        return slugify(self.name, separator="_")
