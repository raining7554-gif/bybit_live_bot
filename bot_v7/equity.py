"""v6.61 잔고 히스토리 — 매일 1회 스냅샷 저장 + 기간별 변화 계산.

봇이 계산한 PnL (DB trades) 과 별개로, 실제 거래소 잔고 변화 추적.
펀딩/수수료/슬리피지/미실현 모두 자동 포함.
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from . import config as cfg


PATH = os.path.join(os.path.dirname(cfg.STATE_PATH) or "/data",
                    "equity_snapshots.json")


def load_all() -> dict:
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_snapshot(equity: float) -> bool:
    """오늘 잔고 저장 (같은 날 덮어씀). 최근 60일만 유지."""
    today = datetime.now().strftime("%Y-%m-%d")
    data = load_all()
    data[today] = {"ts": int(time.time()), "equity": float(equity)}
    # 60일 초과시 오래된 거 삭제
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


def get_delta(days: int, current_equity: float) -> Optional[tuple[float, float, str]]:
    """N일전 잔고 대비 변화. (delta_$, delta_%, snapshot_date).

    정확히 N일 전 데이터 없으면 가장 가까운 과거 스냅샷 사용.
    """
    data = load_all()
    if not data:
        return None
    target = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    keys = sorted(data.keys())
    older = [k for k in keys if k <= target]
    if not older:
        # N일 전 스냅샷 없음 — 가장 오래된 거 사용
        if not keys:
            return None
        used = keys[0]
    else:
        used = older[-1]
    old_eq = data[used]["equity"]
    if old_eq <= 0:
        return None
    delta = current_equity - old_eq
    pct = (delta / old_eq * 100)
    return delta, pct, used


def format_summary(current: float) -> str:
    """1일 / 7일 / 30일 잔고 변화 텍스트."""
    lines = [f"💰 <b>잔고 추이</b> (실제 거래소 기준)"]
    lines.append(f"현재: ${current:,.2f}")
    for days, label in [(1, "1일"), (7, "7일"), (30, "30일")]:
        r = get_delta(days, current)
        if r is None:
            lines.append(f"  {label}: 데이터 부족")
            continue
        delta, pct, used = r
        em = "📈" if delta >= 0 else "📉"
        lines.append(f"  {label} ({used}): {em} ${delta:+.2f} ({pct:+.2f}%)")

    snaps = load_all()
    lines.append(f"\n📅 누적 스냅샷: {len(snaps)}일")
    return "\n".join(lines)
