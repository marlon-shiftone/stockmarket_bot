from abc import ABC, abstractmethod

from core.models.order import Order
from core.models.position import Position
from core.models.signal import Signal
from core.models.trade import ClosedTrade


class BrokerPort(ABC):
    @abstractmethod
    def place_order(self, signal: Signal, qty: float) -> Order | None:
        """Execute a signal as an order. Returns None for non-action signals."""

    @abstractmethod
    def list_orders(self) -> list[Order]:
        """Return historical orders."""

    @abstractmethod
    def list_positions(self) -> list[Position]:
        """Return current open positions."""

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """Return open position for symbol, if any."""

    def mark_price(self, symbol: str, price: float) -> None:
        """Update mark-to-market price for a symbol, if supported."""

    def get_realized_pnl(self) -> float:
        """Return realized PnL, if supported."""
        return 0.0

    def get_unrealized_pnl(self) -> float:
        """Return unrealized PnL, if supported."""
        return 0.0

    def list_closed_trades(self) -> list[ClosedTrade]:
        """Return closed trades, if supported."""
        return []

    @abstractmethod
    def reset(self) -> None:
        """Reset internal broker state."""
