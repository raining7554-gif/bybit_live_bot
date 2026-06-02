# backtest_us — NASDAQ 횡단면 퀀트 백테스트

`backtest/`(크립토 단일종목 선물)와 별개. 이쪽은 **주식 다종목을 랭킹해서
상위 N개만 보유하는 횡단면(cross-sectional) 롱온리 프레임워크**입니다.

## 설계 철학 (벤치마크: 김민겸 IQC)
- **소수정예** — 검증된 알파 1개부터. 상위 `top_n`(기본 12)만 보유.
- **안정적 우상향** — 평가축은 PnL이 아니라 **Sharpe / MDD / Calmar**.
- **레짐 필터** — QQQ가 MA200 위일 때만 보유, 아니면 전액 현금.
- **무미래참조** — 신호 = 리밸런스일 종가, 체결 = 다음 거래일 시가.
  `test_engine.py`의 `test_no_lookahead`가 이를 **차이 0으로 증명**.

## 첫 알파: Clenow 횡단면 모멘텀
`alpha_momentum.py` — "Stocks on the Move":
- 90일 지수회귀(로그가격) **기울기 연율화 × R²** 로 스코어.
- MA100 위 종목만 후보, 큰 갭(>15%) 종목 제외.
- 상위 N개 선정, **역변동성(vol parity)** 가중 + 종목당 상한 20%.

## 폰 ↔ 맥 분업 (중요)
웹 샌드박스는 네트워크가 allowlist라 **stooq 접속 불가**. 그래서:
- **폰(웹)**: 코드 작성·엔진 검증(합성 데이터)·커밋.
- **맥(로컬)**: 실제 데이터 다운로드 + 진짜 백테스트.

## 실행
```bash
# 맥 (네트워크 O) — 실제 NASDAQ 데이터
python -m backtest_us.run                 # 캐시 사용, 없으면 stooq 다운로드
python -m backtest_us.run --refresh       # 강제 재다운로드
python -m backtest_us.run --top-n 15 --lookback 90

# 어디서나 (네트워크 X) — 엔진 메커니즘만 검증
python -m backtest_us.run --synthetic
python -m backtest_us.test_engine         # 무미래참조/레짐/비용 테스트
```
데이터는 `backtest_us/data/*.csv`로 캐시되어 이후 백테스트는 완전 오프라인·재현 가능.

## 파일
| 파일 | 역할 |
|------|------|
| `universe.py` | NASDAQ 단일종목 유니버스 + QQQ 벤치마크 |
| `data.py` | stooq 다운로드 + CSV 캐시 + 합성데이터 생성기 |
| `alpha_momentum.py` | Clenow 모멘텀 스코어/선정/가중 |
| `engine.py` | 횡단면 주봉 리밸런스 백테스터 (무미래참조) |
| `metrics.py` | Sharpe/Sortino/MDD/Calmar + QQQ 대조 |
| `run.py` | 실행 진입점 |
| `test_engine.py` | 엔진 정합성 테스트 |

## 다음 단계 (검증 후)
1. 맥에서 실제 데이터로 walk-forward — 파라미터(lookback/top_n) 민감도 점검.
2. 트렌드 알파가 검증되면 **2단계: 리버전 알파**를 별 sleeve로 추가 (레짐 분산).
   — 소수정예 원칙상 1번이 검증되기 전엔 추가하지 않음.
