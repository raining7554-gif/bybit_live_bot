"""암호화폐 뉴스 sentiment — CryptoPanic 무료 API 기반.

CryptoPanic 가 미리 집계된 positive/negative 투표 제공 → Gemini AI 호출
없이 즉시 sentiment 계산 가능.

free public access (공개 게시물만, 한도 약 200 req/day).
유료 API 키 있으면 더 많은 데이터 + 더 자주 갱신.

env: CRYPTOPANIC_API_KEY (선택)
"""
from __future__ import annotations
import os
import time
from typing import Optional

import requests


_news_cache: dict[str, tuple[float, int, float]] = {}
# symbol -> (sentiment_score, sample_size, fetched_ts)

_CACHE_TTL = 3600  # 1시간


def _fetch_cryptopanic(symbol_short: str) -> tuple[int, int, int]:
    """CryptoPanic 에서 종목 관련 최근 핫 뉴스의 vote 집계.

    Returns (positive, negative, total_posts) — 0,0,0 이면 데이터 부족 또는 실패.
    """
    api_key = os.environ.get("CRYPTOPANIC_API_KEY", "")
    base = "https://cryptopanic.com/api/v1/posts/"
    params = {
        "currencies": symbol_short,
        "kind": "news",
        "filter": "hot",
        "public": "true",
    }
    if api_key:
        params["auth_token"] = api_key
    headers = {"User-Agent": "tradebot/1.0"}
    try:
        r = requests.get(base, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"[news {symbol_short}] HTTP {r.status_code}", flush=True)
            return 0, 0, 0
        data = r.json()
        posts = data.get("results", [])[:30]
        pos = neg = 0
        for p in posts:
            votes = p.get("votes", {}) if isinstance(p, dict) else {}
            pos += int(votes.get("positive", 0))
            neg += int(votes.get("negative", 0))
        return pos, neg, len(posts)
    except Exception as e:
        print(f"[news {symbol_short}] err: {e}", flush=True)
        return 0, 0, 0


def get_news_sentiment(symbol: str) -> Optional[float]:
    """심볼의 최근 뉴스 sentiment (-1 강한 약세 ~ +1 강한 강세).

    None = 데이터 부족 (5표 미만).
    """
    short = symbol.replace("USDT", "").replace("USD", "").upper()
    if not short:
        return None
    now = time.time()
    if short in _news_cache:
        score, sample, ts = _news_cache[short]
        if now - ts < _CACHE_TTL:
            return score if sample >= 5 else None

    pos, neg, posts_count = _fetch_cryptopanic(short)
    total = pos + neg
    score = 0.0
    if total >= 5:
        score = (pos - neg) / total  # -1 ~ +1
    _news_cache[short] = (score, total, now)
    return score if total >= 5 else None
