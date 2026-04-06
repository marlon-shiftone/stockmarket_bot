from datetime import datetime, timedelta, timezone

import pytest

from adapters.brokers.paper_broker import PaperBroker
from core.models.candle import Candle
from core.models.enums import SignalType
from core.models.signal import Signal
from infra.db.in_memory_store import InMemoryStore
from services.execution_engine import ExecutionEngine
from services.trading_runtime import TradingRuntime


class StubSignalEngine:
    def __init__(self, signal_types: list[SignalType]) -> None:
        self._signal_types = signal_types
        self._index = 0

    def process_candle(self, candle: Candle) -> Signal:
        signal_type = self._signal_types[self._index]
        self._index += 1
        return Signal(
            signal_type=signal_type,
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            price=candle.close,
            reasons=["stub"],
        )

    def reset(self) -> None:
        self._index = 0


def _candles() -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                symbol="PETR4",
                timestamp=base + timedelta(minutes=idx),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
            )
        )
    return candles


def test_replay_metrics_include_win_rate_drawdown_and_equity_curve() -> None:
    signal_engine = StubSignalEngine(
        [
            SignalType.BUY,
            SignalType.NONE,
            SignalType.CLOSE_BUY,
            SignalType.SELL,
            SignalType.CLOSE_SELL,
        ]
    )
    broker = PaperBroker()
    runtime = TradingRuntime(
        signal_engine=signal_engine,
        execution_engine=ExecutionEngine(broker=broker, trading_mode="paper"),
        broker=broker,
        store=InMemoryStore(),
        default_order_qty=1.0,
        trading_mode="paper",
    )

    summary = runtime.replay(_candles(), initial_capital=100.0)

    assert summary.initial_capital == 100.0
    assert summary.metrics.total_trades == 2
    assert summary.metrics.winning_trades == 1
    assert summary.metrics.losing_trades == 1
    assert summary.metrics.win_rate == 50.0
    assert summary.metrics.max_drawdown == 1.0
    assert summary.metrics.max_drawdown_pct == pytest.approx(0.9803921568627451)
    assert summary.realized_pnl == 1.0
    assert summary.metrics.equity_curve[0].equity == 100.0
    assert len(summary.metrics.equity_curve) == 5


def test_replay_rejects_non_positive_initial_capital() -> None:
    signal_engine = StubSignalEngine([SignalType.NONE])
    broker = PaperBroker()
    runtime = TradingRuntime(
        signal_engine=signal_engine,
        execution_engine=ExecutionEngine(broker=broker, trading_mode="paper"),
        broker=broker,
        store=InMemoryStore(),
        default_order_qty=1.0,
        trading_mode="paper",
    )

    with pytest.raises(ValueError, match="initial_capital"):
        runtime.replay(_candles()[:1], initial_capital=0.0)


def test_replay_is_blocked_in_live_mode() -> None:
    signal_engine = StubSignalEngine([SignalType.NONE])
    broker = PaperBroker()
    runtime = TradingRuntime(
        signal_engine=signal_engine,
        execution_engine=ExecutionEngine(broker=broker, trading_mode="paper"),
        broker=broker,
        store=InMemoryStore(),
        default_order_qty=1.0,
        trading_mode="live",
    )

    with pytest.raises(RuntimeError, match="Replay is only available"):
        runtime.replay(_candles()[:1])
