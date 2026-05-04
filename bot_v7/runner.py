"""v7 main loop. Wires strategy + exchange + safety + notifier together."""
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


_pos: dict = {}            # in-memory active position dict (or empty)
_last_loss_ts: float = 0.0  # cooldown after a stop
_safety = None             # SafetyState
_loop_count = 0
_last_report_kst_hour: int = -1  # KST hour we last sent the hourly report for
_last_regime_call_ts: float = 0.0  # last AI regime detection call


KST = timezone(timedelta(hours=9))


def _now_str() -> str:
    return datetime.now(KST).strftime("%H:%M:%S KST")


def _compute_stats(window_sec: int) -> tuple[int, int, float]:
    """Read trade log, return (wins, losses, total_pnl) for trades exited
    within the last window_sec seconds. Used for hourly report.
    """
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
    """Returns (today_pnl_dollar, today_pnl_pct) using safety day_anchor."""
    if not _safety or _safety.day_anchor_equity <= 0:
        return 0.0, 0.0
    diff = equity - _safety.day_anchor_equity
    pct = diff / _safety.day_anchor_equity
    return diff, pct


def _build_status_text(equity: float) -> str:
    today_d, today_pct = _today_pnl(equity)
    lines = [
        f"📊 v9 상태 ({_now_str()})",
        f"잔고: ${equity:,.2f} (오늘 ${today_d:+.2f} / {today_pct*100:+.2f}%)",
    ]
    if _pos:
        side_kr = "롱" if _pos.get("side") == "Buy" else "숏"
        lev = _pos.get("leverage", 0)
        strategy_name = _pos.get("strategy", "D")
        lines.append(f"포지션: {strategy_name} {side_kr} ({lev:.0f}x)")
    else:
        lines.append("포지션: 없음")
    if _safety:
        lines.extend(safety.status_lines(_safety, equity))
    return "\n".join(lines)


def _build_score_text(df_15m, df_1h, df_4h) -> str:
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return "데이터 부족"
    from backtest.strategies.strategy_d import _signal_strength
    from backtest.strategies.strategy_mr import _check_signal as mr_check
    row, rh1, rh4 = df_15m.iloc[-1], df_1h.iloc[-1], df_4h.iloc[-1]
    score, direction = _signal_strength(row, rh1, rh4)
    lev = strat._leverage_for_score(score)
    mr_side, mr_reason = mr_check(row, rh4)
    return (
        f"📈 시그널 점수\n"
        f"━ D (추세) ━\n"
        f"방향: {direction}\n"
        f"점수: {score:.1f} / 100\n"
        f"진입 임계: {cfg.ENTRY_MIN_SCORE:.0f}\n"
        f"매핑 레버리지: {lev:.1f}x"
        + ("" if lev > 0 else " (진입 X)") + "\n"
        f"━ MR (평균회귀) ━\n"
        f"신호: {mr_side}\n"
        f"이유: {mr_reason}\n"
        f"━ 시장 데이터 ━\n"
        f"ADX: {row.adx:.1f} | BB폭: {row.bb_width*100:.2f}% | "
        f"BB위치: {row.bb_pos*100:.0f}%\n"
        f"RSI: {row.rsi:.0f} | 거래량: {row.vol_ratio:.2f}x"
    )


_REASON_KR = {
    "fixed_tp": "TP", "tp": "TP", "scale_out": "TP1",
    "trail": "트레일", "sl": "손절", "mr_tp": "MR_TP",
    "server_stop": "서버손절", "flash": "급락", "manual": "수동",
}


def _close_current(reason: str, fill_price: float, equity_before: float):
    """Close active position (uses _pos). Simplified message."""
    global _pos, _last_loss_ts
    if not _pos:
        return
    ok = ex.close_position_market(cfg.SYMBOL, _pos["side"], _pos["size"])
    if not ok:
        tg.send(f"⚠️ 청산 실패 ({reason}) — 다음 루프 재시도")
        return
    side = _pos["side"]
    entry = _pos["entry"]
    pnl_pct = (fill_price - entry) / entry if side == "Buy" else (entry - fill_price) / entry
    notional = _pos["size"] * entry
    pnl_dollar = notional * pnl_pct
    emoji = "✅" if pnl_dollar >= 0 else "❌"

    rec = {
        "ts": time.time(),
        "symbol": cfg.SYMBOL, "side": side,
        "entry": entry, "exit": fill_price,
        "size": _pos["size"], "leverage": _pos.get("leverage", 0),
        "score": _pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": reason, "tier": _pos.get("tier", "?"),
        "strategy": _pos.get("strategy", "D"),
    }
    st.log_trade(rec)
    entry_snapshot = _pos.get("entry_snapshot") or {}
    if pnl_dollar < 0:
        _last_loss_ts = time.time()
    _pos.clear()
    st.save(None)

    # Best-effort post-mortem (background thread, no-op if AI disabled)
    ai.analyze_trade_async(rec, entry_snapshot)

    # Refresh today's PnL after this trade settles into balance
    new_eq = ex.get_balance() or equity_before + pnl_dollar
    today_d, _ = _today_pnl(new_eq)
    label = _REASON_KR.get(reason, reason)
    tg.send(
        f"{emoji} {label} 청산 ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
    )


def _try_open(equity: float, signal: dict, snapshot: dict | None = None):
    """Open new position from a signal dict (D or MR).

    `snapshot` is the indicator-state snapshot at entry time, attached to the
    in-memory position so that the post-mortem at close time has the original
    market context to reason from.
    """
    global _pos
    side = signal["side"]
    lev = signal["leverage"]
    is_mr = bool(signal.get("mr"))
    entry_price = ex.get_price(cfg.SYMBOL)
    if entry_price <= 0:
        return

    if not ex.set_leverage(cfg.SYMBOL, lev):
        tg.send(f"⚠️ 레버리지 설정 실패 → 진입 보류")
        return

    # v9: tier-aware sizing (per-tier margin %)
    sizing_tier = "mr" if is_mr else signal.get("tier", "base")
    qty = strat.calc_qty(equity, lev, entry_price, cfg.SYMBOL, tier=sizing_tier)
    if qty <= 0:
        return
    disaster_sl = entry_price * (1 - cfg.DISASTER_SL_PCT) if side == "Buy" \
                  else entry_price * (1 + cfg.DISASTER_SL_PCT)

    ok, oid = ex.place_market_order(cfg.SYMBOL, side, qty, disaster_sl)
    if not ok:
        tg.send(f"⚠️ {cfg.SYMBOL} 진입 실패: {oid[:200]}")
        return

    strat_stop = signal["stop_price"]
    final_stop = max(strat_stop, disaster_sl) if side == "Buy" else min(strat_stop, disaster_sl)
    ex.update_stop_loss(cfg.SYMBOL, side, final_stop)

    tp_price = signal.get("tp_price")          # MR only — fixed BB-mid price target
    tier = signal.get("tier", "high")           # D only — used by exit policy
    tp_margin = signal.get("tp_margin")         # D only — margin-% target or None

    _pos.update({
        "side": side, "entry": entry_price, "size": qty,
        "leverage": lev, "score": signal["score"],
        "init_stop": signal["stop_price"], "current_stop": final_stop,
        "be_done": False, "scale_done": False, "atr_15m": signal["atr_15m"],
        "tp_price": tp_price,                   # MR price-based TP
        "tier": tier,
        "tp_margin": tp_margin,
        "strategy": "MR" if is_mr else "D",
        "opened_ts": time.time(),
        "entry_snapshot": snapshot or {},
    })
    st.save(_pos)

    side_kr = "롱" if side == "Buy" else "숏"
    if is_mr:
        tg.send(f"〰️ MR {side_kr} 진입 ({lev:.0f}x)\n"
                f"잔고: ${equity:,.2f}  진입가: ${entry_price:,.2f}")
    else:
        tg.send(f"📈 D {side_kr} 진입 ({lev:.0f}x)\n"
                f"잔고: ${equity:,.2f}  진입가: ${entry_price:,.2f}")


def _manage(df_15m: pd.DataFrame):
    """Tier-aware exit management. v8.

    MR  : static stop + fixed BB-mid TP price target (manual close on touch)
    D   : tier-based exit policy
        micro/probe/base : margin-% TP target → full close
        mid              : margin-% TP1 → 50% partial close → BE+chandelier rest
        high             : BE @ +1R → chandelier trail (no fixed TP)
    """
    if not _pos:
        return
    if _pos.get("strategy") == "MR":
        tp = _pos.get("tp_price")
        if tp:
            cur_px = float(df_15m["close"].iloc[-1])
            if (_pos["side"] == "Buy" and cur_px >= tp) or \
               (_pos["side"] == "Sell" and cur_px <= tp):
                _close_current("mr_tp", cur_px, ex.get_balance())
        return

    # D strategy
    last_high = float(df_15m["high"].iloc[-1])
    last_low  = float(df_15m["low"].iloc[-1])
    cur_px    = float(df_15m["close"].iloc[-1])
    atr_15m   = float(df_15m["atr"].iloc[-1]) if "atr" in df_15m.columns else _pos.get("atr_15m", 0)

    decision = strat.evaluate_position_management(_pos, atr_15m, cur_px, last_high, last_low)
    if not decision:
        return
    act = decision.get("action")

    if act == "close":
        _close_current(decision.get("reason", "tp"), cur_px, ex.get_balance())
        return

    if act == "scale_out":
        ratio = float(decision.get("ratio", 0.5))
        partial_qty = _pos["size"] * ratio
        if ex.partial_close_market(cfg.SYMBOL, _pos["side"], partial_qty):
            _pos["size"] -= partial_qty
            _pos["scale_done"] = True
            st.save(_pos)
            new_eq = ex.get_balance()
            today_d, _ = _today_pnl(new_eq)
            tg.send(
                f"🟦 TP1 부분익절 50%\n"
                f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
            )
        return

    if act == "modify_stop":
        new_stop = float(decision["stop"])
        if ex.update_stop_loss(cfg.SYMBOL, _pos["side"], new_stop):
            _pos["current_stop"] = new_stop
            st.save(_pos)


def _reconcile_with_exchange(api_pos):
    """Detect that the server-side SL fired (position no longer exists).

    BUG FIX: previously called _close_current which tried to place another
    close order on a position that was already gone, looping and spamming
    Telegram on each iteration. Now we just record the server-side close
    locally without re-issuing a market order.
    """
    global _pos, _last_loss_ts
    if not _pos:
        return
    if api_pos is not None:
        return  # position still open

    last_price = ex.get_price(cfg.SYMBOL)
    side = _pos.get("side", "Buy")
    entry = float(_pos.get("entry", 0))
    size = float(_pos.get("size", 0))
    if entry <= 0 or last_price <= 0 or size <= 0:
        # State corrupt — just clear and move on
        _pos.clear()
        st.save(None)
        return
    if side == "Buy":
        pnl_pct = (last_price - entry) / entry
    else:
        pnl_pct = (entry - last_price) / entry
    pnl_dollar = (size * entry) * pnl_pct
    emoji = "✅" if pnl_dollar >= 0 else "❌"
    rec = {
        "ts": time.time(),
        "symbol": cfg.SYMBOL, "side": side,
        "entry": entry, "exit": last_price,
        "size": size, "leverage": _pos.get("leverage", 0),
        "score": _pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": "server_stop", "tier": _pos.get("tier", "?"),
        "strategy": _pos.get("strategy", "D"),
    }
    st.log_trade(rec)
    entry_snapshot = _pos.get("entry_snapshot") or {}
    if pnl_dollar < 0:
        _last_loss_ts = time.time()
    _pos.clear()
    st.save(None)
    ai.analyze_trade_async(rec, entry_snapshot)
    new_eq = ex.get_balance()
    today_d, _ = _today_pnl(new_eq)
    tg.send(
        f"{emoji} 서버손절 청산 ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"잔고: ${new_eq:,.2f} (오늘 ${today_d:+.2f})"
    )


def _restore_from_state():
    global _pos
    saved = st.load()
    if saved and saved.get("side"):
        _pos.update(saved)
        tg.send(f"🔄 저장된 포지션 복구: {_pos.get('side')} entry=${_pos.get('entry'):.2f}")


def _setup_handlers():
    def status():
        eq = ex.get_balance()
        tg.send(_build_status_text(eq))

    def score_cmd():
        df15 = ex.get_ohlcv_cached(cfg.SYMBOL, "15", 200)
        df1h = ex.get_ohlcv_cached(cfg.SYMBOL, "60", 200)
        df4h = ex.get_ohlcv_cached(cfg.SYMBOL, "240", 200)
        if any(len(d) < 60 for d in [df15, df1h, df4h]):
            tg.send("데이터 부족")
            return
        d15, d1h, d4h = strat.compute_indicators(df15, df1h, df4h)
        tg.send(_build_score_text(d15, d1h, d4h))

    def ai_cmd():
        """Force a fresh regime classification and post it."""
        if not cfg.AI_ENABLED or not cfg.GEMINI_API_KEY:
            tg.send("AI 비활성 (GEMINI_API_KEY + AI_ENABLED=true 필요)")
            return
        df15 = ex.get_ohlcv_cached(cfg.SYMBOL, "15", 200)
        df1h = ex.get_ohlcv_cached(cfg.SYMBOL, "60", 200)
        df4h = ex.get_ohlcv_cached(cfg.SYMBOL, "240", 200)
        if any(len(d) < 60 for d in [df15, df1h, df4h]):
            tg.send("데이터 부족")
            return
        d15, d1h, d4h = strat.compute_indicators(df15, df1h, df4h)
        snap = ai.market_snapshot(d15, d1h, d4h)
        tg.send("🧠 레짐 분석 중...")
        ai.detect_regime_async(snap, send_telegram=True, verbose_errors=True)

    def halt():
        global _safety
        if not _safety:
            return
        # Force a 24h halt manually
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

    return {
        "/status":  status,
        "/score":   score_cmd,
        "/ai":      ai_cmd,
        "/halt":    halt,
        "/resume":  resume,
    }


def _heartbeat(equity: float):
    print(f"[{_now_str()}] 💓 loop #{_loop_count} | eq=${equity:.2f} | pos={'Y' if _pos else 'N'}",
          flush=True)


def _maybe_run_regime(df15, df1h, df4h):
    """Periodic AI regime classification. Posts to Telegram on each refresh
    so user gets a market-context message alongside hourly stats."""
    global _last_regime_call_ts
    if not cfg.AI_ENABLED or not cfg.GEMINI_API_KEY:
        return
    if time.time() - _last_regime_call_ts < cfg.AI_REGIME_INTERVAL_SEC:
        return
    _last_regime_call_ts = time.time()
    snap = ai.market_snapshot(df15, df1h, df4h)
    ai.detect_regime_async(snap, send_telegram=True)


def _maybe_hourly_report(equity: float, df15, df1h, df4h):
    """v9 simplified KST hourly report.
    Shows: balance, today PnL, position brief, 24h W/L/PnL, 7d W/L/PnL.
    """
    global _last_report_kst_hour
    now_kst = datetime.now(KST)
    if now_kst.minute >= 5:
        return
    if now_kst.hour == _last_report_kst_hour:
        return
    _last_report_kst_hour = now_kst.hour

    today_d, today_pct = _today_pnl(equity)

    # Position brief (no entry price / no score / no market data)
    if _pos:
        side_kr = "롱" if _pos.get("side") == "Buy" else "숏"
        strategy_name = _pos.get("strategy", "D")
        lev = _pos.get("leverage", 0)
        entry = _pos.get("entry", 0)
        size = _pos.get("size", 0)
        cur_px = float(df15.iloc[-1].close) if len(df15) > 0 else entry
        cur_pnl_pct = (cur_px - entry) / entry if _pos.get("side") == "Buy" else (entry - cur_px) / entry
        cur_pnl_d = (size * entry) * cur_pnl_pct
        pos_line = (f"포지션: {strategy_name} {side_kr} ({lev:.0f}x) "
                    f"${cur_pnl_d:+.2f} ({cur_pnl_pct*100:+.2f}%)")
    else:
        pos_line = "포지션: 없음"

    w24, l24, p24 = _compute_stats(86400)
    w7,  l7,  p7  = _compute_stats(604800)
    n24 = w24 + l24
    n7  = w7  + l7
    wr24 = (w24 / n24 * 100) if n24 > 0 else 0
    wr7  = (w7  / n7  * 100) if n7  > 0 else 0

    msg = (
        f"⏰ {now_kst.strftime('%H:%M')} KST\n"
        f"잔고: ${equity:,.2f} (오늘 ${today_d:+.2f} / {today_pct*100:+.2f}%)\n"
        f"{pos_line}\n"
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


def main():
    global _safety, _loop_count

    # ── Stage 1: env vars ─────────────────────────────────────
    print(f"[v7 boot] stage 1: env check", flush=True)
    print(f"  BYBIT_API_KEY: {'set' if cfg.API_KEY else 'MISSING'} ({len(cfg.API_KEY)} chars)", flush=True)
    print(f"  BYBIT_API_SECRET: {'set' if cfg.API_SECRET else 'MISSING'} ({len(cfg.API_SECRET)} chars)", flush=True)
    print(f"  TG_TOKEN: {'set' if cfg.TG_TOKEN else 'MISSING'} ({len(cfg.TG_TOKEN)} chars)", flush=True)
    print(f"  TG_CHAT_ID: {'set' if cfg.TG_CHAT_ID else 'MISSING'} ({len(cfg.TG_CHAT_ID)} chars)", flush=True)
    print(f"  SYMBOL={cfg.SYMBOL} TESTNET={cfg.TESTNET}", flush=True)
    print(f"  MARGIN_PCT={cfg.MARGIN_PCT} CAPITAL_FRACTION={cfg.CAPITAL_FRACTION}", flush=True)

    if not cfg.API_KEY or not cfg.API_SECRET:
        print("❌ FATAL: BYBIT_API_KEY / BYBIT_API_SECRET required — exiting", flush=True)
        sys.exit(1)

    # ── Stage 2: banner ───────────────────────────────────────
    print(f"╔════════════════════════════════════════╗", flush=True)
    print(f"║  Bybit Bot v7 — Strategy D (dynamic)   ║", flush=True)
    print(f"║  symbol={cfg.SYMBOL} margin={cfg.MARGIN_PCT*100:.0f}% testnet={cfg.TESTNET}", flush=True)
    print(f"╚════════════════════════════════════════╝", flush=True)

    # ── Stage 3: imports + exchange init ──────────────────────
    print(f"[v7 boot] stage 3: exchange init", flush=True)
    try:
        ex.init()
    except Exception as e:
        print(f"❌ FATAL: exchange.init failed: {e}", flush=True)
        import traceback; traceback.print_exc()
        sys.exit(1)

    # ── Stage 4: state ────────────────────────────────────────
    print(f"[v7 boot] stage 4: state restore", flush=True)
    _safety = safety.load()
    _restore_from_state()

    # ── Stage 5: smoke-test API ──────────────────────────────
    print(f"[v7 boot] stage 5: API smoke test", flush=True)
    eq0 = ex.get_balance()
    px0 = ex.get_price(cfg.SYMBOL)
    print(f"  balance=${eq0:.2f}  price={cfg.SYMBOL}=${px0:.2f}", flush=True)
    if eq0 <= 0 or px0 <= 0:
        print(f"⚠️  API returned zeros — credentials/network issue likely", flush=True)

    # ── Stage 6: TG smoke-test ───────────────────────────────
    print(f"[v7 boot] stage 6: telegram identity + send", flush=True)
    me = tg.get_me()
    bot_label = (
        f"@{me.get('username')} (id={me.get('id')})" if me else "unknown"
    )
    handlers = _setup_handlers()
    tg.send(
        f"🚀 v9 시작 — 차등증거금 + 비대칭 익절\n"
        f"봇: {bot_label}\n"
        f"심볼: {cfg.SYMBOL} | 잔고: ${eq0:,.2f}\n"
        f"━ D 전략 (점수→tier별 차등) ━\n"
        f"  55-59 → 3x  / 증거금 30% / TP +2%\n"
        f"  60-69 → 5x  / 증거금 40% / TP +3%\n"
        f"  70-79 → 10x / 증거금 50% / TP +6%\n"
        f"  80-89 → 15x / 증거금 65% / TP1 +10% → 3.0×ATR 트레일\n"
        f"  90+   → 20x / 증거금 80% / 4.0×ATR 트레일 (끝까지)\n"
        f"━ MR (평균회귀) ━\n"
        f"  5x / 증거금 50% / BB 중간선 TP\n"
        f"━ 안전 ━\n"
        f"자동 정지 OFF (수동 /halt 가능)\n"
        f"서버사이드 -2% SL 모든 진입에 부착\n"
        f"명령: /status /score /ai /halt /resume\n"
        f"⏰ KST 정각마다 리포트\n"
        f"🧠 AI: {'ON (' + cfg.AI_MODEL + ')' if (cfg.AI_ENABLED and cfg.GEMINI_API_KEY) else 'OFF'}"
    )
    print(f"[v7 boot] startup complete — entering main loop", flush=True)

    while True:
        try:
            _loop_count += 1
            tg.poll_commands(handlers)

            # 1) Equity + safety check
            equity = ex.get_balance()
            if equity <= 0:
                time.sleep(cfg.LOOP_SEC)
                continue

            halted, reason = safety.update_and_check(_safety, equity)
            safety.save(_safety)
            if halted:
                if _pos:
                    last_price = ex.get_price(cfg.SYMBOL)
                    _close_current(f"safety_halt: {reason}", last_price, equity)
                if _loop_count % 60 == 1:
                    tg.send(f"⛔ 정지 중: {reason}")
                time.sleep(cfg.LOOP_SEC)
                continue

            # 2) Sync with exchange
            api_pos = ex.get_open_positions(cfg.SYMBOL)
            _reconcile_with_exchange(api_pos)

            # 3) Pull data + indicators
            df15_raw = ex.get_ohlcv_cached(cfg.SYMBOL, "15", 200)
            df1h_raw = ex.get_ohlcv_cached(cfg.SYMBOL, "60", 200)
            df4h_raw = ex.get_ohlcv_cached(cfg.SYMBOL, "240", 200)
            if any(len(d) < 60 for d in [df15_raw, df1h_raw, df4h_raw]):
                time.sleep(cfg.LOOP_SEC)
                continue
            df15, df1h, df4h = strat.compute_indicators(df15_raw, df1h_raw, df4h_raw)

            # 4) Manage existing position OR consider entry
            if _pos:
                _manage(df15)
            else:
                # cooldown after a recent stop
                if time.time() - _last_loss_ts > cfg.COOLDOWN_BARS_LOSS * 15 * 60:
                    snap = ai.market_snapshot(df15, df1h, df4h)
                    # D first (high-conviction trend setups)
                    sig = strat.evaluate_entry(df15, df1h, df4h)
                    if sig:
                        _try_open(equity, sig, snap)
                    else:
                        # MR fallback (mean reversion in chop)
                        mr_sig = strat.evaluate_mr_entry(df15, df4h)
                        if mr_sig:
                            _try_open(equity, mr_sig, snap)

            # 5) Periodic heartbeat (stdout, not Telegram)
            if _loop_count % 10 == 1:
                _heartbeat(equity)

            # 6) Hourly Telegram report
            _maybe_hourly_report(equity, df15, df1h, df4h)

            # 7) Periodic AI regime classification (best-effort, async)
            _maybe_run_regime(df15, df1h, df4h)

            time.sleep(cfg.LOOP_SEC)

        except KeyboardInterrupt:
            tg.send("🛑 v7 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[loop err] {e}\n{err}", flush=True)
            tg.send(f"⚠️ v7 오류\n{str(e)[:300]}")
            time.sleep(60)
