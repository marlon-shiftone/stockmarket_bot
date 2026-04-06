from datetime import datetime, timezone

from adapters.brokers.paper_broker import PaperBroker
from core.models.enums import SignalType
from core.models.signal import Signal


def _signal(signal_type: SignalType, price: float) -> Signal:
    return Signal(
        signal_type=signal_type,
        symbol="PETR4",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=price,
        reasons=[],
    )


def test_open_and_close_long_updates_realized_pnl() -> None:
    broker = PaperBroker()

    open_order = broker.place_order(_signal(SignalType.BUY, 10.0), qty=2)
    close_order = broker.place_order(_signal(SignalType.CLOSE_BUY, 11.5), qty=2)

    assert open_order is not None
    assert close_order is not None
    assert broker.realized_pnl == 3.0
    assert broker.list_positions() == []
