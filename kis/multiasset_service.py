"""Always-on 멀티에셋 실행 서비스 (레일웨이 worker).

레일웨이에 start 명령으로 띄우면: 미국 정규장이 열려 있을 때 주1회 리밸런스 실행.
KIS 키가 있는 환경에서만 의미가 있다.

레일웨이 설정:
  - 새 서비스(같은 repo), Start Command:  python kis/multiasset_service.py
  - 환경변수:
      KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO   (한투 키)
      TG_TOKEN / TG_CHAT_ID                            (퀀트봇 — 계획+체결 알림)
      TELEGRAM_TOKEN / TELEGRAM_CHAT_ID = 퀀트봇과 동일값   (체결 알림도 퀀트봇으로)
      KIS_PAPER=false / REBALANCE_EXECUTE=false(처음) / US_FRACTIONAL_ENABLED=true
      REBALANCE_BUDGET_USD=500(테스트) → 0(전체)

정규장에만 주문 → 프리장/장마감 미체결 방지. 기본 안전값(드라이런).
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rebalance_live

CHECK_SEC = int(os.environ.get("CHECK_INTERVAL_SEC", "1800"))     # 30분마다 점검
MIN_GAP_SEC = int(os.environ.get("REBALANCE_PERIOD_SEC", str(6 * 24 * 3600)))  # 최소 6일 간격
FORCE_ANYTIME = os.environ.get("REBALANCE_ANYTIME", "false").lower() == "true"  # 장시간 무시(테스트)


def _us_market_open() -> bool:
    """미국 정규장(평일 09:30~16:00 ET) 여부. 공휴일은 KIS가 거부하므로 대략만."""
    try:
        import pytz
        now = datetime.now(pytz.timezone("America/New_York"))
    except Exception:
        return True                       # pytz 없으면 막지 않음
    if now.weekday() >= 5:                 # 주말
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= hm <= 16 * 60


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
          f"점검 {CHECK_SEC//60}분 / 최소간격 {MIN_GAP_SEC/86400:.1f}일 / "
          f"정규장만={'아니오' if FORCE_ANYTIME else '예'}")
    last_run = 0.0
    while True:
        now = time.time()
        due = (now - last_run) >= MIN_GAP_SEC
        tradable = FORCE_ANYTIME or not execute or _us_market_open()
        # execute=false(드라이런)면 계획만 보내므로 장시간 무관하게 실행
        if due and tradable:
            _run_once()
            last_run = now
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
