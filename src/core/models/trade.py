from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.models.enums import PositionSide


class ClosedTrade(BaseModel):
    symbol: str
    side: PositionSide
    qty: float
    entry_price: float
    exit_price: float
    entry_timestamp: datetime
    exit_timestamp: datetime
    pnl: float

    model_config = ConfigDict(extra="forbid")
