# ruff: noqa: RET504
"""Helper functions for HA-USMS."""

from datetime import datetime

import pandas as pd
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from usms import BRUNEI_TZ

from .const import LOGGER


async def get_sensor_statistics(hass: HomeAssistant, statistic_id: str) -> list:
    """Return the sensor statistics for a given statistic_id."""
    LOGGER.debug(
        f"Retrieving statistics from recorder for statistic_id: {statistic_id}"
    )
    statistics = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime.fromtimestamp(0, tz=BRUNEI_TZ),
        None,
        [statistic_id],
        "hour",
        None,
        ["state", "sum"],
    )
    statistics = statistics.get(statistic_id, [])
    if statistics != []:
        LOGGER.debug(
            f"Retrieved statistics from recorder for statistic_id: {statistic_id}"
        )
    else:
        LOGGER.debug(f"No statistics recorded yet for statistic_id: {statistic_id}")
    return statistics


def consumptions_series_to_dataframe(consumptions: pd.Series) -> pd.DataFrame:
    """Return given consumptions pd.Series as DataFrame."""
    consumptions.index.name = "start"
    consumptions.name = "state"
    consumptions_df = consumptions.reset_index()
    consumptions_df = consumptions_df.set_index("start")
    consumptions_df.index.name = "start"
    consumptions_df = consumptions_df[["state"]]
    return consumptions_df


def statistics_to_dataframe(statistics: list) -> pd.DataFrame:
    """Return given statistics list [{"start":datetime, "state":float}] as DataFrame."""
    if statistics == []:
        dt_index = pd.DatetimeIndex([], name="start", tz=BRUNEI_TZ)
        statistics_df = pd.DataFrame(columns=["state", "sum"], index=dt_index)
        return statistics_df

    statistics_df = pd.DataFrame(statistics)
    statistics_df["start"] = pd.to_datetime(statistics_df["start"], unit="s", utc=True)
    statistics_df["start"] = statistics_df["start"].dt.tz_convert(BRUNEI_TZ)
    statistics_df = statistics_df.set_index("start")
    statistics_df = statistics_df[["state", "sum"]]
    return statistics_df


def dataframe_to_statistics(dataframe: pd.DataFrame) -> list:
    """Return given df as statistics [{"start":datetime, "state":float,"sum":float}]."""
    dataframe.index.name = "start"
    statistics = dataframe.reset_index().to_dict(orient="records")
    return statistics


def dataframe_diff(
    old_dataframe: pd.DataFrame,
    new_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Return the diff (updated or new rows) between two dataframes."""
    old_dataframe = old_dataframe.reindex(new_dataframe.index)
    diff_mask = old_dataframe.ne(new_dataframe)
    new_dataframe = new_dataframe[diff_mask.any(axis=1)]
    return new_dataframe
