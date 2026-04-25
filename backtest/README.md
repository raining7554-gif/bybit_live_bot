# Bybit Bot Backtest Framework

현재 봇(v6.3d)과 후보 전략들을 1년치 BTC 실데이터로 비교 백테스트하기 위한 모듈.

## 빠른 시작

```bash
cd /path/to/bybit_live_bot

# 1) 의존성 (이미 requirements.txt에 있음)
pip install -r requirements.txt

# 2) 자체 테스트 (인터넷 불필요, 합성 데이터로 코드 점검)
python -m backtest.test_offline

# 3) 실데이터 백테스트 (1년치, BTCUSDT 기본)
python -m backtest.run

# 옵션
python -m backtest.run --days 180
python -m backtest.run --refresh                    # 캐시 무시하고 재다운
python -m backtest.run --strategies v63d,A          # 일부만
python -m backtest.run --equity 500                 # 초기자본 변경
python -m backtest.run --skip-funding               # 펀딩 분석 생략
```

## 출력물

- 콘솔: 전략별 핵심 지표 비교 표 + 자동 평가
- `backtest/reports/<symbol>_<timestamp>.txt`: 텍스트 리포트
- `backtest/reports/<symbol>_trades.csv`: 전체 거래 기록 (Excel/판다스로 추가 분석 가능)
- `backtest/data/<symbol>_<interval>.csv`: OHLCV 캐시 (재실행 시 빠름)

## 전략

| ID | 이름 | 핵심 룰 | 빈도 | 레버리지 | risk/거래 |
|---|---|---|---|---|---|
| v63d | 현재 봇 (대조군) | 15m ADX/BB/RSI 필터 + 트레일 | 매우 높음 | 7x | ~2% |
| A | 1H 구조 스윙 | 4H 추세 + 1H 되돌림 + 15m 트리거 | 낮음 (월 5~15회) | 5x | 1% |
| C | 15m Donchian 돌파 | 1H 추세 + 20봉 돌파 + ATR 손절 | 중간 (월 20~40회) | 3x | 0.5% |

펀딩비 분석(옵션 2)은 자동으로 함께 출력 (활성 시간/임계별 APR).

## 핵심 지표 해석

- **Sharpe**: 위험조정수익. 1.0 미만 = 라이브 금지 / 1.5+ 양호 / 2.0+ 우수
- **Calmar**: CAGR / |MDD|. 1.0+ 권장
- **Profit Factor**: 총이익/총손실. 1.5+ 권장 / 2.0+ 양호
- **MDD %**: 자본 곡선 최대낙폭. 20% 초과면 라이브 시 심리적으로 못 버팀
- **최대 연속 손실**: 5회 초과면 사이즈 축소 또는 전략 폐기 검토

## 데이터 출처

- Bybit V5 public API (인증 불필요)
- OHLCV: `/v5/market/kline`
- 펀딩: `/v5/market/funding/history`

## 합리적 통과 기준 (라이브 전 체크리스트)

라이브로 가기 전 모든 전략은 다음을 충족해야 함:

1. Sharpe ≥ 1.0 on 1-year out-of-sample
2. MDD ≤ 20%
3. 거래수 ≥ 50회 (통계적 유의)
4. 롱/숏 균형 (한쪽만 수익이면 시장체제 의존)
5. 월별 PnL이 6개월 이상 양수 (체제 견고성)
6. 수수료 비중 < 총수익의 30% (마찰 한도)

위 6개 모두 통과하지 못하면 **무조건 라이브 금지**.

## 자주 쓸 분석

```bash
# 거래 CSV에서 월별 손익
python -c "
import pandas as pd
df = pd.read_csv('backtest/reports/BTCUSDT_trades.csv', parse_dates=['exit_dt'])
df['month'] = df['exit_dt'].dt.to_period('M')
print(df.groupby(['strategy', 'month'])['pnl'].sum().unstack().fillna(0).round(2))
"

# 전략별 reason 분포
python -c "
import pandas as pd
df = pd.read_csv('backtest/reports/BTCUSDT_trades.csv')
print(df.groupby(['strategy', 'reason']).size().unstack().fillna(0))
"
```

## 한계

- 실제 봇의 limit-order 미체결, 피라미딩, 텔레그램 신호 OFF 등은 반영 안 됨
- 백테스트는 종가 체결 가정 (실제는 슬리피지 더 큼) — `BTConfig.slippage` 조정 가능
- 펀딩비 자체 비용은 backtest engine 미반영 (보유 시간 짧음 / `analyze_funding`만 별도)
- 과적합 방지를 위해 **최소 1년** 데이터 권장. 1년 미만은 결과 신뢰 X
