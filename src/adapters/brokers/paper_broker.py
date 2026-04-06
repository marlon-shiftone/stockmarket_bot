from datetime import datetime, timezone
from uuid import uuid4

from core.models.enums import OrderSide, OrderStatus, PositionSide, SignalType
from core.models.order import Order
from core.models.position import Position
from core.models.signal import Signal
from core.models.trade import ClosedTrade
from core.ports.broker_port import BrokerPort


class PaperBroker(BrokerPort):
    def __init__(self) -> None:
        self._orders: list[Order] = []
        self._positions: dict[str, Position] = {}
        self._closed_trades: list[ClosedTrade] = []
        self._realized_pnl: float = 0.0

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    def _reject(self, signal: Signal, qty: float, note: str) -> Order:
        order = Order(
            id=str(uuid4()),
            symbol=signal.symbol,
            timestamp=datetime.now(timezone.utc),
            side=OrderSide.BUY if signal.signal_type in (SignalType.BUY, SignalType.CLOSE_SELL) else OrderSide.SELL,
            qty=qty,
            price=signal.price,
            status=OrderStatus.REJECTED,
            source_signal=signal.signal_type,
            note=note,
        )
        self._orders.append(order)
        return order

    def place_order(self, signal: Signal, qty: float) -> Order | None:
        if signal.signal_type == SignalType.NONE:
            return None

        existing = self._positions.get(signal.symbol)
        now = datetime.now(timezone.utc)

        if signal.signal_type == SignalType.BUY:
            if existing is not None:
                return self._reject(signal, qty, "Position already open")
            self._positions[signal.symbol] = Position(
                symbol=signal.symbol,
                side=PositionSide.LONG,
                qty=qty,
                entry_price=signal.price,
                entry_timestamp=signal.timestamp,
                last_price=signal.price,
            )
            side = OrderSide.BUY
            note = "Opened LONG"

        elif signal.signal_type == SignalType.SELL:
            if existing is not None:
                return self._reject(signal, qty, "Position already open")
            self._positions[signal.symbol] = Position(
                symbol=signal.symbol,
                side=PositionSide.SHORT,
                qty=qty,
                entry_price=signal.price,
                entry_timestamp=signal.timestamp,
                last_price=signal.price,
            )
            side = OrderSide.SELL
            note = "Opened SHORT"

        elif signal.signal_type == SignalType.CLOSE_BUY:
            if existing is None or existing.side != PositionSide.LONG:
                return self._reject(signal, qty, "No LONG position to close")
            execution_qty = existing.qty
            pnl = (signal.price - existing.entry_price) * execution_qty
            self._realized_pnl += pnl
            self._closed_trades.append(
                ClosedTrade(
                    symbol=signal.symbol,
                    side=PositionSide.LONG,
                    qty=execution_qty,
                    entry_price=existing.entry_price,
                    exit_price=signal.price,
                    entry_timestamp=existing.entry_timestamp,
                    exit_timestamp=signal.timestamp,
                    pnl=pnl,
                )
            )
            del self._positions[signal.symbol]
            side = OrderSide.SELL
            qty = execution_qty
            note = "Closed LONG"

        elif signal.signal_type == SignalType.CLOSE_SELL:
            if existing is None or existing.side != PositionSide.SHORT:
                return self._reject(signal, qty, "No SHORT position to close")
            execution_qty = existing.qty
            pnl = (existing.entry_price - signal.price) * execution_qty
            self._realized_pnl += pnl
            self._closed_trades.append(
                ClosedTrade(
                    symbol=signal.symbol,
                    side=PositionSide.SHORT,
                    qty=execution_qty,
                    entry_price=existing.entry_price,
                    exit_price=signal.price,
                    entry_timestamp=existing.entry_timestamp,
                    exit_timestamp=signal.timestamp,
                    pnl=pnl,
                )
            )
            del self._positions[signal.symbol]
            side = OrderSide.BUY
            qty = execution_qty
            note = "Closed SHORT"

        else:
            return self._reject(signal, qty, "Unsupported signal")

        order = Order(
            id=str(uuid4()),
            symbol=signal.symbol,
            timestamp=now,
            side=side,
            qty=qty,
            price=signal.price,
            status=OrderStatus.FILLED,
            source_signal=signal.signal_type,
            note=note,
        )
        self._orders.append(order)
        return order

    def list_orders(self) -> list[Order]:
        return list(self._orders)

    def list_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def mark_price(self, symbol: str, price: float) -> None:
        position = self._positions.get(symbol)
        if position is None:
            return
        self._positions[symbol] = position.model_copy(update={"last_price": price})

    def get_realized_pnl(self) -> float:
        return self._realized_pnl

    def get_unrealized_pnl(self) -> float:
        total = 0.0
        for position in self._positions.values():
            if position.side == PositionSide.LONG:
                total += (position.last_price - position.entry_price) * position.qty
            else:
                total += (position.entry_price - position.last_price) * position.qty
        return total

    def list_closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed_trades)

    def reset(self) -> None:
        self._orders.clear()
        self._positions.clear()
        self._closed_trades.clear()
        self._realized_pnl = 0.0
