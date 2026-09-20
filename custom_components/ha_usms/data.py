"""Custom types for HA-USMS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from homeassistant.components.recorder.models.statistics import StatisticMeanType
from slugify import slugify
from usms import AsyncUSMSMeter

from .const import EXTERNAL_STATISTIC_SOURCE, UNIT_CLASSES

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

    # Projection of the current calendar month, filled in by the coordinator.
    # None until enough history exists (a fresh install with no recorded days).
    projected_month_consumption: float | None = None
    projected_month_cost: float | None = None
    projected_daily_consumption: float | None = None
    credit_runs_out_at: datetime | None = None

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
        """Return the external statistic_id for this meter's consumption.

        External statistics use ``<source>:<object_id>`` (a colon, not a dot)
        so the recorder treats them as externally managed and does not raise a
        state-class repair against the remaining-units sensor.
        """
        return f"{EXTERNAL_STATISTIC_SOURCE}:{self.unique_id}"

    @property
    def metadata(self) -> StatisticMetaData:
        """Return a StatisticMetaData for the sensor associated with this meter."""
        return {
            # Consumption is a cumulative total, never a mean. `mean_type`
            # replaces the deprecated `has_mean` flag, which HA Core removes
            # in 2026.11 along with making `unit_class` mandatory.
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": self.name,
            "source": EXTERNAL_STATISTIC_SOURCE,
            "statistic_id": self.statistic_id,
            "unit_class": UNIT_CLASSES.get(self.unit),
            "unit_of_measurement": self.unit,
        }
