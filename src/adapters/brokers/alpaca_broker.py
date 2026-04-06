from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from core.models.enums import OrderSide, OrderStatus, PositionSide, SignalType
from core.models.order import Order
from core.models.position import Position
from core.models.signal import Signal
from core.models.trade import ClosedTrade
from core.ports.broker_port import BrokerPort


@dataclass
class _OpenLot:
    side: PositionSide
    qty: float
    entry_price: float
    entry_timestamp: datetime


class AlpacaBroker(BrokerPort):
    _REJECTED_STATUSES = {"rejected", "canceled", "expired", "suspended"}
    _ACTIVITY_PAGE_SIZE = 100

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "Content-Type": "application/json",
            },
        )
        self._orders: list[Order] = []

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _parse_float(value: str | float | int | None) -> float:
        if value in {None, ""}:
            return 0.0
        return float(value)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ):
        url = f"{self._base_url}{path}"
        response = self._client.request(method=method, url=url, params=params, json=payload)
        response.raise_for_status()
        return response.json()

    def _fetch_fill_activities(self) -> list[dict]:
        activities: list[dict] = []
        page_token: str | None = None

        while True:
            params: dict[str, str | int] = {
                "direction": "asc",
                "page_size": self._ACTIVITY_PAGE_SIZE,
            }
            if page_token is not None:
                params["page_token"] = page_token

            batch = self._request("GET", "/v2/account/activities/FILL", params=params)
            if not isinstance(batch, list) or not batch:
                break

            activities.extend(batch)
            if len(batch) < self._ACTIVITY_PAGE_SIZE:
                break

            next_page_token = str(batch[-1].get("id", "")).strip()
            if not next_page_token or next_page_token == page_token:
                break
            page_token = next_page_token

        return activities

    @classmethod
    def _build_closed_trades(cls, activities: list[dict]) -> list[ClosedTrade]:
        closed_trades: list[ClosedTrade] = []
        open_lots: dict[str, list[_OpenLot]] = {}

        ordered_activities = sorted(
            activities,
            key=lambda row: (
                cls._parse_timestamp(row.get("transaction_time")),
                str(row.get("id", "")),
            ),
        )

        for activity in ordered_activities:
            symbol = str(activity.get("symbol", "")).strip()
            side_text = str(activity.get("side", "")).lower()
            qty = cls._parse_float(activity.get("qty"))

            if not symbol or side_text not in {"buy", "sell"} or qty <= 0:
                continue

            price = cls._parse_float(activity.get("price"))
            timestamp = cls._parse_timestamp(activity.get("transaction_time"))
            opening_side = PositionSide.LONG if side_text == "buy" else PositionSide.SHORT
            symbol_lots = open_lots.setdefault(symbol, [])

            while qty > 0 and symbol_lots and symbol_lots[0].side != opening_side:
                open_lot = symbol_lots[0]
                matched_qty = min(qty, open_lot.qty)
                pnl = (
                    (price - open_lot.entry_price) * matched_qty
                    if open_lot.side == PositionSide.LONG
                    else (open_lot.entry_price - price) * matched_qty
                )
                closed_trades.append(
                    ClosedTrade(
                        symbol=symbol,
                        side=open_lot.side,
                        qty=matched_qty,
                        entry_price=open_lot.entry_price,
                        exit_price=price,
                        entry_timestamp=open_lot.entry_timestamp,
                        exit_timestamp=timestamp,
                        pnl=pnl,
                    )
                )
                open_lot.qty -= matched_qty
                qty -= matched_qty

                if open_lot.qty <= 1e-12:
                    symbol_lots.pop(0)

            if qty > 1e-12:
                symbol_lots.append(
                    _OpenLot(
                        side=opening_side,
                        qty=qty,
                        entry_price=price,
                        entry_timestamp=timestamp,
                    )
                )

        return closed_trades

    def _reject(self, signal: Signal, qty: float, note: str) -> Order:
        side = OrderSide.BUY if signal.signal_type in {SignalType.BUY, SignalType.CLOSE_SELL} else OrderSide.SELL
        order = Order(
            id=str(uuid4()),
            symbol=signal.symbol,
            timestamp=datetime.now(timezone.utc),
            side=side,
            qty=qty,
            price=signal.price,
            status=OrderStatus.REJECTED,
            source_signal=signal.signal_type,
            note=f"alpaca reject: {note}",
        )
        self._orders.append(order)
        return order

    def _resolve_order_params(self, signal: Signal, qty: float) -> tuple[str, float]:
        if signal.signal_type == SignalType.BUY:
            if self.get_position(signal.symbol) is not None:
                raise ValueError("position already open")
            return "buy", qty

        if signal.signal_type == SignalType.SELL:
            if self.get_position(signal.symbol) is not None:
                raise ValueError("position already open")
            return "sell", qty

        position = self.get_position(signal.symbol)
        if signal.signal_type == SignalType.CLOSE_BUY:
            if position is None or position.side != PositionSide.LONG:
                raise ValueError("no LONG position to close")
            return "sell", position.qty

        if signal.signal_type == SignalType.CLOSE_SELL:
            if position is None or position.side != PositionSide.SHORT:
                raise ValueError("no SHORT position to close")
            return "buy", position.qty

        raise ValueError(f"unsupported signal: {signal.signal_type}")

    def place_order(self, signal: Signal, qty: float) -> Order | None:
        if signal.signal_type == SignalType.NONE:
            return None

        try:
            side, resolved_qty = self._resolve_order_params(signal=signal, qty=qty)
        except Exception as exc:
            return self._reject(signal, qty, str(exc))

        payload = {
            "symbol": signal.symbol,
            "qty": str(resolved_qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }

        try:
            remote = self._request("POST", "/v2/orders", payload=payload)
            remote_status = str(remote.get("status", "unknown")).lower()
            status = OrderStatus.REJECTED if remote_status in self._REJECTED_STATUSES else OrderStatus.FILLED

            remote_side = str(remote.get("side", side)).lower()
            order_side = OrderSide.BUY if remote_side == "buy" else OrderSide.SELL
            fill_price = self._parse_float(remote.get("filled_avg_price")) or signal.price

            order = Order(
                id=str(remote.get("id", uuid4())),
                symbol=str(remote.get("symbol", signal.symbol)),
                timestamp=self._parse_timestamp(remote.get("submitted_at")),
                side=order_side,
                qty=self._parse_float(remote.get("qty")) or resolved_qty,
                price=fill_price,
                status=status,
                source_signal=signal.signal_type,
                note=f"alpaca status={remote_status}",
            )
            self._orders.append(order)
            return order
        except Exception as exc:
            return self._reject(signal, resolved_qty, str(exc))

    def list_orders(self) -> list[Order]:
        return list(self._orders)

    def list_positions(self) -> list[Position]:
        rows = self._request("GET", "/v2/positions")
        now = datetime.now(timezone.utc)

        positions: list[Position] = []
        for row in rows:
            qty = self._parse_float(row.get("qty"))
            side_text = str(row.get("side", "long")).lower()
            side = PositionSide.SHORT if side_text == "short" else PositionSide.LONG
            abs_qty = abs(qty)
            entry = self._parse_float(row.get("avg_entry_price"))
            current = self._parse_float(row.get("current_price")) or entry
            positions.append(
                Position(
                    symbol=str(row.get("symbol", "")),
                    side=side,
                    qty=abs_qty,
                    entry_price=entry,
                    entry_timestamp=now,
                    last_price=current,
                )
            )
        return positions

    def get_position(self, symbol: str) -> Position | None:
        try:
            rows = self._request("GET", f"/v2/positions/{symbol}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        side_text = str(rows.get("side", "long")).lower()
        side = PositionSide.SHORT if side_text == "short" else PositionSide.LONG
        qty = abs(self._parse_float(rows.get("qty")))
        entry = self._parse_float(rows.get("avg_entry_price"))
        current = self._parse_float(rows.get("current_price")) or entry
        now = datetime.now(timezone.utc)
        return Position(
            symbol=str(rows.get("symbol", symbol)),
            side=side,
            qty=qty,
            entry_price=entry,
            entry_timestamp=now,
            last_price=current,
        )

    def mark_price(self, symbol: str, price: float) -> None:
        del symbol
        del price

    def get_realized_pnl(self) -> float:
        return sum(trade.pnl for trade in self.list_closed_trades())

    def get_unrealized_pnl(self) -> float:
        total = 0.0
        for position in self.list_positions():
            if position.side == PositionSide.LONG:
                total += (position.last_price - position.entry_price) * position.qty
            else:
                total += (position.entry_price - position.last_price) * position.qty
        return total

    def list_closed_trades(self) -> list[ClosedTrade]:
        return self._build_closed_trades(self._fetch_fill_activities())

    def reset(self) -> None:
        self._orders.clear()
