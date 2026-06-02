"""NASDAQ / large-cap US stock universe for cross-sectional momentum.

Tickers reused from kis/scanner_overseas.py (the live bot's universe), with
ETFs split out: individual stocks form the tradable universe, QQQ is the
benchmark / regime gauge.

Regenerate periodically (quarterly) — momentum universes drift as names
enter/leave the index. Keep it broad; the alpha + liquidity filter selects.
"""
from __future__ import annotations

# Benchmark / regime gauge (NASDAQ-100 proxy).
BENCHMARK = "QQQ"

# ETFs to exclude from the stock universe (they are not single-name momentum
# candidates; QQQ/SPY are used as benchmark/regime instead).
_ETFS = {
    "QQQ", "SPY", "ARKK", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLP", "XLY", "IWM", "DIA", "GLD",
}

# Full candidate pool (mirrors the live scanner). Cross-sectional rank + the
# liquidity/price filter in data.py decides what is actually held.
_RAW = [
    "NVDA", "MSFT", "GOOGL", "GOOG", "META", "AAPL", "AMZN", "TSLA", "NFLX",
    "AVGO", "AMD", "TSM", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC",
    "ASML", "ARM", "MRVL", "ON", "ADI", "MCHP", "NXPI", "SMCI", "STM",
    "ORCL", "CRM", "ADBE", "NOW", "INTU", "PANW", "CRWD", "ZS", "DDOG",
    "ANET", "SNOW", "FTNT", "MDB", "NET", "OKTA", "WDAY", "TEAM", "TTD",
    "GTLB", "PLTR", "COIN", "SHOP", "UBER", "ABNB", "PYPL", "SQ", "ROKU",
    "HOOD", "AFRM", "SOFI", "RBLX", "JPM", "BAC", "WFC", "GS", "MS", "V",
    "MA", "AXP", "SCHW", "BLK", "VRTX", "REGN", "ISRG", "MRNA", "LLY", "JNJ",
    "UNH", "PFE", "ABBV", "MRK", "TMO", "DHR", "AMGN", "GILD", "SBUX", "NKE",
    "DIS", "WMT", "COST", "MCD", "HD", "LOW", "PG", "KO", "PEP", "TGT",
    "BKNG", "MAR", "F", "GM", "RIVN", "LCID", "BA", "CAT", "GE", "RTX",
    "LMT", "DE", "T", "VZ", "TMUS", "CMCSA", "XOM", "CVX", "OXY", "DELL",
    "HPQ", "IBM", "CSCO", "ADSK", "CDNS", "SNPS", "ANSS", "ROP", "FSLR",
    "ENPH", "PLUG", "CHWY", "PINS", "SNAP", "SPOT", "CPNG", "BIIB", "ILMN",
    "BMY", "CI", "CVS", "ELV", "HUM", "MCK", "HON", "UPS", "FDX", "MMM",
    "EMR", "ETN", "ITW", "FCX", "NEM", "AMT", "PLD", "EQIX", "PATH", "DOCN",
    "BILL", "TWLO", "RDDT", "APP", "DASH",
]

# Tradable single-name universe (ETFs removed, de-duplicated, order preserved).
UNIVERSE: list[str] = list(dict.fromkeys(t for t in _RAW if t not in _ETFS))


def stooq_symbol(ticker: str) -> str:
    """Map a US ticker to stooq's symbol convention, e.g. AAPL -> aapl.us."""
    return f"{ticker.lower().replace('.', '-')}.us"
