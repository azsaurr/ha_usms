"""Sensor platform for HA-USMS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback

from .const import LOGGER
from .entity import HAUSMSEntity

if TYPE_CHECKING:
    from homeassistant.components.recorder.models.statistics import StatisticMetaData
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import HAUSMSDataUpdateCoordinator
    from .data import HAUSMSConfigEntry, HAUSMSMeterData


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: HAUSMSConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: HAUSMSDataUpdateCoordinator = entry.runtime_data.coordinator

    async_add_entities(
        HAUSMSMeterSensor(
            coordinator,
            meter_data,
        )
        for meter_data in coordinator.data
    )


class HAUSMSMeterSensor(HAUSMSEntity, SensorEntity):
    """HA-USMS meter Sensor class."""

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialize the meter sensor class."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update meter sensor with latest data from coordinator."""
        temp_meter_data = self.coordinator.get_meter_data_by_no(self.meter_data.no)

        if temp_meter_data.new_statistics != []:
            LOGGER.info(
                f"Importing {len(temp_meter_data.new_statistics)} new statistics for statistic_id: {self.meter_data.statistic_id}"  # noqa: E501
            )
            async_import_statistics(
                self.hass,
                self.metadata,
                temp_meter_data.new_statistics,
            )

        if self.meter_data.last_refresh != temp_meter_data.last_refresh:
            if self.meter_data.last_update != temp_meter_data.last_update:
                LOGGER.info(f"{self.name} was updated")
            else:
                LOGGER.info(f"{self.name} was refreshed, but no new updates were found")
            self.meter_data = temp_meter_data
            self.async_write_ha_state()

    @property
    def device_class(self) -> str | None:
        """Return device class of the meter sensor."""
        meter_type = self.meter_data.type.upper()
        if "ELECTRIC" in meter_type or "ENERGY" in meter_type:
            return SensorDeviceClass.ENERGY
        if "WATER" in meter_type:
            return SensorDeviceClass.WATER
        return None

    @property
    def metadata(self) -> StatisticMetaData:
        """Return statistic metadata of the meter sensor."""
        return self.meter_data.metadata

    @property
    def name(self) -> str:
        """Return the name of the meter sensor."""
        return self.meter_data.name

    @property
    def native_value(self) -> float:
        """Return the state of the meter sensor."""
        return self.meter_data.remaining_unit

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement of the meter sensor."""
        return self.meter_data.unit

    @property
    def state_class(self) -> str:
        """Return state class of the meter sensor."""
        # Purposely return None, so that current state will not be recorded
        # into long-term statistics by HomeAssistant
        return None

    @property
    def unique_id(self) -> str:
        """Return unique id of the meter sensor."""
        return self.meter_data.unique_id

    @property
    def extra_state_attributes(self) -> dict:
        """Return the extra state attributes of the meter sensor."""
        attrs = {}

        attrs["credit"] = self.meter_data.remaining_credit
        attrs["unit"] = self.meter_data.remaining_unit
        attrs["last_update"] = self.meter_data.last_update
        attrs["last_refresh"] = self.meter_data.last_refresh
        attrs["next_refresh"] = self.meter_data.next_refresh

        attrs["currency"] = self.meter_data.currency

        attrs["last_month_consumption"] = self.meter_data.last_month_total_consumption
        attrs["last_month_cost"] = self.meter_data.last_month_total_cost

        attrs["this_month_consumption"] = self.meter_data.this_month_total_consumption
        attrs["this_month_cost"] = self.meter_data.this_month_total_cost

        return attrs
