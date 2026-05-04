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
    for t in trades:
        s = t.get("strategy") or "?"
        r = t.get("reason") or "?"
        b = t.get("bot_id") or "?"
        ss = by_strategy.setdefault(s, {"n": 0, "wins": 0, "pnl": 0.0})
        ss["n"] += 1
        ss["wins"] += 1 if t["pnl"] >= 0 else 0
        ss["pnl"] += t["pnl"]
        by_reason[r] = by_reason.get(r, 0) + 1
        bb = by_bot.setdefault(b, {"n": 0, "wins": 0, "pnl": 0.0})
        bb["n"] += 1
        bb["wins"] += 1 if t["pnl"] >= 0 else 0
        bb["pnl"] += t["pnl"]

    return {
        "n": n, "wins": wins, "losses": losses,
        "win_rate": wins / n if n > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
        "by_strategy": by_strategy,
        "by_reason": by_reason,
        "by_bot": by_bot,
    }


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
