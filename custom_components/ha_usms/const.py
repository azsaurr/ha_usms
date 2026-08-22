"""Constants for HA-USMS."""

from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ha_usms"
ATTRIBUTION = "Data fetched from https://www.usms.com.bn/"

DEFAULT_SCAN_INTERVAL = 60 * 60
MIN_SCAN_INTERVAL = 10 * 60

# A day's worth of hourly statistics; fewer than this means the day is incomplete.
HOURS_PER_DAY: Final = 24

ELECTRIC_UNIT: Final = "kWh"
WATER_UNIT: Final = "m³"

# Maps a meter's unit to the Home Assistant unit converter that handles it.
# Required in StatisticMetaData since HA Core 2025.11; None means "no converter".
UNIT_CLASSES: Final[dict[str, str]] = {
    ELECTRIC_UNIT: "energy",
    WATER_UNIT: "volume",
}
