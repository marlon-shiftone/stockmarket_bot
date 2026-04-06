from datetime import datetime

from pydantic import BaseModel

from core.models.candle import Candle
from core.models.order import Order
from core.models.position import Position
from core.models.signal import Signal
from core.models.trade import ClosedTrade
from core.ports.broker_port import BrokerPort
from infra.db.in_memory_store import InMemoryStore
from services.execution_engine import ExecutionEngine
from services.signal_engine import SignalEngine


DEFAULT_INITIAL_CAPITAL = 10000.0


class CandleProcessResult(BaseModel):
    signal: Signal
    order: Order | None


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float
    drawdown_pct: float


class BacktestMetrics(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    max_drawdown: float
    max_drawdown_pct: float
    equity_curve: list[EquityPoint]


class ReplaySummary(BaseModel):
    total_candles: int
    total_signals: int
    action_signals: int
    filled_orders: int
    rejected_orders: int
    initial_capital: float
    realized_pnl: float
    metrics: BacktestMetrics


class TradingRuntime:
    def __init__(
        self,
        signal_engine: SignalEngine,
        execution_engine: ExecutionEngine,
        broker: BrokerPort,
        store: InMemoryStore,
        default_order_qty: float = 1.0,
        trading_mode: str = "paper",
    ) -> None:
        self._signal_engine = signal_engine
        self._execution_engine = execution_engine
        self._broker = broker
        self._store = store
        self._default_order_qty = default_order_qty
        self._trading_mode = trading_mode

    def process_candle(self, candle: Candle, qty: float | None = None) -> CandleProcessResult:
        order_qty = qty if qty is not None else self._default_order_qty
        self._broker.mark_price(candle.symbol, candle.close)
        signal = self._signal_engine.process_candle(candle)
        self._store.add_signal(signal)
        order = self._execution_engine.execute(signal=signal, qty=order_qty)
        self._broker.mark_price(candle.symbol, candle.close)
        return CandleProcessResult(signal=signal, order=order)

    def replay(
        self,
        candles: list[Candle],
        qty: float | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    ) -> ReplaySummary:
        if self._trading_mode != "paper":
            raise RuntimeError("Replay is only available in TRADING_MODE=paper.")
        if initial_capital <= 0:
            raise ValueError("initial_capital must be greater than 0.")

        equity_curve: list[EquityPoint] = []
        peak_equity = initial_capital
        for candle in candles:
            self.process_candle(candle=candle, qty=qty)
            realized = self._broker.get_realized_pnl()
            unrealized = self._broker.get_unrealized_pnl()
            equity = initial_capital + realized + unrealized

            peak_equity = max(peak_equity, equity)
            drawdown = peak_equity - equity
            drawdown_pct = (drawdown / peak_equity * 100.0) if peak_equity > 0 else 0.0

            equity_curve.append(
                EquityPoint(
                    timestamp=candle.timestamp,
                    equity=equity,
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    drawdown=drawdown,
                    drawdown_pct=drawdown_pct,
                )
            )

        orders = self._broker.list_orders()
        filled_orders = sum(1 for order in orders if order.status.value == "FILLED")
        rejected_orders = sum(1 for order in orders if order.status.value == "REJECTED")
        signals = self._store.list_signals()
        action_signals = sum(1 for s in signals if s.signal_type.value != "NONE")
        closed_trades = self._broker.list_closed_trades()

        winning_trades = sum(1 for trade in closed_trades if trade.pnl > 0)
        losing_trades = sum(1 for trade in closed_trades if trade.pnl < 0)
        total_trades = len(closed_trades)
        gross_profit = sum(trade.pnl for trade in closed_trades if trade.pnl > 0)
        gross_loss = sum(trade.pnl for trade in closed_trades if trade.pnl < 0)
        net_profit = self._broker.get_realized_pnl()
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        max_drawdown = max((point.drawdown for point in equity_curve), default=0.0)
        max_drawdown_pct = max((point.drawdown_pct for point in equity_curve), default=0.0)

        metrics = BacktestMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=net_profit,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            equity_curve=equity_curve,
        )

        return ReplaySummary(
            total_candles=len(candles),
            total_signals=len(signals),
            action_signals=action_signals,
            filled_orders=filled_orders,
            rejected_orders=rejected_orders,
            initial_capital=initial_capital,
            realized_pnl=net_profit,
            metrics=metrics,
        )

    def list_signals(self) -> list[Signal]:
        return self._store.list_signals()

    def list_orders(self) -> list[Order]:
        return self._broker.list_orders()

    def list_positions(self) -> list[Position]:
        return self._broker.list_positions()

    def list_closed_trades(self) -> list[ClosedTrade]:
        return self._broker.list_closed_trades()

    def reset(self) -> None:
        self._signal_engine.reset()
        self._broker.reset()
        self._store.reset()
