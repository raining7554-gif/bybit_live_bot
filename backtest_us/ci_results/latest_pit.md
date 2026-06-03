# Clenow 백테스트 결과 — S&P500 point-in-time (생존편향-free)

- 실행: 2026-06-03 04:27 UTC (GitHub Actions)
- 브랜치: main
- lookback=90, top_n=12

```
[run] PIT mode — 1194 S&P500 names (691 removed/delisted, 503 current), bench=SPY
[run] loading 1194 tickers + SPY (refresh=False) ...
[data] yfinance 1: 26/40 ok
[data] yfinance 2: 28/40 ok
[data] yfinance 3: 23/40 ok
[data] yfinance 4: 18/40 ok
[data] yfinance 5: 27/40 ok
[data] yfinance 6: 31/40 ok
[data] yfinance 7: 24/40 ok
[data] yfinance 8: 26/40 ok
[data] yfinance 9: 33/40 ok
[data] yfinance 10: 27/40 ok
[data] yfinance 11: 28/40 ok
[data] yfinance 12: 22/40 ok
[data] yfinance 13: 30/40 ok
[data] yfinance 14: 22/40 ok
[data] yfinance 15: 27/40 ok
[data] yfinance 16: 28/40 ok
[data] yfinance 17: 26/40 ok
[data] yfinance 18: 27/40 ok
[data] yfinance 19: 25/40 ok
[data] yfinance 20: 26/40 ok
[data] yfinance 21: 23/40 ok
[data] yfinance 22: 26/40 ok
[data] yfinance 23: 29/40 ok
[data] yfinance 24: 27/40 ok
[data] yfinance 25: 26/40 ok
[data] yfinance 26: 25/40 ok
[data] yfinance 27: 17/28 ok
[data] SKIP AABA: ValueError AABA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP AAMRQ: ValueError AAMRQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP ABC: ValueError ABC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ABKFQ: ValueError ABKFQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP ABMD: ValueError ABMD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ACAS: ValueError ACAS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ACKH: ValueError ACKH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ACS: ValueError ACS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ADS: ValueError ADS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AFS.A: ValueError AFS.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP AGC: ValueError AGC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AGN: ValueError AGN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AHM: ValueError AHM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AKS: ValueError AKS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ALTR: ValueError ALTR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ALXN: ValueError ALXN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP AMCC: ValueError AMCC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ANDW: ValueError ANDW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ANRZQ: ValueError ANRZQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP ANSS: ValueError ANSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ANTM: ValueError ANTM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP APCC: ValueError APCC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP APOL: ValueError APOL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ARC: ValueError ARC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ARG: ValueError ARG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ARNC: ValueError ARNC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ASN: ValueError ASN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AT: ValueError AT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP ATGE: ValueError ATGE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ATVI: ValueError ATVI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP AV: ValueError AV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP AVP: ValueError AVP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AW: ValueError AW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP AWE: ValueError AWE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AYE: ValueError AYE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP AZA.A: ValueError AZA.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP BAY: ValueError BAY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BBI: ValueError BBI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BCR: ValueError BCR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BDK: ValueError BDK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BEV: ValueError BEV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BF.B: ValueError BF.B: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BFI: ValueError BFI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BFO: ValueError BFO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BGEN: ValueError BGEN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BGG: ValueError BGG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BHGE: ValueError BHGE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BHMSQ: ValueError BHMSQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP BIG: ValueError BIG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BJS: ValueError BJS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BKB: ValueError BKB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BLL: ValueError BLL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BLS: ValueError BLS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BLY: ValueError BLY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BMET: ValueError BMET: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BMGCA: ValueError BMGCA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP BNI: ValueError BNI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BRCM: ValueError BRCM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BRK.B: ValueError BRK.B: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP BRL: ValueError BRL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BSC: ValueError BSC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP BT: ValueError BT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP BTUUQ: ValueError BTUUQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP BVSN: ValueError BVSN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP BXLT: ValueError BXLT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CBB: ValueError CBB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CBH: ValueError CBH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CBS: ValueError CBS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CBSS: ValueError CBSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CCTYQ: ValueError CCTYQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP CDAY: ValueError CDAY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CELG: ValueError CELG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CEN: ValueError CEN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CEPH: ValueError CEPH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CERN: ValueError CERN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CFL: ValueError CFL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CFN: ValueError CFN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CGP: ValueError CGP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CHK: ValueError CHK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CIT.A: ValueError CIT.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP CITGQ: ValueError CITGQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP CMA: ValueError CMA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CMCSK: ValueError CMCSK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP CNW: ValueError CNW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP COC.B: ValueError COC.B: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP COG: ValueError COG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP COV: ValueError COV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CPGX: ValueError CPGX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CPNLQ: ValueError CPNLQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP CRR: ValueError CRR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CTB: ValueError CTB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CTL: ValueError CTL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CTLT: ValueError CTLT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CTX: ValueError CTX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CTXS: ValueError CTXS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP CVC: ValueError CVC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CVH: ValueError CVH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CXO: ValueError CXO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CYM: ValueError CYM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP CYR: ValueError CYR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DALRQ: ValueError DALRQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP DAY: ValueError DAY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DCNAQ: ValueError DCNAQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP DF: ValueError DF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP DFS: ValueError DFS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DI: ValueError DI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP DISCA: ValueError DISCA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP DISCK: ValueError DISCK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP DISH: ValueError DISH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP DJ: ValueError DJ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP DNB: ValueError DNB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DNR: ValueError DNR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DO: ValueError DO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP DPHIQ: ValueError DPHIQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP DRE: ValueError DRE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DTV: ValueError DTV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP DWDP: ValueError DWDP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP EDS: ValueError EDS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP EKDKQ: ValueError EKDKQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP ENDP: ValueError ENDP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP ENRNQ: ValueError ENRNQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP EOP: ValueError EOP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ESV: ValueError ESV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ETFC: ValueError ETFC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP FBF: ValueError FBF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FBHS: ValueError FBHS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP FBO: ValueError FBO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FDC: ValueError FDC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FDO: ValueError FDO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FI: ValueError FI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP FII: ValueError FII: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FJ: ValueError FJ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP FL: ValueError FL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP FLIR: ValueError FLIR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP FLMIQ: ValueError FLMIQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP FLT: ValueError FLT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FLTWQ: ValueError FLTWQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP FRC: ValueError FRC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FRX: ValueError FRX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FSL: ValueError FSL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FTL.A: ValueError FTL.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP FTR: ValueError FTR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP FWLT: ValueError FWLT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP GAPTQ: ValueError GAPTQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP GAS: ValueError GAS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GFS.A: ValueError GFS.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP GGP: ValueError GGP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GIDL: ValueError GIDL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP GMCR: ValueError GMCR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP GPS: ValueError GPS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GPU: ValueError GPU: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GRA: ValueError GRA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GTW: ValueError GTW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GWF: ValueError GWF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP GX: ValueError GX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP HBI: ValueError HBI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HBOC: ValueError HBOC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP HCBK: ValueError HCBK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP HCP: ValueError HCP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HCR: ValueError HCR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HDLM: ValueError HDLM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP HES: ValueError HES: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HFC: ValueError HFC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HFS: ValueError HFS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HI: ValueError HI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP HMA: ValueError HMA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HNZ: ValueError HNZ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HPH: ValueError HPH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HRS: ValueError HRS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HSH: ValueError HSH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP HSP: ValueError HSP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP I: ValueError I: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq.
[data] SKIP IGT: ValueError IGT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP IKN: ValueError IKN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP IMNX: ValueError IMNX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP INCLF: ValueError INCLF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP IPG: ValueError IPG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JCP: ValueError JCP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JEC: ValueError JEC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JH: ValueError JH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP JHF: ValueError JHF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JNPR: ValueError JNPR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP JNS: ValueError JNS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JNY: ValueError JNY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JOS: ValueError JOS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JOY: ValueError JOY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP JP: ValueError JP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP JWN: ValueError JWN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP K: ValueError K: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq.
[data] SKIP KATE: ValueError KATE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP KORS: ValueError KORS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP KRB: ValueError KRB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP KRFT: ValueError KRFT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP KSE: ValueError KSE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP KSU: ValueError KSU: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP KWP: ValueError KWP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LDW.B: ValueError LDW.B: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP LEHMQ: ValueError LEHMQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP LLL: ValueError LLL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LLTC: ValueError LLTC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP LLX: ValueError LLX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LM: ValueError LM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP LO: ValueError LO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP LOR: ValueError LOR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LSI: ValueError LSI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LUB: ValueError LUB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP LVLT: ValueError LVLT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP LXK: ValueError LXK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MDP: ValueError MDP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MDR: ValueError MDR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MEA: ValueError MEA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MEL: ValueError MEL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MERQ: ValueError MERQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP MFE: ValueError MFE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MIL: ValueError MIL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MJN: ValueError MJN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MKG: ValueError MKG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MMC: ValueError MMC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MNK: ValueError MNK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MON: ValueError MON: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MRO: ValueError MRO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MTL: ValueError MTL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MTLQQ: ValueError MTLQQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP MWV: ValueError MWV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MWW: ValueError MWW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MXIM: ValueError MXIM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP MYG: ValueError MYG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MYL: ValueError MYL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP MZIAQ: ValueError MZIAQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP NAE: ValueError NAE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NAV: ValueError NAV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NBL: ValueError NBL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NCR: ValueError NCR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NFB: ValueError NFB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NLC: ValueError NLC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NLOK: ValueError NLOK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP NLSN: ValueError NLSN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP NOVL: ValueError NOVL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP NRTLQ: ValueError NRTLQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP NVLS: ValueError NVLS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP NXTL: ValueError NXTL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP NYN: ValueError NYN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP NYX: ValueError NYX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP OAT: ValueError OAT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ODP: ValueError ODP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP OMX: ValueError OMX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ONE: ValueError ONE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP OWENQ: ValueError OWENQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP PARA: ValueError PARA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PBCT: ValueError PBCT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PCH: ValueError PCH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PCP: ValueError PCP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PDCO: ValueError PDCO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PEAK: ValueError PEAK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PEL: ValueError PEL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PET: ValueError PET: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PETM: ValueError PETM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PGL: ValueError PGL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PGN: ValueError PGN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PHA: ValueError PHA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PKI: ValueError PKI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PLL: ValueError PLL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PMCS: ValueError PMCS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PNU: ValueError PNU: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PRD: ValueError PRD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PSFT: ValueError PSFT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP PVN: ValueError PVN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PVT: ValueError PVT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP PX: ValueError PX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP PXD: ValueError PXD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP QEP: ValueError QEP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP QLGC: ValueError QLGC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP QTRN: ValueError QTRN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP RAD: ValueError RAD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RAI: ValueError RAI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RATL: ValueError RATL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP RBD: ValueError RBD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RBK: ValueError RBK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RDC: ValueError RDC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RDS.A: ValueError RDS.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP RE: ValueError RE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP RHT: ValueError RHT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RLM: ValueError RLM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RML: ValueError RML: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RNB: ValueError RNB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP ROH: ValueError ROH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RRD: ValueError RRD: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RSHCQ: ValueError RSHCQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP RTN: ValueError RTN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP RYI: ValueError RYI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SAI: ValueError SAI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SAPE: ValueError SAPE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SBL: ValueError SBL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SEBL: ValueError SEBL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SFA: ValueError SFA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SFS: ValueError SFS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SGID: ValueError SGID: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SHN: ValueError SHN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SIAL: ValueError SIAL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SIVB: ValueError SIVB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SK: ValueError SK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP SLR: ValueError SLR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SMS: ValueError SMS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SNI: ValueError SNI: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SNV: ValueError SNV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SOTR: ValueError SOTR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SOV: ValueError SOV: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SRCL: ValueError SRCL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP STJ: ValueError STJ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP STO: ValueError STO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP STR: ValueError STR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SUNEQ: ValueError SUNEQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP SWN: ValueError SWN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SWY: ValueError SWY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP SXCL: ValueError SXCL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP SYMC: ValueError SYMC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP TA: ValueError TA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP TCOMA: ValueError TCOMA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP TGNA: ValueError TGNA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP TIF: ValueError TIF: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TIN: ValueError TIN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TMC.A: ValueError TMC.A: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP TMK: ValueError TMK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TOY: ValueError TOY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TRB: ValueError TRB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TRW: ValueError TRW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TSG: ValueError TSG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TSS: ValueError TSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TUP: ValueError TUP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TWC: ValueError TWC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP TWTR: ValueError TWTR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP TXU: ValueError TXU: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP UAWGQ: ValueError UAWGQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP UMG: ValueError UMG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP UN: ValueError UN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP UPR: ValueError UPR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP USH: ValueError USH: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP USHC: ValueError USHC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP USS: ValueError USS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP USW: ValueError USW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP UTX: ValueError UTX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP VAR: ValueError VAR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP VAT: ValueError VAT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP VIAB: ValueError VIAB: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP VIAC: ValueError VIAC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP VSTNQ: ValueError VSTNQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP VTSS: ValueError VTSS: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP WAMUQ: ValueError WAMUQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP WBA: ValueError WBA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WCG: ValueError WCG: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WCOEQ: ValueError WCOEQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP WFM: ValueError WFM: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WFT: ValueError WFT: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WIN: ValueError WIN: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WLA: ValueError WLA: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WLL: ValueError WLL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WLP: ValueError WLP: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WLTW: ValueError WLTW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP WNDXQ: ValueError WNDXQ: non-CSV stooq response ('Get your apikey:\n\n1. Open https://st
[data] SKIP WPX: ValueError WPX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WRK: ValueError WRK: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WWY: ValueError WWY: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WYE: ValueError WYE: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP WYND: ValueError WYND: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP X: ValueError X: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq.
[data] SKIP XEC: ValueError XEC: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP XL: ValueError XL: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stooq
[data] SKIP XLNX: ValueError XLNX: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] SKIP XTO: ValueError XTO: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP YNR: ValueError YNR: non-CSV stooq response ('Get your apikey:\n\n1. Open https://stoo
[data] SKIP YRCW: ValueError YRCW: non-CSV stooq response ('Get your apikey:\n\n1. Open https://sto
[data] fetched 697/1068 new; sample range 1999-11-18..2026-06-02
[data] sanitize: dropped 57/823 corrupt series (e.g. BEN, BMC, BOL, CAR, CBE, CFC, CIN, CNG...)
[data] yfinance 1: 1/1 ok
[data] fetched 1/1 new; sample range 1993-01-29..2026-06-02
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

[run] report saved: /home/runner/work/bybit_live_bot/bybit_live_bot/backtest_us/reports/pit_20260603_042713.txt
```
