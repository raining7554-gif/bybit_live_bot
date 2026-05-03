"""v7 config: env vars + immutable strategy/risk constants.

Environment variables override defaults; safety guards (daily/weekly/monthly
loss limits) are *not* environment-tunable and are enforced in safety.py.
"""
from __future__ import annotations
import os

# ─── Credentials ───────────────────────────────────────────────
API_KEY    = os.environ.get("BYBIT_API_KEY", "")
API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
TESTNET    = os.environ.get("TESTNET", "false").lower() == "true"

# ─── Symbol / loop ─────────────────────────────────────────────
SYMBOL     = os.environ.get("SYMBOL", "BTCUSDT")
LOOP_SEC   = int(os.environ.get("LOOP_SEC", "30"))
POSITION_MODE = os.environ.get("POSITION_MODE", "one_way")

# ─── Capital / sizing (v9: per-tier differential margin) ──────
# Each D-tier gets its own margin allocation (Option C aggressive).
# Notional per trade = margin% × leverage × equity.
MARGIN_PCT_MICRO = 0.30   # 3x  → notional 90%   equity
MARGIN_PCT_PROBE = 0.40   # 5x  → notional 200%
MARGIN_PCT_BASE  = 0.50   # 10x → notional 500%
MARGIN_PCT_MID   = 0.65   # 15x → notional 975%
MARGIN_PCT_HIGH  = 0.80   # 20x → notional 1600%
MARGIN_PCT_MR    = 0.50   # MR 5x → notional 250% (unchanged)
# Legacy single-margin used only as fallback / display
MARGIN_PCT       = float(os.environ.get("MARGIN_PCT", "0.50"))
# Max equity actually used by the bot (rest sits idle as buffer).
CAPITAL_FRACTION = float(os.environ.get("CAPITAL_FRACTION", "1.00"))

# ─── Strategy D v9 (5-tier aggressive + per-tier exit + per-tier margin) ──
ENTRY_MIN_SCORE   = 55.0
SCORE_TIER_MICRO  = 60.0   # 55..59 → 3x
SCORE_TIER_PROBE  = 70.0   # 60..69 → 5x
SCORE_TIER_BASE   = 80.0   # 70..79 → 10x
SCORE_TIER_MID    = 90.0   # 80..89 → 15x; >=90 → 20x
LEV_TIER_MICRO    = 3.0
LEV_TIER_PROBE    = 5.0
LEV_TIER_BASE     = 10.0
LEV_TIER_MID      = 15.0
LEV_TIER_HIGH     = 20.0

# Per-tier exit policy v9 — option A (more extreme on both ends):
#   low tiers cash out faster (smaller TP)
#   high tiers trail wider (let trends run)
TP_MARGIN_MICRO   = 0.02   # micro: +2% margin → close (was +3%)
TP_MARGIN_PROBE   = 0.03   # probe: +3% margin → close (was +5%)
TP_MARGIN_BASE    = 0.06   # base:  +6% margin → close (was +10%)
TP1_MARGIN_MID    = 0.10   # mid:   TP1 +10% partial 50% → BE+trail rest
TP_MARGIN_HIGH    = None   # high:  no fixed TP — BE+trail only

# Per-tier ATR trail multiplier (mid + high are wider for trend riding)
TRAIL_ATR_DEFAULT = 1.5
TRAIL_ATR_MID     = 2.5
TRAIL_ATR_HIGH    = 3.0

# ─── Stop / trail ──────────────────────────────────────────────
ATR_STOP_MULT  = 1.5
ATR_TRAIL_MULT = 1.5
COOLDOWN_BARS_LOSS = 6      # 6 × 15m = 90 min after a stop

# ─── Hard safety guards (immutable; set in safety.py) ──────────
# Daily loss -3% → 24h halt
# Weekly loss -7% → 7d halt
# Monthly loss -12% → 30d halt
# These are NOT exposed via env to prevent mid-blowup tampering.

# ─── Persistence ───────────────────────────────────────────────
STATE_PATH      = os.environ.get("STATE_PATH",      "/data/state_v7.json")
TRADE_LOG_PATH  = os.environ.get("TRADE_LOG_PATH",  "/data/trades_v7.jsonl")
SAFETY_PATH     = os.environ.get("SAFETY_PATH",     "/data/safety_v7.json")

# ─── Symbol decimals (price + qty) ─────────────────────────────
PRICE_DECIMALS = {"BTCUSDT": 1, "ETHUSDT": 2, "SOLUSDT": 3, "XRPUSDT": 4, "LINKUSDT": 3}
QTY_DECIMALS   = {"BTCUSDT": 3, "ETHUSDT": 2, "SOLUSDT": 1, "XRPUSDT": 0, "LINKUSDT": 1}

# Disaster SL placed server-side at -2% (catches even if bot crashes)
DISASTER_SL_PCT = 0.02

# Refresh OHLCV cache every N seconds within a loop iteration (avoid spam)
CACHE_15M_SEC = 30
CACHE_1H_SEC  = 600
CACHE_4H_SEC  = 1800
