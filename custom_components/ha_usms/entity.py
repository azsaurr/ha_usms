"""HAUSMSEntity class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ACCOUNT_URL, ATTRIBUTION
from .coordinator import HAUSMSDataUpdateCoordinator


class HAUSMSEntity(CoordinatorEntity[HAUSMSDataUpdateCoordinator]):
    """HAUSMSEntity class."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: HAUSMSDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info for this entity."""
        return DeviceInfo(
            manufacturer="USMS",
            configuration_url=ACCOUNT_URL,
            # NB: this was `{self.meter_data.name}` — a set literal, not a str.
            model=self.meter_data.name,
            identifiers={
                (
                    self.coordinator.config_entry.domain,
                    self.coordinator.config_entry.entry_id,
                ),
            },
        )
