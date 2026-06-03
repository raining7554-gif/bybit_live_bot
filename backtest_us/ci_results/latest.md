# Clenow 백테스트 결과 — NASDAQ survivor

- 실행: 2026-06-03 03:07 UTC (GitHub Actions)
- 브랜치: main
- lookback=90, top_n=12

```
[run] loading 158 tickers + QQQ (refresh=False) ...
[data] yfinance 1: 0/2 ok
[data] SKIP SQ: ValueError SQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP ANSS: ValueError ANSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto

Clenow Momentum [NASDAQ survivor] — 156 stocks, lookback=90, top_n=12, cost=0.10%
period: 1999-03-10 .. 2026-06-02

                        Clenow top12      QQQ buy&hold       EW-universe
------------------------------------------------------------------------
총수익률                         3037.8%           1632.3%          13156.4%
CAGR                           13.5%             11.0%             19.7%
연변동성                           18.0%             26.9%             22.3%
Sharpe                          0.79              0.52              0.92
Sortino                         0.88              0.69              1.23
MDD                           -35.6%            -83.0%            -49.9%
Calmar                          0.38              0.13              0.39
최종자본                      $3,137,776        $1,732,261       $13,256,380
리밸런스 횟수                         1380                 -                 -
투자비중(레짐ON)                       73%                 -                 -
평균 회전율                           44%                 -                 -

[run] report saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/stooq_20260603_030738.txt
```
