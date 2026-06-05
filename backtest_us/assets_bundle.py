"""Macro multi-asset price bundle — for genuine cross-asset diversification.

Within US equities, stacking strategies doesn't diversify (ROADMAP [3d]/[3i]:
everything is the same beta, corr ~0.6-0.8). Real diversification comes from
different ASSET CLASSES. This fetches a curated macro set so the regime/trend
engine can run on each and allocate to whatever is actually trending — the
managed-futures approach that genuinely spreads risk.

  python -m backtest_us.assets_bundle --export   # (in CI, network) build bundle
  from backtest_us.assets_bundle import load_assets
  closes = load_assets()                          # date x asset close matrix
"""
from __future__ import annotations

import os
import pandas as pd

from .data import load_prices, close_matrix, BUNDLE_DIR

ASSETS_CSV = os.path.join(BUNDLE_DIR, "assets.csv.gz")

# Curated cross-regime MACRO set (yfinance tickers). Spans risk-on / safe-haven /
# real-assets / crypto so that in any macro regime SOMETHING tends to trend.
# This is the diversified CORE.
MACRO = [
    "SPY", "QQQ", "EEM", "EFA",          # equities (US / growth / EM / intl)
    "TLT", "IEF", "HYG",                 # bonds (long / mid treasury / high-yield)
    "GLD", "SLV", "DBC",                 # gold / silver / broad commodities
    "UUP", "VNQ",                        # US dollar / real estate
    "BTC-USD", "ETH-USD",                # crypto
]

# SECTOR / THEMATIC ETFs — for the momentum-rotation sleeve that LEANS INTO
# whatever sector money is flooding (price = the flow signal). Trend-gated, so a
# hot sector is ridden up and dropped when it breaks its 200-MA.
SECTORS = [
    "SMH", "SOXX",                       # semiconductors (the hot one)
    "XLK", "XLC",                        # tech / communications
    "XLE", "XLF", "XLV", "XLI",          # energy / financials / health / industrials
    "XLY", "XLP", "XLU", "XLB",          # disc / staples / utilities / materials
    "XBI", "GDX", "ARKK",                # biotech / gold miners / innovation
    "TAN", "ICLN",                       # solar / clean energy
]

ASSETS = MACRO + SECTORS                  # full fetch list (one bundle)



def export(refresh: bool = True) -> str:
    prices = load_prices(ASSETS, refresh=refresh)
    cm = close_matrix(prices).round(4)

    # Resilience: a transient yfinance miss must not wipe an asset (esp. SPY, the
    # regime gauge). Merge fresh data over the previously committed bundle so any
    # asset missing this run keeps its last good column.
    if os.path.exists(ASSETS_CSV):
        prev = pd.read_csv(ASSETS_CSV, index_col=0, parse_dates=True)
        cm = cm.combine_first(prev) if len(cm) else prev
        for c in prev.columns:
            if c not in cm.columns:
                cm[c] = prev[c]
        cm = cm.sort_index()

    os.makedirs(BUNDLE_DIR, exist_ok=True)
    cm.to_csv(ASSETS_CSV)
    got = [c for c in cm.columns]
    print(f"[assets] exported {ASSETS_CSV}: {len(got)} assets — {', '.join(got)}")
    miss = [a for a in ASSETS if a not in got]
    if miss:
        print(f"[assets] MISSING (not fetched): {', '.join(miss)}")
    return ASSETS_CSV


def load_assets() -> pd.DataFrame:
    if not os.path.exists(ASSETS_CSV):
        raise SystemExit(f"no asset bundle at {ASSETS_CSV} — run the "
                         "'Export Multi-Asset Bundle' workflow once.")
    return pd.read_csv(ASSETS_CSV, index_col=0, parse_dates=True)


if __name__ == "__main__":
    import sys
    if "--export" in sys.argv:
        export()
    else:
        cm = load_assets()
        print(cm.tail().round(2).to_string())
