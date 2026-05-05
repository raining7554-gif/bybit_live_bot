"""Multi-symbol position state persistence (v12).

저장 형식:
  {"BTCUSDT": {pos dict}, "ETHUSDT": {pos dict}, ...}

레거시 단일 심볼 형식 (side/entry/size 등 직접 키)도 자동 감지하여
SYMBOL 키 하나로 wrapping 해서 로드.
"""
from __future__ import annotations
import json
import os
from typing import Optional

from . import config as cfg


def _is_legacy_single(data: dict) -> bool:
    """레거시 단일 심볼 포맷이면 True."""
    if not data:
        return False
    # 단일 포지션 dict는 'side' 같은 키가 최상위에 있음
    if "side" in data and not isinstance(data.get("side"), dict):
        return True
    return False


def load_all() -> dict[str, dict]:
    """심볼별 포지션 dict 반환. 비어있으면 {}."""
    try:
        if not os.path.exists(cfg.STATE_PATH):
            return {}
        with open(cfg.STATE_PATH) as f:
            data = json.load(f)
        if not data:
            return {}
        if _is_legacy_single(data):
            return {cfg.SYMBOL: data}
        return data
    except Exception as e:
        print(f"[state load_all err] {e}", flush=True)
        return {}


def save_all(positions: dict[str, dict]):
    """심볼 → 포지션 dict 통째로 저장 (빈 포지션은 제외)."""
    try:
        os.makedirs(os.path.dirname(cfg.STATE_PATH), exist_ok=True)
        clean = {sym: p for sym, p in positions.items() if p}
        with open(cfg.STATE_PATH, "w") as f:
            json.dump(clean, f)
    except Exception as e:
        print(f"[state save_all err] {e}", flush=True)


# ── 레거시 호환 ─────────────────────────────────────────────────
def load() -> Optional[dict]:
    return load_all().get(cfg.SYMBOL)


def save(pos: Optional[dict]):
    all_pos = load_all()
    if pos:
        all_pos[cfg.SYMBOL] = pos
    else:
        all_pos.pop(cfg.SYMBOL, None)
    save_all(all_pos)


def log_trade(rec: dict):
    """거래 종료 jsonl 로그 (추가만). symbol 필드 포함 권장."""
    try:
        os.makedirs(os.path.dirname(cfg.TRADE_LOG_PATH), exist_ok=True)
        with open(cfg.TRADE_LOG_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[trade log err] {e}", flush=True)
