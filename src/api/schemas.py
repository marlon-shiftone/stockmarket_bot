from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CandleIn(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    qty: float | None = None

    model_config = ConfigDict(extra="forbid")


class ReplayRequest(BaseModel):
    csv_path: str
    symbol: str
    qty: float | None = None
    initial_capital: float = Field(default=10000.0, gt=0)

    model_config = ConfigDict(extra="forbid")


class BacktestReportRequest(BaseModel):
    csv_path: str
    symbol: str | None = None
    qty: float | None = None
    initial_capital: float = Field(default=10000.0, gt=0)
    period: Literal["day", "week", "month"] = "day"
    output_dir: str = "reports/backtests"

    model_config = ConfigDict(extra="forbid")
