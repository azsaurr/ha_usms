"""Constants for HA-USMS."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ha_usms"
ATTRIBUTION = "Data fetched from https://www.usms.com.bn/"

DEFAULT_SCAN_INTERVAL = 60 * 60
MIN_SCAN_INTERVAL = 10 * 60
