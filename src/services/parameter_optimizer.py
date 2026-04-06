import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from api.runtime import build_runtime
from core.models.candle import Candle
from services.trading_runtime import EquityPoint, ReplaySummary


class OptimizationDataset(BaseModel):
    symbol: str
    timeframe: str
    csv_path: str
    cache_hit: bool
    candle_count: int
    window_start: datetime | None = None
    window_end: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @property
    def dataset_key(self) -> str:
        return f"{self.symbol}:{self.timeframe}"


class OptimizationCandidate(BaseModel):
    nw_bandwidth: float
    nw_mult: float
    mkr_bandwidth: float
    require_confirmation: bool
    require_trend_meter: bool
    require_mkr_alignment: bool

    model_config = ConfigDict(extra="forbid")

    def key(self) -> tuple[float, float, float, bool, bool, bool]:
        return (
            round(self.nw_bandwidth, 6),
            round(self.nw_mult, 6),
            round(self.mkr_bandwidth, 6),
            self.require_confirmation,
            self.require_trend_meter,
            self.require_mkr_alignment,
        )


class ParameterSearchSpace(BaseModel):
    nw_bandwidths: list[float] = Field(default_factory=lambda: [8.0])
    nw_mults: list[float] = Field(default_factory=lambda: [3.0, 2.0, 1.5, 1.0, 0.75])
    mkr_bandwidths: list[float] = Field(default_factory=lambda: [9.0])
    require_confirmation_values: list[bool] = Field(default_factory=lambda: [True, False])
    require_trend_meter_values: list[bool] = Field(default_factory=lambda: [True, False])
    require_mkr_alignment_values: list[bool] = Field(default_factory=lambda: [True, False])
    refine_top_k: int = 3
    nw_bandwidth_refine_step: float = 1.0
    nw_mult_refine_step: float = 0.25
    mkr_bandwidth_refine_step: float = 1.0

    model_config = ConfigDict(extra="forbid")

    def coarse_candidates(self) -> list[OptimizationCandidate]:
        return _dedupe_candidates(
            OptimizationCandidate(
                nw_bandwidth=nw_bandwidth,
                nw_mult=nw_mult,
                mkr_bandwidth=mkr_bandwidth,
                require_confirmation=require_confirmation,
                require_trend_meter=require_trend_meter,
                require_mkr_alignment=require_mkr_alignment,
            )
            for (
                nw_bandwidth,
                nw_mult,
                mkr_bandwidth,
                require_confirmation,
                require_trend_meter,
                require_mkr_alignment,
            ) in product(
                self.nw_bandwidths,
                self.nw_mults,
                self.mkr_bandwidths,
                self.require_confirmation_values,
                self.require_trend_meter_values,
                self.require_mkr_alignment_values,
            )
        )

    def refine_candidates(
        self,
        top_trials: list["OptimizationTrial"],
        existing_keys: set[tuple[float, float, float, bool, bool, bool]],
    ) -> list[OptimizationCandidate]:
        if self.refine_top_k <= 0:
            return []

        candidates: list[OptimizationCandidate] = []
        for trial in top_trials[: self.refine_top_k]:
            base = trial.to_candidate()
            for nw_bandwidth in _refined_values(base.nw_bandwidth, self.nw_bandwidth_refine_step):
                for nw_mult in _refined_values(base.nw_mult, self.nw_mult_refine_step):
                    for mkr_bandwidth in _refined_values(base.mkr_bandwidth, self.mkr_bandwidth_refine_step):
                        candidate = OptimizationCandidate(
                            nw_bandwidth=nw_bandwidth,
                            nw_mult=nw_mult,
                            mkr_bandwidth=mkr_bandwidth,
                            require_confirmation=base.require_confirmation,
                            require_trend_meter=base.require_trend_meter,
                            require_mkr_alignment=base.require_mkr_alignment,
                        )
                        if candidate.key() in existing_keys:
                            continue
                        candidates.append(candidate)
                        existing_keys.add(candidate.key())
        return _dedupe_candidates(candidates)


class OptimizationConstraints(BaseModel):
    min_trades: int = 20
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 5.0
    drawdown_weight: float = 1.0
    profit_factor_weight: float = 0.25
    profit_factor_cap: float = 5.0

    model_config = ConfigDict(extra="forbid")


class OptimizationTrial(BaseModel):
    stage: str
    symbol: str
    timeframe: str
    nw_bandwidth: float
    nw_mult: float
    mkr_bandwidth: float
    require_confirmation: bool
    require_trend_meter: bool
    require_mkr_alignment: bool
    total_candles: int
    action_signals: int
    filled_orders: int
    rejected_orders: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    net_profit: float
    max_drawdown: float
    max_drawdown_pct: float
    score: float
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def to_candidate(self) -> OptimizationCandidate:
        return OptimizationCandidate(
            nw_bandwidth=self.nw_bandwidth,
            nw_mult=self.nw_mult,
            mkr_bandwidth=self.mkr_bandwidth,
            require_confirmation=self.require_confirmation,
            require_trend_meter=self.require_trend_meter,
            require_mkr_alignment=self.require_mkr_alignment,
        )


class DatasetBestTrial(BaseModel):
    symbol: str
    timeframe: str
    best_eligible_trial: OptimizationTrial | None = None
    best_overall_trial: OptimizationTrial | None = None

    model_config = ConfigDict(extra="forbid")


class OptimizationRunResult(BaseModel):
    run_id: str
    generated_at: datetime
    initial_capital: float
    qty: float | None
    constraints: OptimizationConstraints
    search_space: ParameterSearchSpace
    datasets: list[OptimizationDataset]
    coarse_candidates: int
    refined_candidates: int
    trials_evaluated: int
    eligible_trials: int
    all_trials_csv_path: str
    best_params_json_path: str
    operational_params_json_path: str
    summary_json_path: str
    best_eligible_trial: OptimizationTrial | None = None
    best_overall_trial: OptimizationTrial | None = None
    best_by_dataset: list[DatasetBestTrial] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WalkForwardConfig(BaseModel):
    train_size_bars: int | None = None
    test_size_bars: int | None = None
    step_size_bars: int | None = None
    anchored: bool = False

    model_config = ConfigDict(extra="forbid")


class WalkForwardWindow(BaseModel):
    index: int
    symbol: str
    timeframe: str
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_candles: int
    test_candles: int

    model_config = ConfigDict(extra="forbid")


class WalkForwardWindowResult(BaseModel):
    window: WalkForwardWindow
    selection_basis: str
    train_trials_evaluated: int
    refined_candidates: int
    selected_train_trial: OptimizationTrial | None = None
    test_trial: OptimizationTrial | None = None

    model_config = ConfigDict(extra="forbid")


class WalkForwardCandidateSummary(BaseModel):
    symbol: str
    timeframe: str
    nw_bandwidth: float
    nw_mult: float
    mkr_bandwidth: float
    require_confirmation: bool
    require_trend_meter: bool
    require_mkr_alignment: bool
    windows_evaluated: int
    eligible_windows: int
    starting_capital: float
    ending_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    net_profit: float
    max_drawdown: float
    max_drawdown_pct: float
    score: float
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WalkForwardDatasetSummary(BaseModel):
    symbol: str
    timeframe: str
    total_windows: int
    eligible_windows: int
    train_size_bars: int
    test_size_bars: int
    step_size_bars: int
    anchored: bool
    starting_capital: float
    ending_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    net_profit: float
    max_drawdown: float
    max_drawdown_pct: float
    equity_curve_csv_path: str | None = None
    candidate_summaries_csv_path: str | None = None
    best_eligible_candidate: WalkForwardCandidateSummary | None = None
    best_overall_candidate: WalkForwardCandidateSummary | None = None
    windows: list[WalkForwardWindowResult] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WalkForwardRunResult(BaseModel):
    generated_at: datetime
    config: WalkForwardConfig
    datasets: list[WalkForwardDatasetSummary]
    total_windows: int
    total_test_trials: int
    eligible_windows: int
    trials_csv_path: str
    operational_params_json_path: str
    summary_json_path: str

    model_config = ConfigDict(extra="forbid")


@dataclass
class _CandidateEvaluation:
    trial: OptimizationTrial
    summary: ReplaySummary


@dataclass
class _WalkForwardSlices:
    window: WalkForwardWindow
    train_candles: list[Candle]
    test_candles: list[Candle]


class ParameterOptimizer:
    def __init__(
        self,
        *,
        datasets: list[OptimizationDataset],
        candles_by_dataset: dict[str, list[Candle]],
        output_dir: str | Path,
        search_space: ParameterSearchSpace,
        constraints: OptimizationConstraints,
        qty: float | None = None,
        initial_capital: float = 10000.0,
    ) -> None:
        self._datasets = datasets
        self._candles_by_dataset = candles_by_dataset
        self._output_dir = Path(output_dir)
        self._search_space = search_space
        self._constraints = constraints
        self._qty = qty
        self._initial_capital = initial_capital

    def run(self) -> OptimizationRunResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)

        coarse_candidates = self._search_space.coarse_candidates()
        trials = self._evaluate_candidates(coarse_candidates, stage="coarse")

        existing_keys = {trial.to_candidate().key() for trial in trials}
        ranked_trials = sorted(trials, key=self._trial_sort_key, reverse=True)
        refined_candidates = self._search_space.refine_candidates(ranked_trials, existing_keys)
        if refined_candidates:
            trials.extend(self._evaluate_candidates(refined_candidates, stage="refine"))

        best_eligible_trial = next(
            (trial for trial in sorted(trials, key=self._trial_sort_key, reverse=True) if trial.eligible),
            None,
        )
        best_overall_trial = max(trials, key=self._trial_sort_key, default=None)

        dataset_bests = self._dataset_bests(trials)
        all_trials_csv_path = self._write_trials_csv(trials)
        best_params_json_path = self._write_best_params_json(best_eligible_trial, best_overall_trial)
        operational_params_json_path = self._write_operational_params_json(
            selection_source="in_sample",
            dataset_entries=[self._operational_entry_from_dataset_best(item) for item in dataset_bests],
        )
        summary_json_path = self._output_dir / "summary.json"

        result = OptimizationRunResult(
            run_id=self._output_dir.name,
            generated_at=datetime.now(timezone.utc),
            initial_capital=self._initial_capital,
            qty=self._qty,
            constraints=self._constraints,
            search_space=self._search_space,
            datasets=self._datasets,
            coarse_candidates=len(coarse_candidates),
            refined_candidates=len(refined_candidates),
            trials_evaluated=len(trials),
            eligible_trials=sum(1 for trial in trials if trial.eligible),
            all_trials_csv_path=str(all_trials_csv_path.resolve()),
            best_params_json_path=str(best_params_json_path.resolve()),
            operational_params_json_path=str(operational_params_json_path.resolve()),
            summary_json_path=str(summary_json_path.resolve()),
            best_eligible_trial=best_eligible_trial,
            best_overall_trial=best_overall_trial,
            best_by_dataset=dataset_bests,
        )
        summary_json_path.write_text(json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8")
        return result

    def run_walk_forward(self, config: WalkForwardConfig) -> WalkForwardRunResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)

        dataset_summaries: list[WalkForwardDatasetSummary] = []
        trial_rows: list[dict[str, object]] = []

        for dataset in self._datasets:
            dataset_summary, dataset_rows = self._run_walk_forward_for_dataset(dataset=dataset, config=config)
            dataset_summaries.append(dataset_summary)
            trial_rows.extend(dataset_rows)

        trials_csv_path = self._write_walk_forward_trials_csv(trial_rows)
        operational_params_json_path = self._write_operational_params_json(
            selection_source="walk_forward",
            dataset_entries=[self._operational_entry_from_walk_forward_summary(item) for item in dataset_summaries],
            metadata={"walk_forward_config": config.model_dump(mode="json")},
        )
        summary_json_path = self._output_dir / "walk_forward_summary.json"
        result = WalkForwardRunResult(
            generated_at=datetime.now(timezone.utc),
            config=config,
            datasets=dataset_summaries,
            total_windows=sum(summary.total_windows for summary in dataset_summaries),
            total_test_trials=sum(len(summary.windows) for summary in dataset_summaries),
            eligible_windows=sum(summary.eligible_windows for summary in dataset_summaries),
            trials_csv_path=str(trials_csv_path.resolve()),
            operational_params_json_path=str(operational_params_json_path.resolve()),
            summary_json_path=str(summary_json_path.resolve()),
        )
        summary_json_path.write_text(json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8")
        return result

    def _run_walk_forward_for_dataset(
        self,
        *,
        dataset: OptimizationDataset,
        config: WalkForwardConfig,
    ) -> tuple[WalkForwardDatasetSummary, list[dict[str, object]]]:
        candles = self._candles_by_dataset[dataset.dataset_key]
        window_slices, train_size, test_size, step_size = self._build_walk_forward_windows(
            dataset=dataset,
            candles=candles,
            config=config,
        )

        current_capital = self._initial_capital
        peak_equity = current_capital
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        gross_profit = 0.0
        gross_loss = 0.0
        net_profit = 0.0
        combined_equity_curve: list[EquityPoint] = []
        window_results: list[WalkForwardWindowResult] = []
        trial_rows: list[dict[str, object]] = []
        candidate_pool: dict[tuple[float, float, float, bool, bool, bool], OptimizationCandidate] = {}

        for slices in window_slices:
            train_trials = self._evaluate_candidates_for_dataset(
                dataset=dataset,
                candles=slices.train_candles,
                candidates=self._search_space.coarse_candidates(),
                stage=f"walk_forward_train_{slices.window.index}",
                initial_capital=self._initial_capital,
            )
            existing_keys = {trial.to_candidate().key() for trial in train_trials}
            ranked_trials = sorted(train_trials, key=self._trial_sort_key, reverse=True)
            refined_candidates = self._search_space.refine_candidates(ranked_trials, existing_keys)
            if refined_candidates:
                train_trials.extend(
                    self._evaluate_candidates_for_dataset(
                        dataset=dataset,
                        candles=slices.train_candles,
                        candidates=refined_candidates,
                        stage=f"walk_forward_train_refine_{slices.window.index}",
                        initial_capital=self._initial_capital,
                    )
                )
                ranked_trials = sorted(train_trials, key=self._trial_sort_key, reverse=True)

            for trial in train_trials:
                candidate = trial.to_candidate()
                candidate_pool[candidate.key()] = candidate

            selected_train_trial, selection_basis = self._select_trial(ranked_trials)
            test_trial: OptimizationTrial | None = None
            if selected_train_trial is not None:
                test_evaluation = self._evaluate_candidate(
                    dataset=dataset,
                    candles=slices.test_candles,
                    candidate=selected_train_trial.to_candidate(),
                    stage=f"walk_forward_test_{slices.window.index}",
                    initial_capital=current_capital,
                )
                test_trial = test_evaluation.trial
                current_capital += test_evaluation.summary.metrics.net_profit
                total_trades += test_trial.total_trades
                winning_trades += test_trial.winning_trades
                losing_trades += test_trial.losing_trades
                gross_profit += test_trial.gross_profit
                gross_loss += test_trial.gross_loss
                net_profit += test_trial.net_profit
                for point in test_evaluation.summary.metrics.equity_curve:
                    combined_equity_curve.append(point)
                    peak_equity = max(peak_equity, point.equity)
                    drawdown = peak_equity - point.equity
                    drawdown_pct = (drawdown / peak_equity * 100.0) if peak_equity > 0 else 0.0
                    max_drawdown = max(max_drawdown, drawdown)
                    max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

            result = WalkForwardWindowResult(
                window=slices.window,
                selection_basis=selection_basis,
                train_trials_evaluated=len(train_trials),
                refined_candidates=len(refined_candidates),
                selected_train_trial=selected_train_trial,
                test_trial=test_trial,
            )
            window_results.append(result)
            trial_rows.append(self._walk_forward_row(result))

        equity_curve_csv_path = None
        if combined_equity_curve:
            equity_curve_csv_path = str(
                self._write_equity_curve_csv(
                    equity_curve=combined_equity_curve,
                    filename=f"walk_forward_{dataset.symbol}_{dataset.timeframe}_equity_curve.csv",
                ).resolve()
            )

        candidate_summaries = self._evaluate_walk_forward_candidate_pool(
            dataset=dataset,
            window_slices=window_slices,
            candidates=sorted(candidate_pool.values(), key=lambda item: item.key()),
        )
        best_eligible_candidate = next(
            (candidate for candidate in candidate_summaries if candidate.eligible),
            None,
        )
        best_overall_candidate = candidate_summaries[0] if candidate_summaries else None
        candidate_summaries_csv_path = None
        if candidate_summaries:
            candidate_summaries_csv_path = str(
                self._write_walk_forward_candidate_csv(
                    dataset=dataset,
                    candidate_summaries=candidate_summaries,
                ).resolve()
            )

        profit_factor = _profit_factor(gross_profit, gross_loss)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        summary = WalkForwardDatasetSummary(
            symbol=dataset.symbol,
            timeframe=dataset.timeframe,
            total_windows=len(window_results),
            eligible_windows=sum(1 for row in window_results if row.selection_basis == "eligible"),
            train_size_bars=train_size,
            test_size_bars=test_size,
            step_size_bars=step_size,
            anchored=config.anchored,
            starting_capital=self._initial_capital,
            ending_capital=current_capital,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=profit_factor,
            net_profit=net_profit,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            equity_curve_csv_path=equity_curve_csv_path,
            candidate_summaries_csv_path=candidate_summaries_csv_path,
            best_eligible_candidate=best_eligible_candidate,
            best_overall_candidate=best_overall_candidate,
            windows=window_results,
        )
        return summary, trial_rows

    def _evaluate_candidates(
        self,
        candidates: list[OptimizationCandidate],
        *,
        stage: str,
    ) -> list[OptimizationTrial]:
        trials: list[OptimizationTrial] = []
        for dataset in self._datasets:
            candles = self._candles_by_dataset[dataset.dataset_key]
            trials.extend(
                self._evaluate_candidates_for_dataset(
                    dataset=dataset,
                    candles=candles,
                    candidates=candidates,
                    stage=stage,
                    initial_capital=self._initial_capital,
                )
            )
        return trials

    def _evaluate_candidates_for_dataset(
        self,
        *,
        dataset: OptimizationDataset,
        candles: list[Candle],
        candidates: list[OptimizationCandidate],
        stage: str,
        initial_capital: float,
    ) -> list[OptimizationTrial]:
        return [
            self._evaluate_candidate(
                dataset=dataset,
                candles=candles,
                candidate=candidate,
                stage=stage,
                initial_capital=initial_capital,
            ).trial
            for candidate in candidates
        ]

    def _evaluate_candidate(
        self,
        *,
        dataset: OptimizationDataset,
        candles: list[Candle],
        candidate: OptimizationCandidate,
        stage: str,
        initial_capital: float,
    ) -> _CandidateEvaluation:
        runtime = build_runtime(
            force_local_paper=True,
            nw_bandwidth=candidate.nw_bandwidth,
            nw_mult=candidate.nw_mult,
            mkr_bandwidth=candidate.mkr_bandwidth,
            require_confirmation=candidate.require_confirmation,
            require_trend_meter=candidate.require_trend_meter,
            require_mkr_alignment=candidate.require_mkr_alignment,
        )
        summary = runtime.replay(
            candles=candles,
            qty=self._qty,
            initial_capital=initial_capital,
        )
        metrics = summary.metrics
        profit_factor = _profit_factor(metrics.gross_profit, metrics.gross_loss)
        profit_factor_for_score = (
            self._constraints.profit_factor_cap
            if profit_factor is None and metrics.gross_profit > 0
            else min(profit_factor or 0.0, self._constraints.profit_factor_cap)
        )
        score = (
            metrics.net_profit
            - self._constraints.drawdown_weight * metrics.max_drawdown
            + self._constraints.profit_factor_weight * profit_factor_for_score
        )
        rejection_reasons = _rejection_reasons(
            total_trades=metrics.total_trades,
            gross_profit=metrics.gross_profit,
            profit_factor=profit_factor,
            max_drawdown_pct=metrics.max_drawdown_pct,
            constraints=self._constraints,
        )
        trial = OptimizationTrial(
            stage=stage,
            symbol=dataset.symbol,
            timeframe=dataset.timeframe,
            nw_bandwidth=candidate.nw_bandwidth,
            nw_mult=candidate.nw_mult,
            mkr_bandwidth=candidate.mkr_bandwidth,
            require_confirmation=candidate.require_confirmation,
            require_trend_meter=candidate.require_trend_meter,
            require_mkr_alignment=candidate.require_mkr_alignment,
            total_candles=summary.total_candles,
            action_signals=summary.action_signals,
            filled_orders=summary.filled_orders,
            rejected_orders=summary.rejected_orders,
            total_trades=metrics.total_trades,
            winning_trades=metrics.winning_trades,
            losing_trades=metrics.losing_trades,
            win_rate=metrics.win_rate,
            gross_profit=metrics.gross_profit,
            gross_loss=metrics.gross_loss,
            profit_factor=profit_factor,
            net_profit=metrics.net_profit,
            max_drawdown=metrics.max_drawdown,
            max_drawdown_pct=metrics.max_drawdown_pct,
            score=score,
            eligible=not rejection_reasons,
            rejection_reasons=rejection_reasons,
        )
        return _CandidateEvaluation(trial=trial, summary=summary)

    def _build_walk_forward_windows(
        self,
        *,
        dataset: OptimizationDataset,
        candles: list[Candle],
        config: WalkForwardConfig,
    ) -> tuple[list[_WalkForwardSlices], int, int, int]:
        total_bars = len(candles)
        train_size = config.train_size_bars or max(int(total_bars * 0.6), 1)
        test_size = config.test_size_bars or max(int(total_bars * 0.2), 1)
        step_size = config.step_size_bars or test_size

        if train_size <= 0 or test_size <= 0 or step_size <= 0:
            raise ValueError("Walk-forward window sizes must be greater than 0.")

        windows: list[_WalkForwardSlices] = []
        offset = 0
        index = 1
        while True:
            train_start = 0 if config.anchored else offset
            train_end = train_size + offset if config.anchored else train_start + train_size
            test_start = train_end
            test_end = test_start + test_size
            if test_end > total_bars:
                break

            train_candles = candles[train_start:train_end]
            test_candles = candles[test_start:test_end]
            if not train_candles or not test_candles:
                break

            windows.append(
                _WalkForwardSlices(
                    window=WalkForwardWindow(
                        index=index,
                        symbol=dataset.symbol,
                        timeframe=dataset.timeframe,
                        train_start=train_candles[0].timestamp,
                        train_end=train_candles[-1].timestamp,
                        test_start=test_candles[0].timestamp,
                        test_end=test_candles[-1].timestamp,
                        train_candles=len(train_candles),
                        test_candles=len(test_candles),
                    ),
                    train_candles=train_candles,
                    test_candles=test_candles,
                )
            )
            offset += step_size
            index += 1

        return windows, train_size, test_size, step_size

    @staticmethod
    def _select_trial(ranked_trials: list[OptimizationTrial]) -> tuple[OptimizationTrial | None, str]:
        selected = next((trial for trial in ranked_trials if trial.eligible), None)
        if selected is not None:
            return selected, "eligible"
        if ranked_trials:
            return ranked_trials[0], "overall_fallback"
        return None, "none"

    def _evaluate_walk_forward_candidate_pool(
        self,
        *,
        dataset: OptimizationDataset,
        window_slices: list[_WalkForwardSlices],
        candidates: list[OptimizationCandidate],
    ) -> list[WalkForwardCandidateSummary]:
        summaries: list[WalkForwardCandidateSummary] = []
        for candidate in candidates:
            current_capital = self._initial_capital
            peak_equity = current_capital
            max_drawdown = 0.0
            max_drawdown_pct = 0.0
            total_trades = 0
            winning_trades = 0
            losing_trades = 0
            gross_profit = 0.0
            gross_loss = 0.0
            net_profit = 0.0
            eligible_windows = 0

            for slices in window_slices:
                evaluation = self._evaluate_candidate(
                    dataset=dataset,
                    candles=slices.test_candles,
                    candidate=candidate,
                    stage=f"walk_forward_candidate_test_{slices.window.index}",
                    initial_capital=current_capital,
                )
                trial = evaluation.trial
                if trial.eligible:
                    eligible_windows += 1
                current_capital += evaluation.summary.metrics.net_profit
                total_trades += trial.total_trades
                winning_trades += trial.winning_trades
                losing_trades += trial.losing_trades
                gross_profit += trial.gross_profit
                gross_loss += trial.gross_loss
                net_profit += trial.net_profit
                for point in evaluation.summary.metrics.equity_curve:
                    peak_equity = max(peak_equity, point.equity)
                    drawdown = peak_equity - point.equity
                    drawdown_pct = (drawdown / peak_equity * 100.0) if peak_equity > 0 else 0.0
                    max_drawdown = max(max_drawdown, drawdown)
                    max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

            profit_factor = _profit_factor(gross_profit, gross_loss)
            profit_factor_for_score = (
                self._constraints.profit_factor_cap
                if profit_factor is None and gross_profit > 0
                else min(profit_factor or 0.0, self._constraints.profit_factor_cap)
            )
            score = (
                net_profit
                - self._constraints.drawdown_weight * max_drawdown
                + self._constraints.profit_factor_weight * profit_factor_for_score
            )
            rejection_reasons = _rejection_reasons(
                total_trades=total_trades,
                gross_profit=gross_profit,
                profit_factor=profit_factor,
                max_drawdown_pct=max_drawdown_pct,
                constraints=self._constraints,
            )
            win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
            summaries.append(
                WalkForwardCandidateSummary(
                    symbol=dataset.symbol,
                    timeframe=dataset.timeframe,
                    nw_bandwidth=candidate.nw_bandwidth,
                    nw_mult=candidate.nw_mult,
                    mkr_bandwidth=candidate.mkr_bandwidth,
                    require_confirmation=candidate.require_confirmation,
                    require_trend_meter=candidate.require_trend_meter,
                    require_mkr_alignment=candidate.require_mkr_alignment,
                    windows_evaluated=len(window_slices),
                    eligible_windows=eligible_windows,
                    starting_capital=self._initial_capital,
                    ending_capital=current_capital,
                    total_trades=total_trades,
                    winning_trades=winning_trades,
                    losing_trades=losing_trades,
                    win_rate=win_rate,
                    gross_profit=gross_profit,
                    gross_loss=gross_loss,
                    profit_factor=profit_factor,
                    net_profit=net_profit,
                    max_drawdown=max_drawdown,
                    max_drawdown_pct=max_drawdown_pct,
                    score=score,
                    eligible=not rejection_reasons,
                    rejection_reasons=rejection_reasons,
                )
            )

        return sorted(summaries, key=self._walk_forward_candidate_sort_key, reverse=True)

    def _walk_forward_candidate_sort_key(
        self,
        summary: WalkForwardCandidateSummary,
    ) -> tuple[bool, float, float, float, int, int]:
        profit_factor = summary.profit_factor
        if profit_factor is None and summary.gross_profit > 0:
            profit_factor = self._constraints.profit_factor_cap
        return (
            summary.eligible,
            summary.score,
            summary.net_profit,
            profit_factor or 0.0,
            summary.eligible_windows,
            summary.total_trades,
        )

    def _dataset_bests(self, trials: list[OptimizationTrial]) -> list[DatasetBestTrial]:
        bests: list[DatasetBestTrial] = []
        for dataset in self._datasets:
            dataset_trials = [
                trial
                for trial in trials
                if trial.symbol == dataset.symbol and trial.timeframe == dataset.timeframe
            ]
            ranked = sorted(dataset_trials, key=self._trial_sort_key, reverse=True)
            best_eligible = next((trial for trial in ranked if trial.eligible), None)
            best_overall = ranked[0] if ranked else None
            bests.append(
                DatasetBestTrial(
                    symbol=dataset.symbol,
                    timeframe=dataset.timeframe,
                    best_eligible_trial=best_eligible,
                    best_overall_trial=best_overall,
                )
            )
        return bests

    @staticmethod
    def _select_dataset_trial(dataset_best: DatasetBestTrial) -> tuple[OptimizationTrial | None, str]:
        if dataset_best.best_eligible_trial is not None:
            return dataset_best.best_eligible_trial, "eligible"
        if dataset_best.best_overall_trial is not None:
            return dataset_best.best_overall_trial, "overall_fallback"
        return None, "none"

    @staticmethod
    def _select_walk_forward_candidate(
        dataset_summary: WalkForwardDatasetSummary,
    ) -> tuple[WalkForwardCandidateSummary | None, str]:
        if dataset_summary.best_eligible_candidate is not None:
            return dataset_summary.best_eligible_candidate, "eligible"
        if dataset_summary.best_overall_candidate is not None:
            return dataset_summary.best_overall_candidate, "overall_fallback"
        return None, "none"

    def _operational_entry_from_dataset_best(self, dataset_best: DatasetBestTrial) -> dict[str, object]:
        selected, selection_basis = self._select_dataset_trial(dataset_best)
        payload: dict[str, object] = {
            "symbol": dataset_best.symbol,
            "timeframe": dataset_best.timeframe,
            "selection_basis": selection_basis,
            "candidate": None,
            "metrics": None,
        }
        if selected is None:
            return payload

        payload["candidate"] = {
            "nw_bandwidth": selected.nw_bandwidth,
            "nw_mult": selected.nw_mult,
            "mkr_bandwidth": selected.mkr_bandwidth,
            "require_confirmation": selected.require_confirmation,
            "require_trend_meter": selected.require_trend_meter,
            "require_mkr_alignment": selected.require_mkr_alignment,
        }
        payload["metrics"] = {
            "stage": selected.stage,
            "total_candles": selected.total_candles,
            "action_signals": selected.action_signals,
            "filled_orders": selected.filled_orders,
            "rejected_orders": selected.rejected_orders,
            "total_trades": selected.total_trades,
            "winning_trades": selected.winning_trades,
            "losing_trades": selected.losing_trades,
            "win_rate": selected.win_rate,
            "gross_profit": selected.gross_profit,
            "gross_loss": selected.gross_loss,
            "profit_factor": selected.profit_factor,
            "net_profit": selected.net_profit,
            "max_drawdown": selected.max_drawdown,
            "max_drawdown_pct": selected.max_drawdown_pct,
            "score": selected.score,
            "eligible": selected.eligible,
            "rejection_reasons": selected.rejection_reasons,
        }
        return payload

    def _operational_entry_from_walk_forward_summary(
        self,
        dataset_summary: WalkForwardDatasetSummary,
    ) -> dict[str, object]:
        selected, selection_basis = self._select_walk_forward_candidate(dataset_summary)
        payload: dict[str, object] = {
            "symbol": dataset_summary.symbol,
            "timeframe": dataset_summary.timeframe,
            "selection_basis": selection_basis,
            "candidate": None,
            "metrics": None,
        }
        if selected is None:
            return payload

        payload["candidate"] = {
            "nw_bandwidth": selected.nw_bandwidth,
            "nw_mult": selected.nw_mult,
            "mkr_bandwidth": selected.mkr_bandwidth,
            "require_confirmation": selected.require_confirmation,
            "require_trend_meter": selected.require_trend_meter,
            "require_mkr_alignment": selected.require_mkr_alignment,
        }
        payload["metrics"] = {
            "windows_evaluated": selected.windows_evaluated,
            "eligible_windows": selected.eligible_windows,
            "starting_capital": selected.starting_capital,
            "ending_capital": selected.ending_capital,
            "total_trades": selected.total_trades,
            "winning_trades": selected.winning_trades,
            "losing_trades": selected.losing_trades,
            "win_rate": selected.win_rate,
            "gross_profit": selected.gross_profit,
            "gross_loss": selected.gross_loss,
            "profit_factor": selected.profit_factor,
            "net_profit": selected.net_profit,
            "max_drawdown": selected.max_drawdown,
            "max_drawdown_pct": selected.max_drawdown_pct,
            "score": selected.score,
            "eligible": selected.eligible,
            "rejection_reasons": selected.rejection_reasons,
        }
        return payload

    def _write_operational_params_json(
        self,
        *,
        selection_source: str,
        dataset_entries: list[dict[str, object]],
        metadata: dict[str, object] | None = None,
    ) -> Path:
        output_path = self._output_dir / "operational_params.json"
        payload: dict[str, object] = {
            "selection_source": selection_source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "initial_capital": self._initial_capital,
            "qty": self._qty,
            "constraints": self._constraints.model_dump(mode="json"),
            "datasets": dataset_entries,
        }
        if metadata:
            payload["metadata"] = metadata
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output_path

    def _write_trials_csv(self, trials: list[OptimizationTrial]) -> Path:
        output_path = self._output_dir / "all_trials.csv"
        fieldnames = [
            "stage",
            "symbol",
            "timeframe",
            "nw_bandwidth",
            "nw_mult",
            "mkr_bandwidth",
            "require_confirmation",
            "require_trend_meter",
            "require_mkr_alignment",
            "total_candles",
            "action_signals",
            "filled_orders",
            "rejected_orders",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "win_rate",
            "gross_profit",
            "gross_loss",
            "profit_factor",
            "net_profit",
            "max_drawdown",
            "max_drawdown_pct",
            "score",
            "eligible",
            "rejection_reasons",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for trial in trials:
                row = trial.model_dump(mode="json")
                row["rejection_reasons"] = " | ".join(row["rejection_reasons"])
                writer.writerow(row)
        return output_path

    def _write_best_params_json(
        self,
        best_eligible_trial: OptimizationTrial | None,
        best_overall_trial: OptimizationTrial | None,
    ) -> Path:
        output_path = self._output_dir / "best_params.json"
        selected = best_eligible_trial or best_overall_trial
        selection_basis = "eligible" if best_eligible_trial is not None else "overall_fallback"
        payload = {
            "selection_basis": selection_basis if selected is not None else "none",
            "constraints": self._constraints.model_dump(mode="json"),
            "trial": selected.model_dump(mode="json") if selected is not None else None,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output_path

    def _write_walk_forward_candidate_csv(
        self,
        *,
        dataset: OptimizationDataset,
        candidate_summaries: list[WalkForwardCandidateSummary],
    ) -> Path:
        safe_symbol = dataset.symbol.replace("/", "_")
        output_path = self._output_dir / f"walk_forward_candidates_{safe_symbol}_{dataset.timeframe}.csv"
        fieldnames = [
            "symbol",
            "timeframe",
            "nw_bandwidth",
            "nw_mult",
            "mkr_bandwidth",
            "require_confirmation",
            "require_trend_meter",
            "require_mkr_alignment",
            "windows_evaluated",
            "eligible_windows",
            "starting_capital",
            "ending_capital",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "win_rate",
            "gross_profit",
            "gross_loss",
            "profit_factor",
            "net_profit",
            "max_drawdown",
            "max_drawdown_pct",
            "score",
            "eligible",
            "rejection_reasons",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for summary in candidate_summaries:
                row = summary.model_dump(mode="json")
                row["rejection_reasons"] = " | ".join(row["rejection_reasons"])
                writer.writerow(row)
        return output_path

    def _write_walk_forward_trials_csv(self, rows: list[dict[str, object]]) -> Path:
        output_path = self._output_dir / "walk_forward_trials.csv"
        fieldnames = [
            "symbol",
            "timeframe",
            "window_index",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "train_candles",
            "test_candles",
            "selection_basis",
            "train_trials_evaluated",
            "refined_candidates",
            "selected_nw_bandwidth",
            "selected_nw_mult",
            "selected_mkr_bandwidth",
            "selected_require_confirmation",
            "selected_require_trend_meter",
            "selected_require_mkr_alignment",
            "train_score",
            "train_net_profit",
            "train_total_trades",
            "train_profit_factor",
            "test_score",
            "test_net_profit",
            "test_total_trades",
            "test_win_rate",
            "test_profit_factor",
            "test_max_drawdown",
            "test_max_drawdown_pct",
            "test_eligible",
            "test_rejection_reasons",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return output_path

    def _write_equity_curve_csv(self, *, equity_curve: list[EquityPoint], filename: str) -> Path:
        output_path = self._output_dir / filename
        with output_path.open("w", encoding="utf-8", newline="") as f:
            f.write("timestamp,equity,realized_pnl,unrealized_pnl,drawdown,drawdown_pct\n")
            for point in equity_curve:
                f.write(
                    f"{point.timestamp.isoformat()},{point.equity},{point.realized_pnl},"
                    f"{point.unrealized_pnl},{point.drawdown},{point.drawdown_pct}\n"
                )
        return output_path

    def _walk_forward_row(self, result: WalkForwardWindowResult) -> dict[str, object]:
        train = result.selected_train_trial
        test = result.test_trial
        return {
            "symbol": result.window.symbol,
            "timeframe": result.window.timeframe,
            "window_index": result.window.index,
            "train_start": result.window.train_start.isoformat(),
            "train_end": result.window.train_end.isoformat(),
            "test_start": result.window.test_start.isoformat(),
            "test_end": result.window.test_end.isoformat(),
            "train_candles": result.window.train_candles,
            "test_candles": result.window.test_candles,
            "selection_basis": result.selection_basis,
            "train_trials_evaluated": result.train_trials_evaluated,
            "refined_candidates": result.refined_candidates,
            "selected_nw_bandwidth": train.nw_bandwidth if train else None,
            "selected_nw_mult": train.nw_mult if train else None,
            "selected_mkr_bandwidth": train.mkr_bandwidth if train else None,
            "selected_require_confirmation": train.require_confirmation if train else None,
            "selected_require_trend_meter": train.require_trend_meter if train else None,
            "selected_require_mkr_alignment": train.require_mkr_alignment if train else None,
            "train_score": train.score if train else None,
            "train_net_profit": train.net_profit if train else None,
            "train_total_trades": train.total_trades if train else None,
            "train_profit_factor": train.profit_factor if train else None,
            "test_score": test.score if test else None,
            "test_net_profit": test.net_profit if test else None,
            "test_total_trades": test.total_trades if test else None,
            "test_win_rate": test.win_rate if test else None,
            "test_profit_factor": test.profit_factor if test else None,
            "test_max_drawdown": test.max_drawdown if test else None,
            "test_max_drawdown_pct": test.max_drawdown_pct if test else None,
            "test_eligible": test.eligible if test else None,
            "test_rejection_reasons": " | ".join(test.rejection_reasons) if test else "",
        }

    def _trial_sort_key(self, trial: OptimizationTrial) -> tuple[bool, float, float, float, int]:
        profit_factor = trial.profit_factor
        if profit_factor is None and trial.gross_profit > 0:
            profit_factor = self._constraints.profit_factor_cap
        return (
            trial.eligible,
            trial.score,
            trial.net_profit,
            profit_factor or 0.0,
            trial.total_trades,
        )


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    gross_loss_abs = abs(gross_loss)
    if gross_loss_abs == 0:
        return None if gross_profit > 0 else 0.0
    return gross_profit / gross_loss_abs


def _rejection_reasons(
    *,
    total_trades: int,
    gross_profit: float,
    profit_factor: float | None,
    max_drawdown_pct: float,
    constraints: OptimizationConstraints,
) -> list[str]:
    reasons: list[str] = []
    if total_trades < constraints.min_trades:
        reasons.append(f"total_trades<{constraints.min_trades}")

    profit_factor_ok = False
    if profit_factor is None:
        profit_factor_ok = gross_profit > 0
    else:
        profit_factor_ok = profit_factor >= constraints.min_profit_factor
    if not profit_factor_ok:
        reasons.append(f"profit_factor<{constraints.min_profit_factor}")

    if max_drawdown_pct > constraints.max_drawdown_pct:
        reasons.append(f"max_drawdown_pct>{constraints.max_drawdown_pct}")
    return reasons


def _refined_values(center: float, step: float) -> list[float]:
    values = {round(center, 6)}
    if step > 0:
        if center - step > 0:
            values.add(round(center - step, 6))
        values.add(round(center + step, 6))
    return sorted(values)


def _dedupe_candidates(candidates) -> list[OptimizationCandidate]:
    unique: list[OptimizationCandidate] = []
    seen: set[tuple[float, float, float, bool, bool, bool]] = set()
    for candidate in candidates:
        key = candidate.key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique
