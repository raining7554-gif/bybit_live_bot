"""텔레그램 알림 v1.1 - 중복 메시지 디듀핑 + 레이트리밋

- 동일(또는 거의 동일) 메시지가 짧은 시간 안에 연달아 오는 스팸을 차단.
- send_error 는 같은 에러 시그니처 기준 10분에 1회로 제한.
- 그 외 일반 메시지도 동일 텍스트 기준 60초 내 재전송은 스킵.
"""
import time
import hashlib
import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

# 메시지 시그니처 → 마지막 전송 epoch 초
_recent_sent: dict[str, float] = {}

# 동일 메시지(일반) 최소 재전송 간격
_DEFAULT_DEDUP_SEC = 60
# 에러 메시지 최소 재전송 간격
_ERROR_DEDUP_SEC = 600  # 10분


def _sig(message: str) -> str:
    # 앞 120자 기준 해시 (숫자 차이 때문에 달라지는 경우까지 흡수하려면 정규화 추가 가능)
    return hashlib.md5(message[:120].encode("utf-8", errors="ignore")).hexdigest()


def _should_send(message: str, min_interval: int) -> bool:
    now = time.time()
    key = _sig(message)
    last = _recent_sent.get(key, 0)
    if now - last < min_interval:
        return False
    _recent_sent[key] = now
    # 메모리 관리: 3600초 지난 엔트리 정리
    if len(_recent_sent) > 200:
        cutoff = now - 3600
        for k in [k for k, t in _recent_sent.items() if t < cutoff]:
            _recent_sent.pop(k, None)
    return True


def _raw_send(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM 미설정] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=5)
    except Exception as e:
        print(f"[TELEGRAM 오류] {e}")


def send(message: str, dedup_sec: int = _DEFAULT_DEDUP_SEC):
    """텔레그램 메시지 전송 (중복 메시지 자동 억제)"""
    if not _should_send(message, dedup_sec):
        return
    _raw_send(message)


def send_force(message: str):
    """중복 필터를 무시하고 바로 전송 (부팅·일일결산 등)"""
    _raw_send(message)


def send_buy(ticker: str, name: str, price: int, qty: int, amount: int, reason: str):
    # 매수/매도는 실제 체결 이벤트라 dedup 최소화(30초)
    send(
        f"🟢 <b>매수 체결</b>\n"
        f"종목: {name} ({ticker})\n"
        f"가격: {price:,}원 × {qty}주\n"
        f"금액: {amount:,}원\n"
        f"사유: {reason}",
        dedup_sec=30,
    )


def send_sell(ticker: str, name: str, price: int, qty: int, pnl: float, reason: str):
    emoji = "💰" if pnl >= 0 else "🔴"
    send(
        f"{emoji} <b>매도 체결</b>\n"
        f"종목: {name} ({ticker})\n"
        f"가격: {price:,}원 × {qty}주\n"
        f"수익률: {pnl:+.2f}%\n"
        f"사유: {reason}",
        dedup_sec=30,
    )


def send_scan_result(candidates: list):
    if not candidates:
        send("📊 스캔 완료 - 조건 충족 종목 없음")
        return
    lines = ["📊 <b>스캔 결과</b>"]
    for c in candidates:
        lines.append(f"• {c['name']} ({c['ticker']}) +{c['change_rate']:.1f}% 거래량{c['vol_ratio']:.0f}배")
    send("\n".join(lines))


def send_error(msg: str):
    """오류 알림 - 같은 에러는 10분에 1회만 전송"""
    send(f"⚠️ <b>오류 발생</b>\n{msg}", dedup_sec=_ERROR_DEDUP_SEC)


def send_daily_summary(total_pnl: float, trade_count: int):
    emoji = "✅" if total_pnl >= 0 else "❌"
    send_force(
        f"{emoji} <b>일일 결산</b>\n"
        f"총 수익률: {total_pnl:+.2f}%\n"
        f"거래 횟수: {trade_count}회"
    )
