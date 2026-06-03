"""Point-in-time S&P 500 universe — the survivorship-bias-FREE membership.

The hardcoded list in `universe.py` is today's survivors: it cannot tell us
whether the Clenow stock-selection adds alpha, because a survivor-only universe
has no losers for momentum to dodge (see ROADMAP [2]). To test fairly we need
the universe *as it was* at each historical date, including the 740+ names that
were later removed/delisted.

Source: fja05680/sp500 — "sp500_ticker_start_end.csv", a community-maintained
point-in-time membership of the S&P 500 back to 1996 (each ticker's first/last
day in the index). MIT-licensed, fetched from raw.githubusercontent (reachable
from the GitHub Actions runner). A cached copy lives in data/ for reproducibility.

  from backtest_us.pit_universe import load_pit_universe
  tickers, eligibility = load_pit_universe()
  # eligibility[t] = (start_ts, end_ts | None)  — listed window for ticker t

Caveat that this does NOT fix: price coverage of delisted names. yfinance drops
delisted tickers; stooq retains many but rate-limits CI. Whatever the price
loader cannot fetch is reported as a coverage gap — an honest, measured limit
rather than a hidden one.
"""
from __future__ import annotations

import os
import urllib.request

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_CSV = os.path.join(DATA_DIR, "sp500_ticker_start_end.csv")
_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "sp500_ticker_start_end.csv"
)
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# S&P 500 tracker — apt benchmark / regime gauge for this universe (longer
# history than QQQ, and it IS the index these names belong to).
PIT_BENCHMARK = "SPY"


def _download_csv() -> None:
    req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    if "ticker" not in raw.splitlines()[0]:
        raise ValueError(f"unexpected membership CSV header: {raw[:80]!r}")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_CSV, "w") as f:
        f.write(raw)


def load_pit_universe(
    refresh: bool = False,
) -> tuple[list[str], dict[str, tuple[pd.Timestamp, pd.Timestamp | None]]]:
    """Return (tickers, eligibility) for the point-in-time S&P 500.

    `eligibility[ticker] = (start_ts, end_ts_or_None)`; end_ts None means the
    name is still in the index. Tickers are normalised to the loader's symbol
    style (dots, not yet stooq-mapped — the data layer handles that).
    """
    if refresh or not os.path.exists(_CSV):
        _download_csv()
    df = pd.read_csv(_CSV)
    df.columns = [c.strip() for c in df.columns]

    eligibility: dict[str, tuple[pd.Timestamp, pd.Timestamp | None]] = {}
    for _, row in df.iterrows():
        t = str(row["ticker"]).strip().upper()
        if not t or t == "NAN":
            continue
        start = pd.to_datetime(row["start_date"])
        end = pd.to_datetime(row["end_date"]) if pd.notna(row["end_date"]) else None
        # A ticker can have multiple spells; keep the widest window (earliest
        # start, and "still in" wins over any end date).
        if t in eligibility:
            p_start, p_end = eligibility[t]
            start = min(start, p_start)
            end = None if (end is None or p_end is None) else max(end, p_end)
        eligibility[t] = (start, end)

    tickers = sorted(eligibility)
    return tickers, eligibility
