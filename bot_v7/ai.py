"""Bybit 봇 AI 레이어 — intelligence/ 모듈을 호출하는 thin wrapper.

기존 단독 ai.py 대신 cross-bot 공유 모듈 (intelligence/) 을 사용.
거래/분석/레짐/제안이 모두 SQLite (`/data/intelligence.db`) 에 영구 저장됨.

이 파일은 runner.py가 의존하는 외부 인터페이스를 유지하기 위한 어댑터:
  analyze_trade_async(trade, snapshot)
  detect_regime_async(snapshot, send_telegram=False, verbose_errors=False)
  market_snapshot(df15, df1h, df4h)
  get_last_regime()  → in-memory 마지막 레짐
"""
from __future__ import annotations
import os
import sys
from typing import Optional

# intelligence/ 모듈은 repo root 에 있음. bot_v7/ 에서 부모 경로 추가.
_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from intelligence import journal as _journal
from intelligence import agent as _agent

from . import config as cfg
from . import notifier as tg


# Bybit 봇 식별자 (cross-bot 통계에서 사용)
BOT_ID = os.environ.get("INTELLIGENCE_BOT_ID", "bybit_btc_d")


# ── 마지막 레짐 메모리 캐시 (시간별 리포트가 참조) ─────────────
_last_regime: dict = {}


def get_last_regime() -> Optional[dict]:
    """가장 최근 레짐 결과. DB에 저장된 것 중 1건 반환 (시간별 리포트용)."""
    rows = _journal.recent_regimes(bot_id=BOT_ID, since_seconds=86400, limit=1)
    if rows:
        r = rows[0]
        return {
            "regime": r.get("regime"),
            "confidence": r.get("confidence", 0),
            "summary_kr": r.get("summary"),
            "suggested": r.get("suggested"),
        }
    return _last_regime if _last_regime else None


# ── Snapshot helper (기존 인터페이스 유지) ──────────────────────

def market_snapshot(df_15m, df_1h, df_4h) -> dict:
    """현재 지표 상태를 압축된 dict 로. AI 프롬프트에 충분히 작게 들어감."""
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
    return {"15m": _row(df_15m), "1h": _row(df_1h), "4h": _row(df_4h)}


# ── Public API (runner.py가 호출) ────────────────────────────────

def analyze_trade_async(trade: dict, snapshot: Optional[dict] = None):
    """거래 종료 직후 호출. journal에 거래 기록 + AI 사후분석을 백그라운드로."""
    # 1. 저널에 거래 영구 저장
    trade_id = _journal.log_trade(
        bot_id=BOT_ID,
        symbol=trade.get("symbol", cfg.SYMBOL),
        side=trade.get("side", ""),
        entry_price=float(trade.get("entry") or 0),
        exit_price=float(trade.get("exit") or 0),
        size=float(trade.get("size") or 0),
        leverage=float(trade.get("leverage") or 1.0),
        pnl=float(trade.get("pnl") or 0),
        pnl_pct=float(trade.get("pnl_pct") or 0),
        reason=str(trade.get("reason", "")),
        strategy=str(trade.get("strategy", "")),
        tier=trade.get("tier"),
        score=trade.get("score"),
        entry_ts=int(trade.get("opened_ts") or 0) or None,
        exit_ts=int(trade.get("ts") or 0) or None,
        market_snapshot=snapshot,
    )
    # 2. AI 사후분석 (백그라운드)
    _agent.analyze_trade_async(
        bot_id=BOT_ID,
        trade=trade,
        snapshot=snapshot,
        trade_id=trade_id or None,
        send_telegram=tg.send,
    )


def detect_regime_async(snapshot: dict, *, send_telegram: bool = False,
                        verbose_errors: bool = False):
    """주기적 레짐 분류. send_telegram=True면 결과를 텔레그램으로 보냄."""
    _agent.detect_regime_async(
        bot_id=BOT_ID,
        asset=cfg.SYMBOL,
        snapshot=snapshot,
        send_telegram=tg.send if send_telegram else None,
        verbose_errors=verbose_errors,
    )


# ── /review, /propose, /lessons (텔레그램 명령) ─────────────────

def weekly_review_async(verbose_errors: bool = True):
    """본인 봇 데이터만 회고. /review 명령에서 호출."""
    _agent.weekly_review_async(
        bot_id=BOT_ID,
        send_telegram=tg.send,
        verbose_errors=verbose_errors,
    )


def propose_async(verbose_errors: bool = True):
    """현재 파라미터 + 4주 데이터 → AI 제안. /propose 명령에서 호출."""
    current = {
        "ENTRY_MIN_SCORE": cfg.ENTRY_MIN_SCORE,
        "MARGIN_PCT_MICRO": cfg.MARGIN_PCT_MICRO,
        "MARGIN_PCT_PROBE": cfg.MARGIN_PCT_PROBE,
        "MARGIN_PCT_BASE":  cfg.MARGIN_PCT_BASE,
        "MARGIN_PCT_MID":   cfg.MARGIN_PCT_MID,
        "MARGIN_PCT_HIGH":  cfg.MARGIN_PCT_HIGH,
        "TP_MARGIN_MICRO":  cfg.TP_MARGIN_MICRO,
        "TP_MARGIN_PROBE":  cfg.TP_MARGIN_PROBE,
        "TP_MARGIN_BASE":   cfg.TP_MARGIN_BASE,
        "TP1_MARGIN_MID":   cfg.TP1_MARGIN_MID,
        "TRAIL_ATR_MID":    cfg.TRAIL_ATR_MID,
        "TRAIL_ATR_HIGH":   cfg.TRAIL_ATR_HIGH,
    }
    _agent.propose_async(
        bot_id=BOT_ID,
        current_params=current,
        send_telegram=tg.send,
        verbose_errors=verbose_errors,
    )


def get_recent_lessons_text(limit: int = 5) -> str:
    """/lessons 명령용. 최근 도출된 교훈 N개 텍스트."""
    rows = _journal.recent_lessons(bot_id=BOT_ID, limit=limit)
    if not rows:
        return "📚 누적 교훈 없음 (거래 누적 + 사후분석 후 표시)"
    lines = ["📚 <b>최근 교훈</b>"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r.get('lesson', '?')}")
    return "\n".join(lines)
