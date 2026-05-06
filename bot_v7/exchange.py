"""Bybit API wrapper with retry + cached OHLCV.

All calls return safe defaults on error (no exceptions propagate). Sets
leverage dynamically per-entry and ALWAYS attaches a server-side disaster SL.
"""
from __future__ import annotations
import time
from typing import Optional
import pandas as pd
from pybit.unified_trading import HTTP

from . import config as cfg


# Lazily initialized session
_session: Optional[HTTP] = None


def session() -> HTTP:
    global _session
    if _session is None:
        _session = HTTP(
            testnet=cfg.TESTNET,
            api_key=cfg.API_KEY,
            api_secret=cfg.API_SECRET,
            max_retries=3,
            retry_delay=5,
            timeout=10,
        )
    return _session


def get_balance() -> float:
    try:
        r = session().get_wallet_balance(accountType="UNIFIED")
        return float(r["result"]["list"][0]["totalEquity"])
    except Exception as e:
        print(f"[balance err] {e}", flush=True)
        return 0.0


def get_price(symbol: str) -> float:
    try:
        r = session().get_tickers(category="linear", symbol=symbol)
        return float(r["result"]["list"][0]["lastPrice"])
    except Exception:
        return 0.0


def get_ohlcv(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    try:
        r = session().get_kline(category="linear", symbol=symbol,
                                interval=interval, limit=limit)
        rows = r["result"]["list"]
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low",
                                         "close", "volume", "turnover"])
        df = df.astype({"ts": "int64", "open": float, "high": float,
                        "low": float, "close": float, "volume": float})
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.iloc[::-1].reset_index(drop=True)
        return df.set_index("dt")
    except Exception as e:
        print(f"[ohlcv err {symbol} {interval}] {e}", flush=True)
        return pd.DataFrame()


def get_open_positions(symbol: str) -> Optional[dict]:
    """Return dict for the single symbol position, or None."""
    try:
        r = session().get_positions(category="linear", symbol=symbol)
        for p in r["result"]["list"]:
            if float(p.get("size", 0)) > 0:
                return {
                    "side":  p["side"],     # 'Buy' or 'Sell'
                    "size":  float(p["size"]),
                    "entry": float(p["avgPrice"]),
                    "pnl":   float(p["unrealisedPnl"]),
                }
        return None
    except Exception as e:
        print(f"[positions err] {e}", flush=True)
        return None


def set_leverage(symbol: str, leverage: float) -> bool:
    """Set per-symbol leverage. No-op if same as current."""
    try:
        session().set_leverage(
            category="linear", symbol=symbol,
            buyLeverage=str(leverage), sellLeverage=str(leverage)
        )
        return True
    except Exception as e:
        # 110043 = leverage not modified (same value) — benign
        msg = str(e)
        if "110043" in msg or "not modified" in msg:
            return True
        print(f"[set_leverage err] {e}", flush=True)
        return False


def _round_qty(symbol: str, qty: float) -> float:
    return round(qty, cfg.QTY_DECIMALS.get(symbol, 2))


def _round_price(symbol: str, price: float) -> float:
    return round(price, cfg.PRICE_DECIMALS.get(symbol, 2))


def place_market_order(symbol: str, side: str, qty: float,
                       disaster_sl_price: float) -> tuple[bool, str]:
    """Market entry with server-side disaster SL. Returns (ok, msg)."""
    try:
        qty = _round_qty(symbol, qty)
        if qty <= 0:
            return False, "qty<=0"
        sl_price = _round_price(symbol, disaster_sl_price)
        idx = 0  # one_way
        kwargs = dict(
            category="linear", symbol=symbol,
            side=side, orderType="Market",
            qty=str(qty), positionIdx=idx,
            stopLoss=str(sl_price),
        )
        r = session().place_order(**kwargs)
        if r.get("retCode") == 0:
            return True, r.get("result", {}).get("orderId", "")
        return False, str(r)
    except Exception as e:
        return False, str(e)


def close_position_market(symbol: str, side_open: str, qty: float) -> bool:
    """Close existing position with reduce-only market order."""
    close_side = "Sell" if side_open == "Buy" else "Buy"
    try:
        r = session().place_order(
            category="linear", symbol=symbol,
            side=close_side, orderType="Market",
            qty=str(_round_qty(symbol, qty)),
            positionIdx=0,
            reduceOnly=True,
        )
        return r.get("retCode") == 0
    except Exception as e:
        print(f"[close err] {e}", flush=True)
        return False


def partial_close_market(symbol: str, side_open: str, partial_qty: float) -> bool:
    """Reduce-only market order for a fraction of the open position.
    Used by mid-tier TP1 (50% scale-out)."""
    close_side = "Sell" if side_open == "Buy" else "Buy"
    qty = _round_qty(symbol, partial_qty)
    if qty <= 0:
        return False
    try:
        r = session().place_order(
            category="linear", symbol=symbol,
            side=close_side, orderType="Market",
            qty=str(qty),
            positionIdx=0,
            reduceOnly=True,
        )
        return r.get("retCode") == 0
    except Exception as e:
        print(f"[partial close err] {e}", flush=True)
        return False


def update_stop_loss(symbol: str, side_open: str, new_sl_price: float) -> bool:
    """Update server-side trailing stop. side_open is the original side ('Buy'/'Sell')."""
    try:
        r = session().set_trading_stop(
            category="linear", symbol=symbol,
            stopLoss=str(_round_price(symbol, new_sl_price)),
            positionIdx=0,
        )
        return r.get("retCode") == 0
    except Exception as e:
        msg = str(e)
        if "34040" in msg or "not modified" in msg:
            return True
        print(f"[update SL err] {e}", flush=True)
        return False


# ─── OHLCV cache ───────────────────────────────────────────────
_cache: dict[tuple[str, str], tuple[pd.DataFrame, float]] = {}
_CACHE_TTL = {"15": cfg.CACHE_15M_SEC, "60": cfg.CACHE_1H_SEC,
              "240": cfg.CACHE_4H_SEC}

# v14: 펀딩 레이트 캐시 (8시간 funding interval, 30분 캐시)
_funding_cache: dict[str, tuple[float, float]] = {}
_FUNDING_CACHE_TTL = 1800  # 30분


def get_funding_rate(symbol: str) -> Optional[float]:
    """현재 8시간 펀딩 레이트 (소수점 비율, 예: 0.0001 = 0.01%/8h).

    None 반환 = 조회 실패. 신호 점수 계산시 None 이면 페널티 없음 (보수적).
    """
    now = time.time()
    if symbol in _funding_cache:
        rate, ts = _funding_cache[symbol]
        if now - ts < _FUNDING_CACHE_TTL:
            return rate
    try:
        r = session().get_funding_rate_history(
            category="linear", symbol=symbol, limit=1,
        )
        rows = r.get("result", {}).get("list", [])
        if rows:
            rate = float(rows[0].get("fundingRate", 0))
            _funding_cache[symbol] = (rate, now)
            return rate
    except Exception as e:
        print(f"[funding {symbol}] err: {e}", flush=True)
    return None


def get_ohlcv_cached(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    now = time.time()
    key = (symbol, interval)
    if key in _cache:
        df, ts = _cache[key]
        if now - ts < _CACHE_TTL.get(interval, 30):
            return df
    df = get_ohlcv(symbol, interval, limit)
    if len(df) > 0:
        _cache[key] = (df, now)
    return df


def init():
    """Force session init + log readiness."""
    s = session()
    print(f"[v7 exchange] session ready (testnet={cfg.TESTNET})", flush=True)
    return s
