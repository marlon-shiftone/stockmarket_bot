from fastapi import FastAPI, HTTPException

from adapters.market_data.csv_feed import CSVMarketDataAdapter
from api.runtime import build_runtime
from api.schemas import BacktestReportRequest, CandleIn, ReplayRequest
from core.models.candle import Candle
from infra.config import get_settings
from services.backtest_report_service import BacktestReportService

app = FastAPI(title="StockMarket Bot API", version="0.1.0")
_runtime = build_runtime()
_csv_loader = CSVMarketDataAdapter()
_settings = get_settings()


def _build_backtest_report_service() -> BacktestReportService:
    # Backtests must stay local even when the operational runtime uses Alpaca paper.
    return BacktestReportService(runtime=build_runtime(force_local_paper=True))


@app.get("/health")
def health() -> dict[str, str | bool | float]:
    return {
        "status": "ok",
        "trading_mode": _settings.trading_mode,
        "broker_provider": _settings.broker_provider,
        "allow_live_trading": _settings.allow_live_trading,
        "nw_bandwidth": _settings.nw_bandwidth,
        "nw_mult": _settings.nw_mult,
        "mkr_bandwidth": _settings.mkr_bandwidth,
        "require_confirmation": _settings.require_confirmation,
        "require_trend_meter": _settings.require_trend_meter,
        "require_mkr_alignment": _settings.require_mkr_alignment,
        "operational_params_path": _settings.operational_params_path or "",
        "operational_selection_source": _settings.operational_selection_source or "",
        "operational_selection_basis": _settings.operational_selection_basis or "",
        "operational_symbol": _settings.operational_symbol or "",
        "operational_timeframe": _settings.operational_timeframe or "",
    }


@app.post("/v1/candles")
def ingest_candle(payload: CandleIn):
    candle = Candle(
        symbol=payload.symbol,
        timestamp=payload.timestamp,
        open=payload.open,
        high=payload.high,
        low=payload.low,
        close=payload.close,
        volume=payload.volume,
    )
    result = _runtime.process_candle(candle=candle, qty=payload.qty)
    return result.model_dump()


@app.post("/v1/replay")
def replay(request: ReplayRequest):
    try:
        candles = _csv_loader.load_candles(source=request.csv_path, symbol=request.symbol)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"CSV not found: {request.csv_path}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    replay_runtime = build_runtime(force_local_paper=True)
    try:
        summary = replay_runtime.replay(
            candles=candles,
            qty=request.qty,
            initial_capital=request.initial_capital,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summary.model_dump()


@app.post("/v1/backtest/report")
def backtest_report(request: BacktestReportRequest):
    try:
        candles = _csv_loader.load_candles_with_symbol_fallback(
            source=request.csv_path,
            default_symbol=request.symbol,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"CSV not found: {request.csv_path}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    backtest_report_service = _build_backtest_report_service()
    try:
        report = backtest_report_service.run_report(
            candles=candles,
            qty=request.qty,
            period=request.period,
            output_dir=request.output_dir,
            initial_capital=request.initial_capital,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return report.model_dump()


@app.get("/v1/signals")
def list_signals():
    return [signal.model_dump() for signal in _runtime.list_signals()]


@app.get("/v1/orders")
def list_orders():
    return [order.model_dump() for order in _runtime.list_orders()]


@app.get("/v1/positions")
def list_positions():
    return [position.model_dump() for position in _runtime.list_positions()]


@app.get("/v1/trades")
def list_trades():
    return [trade.model_dump() for trade in _runtime.list_closed_trades()]


@app.post("/v1/reset")
def reset():
    _runtime.reset()
    return {"status": "reset"}
