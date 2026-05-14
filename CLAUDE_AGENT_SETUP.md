# Claude Agent 셋업 가이드 (v6.43)

봇 옆에 자율 분석 에이전트 추가. 매시간 1회 거래 데이터 분석 → 개선안 PR 자동 생성.

## 비용 예상

- 모델: `claude-sonnet-4-6`
- 시간당 1회 호출 (캐싱 활용)
- **월 ~$10~15**

## 1. Anthropic API 키 발급

1. https://console.anthropic.com 접속
2. Settings → API Keys → **Create Key**
3. 결제 등록 (Billing → Add payment method, $5 충전 권장)
4. 키 복사 (`sk-ant-api03-...`)

## 2. GitHub PAT 발급 (선택 — PR 생성용)

1. https://github.com/settings/tokens
2. **Generate new token (classic)**
3. 권한: `repo` (full control)
4. 만료: 90일 (또는 No expiration)
5. 키 복사 (`ghp_...`)

GH_PAT 없으면 PR 생성 불가, 분석 + 텔레그램 알림만 작동.

## 3. Railway 환경변수 등록

Bybit 봇 서비스에:

| 변수 | 값 | 필수 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | ✅ |
| `GH_PAT` | `ghp_...` | 선택 |
| `GH_REPO` | `raining7554-gif/bybit_live_bot` | 선택 (default 동일) |
| `GH_BASE_BRANCH` | `main` | 선택 |
| `CLAUDE_AGENT_ENABLED` | `true` | 선택 (default) |
| `CLAUDE_AGENT_INTERVAL_SEC` | `3600` | 선택 (default 1시간) |
| `CLAUDE_AGENT_MODEL` | `claude-sonnet-4-6` | 선택 (default) |

## 4. 작동 확인

### 자동 (매시간)
- 봇 재배포 후 매 시간 정각 무렵 자동 트리거
- 결과: 텔레그램에 `🤖 Claude Agent` 알림
- 의미 있는 인사이트 발견시: GitHub PR 자동 생성

### 수동 (즉시 테스트)
- 텔레그램에서 `/agent` 명령
- ~30초 후 결과 도착
- PR 생성됐으면 GitHub 알림도 옴

## 5. PR 검토 + 머지

Agent 가 만든 PR:
- 제목 예: `auto: tighten mid tier SL based on 32-trade analysis`
- 본문:
  - 데이터: 표본 크기, 승률, PnL
  - 가설: 발견한 패턴
  - 변경: 파라미터 diff
  - 위험: 최악 시나리오
- 검토 후 머지 → 봇 자동 재배포 → 다음 거래부터 적용

**자동 머지 X** — 항상 사람 검토 필요.

## 6. 비용 모니터링

- https://console.anthropic.com → Usage
- 시간/일/월별 사용량 확인
- 예상 초과시: `CLAUDE_AGENT_INTERVAL_SEC=7200` (2시간으로)

## 7. 비활성화

`CLAUDE_AGENT_ENABLED=false` env 추가 → 다음 배포 후 멈춤.

## 트러블슈팅

**"Claude Agent 분석 시작" 후 응답 없음**:
- Railway 로그에서 `[claude_agent]` 검색
- API 키 오타 / 결제 미등록 / quota 초과 확인

**PR 생성 실패**:
- GH_PAT 권한 확인 (`repo` 풀권한)
- repo 이름 오타 확인 (`GH_REPO`)

**비용 너무 많이 나옴**:
- Interval ↑ (1h → 2h or 4h)
- 또는 model ↓ (sonnet → haiku, 추론력 ↓ but $4x 저렴)
