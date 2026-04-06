from adapters.brokers.alpaca_broker import AlpacaBroker
from adapters.brokers.paper_broker import PaperBroker
from core.ports.broker_port import BrokerPort
from indicators.pipeline import IndicatorCalculator
from infra.config import Settings, get_settings
from infra.db.in_memory_store import InMemoryStore
from services.execution_engine import ExecutionEngine
from services.signal_engine import SignalEngine
from services.trading_runtime import TradingRuntime
from strategies.ha_envelope_trend_meter import HAEnvelopeTrendMeterStrategy


def _build_broker(settings: Settings, *, force_local_paper: bool = False) -> BrokerPort:
    if force_local_paper:
        return PaperBroker()

    if settings.broker_provider == "paper":
        return PaperBroker()

    if settings.broker_provider == "alpaca":
        return AlpacaBroker(
            api_key=settings.alpaca_api_key,
            api_secret=settings.alpaca_api_secret,
            base_url=settings.alpaca_base_url,
        )

    raise RuntimeError(f"Unsupported broker provider: {settings.broker_provider}")


def build_runtime(
    *,
    force_local_paper: bool = False,
    nw_bandwidth: float | None = None,
    nw_mult: float | None = None,
    mkr_bandwidth: float | None = None,
    require_confirmation: bool | None = None,
    require_trend_meter: bool | None = None,
    require_mkr_alignment: bool | None = None,
) -> TradingRuntime:
    settings = get_settings()
    broker = _build_broker(settings, force_local_paper=force_local_paper)
    strategy = HAEnvelopeTrendMeterStrategy(
        require_confirmation=settings.require_confirmation if require_confirmation is None else require_confirmation,
        require_trend_meter=settings.require_trend_meter if require_trend_meter is None else require_trend_meter,
        require_mkr_alignment=(
            settings.require_mkr_alignment if require_mkr_alignment is None else require_mkr_alignment
        ),
    )
    indicators = IndicatorCalculator(
        nw_bandwidth=settings.nw_bandwidth if nw_bandwidth is None else nw_bandwidth,
        nw_mult=settings.nw_mult if nw_mult is None else nw_mult,
        mkr_bandwidth=settings.mkr_bandwidth if mkr_bandwidth is None else mkr_bandwidth,
    )
    store = InMemoryStore()
    trading_mode = "paper" if force_local_paper else settings.trading_mode

    signal_engine = SignalEngine(
        strategy=strategy,
        indicator_calculator=indicators,
        broker=broker,
    )
    execution_engine = ExecutionEngine(
        broker=broker,
        trading_mode=trading_mode,
        allow_live_trading=False if force_local_paper else settings.allow_live_trading,
    )

    return TradingRuntime(
        signal_engine=signal_engine,
        execution_engine=execution_engine,
        broker=broker,
        store=store,
        default_order_qty=settings.default_order_qty,
        trading_mode=trading_mode,
    )
