from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Candle(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    model_config = ConfigDict(extra="forbid")
