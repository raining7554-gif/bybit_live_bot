#!/usr/bin/env bash
# kis_bot 일봉 데이터 수정 자동 적용 스크립트
# 사용법:
#   bash <(curl -sL https://raw.githubusercontent.com/raining7554-gif/bybit_live_bot/claude/agent-ai-overview-jgLqY/patches/apply_kis_fix.sh)
#
# 이게 하는 일:
#   1) kis_bot 임시 클론
#   2) 패치 다운로드 + 적용
#   3) claude/fix-daily-data 브랜치 생성 + 푸시
#   4) PR 만들 수 있는 GitHub URL 출력
set -e

WORKDIR=$(mktemp -d)
cd "$WORKDIR"

echo "▶ kis_bot 클론 중..."
git clone --depth 5 https://github.com/raining7554-gif/kis_bot.git
cd kis_bot

echo "▶ 패치 다운로드..."
curl -sLO https://raw.githubusercontent.com/raining7554-gif/bybit_live_bot/claude/agent-ai-overview-jgLqY/patches/kis_bot_daily_fix.patch

echo "▶ 패치 적용..."
git apply kis_bot_daily_fix.patch

echo "▶ 브랜치 생성 + 커밋..."
git checkout -b claude/fix-daily-data
git add strategy_clenow_kr.py strategy_leveraged.py
git -c commit.gpgsign=false commit -m "fix: 일봉 조회 페이지네이션 + KOSPI 지수 market_code 수정

- inquire-daily-price (~30건) → inquire-daily-itemchartprice (FHKST03010100) + 페이지네이션
- KOSPI 지수 호출 market_code 'J' → 'U' 수정
- 해외 일봉 BYMD 페이지네이션 + 거래소 fallback (AMS/NYS/NAS)

증상 해결: [CLENOW] KOSPI 체제=UNKNOWN, [LEV] SPY 0일"

echo "▶ GitHub 푸시 중... (인증 필요할 수 있음)"
git push -u origin claude/fix-daily-data

echo ""
echo "✅ 푸시 완료!"
echo ""
echo "🔗 다음 URL 가서 'Create pull request' 클릭:"
echo "   https://github.com/raining7554-gif/kis_bot/pull/new/claude/fix-daily-data"
echo ""
echo "(머지하면 Railway 자동 재배포)"
