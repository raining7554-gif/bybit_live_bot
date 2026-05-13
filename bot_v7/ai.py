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


# Bybit 봇 식별자 (cross-bot 통계에서 사용). v12: 다중 심볼 → 단일 ID
# 거래 기록의 symbol 컬럼으로 심볼 구분.
BOT_ID = os.environ.get("INTELLIGENCE_BOT_ID", "bybit_d")


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


def hold_check(symbol: str, pos: dict, current_price: float,
               snapshot: dict | None = None) -> dict:
    """v6.35 A1b: 보유중 포지션 유지 vs 조기 청산 AI 평가.

    Returns: {
      "action": "hold" | "exit" | "tighten",
      "reason": str,
      "confidence": 0.0-1.0,
    }
    AI 비활성/quota 소진/오류시 항상 hold (개입 X).
    """
    try:
        if not _agent or not _agent._enabled():
            return {"action": "hold", "reason": "AI off", "confidence": 0.0}
        from intelligence import agent as _ag
        if _ag._quota_state.get("exhausted"):
            return {"action": "hold", "reason": "quota exhausted", "confidence": 0.0}
    except Exception:
        return {"action": "hold", "reason": "AI err", "confidence": 0.0}

    side = pos.get("side", "?")
    entry = pos.get("entry", 0)
    leverage = pos.get("leverage", 1)
    tier = pos.get("tier", "?")
    score = pos.get("score", 0)
    if entry <= 0:
        return {"action": "hold", "reason": "no entry", "confidence": 0.0}
    price_chg_pct = ((current_price - entry) / entry) if side == "Buy" \
                    else ((entry - current_price) / entry)
    margin_pct = price_chg_pct * leverage
    snap_str = ""
    if snapshot:
        snap_str = (
            f"\n현재 RSI {snapshot.get('rsi', '?')}, "
            f"BB pos {snapshot.get('bb_pos', '?')}, "
            f"ADX {snapshot.get('adx', '?')}"
        )

    prompt = (
        f"보유 포지션 hold/exit AI 결정. JSON 만 응답.\n"
        f"심볼: {symbol} {side} (tier {tier}, score {score})\n"
        f"진입가 {entry}, 현재가 {current_price}\n"
        f"가격 변동 {price_chg_pct*100:+.2f}%, 마진 변동 {margin_pct*100:+.1f}%"
        f"{snap_str}\n\n"
        f"이 포지션 유지가 합리적인가? "
        f"고점 도달 후 풀백, 추세 반전 신호, 큰 뉴스 등 위험 요소가 있나?\n"
        f'JSON: {{"action": "hold|exit|tighten", "reason": "20자내", "confidence": 0.0~1.0}}\n'
        f"  - hold: 유지\n"
        f"  - exit: 즉시 청산 (큰 위험 감지)\n"
        f"  - tighten: trail 강화 권장 (수익 보호)"
    )
    try:
        from intelligence.agent import _call_gemini, _extract_json
        text, err = _call_gemini(prompt, want_json=True, timeout=15)
        if err or not text:
            return {"action": "hold", "reason": err or "no resp", "confidence": 0.0}
        data = _extract_json(text) or {}
        return {
            "action": str(data.get("action", "hold")),
            "reason": str(data.get("reason", ""))[:60],
            "confidence": float(data.get("confidence", 0.5)),
        }
    except Exception as e:
        return {"action": "hold", "reason": f"exc: {e}", "confidence": 0.0}


def regime_deep(rule_regime: dict | None = None,
                news_sentiment: float | None = None,
                snapshot: dict | None = None) -> dict:
    """v6.35 A3: 레짐 종합 분석 — 룰 분류기 + 뉴스 + AI.

    Returns: {
      "regime": "trending_bull" | "trending_bear" | "ranging" | "transition",
      "summary": str,
      "suggested_action": str,
      "confidence": 0.0-1.0,
    }
    """
    try:
        if not _agent or not _agent._enabled():
            return {"regime": "?", "summary": "AI off", "suggested_action": "?", "confidence": 0.0}
        from intelligence import agent as _ag
        if _ag._quota_state.get("exhausted"):
            return {"regime": "?", "summary": "quota exhausted", "suggested_action": "?", "confidence": 0.0}
    except Exception:
        return {"regime": "?", "summary": "AI err", "suggested_action": "?", "confidence": 0.0}

    rule_str = ""
    if rule_regime:
        rule_str = (
            f"룰 분류기: {rule_regime.get('regime', '?')} "
            f"(신뢰 {rule_regime.get('confidence', 0)*100:.0f}%) "
            f"ADX 4H={rule_regime.get('adx_4h', '?')} 1H={rule_regime.get('adx_1h', '?')}"
        )
    news_str = ""
    if news_sentiment is not None:
        news_str = f"뉴스 sentiment: {news_sentiment:+.2f}"
    snap_str = ""
    if snapshot:
        snap_str = f"현재가 {snapshot.get('price', '?')} RSI {snapshot.get('rsi', '?')}"

    prompt = (
        f"암호화폐 시장 레짐 종합 분석. JSON 만 응답.\n"
        f"{rule_str}\n{news_str}\n{snap_str}\n\n"
        f"위 정보 종합해서 현재 시장 레짐 + 권장 행동 평가.\n"
        f'JSON: {{"regime": "trending_bull|trending_bear|ranging|transition",\n'
        f'        "summary": "한국어 1줄 (40자내)",\n'
        f'        "suggested_action": "한국어 1줄 (50자내)",\n'
        f'        "confidence": 0.0~1.0}}'
    )
    try:
        from intelligence.agent import _call_gemini, _extract_json
        text, err = _call_gemini(prompt, want_json=True, timeout=20)
        if err or not text:
            return {"regime": "?", "summary": err or "no resp", "suggested_action": "?", "confidence": 0.0}
        data = _extract_json(text) or {}
        return {
            "regime": str(data.get("regime", "?")),
            "summary": str(data.get("summary", ""))[:80],
            "suggested_action": str(data.get("suggested_action", ""))[:100],
            "confidence": float(data.get("confidence", 0.5)),
        }
    except Exception as e:
        return {"regime": "?", "summary": f"exc: {e}", "suggested_action": "?", "confidence": 0.0}


def gate_check(symbol: str, signal: dict, snapshot: dict | None = None) -> dict:
    """v6.33B: 진입 직전 AI final gate. (실시간, 동기, 빠른 평가).

    Returns: {
      "approved": True/False,
      "reason": str,
      "risk": "low"/"medium"/"high",
    }
    AI 비활성/quota 소진/오류시 항상 approved=True (개입 X).
    """
    try:
        if not _agent or not _agent._enabled():
            return {"approved": True, "reason": "AI off", "risk": "?"}
        from intelligence import agent as _ag
        # quota 사전 체크 — 소진시 통과
        if _ag._quota_state.get("exhausted"):
            return {"approved": True, "reason": "quota exhausted", "risk": "?"}
    except Exception:
        return {"approved": True, "reason": "AI err", "risk": "?"}

    side = signal.get("side", "?")
    score = signal.get("score", 0)
    tier = signal.get("tier", "?")
    tag = signal.get("tag", "D")
    snap_str = ""
    if snapshot:
        snap_str = (
            f"\n현재가 {snapshot.get('price', 0)}, RSI {snapshot.get('rsi', '?')}, "
            f"BB pos {snapshot.get('bb_pos', '?')}, ADX {snapshot.get('adx', '?')}"
        )

    prompt = (
        f"트레이딩 봇 진입 직전 AI 게이트 체크. JSON 만 응답.\n"
        f"심볼: {symbol}\n"
        f"방향: {side} (tag: {tag})\n"
        f"점수: {score}/100, tier: {tier}\n"
        f"{snap_str}\n\n"
        f"이 진입에 명확한 위험 신호가 있나? (예: 큰 뉴스, 명백한 반대 추세,"
        f" 슬리피지 위험)\n"
        f'JSON: {{"approved": true|false, "reason": "20자내", "risk": "low|medium|high"}}'
    )
    try:
        from intelligence.agent import _call_gemini, _extract_json
        text, err = _call_gemini(prompt, want_json=True, timeout=15)
        if err or not text:
            return {"approved": True, "reason": err or "no resp", "risk": "?"}
        data = _extract_json(text) or {}
        return {
            "approved": bool(data.get("approved", True)),
            "reason": str(data.get("reason", ""))[:60],
            "risk": str(data.get("risk", "?")),
        }
    except Exception as e:
        return {"approved": True, "reason": f"exc: {e}", "risk": "?"}


def detect_regime_async(snapshot: dict, *, asset: str | None = None,
                        send_telegram: bool = False,
                        verbose_errors: bool = False):
    """주기적 레짐 분류. asset 미지정시 첫 심볼 사용."""
    _agent.detect_regime_async(
        bot_id=BOT_ID,
        asset=asset or cfg.SYMBOL,
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


def get_symbol_stats_text(days: int = 7) -> str:
    """/symbols 명령용. 심볼별/tier별 누적 성과 텍스트."""
    return _journal.format_symbol_stats(
        bot_id=BOT_ID, since_seconds=days * 86400,
    )
