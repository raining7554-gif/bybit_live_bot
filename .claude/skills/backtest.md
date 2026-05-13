---
name: backtest
description: Run Bybit MR v5 backtest sweep locally. Use when user wants to test parameter changes before deploying live, or to validate a hypothesis with historical data.
---

# /backtest skill

빠른 백테스트 실행 + 결과 보고.

## 작동 방식

1. 사용자 질문/요청 분석 — 어떤 심볼/기간/파라미터 테스트하고 싶은지
2. `backtest/sweep_mr_v5.py` 실행 (필요시 사용자 환경에서)
3. 결과 JSON 분석 (`backtest/reports/sweep_mr_v5_*.json`)
4. Top 3 + 현재 파라미터 비교 표 출력

## 사용 예

`/backtest BTC 180일` → BTC 180일 sweep
`/backtest ETH 90일 score_min 50` → 특정 파라미터 sweep

## 출력 형식

```
📊 백테스트 결과 (BTC, 180일)
━━━━━━━━━━━━━
#1 sharpe=1.42 ret=+24.3% wr=58% (n=143)
   score>=55 rsi=35 bb=0.15 vol=1.3
#2 sharpe=1.28 ret=+19.7% wr=54% (n=128)
   ...
현재 운영값과 차이:
   score_min: 55 (현재) → 50 (top 1) [-5]
   ...
권장: 1주일 관측 후 적용
```

## 주의

- KIS API 가 sandbox 에서 막혀있어 봇 안에서 직접 못 돌림
- 사용자 로컬 또는 GitHub Actions 에서 실행 필요
- 주간 자동 sweep (weekly_sweep.yml) 결과도 참고 가능
