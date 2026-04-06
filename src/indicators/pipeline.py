from pydantic import BaseModel, ConfigDict

from core.models.candle import Candle
from core.models.indicator_snapshot import IndicatorSnapshot
from indicators.heiken_ashi import compute_heiken_ashi
from indicators.multi_kernel_regression import compute_multi_kernel_regression
from indicators.nadaraya_watson import compute_nadaraya_watson_envelope
from indicators.trend_meter_macd import compute_trend_meter_macd


class IndicatorComputation(BaseModel):
    snapshot: IndicatorSnapshot
    ha_open: float
    ha_close: float
    mkr_value: float

    model_config = ConfigDict(extra="forbid")


class IndicatorCalculator:
    def __init__(
        self,
        nw_bandwidth: float = 8.0,
        nw_mult: float = 3.0,
        mkr_bandwidth: float = 9.0,
    ) -> None:
        self.nw_bandwidth = nw_bandwidth
        self.nw_mult = nw_mult
        self.mkr_bandwidth = mkr_bandwidth

    def compute(
        self,
        candle: Candle,
        closes: list[float],
        prev_ha_open: float | None,
        prev_ha_close: float | None,
        prev_mkr_value: float | None,
    ) -> IndicatorComputation:
        ha_open, ha_close = compute_heiken_ashi(
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            prev_ha_open,
            prev_ha_close,
        )
        _, nw_upper, nw_lower = compute_nadaraya_watson_envelope(
            closes,
            bandwidth=self.nw_bandwidth,
            mult=self.nw_mult,
        )
        mkr_value, mkr_color = compute_multi_kernel_regression(
            closes,
            bandwidth=self.mkr_bandwidth,
            prev_value=prev_mkr_value,
        )
        tm_green, tm_red = compute_trend_meter_macd(closes)

        snapshot = IndicatorSnapshot(
            ha_open=ha_open,
            ha_close=ha_close,
            nw_upper=nw_upper,
            nw_lower=nw_lower,
            mkr_value=mkr_value,
            mkr_color=mkr_color,
            trend_meter_all_green=tm_green,
            trend_meter_all_red=tm_red,
        )
        return IndicatorComputation(
            snapshot=snapshot,
            ha_open=ha_open,
            ha_close=ha_close,
            mkr_value=mkr_value,
        )
