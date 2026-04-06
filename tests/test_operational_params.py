import json
from pathlib import Path

import pytest

from infra.config import Settings
from infra.operational_params import resolve_operational_selection


def _write_operational_file(path: Path) -> None:
    payload = {
        "selection_source": "walk_forward",
        "generated_at": "2026-03-25T00:00:00+00:00",
        "datasets": [
            {
                "symbol": "AAPL",
                "timeframe": "5Min",
                "selection_basis": "eligible",
                "candidate": {
                    "nw_bandwidth": 8.0,
                    "nw_mult": 0.75,
                    "mkr_bandwidth": 9.0,
                    "require_confirmation": False,
                    "require_trend_meter": False,
                    "require_mkr_alignment": False,
                },
                "metrics": {"net_profit": 1.23},
            },
            {
                "symbol": "AAPL",
                "timeframe": "15Min",
                "selection_basis": "overall_fallback",
                "candidate": {
                    "nw_bandwidth": 8.0,
                    "nw_mult": 1.0,
                    "mkr_bandwidth": 9.0,
                    "require_confirmation": False,
                    "require_trend_meter": False,
                    "require_mkr_alignment": True,
                },
                "metrics": {"net_profit": 0.5},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_operational_selection_matches_symbol_and_timeframe(tmp_path: Path) -> None:
    operational_file = tmp_path / "operational_params.json"
    _write_operational_file(operational_file)

    params, entry = resolve_operational_selection(operational_file, symbol="AAPL", timeframe="5Min")

    assert params.selection_source == "walk_forward"
    assert entry.selection_basis == "eligible"
    assert entry.candidate is not None
    assert entry.candidate.nw_mult == 0.75


def test_settings_uses_operational_params_when_configured(tmp_path: Path, monkeypatch) -> None:
    operational_file = tmp_path / "operational_params.json"
    _write_operational_file(operational_file)

    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("BROKER_PROVIDER", "alpaca")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("SYMBOL", "AAPL")
    monkeypatch.setenv("ALPACA_BAR_TIMEFRAME", "15Min")
    monkeypatch.setenv("OPERATIONAL_PARAMS_PATH", str(operational_file))
    monkeypatch.setenv("NW_MULT", "3.0")
    monkeypatch.setenv("REQUIRE_MKR_ALIGNMENT", "false")

    settings = Settings()

    assert settings.nw_mult == 1.0
    assert settings.require_mkr_alignment is True
    assert settings.operational_selection_source == "walk_forward"
    assert settings.operational_selection_basis == "overall_fallback"
    assert settings.operational_timeframe == "15Min"


def test_resolve_operational_selection_raises_when_no_match(tmp_path: Path) -> None:
    operational_file = tmp_path / "operational_params.json"
    _write_operational_file(operational_file)

    with pytest.raises(ValueError, match="No operational parameter dataset matched"):
        resolve_operational_selection(operational_file, symbol="TSLA", timeframe="5Min")
