# Clenow 백테스트 결과 — S&P500 point-in-time (생존편향-free)

- 실행: 2026-06-03 05:20 UTC (GitHub Actions)
- 브랜치: main

```
[run] PIT mode — 1194 S&P500 names (691 removed/delisted, 503 current), bench=SPY
[run] loading 1194 tickers + SPY (refresh=False) ...
[data] sanitize: dropped 57/823 corrupt series (e.g. BEN, BMC, BOL, CAR, CBE, CFC, CIN, CNG...)
[run] PIT price coverage: 766/1194 (64%); delisted names fetched: 272

Clenow Momentum [S&P500 point-in-time] — 766 stocks, lookback=90, top_n=12, cost=0.10%
period: 1993-01-29 .. 2026-06-02

                        Clenow top12      SPY buy&hold       EW-universe
------------------------------------------------------------------------
총수익률                         1781.9%           3041.9%           4722.4%
CAGR                            9.2%             10.9%             12.3%
연변동성                           16.4%             18.6%             18.9%
Sharpe                          0.62              0.65              0.71
Sortino                         0.70              0.83              0.86
MDD                           -25.8%            -55.2%            -56.1%
Calmar                          0.36              0.20              0.22
최종자본                      $1,881,863        $3,141,916        $4,822,420
리밸런스 횟수                         1699                 -                 -
투자비중(레짐ON)                       77%                 -                 -
평균 회전율                           49%                 -                 -

[run] report saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/pit_20260603_052040.txt
```
