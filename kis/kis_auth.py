import requests
import json
import time
import os
from datetime import datetime, timedelta
from config import APP_KEY, APP_SECRET, IS_PAPER

BASE_URL = "https://openapivts.koreainvestment.com:29443" if IS_PAPER else "https://openapi.koreainvestment.com:9443"

_token_info = {"access_token": None, "expires_at": None}

def get_access_token() -> str:
    """액세스 토큰 발급 (24시간 캐시)"""
    now = datetime.now()
    if _token_info["access_token"] and _token_info["expires_at"] > now:
        return _token_info["access_token"]

    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    resp = requests.post(url, json=body)
    resp.raise_for_status()
    data = resp.json()

    _token_info["access_token"] = data["access_token"]
    _token_info["expires_at"] = now + timedelta(hours=23)  # 만료 1시간 전 갱신
    print(f"[AUTH] 토큰 발급 완료 - 만료: {_token_info['expires_at'].strftime('%H:%M')}")
    return _token_info["access_token"]

def get_headers(tr_id: str) -> dict:
    """공통 헤더 생성"""
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }

def get(path: str, tr_id: str, params: dict) -> dict:
    """GET 요청"""
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=get_headers(tr_id), params=params)
    resp.raise_for_status()
    return resp.json()

def post(path: str, tr_id: str, body: dict) -> dict:
    """POST 요청"""
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, headers=get_headers(tr_id), json=body)
    resp.raise_for_status()
    return resp.json()
