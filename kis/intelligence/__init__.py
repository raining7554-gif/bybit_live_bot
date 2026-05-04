"""Cross-bot trading intelligence layer.

핵심 모듈:
  journal — 거래/분석/제안의 SQLite 기반 영구 저장 (bot-agnostic)
  agent   — Gemini 기반 사후분석/레짐/주간회고/파라미터제안
  schema  — DDL (SQLite 1차, Postgres 호환 작성)

각 봇은 자기 /data/intelligence.db 에 기록. 향후 INTELLIGENCE_DB_URL 환경
변수에 postgres URL 넣으면 통합 DB로 전환 가능 (코드 변경 없음).

사용법:
    from intelligence import journal, agent

    journal.log_trade(bot_id="bybit_btc_d", symbol="BTCUSDT", ...)
    agent.analyze_trade_async(bot_id="bybit_btc_d", trade=...)
    agent.weekly_review_async(bot_id="bybit_btc_d")
"""
from . import journal, agent, schema

__all__ = ["journal", "agent", "schema"]
