"""Constants for HA-USMS."""

from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ha_usms"
ATTRIBUTION = "Data fetched from https://www.usms.com.bn/"

# Shown as the "Visit" link on the device page, alongside the per-meter Top Up
# buttons. The device covers the whole account, so this points at the account
# home rather than any one meter's top up page.
ACCOUNT_URL: Final = "https://www.usms.com.bn/SmartMeter/Home"

DEFAULT_SCAN_INTERVAL = 60 * 60
MIN_SCAN_INTERVAL = 10 * 60

# Long-term statistics are published as *external* statistics under this domain
# prefix (e.g. "ha_usms:electricity_meter_55014488") rather than under the
# sensor's own entity id. External statistics are not policed by the sensor
# recorder, which is what raised the recurring "no longer has a state class"
# repair: the meter entity reports *remaining* units (a level, no state_class)
# while the statistic it owns is cumulative *consumption*.
EXTERNAL_STATISTIC_SOURCE: Final = DOMAIN

# Rolling window (in days) used to project the current month's total from the
# recent daily consumption rate. Chosen empirically: a 7-day trailing mean
# blended 50/50 with the month-to-date rate gave the lowest backtested error
# (~4% by day 7, ~1% by day 25) across two years of hourly data, and needs no
# numpy so it runs on constrained hosts.
PROJECTION_TRAILING_DAYS: Final = 7

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
