"""v12 main loop — multi-symbol Strategy D + MR.

심볼별 독립 포지션. 같은 D 전략을 N개 심볼에 적용. calc_qty 가 마진을
N등분 하므로 총 노출은 단일 심볼 시절과 동일.
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
from . import safety
from . import state as st
from . import strategy as strat


# ── 글로벌 상태 (계정 레벨) ────────────────────────────────────
_safety = None
_loop_count = 0
_last_report_kst_hour: int = -1
_last_regime_call_ts: dict[str, float] = {}    # symbol → last regime call ts
_last_weekly_review_kst: str = ""

# ── 심볼별 상태 ────────────────────────────────────────────────
_positions: dict[str, dict] = {}        # symbol → 포지션 dict
_last_loss_ts: dict[str, float] = {}    # symbol → 마지막 손절 시각 (cooldown)


KST = timezone(timedelta(hours=9))


def _now_str() -> str:
    return datetime.now(KST).strftime("%H:%M:%S KST")


def _short(symbol: str) -> str:
    """BTCUSDT → BTC (메시지 prefix 용)."""
    return symbol.replace("USDT", "").replace("USD", "") or symbol


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
        f"📊 v12 상태 ({_now_str()})",
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
    side = signal["side"]
    lev = signal["leverage"]
    is_mr = bool(signal.get("mr"))
    entry_price = ex.get_price(symbol)
    if entry_price <= 0:
        return

    if not ex.set_leverage(symbol, lev):
        tg.send(f"⚠️ [{_short(symbol)}] 레버리지 설정 실패 → 진입 보류")
        return

    sizing_tier = "mr" if is_mr else signal.get("tier", "base")
    qty = strat.calc_qty(equity, lev, entry_price, symbol, tier=sizing_tier)
    if qty <= 0:
        return
    disaster_sl = entry_price * (1 - cfg.DISASTER_SL_PCT) if side == "Buy" \
                  else entry_price * (1 + cfg.DISASTER_SL_PCT)

    ok, oid = ex.place_market_order(symbol, side, qty, disaster_sl)
    if not ok:
        tg.send(f"⚠️ [{_short(symbol)}] 진입 실패: {oid[:200]}")
        return

    strat_stop = signal["stop_price"]
    final_stop = max(strat_stop, disaster_sl) if side == "Buy" \
                 else min(strat_stop, disaster_sl)
    ex.update_stop_loss(symbol, side, final_stop)

    _positions[symbol] = {
        "side": side, "entry": entry_price, "size": qty,
        "leverage": lev, "score": signal["score"],
        "init_stop": signal["stop_price"], "current_stop": final_stop,
        "be_done": False, "scale_done": False, "atr_15m": signal["atr_15m"],
        "tp_price": signal.get("tp_price"),
        "tier": signal.get("tier", "high"),
        "tp_margin": signal.get("tp_margin"),
        "strategy": "MR" if is_mr else "D",
        "opened_ts": time.time(),
        "entry_snapshot": snapshot or {},
        "symbol": symbol,
    }
    st.save_all(_positions)

    side_kr = "롱" if side == "Buy" else "숏"
    icon = "〰️ MR" if is_mr else "📈 D"
    tg.send(
        f"{icon} [{_short(symbol)}] {side_kr} 진입 ({lev:.0f}x)\n"
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
        partial_qty = pos["size"] * ratio
        if ex.partial_close_market(symbol, pos["side"], partial_qty):
            pos["size"] -= partial_qty
            pos["scale_done"] = True
            st.save_all(_positions)
            new_eq = ex.get_balance()
            today_d, _ = _today_pnl(new_eq)
            tg.send(
                f"🟦 [{_short(symbol)}] TP1 부분익절 50%\n"
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

    return {
        "/status":  status,
        "/score":   score_cmd,
        "/ai":      ai_cmd,
        "/review":  review_cmd,
        "/propose": propose_cmd,
        "/lessons": lessons_cmd,
        "/halt":    halt,
        "/resume":  resume,
    }


def _heartbeat(equity: float):
    pos_str = ",".join(_short(s) for s in _positions.keys()) or "-"
    print(f"[{_now_str()}] 💓 #{_loop_count} eq=${equity:.2f} pos={pos_str}",
          flush=True)


# ── 주기 작업 ───────────────────────────────────────────────────
def _maybe_run_regime(symbol: str, df15, df1h, df4h):
    """심볼별 레짐 분류 (1시간 간격)."""
    if not cfg.AI_ENABLED or not cfg.GEMINI_API_KEY:
        return
    last = _last_regime_call_ts.get(symbol, 0.0)
    if time.time() - last < cfg.AI_REGIME_INTERVAL_SEC:
        return
    _last_regime_call_ts[symbol] = time.time()
    snap = ai.market_snapshot(df15, df1h, df4h)
    ai.detect_regime_async(snap, asset=symbol, send_telegram=True)


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
    reg = ai.get_last_regime()
    if reg:
        msg += (
            f"\n🧠 레짐: {reg.get('regime', '?')} "
            f"({float(reg.get('confidence', 0))*100:.0f}%) → {reg.get('suggested', '?')}"
        )
    tg.send(msg)


# ── 메인 루프 ──────────────────────────────────────────────────
def main():
    global _safety, _loop_count

    print(f"[v12 boot] stage 1: env check", flush=True)
    print(f"  BYBIT_API_KEY: {'set' if cfg.API_KEY else 'MISSING'}", flush=True)
    print(f"  TG_TOKEN: {'set' if cfg.TG_TOKEN else 'MISSING'}", flush=True)
    print(f"  SYMBOLS={cfg.SYMBOLS} TESTNET={cfg.TESTNET}", flush=True)
    print(f"  CAPITAL_FRACTION={cfg.CAPITAL_FRACTION}", flush=True)

    if not cfg.API_KEY or not cfg.API_SECRET:
        print("❌ FATAL: BYBIT_API_KEY / BYBIT_API_SECRET required — exiting",
              flush=True)
        sys.exit(1)

    print(f"╔════════════════════════════════════════╗", flush=True)
    print(f"║  Bybit Bot v12 — Multi-Symbol Strategy ║", flush=True)
    print(f"║  symbols={','.join(cfg.SYMBOLS)}", flush=True)
    print(f"╚════════════════════════════════════════╝", flush=True)

    print(f"[v12 boot] stage 2: exchange init", flush=True)
    try:
        ex.init()
    except Exception as e:
        print(f"❌ FATAL: exchange.init failed: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    print(f"[v12 boot] stage 3: state restore", flush=True)
    _safety = safety.load()
    _restore_from_state()

    print(f"[v12 boot] stage 4: API smoke test", flush=True)
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
        f"🚀 v12 시작 — 다중 심볼 ({n}종)\n"
        f"봇: {bot_label}\n"
        f"심볼: {sym_label} | 잔고: ${eq0:,.2f}\n"
        f"━ D 전략 (점수→tier별 차등) ━\n"
        f"  심볼당 마진 = 단일 모드 / {n} (총 노출 동일)\n"
        f"  55-59 → 3x  / probe / TP +2%\n"
        f"  60-69 → 5x  / probe / TP +3%\n"
        f"  70-79 → 10x / base  / TP +6%\n"
        f"  80-89 → 15x / mid   / TP1 +10% → 3.0×ATR 트레일\n"
        f"  90+   → 20x / high  / 4.0×ATR 트레일\n"
        f"━ MR (평균회귀) — 5x / BB 중간선 TP\n"
        f"━ 안전 ━\n"
        f"자동 정지 OFF (수동 /halt)\n"
        f"서버사이드 -2% SL 부착\n"
        f"명령: /status /score /ai /review /propose /lessons /halt /resume\n"
        f"⏰ KST 정각 리포트\n"
        f"🧠 AI: {'ON (' + cfg.AI_MODEL + ')' if (cfg.AI_ENABLED and cfg.GEMINI_API_KEY) else 'OFF'}"
    )
    print(f"[v12 boot] startup complete — entering main loop", flush=True)

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

            # 심볼별 처리
            for symbol in cfg.SYMBOLS:
                try:
                    api_pos = ex.get_open_positions(symbol)
                    _reconcile_with_exchange(symbol, api_pos)

                    df15_raw = ex.get_ohlcv_cached(symbol, "15", 200)
                    df1h_raw = ex.get_ohlcv_cached(symbol, "60", 200)
                    df4h_raw = ex.get_ohlcv_cached(symbol, "240", 200)
                    if any(len(d) < 60 for d in [df15_raw, df1h_raw, df4h_raw]):
                        continue
                    df15, df1h, df4h = strat.compute_indicators(
                        df15_raw, df1h_raw, df4h_raw)

                    if symbol in _positions:
                        _manage(symbol, df15)
                    else:
                        last_loss = _last_loss_ts.get(symbol, 0.0)
                        if time.time() - last_loss > cfg.COOLDOWN_BARS_LOSS * 15 * 60:
                            snap = ai.market_snapshot(df15, df1h, df4h)
                            sig = strat.evaluate_entry(df15, df1h, df4h)
                            if sig:
                                _try_open(symbol, equity, sig, snap)
                            else:
                                mr_sig = strat.evaluate_mr_entry(df15, df4h)
                                if mr_sig:
                                    _try_open(symbol, equity, mr_sig, snap)

                    _maybe_run_regime(symbol, df15, df1h, df4h)
                except Exception as sym_e:
                    print(f"[loop {symbol} err] {sym_e}", flush=True)

            if _loop_count % 10 == 1:
                _heartbeat(equity)
            _maybe_hourly_report(equity)
            _maybe_run_weekly_review()

            time.sleep(cfg.LOOP_SEC)

        except KeyboardInterrupt:
            tg.send("🛑 v12 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[loop err] {e}\n{err}", flush=True)
            tg.send(f"⚠️ v12 오류\n{str(e)[:300]}")
            time.sleep(60)
