from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from core.models.candle import Candle
from core.models.signal import Signal
from core.models.trade import ClosedTrade
from services.trading_runtime import (
    DEFAULT_INITIAL_CAPITAL,
    EquityPoint,
    ReplaySummary,
    TradingRuntime,
)

DEFAULT_BUY_RULES = [
    "buy.body_below_nw_lower",
    "buy.confirm_next_body_below_nw_lower",
    "buy.mkr_green",
    "buy.trend_meter_all_green",
]

DEFAULT_SELL_RULES = [
    "sell.body_above_nw_upper",
    "sell.confirm_next_body_above_nw_upper",
    "sell.mkr_red",
    "sell.trend_meter_all_red",
]


class GroupedTradeMetrics(BaseModel):
    symbol: str
    period: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float


class RuleDiagnostic(BaseModel):
    rule: str
    passed: int
    total: int
    pass_rate: float


class BacktestDiagnostics(BaseModel):
    signal_count: int
    action_signal_count: int
    buy_all_rules_passed_count: int
    sell_all_rules_passed_count: int
    rule_pass_rates: list[RuleDiagnostic]


class BacktestReport(BaseModel):
    summary: ReplaySummary
    grouped_metrics: list[GroupedTradeMetrics]
    equity_curve_csv_path: str
    diagnostics: BacktestDiagnostics


class BacktestReportService:
    def __init__(self, runtime: TradingRuntime) -> None:
        self._runtime = runtime

    @staticmethod
    def _period_key(timestamp: datetime, period: str) -> str:
        if period == "day":
            return timestamp.date().isoformat()
        if period == "week":
            iso = timestamp.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if period == "month":
            return f"{timestamp.year}-{timestamp.month:02d}"
        raise ValueError("period must be one of: day, week, month")

    def _aggregate_grouped_metrics(
        self,
        trades: list[ClosedTrade],
        period: str,
    ) -> list[GroupedTradeMetrics]:
        grouped: dict[tuple[str, str], list[ClosedTrade]] = defaultdict(list)

        for trade in trades:
            key = (trade.symbol, self._period_key(trade.exit_timestamp, period))
            grouped[key].append(trade)

        rows: list[GroupedTradeMetrics] = []
        for (symbol, period_key), grouped_trades in sorted(grouped.items(), key=lambda item: item[0]):
            winning = sum(1 for trade in grouped_trades if trade.pnl > 0)
            losing = sum(1 for trade in grouped_trades if trade.pnl < 0)
            total = len(grouped_trades)
            gross_profit = sum(trade.pnl for trade in grouped_trades if trade.pnl > 0)
            gross_loss = sum(trade.pnl for trade in grouped_trades if trade.pnl < 0)
            net_profit = sum(trade.pnl for trade in grouped_trades)
            win_rate = (winning / total * 100.0) if total > 0 else 0.0

            rows.append(
                GroupedTradeMetrics(
                    symbol=symbol,
                    period=period_key,
                    total_trades=total,
                    winning_trades=winning,
                    losing_trades=losing,
                    win_rate=win_rate,
                    gross_profit=gross_profit,
                    gross_loss=gross_loss,
                    net_profit=net_profit,
                )
            )

        return rows

    @staticmethod
    def _reason_is_pass(reason: str) -> bool:
        text = reason.lower()
        return not (" not " in text or text.startswith("no ") or " conflict" in text)

    def _active_rule_names(self) -> tuple[list[str], list[str]]:
        strategy = getattr(self._runtime._signal_engine, "_strategy", None)
        if strategy is None:
            return DEFAULT_BUY_RULES, DEFAULT_SELL_RULES
        return strategy.buy_rule_names(), strategy.sell_rule_names()

    def _build_diagnostics(self, signals: list[Signal]) -> BacktestDiagnostics:
        buy_rules, sell_rules = self._active_rule_names()
        pass_counts: dict[str, int] = {}
        total_counts: dict[str, int] = {}
        buy_all_passed = 0
        sell_all_passed = 0

        for signal in signals:
            by_rule: dict[str, str] = {}
            for item in signal.reasons:
                if ":" not in item:
                    continue
                rule, reason = item.split(":", 1)
                by_rule[rule.strip()] = reason.strip()

            for rule in buy_rules + sell_rules:
                if rule not in by_rule:
                    continue
                total_counts[rule] = total_counts.get(rule, 0) + 1
                if self._reason_is_pass(by_rule[rule]):
                    pass_counts[rule] = pass_counts.get(rule, 0) + 1

            if buy_rules and all(rule in by_rule and self._reason_is_pass(by_rule[rule]) for rule in buy_rules):
                buy_all_passed += 1
            if sell_rules and all(rule in by_rule and self._reason_is_pass(by_rule[rule]) for rule in sell_rules):
                sell_all_passed += 1

        rule_pass_rates: list[RuleDiagnostic] = []
        for rule in buy_rules + sell_rules:
            total = total_counts.get(rule, 0)
            passed = pass_counts.get(rule, 0)
            pass_rate = (passed / total * 100.0) if total > 0 else 0.0
            rule_pass_rates.append(
                RuleDiagnostic(
                    rule=rule,
                    passed=passed,
                    total=total,
                    pass_rate=pass_rate,
                )
            )

        action_signal_count = sum(1 for signal in signals if signal.signal_type.value != "NONE")
        return BacktestDiagnostics(
            signal_count=len(signals),
            action_signal_count=action_signal_count,
            buy_all_rules_passed_count=buy_all_passed,
            sell_all_rules_passed_count=sell_all_passed,
            rule_pass_rates=rule_pass_rates,
        )

    @staticmethod
    def _write_equity_curve_csv(equity_curve: list[EquityPoint], output_dir: str) -> str:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"equity_curve_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid4().hex[:8]}.csv"
        )
        output_path = out_dir / filename

        with output_path.open("w", encoding="utf-8", newline="") as f:
            f.write("timestamp,equity,realized_pnl,unrealized_pnl,drawdown,drawdown_pct\n")
            for point in equity_curve:
                f.write(
                    f"{point.timestamp.isoformat()},{point.equity},{point.realized_pnl},"
                    f"{point.unrealized_pnl},{point.drawdown},{point.drawdown_pct}\n"
                )

        return str(output_path.resolve())

    def run_report(
        self,
        candles: list[Candle],
        qty: float | None,
        period: str,
        output_dir: str,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    ) -> BacktestReport:
        summary = self._runtime.replay(candles=candles, qty=qty, initial_capital=initial_capital)
        grouped_metrics = self._aggregate_grouped_metrics(
            trades=self._runtime.list_closed_trades(),
            period=period,
        )
        csv_path = self._write_equity_curve_csv(
            equity_curve=summary.metrics.equity_curve,
            output_dir=output_dir,
        )
        diagnostics = self._build_diagnostics(self._runtime.list_signals())

        return BacktestReport(
            summary=summary,
            grouped_metrics=grouped_metrics,
            equity_curve_csv_path=csv_path,
            diagnostics=diagnostics,
        )
