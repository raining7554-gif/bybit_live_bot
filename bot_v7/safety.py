"""Hard safety guards: daily / weekly / monthly loss cutoffs.

State persisted in SAFETY_PATH so restarts don't reset the kill-switch clocks.
NOT exposed via env vars — limits are intentionally hard-coded (the whole point
is preventing the user from disabling them mid-blowup).
"""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from . import config as cfg


# ─── LIMITS (relaxed v7-3tier — user actively monitoring) ──────
# Raised from -3/-7/-12 to -7/-15/-25 because the new tier map allows
# 10x leverage at score >= 90, where a single 1.5*ATR stop can hit -2.85%
# equity. Tighter limits would halt on a single losing high-score trade.
DAILY_LOSS_LIMIT_PCT   = -0.07   # -7% intra-day → 24h halt
WEEKLY_LOSS_LIMIT_PCT  = -0.15   # -15% rolling 7d → 7d halt
MONTHLY_LOSS_LIMIT_PCT = -0.25   # -25% rolling 30d → 30d halt (catches
                                  # before reaching v6.3d's -35% disaster)
LIQ_DISTANCE_DOWNSIZE  = 0.10    # if any open pos liq distance < 10%, downsize

DAY_SEC   = 86400
WEEK_SEC  = 604800
MONTH_SEC = 2592000


@dataclass
class SafetyState:
    # Anchors (equity at the start of each rolling window)
    day_anchor_equity:   float = 0.0
    day_anchor_ts:       float = 0.0
    week_anchor_equity:  float = 0.0
    week_anchor_ts:      float = 0.0
    month_anchor_equity: float = 0.0
    month_anchor_ts:     float = 0.0
    # Halt timestamps (until when the bot must stay flat)
    halt_until_day:      float = 0.0
    halt_until_week:     float = 0.0
    halt_until_month:    float = 0.0
    # Last reason (for /status)
    last_halt_reason:    str   = ""


def load() -> SafetyState:
    try:
        if os.path.exists(cfg.SAFETY_PATH):
            with open(cfg.SAFETY_PATH) as f:
                return SafetyState(**json.load(f))
    except Exception as e:
        print(f"[safety load err] {e}", flush=True)
    return SafetyState()


def save(s: SafetyState):
    try:
        os.makedirs(os.path.dirname(cfg.SAFETY_PATH), exist_ok=True)
        with open(cfg.SAFETY_PATH, "w") as f:
            json.dump(asdict(s), f)
    except Exception as e:
        print(f"[safety save err] {e}", flush=True)


def _ensure_anchor(equity: float, anchor_eq: float, anchor_ts: float,
                   window_sec: int) -> tuple[float, float]:
    now = time.time()
    if anchor_eq <= 0 or now - anchor_ts > window_sec:
        return equity, now
    return anchor_eq, anchor_ts


def update_and_check(s: SafetyState, equity: float) -> tuple[bool, str]:
    """Refresh anchors, check rolling drawdowns, set halts. Returns (halted, reason)."""
    now = time.time()
    if equity <= 0:
        return False, ""

    # Refresh rolling anchors when window expires
    s.day_anchor_equity,   s.day_anchor_ts   = _ensure_anchor(
        equity, s.day_anchor_equity,   s.day_anchor_ts,   DAY_SEC)
    s.week_anchor_equity,  s.week_anchor_ts  = _ensure_anchor(
        equity, s.week_anchor_equity,  s.week_anchor_ts,  WEEK_SEC)
    s.month_anchor_equity, s.month_anchor_ts = _ensure_anchor(
        equity, s.month_anchor_equity, s.month_anchor_ts, MONTH_SEC)

    # Compute rolling drawdowns
    def dd(anchor: float) -> float:
        return (equity - anchor) / anchor if anchor > 0 else 0.0

    day_dd   = dd(s.day_anchor_equity)
    week_dd  = dd(s.week_anchor_equity)
    month_dd = dd(s.month_anchor_equity)

    # Trigger halts (cumulative — most severe wins)
    if month_dd <= MONTHLY_LOSS_LIMIT_PCT and now >= s.halt_until_month:
        s.halt_until_month = now + MONTH_SEC
        s.last_halt_reason = f"MONTHLY -{abs(month_dd)*100:.1f}% → 30d halt"
        save(s)

    if week_dd <= WEEKLY_LOSS_LIMIT_PCT and now >= s.halt_until_week:
        s.halt_until_week = now + WEEK_SEC
        s.last_halt_reason = f"WEEKLY -{abs(week_dd)*100:.1f}% → 7d halt"
        save(s)

    if day_dd <= DAILY_LOSS_LIMIT_PCT and now >= s.halt_until_day:
        s.halt_until_day = now + DAY_SEC
        s.last_halt_reason = f"DAILY -{abs(day_dd)*100:.1f}% → 24h halt"
        save(s)

    if now < s.halt_until_month:
        return True, f"MONTHLY halt until {time.strftime('%m-%d %H:%M', time.localtime(s.halt_until_month))}"
    if now < s.halt_until_week:
        return True, f"WEEKLY halt until {time.strftime('%m-%d %H:%M', time.localtime(s.halt_until_week))}"
    if now < s.halt_until_day:
        return True, f"DAILY halt until {time.strftime('%m-%d %H:%M', time.localtime(s.halt_until_day))}"

    return False, ""


def status_lines(s: SafetyState, equity: float) -> list[str]:
    """Human-readable lines for /status command."""
    def pct(anchor: float) -> str:
        if anchor <= 0:
            return "n/a"
        return f"{(equity-anchor)/anchor*100:+.2f}%"
    out = [
        f"일: {pct(s.day_anchor_equity)} (한도 {DAILY_LOSS_LIMIT_PCT*100:.0f}%)",
        f"주: {pct(s.week_anchor_equity)} (한도 {WEEKLY_LOSS_LIMIT_PCT*100:.0f}%)",
        f"월: {pct(s.month_anchor_equity)} (한도 {MONTHLY_LOSS_LIMIT_PCT*100:.0f}%)",
    ]
    now = time.time()
    if now < s.halt_until_day or now < s.halt_until_week or now < s.halt_until_month:
        out.append(f"⛔ {s.last_halt_reason}")
    return out
