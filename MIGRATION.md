# Monorepo 마이그레이션 가이드

기존 별도 레포(`raining7554-gif/kis_bot`)를 이 레포(`bybit_live_bot`) 의 `/kis` 디렉토리로 통합. 본 문서는 Railway 서비스 재연결 절차를 안내합니다.

## 마이그레이션 효과

- ✅ Bybit + KIS 봇 한 곳에서 관리 → AI/공유 학습 모듈 자연스럽게 통합
- ✅ git 히스토리 보존 (`git subtree --squash`)
- ✅ 기존 환경변수 그대로 유지 (재입력 불필요)
- ✅ 옛날 kis_bot 레포는 archive — 코드/이슈는 그대로 남음

## 작업 순서

### 1단계 — 이 레포의 monorepo 브랜치 main에 머지

이 변경은 PR로 올라옵니다. 머지 후 `main` 브랜치에 다음이 생깁니다:
- `/kis/` 폴더 (한투봇 코드 + 일봉 데이터 수정 적용본)
- 업데이트된 `README.md`

### 2단계 — Railway: 기존 KIS 봇 서비스 재연결

Railway 대시보드 → **기존 kis_bot 서비스** 클릭 →

#### 2-A. Source 변경
- Settings → **Service** → **Source**
- **Disconnect** 클릭 → 기존 `raining7554-gif/kis_bot` 연결 해제
- **Connect Repo** → `raining7554-gif/bybit_live_bot` 선택
- **Branch**: `main`

#### 2-B. Root Directory 설정
- Settings → **Service** → **Root Directory**
- 입력: `kis`
- 저장

#### 2-C. Start Command (필요시 명시)
- Settings → **Deploy** → **Custom Start Command**
- 보통 `kis/railway.toml` 의 `python main.py` 가 자동 적용됨
- 안 되면 수동 입력: `python main.py`

#### 2-D. 환경변수
- 그대로 유지 — 변경 불필요
- (혹시 Source 변경하면서 사라졌으면 다시 입력)

### 3단계 — 재배포 + 확인

저장하면 자동 재배포. 1~2분 후 텔레그램 시작 메시지 + 로그 확인:

**시작 메시지**:
```
🚀 KIS 봇 v3.2 시작
💵 실거래
국내: Clenow 모멘텀 (...)
해외: 레버리지 4-way (...)
```

**로그에서 확인할 것** (이전 vs 이후):

| 이전 (BUG) | 이후 (정상) |
|---|---|
| `[CLENOW] KOSPI 체제=UNKNOWN → 진입 보류` | `[CLENOW] KOSPI=2710.20 MA200=2655.30 → BULL` |
| `[LEV] SPY 데이터 부족 (0일)` | `[LEV] SPY: AMS 실패 → NYS 로 220건 확보` |
| `[LEV] QQQ 데이터 부족 (100일)` | `[LEV] QQQ: 220건 확보` (또는 fallback 메시지) |

### 4단계 (선택) — 옛날 kis_bot 레포 archive

확인 끝나면 GitHub에서 옛날 kis_bot 레포를:
- Settings → **Archive this repository** 처리
- 또는 README에 "이 레포는 https://github.com/raining7554-gif/bybit_live_bot 로 통합되었습니다" 안내 추가

## Bybit 봇은 영향 없음

Bybit 서비스는 변경할 필요 없습니다. 같은 레포의 `/` (root) 에서 그대로 빌드/실행됩니다.

## 롤백 방법 (혹시 문제 생기면)

Railway에서:
1. KIS 서비스 → Source 다시 `raining7554-gif/kis_bot` 으로 변경
2. Root Directory 비우기
3. 옛 레포가 그대로 살아있어서 즉시 동작 재개

## 자주 발생하는 문제

| 증상 | 원인 | 해결 |
|---|---|---|
| `ModuleNotFoundError: No module named 'config'` | Root Directory 미설정 | 설정에 `kis` 입력 |
| `python main.py` 못 찾음 | Start command path 문제 | Root Directory 정확히 `kis` 인지 확인 |
| 빌드 실패 (NIXPACKS) | `kis/requirements.txt` 못 찾음 | Root Directory 설정 확인 |
| 환경변수 사라짐 | Source 재연결시 기본값 리셋 | Variables 탭에서 재입력 |

## 작업 후 다음 단계

이 마이그레이션이 끝나면 다음 작업이 가능해집니다:

1. **`intelligence/` 공유 모듈 빌드** — 두 봇이 거래 데이터를 같은 DB에 저장
2. **통합 회고** — 일주일에 한 번 "BTC + 국장 + 미장 합산 분석" 텔레그램 보고
3. **누적 교훈 메모리** — AI가 과거 패턴 기억하면서 분석 품질 향상
4. **파라미터 개선 제안** — 사람 승인 후 적용 (자동 반영 X)
