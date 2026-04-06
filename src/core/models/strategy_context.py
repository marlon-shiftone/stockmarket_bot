from pydantic import BaseModel, ConfigDict

from core.models.candle import Candle
from core.models.indicator_snapshot import IndicatorSnapshot


class StrategyFrame(BaseModel):
    candle: Candle
    indicators: IndicatorSnapshot

    model_config = ConfigDict(extra="forbid")
