from pydantic import BaseModel, ConfigDict

from core.models.enums import TrendColor


class IndicatorSnapshot(BaseModel):
    ha_open: float
    ha_close: float
    nw_upper: float
    nw_lower: float
    mkr_value: float
    mkr_color: TrendColor
    trend_meter_all_green: bool
    trend_meter_all_red: bool

    model_config = ConfigDict(extra="forbid")
