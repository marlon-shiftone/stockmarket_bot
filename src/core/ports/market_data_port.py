from abc import ABC, abstractmethod

from core.models.candle import Candle


class MarketDataPort(ABC):
    @abstractmethod
    def load_candles(self, source: str, symbol: str) -> list[Candle]:
        """Load candles from a source (file path, endpoint, etc.)."""
