from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.models.enums import OrderSide, OrderStatus, SignalType


class Order(BaseModel):
    id: str
    symbol: str
    timestamp: datetime
    side: OrderSide
    qty: float
    price: float
    status: OrderStatus
    source_signal: SignalType
    note: str = "paper execution"

    model_config = ConfigDict(extra="forbid")
