from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.models.enums import SignalType
from core.models.indicator_snapshot import IndicatorSnapshot


class Signal(BaseModel):
    signal_type: SignalType
    symbol: str
    timestamp: datetime
    price: float
    reasons: list[str] = Field(default_factory=list)
    indicator_snapshot: IndicatorSnapshot | None = None

    model_config = ConfigDict(extra="forbid")
