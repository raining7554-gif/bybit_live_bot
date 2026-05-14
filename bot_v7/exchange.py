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


def set_server_trailing(symbol: str, trail_distance: float,
                        activate_price: float | None = None) -> bool:
    """v6.41 A: Bybit 서버사이드 trailing stop 등록.

    trail_distance: 가격 절대 거리 (예: BTC $300 = peak 대비 $300 풀백시 청산)
    activate_price: 트레일 시작 가격 (이 가격 도달 후 trail 활성). None = 즉시.

    봇 sleep 무관, tick 단위로 서버가 추적.
    """
    try:
        params = {
            "category": "linear", "symbol": symbol,
            "trailingStop": str(_round_price(symbol, trail_distance)),
            "positionIdx": 0,
        }
        if activate_price is not None:
            params["activePrice"] = str(_round_price(symbol, activate_price))
        r = session().set_trading_stop(**params)
        ok = r.get("retCode") == 0
        if not ok:
            print(f"[set trail err] {r.get('retMsg', '?')}", flush=True)
        return ok
    except Exception as e:
        msg = str(e)
        if "34040" in msg or "not modified" in msg:
            return True
        print(f"[set trail exc] {e}", flush=True)
        return False


# ─── OHLCV cache ───────────────────────────────────────────────
_cache: dict[tuple[str, str], tuple[pd.DataFrame, float]] = {}
_CACHE_TTL = {"15": cfg.CACHE_15M_SEC, "60": cfg.CACHE_1H_SEC,
              "240": cfg.CACHE_4H_SEC}

# v14: 펀딩 레이트 캐시 (8시간 funding interval, 30분 캐시)
_funding_cache: dict[str, tuple[float, float]] = {}
_FUNDING_CACHE_TTL = 1800  # 30분
# v15: 펀딩 히스토리 (추세 계산용) + OI 캐시
_funding_hist_cache: dict[str, tuple[list, float]] = {}
_FUNDING_HIST_TTL = 1800  # 30분
_oi_cache: dict[str, tuple[list, float]] = {}
_OI_CACHE_TTL = 600  # 10분 (OI 는 변동 잦음)


def get_funding_rate(symbol: str) -> Optional[float]:
    """현재 8시간 펀딩 레이트 (소수점 비율, 예: 0.0001 = 0.01%/8h).

    None 반환 = 조회 실패. 신호 점수 계산시 None 이면 페널티 없음.
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


def get_funding_history(symbol: str, count: int = 4) -> Optional[list[float]]:
    """최근 N개 펀딩 레이트 (가장 최근이 [0]). 8시간 간격 × N = N×8h 시계열.

    추세 계산용: [현재, 8h전, 16h전, 24h전].
    None = 조회 실패.
    """
    now = time.time()
    if symbol in _funding_hist_cache:
        hist, ts = _funding_hist_cache[symbol]
        if now - ts < _FUNDING_HIST_TTL and len(hist) >= count:
            return hist[:count]
    try:
        r = session().get_funding_rate_history(
            category="linear", symbol=symbol, limit=count,
        )
        rows = r.get("result", {}).get("list", [])
        if rows:
            hist = [float(row.get("fundingRate", 0)) for row in rows]
            _funding_hist_cache[symbol] = (hist, now)
            return hist
    except Exception as e:
        print(f"[funding_hist {symbol}] err: {e}", flush=True)
    return None


def get_open_interest_trend(symbol: str, interval: str = "1h",
                            count: int = 5) -> Optional[dict]:
    """OI 시계열 + 변화율. count=5, interval=1h 면 5시간 OI 추적.

    Returns:
        {"current": float, "past": float, "change_pct": float, "values": [...]}
        change_pct: (current - past) / past — 양수 = 증가, 음수 = 감소
        None = 조회 실패
    """
    now = time.time()
    if symbol in _oi_cache:
        info, ts = _oi_cache[symbol]
        if now - ts < _OI_CACHE_TTL:
            return info
    try:
        r = session().get_open_interest(
            category="linear", symbol=symbol,
            intervalTime=interval, limit=count,
        )
        rows = r.get("result", {}).get("list", [])
        if len(rows) < 2:
            return None
        values = [float(row.get("openInterest", 0)) for row in rows]
        current = values[0]
        past = values[-1]  # count-1 시간 전
        if past <= 0:
            return None
        change_pct = (current - past) / past
        info = {
            "current": current,
            "past": past,
            "change_pct": change_pct,
            "values": values,
        }
        _oi_cache[symbol] = (info, now)
        return info
    except Exception as e:
        print(f"[oi {symbol}] err: {e}", flush=True)
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
