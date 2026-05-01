"""v7 main loop. Wires strategy + exchange + safety + notifier together."""
from __future__ import annotations
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

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
_last_report_kst_hour: int = -1  # KST hour we last sent the hourly report for


KST = timezone(timedelta(hours=9))


def _now_str() -> str:
    return datetime.now(KST).strftime("%H:%M:%S KST")


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
    """Open new position from a signal dict (D or MR)."""
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

    qty = strat.calc_qty(equity, lev, entry_price, cfg.SYMBOL)
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
    })
    st.save(_pos)

    if is_mr:
        tg.send(
            f"〰️ {cfg.SYMBOL} MR 진입 ({'롱' if side=='Buy' else '숏'})\n"
            f"전략: 평균회귀 (BB 극단 + 횡보)\n"
            f"가격: ${entry_price:.2f} | qty: {qty} | lev {lev:.1f}x\n"
            f"손절: ${final_stop:.2f} ({(final_stop/entry_price-1)*100:+.2f}%)\n"
            f"익절: ${tp_price:.2f} (BB 중앙선)\n"
            f"잔고: ${equity:,.2f}"
        )
    else:
        tier_kr = {"micro": "마이크로", "probe": "프로브",
                   "base": "베이스", "mid": "미드", "high": "하이"}.get(tier, tier)
        tp_str = (f"+{tp_margin*100:.0f}% 마진" if tp_margin is not None
                  else "트레일만 (고정 TP X)")
        tg.send(
            f"📈 {cfg.SYMBOL} D 진입 ({'롱' if side=='Buy' else '숏'})\n"
            f"점수: {signal['score']:.1f} → tier {tier_kr} (lev {lev:.1f}x)\n"
            f"가격: ${entry_price:.2f} | qty: {qty}\n"
            f"손절: ${final_stop:.2f} ({(final_stop/entry_price-1)*100:+.2f}%)\n"
            f"익절: {tp_str}\n"
            f"잔고: ${equity:,.2f} | 증거금: ${equity*cfg.MARGIN_PCT*cfg.CAPITAL_FRACTION:,.2f}"
        )


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
            tg.send(
                f"🟦 {cfg.SYMBOL} TP1 부분익절 50%\n"
                f"점수 tier {_pos.get('tier','?')} | 남은 수량 {_pos['size']:.4f}\n"
                f"이제 BE → 챈들리어 트레일"
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


def _maybe_hourly_report(equity: float, df15, df1h, df4h):
    """Send a status report on every KST hour mark (XX:00 ~ XX:05 window).

    Fires at most once per KST hour. Window is 5 minutes wide so a 30s
    main loop reliably catches it without missing on slow ticks.
    """
    global _last_report_kst_hour
    now_kst = datetime.now(KST)
    if now_kst.minute >= 5:
        return                          # outside the top-of-hour window
    if now_kst.hour == _last_report_kst_hour:
        return                          # already reported this hour
    _last_report_kst_hour = now_kst.hour

    from backtest.strategies.strategy_d import _signal_strength
    from backtest.strategies.strategy_mr import _check_signal as mr_check
    try:
        score, direction = _signal_strength(df15.iloc[-1], df1h.iloc[-1], df4h.iloc[-1])
        lev = strat._leverage_for_score(score)
    except Exception:
        score, direction, lev = 0.0, "n/a", 0.0
    try:
        mr_side, mr_reason = mr_check(df15.iloc[-1], df4h.iloc[-1])
    except Exception:
        mr_side, mr_reason = "none", "err"

    px = float(df15.iloc[-1].close)

    # Daily PnL anchor (from safety state)
    day_dd = ""
    if _safety and _safety.day_anchor_equity > 0:
        d = (equity - _safety.day_anchor_equity) / _safety.day_anchor_equity
        day_dd = f"오늘 PnL: {d*100:+.2f}% (한도 -3%)"

    pos_line = "포지션: 없음"
    if _pos:
        side_kr = "롱" if _pos.get("side") == "Buy" else "숏"
        entry = _pos.get("entry", 0)
        cur_pnl = (px - entry) / entry if _pos.get("side") == "Buy" else (entry - px) / entry
        notional = _pos.get("size", 0) * entry
        pnl_dollar = notional * cur_pnl
        pos_line = (
            f"포지션: {_pos.get('strategy','?')} {side_kr} "
            f"entry=${entry:.2f} now=${px:.2f}\n"
            f"  PnL: ${pnl_dollar:+.2f} ({cur_pnl*100:+.2f}%) "
            f"lev={_pos.get('leverage',0):.1f}x"
        )

    msg = (
        f"⏰ {now_kst.strftime('%m/%d %H:00 KST')} 리포트\n"
        f"잔고: ${equity:,.2f}\n"
        f"가격: ${px:,.2f}\n"
        f"{day_dd}\n"
        f"D 점수: {score:.1f} (방향: {direction}, 매핑 lev: {lev:.1f}x)\n"
        f"MR 신호: {mr_side} ({mr_reason})\n"
        f"{pos_line}"
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
        f"🚀 v7 시작 (3tier 공격형)\n"
        f"봇: {bot_label}\n"
        f"심볼: {cfg.SYMBOL} | testnet: {cfg.TESTNET}\n"
        f"잔고: ${eq0:,.2f} | 가격: ${px0:,.2f}\n"
        f"━ D 전략 (v8 공격형 + 비대칭 익절) ━\n"
        f"증거금 {cfg.MARGIN_PCT*100:.0f}% × 레버리지 3/5/10/15/20x\n"
        f"  55-59 → 3x  / TP +3% 마진\n"
        f"  60-69 → 5x  / TP +5% 마진\n"
        f"  70-79 → 10x / TP +10% 마진\n"
        f"  80-89 → 15x / TP1 +10% 부분익절 → 트레일\n"
        f"  90+   → 20x / 트레일만 (끝까지)\n"
        f"  4H bias EMA50 (단기 추세) + RSI 체크 X\n"
        f"━ MR 전략 (평균회귀) ━\n"
        f"BB 0.15/0.85 + ADX<30 + RSI 35/65\n"
        f"고정 lev 5.0x, TP=BB 중간선\n"
        f"━ 안전 (사용자 모니터링 가정) ━\n"
        f"일{safety.DAILY_LOSS_LIMIT_PCT*100:.0f}% / 주{safety.WEEKLY_LOSS_LIMIT_PCT*100:.0f}% / 월{safety.MONTHLY_LOSS_LIMIT_PCT*100:.0f}% 자동정지\n"
        f"서버사이드 -2% SL 모든 진입에 부착\n"
        f"명령: /status /score /halt /resume\n"
        f"⏰ KST 정각마다 자동 리포트"
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
                    # D first (high-conviction trend setups)
                    sig = strat.evaluate_entry(df15, df1h, df4h)
                    if sig:
                        _try_open(equity, sig)
                    else:
                        # MR fallback (mean reversion in chop)
                        mr_sig = strat.evaluate_mr_entry(df15, df4h)
                        if mr_sig:
                            _try_open(equity, mr_sig)

            # 5) Periodic heartbeat (stdout, not Telegram)
            if _loop_count % 10 == 1:
                _heartbeat(equity)

            # 6) Hourly Telegram report
            _maybe_hourly_report(equity, df15, df1h, df4h)

            time.sleep(cfg.LOOP_SEC)

        except KeyboardInterrupt:
            tg.send("🛑 v7 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[loop err] {e}\n{err}", flush=True)
            tg.send(f"⚠️ v7 오류\n{str(e)[:300]}")
            time.sleep(60)
