"""
Custom integration to integrate USMS with Home Assistant.

For more details about this integration, please refer to
https://github.com/azsaurr/ha_usms
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import DOMAIN, LOGGER
from .coordinator import HAUSMSDataUpdateCoordinator
from .data import HAUSMSRuntimeData

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
        config_entry=entry,
        logger=LOGGER,
        name=DOMAIN,
    )
    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    entry.runtime_data = HAUSMSRuntimeData(coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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


async def _async_update_listener(
    hass: HomeAssistant,
    entry: HAUSMSConfigEntry,
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
