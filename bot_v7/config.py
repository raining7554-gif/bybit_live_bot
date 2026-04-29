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

# ─── Capital / sizing (user-configurable) ──────────────────────
# Margin = MARGIN_PCT × equity (per trade). Notional = margin × dynamic_leverage.
MARGIN_PCT       = float(os.environ.get("MARGIN_PCT", "0.50"))
# Max equity actually used by the bot (rest sits idle as buffer).
CAPITAL_FRACTION = float(os.environ.get("CAPITAL_FRACTION", "1.00"))

# ─── Strategy D v7-3tier (user-requested aggressive scaling) ──
ENTRY_MIN_SCORE  = 70.0   # back to v3 — only enter on strong signals
SCORE_TIER_1     = 80.0   # 70..79 -> base (5x)
SCORE_TIER_2     = 90.0   # 80..89 -> mid (7x); >=90 -> high (10x)
LEV_TIER_BASE    = 5.0    # 70..79
LEV_TIER_MID     = 7.0    # 80..89
LEV_TIER_HIGH    = 10.0   # 90+

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
