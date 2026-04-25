"""Option 2: Funding rate analysis (cash-and-carry feasibility).

Not a directional strategy. Computes the *theoretical* annualized yield achievable
by going short perp + long spot whenever funding > threshold (and vice-versa for
deeply negative funding). Output is APR-equivalent assuming you can hedge perfectly
on spot side.

Outputs:
  - APR if always hedged (passive, suboptimal)
  - APR if only hedged when |rate| > 0.03% per 8h (active filter)
  - Distribution of funding rates
  - Recommended threshold based on actual data

Use:
    from backtest.data import load_funding
    df = load_funding("BTCUSDT", days=365)
    analyze_funding(df)
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def analyze_funding(df: pd.DataFrame, thresholds=(0.0001, 0.0003, 0.0005, 0.0010)) -> dict:
    if df is None or len(df) == 0:
        return {"error": "no funding data"}

    rates = df["rate"].astype(float)
    intervals_per_year = 365 * 3   # 3 funding events per day

    out = {
        "n_periods": len(rates),
        "mean_rate_8h": float(rates.mean()),
        "median_rate_8h": float(rates.median()),
        "std_rate_8h": float(rates.std()),
        "max_rate_8h": float(rates.max()),
        "min_rate_8h": float(rates.min()),
        "passive_long_apr": float(-rates.mean() * intervals_per_year),  # short perp = receives funding when positive
        "passive_short_apr": float(rates.mean() * intervals_per_year),  # long perp
    }

    # Active strategy: only enter (short perp) when rate > +threshold;
    # enter (long perp) when rate < -threshold; else flat.
    active_returns = {}
    for thr in thresholds:
        # When rate > thr: short perp receives `rate` and we hedge with spot.
        # When rate < -thr: long perp receives -rate.
        # When |rate| <= thr: flat (zero return, no fees modeled here for simplicity).
        cond_short = rates > thr
        cond_long = rates < -thr
        contrib = pd.Series(0.0, index=rates.index)
        contrib[cond_short] = rates[cond_short]
        contrib[cond_long] = -rates[cond_long]
        active_returns[thr] = {
            "apr": float(contrib.sum() / len(rates) * intervals_per_year) if len(rates) > 0 else 0,
            "active_pct": float((cond_short | cond_long).mean()),
            "annual_event_count": int((cond_short | cond_long).sum() / (len(rates) / intervals_per_year)) if len(rates) > 0 else 0,
        }
    out["active_strategy_by_threshold"] = active_returns

    # Risk: spot/perp basis can diverge by ~0.1% during stress (funding cap reset etc.)
    # Subtract realistic costs:
    #   spot maker 0.1% + perp taker 0.055% on entry = 0.155%
    #   exit similar = 0.155%, total ~0.31% per round-trip
    # If we hold for ~3 funding periods average (active), that's ~0.31%/3periods=0.103% per period overhead
    cost_per_period_pct = 0.001  # 0.1% conservative
    out["estimated_net_apr_at_0.03pct_threshold"] = active_returns[0.0003]["apr"] - (
        active_returns[0.0003]["active_pct"] * cost_per_period_pct * intervals_per_year
    )

    return out


def format_funding_report(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    lines = [
        "📊 Funding Rate Analysis",
        f"  데이터 기간: {result['n_periods']} periods (8h each = ~{result['n_periods']/3:.0f}일)",
        f"  평균 펀딩 (8h): {result['mean_rate_8h']*100:+.4f}%",
        f"  중앙값 (8h):    {result['median_rate_8h']*100:+.4f}%",
        f"  표준편차:       {result['std_rate_8h']*100:.4f}%",
        f"  최대/최소:      {result['max_rate_8h']*100:+.4f}% / {result['min_rate_8h']*100:+.4f}%",
        "",
        "  Passive (perp 항상 short, spot 헤지):",
        f"    이론 APR: {result['passive_long_apr']*100:+.2f}% (수수료/이탈비 차감 전)",
        "",
        "  Active (임계 초과 시만 진입):",
    ]
    for thr, r in result["active_strategy_by_threshold"].items():
        lines.append(
            f"    임계 ±{thr*100:.3f}%/8h: APR {r['apr']*100:+.2f}% | "
            f"활성시간 {r['active_pct']*100:.1f}% | 연 이벤트 {r['annual_event_count']}회"
        )
    lines.append("")
    lines.append(f"  💡 0.03%/8h 임계 + 거래비용 차감 후 추정 APR: "
                 f"{result['estimated_net_apr_at_0.03pct_threshold']*100:+.2f}%")
    return "\n".join(lines)
