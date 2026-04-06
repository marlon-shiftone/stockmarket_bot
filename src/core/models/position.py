from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.models.enums import PositionSide


class Position(BaseModel):
    symbol: str
    side: PositionSide
    qty: float
    entry_price: float
    entry_timestamp: datetime
    last_price: float

    model_config = ConfigDict(extra="forbid")
