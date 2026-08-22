"""Button platform for HA-USMS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.components.recorder.statistics import async_import_statistics
from slugify import slugify

from .const import LOGGER
from .entity import HAUSMSEntity
from .helpers import (
    get_missing_days,
    get_sensor_statistics,
    map_to_statistics,
    statistics_diff,
    statistics_to_map,
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

    async_add_entities(
        button_class(coordinator, meter_data)
        for meter_data in coordinator.data
        for button_class in (
            HAUSMSMeterDownloadStatisticsButton,
            HAUSMSMeterRecalculateStatisticsButton,
            HAUSMSMeterDownloadMissingStatisticsButton,
        )
    )


class HAUSMSMeterButton(HAUSMSEntity, ButtonEntity):
    """Base for the per-meter statistics buttons."""

    _name_suffix: str

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialise button."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return f"{self.meter_data.name} {self._name_suffix}"

    @property
    def unique_id(self) -> str:
        """Return unique id of the button."""
        return slugify(self.name, separator="_")

    async def _get_statistics(self) -> list:
        """Return the statistics currently recorded for this meter."""
        return await get_sensor_statistics(self.hass, self.meter_data.statistic_id)

    async def _import_statistics(self, statistics: list) -> None:
        """Write the given statistics into the recorder."""
        await self.hass.async_add_executor_job(
            async_import_statistics,
            self.hass,
            self.meter_data.metadata,
            statistics,
        )


class HAUSMSMeterDownloadStatisticsButton(HAUSMSMeterButton):
    """Download the meter's entire consumption history."""

    _name_suffix = "Download Statistics"
    _attr_device_class = ButtonDeviceClass.UPDATE

    async def async_press(self) -> None:
        """Press the button."""
        LOGGER.info(
            "Fetching all consumptions history for %s, please wait...",
            self.meter_data.name,
        )
        hourly_consumptions = await self.meter_data.get_all_hourly_consumptions()

        await self._import_statistics(map_to_statistics(hourly_consumptions))
        LOGGER.info(
            "Finished downloading all consumptions history for %s", self.meter_data.name
        )


class HAUSMSMeterRecalculateStatisticsButton(HAUSMSMeterButton):
    """Recalculate the cumulative sum of the meter's recorded statistics."""

    _name_suffix = "Recalculate Statistics"
    _attr_device_class = ButtonDeviceClass.RESTART

    async def async_press(self) -> None:
        """Press the button."""
        statistics = await self._get_statistics()
        if not statistics:
            LOGGER.error("No statistics found for %s", self.meter_data.statistic_id)
            return

        await self._import_statistics(map_to_statistics(statistics_to_map(statistics)))
        LOGGER.info(
            "Finished recalculating statistics for %s", self.meter_data.statistic_id
        )


class HAUSMSMeterDownloadMissingStatisticsButton(HAUSMSMeterButton):
    """Backfill days that have no, or incomplete, hourly statistics."""

    _name_suffix = "Download Missing Statistics"
    _attr_device_class = ButtonDeviceClass.UPDATE

    async def async_press(self) -> None:
        """Press the button."""
        old_statistics = await self._get_statistics()
        if not old_statistics:
            LOGGER.error("No statistics found for %s", self.meter_data.statistic_id)
            return

        # Fetch consumptions for each missing day
        missing_consumptions: dict = {}
        for date in get_missing_days(old_statistics):
            missing_consumptions.update(
                await self.meter_data.fetch_hourly_consumptions(date)
            )

        # Already recorded statistics win over anything refetched
        combined = {**missing_consumptions, **statistics_to_map(old_statistics)}
        new_statistics = statistics_diff(old_statistics, map_to_statistics(combined))

        await self._import_statistics(new_statistics)
        LOGGER.info(
            "Finished downloading missing statistics for %s",
            self.meter_data.statistic_id,
        )
