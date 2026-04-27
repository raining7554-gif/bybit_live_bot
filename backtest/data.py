"""Bybit OHLCV + funding rate fetcher with on-disk CSV cache.

Public endpoints, no auth required. Run from a network-enabled environment.
"""
from __future__ import annotations
import os, time
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
import requests

BYBIT_BASE = "https://api.bybit.com"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

INTERVAL_MS = {
    "1": 60_000, "3": 180_000, "5": 300_000, "15": 900_000,
    "30": 1_800_000, "60": 3_600_000, "120": 7_200_000,
    "240": 14_400_000, "360": 21_600_000, "720": 43_200_000,
    "D": 86_400_000, "W": 604_800_000,
}


def _kline_path(symbol: str, interval: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")


def _funding_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_funding.csv")


def fetch_kline(symbol: str, interval: str, start_ms: int, end_ms: int,
                category: str = "linear") -> pd.DataFrame:
    """Pull OHLCV in 1000-bar chunks. Returns DataFrame indexed by UTC datetime."""
    step = INTERVAL_MS[interval] * 1000
    rows = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "start": cur,
            "end": min(cur + step, end_ms),
            "limit": 1000,
        }
        r = requests.get(f"{BYBIT_BASE}/v5/market/kline", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()["result"]["list"]
        if not data:
            cur += step
            continue
        rows.extend(data)
        last_ts = int(data[0][0])
        cur = last_ts + INTERVAL_MS[interval]
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    df = df.astype({"ts": "int64", "open": float, "high": float, "low": float,
                    "close": float, "volume": float, "turnover": float})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("dt")


def load_kline(symbol: str, interval: str, days: int = 365,
               refresh: bool = False) -> pd.DataFrame:
    """Cached load. Refreshes if missing or `refresh=True`."""
    path = _kline_path(symbol, interval)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    if not refresh and os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["dt"], index_col="dt")
        if len(df) > 0 and (df.index[-1].timestamp() * 1000 > end_ms - 2 * INTERVAL_MS[interval]):
            return df.loc[df.index >= pd.to_datetime(start_ms, unit="ms", utc=True)]
    print(f"[fetch] {symbol} {interval} {days}d ...")
    df = fetch_kline(symbol, interval, start_ms, end_ms)
    if len(df) > 0:
        df.to_csv(path)
    return df


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Historical funding rates (8h cadence). Bybit returns latest first."""
    rows = []
    cur_end = end_ms
    while cur_end > start_ms:
        params = {
            "category": "linear",
            "symbol": symbol,
            "startTime": start_ms,
            "endTime": cur_end,
            "limit": 200,
        }
        r = requests.get(f"{BYBIT_BASE}/v5/market/funding/history", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()["result"]["list"]
        if not data:
            break
        rows.extend(data)
        oldest_ts = int(data[-1]["fundingRateTimestamp"])
        if oldest_ts <= start_ms:
            break
        cur_end = oldest_ts - 1
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = df["fundingRateTimestamp"].astype("int64")
    df["rate"] = df["fundingRate"].astype(float)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["dt", "ts", "rate"]].drop_duplicates("ts").sort_values("ts").set_index("dt")


def load_funding(symbol: str, days: int = 365, refresh: bool = False) -> pd.DataFrame:
    path = _funding_path(symbol)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    if not refresh and os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["dt"], index_col="dt")
        if len(df) > 0:
            return df.loc[df.index >= pd.to_datetime(start_ms, unit="ms", utc=True)]
    print(f"[fetch funding] {symbol} {days}d ...")
    df = fetch_funding(symbol, start_ms, end_ms)
    if len(df) > 0:
        df.to_csv(path)
    return df
