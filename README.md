# bybit_live_bot

## AI 분석 레이어 (Gemini, 무료 티어)

봇이 닫은 모든 거래에 대해 AI 사후분석을 텔레그램으로 보내고, 1시간마다
시장 레짐(추세/횡보/고변동성 등)을 분류해 보고합니다. **봇의 매매 결정에는
일절 개입하지 않습니다** — 분석/조언만.

### 활성화

1. https://aistudio.google.com/apikey 에서 무료 API 키 발급
2. 환경변수 2개 설정:
   ```
   GEMINI_API_KEY=AIza...
   AI_ENABLED=true
   ```
3. 봇 재시작. 시작 메시지에 `🧠 AI: ON (gemini-2.0-flash)` 표시되면 OK.

### 비활성화

`AI_ENABLED=false` 또는 키 제거. 봇 매매 로직은 영향 없음.

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | (없음) | Google AI Studio에서 발급 |
| `AI_ENABLED` | `false` | 활성화 스위치 |
| `AI_MODEL` | `gemini-2.0-flash` | 사용 모델 |
| `AI_REGIME_INTERVAL_SEC` | `3600` | 레짐 분석 주기(초) |

### 명령어

- `/ai` — 즉시 시장 레짐 분석 1회 실행

### 비용

`gemini-2.0-flash` 무료 티어는 일 1500회 / 분당 15회. 거래 50건/일 +
1시간 레짐(24회/일) 사용해도 한참 여유 있음. 본 글 기준 추가비용 0원.

### 안전장치

- AI 호출은 항상 백그라운드 스레드에서 실행 → 매매 루프 절대 블로킹 안됨
- AI 응답 실패/타임아웃/잘못된 JSON → 조용히 무시, 봇은 계속 동작
- 키 없거나 `AI_ENABLED=false` → 모든 AI 호출이 즉시 no-op
