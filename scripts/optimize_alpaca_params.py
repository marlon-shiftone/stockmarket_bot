import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from adapters.market_data.csv_feed import CSVMarketDataAdapter
from services.alpaca_historical_data import default_alpaca_data_url, fetch_or_load_cached_bars
from services.parameter_optimizer import (
    OptimizationConstraints,
    OptimizationDataset,
    ParameterOptimizer,
    ParameterSearchSpace,
    WalkForwardConfig,
)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_csv_list(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("Expected at least one comma-separated value")
    return values


def _parse_float_list(raw: str) -> list[float]:
    return [float(item) for item in _parse_csv_list(raw)]


def _parse_bool_list(raw: str) -> list[bool]:
    mapping = {
        "1": True,
        "true": True,
        "yes": True,
        "on": True,
        "0": False,
        "false": False,
        "no": False,
        "off": False,
    }
    values: list[bool] = []
    for item in _parse_csv_list(raw):
        normalized = item.lower()
        if normalized not in mapping:
            raise ValueError(f"Invalid boolean value: {item}")
        values.append(mapping[normalized])
    return values


def _optional_env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize Alpaca strategy parameters with local paper backtests.")
    parser.add_argument("--symbols", default=os.getenv("SYMBOL", "AAPL"))
    parser.add_argument("--timeframes", default=os.getenv("ALPACA_BAR_TIMEFRAME", "5Min"))
    parser.add_argument("--asset-class", default=os.getenv("ALPACA_ASSET_CLASS", "stocks"))
    parser.add_argument("--lookback-days", type=int, default=int(os.getenv("VALIDATION_LOOKBACK_DAYS", "30")))
    parser.add_argument("--stock-feed", default=os.getenv("VALIDATION_STOCK_FEED", "iex"))
    parser.add_argument("--data-url", default=os.getenv("VALIDATION_ALPACA_DATA_URL", ""))
    parser.add_argument("--cache-dir", default=os.getenv("OPTIMIZATION_CACHE_DIR", "data/cache/alpaca"))
    parser.add_argument("--output-dir", default=os.getenv("OPTIMIZATION_OUTPUT_DIR", "data/optimization"))
    parser.add_argument("--qty", type=float, default=float(os.getenv("VALIDATION_QTY", "1")))
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=float(os.getenv("VALIDATION_INITIAL_CAPITAL", "10000")),
    )
    parser.add_argument("--nw-bandwidths", default=os.getenv("OPT_NW_BANDWIDTHS", "8.0"))
    parser.add_argument("--nw-mults", default=os.getenv("OPT_NW_MULTS", "3.0,2.0,1.5,1.0,0.75"))
    parser.add_argument("--mkr-bandwidths", default=os.getenv("OPT_MKR_BANDWIDTHS", "9.0"))
    parser.add_argument(
        "--require-confirmation-values",
        default=os.getenv("OPT_REQUIRE_CONFIRMATION_VALUES", "true,false"),
    )
    parser.add_argument(
        "--require-trend-meter-values",
        default=os.getenv("OPT_REQUIRE_TREND_METER_VALUES", "true,false"),
    )
    parser.add_argument(
        "--require-mkr-alignment-values",
        default=os.getenv("OPT_REQUIRE_MKR_ALIGNMENT_VALUES", "true,false"),
    )
    parser.add_argument("--min-trades", type=int, default=int(os.getenv("OPT_MIN_TRADES", "20")))
    parser.add_argument(
        "--min-profit-factor",
        type=float,
        default=float(os.getenv("OPT_MIN_PROFIT_FACTOR", "1.2")),
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=float,
        default=float(os.getenv("OPT_MAX_DRAWDOWN_PCT", "5.0")),
    )
    parser.add_argument(
        "--drawdown-weight",
        type=float,
        default=float(os.getenv("OPT_DRAWDOWN_WEIGHT", "1.0")),
    )
    parser.add_argument(
        "--profit-factor-weight",
        type=float,
        default=float(os.getenv("OPT_PROFIT_FACTOR_WEIGHT", "0.25")),
    )
    parser.add_argument(
        "--profit-factor-cap",
        type=float,
        default=float(os.getenv("OPT_PROFIT_FACTOR_CAP", "5.0")),
    )
    parser.add_argument("--refine-top-k", type=int, default=int(os.getenv("OPT_REFINE_TOP_K", "3")))
    parser.add_argument(
        "--nw-bandwidth-refine-step",
        type=float,
        default=float(os.getenv("OPT_NW_BANDWIDTH_REFINE_STEP", "1.0")),
    )
    parser.add_argument(
        "--nw-mult-refine-step",
        type=float,
        default=float(os.getenv("OPT_NW_MULT_REFINE_STEP", "0.25")),
    )
    parser.add_argument(
        "--mkr-bandwidth-refine-step",
        type=float,
        default=float(os.getenv("OPT_MKR_BANDWIDTH_REFINE_STEP", "1.0")),
    )
    parser.add_argument("--walk-forward", action="store_true", default=os.getenv("OPT_WALK_FORWARD", "false").lower() in {"1", "true", "yes", "on"})
    parser.add_argument("--wf-train-bars", type=int, default=_optional_env_int("OPT_WF_TRAIN_BARS"))
    parser.add_argument("--wf-test-bars", type=int, default=_optional_env_int("OPT_WF_TEST_BARS"))
    parser.add_argument("--wf-step-bars", type=int, default=_optional_env_int("OPT_WF_STEP_BARS"))
    parser.add_argument("--wf-anchored", action="store_true", default=os.getenv("OPT_WF_ANCHORED", "false").lower() in {"1", "true", "yes", "on"})
    parser.add_argument("--force-refresh", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    api_key = _required_env("ALPACA_API_KEY")
    api_secret = _required_env("ALPACA_API_SECRET")

    asset_class = args.asset_class.lower()
    symbols = _parse_csv_list(args.symbols)
    timeframes = _parse_csv_list(args.timeframes)
    data_url = args.data_url.strip() or default_alpaca_data_url(asset_class)
    stock_feed = args.stock_feed.strip() or None
    run_id = f"alpaca_opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    output_dir = Path(args.output_dir) / run_id

    loader = CSVMarketDataAdapter()
    datasets: list[OptimizationDataset] = []
    candles_by_dataset: dict[str, list] = {}

    print("Preparing Alpaca datasets for optimization...")
    for symbol in symbols:
        for timeframe in timeframes:
            cached = fetch_or_load_cached_bars(
                api_key=api_key,
                api_secret=api_secret,
                asset_class=asset_class,
                symbol=symbol,
                timeframe=timeframe,
                lookback_days=args.lookback_days,
                cache_dir=args.cache_dir,
                stock_feed=stock_feed if asset_class == "stocks" else None,
                data_url=data_url,
                force_refresh=args.force_refresh,
            )
            candles = loader.load_candles(source=cached.csv_path, symbol=symbol)
            dataset = OptimizationDataset(
                symbol=symbol,
                timeframe=timeframe,
                csv_path=cached.csv_path,
                cache_hit=cached.cache_hit,
                candle_count=len(candles),
                window_start=cached.window_start,
                window_end=cached.window_end,
            )
            datasets.append(dataset)
            candles_by_dataset[dataset.dataset_key] = candles
            print(
                f"dataset symbol={symbol} timeframe={timeframe} candles={len(candles)} "
                f"cache_hit={cached.cache_hit} csv={cached.csv_path}"
            )

    search_space = ParameterSearchSpace(
        nw_bandwidths=_parse_float_list(args.nw_bandwidths),
        nw_mults=_parse_float_list(args.nw_mults),
        mkr_bandwidths=_parse_float_list(args.mkr_bandwidths),
        require_confirmation_values=_parse_bool_list(args.require_confirmation_values),
        require_trend_meter_values=_parse_bool_list(args.require_trend_meter_values),
        require_mkr_alignment_values=_parse_bool_list(args.require_mkr_alignment_values),
        refine_top_k=args.refine_top_k,
        nw_bandwidth_refine_step=args.nw_bandwidth_refine_step,
        nw_mult_refine_step=args.nw_mult_refine_step,
        mkr_bandwidth_refine_step=args.mkr_bandwidth_refine_step,
    )
    constraints = OptimizationConstraints(
        min_trades=args.min_trades,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_pct=args.max_drawdown_pct,
        drawdown_weight=args.drawdown_weight,
        profit_factor_weight=args.profit_factor_weight,
        profit_factor_cap=args.profit_factor_cap,
    )

    optimizer = ParameterOptimizer(
        datasets=datasets,
        candles_by_dataset=candles_by_dataset,
        output_dir=output_dir,
        search_space=search_space,
        constraints=constraints,
        qty=args.qty,
        initial_capital=args.initial_capital,
    )
    result = optimizer.run()

    print()
    print("=== Optimization Result ===")
    print(
        f"run_id={result.run_id} trials={result.trials_evaluated} eligible={result.eligible_trials} "
        f"coarse_candidates={result.coarse_candidates} refined_candidates={result.refined_candidates}"
    )
    selected = result.best_eligible_trial or result.best_overall_trial
    if selected is None:
        print("No trial was evaluated.")
    else:
        basis = "eligible" if result.best_eligible_trial is not None else "overall_fallback"
        print(
            f"best_selection={basis} symbol={selected.symbol} timeframe={selected.timeframe} "
            f"nw_bandwidth={selected.nw_bandwidth} nw_mult={selected.nw_mult} "
            f"mkr_bandwidth={selected.mkr_bandwidth} require_confirmation={selected.require_confirmation} "
            f"require_trend_meter={selected.require_trend_meter} "
            f"require_mkr_alignment={selected.require_mkr_alignment}"
        )
        print(
            f"total_trades={selected.total_trades} win_rate={selected.win_rate} "
            f"profit_factor={selected.profit_factor} net_profit={selected.net_profit} "
            f"max_drawdown={selected.max_drawdown} max_drawdown_pct={selected.max_drawdown_pct} "
            f"score={selected.score}"
        )
    print(f"all_trials_csv_path={result.all_trials_csv_path}")
    print(f"best_params_json_path={result.best_params_json_path}")
    print(f"operational_params_json_path={result.operational_params_json_path}")
    print(f"summary_json_path={result.summary_json_path}")

    if args.walk_forward:
        walk_forward = optimizer.run_walk_forward(
            WalkForwardConfig(
                train_size_bars=args.wf_train_bars,
                test_size_bars=args.wf_test_bars,
                step_size_bars=args.wf_step_bars,
                anchored=args.wf_anchored,
            )
        )
        print()
        print("=== Walk Forward Result ===")
        print(
            f"total_windows={walk_forward.total_windows} eligible_windows={walk_forward.eligible_windows} "
            f"datasets={len(walk_forward.datasets)}"
        )
        for dataset_summary in walk_forward.datasets:
            print(
                f"dataset symbol={dataset_summary.symbol} timeframe={dataset_summary.timeframe} "
                f"windows={dataset_summary.total_windows} net_profit={dataset_summary.net_profit} "
                f"ending_capital={dataset_summary.ending_capital} max_drawdown={dataset_summary.max_drawdown} "
                f"max_drawdown_pct={dataset_summary.max_drawdown_pct} profit_factor={dataset_summary.profit_factor}"
            )
            best_candidate = dataset_summary.best_eligible_candidate or dataset_summary.best_overall_candidate
            if best_candidate is not None:
                basis = "eligible" if dataset_summary.best_eligible_candidate is not None else "overall_fallback"
                print(
                    f"walk_forward_best_candidate_selection={basis} "
                    f"nw_bandwidth={best_candidate.nw_bandwidth} nw_mult={best_candidate.nw_mult} "
                    f"mkr_bandwidth={best_candidate.mkr_bandwidth} "
                    f"require_confirmation={best_candidate.require_confirmation} "
                    f"require_trend_meter={best_candidate.require_trend_meter} "
                    f"require_mkr_alignment={best_candidate.require_mkr_alignment} "
                    f"net_profit={best_candidate.net_profit} profit_factor={best_candidate.profit_factor} "
                    f"max_drawdown={best_candidate.max_drawdown} "
                    f"max_drawdown_pct={best_candidate.max_drawdown_pct} "
                    f"eligible_windows={best_candidate.eligible_windows}/{best_candidate.windows_evaluated}"
                )
            if dataset_summary.equity_curve_csv_path:
                print(f"walk_forward_equity_curve_csv_path={dataset_summary.equity_curve_csv_path}")
            if dataset_summary.candidate_summaries_csv_path:
                print(f"walk_forward_candidate_summaries_csv_path={dataset_summary.candidate_summaries_csv_path}")
        print(f"walk_forward_trials_csv_path={walk_forward.trials_csv_path}")
        print(f"walk_forward_operational_params_json_path={walk_forward.operational_params_json_path}")
        print(f"walk_forward_summary_json_path={walk_forward.summary_json_path}")


if __name__ == "__main__":
    main()
