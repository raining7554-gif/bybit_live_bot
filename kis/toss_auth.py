"""토스증권 Open API 인증·요청 헬퍼.

OAuth 2.0 Client Credentials Grant. client 당 유효 토큰 1개(재발급시 이전 토큰 무효)
이므로 토큰을 캐시해 재사용한다. 모든 계좌 API는 X-Tossinvest-Account 헤더 필요.

  export TOSS_CLIENT_ID=...  TOSS_CLIENT_SECRET=...
  from toss_auth import request
  accounts = request("GET", "/api/v1/accounts")["result"]
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("TOSS_API_BASE", "https://openapi.tossinvest.com")
CLIENT_ID = os.environ.get("TOSS_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "")

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
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/oauth2/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            ej = json.loads(body)
            raise TossError(e.code, ej.get("error", "auth-error"),
                            ej.get("error_description", body[:200]))
        except (ValueError, KeyError):
            raise TossError(e.code, "auth-error", body[:200])
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
    if params:
        url += "?" + urllib.parse.urlencode(params)
    payload = json.dumps(body).encode() if body is not None else None

    for attempt in range(retries):
        _throttle()
        headers = {"Authorization": f"Bearer {get_token()}"}
        if account_seq is not None:
            headers["X-Tossinvest-Account"] = str(account_seq)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            if e.code == 429 and attempt < retries - 1:
                time.sleep(float(e.headers.get("Retry-After", "1")) + 0.2)
                continue
            if e.code == 401 and attempt < retries - 1:
                _token["access_token"] = None            # 토큰 강제 갱신 후 재시도
                continue
            # 에러 바디에서 code/message 추출 (BFF 공통 envelope)
            code, msg, rid = f"http-{e.code}", raw[:200], ""
            try:
                ej = json.loads(raw).get("error", {})
                code = ej.get("code", code)
                msg = ej.get("message", msg)
                rid = ej.get("requestId", "")
            except (ValueError, AttributeError):
                pass
            raise TossError(e.code, code, msg, rid)
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise TossError(0, "network", str(e))
    raise TossError(0, "exhausted", f"{method} {path} 재시도 소진")
