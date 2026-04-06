import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _asset_defaults(asset_class: str) -> tuple[str, str]:
    if asset_class == "stocks":
        return "AAPL", "https://data.alpaca.markets/v2/stocks/bars"
    if asset_class == "crypto":
        return "BTC/USD", "https://data.alpaca.markets/v1beta3/crypto/us/bars"
    raise RuntimeError("ALPACA_ASSET_CLASS must be 'stocks' or 'crypto'")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def _as_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _safe_name(value: str) -> str:
    return value.replace("/", "_").replace(" ", "_")


def _derive_api_base_url(api_ingest_url: str) -> str:
    marker = "/v1/candles"
    if api_ingest_url.endswith(marker):
        return api_ingest_url[: -len(marker)]
    raise RuntimeError("API_INGEST_URL must end with /v1/candles so the collector can query runtime state.")


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _fetch_runtime_state(client: httpx.Client, api_base_url: str) -> dict:
    health = client.get(f"{api_base_url}/health")
    health.raise_for_status()

    orders = client.get(f"{api_base_url}/v1/orders")
    orders.raise_for_status()

    positions = client.get(f"{api_base_url}/v1/positions")
    positions.raise_for_status()

    trades = client.get(f"{api_base_url}/v1/trades")
    trades.raise_for_status()

    order_rows = orders.json()
    position_rows = positions.json()
    trade_rows = trades.json()
    return {
        "health": health.json(),
        "orders_total": len(order_rows),
        "positions_total": len(position_rows),
        "closed_trades_total": len(trade_rows),
        "last_order": order_rows[-1] if order_rows else None,
        "positions": position_rows,
        "closed_trades": trade_rows,
    }


def _build_run_dir(root: Path, *, symbol: str, timeframe: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / f"{timestamp}_{_safe_name(symbol)}_{_safe_name(timeframe)}"


def main() -> None:
    asset_class = os.getenv("ALPACA_ASSET_CLASS", "stocks").lower()
    default_symbol, default_data_url = _asset_defaults(asset_class)

    symbol = os.getenv("SYMBOL", default_symbol)
    timeframe = os.getenv("ALPACA_BAR_TIMEFRAME", "5Min")
    api_ingest_url = os.getenv("API_INGEST_URL", "http://127.0.0.1:8000/v1/candles")
    api_base_url = os.getenv("API_BASE_URL", "").strip() or _derive_api_base_url(api_ingest_url)
    alpaca_data_url = os.getenv("ALPACA_DATA_URL", default_data_url)
    poll_interval = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))
    no_data_warn_every = int(os.getenv("NO_DATA_WARN_EVERY_POLLS", "12"))
    unchanged_warn_every = int(os.getenv("UNCHANGED_BAR_WARN_EVERY_POLLS", "12"))
    capture_enabled = _as_bool(os.getenv("STREAM_CAPTURE_ENABLED"), default=True)
    capture_root = Path(os.getenv("STREAM_CAPTURE_ROOT", "data/paper_runs"))
    max_new_bars = _as_int(os.getenv("MAX_NEW_BARS"))
    max_runtime_seconds = _as_float(os.getenv("MAX_RUNTIME_SECONDS"))
    order_qty = _as_float(os.getenv("STREAM_ORDER_QTY"))
    run_dir = _build_run_dir(capture_root, symbol=symbol, timeframe=timeframe)
    events_path = run_dir / "events.jsonl"
    latest_state_path = run_dir / "latest_state.json"
    manifest_path = run_dir / "manifest.json"

    if alpaca_data_url.rstrip("/").endswith("/latest"):
        raise RuntimeError(
            "ALPACA_DATA_URL is pointing to a /latest endpoint, which is incompatible with "
            "ALPACA_BAR_TIMEFRAME. Use the bars endpoint instead, for example: "
            "https://data.alpaca.markets/v2/stocks/bars"
        )

    headers = {
        "APCA-API-KEY-ID": _required_env("ALPACA_API_KEY"),
        "APCA-API-SECRET-KEY": _required_env("ALPACA_API_SECRET"),
    }

    print(f"Starting real-price stream for {symbol} ({asset_class}, timeframe={timeframe})")
    print(f"Alpaca data endpoint: {alpaca_data_url}")
    print(f"API ingest endpoint: {api_ingest_url}")
    print(f"API base endpoint: {api_base_url}")
    if capture_enabled:
        print(f"Capture directory: {run_dir}")

    last_ts = None
    no_data_polls = 0
    unchanged_polls = 0
    processed_new_bars = 0
    started_at = time.time()
    with httpx.Client(timeout=20) as client:
        initial_state = _fetch_runtime_state(client, api_base_url)
        if capture_enabled:
            _write_json(
                manifest_path,
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "asset_class": asset_class,
                    "api_ingest_url": api_ingest_url,
                    "api_base_url": api_base_url,
                    "alpaca_data_url": alpaca_data_url,
                    "poll_interval_seconds": poll_interval,
                    "stream_order_qty": order_qty,
                    "operational_params_path": os.getenv("OPERATIONAL_PARAMS_PATH", ""),
                    "initial_state": initial_state,
                },
            )
            _write_json(latest_state_path, initial_state)

        while True:
            if max_runtime_seconds is not None and time.time() - started_at >= max_runtime_seconds:
                print(f"Stopping after reaching MAX_RUNTIME_SECONDS={max_runtime_seconds}.")
                break

            response = client.get(
                alpaca_data_url,
                params={
                    "symbols": symbol,
                    "timeframe": timeframe,
                    "limit": 1,
                    "sort": "desc",
                },
                headers=headers,
            )
            response.raise_for_status()

            bars = response.json().get("bars", {})
            raw_symbol_bars = bars.get(symbol)
            if not raw_symbol_bars:
                no_data_polls += 1
                if no_data_polls == 1 or no_data_polls % no_data_warn_every == 0:
                    print(
                        f"No bars returned for symbol={symbol} in Alpaca ({asset_class}, {timeframe}). "
                        "Still polling..."
                    )
                time.sleep(poll_interval)
                continue

            no_data_polls = 0
            if isinstance(raw_symbol_bars, list):
                bar = raw_symbol_bars[-1]
            else:
                bar = raw_symbol_bars

            if bar["t"] != last_ts:
                unchanged_polls = 0
                payload = {
                    "symbol": symbol,
                    "timestamp": bar["t"],
                    "open": bar["o"],
                    "high": bar["h"],
                    "low": bar["l"],
                    "close": bar["c"],
                    "volume": bar.get("v", 0),
                }
                if order_qty is not None:
                    payload["qty"] = order_qty

                out = client.post(api_ingest_url, json=payload)
                out.raise_for_status()
                body = out.json()
                runtime_state = _fetch_runtime_state(client, api_base_url)
                signal_type = body.get("signal", {}).get("signal_type", "UNKNOWN")
                print(payload["timestamp"], payload["close"], signal_type)

                if capture_enabled:
                    event = {
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "candle": payload,
                        "result": body,
                        "runtime_state": runtime_state,
                    }
                    _append_jsonl(events_path, event)
                    latest_payload = {
                        "last_event": event,
                        "runtime_state": runtime_state,
                    }
                    _write_json(latest_state_path, latest_payload)

                last_ts = bar["t"]
                processed_new_bars += 1
                if max_new_bars is not None and processed_new_bars >= max_new_bars:
                    print(f"Stopping after reaching MAX_NEW_BARS={max_new_bars}.")
                    break
            else:
                unchanged_polls += 1
                if unchanged_polls == 1 or unchanged_polls % unchanged_warn_every == 0:
                    print(
                        f"No new {timeframe} bar yet for {symbol}. "
                        f"Latest bar is still {bar['t']} at close={bar['c']}."
                    )

            time.sleep(poll_interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"Stream failed: {exc}")
