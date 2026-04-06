import json
from datetime import datetime, timezone
from pathlib import Path

import services.parameter_optimizer as optimizer_module
from core.models.candle import Candle
from services.parameter_optimizer import (
    OptimizationConstraints,
    OptimizationDataset,
    ParameterOptimizer,
    ParameterSearchSpace,
    WalkForwardConfig,
)
from services.trading_runtime import BacktestMetrics, EquityPoint, ReplaySummary


class FakeRuntime:
    def __init__(self, *, nw_mult: float) -> None:
        self._nw_mult = nw_mult

    def replay(self, candles, qty=None, initial_capital=10000.0):
        distance = abs(self._nw_mult - 1.0)
        net_profit = 5.0 - distance * 4.0
        max_drawdown = 1.0 + distance
        final_equity = initial_capital + net_profit
        drawdown_pct = max_drawdown / max(initial_capital, initial_capital + net_profit) * 100.0
        return ReplaySummary(
            total_candles=len(candles),
            total_signals=len(candles),
            action_signals=12,
            filled_orders=12,
            rejected_orders=0,
            initial_capital=initial_capital,
            realized_pnl=net_profit,
            metrics=BacktestMetrics(
                total_trades=24,
                winning_trades=14,
                losing_trades=10,
                win_rate=58.3333,
                gross_profit=9.0,
                gross_loss=-3.0,
                net_profit=net_profit,
                max_drawdown=max_drawdown,
                max_drawdown_pct=drawdown_pct,
                equity_curve=[
                    EquityPoint(
                        timestamp=candles[0].timestamp,
                        equity=initial_capital,
                        realized_pnl=0.0,
                        unrealized_pnl=0.0,
                        drawdown=0.0,
                        drawdown_pct=0.0,
                    ),
                    EquityPoint(
                        timestamp=candles[-1].timestamp,
                        equity=final_equity,
                        realized_pnl=net_profit,
                        unrealized_pnl=0.0,
                        drawdown=max_drawdown,
                        drawdown_pct=drawdown_pct,
                    ),
                ],
            ),
        )


def _build_dataset_and_candles(candle_count: int = 6):
    candles = [
        Candle(
            symbol="AAPL",
            timestamp=datetime(2026, 3, 24, 10, index, tzinfo=timezone.utc),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
        )
        for index in range(candle_count)
    ]
    dataset = OptimizationDataset(
        symbol="AAPL",
        timeframe="5Min",
        csv_path="/tmp/aapl.csv",
        cache_hit=True,
        candle_count=len(candles),
        window_start=candles[0].timestamp,
        window_end=candles[-1].timestamp,
    )
    return dataset, candles


def _optimizer(tmp_path: Path, dataset: OptimizationDataset, candles: list[Candle]) -> ParameterOptimizer:
    return ParameterOptimizer(
        datasets=[dataset],
        candles_by_dataset={dataset.dataset_key: candles},
        output_dir=tmp_path,
        search_space=ParameterSearchSpace(
            nw_bandwidths=[8.0],
            nw_mults=[0.75, 1.25],
            mkr_bandwidths=[9.0],
            require_confirmation_values=[False],
            require_trend_meter_values=[False],
            require_mkr_alignment_values=[False],
            refine_top_k=1,
            nw_bandwidth_refine_step=0.0,
            nw_mult_refine_step=0.25,
            mkr_bandwidth_refine_step=0.0,
        ),
        constraints=OptimizationConstraints(
            min_trades=20,
            min_profit_factor=1.2,
            max_drawdown_pct=5.0,
            drawdown_weight=1.0,
            profit_factor_weight=0.25,
            profit_factor_cap=5.0,
        ),
        qty=1.0,
        initial_capital=100.0,
    )


def test_parameter_optimizer_runs_coarse_and_refine_search(tmp_path: Path, monkeypatch) -> None:
    def fake_build_runtime(*, nw_mult: float, **kwargs):
        return FakeRuntime(nw_mult=nw_mult)

    monkeypatch.setattr(optimizer_module, "build_runtime", fake_build_runtime)
    dataset, candles = _build_dataset_and_candles(candle_count=1)
    optimizer = _optimizer(tmp_path, dataset, candles)

    result = optimizer.run()

    assert result.coarse_candidates == 2
    assert result.refined_candidates == 2
    assert result.trials_evaluated == 4
    assert result.eligible_trials == 4
    assert result.best_eligible_trial is not None
    assert result.best_eligible_trial.nw_mult == 1.0
    assert result.best_eligible_trial.stage == "refine"
    assert Path(result.all_trials_csv_path).exists()
    assert Path(result.best_params_json_path).exists()
    assert Path(result.operational_params_json_path).exists()
    assert Path(result.summary_json_path).exists()
    operational_payload = json.loads(Path(result.operational_params_json_path).read_text(encoding="utf-8"))
    assert operational_payload["selection_source"] == "in_sample"
    assert operational_payload["datasets"][0]["selection_basis"] == "eligible"
    assert operational_payload["datasets"][0]["candidate"]["nw_mult"] == 1.0


def test_parameter_optimizer_runs_walk_forward_out_of_sample(tmp_path: Path, monkeypatch) -> None:
    def fake_build_runtime(*, nw_mult: float, **kwargs):
        return FakeRuntime(nw_mult=nw_mult)

    monkeypatch.setattr(optimizer_module, "build_runtime", fake_build_runtime)
    dataset, candles = _build_dataset_and_candles(candle_count=6)
    optimizer = _optimizer(tmp_path, dataset, candles)

    result = optimizer.run_walk_forward(
        WalkForwardConfig(
            train_size_bars=2,
            test_size_bars=2,
            step_size_bars=2,
            anchored=False,
        )
    )

    assert result.total_windows == 2
    assert result.eligible_windows == 2
    assert Path(result.trials_csv_path).exists()
    assert Path(result.operational_params_json_path).exists()
    assert Path(result.summary_json_path).exists()
    operational_payload = json.loads(Path(result.operational_params_json_path).read_text(encoding="utf-8"))
    assert operational_payload["selection_source"] == "walk_forward"
    assert operational_payload["datasets"][0]["selection_basis"] == "eligible"
    assert operational_payload["datasets"][0]["candidate"]["nw_mult"] == 1.0
    dataset_summary = result.datasets[0]
    assert dataset_summary.total_windows == 2
    assert dataset_summary.total_trades == 48
    assert dataset_summary.net_profit == 10.0
    assert dataset_summary.ending_capital == 110.0
    assert dataset_summary.equity_curve_csv_path is not None
    assert Path(dataset_summary.equity_curve_csv_path).exists()
    assert dataset_summary.candidate_summaries_csv_path is not None
    assert Path(dataset_summary.candidate_summaries_csv_path).exists()
    assert dataset_summary.best_eligible_candidate is not None
    assert dataset_summary.best_eligible_candidate.nw_mult == 1.0
    assert dataset_summary.best_eligible_candidate.net_profit == 10.0
    assert dataset_summary.best_overall_candidate is not None
    assert dataset_summary.best_overall_candidate.nw_mult == 1.0
    assert dataset_summary.windows[0].selected_train_trial is not None
    assert dataset_summary.windows[0].selected_train_trial.nw_mult == 1.0
    assert dataset_summary.windows[0].test_trial is not None
    assert dataset_summary.windows[0].test_trial.nw_mult == 1.0
