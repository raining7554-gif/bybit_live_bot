"""토스증권 Open API 인증·요청 헬퍼.

OAuth 2.0 Client Credentials Grant. client 당 유효 토큰 1개(재발급시 이전 토큰 무효)
이므로 토큰을 캐시해 재사용한다. 모든 계좌 API는 X-Tossinvest-Account 헤더 필요.

고정 IP가 필요한 토스 허용 IP 정책 때문에, 호스팅(예: Railway)의 아웃바운드 IP가
유동적이면 TOSS_PROXY(고정 IP 프록시)를 설정한다. 그러면 '토스 호출만' 그 프록시로
나가고(텔레그램·시세데이터 다운로드는 직접) 토스에는 프록시의 고정 IP를 등록하면 된다.

  export TOSS_CLIENT_ID=...  TOSS_CLIENT_SECRET=...
  export TOSS_PROXY=http://user:pass@proxyhost:port   # 선택(고정 IP 프록시)
  from toss_auth import request
  accounts = request("GET", "/api/v1/accounts")["result"]
"""
from __future__ import annotations

import os
import time

import requests

BASE = os.environ.get("TOSS_API_BASE", "https://openapi.tossinvest.com")
CLIENT_ID = os.environ.get("TOSS_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "")

# 고정 IP 프록시 (선택). 설정 시 토스 호출만 이 프록시를 경유한다.
_PROXY = os.environ.get("TOSS_PROXY", "").strip()
PROXIES = {"http": _PROXY, "https": _PROXY} if _PROXY else None

# 레이트리밋 완화용 최소 호출 간격(초). 계좌계열 그룹이 1req/s로 가장 빡빡해서 기본 1.1초.
MIN_INTERVAL = float(os.environ.get("TOSS_MIN_INTERVAL", "1.1"))

_token = {"access_token": None, "exp": 0.0}
_last_call = {"t": 0.0}


class TossError(RuntimeError):
    """토스 API 에러 — code/message를 담는다."""

    def __init__(self, status, code, message, request_id=""):
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{status}] {code}: {message}")


def get_token() -> str:
    now = time.time()
    if _token["access_token"] and _token["exp"] - 60 > now:
        return _token["access_token"]
    if not CLIENT_ID or not CLIENT_SECRET:
        raise TossError(0, "no-credentials", "TOSS_CLIENT_ID/SECRET 미설정")
    try:
        resp = requests.post(
            f"{BASE}/oauth2/token",
            data={"grant_type": "client_credentials",
                  "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15, proxies=PROXIES)
    except requests.RequestException as e:
        raise TossError(0, "network", str(e))
    if resp.status_code != 200:
        code, msg = "auth-error", (resp.text or "")[:200]
        try:
            j = resp.json()
            code = j.get("error", code)
            msg = j.get("error_description", msg)
        except ValueError:
            pass
        raise TossError(resp.status_code, code, msg)
    j = resp.json()
    _token["access_token"] = j["access_token"]
    _token["exp"] = now + float(j.get("expires_in", 86400))
    return _token["access_token"]


def _throttle():
    if MIN_INTERVAL <= 0:
        return
    dt = time.time() - _last_call["t"]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last_call["t"] = time.time()


def request(method: str, path: str, account_seq=None, params=None,
            body=None, retries: int = 3) -> dict:
    """토스 API 호출. 성공시 파싱된 dict(보통 {'result': ...}) 반환.
    실패시 TossError(code/message) 발생. 429/401은 자동 재시도."""
    url = f"{BASE}{path}"
    for attempt in range(retries):
        _throttle()
        headers = {"Authorization": f"Bearer {get_token()}"}
        if account_seq is not None:
            headers["X-Tossinvest-Account"] = str(account_seq)
        try:
            resp = requests.request(method, url, params=params, json=body,
                                    headers=headers, timeout=15, proxies=PROXIES)
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise TossError(0, "network", str(e))

        if resp.status_code < 400:
            return resp.json() if resp.text else {}
        if resp.status_code == 429 and attempt < retries - 1:
            time.sleep(float(resp.headers.get("Retry-After", "1")) + 0.2)
            continue
        if resp.status_code == 401 and attempt < retries - 1:
            _token["access_token"] = None            # 토큰 강제 갱신 후 재시도
            continue
        code, msg, rid = f"http-{resp.status_code}", (resp.text or "")[:200], ""
        try:
            ej = resp.json().get("error", {})
            if isinstance(ej, dict):
                code = ej.get("code", code)
                msg = ej.get("message", msg)
                rid = ej.get("requestId", "")
            else:                                     # OAuth 스타일 {"error": "..."}
                code = resp.json().get("error", code)
                msg = resp.json().get("error_description", msg)
        except (ValueError, AttributeError):
            pass
        raise TossError(resp.status_code, code, msg, rid)
    raise TossError(0, "exhausted", f"{method} {path} 재시도 소진")
