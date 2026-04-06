from adapters.brokers.alpaca_broker import AlpacaBroker
from adapters.brokers.paper_broker import PaperBroker
from api.runtime import build_runtime


def test_build_runtime_uses_alpaca_broker_in_paper_mode_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("BROKER_PROVIDER", "alpaca")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("NW_BANDWIDTH", "10")
    monkeypatch.setenv("NW_MULT", "1.5")
    monkeypatch.setenv("MKR_BANDWIDTH", "12")
    monkeypatch.setenv("REQUIRE_CONFIRMATION", "false")
    monkeypatch.setenv("REQUIRE_TREND_METER", "false")
    monkeypatch.setenv("REQUIRE_MKR_ALIGNMENT", "true")

    runtime = build_runtime()

    assert isinstance(runtime._broker, AlpacaBroker)
    assert runtime._signal_engine._indicator_calculator.nw_bandwidth == 10.0
    assert runtime._signal_engine._indicator_calculator.nw_mult == 1.5
    assert runtime._signal_engine._indicator_calculator.mkr_bandwidth == 12.0
    assert len(runtime._signal_engine._strategy.buy_rules) == 2
    assert len(runtime._signal_engine._strategy.sell_rules) == 2


def test_build_runtime_force_local_paper_overrides_alpaca(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("BROKER_PROVIDER", "alpaca")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    runtime = build_runtime(force_local_paper=True)

    assert isinstance(runtime._broker, PaperBroker)


def test_build_runtime_uses_default_parameters_when_not_set(monkeypatch) -> None:
    monkeypatch.delenv("NW_BANDWIDTH", raising=False)
    monkeypatch.delenv("NW_MULT", raising=False)
    monkeypatch.delenv("MKR_BANDWIDTH", raising=False)
    monkeypatch.delenv("REQUIRE_CONFIRMATION", raising=False)
    monkeypatch.delenv("REQUIRE_TREND_METER", raising=False)
    monkeypatch.delenv("REQUIRE_MKR_ALIGNMENT", raising=False)
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("BROKER_PROVIDER", "paper")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")

    runtime = build_runtime(force_local_paper=True)

    assert runtime._signal_engine._indicator_calculator.nw_bandwidth == 8.0
    assert runtime._signal_engine._indicator_calculator.nw_mult == 3.0
    assert runtime._signal_engine._indicator_calculator.mkr_bandwidth == 9.0
    assert len(runtime._signal_engine._strategy.buy_rules) == 4
    assert len(runtime._signal_engine._strategy.sell_rules) == 4


def test_build_runtime_allows_explicit_parameter_overrides(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("BROKER_PROVIDER", "paper")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    monkeypatch.setenv("NW_BANDWIDTH", "8")
    monkeypatch.setenv("NW_MULT", "3")
    monkeypatch.setenv("MKR_BANDWIDTH", "9")
    monkeypatch.setenv("REQUIRE_CONFIRMATION", "true")
    monkeypatch.setenv("REQUIRE_TREND_METER", "true")
    monkeypatch.setenv("REQUIRE_MKR_ALIGNMENT", "true")

    runtime = build_runtime(
        force_local_paper=True,
        nw_bandwidth=6.0,
        nw_mult=0.75,
        mkr_bandwidth=7.0,
        require_confirmation=False,
        require_trend_meter=False,
        require_mkr_alignment=False,
    )

    assert runtime._signal_engine._indicator_calculator.nw_bandwidth == 6.0
    assert runtime._signal_engine._indicator_calculator.nw_mult == 0.75
    assert runtime._signal_engine._indicator_calculator.mkr_bandwidth == 7.0
    assert len(runtime._signal_engine._strategy.buy_rules) == 1
    assert len(runtime._signal_engine._strategy.sell_rules) == 1
