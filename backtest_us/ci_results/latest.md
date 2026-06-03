# NASDAQ Clenow 백테스트 결과

- 실행: 2026-06-03 00:03 UTC (GitHub Actions)
- 브랜치: main
- lookback=90, top_n=12

```
[run] loading 158 tickers + QQQ from stooq cache (refresh=False) ...
[data] yfinance 1: 40/40 ok
[data] yfinance 2: 39/40 ok
[data] yfinance 3: 40/40 ok
[data] yfinance 4: 37/38 ok
[data] SKIP SQ: ValueError SQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP ANSS: ValueError ANSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] fetched 156/158 new; sample range 1999-01-22..2026-06-02
[data] yfinance 1: 1/1 ok
[data] fetched 1/1 new; sample range 1999-03-10..2026-06-02

NASDAQ Clenow Momentum — 156 stocks, lookback=90, top_n=12, cost=0.10%
period: 1999-03-10 .. 2026-06-02

                        Clenow top12      QQQ buy&hold
------------------------------------------------------
총수익률                         3037.8%           1632.3%
CAGR                           13.5%             11.0%
연변동성                           18.0%             26.9%
Sharpe                          0.79              0.52
Sortino                         0.88              0.69
MDD                           -35.6%            -83.0%
Calmar                          0.38              0.13
최종자본                      $3,137,776        $1,732,261
리밸런스 횟수                         1380                 -
투자비중(레짐ON)                       73%                 -
평균 회전율                           44%                 -

[run] report saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/stooq_20260603_000318.txt
```
