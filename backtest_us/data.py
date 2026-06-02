"""US daily OHLCV loader — yfinance (primary) + stooq (fallback), CSV cache.

Why two sources: stooq is simple but rate-limits cloud/CI IPs (returns a limit
message instead of CSV). yfinance (Yahoo) is reliable from GitHub runners and
gives split/dividend-adjusted prices (auto_adjust), which matters for momentum.

  from backtest_us.data import load_prices
  prices = load_prices(["AAPL", "MSFT"])     # dict[ticker] -> OHLCV DataFrame

The CSV cache (backtest_us/data/*.csv) makes every later backtest fully offline
& reproducible. For engine dev without network use make_synthetic_prices().
"""
from __future__ import annotations

import io
import os
import time
import urllib.request

import numpy as np
import pandas as pd

from .universe import stooq_symbol

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_COLS = ["open", "high", "low", "close", "volume"]


def _csv_path(ticker: str) -> str:
    return os.path.join(DATA_DIR, f"{ticker.upper()}.csv")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case OHLCV columns, datetime index named 'date', sorted, no NaN rows."""
    df = df.rename(columns={c: c.lower() for c in df.columns})
    keep = [c for c in _COLS if c in df.columns]
    df = df[keep].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df.dropna(how="all").sort_index().astype(float)


# ── yfinance (primary) ────────────────────────────────────────────────
def fetch_yfinance_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Batch-download adjusted daily history for many tickers via yfinance."""
    import yfinance as yf  # imported lazily so synthetic/test mode needs no install

    out: dict[str, pd.DataFrame] = {}
    data = yf.download(
        tickers, period="max", interval="1d", auto_adjust=True,
        group_by="ticker", progress=False, threads=True,
    )
    if data is None or len(data) == 0:
        return out
    multi = isinstance(data.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = data[t] if multi else data
            df = _normalize(df)
            if len(df) > 50:
                out[t] = df
        except (KeyError, ValueError):
            continue
    return out


# ── stooq (fallback) ──────────────────────────────────────────────────
def fetch_stooq(ticker: str, timeout: int = 15) -> pd.DataFrame:
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol(ticker)}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
    head = raw.strip().lower()
    # stooq returns a plain-text limit/error message instead of CSV when throttled.
    if not head or head.startswith("<") or not head.startswith("date,"):
        raise ValueError(f"{ticker}: non-CSV stooq response ({raw.strip()[:60]!r})")
    df = pd.read_csv(io.StringIO(raw))
    return _normalize(df)


def load_prices(
    tickers: list[str],
    refresh: bool = False,
    verbose: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for many tickers: cache → yfinance batch → stooq fallback.

    Failures are skipped (not fatal). Successful downloads are cached as CSV.
    """
    out: dict[str, pd.DataFrame] = {}
    need: list[str] = []
    for t in tickers:
        path = _csv_path(t)
        if not refresh and os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(df) > 0:
                out[t] = df
                continue
        need.append(t)

    if not need:
        return out

    # Primary: yfinance, chunked to keep each request modest.
    fetched: dict[str, pd.DataFrame] = {}
    try:
        for i in range(0, len(need), 40):
            chunk = need[i:i + 40]
            got = fetch_yfinance_batch(chunk)
            fetched.update(got)
            if verbose:
                print(f"[data] yfinance {i//40 + 1}: {len(got)}/{len(chunk)} ok")
            time.sleep(1.0)
    except ImportError:
        if verbose:
            print("[data] yfinance not installed — falling back to stooq only")

    # Fallback: stooq for anything yfinance missed.
    for t in need:
        if t in fetched:
            continue
        try:
            fetched[t] = fetch_stooq(t)
            time.sleep(0.3)
        except Exception as e:  # noqa: BLE001 — any failure -> skip this ticker
            if verbose:
                print(f"[data] SKIP {t}: {type(e).__name__} {str(e)[:70]}")

    for t, df in fetched.items():
        df.to_csv(_csv_path(t))
        out[t] = df
    if verbose and fetched:
        any_df = next(iter(fetched.values()))
        print(f"[data] fetched {len(fetched)}/{len(need)} new; "
              f"sample range {any_df.index[0].date()}..{any_df.index[-1].date()}")
    return out


def close_matrix(prices: dict[str, pd.DataFrame], field: str = "close") -> pd.DataFrame:
    cols = {t: df[field] for t, df in prices.items() if field in df.columns}
    return pd.DataFrame(cols).sort_index()


def make_synthetic_prices(
    tickers: list[str],
    days: int = 1500,
    seed: int = 7,
    start: str = "2019-01-01",
) -> dict[str, pd.DataFrame]:
    """Deterministic GBM OHLCV for in-container engine testing (no network)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=days)
    market = rng.normal(0.0003, 0.011, days)
    out: dict[str, pd.DataFrame] = {}
    for k, t in enumerate(tickers):
        drift = 0.0002 + 0.0006 * np.sin(k)
        idio = rng.normal(0, 0.014, days)
        beta = 0.6 + 0.8 * ((k % 5) / 5.0)
        logret = drift + beta * market + idio
        close = 50 * np.exp(np.cumsum(logret))
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
