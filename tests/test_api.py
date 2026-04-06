from pathlib import Path

from api.app import backtest_report, health, ingest_candle, list_trades
from api.schemas import BacktestReportRequest, CandleIn


def test_health() -> None:
    payload = health()
    assert payload["status"] == "ok"
    assert payload["trading_mode"] == "paper"
    assert "nw_bandwidth" in payload
    assert "nw_mult" in payload
    assert "mkr_bandwidth" in payload
    assert "require_confirmation" in payload
    assert "require_trend_meter" in payload
    assert "operational_selection_source" in payload


def test_ingest_candle_smoke() -> None:
    result = ingest_candle(
        CandleIn(
            symbol="PETR4",
            timestamp="2026-01-01T00:00:00+00:00",
            open=10,
            high=11,
            low=9,
            close=10.5,
            volume=1000,
        )
    )

    assert "signal" in result
    assert result["signal"]["signal_type"] in {
        "NONE",
        "BUY",
        "SELL",
        "CLOSE_BUY",
        "CLOSE_SELL",
    }
    assert result["signal"]["indicator_snapshot"] is not None


def test_list_trades_smoke() -> None:
    result = list_trades()
    assert isinstance(result, list)


def test_backtest_report_endpoint_smoke(tmp_path: Path) -> None:
    csv_file = tmp_path / "candles.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,symbol,open,high,low,close,volume",
                "2026-01-01T00:00:00+00:00,PETR4,10,11,9,10.5,1000",
                "2026-01-01T00:01:00+00:00,PETR4,10.5,11.2,10.2,10.9,900",
            ]
        ),
        encoding="utf-8",
    )

    result = backtest_report(
        BacktestReportRequest(
            csv_path=str(csv_file),
            period="day",
            output_dir=str(tmp_path),
            initial_capital=5000.0,
        )
    )

    assert result["summary"]["initial_capital"] == 5000.0
    assert "summary" in result
    assert "grouped_metrics" in result
    assert "equity_curve_csv_path" in result
