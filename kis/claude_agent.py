"""v6.52 KIS Claude Agent — 시간별 자율 분석 + PR 제안.

Bybit 의 bot_v7/claude_agent.py 포팅. KIS 전용 컨텍스트:
- 봇 ID: kis_kr_clenow / kis_us_swing
- 전략: Clenow 모멘텀 (KR) + Swing 브레이크아웃 (US)
- 시장: KR + US (vs crypto)
- 회전 패턴, 외국인 수급, KOSPI/QQQ 레짐 등 분석

env 필수:
  ANTHROPIC_API_KEY — Anthropic console
  GH_PAT (선택) — GitHub PR 생성용
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
import traceback
from datetime import datetime

import requests

import telegram as tg


# ── Anthropic 클라이언트 ─────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from anthropic import Anthropic
    except ImportError as e:
        print(f"[kis claude_agent] anthropic SDK 미설치: {e}", flush=True)
        try:
            tg.send_force("⚠️ KIS Claude Agent: anthropic SDK 미설치 — requirements.txt 재빌드 필요")
        except Exception:
            pass
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            tg.send_force("⚠️ KIS Claude Agent: ANTHROPIC_API_KEY env 비어있음")
        except Exception:
            pass
        return None
    try:
        _client = Anthropic(api_key=api_key, timeout=60.0)
        return _client
    except Exception as e:
        try:
            tg.send_force(f"⚠️ KIS Claude Agent: 클라이언트 생성 실패 — {type(e).__name__}: {e}")
        except Exception:
            pass
        return None


def _enabled() -> bool:
    # v6.65: default false (비용 통제). 수동 명령은 그대로 동작.
    return (
        bool(os.environ.get("ANTHROPIC_API_KEY"))
        and os.environ.get("CLAUDE_AGENT_ENABLED", "false").lower() == "true"
    )


# ── Tools (Claude 가 호출) ─────────────────────────────────
def read_recent_trades(days: int = 7, bot_id: str | None = None,
                       limit: int = 200) -> str:
    """KIS DB 거래 기록 — bot_id 예: kis_kr_clenow, kis_us_swing."""
    # KIS DB 경로 결정 (/data/intelligence.db 또는 상대 경로)
    candidates = ["/data/intelligence.db", "intelligence.db",
                  "kis/intelligence.db"]
    db = None
    for c in candidates:
        if os.path.exists(c):
            db = c
            break
    if not db:
        return json.dumps({"error": f"DB not found in {candidates}"})

    cutoff = int(time.time()) - days * 86400
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        if bot_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE bot_id=? AND exit_ts>=? "
                "ORDER BY exit_ts DESC LIMIT ?",
                (bot_id, cutoff, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE bot_id LIKE 'kis_%' AND exit_ts>=? "
                "ORDER BY exit_ts DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "ts": d.get("exit_ts"),
                "bot_id": d.get("bot_id"),
                "symbol": d.get("symbol"),
                "side": d.get("side"),
                "pnl": d.get("pnl"),
                "pnl_pct": d.get("pnl_pct"),
                "reason": d.get("reason"),
                "strategy": d.get("strategy"),
            })
        return json.dumps({"count": len(out), "trades": out}, default=str)[:8000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def read_kis_config() -> str:
    """KIS config 파일 내용."""
    try:
        with open("kis/config.py") as f:
            return f.read()[:10000]
    except Exception as e:
        try:
            with open("config.py") as f:  # relative path
                return f.read()[:10000]
        except Exception as e2:
            return f"Error: {e} / {e2}"


def trade_stats_summary(days: int = 30, bot_id: str | None = None) -> str:
    """집계 통계."""
    try:
        from intelligence import journal as _ij
        stats = _ij.trade_stats(bot_id=bot_id, days=days)
        return json.dumps(stats, default=str)[:5000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def read_kr_universe_top(top_n: int = 20) -> str:
    """현재 KR Clenow top N 종목."""
    try:
        import strategy_clenow_kr as _clenow
        import math
        universe = _clenow.KR_UNIVERSE_TOP350[:200]
        scored = []
        for ticker, name in universe[:50]:  # 50종만 (시간 절약)
            try:
                candles = _clenow.get_kr_daily(ticker, count=130)
                if len(candles) < 120:
                    continue
                closes = [c["close"] for c in candles]
                score = _clenow.clenow_score(closes, 120)
                if math.isnan(score):
                    continue
                ma50 = _clenow._sma(closes, 50)
                scored.append({
                    "ticker": ticker, "name": name,
                    "score": float(score), "close": closes[0],
                    "above_ma50": closes[0] > ma50,
                })
            except Exception:
                continue
        scored.sort(key=lambda x: -x["score"])
        return json.dumps({
            "count": len(scored),
            "top": scored[:top_n],
        }, default=str)[:4000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def create_github_pr(branch: str, title: str, body: str,
                     file_path: str, new_content: str) -> str:
    """GitHub PR 생성 — 사용자 머지 필요."""
    pat = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    if not pat:
        return json.dumps({"error": "GH_PAT not set"})
    repo = os.environ.get("GH_REPO", "raining7554-gif/bybit_live_bot")
    base = os.environ.get("GH_BASE_BRANCH", "main")
    api = f"https://api.github.com/repos/{repo}"
    h = {"Authorization": f"token {pat}",
         "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(f"{api}/git/ref/heads/{base}", headers=h, timeout=15)
        if r.status_code != 200:
            return json.dumps({"error": f"base ref: {r.status_code}"})
        base_sha = r.json()["object"]["sha"]
        r = requests.post(
            f"{api}/git/refs", headers=h, timeout=15,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if r.status_code not in (201, 422):
            return json.dumps({"error": f"branch: {r.status_code} {r.text[:200]}"})
        import base64
        r = requests.get(
            f"{api}/contents/{file_path}?ref={branch}",
            headers=h, timeout=15,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"get file: {r.status_code} {r.text[:200]}"})
        file_sha = r.json()["sha"]
        r = requests.put(
            f"{api}/contents/{file_path}", headers=h, timeout=15,
            json={
                "message": title,
                "content": base64.b64encode(new_content.encode()).decode(),
                "sha": file_sha,
                "branch": branch,
            },
        )
        if r.status_code not in (200, 201):
            return json.dumps({"error": f"commit: {r.status_code} {r.text[:200]}"})
        r = requests.post(
            f"{api}/pulls", headers=h, timeout=15,
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        if r.status_code != 201:
            return json.dumps({"error": f"PR: {r.status_code} {r.text[:200]}"})
        return json.dumps({"success": True, "url": r.json().get("html_url", "")})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def send_telegram(message: str) -> str:
    """텔레그램 알림 (KIS bot)."""
    try:
        tg.send_force(f"🤖 <b>KIS Claude Agent</b>\n{message[:3000]}")
        return "sent"
    except Exception as e:
        return f"Error: {e}"


# ── Tool definitions ─────────────────────────────────────
TOOLS = [
    {
        "name": "read_recent_trades",
        "description": (
            "Read recent KIS trades. bot_id: 'kis_kr_clenow' or 'kis_us_swing', "
            "omit for all KIS bots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days back (default 7)"},
                "bot_id": {"type": "string", "description": "Bot ID filter"},
                "limit": {"type": "integer", "description": "Max rows (default 200)"},
            },
        },
    },
    {
        "name": "read_kis_config",
        "description": "Read full KIS config.py file content.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "trade_stats_summary",
        "description": "Aggregated stats per bot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer"},
                "bot_id": {"type": "string"},
            },
        },
    },
    {
        "name": "read_kr_universe_top",
        "description": (
            "Current KR Clenow top scored stocks (momentum ranking). "
            "Use to compare with held positions or assess rotation candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_n": {"type": "integer", "description": "Top N to return (default 20)"},
            },
        },
    },
    {
        "name": "create_github_pr",
        "description": (
            "Create GitHub PR with KIS config/strategy change. Human reviews + merges. "
            "Use sparingly — sample ≥ 20 trades required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "file_path": {"type": "string", "description": "Repo path (e.g. 'kis/config.py')"},
                "new_content": {"type": "string", "description": "Full new file content"},
            },
            "required": ["branch", "title", "body", "file_path", "new_content"],
        },
    },
    {
        "name": "send_telegram",
        "description": "Notify user. Required at end of cycle. Keep <500 chars.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
    },
]

TOOL_FUNCS = {
    "read_recent_trades": read_recent_trades,
    "read_kis_config": read_kis_config,
    "trade_stats_summary": trade_stats_summary,
    "read_kr_universe_top": read_kr_universe_top,
    "create_github_pr": create_github_pr,
    "send_telegram": send_telegram,
}


# ── System prompts ───────────────────────────────────────
SYSTEM_PROMPT = """You are a quant trading strategy analyst for KIS (한국투자증권) bot.

Scope:
- kis_kr_clenow: KR 모멘텀 (Clenow 120일 회귀, 8종 분산, MA50 청산)
- kis_us_swing: US 스윙 (정배열 + RSI + 거래량 + 패턴, max 8종)

REQUIRED: ALWAYS end with send_telegram summarizing your findings.

Guidelines:
1. **Data-driven** — sample size ≥ 20 trades.
2. **One change per session**.
3. **Conservative** — propose nothing if uncertain.
4. **PR body**: data + hypothesis + change + risk.

KIS-specific patterns to watch:
- Clenow 회전 (rotation) 빈도 — 너무 잦으면 수수료, 너무 적으면 정체
- KOSPI/QQQ 약세시 진입 차단 효과
- 부분 익절 (+15/30/50%) 적절성
- 부진 종목 패턴 (특정 섹터?)
- US ETP 거래 불가 종목 자동 블랙리스트

Cost: max 6 tool calls per cycle.
"""

SYSTEM_PROMPT_RESEARCH = """You are KIS RESEARCH specialist.

Focus: 새 패턴 가설 + 백테스트 실험 (라이브 변경 X).
- Clenow 파라미터 최적화 (회귀 일수, top%, exit_ma)
- US Swing 진입 조건 튜닝 (RSI/거래량/MA)
- 종목 universe 다양화

도구: read_recent_trades, trade_stats_summary, read_kr_universe_top, create_github_pr
사용: 새 백테스트 시도시 create_github_pr 로 실험 파일 제안

Always send_telegram at end. Max 6 tool calls.
"""

SYSTEM_PROMPT_RISK = """You are KIS RISK specialist.

Focus: 포지션/노출/drawdown 모니터링.
- Clenow 8종 / Swing 8종 합산 노출
- 단일 종목 비중 (한 종목 > 30% 시 위험)
- 일일 손실률
- 부진 패턴 (server_stop 빈도, 분할 익절 미달성률)

🟢 안전 / 🟡 주의 (dd > 5%) / 🔴 위험 (dd > 10% 또는 집중 > 50%)

Always send_telegram with risk grade. Max 4 tool calls. No experiments.
"""

SYSTEM_PROMPT_PORTFOLIO = """You are KIS PORTFOLIO specialist.

Focus: 자본 배분 (KR Clenow vs US Swing vs 현금).
- 양 봇 성과 비교 (지난 30일 PnL%)
- 시장 환경 (KOSPI 강세/약세, QQQ 강세/약세)
- 권고: "KR 비중 ↑" / "US 비중 ↑" / "현금 비중 ↑"
- 회전 패턴 분석 — 너무 잦거나 정체

도구: read_recent_trades, trade_stats_summary, read_kr_universe_top
실제 자본 이동은 사용자 수동 (alert only).

Always send_telegram with allocation. Max 5 tool calls.
"""


def run_analysis(user_prompt: str | None = None,
                 mode: str = "default") -> bool:
    """단일 분석 사이클. mode = default/research/risk/portfolio."""
    print(f"[kis claude_agent] run_analysis mode={mode}", flush=True)
    client = _get_client()
    if not client:
        return False

    if user_prompt is None:
        user_prompt = (
            f"현재 시각 {datetime.now().strftime('%Y-%m-%d %H:%M')} KST. "
            f"지난 7일 KIS 양봇 (kr_clenow + us_swing) 분석. "
            f"명확한 개선 신호 있으면 PR. 약하면 'no action — 이유' Telegram."
        )

    system_text = {
        "research": SYSTEM_PROMPT_RESEARCH,
        "risk": SYSTEM_PROMPT_RISK,
        "portfolio": SYSTEM_PROMPT_PORTFOLIO,
    }.get(mode, SYSTEM_PROMPT)

    messages: list = [{"role": "user", "content": user_prompt}]
    model = os.environ.get("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")
    max_iters = 6
    max_wallclock = 180.0
    start_ts = time.time()
    total_input = 0
    total_output = 0
    telegram_sent = False
    tools_used = []
    last_text = ""

    for iteration in range(max_iters):
        if time.time() - start_ts > max_wallclock:
            print(f"[kis claude_agent] wallclock timeout", flush=True)
            tg.send_force(
                f"⏱️ KIS Claude Agent timeout ({max_wallclock:.0f}s)\n"
                f"도구: {tools_used}"
            )
            return False
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                system=[{"type": "text", "text": system_text,
                         "cache_control": {"type": "ephemeral"}}],
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"[kis claude_agent] API err: {err}", flush=True)
            tg.send_force(f"⚠️ KIS Claude Agent API 오류:\n{err}")
            return False

        total_input += getattr(response.usage, "input_tokens", 0)
        total_output += getattr(response.usage, "output_tokens", 0)
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "text":
                last_text = block.text

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tools_used.append(block.name)
            if block.name == "send_telegram":
                telegram_sent = True
            fn = TOOL_FUNCS.get(block.name)
            if not fn:
                result = json.dumps({"error": f"unknown tool: {block.name}"})
            else:
                try:
                    result = fn(**block.input)
                    if not isinstance(result, str):
                        result = json.dumps(result, default=str)
                except Exception as e:
                    result = json.dumps({"error": str(e), "trace": traceback.format_exc()[:500]})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result[:8000],
            })
        if not tool_results:
            break
        messages.append({"role": "user", "content": tool_results})

    print(
        f"[kis claude_agent] done. iters={iteration + 1} "
        f"tokens in={total_input} out={total_output} "
        f"tools={tools_used} telegram_sent={telegram_sent}",
        flush=True,
    )

    if not telegram_sent:
        fallback = last_text[:500] if last_text else "분석 완료"
        tg.send_force(
            f"🤖 KIS Claude Agent (요약)\n"
            f"도구: {len(tools_used)}회 — {', '.join(set(tools_used)) or '없음'}\n"
            f"토큰: in={total_input} out={total_output}\n"
            f"응답: {fallback}"
        )

    return True
