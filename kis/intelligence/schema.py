"""Intelligence DB 스키마 (SQLite 1차, Postgres 호환 작성).

테이블:
  trades     — 모든 종료된 거래
  analyses   — AI 사후분석 (텍스트 + 추출된 lesson)
  regimes    — 주기적 시장 레짐 분류 결과
  proposals  — AI가 제안한 파라미터 변경

모든 행에 bot_id 컬럼 → 봇별 / 통합 분석 모두 가능.
"""
from __future__ import annotations

# SQLite-호환 DDL. 향후 Postgres로 갈 때 INTEGER PRIMARY KEY AUTOINCREMENT를
# SERIAL로 바꾸면 됨 (또는 SQLAlchemy 도입).
DDL = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    entry_price     REAL,
    exit_price      REAL,
    size            REAL,
    leverage        REAL    DEFAULT 1.0,
    pnl             REAL    NOT NULL,
    pnl_pct         REAL    NOT NULL,
    fees            REAL    DEFAULT 0,
    reason          TEXT,
    strategy        TEXT,
    tier            TEXT,
    score           REAL,
    entry_ts        INTEGER,
    exit_ts         INTEGER NOT NULL,
    market_snapshot TEXT,
    extra           TEXT
);

CREATE TABLE IF NOT EXISTS analyses (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id    TEXT    NOT NULL,
    kind      TEXT    NOT NULL,
    trade_id  INTEGER,
    content   TEXT    NOT NULL,
    lesson    TEXT,
    ts        INTEGER NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE TABLE IF NOT EXISTS regimes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id     TEXT    NOT NULL,
    asset      TEXT    NOT NULL,
    regime     TEXT    NOT NULL,
    confidence REAL,
    summary    TEXT,
    suggested  TEXT,
    ts         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          TEXT    NOT NULL,
    param           TEXT    NOT NULL,
    current_value   TEXT,
    suggested_value TEXT,
    reason          TEXT,
    confidence      REAL,
    status          TEXT    DEFAULT 'pending',
    ts              INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_bot_ts    ON trades(bot_id, exit_ts);
CREATE INDEX IF NOT EXISTS idx_analyses_bot_ts  ON analyses(bot_id, ts);
CREATE INDEX IF NOT EXISTS idx_analyses_kind    ON analyses(kind, ts);
CREATE INDEX IF NOT EXISTS idx_regimes_bot_ts   ON regimes(bot_id, ts);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, ts);
"""
