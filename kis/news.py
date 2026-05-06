"""KR 뉴스 sentiment — 한경/매경/연합 RSS + Gemini 한국어 분석.

설계:
  - 매크로 sentiment: 30분 캐시. 시장 전체 분위기 + 키 테마 + 위험도.
  - 종목별 sentiment: 1시간 캐시. 회사명 매칭 헤드라인만 분석.
  - Gemini API 호출 최소화 (캐시 적극 활용).

용도:
  /news 명령 → 즉시 매크로 sentiment 출력
  09:00 KST 자동 → 시장 시작 시 매크로 분위기 텔레그램 보고
  진입 결정에는 아직 사용 X (정보 수집 단계)
"""
from __future__ import annotations
import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests


# ── RSS 소스 ────────────────────────────────────────────────
KR_RSS_FEEDS = [
    ("한경 경제",   "https://www.hankyung.com/feed/economy"),
    ("연합 경제",   "https://www.yna.co.kr/RSS/economy.xml"),
    ("매경 증권",   "https://www.mk.co.kr/rss/50200011/"),
    ("이데일리 경제", "https://rss.edaily.co.kr/economy_news.xml"),
]

# ── 캐시 ─────────────────────────────────────────────────────
_macro_cache: dict = {"data": None, "ts": 0.0}
_MACRO_TTL = 1800   # 30분

_stock_cache: dict[str, tuple[Optional[dict], float]] = {}
_STOCK_TTL = 3600   # 1시간

_news_pool_cache: dict = {"data": [], "ts": 0.0}
_POOL_TTL = 600     # 10분 (RSS 자체 캐시)


# ── RSS 파싱 ─────────────────────────────────────────────────
def _fetch_rss(url: str) -> list[str]:
    """RSS XML 에서 <title> 추출. 최대 20건/feed."""
    try:
        r = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; tradebot/1.0)"},
        )
        if r.status_code != 200:
            print(f"[news rss {r.status_code}] {url}", flush=True)
            return []
        # XML 파싱 (encoding 자동 감지)
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            return []
        titles = []
        for item in root.iter():
            tag = item.tag.split("}")[-1] if "}" in item.tag else item.tag
            if tag in ("item", "entry"):
                for child in item:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "title" and child.text:
                        t = child.text.strip()
                        if t:
                            titles.append(t)
                        break
        return titles[:20]
    except Exception as e:
        print(f"[news rss err] {url}: {e}", flush=True)
        return []


def fetch_news_pool() -> list[tuple[str, str]]:
    """전체 RSS 풀. (source, title) 리스트. 10분 캐시."""
    now = time.time()
    if _news_pool_cache["data"] and now - _news_pool_cache["ts"] < _POOL_TTL:
        return _news_pool_cache["data"]
    pool = []
    for source, url in KR_RSS_FEEDS:
        titles = _fetch_rss(url)
        for t in titles:
            pool.append((source, t))
    _news_pool_cache["data"] = pool
    _news_pool_cache["ts"] = now
    return pool


# ── Gemini sentiment ────────────────────────────────────────
def _gemini_sentiment(prompt: str, timeout: int = 20) -> Optional[dict]:
    """Gemini 호출 → JSON 파싱. 실패시 None."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    if os.environ.get("AI_ENABLED", "false").lower() != "true":
        return None

    model = os.environ.get("AI_MODEL", "gemini-2.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 500,
            "responseMimeType": "application/json",
        },
    }
    try:
        r = requests.post(url, json=body, timeout=timeout)
        if r.status_code != 200:
            print(f"[news gemini {r.status_code}] {r.text[:150]}", flush=True)
            return None
        data = r.json()
        cands = data.get("candidates", [])
        if not cands:
            return None
        text = "".join(p.get("text", "")
                       for p in cands[0].get("content", {}).get("parts", []))
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 코드펜스 또는 prose 둘러싸여있을 수 있음
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None
    except Exception as e:
        print(f"[news gemini exc] {e}", flush=True)
        return None


# ── Public API ──────────────────────────────────────────────
def get_kr_market_sentiment() -> Optional[dict]:
    """매크로 sentiment.

    Returns: {
        "sentiment": -1.0 ~ +1.0,
        "summary_kr": "1~2줄 요약",
        "key_themes": ["테마1", "테마2"],
        "risk_level": "low" | "medium" | "high",
        "count": int (분석한 헤드라인 수)
    }
    또는 None (데이터 부족 / API 실패).
    """
    now = time.time()
    if _macro_cache["data"] and now - _macro_cache["ts"] < _MACRO_TTL:
        return _macro_cache["data"]

    pool = fetch_news_pool()
    if len(pool) < 5:
        return None

    titles_text = "\n".join(f"- [{s}] {t}" for s, t in pool[:30])
    prompt = (
        "당신은 한국 주식시장 분석가입니다. 최근 경제 뉴스 헤드라인을 분석해서\n"
        "코스피/코스닥 시장 전체 sentiment 를 평가하세요.\n"
        "\n"
        "JSON 으로만 응답 (다른 텍스트 없이):\n"
        "{\n"
        '  "sentiment": -1.0~+1.0 (강한 약세 ~ 강한 강세),\n'
        '  "summary_kr": "한국어 1~2 줄 요약 (60자 이내)",\n'
        '  "key_themes": ["주요 테마 1", "테마 2", "테마 3"],\n'
        '  "risk_level": "low" | "medium" | "high"\n'
        "}\n"
        "\n"
        f"분석 대상 헤드라인 ({len(pool)}건):\n"
        f"{titles_text}\n"
    )
    result = _gemini_sentiment(prompt)
    if result:
        result["count"] = len(pool)
        _macro_cache["data"] = result
        _macro_cache["ts"] = now
    return result


def get_stock_news_sentiment(ticker: str, name: str) -> Optional[dict]:
    """종목별 sentiment (회사명 매칭 헤드라인만).

    Returns: {sentiment, summary_kr, key_event, count} 또는 None.
    """
    cache_key = f"{ticker}:{name}"
    now = time.time()
    if cache_key in _stock_cache:
        data, ts = _stock_cache[cache_key]
        if now - ts < _STOCK_TTL:
            return data

    pool = fetch_news_pool()
    # 회사명 또는 ticker 매칭
    relevant = [(s, t) for s, t in pool if name in t or ticker in t]
    if len(relevant) < 2:
        _stock_cache[cache_key] = (None, now)
        return None

    titles_text = "\n".join(f"- [{s}] {t}" for s, t in relevant[:10])
    prompt = (
        f"한국 주식 {name}({ticker}) 관련 뉴스 헤드라인을 분석.\n"
        "\n"
        "JSON 응답 (다른 텍스트 없이):\n"
        "{\n"
        '  "sentiment": -1.0~+1.0,\n'
        '  "summary_kr": "1줄 요약 (40자)",\n'
        '  "key_event": "이벤트 한 단어 (예: 실적호조, 부진, 신제품)"\n'
        "}\n"
        "\n"
        f"뉴스 ({len(relevant)}건):\n"
        f"{titles_text}\n"
    )
    result = _gemini_sentiment(prompt)
    if result:
        result["count"] = len(relevant)
    _stock_cache[cache_key] = (result, now)
    return result


def format_market_sentiment_msg(s: dict) -> str:
    """매크로 sentiment dict → 텔레그램 메시지."""
    if not s:
        return "📰 KR 시장 sentiment — 데이터 없음"
    score = s.get("sentiment", 0.0)
    pct = score * 100
    if score >= 0.3:
        icon = "🟢🟢"
        mood = "강세"
    elif score >= 0.1:
        icon = "🟢"
        mood = "약강세"
    elif score >= -0.1:
        icon = "⚪"
        mood = "중립"
    elif score >= -0.3:
        icon = "🔴"
        mood = "약약세"
    else:
        icon = "🔴🔴"
        mood = "강약세"

    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(s.get("risk_level", "medium"), "🟡")

    themes = s.get("key_themes", [])
    themes_str = ", ".join(themes[:3]) if themes else "없음"

    return (
        f"📰 <b>KR 시장 sentiment</b> ({s.get('count', 0)} 헤드라인)\n"
        f"{icon} {mood} ({pct:+.0f})\n"
        f"위험도: {risk_emoji} {s.get('risk_level', '?')}\n"
        f"요약: {s.get('summary_kr', '?')}\n"
        f"테마: {themes_str}"
    )
