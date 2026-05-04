# Trading Bots Monorepo

Bybit (암호화폐 선물) + KIS (한투 국장/미장) 봇을 한 레포에서 관리.
공통 학습 모듈을 공유하기 위해 monorepo 구조로 통합되었습니다.

## 구조

```
.
├── bybit/                 ← Bybit BTC 봇 (구 bot_v7/)
│   ├── runner.py
│   ├── strategy.py
│   ├── ai.py             ← Gemini 사후분석/레짐 (현재)
│   └── ...
├── bot_v7/                ← (현재 활성) Bybit 봇 코드 — 추후 bybit/ 으로 이동 예정
├── bybit_live_bot_v7.py   ← Bybit 봇 진입점 (Railway 시작 명령)
├── backtest/              ← Bybit 전략 백테스트 엔진
├── kis/                   ← 한투 봇 (KR 국장 + 미장)
│   ├── main.py            ← 진입점
│   ├── strategy_clenow_kr.py
│   ├── strategy_leveraged.py
│   ├── trader.py / trader_overseas.py
│   └── ...
├── intelligence/          ← (예정) 양쪽 봇 공통 학습 모듈
│   ├── journal.py         ← 거래/분석 통합 저장
│   └── agent.py           ← 사후분석/회고/제안
├── patches/               ← 크로스레포 패치 보관 (이력 참고용)
├── Dockerfile             ← Bybit 봇 빌드 (root 기준)
└── README.md
```

## Railway 배포

이 레포 하나에서 **두 개의 Railway 서비스**가 동작합니다.

### 서비스 1 — Bybit 봇 (기존)
- **Root Directory**: `/` (변경 없음)
- **Build**: `Dockerfile`
- **Start**: `python bybit_live_bot_v7.py` (Dockerfile CMD)
- **환경변수**: `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `TG_TOKEN`, `TG_CHAT_ID`,
  `GEMINI_API_KEY`, `AI_ENABLED` 등

### 서비스 2 — KIS 봇
기존 kis_bot Railway 서비스를 **이 레포로 재연결** + Root Directory를 `/kis` 로 변경.

- **Root Directory**: `/kis`
- **Build**: NIXPACKS (`kis/railway.toml` 사용)
- **Start**: `python main.py`
- **환경변수**: `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`,
  `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `DOM_STRATEGY_MODE`,
  `OS_STRATEGY_MODE` 등

자세한 마이그레이션 절차: `MIGRATION.md` 참고.

---

## Bybit 봇 — AI 분석 레이어 (Gemini, 무료 티어)

거래 청산마다 AI 사후분석 + 1시간마다 시장 레짐 분류. **매매 결정에는 일절 개입 안 함** — 분석/조언만.

### 활성화

1. https://aistudio.google.com/apikey 에서 무료 API 키 발급
2. 환경변수 2개 설정:
   ```
   GEMINI_API_KEY=AIza...
   AI_ENABLED=true
   ```
3. 봇 재시작. 시작 메시지에 `🧠 AI: ON (gemini-2.0-flash)` 표시되면 OK.

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | (없음) | Google AI Studio에서 발급 |
| `AI_ENABLED` | `false` | 활성화 스위치 |
| `AI_MODEL` | `gemini-2.0-flash` | 사용 모델 (한도 초과시 `gemini-2.5-flash-lite` 권장) |
| `AI_REGIME_INTERVAL_SEC` | `3600` | 레짐 분석 주기(초) |

### 명령어

- `/status` — 잔고/포지션 요약
- `/score` — 현재 시그널 점수
- `/ai` — 즉시 시장 레짐 분석 1회
- `/halt` `/resume` — 수동 정지·재개

### 비용

`gemini-2.0-flash` 무료 티어 = 일 1500회 / 분당 15회. 한도 초과 시 `gemini-2.5-flash-lite`로 변경 (분당 30회 / 일 1000회).

### 안전장치

- AI 호출은 항상 백그라운드 스레드에서 실행 → 매매 루프 블로킹 안됨
- AI 응답 실패/타임아웃/잘못된 JSON → 조용히 무시, 봇 계속 동작
- 키 없거나 `AI_ENABLED=false` → 모든 AI 호출 즉시 no-op

---

## KIS 봇

### 동작 모드

`DOM_STRATEGY_MODE` (국내):
- `swing` — 섹터 모멘텀 스윙 (기본)
- `clenow` — 120일 Clenow 모멘텀 점수 + KOSPI 체제

`OS_STRATEGY_MODE` (해외):
- `swing` — 기존 섹터 스윙
- `leveraged` — SOXL/TQQQ/TECL/FAS 4-way 체제 스위치

### 환경변수 (주요)
| 변수 | 설명 |
|---|---|
| `KIS_APP_KEY`, `KIS_APP_SECRET` | KIS OpenAPI 키 |
| `KIS_ACCOUNT_NO` | "12345678-01" 형식 |
| `KIS_PAPER` | `true`=모의투자 / `false`=실거래 |
| `DOM_STRATEGY_MODE` | `swing` / `clenow` |
| `OS_STRATEGY_MODE` | `swing` / `leveraged` |
| `DOM_SMALL_SEED_MODE` | 소액 시드 자동 조정 |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | 텔레그램 알림 |

자세한 변수는 `kis/config.py` 참고.

### 일봉 데이터 수정 (이번 마이그레이션에 포함됨)
- `inquire-daily-itemchartprice` 엔드포인트 + 페이지네이션 → 200+ 거래일 확보
- KOSPI 지수 `market_code="U"` 명시
- 해외 일봉 BYMD 페이지네이션 + 거래소 fallback (AMS/NYS/NAS)

이전 증상이었던 `[CLENOW] KOSPI 체제=UNKNOWN`, `[LEV] SPY 0일` 해결됨.

---

## 향후 계획 — `intelligence/` 공유 학습

두 봇이 같이 학습하는 모듈을 추가 예정:
- 통합 거래 저널 (SQLite or Postgres)
- 사후분석 누적 → 패턴 메모리
- 주간 회고 — "BTC vs 코스피 vs 미장 비교"
- 파라미터 개선 제안 (사람 승인 후 적용)

자세한 설계는 추후 `intelligence/README.md` 참고.
