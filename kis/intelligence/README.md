# intelligence/ — 봇 공유 학습 모듈

Bybit + KIS 두 봇이 공통으로 사용하는 거래 저널 + AI 분석 모듈.
각 봇이 자기 SQLite (`/data/intelligence.db`) 에 기록.
향후 환경변수만 바꾸면 통합 Postgres로 확장 가능.

## 구성

| 파일 | 역할 |
|---|---|
| `schema.py` | SQLite/Postgres 호환 DDL |
| `journal.py` | 거래/분석/레짐/제안 영구 저장 + 쿼리 (bot-agnostic) |
| `agent.py`  | Gemini 기반: 사후분석/레짐/주간회고/파라미터제안 |

## 테이블

```
trades     - 종료된 모든 거래 (bot_id로 봇 식별)
analyses   - AI 사후분석 결과 + 추출된 lesson
regimes    - 주기적 시장 레짐 분류
proposals  - AI가 제안한 파라미터 변경 (status: pending/applied/rejected)
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `INTELLIGENCE_DB_PATH` | `/data/intelligence.db` | SQLite 파일 경로 |
| `GEMINI_API_KEY` | - | Gemini API 키 (필수) |
| `AI_ENABLED` | `false` | 활성화 토글 |
| `AI_MODEL` | `gemini-2.0-flash` | 사용 모델 |

## 사용 패턴

### 1. 거래 종료 시
```python
from intelligence import journal, agent

trade_id = journal.log_trade(
    bot_id="bybit_btc_d",
    symbol="BTCUSDT", side="long",
    entry_price=67500, exit_price=67200,
    size=0.01, leverage=10.0,
    pnl=-30, pnl_pct=-0.0044,
    reason="sl", strategy="D", tier="base",
    market_snapshot={"adx": 32, "rsi": 65, ...},
)

agent.analyze_trade_async(
    bot_id="bybit_btc_d",
    trade={"symbol": "BTCUSDT", "side": "long", ...},
    snapshot={"adx": 32, ...},
    trade_id=trade_id,
    send_telegram=lambda msg: telegram_bot.send(msg),
)
```

### 2. 시장 레짐 (주기적)
```python
agent.detect_regime_async(
    bot_id="bybit_btc_d",
    asset="BTCUSDT",
    snapshot={"15m": {...}, "1h": {...}, "4h": {...}},
    send_telegram=...,
)
```

### 3. 주간 회고 (주 1회)
```python
agent.weekly_review_async(
    bot_id="bybit_btc_d",          # None이면 모든 봇 통합
    send_telegram=...,
)
```

### 4. 파라미터 제안 (월 1~2회)
```python
agent.propose_async(
    bot_id="bybit_btc_d",
    current_params={"TRAIL_ATR_HIGH": 4.0, "MARGIN_PCT_HIGH": 0.80, ...},
    send_telegram=...,
)
# AI가 분석 → proposals 테이블에 'pending'로 저장 → 텔레그램 알림
# 사람이 검토 → 수동으로 코드 변경 → status를 'applied'로 업데이트
```

## bot_id 명명 규칙

| bot_id | 봇 |
|---|---|
| `bybit_btc_d`     | Bybit BTC Strategy D |
| `bybit_btc_mr`    | Bybit BTC Mean Reversion |
| `kis_kr_clenow`   | KIS 국내 Clenow |
| `kis_kr_swing`    | KIS 국내 Swing |
| `kis_us_lev`      | KIS 미국 Leveraged |
| `kis_us_swing`    | KIS 미국 Swing |

## 안전 보장

- **모든 AI 호출은 백그라운드 스레드** → 매매 루프 절대 블로킹 X
- **AI 실패시 조용히 스킵** (verbose 모드만 텔레그램 에러 보고)
- **파라미터 제안은 절대 자동 적용 안함** (proposals 테이블에 pending으로만 저장)
- DB 쓰기 실패도 stderr 로그만, 봇 동작에 영향 X

## Phase 2 (예정) — 통합 학습

각 봇이 따로 SQLite 쓰는 현재 구조에서:
1. Railway에 Postgres add-on 추가
2. 환경변수: `INTELLIGENCE_DB_URL=postgresql://...`
3. journal.py 의 sqlite3 코드를 SQLAlchemy 또는 psycopg2 로 교체
4. 두 봇이 같은 DB 사용 → `weekly_review_async(bot_id=None)` 가 진짜 통합 회고
