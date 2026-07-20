"""LIVE combined strategy — core + TQQQ + leveraged-sector satellite.

User-chosen package "섹터라이딩 혼합":  core 70% (multi-asset) + TQQQ 15% +
leveraged-sector rotation 15%. Outputs the actual weekly target weights in
TRADEABLE tickers, so the human can execute on KIS.

The leveraged-sector sleeve rotates among sectors that have a LIQUID 3x ETF
(price/trend judged on the unleveraged underlying in the bundle; held via the
3x ETF). Everything is trend-gated — a leveraged position is dropped to cash the
moment its underlying breaks its 200-day MA.

  python -m backtest_us.strategy_live
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .assets_bundle import load_assets
from .strategy_multiasset import compute as core_compute, _weekly
from .metrics import _curve_stats

TD = 252
COST = 0.0010
# 슬리브 비중 — env로 조절 가능. 기본 70/15/15(레버 30%).
# '반반' 구성: LEV_TQQQ=0.25 LEV_SEC=0.25 (코어 50 + 레버 50).
W_TQQQ = float(os.environ.get("LEV_TQQQ", "0.15"))
W_SEC = float(os.environ.get("LEV_SEC", "0.15"))
W_CORE = 1.0 - W_TQQQ - W_SEC

# 위성(레버리지) 변동성 타게팅 — 0이면 끔(이진 on/off 유지). 예: 0.20.
# 위성 합산 수익의 20일 실현변동성이 목표를 넘으면 그 비율만큼 노출 축소(상한 1).
# 백테스트(2010~, 반반+0.20): CAGR +17.1% Sharpe 0.82 MaxDD -34% —
# 반반 이진(-42.5%) 대비 낙폭·위기월(2022 -5.9%, 26-03 -8.3%) 크게 개선.
SAT_VOL_TARGET = float(os.environ.get("SAT_VOL_TARGET", "0"))
SAT_VOL_WIN = 20

# underlying (in bundle, for trend/momentum) -> tradeable 3x ETF (for execution)
SEC3X = {"SMH": "SOXL", "XLK": "TECL", "XLF": "FAS",
         "XLE": "ERX", "XBI": "LABU", "GDX": "NUGT"}
LETF_DRAG = 0.05   # annual cost of a 3x ETF (expense + financing), for backtest


def _trading(cm):
    return cm.reindex(cm["SPY"].dropna().index)


def sector3x_weights(cm, top_n=3, trend_ma=200, mom_win=126):
    und = [u for u in SEC3X if u in cm.columns]
    px = cm[und]
    trend = px > px.rolling(trend_ma, min_periods=trend_ma // 2).mean()
    mom = px / px.shift(mom_win) - 1.0
    score = mom.where(trend & px.notna())
    rank = score.rank(axis=1, ascending=False)
    held = (rank <= top_n) & score.notna()
    mpos = mom.where(held).clip(lower=0)
    rel = mpos.div(mpos.sum(axis=1).replace(0, np.nan), axis=0)
    inv = (held.sum(axis=1) / top_n).clip(upper=1.0)        # few qualify -> cash
    return rel.mul(inv, axis=0).fillna(0.0)                 # weights on UNDERLYINGS


def compute():
    cm = _trading(load_assets().sort_index())
    R = cm.pct_change()

    # 1) core (macro multi-asset)
    cw, core_ret, _ = core_compute()
    cw = cw.reindex(cm.index).ffill().fillna(0.0)
    core_ret = core_ret.reindex(cm.index).fillna(0.0)

    # 2) TQQQ sleeve (3x QQQ, on when QQQ>200MA)
    qqq = cm["QQQ"]
    tq_gate = _weekly(((qqq > qqq.rolling(200).mean()).astype(float)).to_frame("g"))["g"]
    tq_gate = tq_gate.shift(1).fillna(0.0)
    tqqq_ret = ((3 * R["QQQ"] - LETF_DRAG / TD) * tq_gate).fillna(0.0)

    # 3) leveraged-sector sleeve
    sw = _weekly(sector3x_weights(cm))
    swe = sw.shift(1).fillna(0.0)
    sec_ret = ((swe * (3 * R[sw.columns] - LETF_DRAG / TD)).sum(axis=1)).fillna(0.0)

    # 위성 합산 + (옵션) 변동성 타게팅: 위성 변동성이 목표 초과시 노출 축소 → 현금.
    # 백테스트는 shift(1)로 룩어헤드 방지, 라이브 목표비중은 최신(어제까지) 변동성 사용.
    sat_ret = (W_TQQQ * tqqq_ret + W_SEC * sec_ret).fillna(0.0)
    sat_scale_now = 1.0
    if SAT_VOL_TARGET > 0:
        rv = sat_ret.rolling(SAT_VOL_WIN, min_periods=SAT_VOL_WIN // 2).std() * np.sqrt(TD)
        sc = (SAT_VOL_TARGET / rv).clip(upper=1.0)
        sat_ret = sat_ret * sc.shift(1).fillna(0.0)
        v = sc.iloc[-1]
        sat_scale_now = float(v) if v == v else 1.0

    # combined daily return (weekly sleeve weights)
    total = (W_CORE * core_ret + sat_ret).fillna(0.0)

    # current target weights in tradeable tickers (위성엔 vol 스케일 반영, 남는 몫은 현금)
    tgt = {}
    for a, w in (cw.iloc[-1] * W_CORE).items():
        if w > 0.005:
            tgt[a] = tgt.get(a, 0) + w
    if tq_gate.iloc[-1] > 0:
        tgt["TQQQ"] = tgt.get("TQQQ", 0) + W_TQQQ * sat_scale_now
    for u, w in (sw.iloc[-1] * W_SEC * sat_scale_now).items():
        if w > 0.003:
            tgt[SEC3X[u]] = tgt.get(SEC3X[u], 0) + float(w)
    return total, tgt, cw.index[-1]


def _signal_state_path():
    return os.environ.get("SIGNAL_STATE_FILE", "/tmp/multiasset_last_tickers.json")


def _load_prev_tickers():
    import json
    try:
        with open(_signal_state_path()) as f:
            return set(json.load(f))
    except Exception:  # noqa: BLE001
        return None


def _save_tickers(tickers):
    import json
    try:
        with open(_signal_state_path(), "w") as f:
            json.dump(sorted(tickers), f)
    except Exception:  # noqa: BLE001
        pass


def build_context(tgt: dict) -> str:
    """이번 신호의 '시장 상황 + 왜 이 비중인지 + 지난주 대비 변화'를 텍스트로."""
    from .assets_bundle import MACRO
    cm = load_assets().sort_index()
    cm = cm.reindex(cm["SPY"].dropna().index)
    core = cm[[c for c in MACRO if c in cm.columns]]
    R = core.pct_change()
    last = core.iloc[-1]
    ma200 = core.rolling(200, min_periods=100).mean().iloc[-1]
    trend = (last > ma200) & last.notna()
    n_on, n_tot = int(trend.sum()), int(last.notna().sum())
    vol = (R.rolling(60, min_periods=30).std().iloc[-1] * (TD ** 0.5))

    spy = cm["SPY"]; spy_ext = spy.iloc[-1] / spy.rolling(200).mean().iloc[-1] - 1
    qqq = cm["QQQ"]; tqqq_on = qqq.iloc[-1] > qqq.rolling(200).mean().iloc[-1]
    regime = "강세(위험선호)" if n_on >= n_tot * 0.6 else ("혼조" if n_on >= n_tot * 0.3 else "약세(방어)")

    lines = ["", "📈 왜 이 비중인가",
             f"· 시장: 위험자산 추세 {n_on}/{n_tot} ON → {regime}",
             f"· SPY 200일선 대비 {spy_ext:+.0%} ({'과열' if spy_ext > 0.1 else '정상'})",
             f"· 레버리지 위성: TQQQ {'ON(나스닥 상승추세)' if tqqq_on else 'OFF→현금'}",
             "· 원리: 추세 위인 자산만 보유, 변동성 낮을수록 비중↑(위험 균등)"]
    # 위성 vol 타게팅 상태: 목표 레버리지 대비 실제 배정이 줄었으면 감속 표시
    if SAT_VOL_TARGET > 0:
        lev_now = tgt.get("TQQQ", 0) + sum(tgt.get(x, 0) for x in SEC3X.values())
        lev_cfg = W_TQQQ + W_SEC
        if lev_cfg > 0 and lev_now < lev_cfg * 0.97:
            lines.append(f"· ⚠️ 위성 감속 중: 변동성 급등 → 레버리지 {lev_now:.0%}만 배정"
                         f"(목표 {lev_cfg:.0%}), 나머지 현금 대기")
    # 큰 비중 2~3개 이유
    top = sorted(tgt.items(), key=lambda x: -x[1])[:3]
    for t, w in top:
        v = vol.get(t)
        why = (f"저변동({v:.0%})→비중큼" if (v is not None and v == v and v < 0.15)
               else ("레버리지 위성" if t in SEC3X.values() or t == "TQQQ" else "추세보유"))
        lines.append(f"   {t} {w:.0%}: {why}")

    # 🌐 매크로 해석 — 포지션이 함의하는 시장 뷰(가격 기반, 뉴스와 대조용)
    lev = tgt.get("TQQQ", 0) + sum(tgt.get(x, 0) for x in SEC3X.values())
    bonds = tgt.get("HYG", 0) + tgt.get("TLT", 0) + tgt.get("IEF", 0)
    macro = []
    if tgt.get("UUP", 0) > 0.08:
        macro.append("강달러 베팅")
    macro.append("위험선호" if n_on >= n_tot * 0.6 else
                 ("위험회피·방어" if n_on < n_tot * 0.3 else "혼조"))
    if lev > 0.20:
        macro.append("기술/성장 레버리지 큼")
    if bonds > 0.20:
        macro.append("채권 비중 큼(금리·신용 민감)")
    lines.append("🌐 매크로 해석: " + " · ".join(macro) +
                 " — 시스템이 가격으로 읽은 현재 국면(뉴스와 대조해보세요)")

    # 지난주 대비 변화(신규 진입 / 제외) — 직전 보유종목을 파일로 기억해 비교
    cur = set(tgt)
    prev = _load_prev_tickers()
    if prev is not None:
        added = cur - prev
        removed = prev - cur
        if added or removed:
            ch = "🔄 지난주 대비:"
            if added:
                ch += " 신규 " + ",".join(sorted(added))
            if removed:
                ch += " 제외 " + ",".join(sorted(removed))
            lines.append(ch)
        else:
            lines.append("🔄 지난주 대비: 변동 없음")
    _save_tickers(cur)
    return "\n".join(lines)


def main():
    total, tgt, asof = compute()
    st = _curve_stats((1 + total.loc["2010-01-01":]).cumprod(), "LIVE")
    vt = f", volTgt{SAT_VOL_TARGET:.0%}" if SAT_VOL_TARGET > 0 else ""
    print(f"LIVE 섹터라이딩 혼합 (코어{W_CORE:.0%}+TQQQ{W_TQQQ:.0%}+섹터{W_SEC:.0%}{vt}, "
          f"2010~, net): Sharpe={st['sharpe']:.2f} CAGR={st['cagr']:+.1%} MaxDD={st['mdd']:+.1%}")

    cap = float(os.environ.get("CAPITAL_KRW", "5000000"))
    print(f"\n=== 이번 주 목표 비중 (실거래 종목, {cap/1e4:,.0f}만원) — {asof.date()} ===")
    cash = 1 - sum(tgt.values())
    for k, v in sorted(tgt.items(), key=lambda x: -x[1]):
        tag = " ⚡3x" if k in ("TQQQ",) or k in SEC3X.values() else ""
        print(f"  {k:6} {v:5.1%}  {v*cap:>11,.0f}원{tag}")
    print(f"  현금   {max(cash,0):5.1%}  {max(cash,0)*cap:>11,.0f}원")

    m = (1 + total.loc["2025-05-31":]).resample("ME").prod() - 1
    bal = 5_000_000
    print("\n최근 1년 월별 (500만원):")
    for dt, mr in m.items():
        bal *= 1 + mr
        print(f"  {dt.strftime('%Y-%m')}  {mr:+6.1%}   {bal:>12,.0f}원")
    print(f"  합계 {bal/5_000_000-1:+.1%}")


if __name__ == "__main__":
    main()
