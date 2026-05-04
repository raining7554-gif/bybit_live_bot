# Cross-repo patches

이 폴더는 **다른 레포(예: kis_bot)에 적용할 패치**를 보관합니다.
이 환경에서는 한 레포(bybit_live_bot)에만 직접 푸시 가능하므로,
다른 레포 변경사항은 패치 파일로 전달합니다.

## kis_bot_daily_fix.patch — 한투봇 일봉 데이터 부족 수정

### 증상
```
[CLENOW] KOSPI 체제=UNKNOWN → 진입 보류
[LEV] QQQ 데이터 부족 (100일)
[LEV] SPY 데이터 부족 (0일)
```

### 원인
1. `inquire-daily-price` 엔드포인트가 ~30건만 반환 → MA200 계산 불가
2. KOSPI 지수 호출 시 `market_code="J"`(주식) 잘못 사용 → 0건
3. SPY 거래소 코드 호환성 부족

### 수정
- `get_kr_daily`: `inquire-daily-itemchartprice` (`FHKST03010100`)로 교체 + 페이지네이션
- `check_kospi_regime`: 지수는 `market_code="U"` 명시
- `get_overseas_daily`: BYMD 페이지네이션 + 거래소 fallback (AMS→NYS→NAS)

### 적용 방법

#### 옵션 A — 로컬 git apply
```bash
# 1) 본인 PC에 kis_bot clone
git clone https://github.com/raining7554-gif/kis_bot.git
cd kis_bot

# 2) 패치 다운로드
curl -O https://raw.githubusercontent.com/raining7554-gif/bybit_live_bot/claude/agent-ai-overview-jgLqY/patches/kis_bot_daily_fix.patch

# 3) 적용
git apply kis_bot_daily_fix.patch

# 4) 확인
git diff --stat

# 5) 커밋 + 푸시
git add strategy_clenow_kr.py strategy_leveraged.py
git commit -m "fix: 일봉 200건 페이지네이션 + 거래소 fallback"
git push origin main
```

#### 옵션 B — GitHub 웹 UI에서 직접 편집
이 패치는 Claude Code에 보여주면 두 파일 전체 내용 받아서 GitHub 웹에서
복붙 가능합니다.

### 적용 후 확인
Railway 자동 재배포 → 1~2분 후 로그 확인:
```
[CLENOW] KOSPI=2710.20 MA200=2655.30 → BULL    ← 정상
[LEV] SPY: AMS 실패 → NYS 로 220건 확보         ← fallback 동작
```
