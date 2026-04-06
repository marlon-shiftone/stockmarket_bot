import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OperationalCandidate(BaseModel):
    nw_bandwidth: float
    nw_mult: float
    mkr_bandwidth: float
    require_confirmation: bool
    require_trend_meter: bool
    require_mkr_alignment: bool

    model_config = ConfigDict(extra="forbid")


class OperationalDatasetEntry(BaseModel):
    symbol: str
    timeframe: str
    selection_basis: str
    candidate: OperationalCandidate | None = None
    metrics: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class OperationalParamsFile(BaseModel):
    selection_source: str
    generated_at: str | None = None
    initial_capital: float | None = None
    qty: float | None = None
    constraints: dict[str, Any] | None = None
    datasets: list[OperationalDatasetEntry] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


def load_operational_params(path: str | Path) -> OperationalParamsFile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return OperationalParamsFile.model_validate(payload)


def resolve_operational_selection(
    path: str | Path,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> tuple[OperationalParamsFile, OperationalDatasetEntry]:
    params = load_operational_params(path)
    matches = params.datasets
    if symbol:
        matches = [item for item in matches if item.symbol == symbol]
    if timeframe:
        matches = [item for item in matches if item.timeframe == timeframe]

    if not matches:
        raise ValueError(
            "No operational parameter dataset matched the requested selection: "
            f"symbol={symbol or '*'} timeframe={timeframe or '*'}"
        )
    if len(matches) > 1:
        raise ValueError(
            "Multiple operational parameter datasets matched the requested selection. "
            "Specify SYMBOL and ALPACA_BAR_TIMEFRAME more precisely."
        )

    selected = matches[0]
    if selected.candidate is None:
        raise ValueError(
            "Operational parameter dataset does not contain a candidate selection for "
            f"symbol={selected.symbol} timeframe={selected.timeframe}."
        )
    return params, selected
