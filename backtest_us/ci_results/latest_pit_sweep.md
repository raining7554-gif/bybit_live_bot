# 모멘텀 설계 스윕 — S&P500 point-in-time (생존편향-free)

- 실행: 2026-06-03 05:49 UTC (GitHub Actions)
- 브랜치: main

```
[run] PIT mode — 1194 S&P500 names (691 removed/delisted, 503 current), bench=SPY
[run] loading 1194 tickers + SPY (refresh=False) ...
[data] sanitize: dropped 57/823 corrupt series (e.g. BEN, BMC, BOL, CAR, CBE, CFC, CIN, CNG...)
[run] PIT price coverage: 766/1194 (64%); delisted names fetched: 272

Momentum design sweep [S&P500 point-in-time] — 766 stocks, cost=0.10%

design                             CAGR      Vol   Sharpe  Sortino      MDD   Calmar   vs EW
--------------------------------------------------------------------------------------------
lb90  top12 skip0   (current)     +9.2%   +16.4%     0.62     0.70   -25.8%     0.36   lose (-0.09)
lb90  top30 skip0                 +6.5%   +13.5%     0.54     0.61   -25.7%     0.25   lose (-0.17)
lb90  top50 skip0                 +6.0%   +12.3%     0.53     0.60   -27.6%     0.22   lose (-0.18)
lb126 top30 skip21                +5.4%   +13.2%     0.46     0.52   -28.8%     0.19   lose (-0.25)
lb126 top50 skip21                +5.7%   +12.2%     0.52     0.58   -27.3%     0.21   lose (-0.19)
lb252 top30 skip21                +4.8%   +12.6%     0.43     0.48   -29.1%     0.16   lose (-0.28)
lb252 top50 skip21                +4.8%   +11.7%     0.46     0.51   -30.3%     0.16   lose (-0.25)
lb252 top50 skip21 eqwt           +5.5%   +12.3%     0.50     0.55   -26.6%     0.21   lose (-0.21)
--------------------------------------------------------------------------------------------
EW-universe (baseline)           +12.3%   +18.9%     0.71     0.86   -56.1%     0.22
SPY buy&hold                     +10.9%   +18.6%     0.65     0.83   -55.2%     0.20

[run] sweep saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/sweep_pit_20260603_054927.txt
```
