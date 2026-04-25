"""Vectorized indicators (mirrors live bot's calc_indicators logic)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).rolling(n).mean()
    lo = (-d.clip(upper=0)).rolling(n).mean()
    rs = g / lo.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    up = mid + k * sd
    lo = mid - k * sd
    width = (up - lo) / mid.replace(0, np.nan)
    pos = (close - lo) / (up - lo).replace(0, np.nan)
    return mid, up, lo, width, pos


def adx_di(df: pd.DataFrame, n: int = 14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    dmp = (h - h.shift()).clip(lower=0)
    dmm = (l.shift() - l).clip(lower=0)
    cross = (dmp > dmm) & (dmp > 0)
    dmp = dmp.where(cross, 0)
    dmm = dmm.where(~cross & (dmm > 0), 0)
    atr_n = tr.rolling(n).mean()
    di_p = 100 * dmp.rolling(n).mean() / atr_n.replace(0, np.nan)
    di_m = 100 * dmm.rolling(n).mean() / atr_n.replace(0, np.nan)
    dx = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    adx = dx.rolling(n).mean()
    return adx, di_p, di_m


def donchian(df: pd.DataFrame, n: int = 20):
    return df["high"].rolling(n).max(), df["low"].rolling(n).min()


def volume_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume / volume.rolling(n).mean().replace(0, np.nan)


def add_all_15m(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)
    df["atr_pct"] = df["atr"] / df["close"]
    df["atr_ma"] = df["atr"].rolling(20).mean()
    bb_mid, bb_up, bb_lo, bb_w, bb_pos = bollinger(df["close"], 20, 2)
    df["bb_mid"], df["bb_up"], df["bb_lo"] = bb_mid, bb_up, bb_lo
    df["bb_width"], df["bb_pos"] = bb_w, bb_pos
    a, dp, dm = adx_di(df, 14)
    df["adx"], df["di_plus"], df["di_minus"] = a, dp, dm
    df["di_gap"] = (df["di_plus"] - df["di_minus"]).abs()
    df["vol_ratio"] = volume_ratio(df["volume"], 20)
    body = (df["close"] - df["open"]).abs()
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    df["body"], df["upper_wick"], df["lower_wick"] = body, upper_wick, lower_wick
    df["rsi_h5"] = df["rsi"].rolling(5).max()
    df["rsi_l5"] = df["rsi"].rolling(5).min()
    return df


def add_basic_1h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)
    df["atr_pct"] = df["atr"] / df["close"]
    a, dp, dm = adx_di(df, 14)
    df["adx"], df["di_plus"], df["di_minus"] = a, dp, dm
    return df


def add_basic_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["atr"] = atr(df, 14)
    df["atr_pct"] = df["atr"] / df["close"]
    df["atr_pct_pctile"] = df["atr_pct"].rolling(120).rank(pct=True)
    return df


def resample_to(df_15m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 15m bars to 1H/4H/1D for HTF context (right-closed, right-labeled)."""
    o = df_15m["open"].resample(rule, label="right", closed="right").first()
    h = df_15m["high"].resample(rule, label="right", closed="right").max()
    l = df_15m["low"].resample(rule, label="right", closed="right").min()
    c = df_15m["close"].resample(rule, label="right", closed="right").last()
    v = df_15m["volume"].resample(rule, label="right", closed="right").sum()
    out = pd.concat({"open": o, "high": h, "low": l, "close": c, "volume": v}, axis=1).dropna()
    return out
