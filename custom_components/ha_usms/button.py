"""Button platform for HA-USMS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import persistent_notification
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
            HAUSMSMeterTopUpButton,
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
        if self.meter_data.supports_hourly_consumptions:
            consumptions = await self.meter_data.get_all_hourly_consumptions()
        else:
            # Water exposes no hourly report; its history is daily-resolution only.
            consumptions = await self.meter_data.get_all_daily_consumptions()

        await self._import_statistics(map_to_statistics(consumptions))
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

        missing_consumptions: dict = {}
        if self.meter_data.supports_hourly_consumptions:
            # Fetch consumptions for each missing day
            for date in get_missing_days(old_statistics):
                missing_consumptions.update(
                    await self.meter_data.fetch_hourly_consumptions(date)
                )
        else:
            # Water has one reading per day, so "missing hours" is meaningless.
            # Refetching the whole daily history closes any gaps instead.
            missing_consumptions = await self.meter_data.get_all_daily_consumptions()

        # Already recorded statistics win over anything refetched
        combined = {**missing_consumptions, **statistics_to_map(old_statistics)}
        new_statistics = statistics_diff(old_statistics, map_to_statistics(combined))

        await self._import_statistics(new_statistics)
        LOGGER.info(
            "Finished downloading missing statistics for %s",
            self.meter_data.statistic_id,
        )


class HAUSMSMeterTopUpButton(HAUSMSMeterButton):
    """Surface the meter's USMS Top Up page.

    Topping up cannot be automated: USMS hands the payment off to the bank's
    secure site for card entry. A button press also cannot open a browser tab,
    since it runs on the server, so this raises a notification carrying the
    link instead - which is clickable from any dashboard or the companion app.
    """

    _name_suffix = "Top Up"

    async def async_press(self) -> None:
        """Press the button."""
        persistent_notification.async_create(
            self.hass,
            title=f"Top up {self.meter_data.name}",
            message=(
                f"Remaining credit: **{self.meter_data.currency} "
                f"{self.meter_data.remaining_credit:.2f}** "
                f"({self.meter_data.remaining_unit} {self.meter_data.unit})\n\n"
                f"[Open the USMS top up page]({self.meter_data.topup_url})\n\n"
                "Payment is completed on your bank's secure site."
            ),
            # A fixed id means repeated presses replace the notice rather than
            # stacking up copies of it.
            notification_id=f"{self.meter_data.unique_id}_topup",
        )
        LOGGER.debug("Raised top up notification for %s", self.meter_data.name)
