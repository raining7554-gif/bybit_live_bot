---
name: promote
description: Promote a backtest-verified parameter change to live config. Use when sweep results show clear winner that should be deployed.
---

# /promote skill

검증된 파라미터 변경을 라이브 config 에 적용.

## 작동 흐름

1. 사용자가 변경 의도 제시 (예: "score_min 55 → 50 적용")
2. 최근 sweep 결과 (`backtest/reports/sweep_mr_v5_*.json`) 확인
3. 해당 변경의 백테스트 통계 보고 (sharpe, return, mdd)
4. 안전 체크:
   - sample size ≥ 50 trades
   - sharpe ≥ 0.8
   - mdd 합리적 (-20% 이내)
5. 통과시 `backtest/strategies/strategy_mr_v5.py` 수정
6. 커밋 + PR 생성
7. PR 본문에 백테스트 근거 명시

## 안전 가드

- 한 번에 1 파라미터만 변경 권장
- 변경 후 1주일 라이브 검증 후 다음 변경
- 백테스트 미실행 변경은 거부 (수동 PR 권장)

## 사용 예

```
/promote score_min 55 → 50
```

→ 결과:
```
백테스트 검증:
  sample: 143 trades (sharpe 1.42 ret +24%)
  현재 운영: sharpe ~0.6 ret +5%
  
변경 안전: ✅
PR 생성: https://github.com/...
```

## 거부 예

`/promote score_min 30` → "백테스트 결과 없음 / 표본 부족 — 먼저 /backtest 실행"
