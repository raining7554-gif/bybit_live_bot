"""Always-on 멀티에셋 실행 서비스 (레일웨이 worker).

레일웨이에 이 파일을 start 명령으로 띄우면: 배포 즉시 1회 리밸런스 실행 → 이후
7일마다 자동 실행. KIS 키가 있는 환경에서만 의미가 있다.

레일웨이 설정:
  - 새 서비스(같은 repo) 생성
  - Start Command:  python kis/multiasset_service.py
  - 환경변수:
      KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO   (한투 키)
      TG_TOKEN / TG_CHAT_ID                            (퀀트봇 알림)
      KIS_PAPER=true            (모의투자 — 처음엔 꼭 true)
      REBALANCE_EXECUTE=false   (드라이런 — 계획만, 익숙해지면 true)
      LIQUIDATE=false           (전환 1회만 true: 기존종목 청산)

안전 기본값: EXECUTE/PAPER 미설정이면 드라이런·모의 → 실수로 실거래 안 됨.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rebalance_live

PERIOD = int(os.environ.get("REBALANCE_PERIOD_SEC", str(7 * 24 * 3600)))  # 기본 7일


def _run_once():
    try:
        rebalance_live.main()
    except Exception:  # noqa: BLE001
        print("[service] 리밸런스 오류:\n" + traceback.format_exc())
        try:
            rebalance_live.quant_telegram("⚠️ 멀티에셋 리밸런스 오류 — 로그 확인 필요")
        except Exception:
            pass


def main():
    paper = os.environ.get("KIS_PAPER", "false").lower() == "true"
    execute = os.environ.get("REBALANCE_EXECUTE", "false").lower() == "true"
    print(f"🟢 멀티에셋 서비스 시작 — PAPER={paper} EXECUTE={execute} "
          f"주기={PERIOD/86400:.1f}일")
    while True:
        _run_once()
        time.sleep(PERIOD)


if __name__ == "__main__":
    main()
