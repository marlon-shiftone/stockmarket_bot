from datetime import datetime, timezone

import httpx
import pytest

from adapters.brokers.alpaca_broker import AlpacaBroker
from core.models.enums import OrderStatus, PositionSide, SignalType
from core.models.signal import Signal


def _signal(signal_type: SignalType, price: float, symbol: str = "AAPL") -> Signal:
    return Signal(
        signal_type=signal_type,
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=price,
        reasons=[],
    )


def test_place_order_posts_market_order_and_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AlpacaBroker(api_key="key", api_secret="secret", base_url="https://paper-api.alpaca.markets")
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    def fake_request(method: str, path: str, *, params=None, payload=None):
        calls.append((method, path, params, payload))
        if method == "GET" and path == "/v2/positions/AAPL":
            request = httpx.Request("GET", "https://paper-api.alpaca.markets/v2/positions/AAPL")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        if method == "POST" and path == "/v2/orders":
            return {
                "id": "order-1",
                "symbol": "AAPL",
                "qty": "2",
                "side": "buy",
                "status": "filled",
                "filled_avg_price": "101.25",
                "submitted_at": "2026-01-01T00:00:01Z",
            }
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(broker, "_request", fake_request)

    order = broker.place_order(_signal(SignalType.BUY, 100.0), qty=2.0)

    assert order is not None
    assert order.id == "order-1"
    assert order.status == OrderStatus.FILLED
    assert order.price == 101.25
    assert order.qty == 2.0
    assert calls[-1][3] == {
        "symbol": "AAPL",
        "qty": "2.0",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }


def test_list_positions_maps_remote_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AlpacaBroker(api_key="key", api_secret="secret", base_url="https://paper-api.alpaca.markets")

    def fake_request(method: str, path: str, *, params=None, payload=None):
        assert method == "GET"
        assert path == "/v2/positions"
        return [
            {
                "symbol": "AAPL",
                "qty": "3",
                "side": "long",
                "avg_entry_price": "99.5",
                "current_price": "101.0",
            },
            {
                "symbol": "TSLA",
                "qty": "-1",
                "side": "short",
                "avg_entry_price": "200.0",
                "current_price": "190.0",
            },
        ]

    monkeypatch.setattr(broker, "_request", fake_request)

    positions = broker.list_positions()

    assert len(positions) == 2
    assert positions[0].symbol == "AAPL"
    assert positions[0].side == PositionSide.LONG
    assert positions[0].qty == 3.0
    assert positions[1].symbol == "TSLA"
    assert positions[1].side == PositionSide.SHORT
    assert positions[1].qty == 1.0


def test_closed_trades_and_realized_pnl_are_derived_from_fill_activities(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AlpacaBroker(api_key="key", api_secret="secret", base_url="https://paper-api.alpaca.markets")

    def fake_request(method: str, path: str, *, params=None, payload=None):
        assert method == "GET"
        assert path == "/v2/account/activities/FILL"
        return [
            {
                "id": "1",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "2",
                "price": "10",
                "transaction_time": "2026-01-01T00:00:00Z",
            },
            {
                "id": "2",
                "symbol": "AAPL",
                "side": "sell",
                "qty": "1",
                "price": "11",
                "transaction_time": "2026-01-01T00:01:00Z",
            },
            {
                "id": "3",
                "symbol": "AAPL",
                "side": "sell",
                "qty": "2",
                "price": "12",
                "transaction_time": "2026-01-01T00:02:00Z",
            },
            {
                "id": "4",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "1",
                "price": "9",
                "transaction_time": "2026-01-01T00:03:00Z",
            },
        ]

    monkeypatch.setattr(broker, "_request", fake_request)

    closed_trades = broker.list_closed_trades()

    assert len(closed_trades) == 3
    assert [trade.side for trade in closed_trades] == [
        PositionSide.LONG,
        PositionSide.LONG,
        PositionSide.SHORT,
    ]
    assert [trade.pnl for trade in closed_trades] == [1.0, 2.0, 3.0]
    assert broker.get_realized_pnl() == 6.0
