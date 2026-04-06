import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict


class CachedAlpacaBars(BaseModel):
    asset_class: str
    symbol: str
    timeframe: str
    stock_feed: str | None
    csv_path: str
    metadata_path: str
    cache_hit: bool
    requested_start: datetime
    requested_end: datetime
    window_start: datetime | None
    window_end: datetime | None
    bars: int

    model_config = ConfigDict(extra="forbid")


def default_alpaca_data_url(asset_class: str) -> str:
    if asset_class == "stocks":
        return "https://data.alpaca.markets/v2/stocks/bars"
    if asset_class == "crypto":
        return "https://data.alpaca.markets/v1beta3/crypto/us/bars"
    raise RuntimeError("asset_class must be 'stocks' or 'crypto'")


def fetch_alpaca_bars(
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


def write_bars_csv(output_path: Path, symbol: str, bars: list[dict]) -> None:
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


def fetch_or_load_cached_bars(
    *,
    api_key: str,
    api_secret: str,
    asset_class: str,
    symbol: str,
    timeframe: str,
    lookback_days: int,
    cache_dir: str | Path,
    stock_feed: str | None = None,
    data_url: str | None = None,
    force_refresh: bool = False,
    end_time: datetime | None = None,
) -> CachedAlpacaBars:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be greater than 0")

    now_utc = end_time or datetime.now(timezone.utc)
    requested_start = now_utc - timedelta(days=lookback_days)
    data_url = data_url or default_alpaca_data_url(asset_class)
    cache_root = Path(cache_dir)

    last_error: str | None = None
    for days in _fallback_lookbacks(lookback_days):
        window_start = now_utc - timedelta(days=days)
        csv_path = _cache_file_path(
            cache_root=cache_root,
            asset_class=asset_class,
            symbol=symbol,
            timeframe=timeframe,
            start=window_start,
            end=now_utc,
            stock_feed=stock_feed,
        )
        metadata_path = csv_path.with_suffix(".json")

        if csv_path.exists() and not force_refresh:
            return _read_cached_metadata(
                csv_path=csv_path,
                metadata_path=metadata_path,
                asset_class=asset_class,
                symbol=symbol,
                timeframe=timeframe,
                stock_feed=stock_feed,
                requested_start=requested_start,
                requested_end=now_utc,
            )

        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }
        with httpx.Client(timeout=30, headers=headers) as client:
            try:
                bars = fetch_alpaca_bars(
                    client=client,
                    data_url=data_url,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=window_start.isoformat().replace("+00:00", "Z"),
                    end=now_utc.isoformat().replace("+00:00", "Z"),
                    stock_feed=stock_feed if asset_class == "stocks" else None,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403 and days != _fallback_lookbacks(lookback_days)[-1]:
                    last_error = f"403 Forbidden for lookback_days={days}"
                    continue
                raise

        if not bars:
            continue

        write_bars_csv(csv_path, symbol=symbol, bars=bars)
        record = CachedAlpacaBars(
            asset_class=asset_class,
            symbol=symbol,
            timeframe=timeframe,
            stock_feed=stock_feed,
            csv_path=str(csv_path.resolve()),
            metadata_path=str(metadata_path.resolve()),
            cache_hit=False,
            requested_start=requested_start,
            requested_end=now_utc,
            window_start=_parse_timestamp(bars[0]["t"]),
            window_end=_parse_timestamp(bars[-1]["t"]),
            bars=len(bars),
        )
        metadata_path.write_text(json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")
        return record

    message = (
        "No Alpaca bars returned for this symbol/timeframe in the selected period. "
        "Try another symbol, timeframe, or lookback window."
    )
    if last_error:
        message = f"{last_error}. {message}"
    raise RuntimeError(message)


def _fallback_lookbacks(lookback_days: int) -> list[int]:
    candidates = [lookback_days]
    for days in (30, 7, 2):
        if days < lookback_days and days not in candidates:
            candidates.append(days)
    return candidates


def _cache_file_path(
    *,
    cache_root: Path,
    asset_class: str,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    stock_feed: str | None,
) -> Path:
    safe_symbol = symbol.replace("/", "_")
    safe_feed = stock_feed or "none"
    filename = (
        f"{asset_class}_{safe_symbol}_{timeframe}_"
        f"{_slugify_timestamp(start)}_{_slugify_timestamp(end)}_{safe_feed}.csv"
    )
    return cache_root / filename


def _read_cached_metadata(
    *,
    csv_path: Path,
    metadata_path: Path,
    asset_class: str,
    symbol: str,
    timeframe: str,
    stock_feed: str | None,
    requested_start: datetime,
    requested_end: datetime,
) -> CachedAlpacaBars:
    if metadata_path.exists():
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        data["cache_hit"] = True
        data["requested_start"] = requested_start
        data["requested_end"] = requested_end
        return CachedAlpacaBars.model_validate(data)

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    first_timestamp = _parse_timestamp(rows[0]["timestamp"]) if rows else None
    last_timestamp = _parse_timestamp(rows[-1]["timestamp"]) if rows else None
    record = CachedAlpacaBars(
        asset_class=asset_class,
        symbol=symbol,
        timeframe=timeframe,
        stock_feed=stock_feed,
        csv_path=str(csv_path.resolve()),
        metadata_path=str(metadata_path.resolve()),
        cache_hit=True,
        requested_start=requested_start,
        requested_end=requested_end,
        window_start=first_timestamp,
        window_end=last_timestamp,
        bars=len(rows),
    )
    metadata_path.write_text(json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")
    return record


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _slugify_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")
