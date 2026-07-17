"""Fetch public Binance USD-M funding settlements and 4H mark-price bars.

The output is generated research data and belongs under ``data/derivatives``.
No API key is required.  Pagination is explicit so the resulting funding
ledger covers the same frozen window as the OHLCV audit snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd


BASE_URL = "https://fapi.binance.com"
ARCHIVE_URL = "https://data.binance.vision/data/futures/um/monthly"


def _get_json(path: str, params: dict[str, object]) -> object:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{BASE_URL}{path}?{query}",
        headers={"User-Agent": "Quant-for-BTC-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_funding(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    while cursor <= end_ms:
        payload = _get_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
        )
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(payload)
        next_cursor = int(payload[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"funding pagination stalled for {symbol}")
        cursor = next_cursor
        time.sleep(0.05)

    if not rows:
        raise RuntimeError(f"no funding history returned for {symbol}")
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("fundingTime"), unit="ms", utc=True)
    frame = frame.rename(
        columns={"fundingRate": "funding_rate", "markPrice": "funding_mark_price"}
    )
    frame = frame[["funding_rate", "funding_mark_price"]].apply(pd.to_numeric)
    return frame.loc[~frame.index.duplicated(keep="last")].sort_index()


def fetch_mark_bars(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows: list[list[object]] = []
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    while cursor <= end_ms:
        payload = _get_json(
            "/fapi/v1/markPriceKlines",
            {
                "symbol": symbol,
                "interval": "4h",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1500,
            },
        )
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(payload)
        next_cursor = int(payload[-1][0]) + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"mark-price pagination stalled for {symbol}")
        cursor = next_cursor
        time.sleep(0.05)

    if not rows:
        raise RuntimeError(f"no mark-price history returned for {symbol}")
    frame = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "MarkOpen",
            "MarkHigh",
            "MarkLow",
            "MarkClose",
            "ignore_1",
            "close_time",
            "ignore_2",
            "ignore_3",
            "ignore_4",
            "ignore_5",
            "ignore_6",
        ],
    )
    frame.index = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
    frame = frame[["MarkOpen", "MarkHigh", "MarkLow", "MarkClose"]].apply(pd.to_numeric)
    return frame.loc[~frame.index.duplicated(keep="last")].sort_index()


def _month_keys(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(period) for period in pd.period_range(start=start, end=end, freq="M")]


def _read_archive_csv(url: str) -> pd.DataFrame | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Quant-for-BTC-research/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise RuntimeError(f"expected one CSV in {url}, found {names}")
        with archive.open(names[0]) as handle:
            return pd.read_csv(handle)


def _archive_frames(urls: list[str]) -> list[pd.DataFrame]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = list(pool.map(_read_archive_csv, urls))
    return [frame for frame in frames if frame is not None and not frame.empty]


def fetch_archive_funding(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    urls = [
        f"{ARCHIVE_URL}/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
        for month in _month_keys(start, end)
    ]
    frames = _archive_frames(urls)
    if not frames:
        raise RuntimeError(f"no archived funding history returned for {symbol}")
    frame = pd.concat(frames, ignore_index=True)
    frame.index = pd.to_datetime(frame.pop("calc_time"), unit="ms", utc=True)
    frame = frame.rename(columns={"last_funding_rate": "funding_rate"})
    frame["funding_rate"] = pd.to_numeric(frame["funding_rate"])
    frame = frame[["funding_rate"]].loc[~frame.index.duplicated(keep="last")].sort_index()
    return frame.loc[(frame.index >= start) & (frame.index <= end)]


def fetch_archive_mark_bars(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    urls = [
        f"{ARCHIVE_URL}/markPriceKlines/{symbol}/4h/{symbol}-4h-{month}.zip"
        for month in _month_keys(start, end)
    ]
    frames = _archive_frames(urls)
    if not frames:
        raise RuntimeError(f"no archived mark-price history returned for {symbol}")
    frame = pd.concat(frames, ignore_index=True)
    frame.index = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
    frame = frame.rename(
        columns={"open": "MarkOpen", "high": "MarkHigh", "low": "MarkLow", "close": "MarkClose"}
    )
    frame = frame[["MarkOpen", "MarkHigh", "MarkLow", "MarkClose"]].apply(pd.to_numeric)
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
    return frame.loc[(frame.index >= start) & (frame.index <= end)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-06-30T23:59:59Z")
    parser.add_argument("--source", choices=("archive", "rest"), default="archive")
    parser.add_argument("--output", type=Path, default=Path("data/derivatives"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "source": f"Binance public USD-M {args.source}",
        "start": str(start),
        "end": str(end),
        "symbols": {},
    }
    for symbol in args.symbols.split(","):
        if args.source == "archive":
            funding = fetch_archive_funding(symbol, start, end)
            marks = fetch_archive_mark_bars(symbol, start, end)
        else:
            funding = fetch_funding(symbol, start, end)
            marks = fetch_mark_bars(symbol, start, end)
        funding_path = args.output / f"{symbol}_funding.csv"
        mark_path = args.output / f"{symbol}_mark_4h.csv"
        funding.to_csv(funding_path)
        marks.to_csv(mark_path)
        manifest["symbols"][symbol] = {
            "funding": {
                "path": str(funding_path),
                "rows": len(funding),
                "start": str(funding.index.min()),
                "end": str(funding.index.max()),
                "sha256": _sha256(funding_path),
            },
            "mark_4h": {
                "path": str(mark_path),
                "rows": len(marks),
                "start": str(marks.index.min()),
                "end": str(marks.index.max()),
                "sha256": _sha256(mark_path),
            },
        }
        print(symbol, len(funding), len(marks))
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
