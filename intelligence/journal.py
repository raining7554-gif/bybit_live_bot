"""Bot-agnostic 거래 저널 — SQLite 백엔드.

모든 봇이 같은 인터페이스로 호출. bot_id 컬럼으로 봇별/통합 쿼리 가능.

환경변수:
  INTELLIGENCE_DB_PATH — DB 파일 경로 (기본 /data/intelligence.db)
"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
from typing import Optional

from . import schema


_DB_PATH = os.environ.get("INTELLIGENCE_DB_PATH", "/data/intelligence.db")
_init_lock = threading.Lock()
_initialized = False


def _conn() -> sqlite3.Connection:
    """스레드별 새 connection. 첫 호출시 스키마 초기화."""
    global _initialized
    db_dir = os.path.dirname(_DB_PATH) or "."
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # 동시쓰기 안전성 (멀티 프로세스 / 멀티 스레드)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _initialized:
        with _init_lock:
            if not _initialized:
                conn.executescript(schema.DDL)
                _initialized = True
    return conn


# ── Trade logging ───────────────────────────────────────────────

def log_trade(
    *, bot_id: str, symbol: str, side: str, pnl: float, pnl_pct: float,
    entry_price: Optional[float] = None, exit_price: Optional[float] = None,
    size: Optional[float] = None, leverage: float = 1.0,
    fees: float = 0.0, reason: str = "", strategy: str = "",
    tier: Optional[str] = None, score: Optional[float] = None,
    entry_ts: Optional[int] = None, exit_ts: Optional[int] = None,
    market_snapshot: Optional[dict] = None, extra: Optional[dict] = None,
) -> int:
    """종료된 거래 1건 기록. trade_id 반환."""
    if exit_ts is None:
        exit_ts = int(time.time())
    try:
        conn = _conn()
        cur = conn.execute(
            """
            INSERT INTO trades
              (bot_id, symbol, side, entry_price, exit_price, size, leverage,
               pnl, pnl_pct, fees, reason, strategy, tier, score,
               entry_ts, exit_ts, market_snapshot, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bot_id, symbol, side, entry_price, exit_price, size, leverage,
                pnl, pnl_pct, fees, reason, strategy, tier, score,
                entry_ts, exit_ts,
                json.dumps(market_snapshot, ensure_ascii=False) if market_snapshot else None,
                json.dumps(extra, ensure_ascii=False) if extra else None,
            ),
        )
        return cur.lastrowid or 0
    except Exception as e:
        print(f"[journal log_trade err] {e}", flush=True)
        return 0


# ── Analysis logging ────────────────────────────────────────────

def log_analysis(
    *, bot_id: str, kind: str, content: str,
    trade_id: Optional[int] = None, lesson: Optional[str] = None,
    ts: Optional[int] = None,
) -> int:
    """AI 분석 결과 저장.

    kind: 'postmortem' | 'regime' | 'review' | 'proposal' | 기타
    lesson: 사후분석에서 추출한 1줄 교훈 (선택)
    """
    if ts is None:
        ts = int(time.time())
    try:
        conn = _conn()
        cur = conn.execute(
            """
            INSERT INTO analyses (bot_id, kind, trade_id, content, lesson, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (bot_id, kind, trade_id, content, lesson, ts),
        )
        return cur.lastrowid or 0
    except Exception as e:
        print(f"[journal log_analysis err] {e}", flush=True)
        return 0


def log_regime(
    *, bot_id: str, asset: str, regime: str,
    confidence: Optional[float] = None,
    summary: Optional[str] = None,
    suggested: Optional[str] = None,
    ts: Optional[int] = None,
) -> int:
    if ts is None:
        ts = int(time.time())
    try:
        conn = _conn()
        cur = conn.execute(
            """
            INSERT INTO regimes (bot_id, asset, regime, confidence,
                                 summary, suggested, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (bot_id, asset, regime, confidence, summary, suggested, ts),
        )
        return cur.lastrowid or 0
    except Exception as e:
        print(f"[journal log_regime err] {e}", flush=True)
        return 0


def log_proposal(
    *, bot_id: str, param: str,
    current_value: str, suggested_value: str,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    status: str = "pending",
    ts: Optional[int] = None,
) -> int:
    if ts is None:
        ts = int(time.time())
    try:
        conn = _conn()
        cur = conn.execute(
            """
            INSERT INTO proposals (bot_id, param, current_value, suggested_value,
                                   reason, confidence, status, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bot_id, param, current_value, suggested_value,
             reason, confidence, status, ts),
        )
        return cur.lastrowid or 0
    except Exception as e:
        print(f"[journal log_proposal err] {e}", flush=True)
        return 0


# ── Queries ──────────────────────────────────────────────────────

def recent_trades(*, bot_id: Optional[str] = None,
                  since_seconds: int = 7 * 86400,
                  limit: int = 1000) -> list[dict]:
    """최근 N초 내 거래. bot_id None이면 모든 봇."""
    cutoff = int(time.time()) - since_seconds
    try:
        conn = _conn()
        if bot_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE bot_id=? AND exit_ts>=? "
                "ORDER BY exit_ts DESC LIMIT ?",
                (bot_id, cutoff, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE exit_ts>=? "
                "ORDER BY exit_ts DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[journal recent_trades err] {e}", flush=True)
        return []


def recent_lessons(*, bot_id: Optional[str] = None,
                   limit: int = 10) -> list[dict]:
    """최근 사후분석에서 추출된 lesson들."""
    try:
        conn = _conn()
        if bot_id:
            rows = conn.execute(
                "SELECT bot_id, lesson, ts FROM analyses "
                "WHERE bot_id=? AND kind='postmortem' AND lesson IS NOT NULL "
                "ORDER BY ts DESC LIMIT ?",
                (bot_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT bot_id, lesson, ts FROM analyses "
                "WHERE kind='postmortem' AND lesson IS NOT NULL "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[journal recent_lessons err] {e}", flush=True)
        return []


def recent_regimes(*, bot_id: Optional[str] = None,
                   since_seconds: int = 86400,
                   limit: int = 100) -> list[dict]:
    cutoff = int(time.time()) - since_seconds
    try:
        conn = _conn()
        if bot_id:
            rows = conn.execute(
                "SELECT * FROM regimes WHERE bot_id=? AND ts>=? "
                "ORDER BY ts DESC LIMIT ?",
                (bot_id, cutoff, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM regimes WHERE ts>=? "
                "ORDER BY ts DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[journal recent_regimes err] {e}", flush=True)
        return []


def trade_stats(*, bot_id: Optional[str] = None,
                since_seconds: int = 7 * 86400) -> dict:
    """집계 통계 (사람 읽기용 + AI 프롬프트 컨텍스트용)."""
    trades = recent_trades(bot_id=bot_id, since_seconds=since_seconds, limit=10000)
    if not trades:
        return {"n": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] >= 0)
    losses = n - wins
    total_pnl = sum(t["pnl"] for t in trades)

    by_strategy: dict[str, dict] = {}
    by_reason: dict[str, int] = {}
    by_bot: dict[str, dict] = {}
    by_symbol: dict[str, dict] = {}
    by_tier: dict[str, dict] = {}
    for t in trades:
        s = t.get("strategy") or "?"
        r = t.get("reason") or "?"
        b = t.get("bot_id") or "?"
        sy = t.get("symbol") or "?"
        ti = t.get("tier") or "?"
        ss = by_strategy.setdefault(s, {"n": 0, "wins": 0, "pnl": 0.0})
        ss["n"] += 1
        ss["wins"] += 1 if t["pnl"] >= 0 else 0
        ss["pnl"] += t["pnl"]
        by_reason[r] = by_reason.get(r, 0) + 1
        bb = by_bot.setdefault(b, {"n": 0, "wins": 0, "pnl": 0.0})
        bb["n"] += 1
        bb["wins"] += 1 if t["pnl"] >= 0 else 0
        bb["pnl"] += t["pnl"]
        sym = by_symbol.setdefault(sy, {"n": 0, "wins": 0, "pnl": 0.0})
        sym["n"] += 1
        sym["wins"] += 1 if t["pnl"] >= 0 else 0
        sym["pnl"] += t["pnl"]
        tt = by_tier.setdefault(ti, {"n": 0, "wins": 0, "pnl": 0.0})
        tt["n"] += 1
        tt["wins"] += 1 if t["pnl"] >= 0 else 0
        tt["pnl"] += t["pnl"]

    return {
        "n": n, "wins": wins, "losses": losses,
        "win_rate": wins / n if n > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
        "by_strategy": by_strategy,
        "by_reason": by_reason,
        "by_bot": by_bot,
        "by_symbol": by_symbol,
        "by_tier": by_tier,
    }


def format_symbol_stats(*, bot_id: Optional[str] = None,
                        since_seconds: int = 7 * 86400) -> str:
    """심볼별 성과를 텔레그램용 텍스트로 포매팅."""
    stats = trade_stats(bot_id=bot_id, since_seconds=since_seconds)
    n = stats.get("n", 0)
    if n == 0:
        days = since_seconds // 86400
        scope = bot_id or "all"
        return f"📊 {scope}: 지난 {days}일 거래 없음"

    days = since_seconds // 86400
    scope = bot_id or "all"
    lines = [f"📊 <b>심볼별 성과</b> ({scope}, 지난 {days}일)",
             f"전체: {n}건 / 승률 {stats['win_rate']*100:.0f}% / "
             f"PnL {stats['total_pnl']:+.2f}",
             "─────────"]
    by_sym = stats.get("by_symbol", {})
    # PnL 내림차순
    sorted_syms = sorted(by_sym.items(), key=lambda x: -x[1]["pnl"])
    for sym, s in sorted_syms:
        sn = s["n"]
        sw = s["wins"]
        wr = (sw / sn * 100) if sn > 0 else 0
        icon = "🟢" if s["pnl"] > 0 else ("🔴" if s["pnl"] < 0 else "⚪")
        lines.append(f"{icon} {sym}: {sw}W/{sn-sw}L "
                     f"({wr:.0f}%) PnL {s['pnl']:+.2f}")

    by_tier = stats.get("by_tier", {})
    if by_tier:
        lines.append("─────────")
        lines.append("<b>tier별</b>")
        tier_order = ["high", "mid", "base", "probe", "micro", "mr", "?"]
        for ti in tier_order:
            if ti not in by_tier:
                continue
            t = by_tier[ti]
            tn = t["n"]
            tw = t["wins"]
            wr = (tw / tn * 100) if tn > 0 else 0
            lines.append(f"  {ti}: {tw}W/{tn-tw}L ({wr:.0f}%) {t['pnl']:+.2f}")
    return "\n".join(lines)


def latest_proposals(*, bot_id: Optional[str] = None,
                     status: str = "pending",
                     limit: int = 10) -> list[dict]:
    try:
        conn = _conn()
        if bot_id:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE bot_id=? AND status=? "
                "ORDER BY ts DESC LIMIT ?",
                (bot_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status=? "
                "ORDER BY ts DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[journal latest_proposals err] {e}", flush=True)
        return []


def symbol_weight(*, bot_id: str, symbol: str,
                  days: int = 30, min_trades: int = 3) -> float:
    """심볼별 자동 사이즈 가중치 (Tier 2 자동 학습).

    최근 N일 거래 데이터로 심볼별 승률 + PnL 보고 사이즈 multiplier 계산.

    Returns:
        weight: 0.3 ~ 1.5 (1.0 = 중립)
        - 잘 되는 심볼: > 1.0 (사이즈 boost)
        - 부진 심볼: < 1.0 (사이즈 축소)
        - 데이터 부족: 1.0
    """
    stats = trade_stats(bot_id=bot_id, since_seconds=days * 86400)
    if stats.get("n", 0) < min_trades:
        return 1.0
    by_sym = stats.get("by_symbol", {})
    s = by_sym.get(symbol)
    if not s or s["n"] < min_trades:
        return 1.0

    n = s["n"]
    win_rate = s["wins"] / n
    pnl = s["pnl"]
    pnl_per = pnl / n

    # 승률 기반 weight: 50% = 1.0, 30% = 0.7, 70% = 1.2
    wr_mult = 0.5 + win_rate

    # PnL 부스트/페널티
    if pnl_per >= 5.0:
        pnl_mult = 1.10
    elif pnl_per >= 1.0:
        pnl_mult = 1.05
    elif pnl_per <= -5.0:
        pnl_mult = 0.75
    elif pnl_per <= -1.0:
        pnl_mult = 0.90
    else:
        pnl_mult = 1.0

    weight = wr_mult * pnl_mult
    return max(0.3, min(1.5, weight))


def all_symbol_weights(*, bot_id: str, days: int = 30,
                       min_trades: int = 3) -> dict[str, float]:
    """모든 심볼의 weight 한 번에 계산."""
    stats = trade_stats(bot_id=bot_id, since_seconds=days * 86400)
    out: dict[str, float] = {}
    for sym in stats.get("by_symbol", {}).keys():
        out[sym] = symbol_weight(bot_id=bot_id, symbol=sym,
                                 days=days, min_trades=min_trades)
    return out


def deep_diagnose(*, bot_id: str, days: int = 30) -> str:
    """v4.2: AI 없이 순수 통계로 봇 진단. /diagnose 명령용.

    분석 차원:
      - 기본 통계 (n, win_rate, total_pnl)
      - tier 별 (avg PnL 포함)
      - 심볼별 (PnL 순)
      - 청산 사유별 (TP/SL/trail 분포)
      - 진입 점수: 승리 vs 패배 평균
      - 방향 (long/short)
      - 시간대 (KST 기준 6시간 단위)
      - 핵심 인사이트 자동 도출 (룰 기반)
    """
    import json as _json
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))

    trades = recent_trades(bot_id=bot_id, since_seconds=days * 86400, limit=10000)
    if not trades:
        return f"📊 진단 — 지난 {days}일 거래 없음"

    n = len(trades)
    wins = [t for t in trades if t["pnl"] >= 0]
    losses = [t for t in trades if t["pnl"] < 0]
    win_rate = len(wins) / n
    total_pnl = sum(t["pnl"] for t in trades)

    lines = [
        f"📊 <b>봇 종합 진단</b> ({bot_id}, 지난 {days}일)",
        f"━━━━━━━━━━━━━━━━━",
        f"<b>기본</b>",
        f"총 {n}건 / 승 {len(wins)} / 패 {len(losses)}",
        f"승률 {win_rate*100:.1f}% / PnL {total_pnl:+.2f}",
    ]

    # tier 별
    by_tier: dict[str, list] = {}
    for t in trades:
        ti = t.get("tier") or "?"
        by_tier.setdefault(ti, []).append(t)
    if by_tier:
        lines.append("\n<b>Tier 별</b>")
        order = ["high", "mid", "base", "probe", "micro", "mr", "?"]
        for ti in order:
            if ti not in by_tier:
                continue
            ts = by_tier[ti]
            tn = len(ts)
            tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            avg = tp / tn if tn else 0
            wr = (tw / tn * 100) if tn else 0
            icon = "🟢" if tp > 0 else ("⚪" if tp == 0 else "🔴")
            lines.append(f"  {icon} {ti}: {tn}건 {wr:.0f}% PnL {tp:+.2f} (avg {avg:+.2f})")

    # 심볼별
    by_sym: dict[str, list] = {}
    for t in trades:
        sy = t.get("symbol") or "?"
        by_sym.setdefault(sy, []).append(t)
    if by_sym:
        lines.append("\n<b>심볼별 (PnL 순)</b>")
        items = sorted(by_sym.items(), key=lambda x: -sum(t["pnl"] for t in x[1]))
        for sy, ts in items:
            tn = len(ts)
            tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = (tw / tn * 100) if tn else 0
            icon = "🟢" if tp > 0 else "🔴"
            lines.append(f"  {icon} {sy}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # 방향 (long vs short)
    long_t = [t for t in trades if str(t.get("side", "")).lower() in ("buy", "long")]
    short_t = [t for t in trades if str(t.get("side", "")).lower() in ("sell", "short")]
    if long_t or short_t:
        lines.append("\n<b>방향</b>")
        if long_t:
            ln = len(long_t); lw = sum(1 for t in long_t if t["pnl"] >= 0)
            lp = sum(t["pnl"] for t in long_t)
            lines.append(f"  롱: {ln}건 {lw/ln*100:.0f}% {lp:+.2f}")
        if short_t:
            sn = len(short_t); sw = sum(1 for t in short_t if t["pnl"] >= 0)
            sp = sum(t["pnl"] for t in short_t)
            lines.append(f"  숏: {sn}건 {sw/sn*100:.0f}% {sp:+.2f}")

    # 청산 사유
    by_reason: dict[str, list] = {}
    for t in trades:
        r = t.get("reason") or "?"
        by_reason.setdefault(r, []).append(t)
    if by_reason:
        lines.append("\n<b>청산 사유</b>")
        for r, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            tn = len(ts)
            tp = sum(t["pnl"] for t in ts)
            pct = tn / n * 100
            lines.append(f"  {r}: {tn}건 ({pct:.0f}%) PnL {tp:+.2f}")

    # 점수 비교
    win_scores = [t.get("score") for t in wins if t.get("score")]
    loss_scores = [t.get("score") for t in losses if t.get("score")]
    if win_scores and loss_scores:
        lines.append("\n<b>진입 점수</b>")
        avg_win = sum(win_scores) / len(win_scores)
        avg_loss = sum(loss_scores) / len(loss_scores)
        diff = avg_win - avg_loss
        lines.append(f"  승리 평균: {avg_win:.1f}")
        lines.append(f"  패배 평균: {avg_loss:.1f}")
        lines.append(f"  차이: {diff:+.1f} {'⚠️ 약함' if abs(diff) < 5 else '✅'}")

    # 시간대 (KST)
    by_hour_bucket: dict[str, list] = {}
    for t in trades:
        ts_unix = t.get("exit_ts") or t.get("ts") or 0
        try:
            dt = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc).astimezone(KST)
            h = dt.hour
            if h < 6: bucket = "00~06"
            elif h < 12: bucket = "06~12"
            elif h < 18: bucket = "12~18"
            else: bucket = "18~24"
            by_hour_bucket.setdefault(bucket, []).append(t)
        except Exception:
            pass
    if by_hour_bucket:
        lines.append("\n<b>KST 시간대</b>")
        for b in ["00~06", "06~12", "12~18", "18~24"]:
            if b not in by_hour_bucket:
                continue
            ts = by_hour_bucket[b]
            tn = len(ts); tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = (tw / tn * 100) if tn else 0
            lines.append(f"  {b}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # ── 자동 인사이트 (룰 기반) ────────────────────────────
    insights = []
    if win_rate < 0.40:
        insights.append(f"⚠️ 승률 {win_rate*100:.0f}% — 50% 미만, 전략 검토 필요")
    if total_pnl < 0:
        worst_sym = min(by_sym.items(), key=lambda x: sum(t["pnl"] for t in x[1]))
        insights.append(f"💸 최대 손실 심볼: {worst_sym[0]} → universe 제외 또는 가중치 ↓ 고려")
    if win_scores and loss_scores:
        if abs(avg_win - avg_loss) < 5:
            insights.append("📉 점수가 승률 예측 거의 못함 → ENTRY_MIN_SCORE 상향 또는 score 시스템 검토")
    sl_count = sum(1 for t in trades if "sl" in (t.get("reason") or "").lower())
    if sl_count / n > 0.40:
        insights.append(f"🔴 SL 비율 {sl_count/n*100:.0f}% — SL 너무 빡빡 / 진입 너무 빠름")
    if long_t and short_t and len(long_t) >= 5 and len(short_t) >= 5:
        long_wr = sum(1 for t in long_t if t["pnl"] >= 0) / len(long_t)
        short_wr = sum(1 for t in short_t if t["pnl"] >= 0) / len(short_t)
        if abs(long_wr - short_wr) > 0.20:
            better = "롱" if long_wr > short_wr else "숏"
            insights.append(f"📊 {better} 우세 — 약/강세장 편향. 4H ADX 페널티 강화 검토")
    # 가장 부진 시간대
    if by_hour_bucket:
        hour_wr = []
        for b, ts in by_hour_bucket.items():
            if len(ts) >= 3:
                wr = sum(1 for t in ts if t["pnl"] >= 0) / len(ts)
                hour_wr.append((b, wr, len(ts)))
        if hour_wr:
            worst_hour = min(hour_wr, key=lambda x: x[1])
            if worst_hour[1] < 0.30:
                insights.append(f"🕐 {worst_hour[0]} 시간대 부진 ({worst_hour[1]*100:.0f}% / {worst_hour[2]}건) — 진입 회피 검토")
    if "high" in by_tier and len(by_tier["high"]) >= 3:
        ts = by_tier["high"]
        wr = sum(1 for t in ts if t["pnl"] >= 0) / len(ts)
        if wr < 0.50:
            insights.append("🎯 high tier (점수 90+) 도 승률 50% 미만 → score 시스템 신뢰도 ↓")

    if insights:
        lines.append("\n<b>🧠 자동 인사이트</b>")
        for ins in insights:
            lines.append(f"  • {ins}")
    else:
        lines.append("\n✅ 특별한 이상 패턴 없음")

    return "\n".join(lines)


def market_diagnose(*, bot_id: str, days: int = 30) -> str:
    """v6.70: 시장 흐름 × 전략 궁합 세밀 분석. /market 명령용.

    진입 시점 market_snapshot (RSI/ADX/BB/변동성) 을 활용해
    "어떤 시장 상태에서 우리 전략이 이겼나" 를 분석.

    차원:
      - 주차별 PnL 추세 (최근 개선/악화 정량화)
      - 시장 레짐별 (4H ADX: 추세장 trending vs 횡보장 ranging)
      - 변동성 구간별 (4H bb_width: 저/중/고)
      - RSI 진입 구간별 (과매도/중립/과매수 진입 성과)
      - 요일별 (KST)
    """
    import json as _json
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))

    trades = recent_trades(bot_id=bot_id, since_seconds=days * 86400, limit=10000)
    if not trades:
        return f"📈 시장 진단 — 지난 {days}일 거래 없음"

    def _snap(t):
        """market_snapshot JSON 파싱. 실패시 None."""
        raw = t.get("market_snapshot")
        if not raw:
            return None
        try:
            return _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None

    def _tf(snap, tf, key):
        """snap['4h']['adx'] 안전 추출."""
        if not snap:
            return None
        d = snap.get(tf, {})
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    n = len(trades)
    total_pnl = sum(t["pnl"] for t in trades)
    lines = [
        f"📈 <b>시장 흐름 × 전략 궁합</b> ({bot_id}, {days}일)",
        f"━━━━━━━━━━━━━━━━━",
        f"총 {n}건 / PnL {total_pnl:+.2f}",
    ]

    # ── 1. 주차별 추세 (핵심: 최근이 정말 좋아졌나) ──
    now = datetime.now(timezone.utc).timestamp()
    lines.append("\n<b>📅 주차별 추세 (최근→과거)</b>")
    for w in range(4):
        w_start = now - (w + 1) * 7 * 86400
        w_end = now - w * 7 * 86400
        wk = [t for t in trades
              if w_start <= (t.get("exit_ts") or t.get("ts") or 0) < w_end]
        if not wk:
            continue
        wn = len(wk)
        ww = sum(1 for t in wk if t["pnl"] >= 0)
        wp = sum(t["pnl"] for t in wk)
        wr = ww / wn * 100 if wn else 0
        label = ["이번주", "1주전", "2주전", "3주전"][w]
        icon = "🟢" if wp > 0 else "🔴"
        lines.append(f"  {icon} {label}: {wn}건 {wr:.0f}% {wp:+.2f}")

    # ── 2. 시장 레짐별 (4H ADX 기준) ──
    reg_buckets = {"추세장(ADX≥25)": [], "약추세(18~25)": [], "횡보장(ADX<18)": [], "?": []}
    for t in trades:
        adx4 = _tf(_snap(t), "4h", "adx")
        if adx4 is None:
            reg_buckets["?"].append(t)
        elif adx4 >= 25:
            reg_buckets["추세장(ADX≥25)"].append(t)
        elif adx4 >= 18:
            reg_buckets["약추세(18~25)"].append(t)
        else:
            reg_buckets["횡보장(ADX<18)"].append(t)
    has_regime = any(len(v) > 0 for k, v in reg_buckets.items() if k != "?")
    if has_regime:
        lines.append("\n<b>🌊 시장 레짐별 (진입시 4H ADX)</b>")
        for k in ["추세장(ADX≥25)", "약추세(18~25)", "횡보장(ADX<18)", "?"]:
            ts = reg_buckets[k]
            if not ts:
                continue
            tn = len(ts); tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = tw / tn * 100 if tn else 0
            icon = "🟢" if tp > 0 else "🔴"
            lines.append(f"  {icon} {k}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # ── 3. 변동성 구간별 (4H bb_width) ──
    vol_vals = [(_tf(_snap(t), "4h", "bb_width"), t) for t in trades]
    vol_vals = [(v, t) for v, t in vol_vals if v is not None]
    if len(vol_vals) >= 10:
        sorted_v = sorted(v for v, _ in vol_vals)
        lo_th = sorted_v[len(sorted_v) // 3]
        hi_th = sorted_v[2 * len(sorted_v) // 3]
        vb = {"저변동": [], "중변동": [], "고변동": []}
        for v, t in vol_vals:
            if v <= lo_th:
                vb["저변동"].append(t)
            elif v <= hi_th:
                vb["중변동"].append(t)
            else:
                vb["고변동"].append(t)
        lines.append("\n<b>📊 변동성 구간별 (4H BB폭)</b>")
        for k in ["저변동", "중변동", "고변동"]:
            ts = vb[k]
            if not ts:
                continue
            tn = len(ts); tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = tw / tn * 100 if tn else 0
            icon = "🟢" if tp > 0 else "🔴"
            lines.append(f"  {icon} {k}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # ── 4. RSI 진입 구간별 (15m) ──
    rsi_buckets = {"과매도(<35)": [], "약세(35~45)": [], "중립(45~55)": [],
                   "강세(55~65)": [], "과매수(>65)": []}
    rsi_any = False
    for t in trades:
        rsi = _tf(_snap(t), "15m", "rsi")
        if rsi is None:
            continue
        rsi_any = True
        if rsi < 35: rsi_buckets["과매도(<35)"].append(t)
        elif rsi < 45: rsi_buckets["약세(35~45)"].append(t)
        elif rsi < 55: rsi_buckets["중립(45~55)"].append(t)
        elif rsi < 65: rsi_buckets["강세(55~65)"].append(t)
        else: rsi_buckets["과매수(>65)"].append(t)
    if rsi_any:
        lines.append("\n<b>📉 진입 RSI 구간별 (15m)</b>")
        for k in ["과매도(<35)", "약세(35~45)", "중립(45~55)", "강세(55~65)", "과매수(>65)"]:
            ts = rsi_buckets[k]
            if not ts:
                continue
            tn = len(ts); tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = tw / tn * 100 if tn else 0
            icon = "🟢" if tp > 0 else "🔴"
            lines.append(f"  {icon} {k}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # ── 5. 요일별 (KST) ──
    dow_names = ["월", "화", "수", "목", "금", "토", "일"]
    dow_buckets: dict[int, list] = {}
    for t in trades:
        ts_unix = t.get("exit_ts") or t.get("ts") or 0
        try:
            dt = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc).astimezone(KST)
            dow_buckets.setdefault(dt.weekday(), []).append(t)
        except Exception:
            pass
    if dow_buckets:
        lines.append("\n<b>📆 요일별 (KST)</b>")
        for d in range(7):
            ts = dow_buckets.get(d, [])
            if not ts:
                continue
            tn = len(ts); tw = sum(1 for t in ts if t["pnl"] >= 0)
            tp = sum(t["pnl"] for t in ts)
            wr = tw / tn * 100 if tn else 0
            icon = "🟢" if tp > 0 else "🔴"
            lines.append(f"  {icon} {dow_names[d]}: {tn}건 {wr:.0f}% {tp:+.2f}")

    # ── 자동 인사이트 ──
    insights = []
    # 레짐 궁합
    if has_regime:
        best_reg = max(
            [(k, sum(t["pnl"] for t in v), len(v)) for k, v in reg_buckets.items()
             if k != "?" and len(v) >= 3],
            key=lambda x: x[1], default=None)
        if best_reg and best_reg[1] > 0:
            insights.append(
                f"🌊 '{best_reg[0]}' 에서 가장 수익 ({best_reg[1]:+.2f}) "
                f"— 이 레짐일 때 전략이 잘 맞음")
    # 주차 추세
    wk_pnls = []
    for w in range(4):
        w_start = now - (w + 1) * 7 * 86400
        w_end = now - w * 7 * 86400
        wp = sum(t["pnl"] for t in trades
                 if w_start <= (t.get("exit_ts") or t.get("ts") or 0) < w_end)
        wk_pnls.append(wp)
    if len(wk_pnls) >= 2 and wk_pnls[0] > 0 and wk_pnls[0] > wk_pnls[1]:
        insights.append("📈 이번주가 지난주보다 개선 — 현재 시장이 전략과 궁합 좋음")
    elif len(wk_pnls) >= 2 and wk_pnls[0] < 0:
        insights.append("📉 이번주 마이너스 — 시장 국면 변화 가능성, 관찰 필요")

    if insights:
        lines.append("\n<b>🧠 궁합 인사이트</b>")
        for ins in insights:
            lines.append(f"  • {ins}")

    lines.append("\n💡 이 데이터로 '어떤 시장에서 우리가 강한지' 파악")
    return "\n".join(lines)


def update_proposal_status(proposal_id: int, status: str) -> bool:
    try:
        conn = _conn()
        conn.execute(
            "UPDATE proposals SET status=? WHERE id=?",
            (status, proposal_id),
        )
        return True
    except Exception as e:
        print(f"[journal update_proposal_status err] {e}", flush=True)
        return False
