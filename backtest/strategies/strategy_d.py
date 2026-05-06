"""Strategy D: signal-strength-adaptive leverage.

User-requested design. Trades happen at moderate frequency, but leverage and
risk-per-trade scale with how confident the signal is. Sideways or weak
signals -> small leverage; clean strong-trend setups -> larger leverage.

Signal strength score (0..100)
------------------------------
  +30  ADX             (18 -> 0pt, 36 -> 30pt, linear, capped)   ← v5 mid-ground
  +25  BB width        (0.006 -> 0pt, 0.020 -> 25pt, capped)     ← v5
  +25  Volume ratio    (0.9  -> 0pt, 1.4   -> 25pt, capped)      ← v5
  +20  MTF agreement   (1H trend same direction as 4H trend = 20, else 0)
  --
  0..100 total

Action by score (v6: 4H bias loosened, MTF non-binary, 55-59 micro-probe)
-----------------------------------------------------------------------
  score < 55           skip
  55 <= score < 60     leverage 1.0x, risk 0.2%/trade   ← NEW v6 micro-probe
  60 <= score < 70     leverage 1.5x, risk 0.3%/trade
  70 <= score < 80     leverage 2.5x, risk 0.7%/trade
  80 <= score < 90     leverage 4.0x, risk 1.0%/trade
  score >= 90          leverage 5.5x, risk 1.3%/trade  (highest conviction)

Direction
---------
  4H trend = up   -> long candidates only
  4H trend = down -> short candidates only
  4H neutral      -> skip

Trigger
-------
  long:  RSI(1H) crossed up through 50 in last 4 bars (1h)
  short: RSI(1H) crossed down through 50 in last 4 bars (1h)
  AND 15m close confirms (long: green candle, short: red candle)

Risk management
---------------
  stop = entry +/- 1.5 * ATR(15m)
  break-even at +1R, then trail with 1.5 * ATR(15m) chandelier
  TP scale-out: 50% off at +2R (exit half), rest trails
  cooldown after stop: 6 bars (1.5h)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ATR_STOP_MULT = 1.5
ATR_TRAIL_MULT = 1.5      # default trail (used by base/probe/micro if any)
ATR_TRAIL_MID  = 3.0      # v10.2: widened from 2.5 to ride trends further
ATR_TRAIL_HIGH = 4.0      # v10.2: widened from 3.0 to ride trends further
COOLDOWN_BARS_LOSS = 6
TP_SCALE_R = 2.0


def _trail_mult(tier: str) -> float:
    if tier == "high": return ATR_TRAIL_HIGH
    if tier == "mid":  return ATR_TRAIL_MID
    return ATR_TRAIL_MULT


def _signal_strength(row, row_h1, row_h4, *,
                     funding_8h_pct: float | None = None,
                     funding_24h_ago: float | None = None,
                     cross_agree: float | None = None,
                     oi_change_4h: float | None = None,
                     price_change_4h: float | None = None,
                     news_sentiment: float | None = None) -> tuple[float, str]:
    """Returns (score 0..100, direction).

    v15 — 10-component score:
      기본 점수 (0~100):  ADX(30) + BB(25) + Vol(25) + MTF(20) — 기존 4가지
      필터 multiplier (0.5~1.0 각각, 기하평균 적용):
        - 4H ADX confirmation
        - Funding rate sanity (signal vs crowded position)
        - Funding trend (24h 변화 — 막바지/시작 구분)  [v15 신규]
        - Cross-asset confluence
        - Volatility regime (4H atr_pct_pctile)
        - OI confirmation (가격 + OI 일치 여부)         [v15 신규]

    멀티플라이어 누락시 1.0 (no penalty) — backtest 호환성 유지.
    """
    if row_h4 is None or pd.isna(row_h4.get("ema50", np.nan)):
        return 0.0, "none"
    if row_h1 is None or pd.isna(row_h1.get("ema50", np.nan)):
        return 0.0, "none"

    long_bias = row_h4.close > row_h4.ema50
    short_bias = row_h4.close < row_h4.ema50
    if not (long_bias or short_bias):
        return 0.0, "none"
    direction = "long" if long_bias else "short"

    # ── 기본 4-component 점수 (0~100) — 기존 로직 유지 ──
    adx = row.adx if not pd.isna(row.adx) else 18
    adx_pt = max(0, min(30, (adx - 18) / 18 * 30))

    bbw = row.bb_width if not pd.isna(row.bb_width) else 0.01
    bbw_pt = max(0, min(25, (bbw - 0.006) / 0.014 * 25))

    vr = row.vol_ratio if not pd.isna(row.vol_ratio) else 1.0
    vol_pt = max(0, min(25, (vr - 0.9) / 0.5 * 25))

    if not pd.isna(row_h1.get("ema50", np.nan)) and row_h1.ema50 > 0:
        h1_dist = (row_h1.close - row_h1.ema50) / row_h1.ema50
    else:
        h1_dist = 0.0
    h1_long = h1_dist > 0.001
    h1_short = h1_dist < -0.001
    h1_neutral = abs(h1_dist) <= 0.001
    if (long_bias and h1_long) or (short_bias and h1_short):
        mtf_pt = 20
    elif h1_neutral:
        mtf_pt = 15
    else:
        mtf_pt = 0

    base_score = adx_pt + bbw_pt + vol_pt + mtf_pt  # 0~100

    # ── v14 신규: 4가지 필터 multiplier (0.5~1.0) ──

    # 1) 4H ADX confirmation
    htf_adx_val = row_h4.get("adx") if hasattr(row_h4, "get") else getattr(row_h4, "adx", None)
    if htf_adx_val is None or (hasattr(pd, "isna") and pd.isna(htf_adx_val)):
        htf_mult = 1.0
    else:
        htf_adx_val = float(htf_adx_val)
        if htf_adx_val >= 25:
            htf_mult = 1.0
        elif htf_adx_val >= 18:
            htf_mult = 0.85 + (htf_adx_val - 18) / 7 * 0.15
        else:
            htf_mult = 0.70

    # 2) Funding sanity (None → no penalty)
    if funding_8h_pct is None:
        fund_mult = 1.0
    else:
        # 신호 방향과 펀딩 방향이 같고 절댓값 큼 = 과밀거래 → 강한 페널티
        if direction == "long" and funding_8h_pct > 0.0005:
            fund_mult = 0.50
        elif direction == "short" and funding_8h_pct < -0.0005:
            fund_mult = 0.50
        elif direction == "long" and funding_8h_pct > 0.0003:
            fund_mult = 0.75
        elif direction == "short" and funding_8h_pct < -0.0003:
            fund_mult = 0.75
        else:
            fund_mult = 1.0  # 정상 또는 반대 방향 (양호)

    # 3) Cross-asset confluence (None → no penalty)
    # cross_agree: 0~1. 1=다른 심볼 4H 추세 모두 같은 방향, 0=다 반대
    if cross_agree is None:
        cross_mult = 1.0
    else:
        cross_agree = max(0.0, min(1.0, cross_agree))
        if cross_agree >= 0.6:
            cross_mult = 1.0
        elif cross_agree >= 0.3:
            cross_mult = 0.85
        else:
            cross_mult = 0.70

    # 4) Volatility regime (4H atr_pct_pctile)
    vrp = row_h4.get("atr_pct_pctile") if hasattr(row_h4, "get") else getattr(row_h4, "atr_pct_pctile", None)
    if vrp is None or (hasattr(pd, "isna") and pd.isna(vrp)):
        vol_mult = 1.0
    else:
        vrp = float(vrp)
        if 0.30 <= vrp <= 0.70:
            vol_mult = 1.0
        elif 0.20 <= vrp <= 0.80:
            vol_mult = 0.85
        else:
            vol_mult = 0.70  # 너무 낮거나 너무 높은 변동성

    # ── v15 신규 ──

    # 5) Funding trend (24h 변화)
    if funding_8h_pct is None or funding_24h_ago is None:
        fund_trend_mult = 1.0
    else:
        delta = funding_8h_pct - funding_24h_ago
        # 펀딩 막바지 (이미 한쪽으로 극단 + 같은 방향 더 가속)
        if direction == "long":
            if funding_8h_pct > 0.0003 and delta > 0.0002:
                fund_trend_mult = 0.70  # late stage bull
            elif funding_8h_pct < -0.0003 and delta > 0.0001:
                fund_trend_mult = 1.0  # short squeeze 시작 (롱 좋음)
            else:
                fund_trend_mult = 0.90
        elif direction == "short":
            if funding_8h_pct < -0.0003 and delta < -0.0002:
                fund_trend_mult = 0.70
            elif funding_8h_pct > 0.0003 and delta < -0.0001:
                fund_trend_mult = 1.0
            else:
                fund_trend_mult = 0.90
        else:
            fund_trend_mult = 1.0

    # 6) OI confirmation
    # 가격 동의방향 + OI 증가 = 진짜 추세
    # 가격 동의방향 + OI 감소 = squeeze (forced) → 페널티
    if oi_change_4h is None or price_change_4h is None:
        oi_mult = 1.0
    else:
        if direction == "long":
            if price_change_4h > 0 and oi_change_4h > 0.02:
                oi_mult = 1.0  # confirmed bull
            elif price_change_4h > 0 and oi_change_4h < -0.02:
                oi_mult = 0.65  # squeeze fake pump
            elif price_change_4h <= 0 and oi_change_4h > 0.02:
                oi_mult = 0.75  # 가격 떨어지는데 OI 증가 → 신규 숏 (롱엔 안좋음)
            else:
                oi_mult = 0.90
        elif direction == "short":
            if price_change_4h < 0 and oi_change_4h > 0.02:
                oi_mult = 1.0  # confirmed bear
            elif price_change_4h < 0 and oi_change_4h < -0.02:
                oi_mult = 0.65  # long capitulation only
            elif price_change_4h >= 0 and oi_change_4h > 0.02:
                oi_mult = 0.75  # 가격 오르는데 OI 증가 → 신규 롱 (숏엔 안좋음)
            else:
                oi_mult = 0.90
        else:
            oi_mult = 1.0

    # 7) News sentiment (CryptoPanic 기반)
    if news_sentiment is None:
        news_mult = 1.0
    else:
        # -1 (강한 약세) ~ +1 (강한 강세)
        if direction == "long":
            if news_sentiment >= 0.3:
                news_mult = 1.0  # 긍정 뉴스 + 롱 = OK
            elif news_sentiment >= 0:
                news_mult = 0.95
            elif news_sentiment >= -0.3:
                news_mult = 0.85
            else:
                news_mult = 0.65  # 강한 부정 + 롱 = 강한 페널티
        elif direction == "short":
            if news_sentiment <= -0.3:
                news_mult = 1.0  # 부정 뉴스 + 숏 = OK
            elif news_sentiment <= 0:
                news_mult = 0.95
            elif news_sentiment <= 0.3:
                news_mult = 0.85
            else:
                news_mult = 0.65  # 강한 긍정 + 숏 = 강한 페널티
        else:
            news_mult = 1.0

    # 기하평균 — 7개 멀티 (1/7승). 하나가 매우 낮아도 다른 게 보정.
    combined_mult = (htf_mult * fund_mult * fund_trend_mult *
                     cross_mult * vol_mult * oi_mult * news_mult) ** (1.0 / 7.0)

    score = base_score * combined_mult
    return score, direction


def _leverage_and_risk(score: float) -> tuple[float, float]:
    """v8 5-tier aggressive: 3x/5x/10x/15x/20x. Threshold 55."""
    if score < 55: return 0.0, 0.0
    if score < 60: return 3.0,  0.009    # micro
    if score < 70: return 5.0,  0.014    # probe
    if score < 80: return 10.0, 0.029    # base
    if score < 90: return 15.0, 0.043    # mid
    return 20.0, 0.057                    # high


def tier_for_score(score: float) -> str:
    """v8 string label per tier — used for exit policy lookup."""
    if score < 55: return "skip"
    if score < 60: return "micro"
    if score < 70: return "probe"
    if score < 80: return "base"
    if score < 90: return "mid"
    return "high"


def _rsi_crossed_50(rsi_series: pd.Series, lookback: int = 4) -> str:
    """Returns 'up', 'down', or 'none' for last `lookback` bars."""
    if len(rsi_series) < lookback + 1:
        return "none"
    win = rsi_series.iloc[-lookback - 1:].values
    for i in range(len(win) - 1):
        if win[i] < 50 and win[i + 1] >= 50:
            return "up"
        if win[i] > 50 and win[i + 1] <= 50:
            return "down"
    return "none"


def _rsi_directional(rsi_series: pd.Series, side: str, lookback: int = 4) -> bool:
    """v7-r1: RSI in trend-supporting zone OR recent cross of 50.
    Far more permissive than strict cross (which is rare in chop).
    """
    if len(rsi_series) < 2:
        return False
    cur = rsi_series.iloc[-1]
    if pd.isna(cur):
        return False
    if side == "long" and cur > 50:
        return True
    if side == "short" and cur < 50:
        return True
    cross = _rsi_crossed_50(rsi_series, lookback)
    return (side == "long" and cross == "up") or (side == "short" and cross == "down")


def make_strategy():
    state = {"last_loss_idx": -10_000}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h1 = ctx["df_1h"]
        h4 = ctx["df_4h"]
        pos = ctx["position"]
        cfg = ctx["cfg"]
        row = df.iloc[i]
        row_h1 = h1.iloc[i] if h1 is not None else None
        row_h4 = h4.iloc[i] if h4 is not None else None

        # ----- manage open position -----
        if pos is not None:
            close = ctx["close"]
            high = ctx["high"]
            low = ctx["low"]
            atr15 = row.atr if not pd.isna(row.atr) else 0
            tier = pos.extras.get("tier", "high")
            tp_margin = pos.extras.get("tp_margin")  # None or float
            leverage = pos.leverage
            init_stop = pos.extras.get("init_stop", pos.stop)
            R = abs(pos.entry - init_stop)
            if R <= 0:
                return None

            # Compute current margin gain
            if pos.side == "long":
                price_chg = (close - pos.entry) / pos.entry
            else:
                price_chg = (pos.entry - close) / pos.entry
            margin_pct = price_chg * leverage

            # Tiers with fixed TP (full close at target)
            if tier in ("micro", "probe", "base") and tp_margin is not None:
                if margin_pct >= tp_margin:
                    return {"action": "close", "reason": "fixed_tp"}
                return None

            # Mid tier: TP1 partial 50% then BE+wider trail rest
            if tier == "mid":
                if not pos.extras.get("scale_done") and tp_margin is not None and margin_pct >= tp_margin:
                    pos.extras["scale_done"] = True
                    return {"action": "scale_out", "ratio": 0.5}
                if pos.extras.get("scale_done"):
                    tmult = _trail_mult(tier)
                    if pos.side == "long":
                        if not pos.extras.get("be_done") and (high - pos.entry) >= R:
                            pos.extras["be_done"] = True
                            return {"action": "modify_stop", "stop": pos.entry}
                        if pos.extras.get("be_done") and atr15 > 0:
                            cand = high - tmult * atr15
                            if cand > pos.stop:
                                return {"action": "modify_stop", "stop": cand}
                    else:
                        if not pos.extras.get("be_done") and (pos.entry - low) >= R:
                            pos.extras["be_done"] = True
                            return {"action": "modify_stop", "stop": pos.entry}
                        if pos.extras.get("be_done") and atr15 > 0:
                            cand = low + tmult * atr15
                            if cand < pos.stop:
                                return {"action": "modify_stop", "stop": cand}
                return None

            # High tier: BE @ +1R then widest trail (3.0×ATR)
            if tier == "high":
                tmult = _trail_mult(tier)
                if pos.side == "long":
                    if not pos.extras.get("be_done") and (high - pos.entry) >= R:
                        pos.extras["be_done"] = True
                        return {"action": "modify_stop", "stop": pos.entry}
                    if pos.extras.get("be_done") and atr15 > 0:
                        cand = high - tmult * atr15
                        if cand > pos.stop:
                            return {"action": "modify_stop", "stop": cand}
                else:
                    if not pos.extras.get("be_done") and (pos.entry - low) >= R:
                        pos.extras["be_done"] = True
                        return {"action": "modify_stop", "stop": pos.entry}
                    if pos.extras.get("be_done") and atr15 > 0:
                        cand = low + tmult * atr15
                        if cand < pos.stop:
                            return {"action": "modify_stop", "stop": cand}
            return None

        # ----- cooldown -----
        if i - state["last_loss_idx"] < COOLDOWN_BARS_LOSS:
            return None

        # ----- compute signal strength -----
        score, direction = _signal_strength(row, row_h1, row_h4)
        if direction == "none" or score < 55:    # v8: threshold 55
            return None
        # v8: RSI directional check REMOVED entirely

        # ----- candle confirmation -----
        if direction == "long" and row.close <= row.open:
            return None
        if direction == "short" and row.close >= row.open:
            return None

        # ----- compute stop -----
        atr15 = row.atr
        if pd.isna(atr15) or atr15 <= 0:
            return None

        if direction == "long":
            stop = row.close - ATR_STOP_MULT * atr15
        else:
            stop = row.close + ATR_STOP_MULT * atr15

        # ----- map score -> leverage / risk -----
        lev, risk = _leverage_and_risk(score)
        if lev == 0:
            return None

        # Override engine cfg via signal:
        # The engine uses cfg.risk_per_trade and cfg.max_leverage directly.
        # We can't change cfg per-trade, so we encode via size_pct in non-risk mode,
        # but since we're in risk mode, we use a custom override via extras.
        # Workaround: emit risk_override in signal; engine doesn't read this — we
        # instead synthesize a notional via stop distance.
        stop_dist_pct = abs(row.close - stop) / row.close
        equity = ctx["equity"]
        risk_dollars = equity * risk
        notional = risk_dollars / stop_dist_pct
        max_notional = equity * lev
        notional = min(notional, max_notional)
        size_pct_eff = notional / (equity * cfg.max_leverage) if cfg.max_leverage > 0 else 0

        # v9: per-tier exit policy (more extreme — low cuts faster, high trails wider)
        tier = tier_for_score(score)
        tp_margin_map = {
            "micro": 0.02, "probe": 0.03, "base": 0.06,
            "mid":   0.10, "high":  None,
        }
        tp_margin = tp_margin_map.get(tier)

        return {
            "action": "open",
            "side": direction,
            "stop": float(stop),
            "tp": None,                        # tp via in-strategy logic
            "size_pct": float(size_pct_eff),
            "tag": f"D_{direction}_s{int(score)}_lev{int(lev)}",
            "extras": {
                "init_stop": float(stop),
                "be_done": False,
                "scale_done": False,
                "score": float(score),
                "leverage_chosen": float(lev),
                "risk_chosen": float(risk),
                "tier": tier,
                "tp_margin": tp_margin,
            },
        }

    return strat
