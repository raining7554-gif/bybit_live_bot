"""v7 main loop. Wires strategy + exchange + safety + notifier together."""
from __future__ import annotations
import sys
import time
import traceback
from datetime import datetime

import pandas as pd

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


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _build_status_text(equity: float) -> str:
    lines = [
        f"📊 v7 상태 ({_now_str()})",
        f"심볼: {cfg.SYMBOL} | testnet: {cfg.TESTNET}",
        f"잔고: ${equity:,.2f}",
        f"증거금/거래: {cfg.MARGIN_PCT*100:.0f}% | 자본활용: {cfg.CAPITAL_FRACTION*100:.0f}%",
    ]
    if _pos:
        side_kr = "롱" if _pos.get("side") == "Buy" else "숏"
        lines.append(
            f"포지션: {side_kr} entry=${_pos['entry']:.2f} "
            f"stop=${_pos['current_stop']:.2f} lev={_pos['leverage']:.1f}x"
        )
    else:
        lines.append("포지션: 없음")
    if _safety:
        lines.extend(safety.status_lines(_safety, equity))
    return "\n".join(lines)


def _build_score_text(df_15m, df_1h, df_4h) -> str:
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return "데이터 부족"
    from backtest.strategies.strategy_d import _signal_strength
    score, direction = _signal_strength(
        df_15m.iloc[-1], df_1h.iloc[-1], df_4h.iloc[-1])
    lev = strat._leverage_for_score(score)
    return (
        f"📈 시그널 점수\n"
        f"방향: {direction}\n"
        f"점수: {score:.1f} / 100\n"
        f"진입 임계: {cfg.ENTRY_MIN_SCORE:.0f}\n"
        f"매핑 레버리지: {lev:.1f}x"
        + ("" if lev > 0 else " (진입 X)")
    )


def _close_current(reason: str, fill_price: float, equity_before: float):
    """Close active position (uses _pos)."""
    global _pos, _last_loss_ts
    if not _pos:
        return
    ok = ex.close_position_market(cfg.SYMBOL, _pos["side"], _pos["size"])
    if not ok:
        tg.send(f"⚠️ {cfg.SYMBOL} 청산 실패 (reason={reason}) — 다음 루프 재시도")
        return
    side = _pos["side"]
    entry = _pos["entry"]
    pnl_pct = (fill_price - entry) / entry if side == "Buy" else (entry - fill_price) / entry
    notional = _pos["size"] * entry
    pnl_dollar = notional * pnl_pct
    emoji = "✅" if pnl_dollar >= 0 else "❌"
    tg.send(
        f"{emoji} {cfg.SYMBOL} 청산 ({reason})\n"
        f"방향: {'롱' if side=='Buy' else '숏'}\n"
        f"진입→청산: ${entry:.2f} → ${fill_price:.2f}\n"
        f"PnL: ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"점수: {_pos.get('score', '?')} | 레버리지: {_pos.get('leverage', 0):.1f}x"
    )
    st.log_trade({
        "ts": time.time(),
        "symbol": cfg.SYMBOL, "side": side,
        "entry": entry, "exit": fill_price,
        "size": _pos["size"], "leverage": _pos.get("leverage", 0),
        "score": _pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": reason,
    })
    if pnl_dollar < 0:
        _last_loss_ts = time.time()
    _pos.clear()
    st.save(None)


def _try_open(equity: float, signal: dict):
    """Open new position from a signal dict."""
    global _pos
    side = signal["side"]
    lev = signal["leverage"]
    entry_price = ex.get_price(cfg.SYMBOL)
    if entry_price <= 0:
        return

    # 1) Set leverage on Bybit
    if not ex.set_leverage(cfg.SYMBOL, lev):
        tg.send(f"⚠️ 레버리지 설정 실패 → 진입 보류")
        return

    # 2) Compute qty + disaster SL
    qty = strat.calc_qty(equity, lev, entry_price, cfg.SYMBOL)
    if qty <= 0:
        return
    disaster_sl = entry_price * (1 - cfg.DISASTER_SL_PCT) if side == "Buy" \
                  else entry_price * (1 + cfg.DISASTER_SL_PCT)

    # 3) Place market order
    ok, oid = ex.place_market_order(cfg.SYMBOL, side, qty, disaster_sl)
    if not ok:
        tg.send(f"⚠️ {cfg.SYMBOL} 진입 실패: {oid[:200]}")
        return

    # 4) Tighten SL to strategy stop if it's tighter than disaster SL
    strat_stop = signal["stop_price"]
    final_stop = max(strat_stop, disaster_sl) if side == "Buy" else min(strat_stop, disaster_sl)
    ex.update_stop_loss(cfg.SYMBOL, side, final_stop)

    # 5) Build local pos
    _pos.update({
        "side": side, "entry": entry_price, "size": qty,
        "leverage": lev, "score": signal["score"],
        "init_stop": signal["stop_price"], "current_stop": final_stop,
        "be_done": False, "atr_15m": signal["atr_15m"],
        "opened_ts": time.time(),
    })
    st.save(_pos)
    tg.send(
        f"📈 {cfg.SYMBOL} 진입 ({'롱' if side=='Buy' else '숏'})\n"
        f"점수: {signal['score']:.1f} → 레버리지 {lev:.1f}x\n"
        f"가격: ${entry_price:.2f} | qty: {qty}\n"
        f"손절: ${final_stop:.2f} ({(final_stop/entry_price-1)*100:+.2f}%)\n"
        f"잔고: ${equity:,.2f} | 증거금: ${equity*cfg.MARGIN_PCT*cfg.CAPITAL_FRACTION:,.2f}"
    )


def _manage(df_15m: pd.DataFrame):
    """Update trailing stop on existing position."""
    if not _pos:
        return
    last_high = df_15m["high"].iloc[-1]
    last_low = df_15m["low"].iloc[-1]
    atr_15m = df_15m["atr"].iloc[-1] if "atr" in df_15m.columns else _pos.get("atr_15m", 0)
    new_stop = strat.evaluate_position_management(_pos, atr_15m, last_high, last_low)
    if new_stop is not None:
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
    tg.send(
        f"{emoji} {cfg.SYMBOL} 외부 청산 감지 (server_stop)\n"
        f"방향: {'롱' if side == 'Buy' else '숏'}\n"
        f"진입→마지막가: ${entry:.2f} → ${last_price:.2f}\n"
        f"PnL: ${pnl_dollar:+.2f} ({pnl_pct*100:+.2f}%)\n"
        f"점수: {_pos.get('score', '?')} | 레버리지: {_pos.get('leverage', 0):.1f}x"
    )
    st.log_trade({
        "ts": time.time(),
        "symbol": cfg.SYMBOL, "side": side,
        "entry": entry, "exit": last_price,
        "size": size, "leverage": _pos.get("leverage", 0),
        "score": _pos.get("score", 0),
        "pnl": round(pnl_dollar, 4), "pnl_pct": round(pnl_pct, 6),
        "reason": "server_stop",
    })
    if pnl_dollar < 0:
        _last_loss_ts = time.time()
    _pos.clear()
    st.save(None)


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
        "/halt":    halt,
        "/resume":  resume,
    }


def _heartbeat(equity: float):
    print(f"[{_now_str()}] 💓 loop #{_loop_count} | eq=${equity:.2f} | pos={'Y' if _pos else 'N'}",
          flush=True)


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
    print(f"[v7 boot] stage 6: telegram send", flush=True)
    handlers = _setup_handlers()
    tg.send(
        f"🚀 v7 시작\n"
        f"심볼: {cfg.SYMBOL} | testnet: {cfg.TESTNET}\n"
        f"잔고: ${eq0:,.2f} | 가격: ${px0:,.2f}\n"
        f"증거금: {cfg.MARGIN_PCT*100:.0f}% × 동적레버리지 (2.5/4.0/5.5x)\n"
        f"진입 임계: 점수 {cfg.ENTRY_MIN_SCORE:.0f}\n"
        f"안전: 일{safety.DAILY_LOSS_LIMIT_PCT*100:.0f}% / 주{safety.WEEKLY_LOSS_LIMIT_PCT*100:.0f}% / 월{safety.MONTHLY_LOSS_LIMIT_PCT*100:.0f}%\n"
        f"명령: /status /score /halt /resume"
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
                    sig = strat.evaluate_entry(df15, df1h, df4h)
                    if sig:
                        _try_open(equity, sig)

            if _loop_count % 10 == 1:
                _heartbeat(equity)

            time.sleep(cfg.LOOP_SEC)

        except KeyboardInterrupt:
            tg.send("🛑 v7 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[loop err] {e}\n{err}", flush=True)
            tg.send(f"⚠️ v7 오류\n{str(e)[:300]}")
            time.sleep(60)
