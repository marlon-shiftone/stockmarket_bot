from datetime import datetime, timedelta, timezone
from pathlib import Path

from adapters.brokers.paper_broker import PaperBroker
from core.models.candle import Candle
from core.models.enums import SignalType
from core.models.signal import Signal
from infra.db.in_memory_store import InMemoryStore
from services.backtest_report_service import BacktestReportService
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


def _candles_for_two_days() -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        ("PETR4", base + timedelta(minutes=0), 10.0),
        ("PETR4", base + timedelta(minutes=1), 12.0),
        ("PETR4", base + timedelta(days=1, minutes=0), 11.0),
        ("PETR4", base + timedelta(days=1, minutes=1), 12.0),
    ]

    candles: list[Candle] = []
    for symbol, timestamp, close in rows:
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=timestamp,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
            )
        )
    return candles


def test_backtest_report_generates_grouped_metrics_and_equity_csv(tmp_path: Path) -> None:
    signal_engine = StubSignalEngine(
        [
            SignalType.BUY,
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

    report = BacktestReportService(runtime=runtime).run_report(
        candles=_candles_for_two_days(),
        qty=1.0,
        period="day",
        output_dir=str(tmp_path),
        initial_capital=100.0,
    )

    assert report.summary.initial_capital == 100.0
    assert report.summary.metrics.total_trades == 2
    assert len(report.grouped_metrics) == 2
    assert report.diagnostics.signal_count == 4
    assert report.diagnostics.action_signal_count == 4
    assert len(report.diagnostics.rule_pass_rates) == 8

    day1 = next(row for row in report.grouped_metrics if row.period == "2026-01-01")
    day2 = next(row for row in report.grouped_metrics if row.period == "2026-01-02")

    assert day1.total_trades == 1
    assert day1.net_profit == 2.0
    assert day1.win_rate == 100.0

    assert day2.total_trades == 1
    assert day2.net_profit == -1.0
    assert day2.win_rate == 0.0

    csv_path = Path(report.equity_curve_csv_path)
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "timestamp,equity,realized_pnl,unrealized_pnl,drawdown,drawdown_pct"
    assert lines[1].split(",")[1] == "100.0"
    assert len(lines) == 5
