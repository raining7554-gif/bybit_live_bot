"""v13 main loop — multi-symbol Strategy D + MR (점수기반 사이징).

v12 의 1/N 마진 분할 → v13 점수기반 + 글로벌 마진 캡으로 변경.
- 단일 신호: full tier 마진 사용 (예: high tier 80%)
- 점수 비례 미세조정: margin = tier × (score/100)^SCORE_EXP
- 글로벌 캡 (MAX_TOTAL_MARGIN): 모든 활성 포지션 합계 ≤ 한도
"""
from __future__ import annotations
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

import pandas as pd

from . import ai
from . import config as cfg
from . import exchange as ex
from . import notifier as tg
from . import regime as rgm
from . import safety
from . import state as st
from . import strategy as strat


# ── 글로벌 상태 (계정 레벨) ────────────────────────────────────
_safety = None
_loop_count = 0
_last_report_kst_hour: int = -1
_last_regime_call_ts: dict[str, float] = {}    # symbol → last regime call ts
_last_weekly_review_kst: str = ""

# v6.0: 룰베이스 레짐 분류 캐시 (매 루프 갱신, 텔레그램/명령에서 즉시 조회)
_last_regime: dict[str, dict] = {}             # symbol → classify() 결과
_last_regime_log_ts: dict[str, float] = {}     # symbol → DB 마지막 기록 ts (1h 간격)

# ── 심볼별 상태 ────────────────────────────────────────────────
_positions: dict[str, dict] = {}        # symbol → 포지션 dict
_last_loss_ts: dict[str, float] = {}    # symbol → 마지막 손절 시각 (cooldown)


KST = timezone(timedelta(hours=9))


def _now_str() -> str:
    return datetime.now(KST).strftime("%H:%M:%S KST")


def _short(symbol: str) -> str:
    """BTCUSDT → BTC (메시지 prefix 용)."""
    return symbol.replace("USDT", "").replace("USD", "") or symbol


def _compute_cross_agree(self_symbol: str,
                        symbol_trends: dict[str, str]) -> float | None:
    """v14: 다른 심볼들의 4H 추세가 본 심볼의 추세와 얼마나 일치하는지 (0~1).

    1.0 = 다른 심볼 모두 같은 방향 (강한 시장 컨플루언스)
    0.5 = 절반만 일치 (또는 중립)
    0.0 = 모두 반대 방향 (이상 신호 가능성)
    """
    self_trend = symbol_trends.get(self_symbol)
    if self_trend in (None, "flat"):
        return None  # 본 심볼 추세 불명확 → 페널티 없음
    others = [t for sym, t in symbol_trends.items()
              if sym != self_symbol and t]
    if not others:
        return None  # 비교 대상 없음
    same = sum(1 for t in others if t == self_trend)
    flat = sum(1 for t in others if t == "flat")
    # flat 은 중립 (0.5점), same 은 1점, opposite 은 0점
    score = (same + 0.5 * flat) / len(others)
    return score


# ── 통계 (전 심볼 합산 / 단일 trade log) ──────────────────────
def _compute_stats(window_sec: int) -> tuple[int, int, float]:
    cutoff = time.time() - window_sec
    wins, losses, total_pnl = 0, 0, 0.0
    try:
        if not os.path.exists(cfg.TRADE_LOG_PATH):
            return wins, losses, total_pnl
        with open(cfg.TRADE_LOG_PATH) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("ts", 0) < cutoff:
                        continue
                    pnl = float(rec.get("pnl", 0))
                    total_pnl += pnl
                    if pnl >= 0:
                        wins += 1
                    else:
                        losses += 1
                except Exception:
                    pass
    except Exception as e:
        print(f"[stats err] {e}", flush=True)
    return wins, losses, total_pnl


def _today_pnl(equity: float) -> tuple[float, float]:
    if not _safety or _safety.day_anchor_equity <= 0:
        return 0.0, 0.0
    diff = equity - _safety.day_anchor_equity
    pct = diff / _safety.day_anchor_equity
    return diff, pct


def _build_status_text(equity: float) -> str:
    today_d, today_pct = _today_pnl(equity)
    lines = [
        f"📊 v15 상태 ({_now_str()})",
        f"잔고: ${equity:,.2f} (오늘 ${today_d:+.2f} / {today_pct*100:+.2f}%)",
    ]
    if _positions:
        for sym, p in _positions.items():
            side_kr = "롱" if p.get("side") == "Buy" else "숏"
            lev = p.get("leverage", 0)
            sname = p.get("strategy", "D")
            lines.append(f"• {_short(sym)}: {sname} {side_kr} ({lev:.0f}x)")
    else:
        lines.append("포지션: 없음")
    if _safety:
        lines.extend(safety.status_lines(_safety, equity))
    return "\n".join(lines)


def _build_score_text(symbol: str, df_15m, df_1h, df_4h) -> str:
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return f"{_short(symbol)}: 데이터 부족"
    from backtest.strategies.strategy_d import _signal_strength
    from backtest.strategies.strategy_mr import _check_signal as mr_check
    row, rh1, rh4 = df_15m.iloc[-1], df_1h.iloc[-1], df_4h.iloc[-1]
    score, direction = _signal_strength(row, rh1, rh4)
    lev = strat._leverage_for_score(score)
    mr_side, mr_reason = mr_check(row, rh4)
    return (
        f"📈 {_short(symbol)} 시그널\n"
        f"━ D ━ 방향:{direction} 점수:{score:.0f}/100 → {lev:.0f}x"
        + ("" if lev > 0 else " (X)") + "\n"
        f"━ MR ━ 신호:{mr_side} ({mr_reason})\n"
        f"ADX:{row.adx:.0f} BB폭:{row.bb_width*100:.2f}% RSI:{row.rsi:.0f} "
        f"거래량:{row.vol_ratio:.2f}x"
    )


_REASON_KR = {
    "fixed_tp": "TP", "tp": "TP", "scale_out": "TP1",
    "trail": "트레일", "sl": "손절", "mr_tp": "MR_TP",
    "server_stop": "서버손절", "flash": "급락", "manual": "수동",
}


# ── 청산 ───────────────────────────────────────────────────────
def _close_current(symbol: str, reason: str, fill_price: float,
                   equity_before: float):
    """주어진 심볼 포지션 청산."""
    pos = _positions.get(symbol)
    if not pos:
        return
    ok = ex.close_position_market(symbol, pos["side"], pos["size"])
    if not ok:
        tg.send(f"⚠️ {_short(symbol)} 청산 실패 ({reason}) — 다음 루프 재시도")
        return
    side = pos["side"]
    entry = pos["entry"]
    pnl_pct = (fill_price - entry) / entry if side == "Buy" else (entry - fill_price) / entry
    notional = pos["size"] * entry
    pnl_dollar = notional * pnl_pct
    emoji = "✅" if pnl_dollar >= 0 else "❌"

    rec = {
        "ts": time.time(),
        "symbol": symbol, "side": side,
        "entry": entry, "exit": fill_price,
        "size": pos["size"], "leverage": pos.get("leverage", 0),
        "score": pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": reason, "tier": pos.get("tier", "?"),
        "strategy": pos.get("strategy", "D"),
    }
    st.log_trade(rec)
    entry_snapshot = pos.get("entry_snapshot") or {}
    if pnl_dollar < 0:
        _last_loss_ts[symbol] = time.time()
    _positions.pop(symbol, None)
    st.save_all(_positions)

    # 포스트모템 + DB 영구 저장 (백그라운드, AI 비활성이면 no-op)
    ai.analyze_trade_async(rec, entry_snapshot)

    new_eq = ex.get_balance() or equity_before + pnl_dollar
    today_d, _ = _today_pnl(new_eq)
    label = _REASON_KR.get(reason, reason)
    tg.send(
        f"{emoji} [{_short(symbol)}] {label} 청산 ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
    )


# ── 진입 ───────────────────────────────────────────────────────
def _try_open(symbol: str, equity: float, signal: dict,
              snapshot: dict | None = None):
    if symbol in _positions:
        return  # already have a position on this symbol

    # v6.33A: 시간대 자동 차단 (KST 시간)
    cur_kst_hour = datetime.now(KST).hour
    if cur_kst_hour in cfg.BLOCKED_HOURS_KST_SET:
        # 한 번만 알림 (같은 시간대에 반복 알림 방지 — symbol+hour dedup)
        return  # 조용히 skip (시간대 차단은 정상 동작)

    # v6.33C: 자동 회복 휴식 — 일일 손실 -3% 도달시 진입 차단
    today_d, today_pct = _today_pnl(equity)
    if today_pct <= -cfg.DAILY_LOSS_REST_PCT:
        # 첫 발견 시 1회만 알림 (loop_count dedup 효과)
        if _loop_count % 30 == 1:
            tg.send(
                f"🛌 자동 휴식 발동 (오늘 ${today_d:+.2f} / {today_pct*100:+.2f}%)\n"
                f"-{cfg.DAILY_LOSS_REST_PCT*100:.0f}% 도달 — 다음 KST 자정까지 진입 차단"
            )
        return

    side = signal["side"]
    lev = signal["leverage"]
    is_mr = bool(signal.get("mr"))
    entry_price = ex.get_price(symbol)
    if entry_price <= 0:
        return

    # v6.33B: AI Final Gate (base 이상 tier 만 — 작은 진입은 통과)
    if (cfg.AI_FINAL_GATE_ENABLED and not is_mr
            and signal.get("tier") in ("base", "mid", "high")):
        try:
            gate = ai.gate_check(symbol, signal, snapshot)
            if not gate.get("approved", True):
                tg.send(
                    f"🚫 [{_short(symbol)}] AI 게이트 거부 (위험 {gate.get('risk', '?')})\n"
                    f"사유: {gate.get('reason', '')}"
                )
                return
            # 위험 high 면 통과해도 알림 (수동 확인 가능)
            if gate.get("risk") == "high":
                tg.send(
                    f"⚠️ [{_short(symbol)}] AI 게이트 위험 high (통과)\n"
                    f"사유: {gate.get('reason', '')}"
                )
        except Exception as e:
            print(f"[AI gate {symbol}] err: {e}", flush=True)

    if not ex.set_leverage(symbol, lev):
        tg.send(f"⚠️ [{_short(symbol)}] 레버리지 설정 실패 → 진입 보류")
        return

    sizing_tier = "mr" if is_mr else signal.get("tier", "base")
    score = signal.get("score") or 0

    # v15 Tier 1: 과거 비슷한 거래 패턴 매칭 (D 전략만)
    if not is_mr and snapshot:
        try:
            from intelligence import agent as _ag
            direction = "long" if side == "Buy" else "short"
            pattern = _ag.pattern_check(
                bot_id=ai.BOT_ID, symbol=symbol,
                direction=direction, current_snapshot=snapshot,
            )
            if pattern:
                pat_mult = _ag.pattern_to_multiplier(pattern)
                score_after = score * pat_mult
                rec = pattern.get("recommend", "?")
                similar = pattern.get("similar_count", 0)
                wins = pattern.get("similar_wins", 0)
                reason = pattern.get("reason_kr", "")
                tg.send(
                    f"🧠 [{_short(symbol)}] 패턴매칭: {rec.upper()} "
                    f"({wins}/{similar} 과거 승)\n"
                    f"점수 {score:.0f} → {score_after:.0f}\n"
                    f"근거: {reason}"
                )
                # 패턴 페널티 후 점수 < ENTRY_MIN_SCORE 면 진입 차단
                if score_after < cfg.ENTRY_MIN_SCORE:
                    tg.send(f"⏸️ [{_short(symbol)}] 패턴 거부 → 진입 skip")
                    _last_loss_ts[symbol] = time.time()  # cooldown
                    return
                score = score_after  # 사이징에 사용될 점수 업데이트
        except Exception as e:
            print(f"[pattern {symbol}] err: {e}", flush=True)

    # v13: 다른 활성 포지션이 사용 중인 마진 합계 → 캡 계산용
    active_margin = sum(
        p.get("margin_pct", 0.0) for s, p in _positions.items() if s != symbol
    )

    # v15 Tier 2: 심볼별 자동 가중치 (지난 30일 성과 기반)
    try:
        from intelligence import journal as _ij
        sw = _ij.symbol_weight(bot_id=ai.BOT_ID, symbol=symbol, days=30)
    except Exception:
        sw = 1.0

    qty, margin_pct = strat.calc_qty(
        equity, lev, entry_price, symbol,
        tier=sizing_tier, score=score, active_margin_used=active_margin,
        symbol_weight=sw,
    )
    if qty <= 0:
        # v6.30: 캡 도달 알림 제거 (반복 알림 스팸). 로그만 유지.
        if active_margin >= cfg.MAX_TOTAL_MARGIN * 0.95:
            print(f"[{_now_str()}] [{_short(symbol)}] 마진 캡 — 진입 skip "
                  f"(사용 {active_margin*100:.0f}% / 한도 {cfg.MAX_TOTAL_MARGIN*100:.0f}%)",
                  flush=True)
        return

    disaster_sl = entry_price * (1 - cfg.DISASTER_SL_PCT) if side == "Buy" \
                  else entry_price * (1 + cfg.DISASTER_SL_PCT)

    ok, oid = ex.place_market_order(symbol, side, qty, disaster_sl)
    if not ok:
        # v13.1: 진입 실패시 같은 심볼 cooldown 활성화 — 같은 신호로 매 루프
        # 재시도해서 텔레그램 폭주 방지. 90분 후 자동 해제.
        _last_loss_ts[symbol] = time.time()
        tg.send(f"⚠️ [{_short(symbol)}] 진입 실패 (90분 cooldown): {oid[:150]}")
        return

    strat_stop = signal["stop_price"]
    final_stop = max(strat_stop, disaster_sl) if side == "Buy" \
                 else min(strat_stop, disaster_sl)
    ex.update_stop_loss(symbol, side, final_stop)

    _positions[symbol] = {
        "side": side, "entry": entry_price, "size": qty,
        "leverage": lev, "score": score,
        "init_stop": signal["stop_price"], "current_stop": final_stop,
        "be_done": False, "scale_done": False, "scale_step": 0,
        "peak_margin_pct": 0.0,
        "atr_15m": signal["atr_15m"],
        "tp_price": signal.get("tp_price"),
        "tier": signal.get("tier", "high"),
        "tp_margin": signal.get("tp_margin"),
        # v6.28: D_INV (reverse) 트레이드 추적
        "strategy": (
            "MR" if is_mr
            else ("D_INV" if signal.get("inverse") else "D")
        ),
        "opened_ts": time.time(),
        "entry_snapshot": snapshot or {},
        "symbol": symbol,
        "margin_pct": margin_pct,  # v13: 캡 계산용
    }
    st.save_all(_positions)

    side_kr = "롱" if side == "Buy" else "숏"
    icon = "〰️ MR" if is_mr else "📈 D"
    notional = qty * entry_price
    sw_str = f" (가중치 {sw:.2f}x)" if abs(sw - 1.0) > 0.05 else ""
    tg.send(
        f"{icon} [{_short(symbol)}] {side_kr} 진입 ({lev:.0f}x) score={score:.0f}{sw_str}\n"
        f"마진 {margin_pct*100:.1f}% (notional ${notional:,.0f})\n"
        f"잔고: ${equity:,.2f}  진입가: ${entry_price:,.2f}"
    )


# ── 포지션 관리 (TP/SL/trail) ───────────────────────────────────
def _manage(symbol: str, df_15m: pd.DataFrame):
    pos = _positions.get(symbol)
    if not pos:
        return

    if pos.get("strategy") == "MR":
        tp = pos.get("tp_price")
        if tp:
            cur_px = float(df_15m["close"].iloc[-1])
            if (pos["side"] == "Buy" and cur_px >= tp) or \
               (pos["side"] == "Sell" and cur_px <= tp):
                _close_current(symbol, "mr_tp", cur_px, ex.get_balance())
        return

    # D strategy
    last_high = float(df_15m["high"].iloc[-1])
    last_low  = float(df_15m["low"].iloc[-1])
    cur_px    = float(df_15m["close"].iloc[-1])
    atr_15m   = float(df_15m["atr"].iloc[-1]) if "atr" in df_15m.columns \
                else pos.get("atr_15m", 0)

    decision = strat.evaluate_position_management(
        pos, atr_15m, cur_px, last_high, last_low,
    )
    if not decision:
        return
    act = decision.get("action")

    if act == "close":
        _close_current(symbol, decision.get("reason", "tp"), cur_px,
                       ex.get_balance())
        return

    if act == "scale_out":
        ratio = float(decision.get("ratio", 0.5))
        step = int(decision.get("step", 1))
        reason_tag = decision.get("reason", f"TP{step}")
        partial_qty = pos["size"] * ratio
        if ex.partial_close_market(symbol, pos["side"], partial_qty):
            pos["size"] -= partial_qty
            pos["scale_step"] = step
            pos["scale_done"] = True  # 레거시 호환 (be_then_trail 이 이걸 참조)
            st.save_all(_positions)
            new_eq = ex.get_balance()
            today_d, _ = _today_pnl(new_eq)
            tg.send(
                f"🟦 [{_short(symbol)}] {reason_tag} 부분익절 {ratio*100:.0f}%\n"
                f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
            )
        return

    if act == "modify_stop":
        new_stop = float(decision["stop"])
        if ex.update_stop_loss(symbol, pos["side"], new_stop):
            pos["current_stop"] = new_stop
            st.save_all(_positions)


# ── 거래소 sync ───────────────────────────────────────────────
def _reconcile_with_exchange(symbol: str, api_pos):
    """서버사이드 SL이 발동돼서 거래소 포지션이 사라진 경우 감지."""
    pos = _positions.get(symbol)
    if not pos:
        return
    if api_pos is not None:
        return

    last_price = ex.get_price(symbol)
    side = pos.get("side", "Buy")
    entry = float(pos.get("entry", 0))
    size = float(pos.get("size", 0))
    if entry <= 0 or last_price <= 0 or size <= 0:
        _positions.pop(symbol, None)
        st.save_all(_positions)
        return
    if side == "Buy":
        pnl_pct = (last_price - entry) / entry
    else:
        pnl_pct = (entry - last_price) / entry
    pnl_dollar = (size * entry) * pnl_pct
    emoji = "✅" if pnl_dollar >= 0 else "❌"
    rec = {
        "ts": time.time(),
        "symbol": symbol, "side": side,
        "entry": entry, "exit": last_price,
        "size": size, "leverage": pos.get("leverage", 0),
        "score": pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": "server_stop", "tier": pos.get("tier", "?"),
        "strategy": pos.get("strategy", "D"),
    }
    st.log_trade(rec)
    entry_snapshot = pos.get("entry_snapshot") or {}
    if pnl_dollar < 0:
        _last_loss_ts[symbol] = time.time()
    _positions.pop(symbol, None)
    st.save_all(_positions)
    ai.analyze_trade_async(rec, entry_snapshot)
    new_eq = ex.get_balance()
    today_d, _ = _today_pnl(new_eq)
    tg.send(
        f"{emoji} [{_short(symbol)}] 서버손절 ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
    )


def _restore_from_state():
    """디스크에서 모든 심볼 포지션 복구."""
    saved = st.load_all()
    for sym, pos in saved.items():
        if pos and pos.get("side"):
            _positions[sym] = pos
            tg.send(
                f"🔄 [{_short(sym)}] 저장된 포지션 복구: "
                f"{pos.get('side')} entry=${pos.get('entry'):.2f}"
            )


# ── 텔레그램 핸들러 ────────────────────────────────────────────
def _setup_handlers():
    def status():
        eq = ex.get_balance()
        tg.send(_build_status_text(eq))

    def score_cmd():
        for sym in cfg.SYMBOLS:
            df15 = ex.get_ohlcv_cached(sym, "15", 200)
            df1h = ex.get_ohlcv_cached(sym, "60", 200)
            df4h = ex.get_ohlcv_cached(sym, "240", 200)
            if any(len(d) < 60 for d in [df15, df1h, df4h]):
                tg.send(f"{_short(sym)}: 데이터 부족")
                continue
            d15, d1h, d4h = strat.compute_indicators(df15, df1h, df4h)
            tg.send(_build_score_text(sym, d15, d1h, d4h))

    def ai_cmd():
        if not cfg.AI_ENABLED or not cfg.GEMINI_API_KEY:
            tg.send("AI 비활성 (GEMINI_API_KEY + AI_ENABLED=true 필요)")
            return
        for sym in cfg.SYMBOLS:
            df15 = ex.get_ohlcv_cached(sym, "15", 200)
            df1h = ex.get_ohlcv_cached(sym, "60", 200)
            df4h = ex.get_ohlcv_cached(sym, "240", 200)
            if any(len(d) < 60 for d in [df15, df1h, df4h]):
                continue
            d15, d1h, d4h = strat.compute_indicators(df15, df1h, df4h)
            snap = ai.market_snapshot(d15, d1h, d4h)
            tg.send(f"🧠 {_short(sym)} 레짐 분석 중...")
            ai.detect_regime_async(snap, asset=sym, send_telegram=True,
                                   verbose_errors=True)

    def halt():
        global _safety
        if not _safety:
            return
        _safety.halt_until_day = time.time() + safety.DAY_SEC
        _safety.last_halt_reason = "수동 정지 (/halt)"
        safety.save(_safety)
        tg.send("⛔ 수동 24시간 정지 활성화")

    def resume():
        global _safety
        if not _safety:
            return
        _safety.halt_until_day = 0
        _safety.halt_until_week = 0
        _safety.halt_until_month = 0
        _safety.last_halt_reason = ""
        safety.save(_safety)
        tg.send("✅ 모든 정지 해제 (책임은 사용자)")

    def review_cmd():
        tg.send("📊 주간 회고 분석 중...")
        ai.weekly_review_async(verbose_errors=True)

    def propose_cmd():
        tg.send("⚙️ 파라미터 제안 분석 중...")
        ai.propose_async(verbose_errors=True)

    def lessons_cmd():
        tg.send(ai.get_recent_lessons_text(limit=8))

    def symbols_cmd():
        # 7일 + 30일 두 개 윈도우로 출력
        tg.send(ai.get_symbol_stats_text(days=7))
        tg.send(ai.get_symbol_stats_text(days=30))

    def diagnose_cmd():
        """v4.2: AI 없이 순수 통계 깊은 분석. /diagnose."""
        try:
            from intelligence import journal as _ij
            tg.send(_ij.deep_diagnose(bot_id=ai.BOT_ID, days=30))
        except Exception as e:
            tg.send(f"⚠️ /diagnose 오류: {e}")

    def regime_cmd():
        """v6.0: 룰베이스 레짐 분류 즉시 조회 (모든 심볼)."""
        if not _last_regime:
            tg.send("🧭 레짐 — 데이터 부족 (1~2 루프 후 다시 시도)")
            return
        snapshot = {sym: _last_regime.get(sym) for sym in cfg.SYMBOLS}
        tg.send(rgm.format_regime_msg(snapshot))

    def weights_cmd():
        """v15 Tier 2: 현재 적용 중인 심볼별 자동 가중치 표시."""
        try:
            from intelligence import journal as _ij
            weights = _ij.all_symbol_weights(bot_id=ai.BOT_ID, days=30)
        except Exception as e:
            tg.send(f"⚠️ /weights 오류: {e}")
            return
        if not weights:
            tg.send("📐 심볼 가중치 — 데이터 부족 (거래 3건 이상 누적 후 표시)")
            return
        lines = ["📐 <b>심볼 자동 가중치</b> (지난 30일 기반)"]
        for sym in cfg.SYMBOLS:
            w = weights.get(sym, 1.0)
            if abs(w - 1.0) < 0.05:
                tag = "중립"
                icon = "⚪"
            elif w > 1.0:
                tag = f"부스트 +{(w-1)*100:.0f}%"
                icon = "🟢"
            else:
                tag = f"축소 -{(1-w)*100:.0f}%"
                icon = "🔴"
            lines.append(f"{icon} {_short(sym)}: {w:.2f}x ({tag})")
        lines.append("")
        lines.append("거래 사이즈에 자동 곱해짐. 30일 승률+PnL 기반.")
        tg.send("\n".join(lines))

    return {
        "/status":  status,
        "/score":   score_cmd,
        "/ai":      ai_cmd,
        "/review":  review_cmd,
        "/propose": propose_cmd,
        "/lessons": lessons_cmd,
        "/symbols": symbols_cmd,
        "/weights": weights_cmd,
        "/diagnose": diagnose_cmd,
        "/regime":  regime_cmd,
        "/halt":    halt,
        "/resume":  resume,
    }


def _heartbeat(equity: float):
    pos_str = ",".join(_short(s) for s in _positions.keys()) or "-"
    print(f"[{_now_str()}] 💓 #{_loop_count} eq=${equity:.2f} pos={pos_str}",
          flush=True)


# ── 주기 작업 ───────────────────────────────────────────────────
def _maybe_run_regime(symbol: str, df15, df1h, df4h):
    """심볼별 레짐 분류 (1시간 간격).

    v6.14: AI 호출 비활성화 (Gemini quota 절약).
    v6.0 룰 분류기 (regime.classify) 가 실시간 + 무료로 대체.
    되살리려면 cfg.AI_REGIME_INTERVAL_SEC 줄이고 이 함수 본체 복원.
    """
    return  # AI 레짐 호출 차단 — 룰 분류기 사용


def _maybe_run_weekly_review():
    global _last_weekly_review_kst
    if not cfg.AI_ENABLED or not cfg.GEMINI_API_KEY:
        return
    now_kst = datetime.now(KST)
    if now_kst.weekday() != 6 or now_kst.hour != 0 or now_kst.minute >= 15:
        return
    today = now_kst.strftime("%Y-%m-%d")
    if today == _last_weekly_review_kst:
        return
    _last_weekly_review_kst = today
    print(f"[{_now_str()}] 📊 자동 주간 회고 트리거", flush=True)
    ai.weekly_review_async(verbose_errors=False)


def _maybe_hourly_report(equity: float):
    """KST 정각 보고 — 모든 심볼 포지션 합쳐서."""
    global _last_report_kst_hour
    now_kst = datetime.now(KST)
    if now_kst.minute >= 5:
        return
    if now_kst.hour == _last_report_kst_hour:
        return
    _last_report_kst_hour = now_kst.hour

    today_d, today_pct = _today_pnl(equity)

    pos_lines = []
    if _positions:
        for sym, p in _positions.items():
            side_kr = "롱" if p.get("side") == "Buy" else "숏"
            sname = p.get("strategy", "D")
            lev = p.get("leverage", 0)
            entry = p.get("entry", 0)
            size = p.get("size", 0)
            cur_px = ex.get_price(sym) or entry
            cur_pnl_pct = ((cur_px - entry) / entry) if p.get("side") == "Buy" \
                          else ((entry - cur_px) / entry)
            cur_pnl_d = (size * entry) * cur_pnl_pct
            pos_lines.append(
                f"• {_short(sym)} {sname} {side_kr} ({lev:.0f}x) "
                f"${cur_pnl_d:+.2f} ({cur_pnl_pct*100:+.2f}%)"
            )
    else:
        pos_lines.append("포지션: 없음")

    w24, l24, p24 = _compute_stats(86400)
    w7,  l7,  p7  = _compute_stats(604800)
    n24 = w24 + l24
    n7  = w7  + l7
    wr24 = (w24 / n24 * 100) if n24 > 0 else 0
    wr7  = (w7  / n7  * 100) if n7  > 0 else 0

    msg = (
        f"⏰ {now_kst.strftime('%H:%M')} KST\n"
        f"잔고: ${equity:,.2f} (오늘 ${today_d:+.2f} / {today_pct*100:+.2f}%)\n"
        + "\n".join(pos_lines) + "\n"
        f"─────────\n"
        f"24h: {w24}W/{l24}L ({wr24:.0f}%)  ${p24:+.2f}\n"
        f"7일: {w7}W/{l7}L ({wr7:.0f}%)  ${p7:+.2f}"
    )
    # v6.0: 룰베이스 레짐 — 심볼별 한 줄 요약
    if _last_regime:
        icon_map = {"trending": "🔥", "ranging": "💤", "mixed": "🌫"}
        reg_lines = ["🧭 레짐:"]
        for sym in cfg.SYMBOLS:
            r = _last_regime.get(sym)
            if not r:
                continue
            ic = icon_map.get(r["regime"], "❓")
            reg_lines.append(
                f"  {ic} {_short(sym)} {r['regime']} "
                f"→ {r['suggested']} ({int(r['confidence']*100)}%)"
            )
        if len(reg_lines) > 1:
            msg += "\n" + "\n".join(reg_lines)
    # AI 레짐 (있으면 추가 표시)
    reg = ai.get_last_regime()
    if reg:
        msg += (
            f"\n🧠 AI: {reg.get('regime', '?')} "
            f"({float(reg.get('confidence', 0))*100:.0f}%) → {reg.get('suggested', '?')}"
        )
    tg.send(msg)


# ── 메인 루프 ──────────────────────────────────────────────────
def main():
    global _safety, _loop_count

    print(f"[v15 boot] stage 1: env check", flush=True)
    print(f"  BYBIT_API_KEY: {'set' if cfg.API_KEY else 'MISSING'}", flush=True)
    print(f"  TG_TOKEN: {'set' if cfg.TG_TOKEN else 'MISSING'}", flush=True)
    print(f"  SYMBOLS={cfg.SYMBOLS} TESTNET={cfg.TESTNET}", flush=True)
    print(f"  CAPITAL_FRACTION={cfg.CAPITAL_FRACTION}", flush=True)

    if not cfg.API_KEY or not cfg.API_SECRET:
        print("❌ FATAL: BYBIT_API_KEY / BYBIT_API_SECRET required — exiting",
              flush=True)
        sys.exit(1)

    print(f"╔════════════════════════════════════════╗", flush=True)
    print(f"║  Bybit Bot v15 — 10-Component Signal   ║", flush=True)
    print(f"║  symbols={','.join(cfg.SYMBOLS)}", flush=True)
    print(f"╚════════════════════════════════════════╝", flush=True)

    print(f"[v15 boot] stage 2: exchange init", flush=True)
    try:
        ex.init()
    except Exception as e:
        print(f"❌ FATAL: exchange.init failed: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    print(f"[v15 boot] stage 3: state restore", flush=True)
    _safety = safety.load()
    _restore_from_state()

    print(f"[v15 boot] stage 4: API smoke test", flush=True)
    eq0 = ex.get_balance()
    print(f"  balance=${eq0:.2f}", flush=True)
    for sym in cfg.SYMBOLS:
        px0 = ex.get_price(sym)
        print(f"  price={sym}=${px0:.2f}", flush=True)

    me = tg.get_me()
    bot_label = f"@{me.get('username')} (id={me.get('id')})" if me else "unknown"
    handlers = _setup_handlers()
    n = len(cfg.SYMBOLS)
    sym_label = ", ".join(_short(s) for s in cfg.SYMBOLS)
    tg.send(
        f"🚀 v5.0 시작 — Mean Reversion primary ({n}종, mode={cfg.STRATEGY_MODE})\n"
        f"봇: {bot_label}\n"
        f"심볼: {sym_label} | 잔고: ${eq0:,.2f}\n"
        f"━ D 전략 (점수×tier 마진) ━\n"
        f"  base: ADX + BB + Vol + MTF (0~100)\n"
        f"  ×멀티: 4H ADX, 펀딩 sanity, 펀딩 추세\n"
        f"          cross-asset, 변동성 regime, OI\n"
        f"  margin = tier × (score/100)^{cfg.SCORE_EXP:.1f}\n"
        f"  55-59 → 3x  / TP +2%\n"
        f"  60-69 → 5x  / TP +3%\n"
        f"  70-79 → 10x / TP +6%\n"
        f"  80-89 → 15x / TP1+10% → 3.0×ATR\n"
        f"  90+   → 20x / 4.0×ATR\n"
        f"━ 글로벌 캡 ━\n"
        f"  활성 포지션 합계 마진 ≤ {cfg.MAX_TOTAL_MARGIN*100:.0f}%\n"
        f"  진입 실패시 90분 cooldown\n"
        f"━ MR — 5x / BB 중간선 TP / 마진 50%\n"
        f"━ 안전 ━\n"
        f"자동 정지 OFF (수동 /halt)\n"
        f"서버사이드 -2% SL 부착\n"
        f"명령: /status /score /ai /review /propose /lessons /symbols /weights /regime /halt /resume\n"
        f"⏰ KST 정각 리포트\n"
        f"🧠 AI: {'ON (' + cfg.AI_MODEL + ')' if (cfg.AI_ENABLED and cfg.GEMINI_API_KEY) else 'OFF'}"
    )
    print(f"[v15 boot] startup complete — entering main loop", flush=True)

    while True:
        try:
            _loop_count += 1
            tg.poll_commands(handlers)

            equity = ex.get_balance()
            if equity <= 0:
                time.sleep(cfg.LOOP_SEC)
                continue

            halted, reason = safety.update_and_check(_safety, equity)
            safety.save(_safety)
            if halted:
                # 모든 심볼 포지션 강제 청산
                for sym in list(_positions.keys()):
                    last_price = ex.get_price(sym)
                    _close_current(sym, f"safety_halt: {reason}",
                                   last_price, equity)
                if _loop_count % 60 == 1:
                    tg.send(f"⛔ 정지 중: {reason}")
                time.sleep(cfg.LOOP_SEC)
                continue

            # v14: 심볼별 4H 추세 사전 계산 (cross-asset confluence 용)
            symbol_trends: dict[str, str] = {}  # symbol → 'up' / 'down' / 'flat'
            symbol_dfs: dict[str, tuple] = {}    # symbol → (df15, df1h, df4h)
            for symbol in cfg.SYMBOLS:
                try:
                    df15_raw = ex.get_ohlcv_cached(symbol, "15", 200)
                    df1h_raw = ex.get_ohlcv_cached(symbol, "60", 200)
                    df4h_raw = ex.get_ohlcv_cached(symbol, "240", 200)
                    if any(len(d) < 60 for d in [df15_raw, df1h_raw, df4h_raw]):
                        continue
                    df15, df1h, df4h = strat.compute_indicators(
                        df15_raw, df1h_raw, df4h_raw)
                    symbol_dfs[symbol] = (df15, df1h, df4h)
                    # v6.0: 룰베이스 레짐 분류 (관측 단계 — 거래 결정 미적용)
                    try:
                        reg = rgm.classify(df1h, df4h)
                        if reg:
                            _last_regime[symbol] = reg
                            # 1시간 간격으로 DB 기록 (분류 정확도 사후 검증용)
                            now_ts = time.time()
                            if now_ts - _last_regime_log_ts.get(symbol, 0) > 3600:
                                try:
                                    from intelligence import journal as _ij
                                    _ij.log_regime(
                                        bot_id=ai.BOT_ID, asset=symbol,
                                        regime=reg["regime"],
                                        confidence=reg["confidence"],
                                        summary=(
                                            f"adx_4h={reg['adx_4h']} "
                                            f"adx_1h={reg['adx_1h']} "
                                            f"bb_ratio={reg['bb_ratio']}"
                                        ),
                                        suggested=reg["suggested"],
                                    )
                                    _last_regime_log_ts[symbol] = now_ts
                                except Exception as je:
                                    print(f"[regime log err {symbol}] {je}",
                                          flush=True)
                    except Exception as re:
                        print(f"[regime classify {symbol} err] {re}", flush=True)
                    # 4H 추세 분류
                    r4 = df4h.iloc[-1]
                    ema50 = float(getattr(r4, "ema50", 0))
                    close = float(getattr(r4, "close", 0))
                    if ema50 > 0:
                        diff = (close - ema50) / ema50
                        if diff > 0.005:
                            symbol_trends[symbol] = "up"
                        elif diff < -0.005:
                            symbol_trends[symbol] = "down"
                        else:
                            symbol_trends[symbol] = "flat"
                except Exception as e:
                    print(f"[trend {symbol} err] {e}", flush=True)

            # 심볼별 처리
            for symbol in cfg.SYMBOLS:
                try:
                    api_pos = ex.get_open_positions(symbol)
                    _reconcile_with_exchange(symbol, api_pos)

                    if symbol not in symbol_dfs:
                        continue
                    df15, df1h, df4h = symbol_dfs[symbol]

                    if symbol in _positions:
                        _manage(symbol, df15)
                    else:
                        last_loss = _last_loss_ts.get(symbol, 0.0)
                        if time.time() - last_loss > cfg.COOLDOWN_BARS_LOSS * 15 * 60:
                            snap = ai.market_snapshot(df15, df1h, df4h)

                            # v5.0: STRATEGY_MODE 별 진입 평가
                            mode = cfg.STRATEGY_MODE
                            sig = None

                            if mode in ("D", "BOTH"):
                                # v14/v15: 8-component 신호 검증 데이터 수집
                                cross_agree = _compute_cross_agree(symbol, symbol_trends)
                                funding_hist = ex.get_funding_history(symbol, count=4)
                                funding_now = funding_hist[0] if funding_hist else None
                                funding_24h = funding_hist[3] if (funding_hist and len(funding_hist) >= 4) else None
                                oi_info = ex.get_open_interest_trend(symbol)
                                oi_change_4h = oi_info["change_pct"] if oi_info else None
                                try:
                                    if len(df4h) >= 2:
                                        p_now = float(df4h.iloc[-1].close)
                                        p_past = float(df4h.iloc[-2].close)
                                        price_change_4h = (p_now - p_past) / p_past if p_past > 0 else None
                                    else:
                                        price_change_4h = None
                                except Exception:
                                    price_change_4h = None
                                try:
                                    from . import news as _news
                                    news_sent = _news.get_news_sentiment(symbol)
                                except Exception:
                                    news_sent = None
                                sig = strat.evaluate_entry(
                                    df15, df1h, df4h,
                                    funding_8h_pct=funding_now,
                                    funding_24h_ago=funding_24h,
                                    cross_agree=cross_agree,
                                    oi_change_4h=oi_change_4h,
                                    price_change_4h=price_change_4h,
                                    news_sentiment=news_sent,
                                )

                            # v5.0 MR primary mode (또는 D 가 신호 없을 때 fallback)
                            if not sig and mode in ("MR", "BOTH"):
                                sig = strat.evaluate_mr_entry(df15, df4h)

                            if sig:
                                _try_open(symbol, equity, sig, snap)

                    _maybe_run_regime(symbol, df15, df1h, df4h)
                except Exception as sym_e:
                    print(f"[loop {symbol} err] {sym_e}", flush=True)

            if _loop_count % 10 == 1:
                _heartbeat(equity)
            _maybe_hourly_report(equity)
            _maybe_run_weekly_review()

            time.sleep(cfg.LOOP_SEC)

        except KeyboardInterrupt:
            tg.send("🛑 v15 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[loop err] {e}\n{err}", flush=True)
            tg.send(f"⚠️ v15 오류\n{str(e)[:300]}")
            time.sleep(60)
