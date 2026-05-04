"""Gemini-powered analysis layer (free tier).

Two responsibilities:
  1. Post-mortem on every closed trade  → short Korean lesson via Telegram
  2. Hourly market-regime classification → tag + suggested strategy

Both calls are best-effort, run on background threads, and never block the
trading loop. Failure modes (no key, network error, malformed JSON, rate
limit) are swallowed with a stderr line.

Default model: gemini-2.0-flash (free tier: ~15 RPM / 1500 RPD — plenty for
sub-100 trades/day + hourly regime).
"""
from __future__ import annotations
import json
import os
import threading
import time
from typing import Optional

import requests

from . import config as cfg
from . import notifier as tg


_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# In-memory regime cache (latest classification). Read by /ai handler and
# hourly report. Updated by detect_regime_async.
_last_regime: dict = {}
_last_regime_ts: float = 0.0


def _enabled() -> bool:
    return bool(cfg.GEMINI_API_KEY) and cfg.AI_ENABLED


def _call_gemini(prompt: str, *, want_json: bool = False,
                 timeout: int = 20) -> tuple[Optional[str], Optional[str]]:
    """Single REST call. Returns (text, error_msg). On success error_msg is None."""
    if not _enabled():
        return None, "AI disabled"
    url = f"{_API_BASE}/{cfg.AI_MODEL}:generateContent?key={cfg.GEMINI_API_KEY}"
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 400,
        },
    }
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    try:
        r = requests.post(url, json=body, timeout=timeout)
        if r.status_code != 200:
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            print(f"[AI {err}]", flush=True)
            return None, err
        data = r.json()
        cands = data.get("candidates", [])
        if not cands:
            err = f"no candidates: {str(data)[:200]}"
            print(f"[AI {err}]", flush=True)
            return None, err
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return None, "empty text in response"
        return text, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[AI exc] {err}", flush=True)
        return None, err


# ── Trade post-mortem ──────────────────────────────────────────────

def _build_postmortem_prompt(trade: dict, snapshot: dict) -> str:
    side_kr = "롱" if trade.get("side") == "Buy" else "숏"
    pnl = trade.get("pnl", 0)
    pnl_pct = trade.get("pnl_pct", 0) * 100
    outcome = "수익" if pnl >= 0 else "손실"
    reason = trade.get("reason", "?")
    strategy = trade.get("strategy", "D")
    tier = trade.get("tier", "?")
    score = trade.get("score", 0)
    lev = trade.get("leverage", 0)

    return (
        "당신은 암호화폐 트레이딩 분석가입니다. 방금 종료된 거래를 분석하세요.\n"
        "응답은 한국어로 정확히 3줄, 각 줄 50자 이내:\n"
        "1줄: 결과 핵심 원인 (시장 상황 기반)\n"
        "2줄: 다음에 적용할 구체적 교훈 1가지\n"
        "3줄: 현재 전략 유지/수정 제안 (한 단어 + 짧은 이유)\n"
        "─────────\n"
        f"거래: {strategy} {side_kr} {lev:.0f}x (tier={tier}, score={score:.0f})\n"
        f"진입가 {trade.get('entry'):.2f} → 청산가 {trade.get('exit'):.2f}\n"
        f"결과: {outcome} ${pnl:+.2f} ({pnl_pct:+.2f}%) | 청산사유: {reason}\n"
        f"진입시 시장상태: {json.dumps(snapshot, ensure_ascii=False)}\n"
    )


def _postmortem_worker(trade: dict, snapshot: dict):
    text, err = _call_gemini(_build_postmortem_prompt(trade, snapshot))
    if not text:
        # Background — don't spam Telegram on transient failures, just log
        print(f"[AI postmortem skipped] {err}", flush=True)
        return
    pnl = trade.get("pnl", 0)
    icon = "🧠✅" if pnl >= 0 else "🧠❌"
    tg.send(f"{icon} AI 분석\n{text}")


def analyze_trade_async(trade: dict, snapshot: dict):
    """Fire-and-forget post-mortem. Safe to call even if AI disabled."""
    if not _enabled():
        return
    threading.Thread(
        target=_postmortem_worker, args=(trade, snapshot),
        daemon=True, name="ai-postmortem",
    ).start()


# ── Regime detection ──────────────────────────────────────────────

def _build_regime_prompt(snapshot: dict) -> str:
    return (
        "당신은 암호화폐 시장 분석가입니다. 현재 BTCUSDT 시장 레짐을 판단하세요.\n"
        "JSON으로만 응답 (다른 텍스트 없이):\n"
        '{\n'
        '  "regime": "trending_up" | "trending_down" | "chop" | "high_vol" | "low_vol",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "summary_kr": "한국어 1줄 요약 (50자 이내)",\n'
        '  "suggested": "trend" | "mr" | "stand_aside",\n'
        '  "reason_kr": "한국어 1줄 근거 (50자 이내)"\n'
        '}\n'
        "─────────\n"
        f"시장 데이터: {json.dumps(snapshot, ensure_ascii=False)}\n"
    )


def _extract_json(text: str) -> Optional[dict]:
    """Tolerant JSON extractor: handles raw JSON, ```json fences, prose around JSON."""
    text = text.strip()
    # Strip code fence
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    # Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _regime_worker(snapshot: dict, send_telegram: bool, verbose_errors: bool):
    global _last_regime, _last_regime_ts
    text, err = _call_gemini(_build_regime_prompt(snapshot), want_json=True)
    if not text:
        if verbose_errors:
            tg.send(f"⚠️ AI 호출 실패\n{err}")
        return
    parsed = _extract_json(text)
    if parsed is None:
        msg = f"JSON 파싱 실패 — 응답: {text[:200]}"
        print(f"[AI regime parse err] {msg}", flush=True)
        if verbose_errors:
            tg.send(f"⚠️ AI 응답 파싱 실패\n{text[:300]}")
        return
    parsed["_ts"] = time.time()
    _last_regime = parsed
    _last_regime_ts = parsed["_ts"]
    if send_telegram:
        tg.send(
            f"🧠 시장 레짐: {parsed.get('regime', '?')}"
            f" (확신 {float(parsed.get('confidence', 0))*100:.0f}%)\n"
            f"{parsed.get('summary_kr', '')}\n"
            f"근거: {parsed.get('reason_kr', '')}\n"
            f"제안: {parsed.get('suggested', '?')}"
        )


def detect_regime_async(snapshot: dict, *, send_telegram: bool = False,
                        verbose_errors: bool = False):
    if not _enabled():
        return
    threading.Thread(
        target=_regime_worker, args=(snapshot, send_telegram, verbose_errors),
        daemon=True, name="ai-regime",
    ).start()


def get_last_regime() -> Optional[dict]:
    """Returns most recent regime classification (or None if none yet)."""
    return _last_regime if _last_regime else None


# ── Snapshot helpers ──────────────────────────────────────────────

def market_snapshot(df_15m, df_1h, df_4h) -> dict:
    """Compact dict of current indicator state. Cheap to compute, small
    enough to fit comfortably in a Gemini prompt."""
    def _row(df):
        if df is None or len(df) == 0:
            return {}
        r = df.iloc[-1]
        out = {}
        for k in ("close", "rsi", "adx", "bb_width", "bb_pos", "vol_ratio", "atr"):
            v = getattr(r, k, None)
            if v is None:
                continue
            try:
                fv = float(v)
                if fv != fv:  # NaN
                    continue
                out[k] = round(fv, 4)
            except Exception:
                pass
        return out
    return {
        "15m": _row(df_15m),
        "1h":  _row(df_1h),
        "4h":  _row(df_4h),
    }
