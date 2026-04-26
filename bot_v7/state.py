"""Position state persistence (recovery on restart)."""
from __future__ import annotations
import json
import os
from typing import Optional

from . import config as cfg


def load() -> Optional[dict]:
    try:
        if os.path.exists(cfg.STATE_PATH):
            with open(cfg.STATE_PATH) as f:
                return json.load(f)
    except Exception as e:
        print(f"[state load err] {e}", flush=True)
    return None


def save(pos: Optional[dict]):
    try:
        os.makedirs(os.path.dirname(cfg.STATE_PATH), exist_ok=True)
        with open(cfg.STATE_PATH, "w") as f:
            json.dump(pos or {}, f)
    except Exception as e:
        print(f"[state save err] {e}", flush=True)


def log_trade(rec: dict):
    try:
        os.makedirs(os.path.dirname(cfg.TRADE_LOG_PATH), exist_ok=True)
        with open(cfg.TRADE_LOG_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[trade log err] {e}", flush=True)
