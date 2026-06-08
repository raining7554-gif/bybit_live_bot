# Clenow 백테스트 결과 — NASDAQ survivor

- 실행: 2026-06-08 05:09 UTC (GitHub Actions)
- 브랜치: main
- lookback=90, top_n=12

```
[run] loading 158 tickers + QQQ (refresh=False) ...
[data] yfinance 1: 0/2 ok
[data] SKIP SQ: ValueError SQ: non-CSV stooq response ('<!DOCTYPE html><html><head><meta charset=
[data] SKIP ANSS: ValueError ANSS: non-CSV stooq response ('<!DOCTYPE html><html><head><meta charse
[data] sanitize: dropped 1/156 corrupt series (e.g. PLUG)

Clenow Momentum [NASDAQ survivor] — 155 stocks, lookback=90, top_n=12, cost=0.10%
period: 1999-03-10 .. 2026-06-02

                        Clenow top12      QQQ buy&hold       EW-universe
------------------------------------------------------------------------
총수익률                         3096.8%           1632.3%          12957.9%
CAGR                           13.6%             11.0%             19.6%
연변동성                           18.0%             26.9%             22.2%
Sharpe                          0.80              0.52              0.92
Sortino                         0.88              0.69              1.23
MDD                           -34.8%            -83.0%            -49.8%
Calmar                          0.39              0.13              0.39
최종자본                      $3,196,760        $1,732,261       $13,057,950
리밸런스 횟수                         1380                 -                 -
투자비중(레짐ON)                       73%                 -                 -
평균 회전율                           44%                 -                 -

[run] report saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/stooq_20260608_050932.txt
```
