"""한국 매니지드 퓨처스 백테스트 — 유휴 원화로 낮(한국장)에 굴릴 별도 전략 검증.

미국 코어와 같은 원리(200일선 추세게이트 + 역변동성 위험균등 + 목표변동성)를 KRX ETF
유니버스에 적용. 한국이 빠질 땐 국고채·금·달러·인버스로 로테이션해 버티는 구조.

네트워크 필요 → GitHub Actions에서 실행. stdout으로 리포트 출력.
  python -m backtest_us.kr_backtest
"""
from __future__ import annotations
import numpy as np, pandas as pd
import yfinance as yf

TD = 252
COST = 0.0010

# 유동성·역사 있는 KODEX 중심 유니버스 (yfinance .KS 심볼)
UNIV = {
    "069500.KS": "KODEX200(코스피)",
    "229200.KS": "KODEX코스닥150",
    "114260.KS": "KODEX국고채3년",
    "148070.KS": "KOSEF국고채10년",
    "132030.KS": "KODEX골드선물H",
    "261240.KS": "KODEX미국달러선물",
    "114800.KS": "KODEX인버스",
}
LEV = {"122630.KS": "KODEX레버리지2x"}   # 위성(2x 코스피) — 참고용 별도


def _weekly(df):
    wk = pd.Series(df.index, index=df.index).resample("W").last().dropna()
    keep = df.index.isin(set(wk.values)); o = df.copy(); o[~keep] = np.nan
    return o.ffill()


def _stats(s, name):
    s = s.dropna()
    if len(s) < 60:
        return dict(cagr=float("nan"), sharpe=float("nan"), mdd=float("nan"), name=name)
    eq = (1 + s).cumprod()
    cagr = eq.iloc[-1] ** (TD / len(s)) - 1
    sharpe = s.mean() / s.std() * np.sqrt(TD) if s.std() else 0
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd, name=name)


def riskparity(px, cap=0.40, tv=0.10, trend_ma=200, vol_win=60):
    R = px.pct_change()
    trend = px > px.rolling(trend_ma, min_periods=trend_ma // 2).mean()
    vol = R.rolling(vol_win, min_periods=vol_win // 2).std()
    iv = (1.0 / vol).where(trend & px.notna())
    w = iv.div(iv.sum(axis=1), axis=0).clip(upper=cap)
    w = w.div(w.sum(axis=1), axis=0).fillna(0.0)
    wk = _weekly(w); we = wk.shift(1).fillna(0.0)
    port = (we * R).sum(axis=1) - COST * we.diff().abs().sum(axis=1).fillna(0)
    rv = port.rolling(40, min_periods=20).std() * np.sqrt(TD)
    lev = (tv / rv).clip(upper=1.0).shift(1).fillna(0)
    return (port * lev - COST * lev.diff().abs().fillna(0)).fillna(0.0), wk.iloc[-1]


def main():
    syms = list(UNIV) + list(LEV)
    raw = yf.download(syms, start="2010-01-01", auto_adjust=True, progress=False)["Close"]
    px = raw.dropna(how="all").sort_index()
    got = [c for c in px.columns if px[c].notna().sum() > 250]
    core_syms = [s for s in UNIV if s in got]
    px_core = px[core_syms].dropna(how="all")

    print("=== 한국 매니지드 퓨처스 백테스트 ===")
    print(f"데이터: {px.index.min().date()} ~ {px.index.max().date()}")
    print(f"유니버스({len(core_syms)}): " + ", ".join(UNIV[s] for s in core_syms))
    miss = [UNIV[s] for s in UNIV if s not in got]
    if miss:
        print(f"제외(데이터부족): {', '.join(miss)}")

    ret, wlast = riskparity(px_core)
    # 벤치마크
    kospi = px["069500.KS"].pct_change() if "069500.KS" in px else None
    start = ret.index[ret != 0][0] if (ret != 0).any() else ret.index[0]
    def line(name, st):
        print(f"  {name:26} Sharpe {st['sharpe']:5.2f}  CAGR {st['cagr']:+6.1%}  MaxDD {st['mdd']:+6.1%}")
    print("\n성과 (2010~, net, 목표변동성 10%):")
    line("한국 매니지드퓨처스", _stats(ret.loc[start:], "KRMF"))
    if kospi is not None:
        line("KODEX200 매수보유(참고)", _stats(kospi.loc[start:], "KOSPI"))
    if "122630.KS" in px:
        line("KODEX레버리지 보유(참고)", _stats(px["122630.KS"].pct_change().loc[start:], "LEV"))

    print("\n이번 주 목표비중(원화 봇이 살 것):")
    for s in sorted(core_syms, key=lambda x: -wlast.get(x, 0)):
        w = wlast.get(s, 0)
        if w > 0.005:
            print(f"  {UNIV[s]:20} {w:5.1%}")
    print(f"  현금 {max(0,1-wlast[core_syms].clip(lower=0).sum()):5.1%}")

    m = (1 + ret.loc[start:]).resample("ME").prod() - 1
    print("\n최근 12개월:")
    for dt, r in m.tail(12).items():
        print(f"  {dt.strftime('%Y-%m')}  {r:+6.1%}")


if __name__ == "__main__":
    main()
