"""Custom types for HA-USMS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from slugify import slugify
from usms import AsyncUSMSMeter

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.components.recorder.models.statistics import StatisticMetaData
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import HAUSMSDataUpdateCoordinator


type HAUSMSConfigEntry = ConfigEntry[HAUSMSRuntimeData]


@dataclass
class HAUSMSRuntimeData:
    """Data for the HAUSMS integration."""

    coordinator: HAUSMSDataUpdateCoordinator


@dataclass
class HAUSMSMeterData(AsyncUSMSMeter):
    """Class to hold HA-USMS Meter data, to be stored in coordinator.data."""

    last_refresh: datetime
    next_refresh: datetime

    last_month_total_consumption: float
    last_month_total_cost: float

    this_month_total_consumption: float
    this_month_total_cost: float

    new_statistics: list

    currency: str = "BND"

    @classmethod
    def from_meter(cls, meter: AsyncUSMSMeter, **kwargs: dict) -> Self:
        """Return a HAUSMSMeterData based on a AsyncUSMSMeter."""
        meter_data = cls.__new__(cls)
        meter_data.__dict__ = meter.__dict__.copy()

        for k, v in kwargs.items():
            setattr(meter_data, k, v)

        return meter_data

    @property
    def name(self) -> str:
        """Return the name of the meter."""
        return f"{self.type} Meter {self.no}"

    @property
    def unique_id(self) -> str:
        """Return a unique_id for this meter."""
        return slugify(self.name, separator="_")

    @property
    def statistic_id(self) -> str:
        """Return the statistic_id for the sensor associated with this meter."""
        return f"sensor.{self.unique_id}"

    @property
    def metadata(self) -> StatisticMetaData:
        """Return a StatisticMetaData for the sensor associated with this meter."""
        return {
            "has_mean": False,
            "has_sum": True,
            "name": self.name,
            "source": "recorder",
            "statistic_id": self.statistic_id,
            "unit_of_measurement": self.unit,
        }
