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

    entities: list[SensorEntity] = []
    for meter_data in coordinator.data:
        entities.append(HAUSMSMeterSensor(coordinator, meter_data))
        entities.append(HAUSMSMeterDebtSensor(coordinator, meter_data))
    async_add_entities(entities)


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
                "Importing %s new statistics for statistic_id: %s",
                len(temp_meter_data.new_statistics),
                self.meter_data.statistic_id,
            )
            async_import_statistics(
                self.hass,
                self.metadata,
                temp_meter_data.new_statistics,
            )

        if self.meter_data.last_refresh != temp_meter_data.last_refresh:
            if self.meter_data.last_update != temp_meter_data.last_update:
                LOGGER.info("%s was updated", self.name)
            else:
                LOGGER.info(
                    "%s was refreshed, but no new updates were found", self.name
                )
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

        attrs["customer_type"] = self.meter_data.customer_type
        # Topping up cannot be automated: USMS hands off to the bank's secure
        # site for card entry, so surface the URL for the user to open.
        attrs["topup_url"] = self.meter_data.topup_url

        return attrs


class HAUSMSMeterDebtSensor(HAUSMSEntity, SensorEntity):
    """Outstanding debt owed on a USMS meter.

    USMS clears debt by deducting from top-ups, so this is worth alerting on:
    a non-zero value means part of every top-up is going to the debt rather
    than to credit.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    # Deliberately no state_class, matching the meter sensor: this integration
    # writes its own long-term statistics rather than letting the recorder
    # derive them.
    _attr_state_class = None

    def __init__(
        self,
        coordinator: HAUSMSDataUpdateCoordinator,
        meter_data: HAUSMSMeterData,
    ) -> None:
        """Initialize the meter debt sensor."""
        super().__init__(coordinator)
        self.meter_data = meter_data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the debt sensor with the latest data from the coordinator."""
        self.meter_data = self.coordinator.get_meter_data_by_no(self.meter_data.no)
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the name of the debt sensor."""
        return f"{self.meter_data.name} Debt"

    @property
    def unique_id(self) -> str:
        """Return unique id of the debt sensor."""
        return f"{self.meter_data.unique_id}_debt"

    @property
    def native_value(self) -> float:
        """Return the total debt owing."""
        return self.meter_data.total_debt_owing

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the currency the debt is denominated in."""
        return self.meter_data.currency

    @property
    def extra_state_attributes(self) -> dict:
        """Return the remaining debt detail."""
        return {
            "debt_balance_remaining": self.meter_data.debt_balance_remaining,
            "monthly_debt_amount": self.meter_data.monthly_debt_amount,
            "debt_repayment_period": self.meter_data.debt_repayment_period,
            "debt_period_remaining": self.meter_data.debt_period_remaining,
            "debt_clearance_model": self.meter_data.debt_clearance_model,
            "has_debt": self.meter_data.has_debt,
            "topup_url": self.meter_data.topup_url,
        }
