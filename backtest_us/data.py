"""US daily OHLCV loader — stooq source with on-disk CSV cache.

stooq is free and needs no auth, but blocks default user-agents (and some
datacenter IPs). Run the download step from a network-enabled machine (your
Mac); the CSV cache makes every later backtest fully offline & reproducible.

  from backtest_us.data import load_prices
  prices = load_prices(["AAPL", "MSFT"], refresh=False)   # dict[ticker] -> DataFrame

For engine development without network, use make_synthetic_prices() — it
generates deterministic geometric-brownian series so the engine mechanics
(look-ahead, sizing, metrics) can be tested in-container.
"""
from __future__ import annotations

import io
import os
import time
import urllib.request
import urllib.error

import numpy as np
import pandas as pd

from .universe import stooq_symbol

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _csv_path(ticker: str) -> str:
    return os.path.join(DATA_DIR, f"{ticker.upper()}.csv")


def fetch_stooq(ticker: str, timeout: int = 15) -> pd.DataFrame:
    """Download full daily history for one ticker from stooq.

    Returns a DataFrame indexed by date (UTC-naive) with columns
    open/high/low/close/volume. Raises on network/HTTP failure.
    """
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol(ticker)}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
    if not raw.strip() or raw.strip().lower().startswith("<"):
        raise ValueError(f"{ticker}: empty/HTML response from stooq")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{ticker}: unexpected columns {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return df[keep].astype(float)


def load_prices(
    tickers: list[str],
    refresh: bool = False,
    pause: float = 0.3,
    verbose: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for many tickers, using the CSV cache when present.

    Tickers that fail to download (delisted, not on stooq, network) are skipped
    with a warning rather than aborting the whole run.
    """
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        path = _csv_path(t)
        if not refresh and os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(df) > 0:
                out[t] = df
                continue
        try:
            df = fetch_stooq(t)
            df.to_csv(path)
            out[t] = df
            if verbose:
                print(f"[data] {t}: {len(df)} bars {df.index[0].date()}..{df.index[-1].date()}")
            time.sleep(pause)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
            if verbose:
                print(f"[data] SKIP {t}: {type(e).__name__} {str(e)[:80]}")
    return out


def close_matrix(prices: dict[str, pd.DataFrame], field: str = "close") -> pd.DataFrame:
    """Stack per-ticker frames into a single [date x ticker] matrix for one field."""
    cols = {t: df[field] for t, df in prices.items() if field in df.columns}
    mat = pd.DataFrame(cols).sort_index()
    return mat


def make_synthetic_prices(
    tickers: list[str],
    days: int = 1500,
    seed: int = 7,
    start: str = "2019-01-01",
) -> dict[str, pd.DataFrame]:
    """Deterministic GBM OHLCV for in-container engine testing (no network).

    Each ticker gets its own drift so cross-sectional ranking has signal; a
    shared market factor creates correlation so the regime filter is exercised.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=days)
    market = rng.normal(0.0003, 0.011, days)  # common factor (daily log-ret)
    out: dict[str, pd.DataFrame] = {}
    for k, t in enumerate(tickers):
        drift = 0.0002 + 0.0006 * np.sin(k)        # idiosyncratic drift spread
        idio = rng.normal(0, 0.014, days)
        beta = 0.6 + 0.8 * ((k % 5) / 5.0)
        logret = drift + beta * market + idio
        close = 50 * np.exp(np.cumsum(logret))
        # Build OHLC around close with mild intrabar range.
        rngf = np.abs(rng.normal(0, 0.008, days))
        high = close * (1 + rngf)
        low = close * (1 - rngf)
        open_ = np.empty(days)
        open_[0] = close[0]
        open_[1:] = close[:-1] * (1 + rng.normal(0, 0.004, days - 1))
        vol = rng.integers(1_000_000, 10_000_000, days).astype(float)
        out[t] = pd.DataFrame(
            {"open": open_, "high": np.maximum.reduce([high, open_, close]),
             "low": np.minimum.reduce([low, open_, close]), "close": close,
             "volume": vol},
            index=dates,
        )
    return out
