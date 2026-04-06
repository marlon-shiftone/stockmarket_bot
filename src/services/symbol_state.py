from collections import deque
from dataclasses import dataclass, field

from core.models.strategy_context import StrategyFrame


@dataclass
class SymbolState:
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    prev_frame: StrategyFrame | None = None
    prev_ha_open: float | None = None
    prev_ha_close: float | None = None
    prev_mkr_value: float | None = None
