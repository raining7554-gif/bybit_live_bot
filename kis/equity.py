"""v6.61 KIS 잔고 히스토리 — 매일 1회 KRW+USD 환산 총자산 스냅샷.

Bybit equity.py 와 동일 구조. KIS 는 KRW + USD 둘 다 추적.
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional


PATH = "/data/kis_equity_snapshots.json"


def load_all() -> dict:
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_snapshot(krw_total: float, usd_total: float,
                  usd_krw_rate: float = 1380) -> bool:
    """오늘 잔고 저장. 총자산 (KRW + USD×환율) 까지."""
    today = datetime.now().strftime("%Y-%m-%d")
    data = load_all()
    grand_total = krw_total + usd_total * usd_krw_rate
    data[today] = {
        "ts": int(time.time()),
        "krw": float(krw_total),
        "usd": float(usd_total),
        "rate": float(usd_krw_rate),
        "grand_total": float(grand_total),
    }
    keys = sorted(data.keys())
    if len(keys) > 60:
        for k in keys[:-60]:
            del data[k]
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w") as f:
            json.dump(data, f)
        return True
    except Exception as e:
        print(f"[equity save err] {e}", flush=True)
        return False


def get_delta(days: int, current: float) -> Optional[tuple[float, float, str]]:
    """N일전 총자산 대비 변화."""
    data = load_all()
    if not data:
        return None
    target = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    keys = sorted(data.keys())
    older = [k for k in keys if k <= target]
    if not older:
        if not keys:
            return None
        used = keys[0]
    else:
        used = older[-1]
    old = data[used].get("grand_total", 0)
    if old <= 0:
        return None
    delta = current - old
    pct = (delta / old * 100)
    return delta, pct, used


def format_summary(krw_total: float, usd_total: float,
                   usd_krw_rate: float = 1380) -> str:
    """1일 / 7일 / 30일 변화 텍스트."""
    grand = krw_total + usd_total * usd_krw_rate
    lines = [f"💰 <b>KIS 총자산 추이</b> (실제 잔고 기준)"]
    lines.append(f"현재: ₩{grand:,.0f} (KRW ₩{krw_total:,} + USD ${usd_total:.2f})")
    for days, label in [(1, "1일"), (7, "7일"), (30, "30일")]:
        r = get_delta(days, grand)
        if r is None:
            lines.append(f"  {label}: 데이터 부족")
            continue
        delta, pct, used = r
        em = "📈" if delta >= 0 else "📉"
        lines.append(f"  {label} ({used}): {em} ₩{delta:+,.0f} ({pct:+.2f}%)")
    snaps = load_all()
    lines.append(f"\n📅 누적 스냅샷: {len(snaps)}일")
    return "\n".join(lines)
