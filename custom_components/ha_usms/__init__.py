"""
Custom integration to integrate USMS with Home Assistant.

For more details about this integration, please refer to
https://github.com/azsaurr/ha_usms
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.loader import async_get_loaded_integration
from usms import AsyncUSMSAccount

from .const import DOMAIN, LOGGER
from .coordinator import HAUSMSDataUpdateCoordinator
from .data import HAUSMSData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import HAUSMSConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: HAUSMSConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = HAUSMSDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(hours=1),
    )
    account = await AsyncUSMSAccount.create(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    entry.runtime_data = HAUSMSData(
        account=account,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HAUSMSConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: HAUSMSConfigEntry,
) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
