import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _default_data_url(asset_class: str) -> str:
    if asset_class == "stocks":
        return "https://data.alpaca.markets/v2/stocks/bars"
    if asset_class == "crypto":
        return "https://data.alpaca.markets/v1beta3/crypto/us/bars"
    raise RuntimeError("ALPACA_ASSET_CLASS must be 'stocks' or 'crypto'")


def _fetch_bars(
    client: httpx.Client,
    data_url: str,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    stock_feed: str | None = None,
) -> list[dict]:
    bars: list[dict] = []
    page_token: str | None = None

    while True:
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": 10000,
            "sort": "asc",
        }
        if stock_feed:
            params["feed"] = stock_feed
        if page_token:
            params["page_token"] = page_token

        response = client.get(data_url, params=params)
        response.raise_for_status()

        body = response.json()
        batch = body.get("bars", {}).get(symbol, [])
        if batch:
            bars.extend(batch)

        page_token = body.get("next_page_token")
        if not page_token:
            break

    return bars


def _write_csv(output_path: Path, symbol: str, bars: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar["t"],
                    symbol,
                    bar["o"],
                    bar["h"],
                    bar["l"],
                    bar["c"],
                    bar.get("v", 0),
                ]
            )


def main() -> None:
    api_key = _required_env("ALPACA_API_KEY")
    api_secret = _required_env("ALPACA_API_SECRET")

    asset_class = os.getenv("ALPACA_ASSET_CLASS", "stocks").lower()
    symbol = os.getenv("SYMBOL", "AAPL")
    timeframe = os.getenv("ALPACA_BAR_TIMEFRAME", "5Min")
    lookback_days = int(os.getenv("VALIDATION_LOOKBACK_DAYS", "7"))
    stock_feed = os.getenv("VALIDATION_STOCK_FEED", "iex").strip() or None

    data_url = os.getenv("VALIDATION_ALPACA_DATA_URL", _default_data_url(asset_class))
    output_dir = Path(os.getenv("VALIDATION_OUTPUT_DIR", "data/validation"))
    report_output_dir = os.getenv("VALIDATION_REPORT_OUTPUT_DIR", "reports/backtests")
    report_period = os.getenv("VALIDATION_REPORT_PERIOD", "day")
    api_base_url = os.getenv("VALIDATION_API_BASE_URL", "http://127.0.0.1:8000")
    initial_capital = float(os.getenv("VALIDATION_INITIAL_CAPITAL", "10000"))

    qty_raw = os.getenv("VALIDATION_QTY", "")
    qty = float(qty_raw) if qty_raw else None

    now_utc = datetime.now(timezone.utc)

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    print("Fetching Alpaca bars for validation...")
    print(
        f"asset_class={asset_class} symbol={symbol} timeframe={timeframe} "
        f"lookback_days={lookback_days} initial_capital={initial_capital}"
    )
    print("Validation mode is local only: no orders will be sent to the Alpaca paper account.")

    bars: list[dict] = []
    candidates: list[int] = [lookback_days]
    if lookback_days > 7:
        candidates.append(7)
    if lookback_days > 2:
        candidates.append(2)

    with httpx.Client(timeout=30, headers=headers) as alpaca_client:
        last_error: str | None = None
        for days in candidates:
            start_utc = now_utc - timedelta(days=days)
            try:
                bars = _fetch_bars(
                    client=alpaca_client,
                    data_url=data_url,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start_utc.isoformat().replace("+00:00", "Z"),
                    end=now_utc.isoformat().replace("+00:00", "Z"),
                    stock_feed=stock_feed if asset_class == "stocks" else None,
                )
                if bars:
                    if days != lookback_days:
                        print(f"Fallback succeeded with lookback_days={days}")
                    break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    last_error = f"403 Forbidden for lookback_days={days}"
                    print(f"{last_error}. Trying shorter lookback...")
                    continue
                raise

        if not bars and last_error:
            print(last_error)

    if not bars:
        print(
            "No bars returned from Alpaca for this symbol/timeframe in the selected period. "
            "Try another symbol (e.g. AAPL) or increase VALIDATION_LOOKBACK_DAYS."
        )
        sys.exit(2)

    safe_symbol = symbol.replace("/", "_")
    csv_path = output_dir / f"alpaca_{asset_class}_{safe_symbol}_{timeframe}.csv"
    _write_csv(csv_path, symbol, bars)
    print(f"Saved {len(bars)} bars to {csv_path}")

    payload: dict[str, object] = {
        "csv_path": str(csv_path),
        "period": report_period,
        "output_dir": report_output_dir,
        "initial_capital": initial_capital,
    }
    if qty is not None:
        payload["qty"] = qty

    print("Running local backtest report...")
    with httpx.Client(timeout=60) as local_client:
        response = local_client.post(f"{api_base_url}/v1/backtest/report", json=payload)
        response.raise_for_status()
        report = response.json()

    summary = report.get("summary", {})
    metrics = summary.get("metrics", {})
    diagnostics = report.get("diagnostics", {})

    print("\n=== Validation Result ===")
    print(f"candles={summary.get('total_candles')} action_signals={summary.get('action_signals')}")
    print(f"filled_orders={summary.get('filled_orders')} rejected_orders={summary.get('rejected_orders')}")
    print(
        f"initial_capital={summary.get('initial_capital')} "
        f"win_rate={metrics.get('win_rate')} net_profit={metrics.get('net_profit')}"
    )
    print(f"max_drawdown={metrics.get('max_drawdown')} max_drawdown_pct={metrics.get('max_drawdown_pct')}")
    print(f"equity_curve_csv_path={report.get('equity_curve_csv_path')}")

    grouped = report.get("grouped_metrics", [])
    print(f"grouped_rows={len(grouped)}")

    print("\n=== Rule Diagnostics ===")
    for row in diagnostics.get("rule_pass_rates", []):
        print(f"{row.get('rule')}: pass_rate={row.get('pass_rate'):.2f}% ({row.get('passed')}/{row.get('total')})")
    print(f"buy_all_rules_passed_count={diagnostics.get('buy_all_rules_passed_count')}")
    print(f"sell_all_rules_passed_count={diagnostics.get('sell_all_rules_passed_count')}")

    report_json_path = output_dir / f"alpaca_{asset_class}_{safe_symbol}_{timeframe}_report.json"
    report_json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"report_json_path={report_json_path}")


if __name__ == "__main__":
    main()
