"""v6.43 Claude Agent — 시간별 자율 분석 + PR 제안.

작동 흐름:
  1. 매 시간 1회 트리거 (runner._maybe_run_claude_agent)
  2. Claude Sonnet 4.6 + tool use
  3. DB / config 읽기 → 패턴 발견 → 가설 → PR 생성 → 텔레그램 알림
  4. 사용자가 PR 검토 후 머지

비용 (캐싱 활용):
  - 시간당 1회 = ~$0.015/call
  - 일 24 × $0.015 = $0.36
  - 월 ~$11

env 필수:
  ANTHROPIC_API_KEY — Anthropic console 에서 발급
  GH_PAT (선택) — GitHub Personal Access Token (PR 생성용)

env 선택:
  CLAUDE_AGENT_ENABLED=true (기본)
  CLAUDE_AGENT_INTERVAL_SEC=3600 (기본 1시간)
  CLAUDE_AGENT_MODEL=claude-sonnet-4-6 (기본)
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
import traceback
from datetime import datetime

import requests

from . import config as cfg
from . import notifier as tg


# ── Anthropic 클라이언트 ─────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from anthropic import Anthropic
    except ImportError as e:
        print(f"[claude_agent] anthropic SDK 미설치: {e}", flush=True)
        try:
            tg.send_force("⚠️ Claude Agent: anthropic SDK 미설치 — Railway 재배포 필요")
        except Exception:
            pass
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            tg.send_force("⚠️ Claude Agent: ANTHROPIC_API_KEY env 비어있음")
        except Exception:
            pass
        return None
    try:
        _client = Anthropic(api_key=api_key, timeout=60.0)
        return _client
    except Exception as e:
        try:
            tg.send_force(f"⚠️ Claude Agent: 클라이언트 생성 실패 — {type(e).__name__}: {e}")
        except Exception:
            pass
        return None


def _enabled() -> bool:
    return (
        bool(os.environ.get("ANTHROPIC_API_KEY"))
        and os.environ.get("CLAUDE_AGENT_ENABLED", "true").lower() == "true"
    )


# ── Tools (Claude 가 호출할 함수) ─────────────────────────
def read_recent_trades(days: int = 7, bot_id: str | None = None,
                       limit: int = 200) -> str:
    """최근 N일 거래 기록 (intelligence.db)."""
    db_path = os.environ.get("STATE_PATH", "/data/state_v7.json")
    # state_v7.json 경로의 부모에서 intelligence.db 찾기
    parent = os.path.dirname(db_path) or "/data"
    db = os.path.join(parent, "intelligence.db")
    if not os.path.exists(db):
        return json.dumps({"error": f"DB not found: {db}"})

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
                "SELECT * FROM trades WHERE exit_ts>=? "
                "ORDER BY exit_ts DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        # 간소화: 핵심 필드만
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "ts": d.get("exit_ts"),
                "symbol": d.get("symbol"),
                "side": d.get("side"),
                "score": d.get("score"),
                "tier": d.get("tier"),
                "pnl": d.get("pnl"),
                "pnl_pct": d.get("pnl_pct"),
                "reason": d.get("reason"),
                "strategy": d.get("strategy"),
            })
        return json.dumps({"count": len(out), "trades": out}, default=str)[:8000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def read_config(bot: str = "bybit") -> str:
    """현재 bot config 파일 내용 반환."""
    path = "bot_v7/config.py" if bot == "bybit" else "kis/config.py"
    try:
        with open(path) as f:
            return f.read()[:10000]
    except Exception as e:
        return f"Error: {e}"


def read_recent_regimes(days: int = 3) -> str:
    """최근 N일 레짐 분류 결과."""
    db_path = os.environ.get("STATE_PATH", "/data/state_v7.json")
    parent = os.path.dirname(db_path) or "/data"
    db = os.path.join(parent, "intelligence.db")
    if not os.path.exists(db):
        return json.dumps({"error": f"DB not found: {db}"})
    cutoff = int(time.time()) - days * 86400
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM regimes WHERE ts>=? ORDER BY ts DESC LIMIT 200",
            (cutoff,),
        ).fetchall()
        out = [dict(r) for r in rows]
        return json.dumps({"count": len(out), "regimes": out}, default=str)[:5000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def trade_stats_summary(days: int = 30, bot_id: str | None = None) -> str:
    """승률, PnL, 시간대별 통계 요약."""
    try:
        from intelligence import journal as _ij
        stats = _ij.trade_stats(bot_id=bot_id, days=days)
        return json.dumps(stats, default=str)[:5000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def create_github_pr(branch: str, title: str, body: str,
                     file_path: str, new_content: str) -> str:
    """GitHub PR 생성. (사용자 머지 필요)

    branch: feature/claude-... 형식
    file_path: 'bot_v7/config.py' 같은 repo 상대 경로
    """
    pat = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    if not pat:
        return json.dumps({"error": "GH_PAT not set — cannot create PR"})
    repo = os.environ.get("GH_REPO", "raining7554-gif/bybit_live_bot")
    base = os.environ.get("GH_BASE_BRANCH", "main")
    api = f"https://api.github.com/repos/{repo}"
    h = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
    }
    try:
        # 1) base SHA
        r = requests.get(f"{api}/git/ref/heads/{base}", headers=h, timeout=15)
        if r.status_code != 200:
            return json.dumps({"error": f"base ref: {r.status_code} {r.text[:200]}"})
        base_sha = r.json()["object"]["sha"]
        # 2) 새 브랜치 생성 (이미 있으면 통과)
        r = requests.post(
            f"{api}/git/refs", headers=h, timeout=15,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if r.status_code not in (201, 422):  # 422 = already exists
            return json.dumps({"error": f"branch create: {r.status_code} {r.text[:200]}"})
        # 3) 파일 현재 sha (수정용)
        import base64
        r = requests.get(
            f"{api}/contents/{file_path}?ref={branch}",
            headers=h, timeout=15,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"get file: {r.status_code} {r.text[:200]}"})
        file_sha = r.json()["sha"]
        # 4) 커밋
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
        # 5) PR
        r = requests.post(
            f"{api}/pulls", headers=h, timeout=15,
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        if r.status_code != 201:
            return json.dumps({"error": f"PR: {r.status_code} {r.text[:200]}"})
        url = r.json().get("html_url", "")
        return json.dumps({"success": True, "url": url})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def send_telegram(message: str) -> str:
    """텔레그램 알림 (사용자에게 인사이트/PR 보고)."""
    try:
        tg.send_force(f"🤖 <b>Claude Agent</b>\n{message[:3000]}")
        return "sent"
    except Exception as e:
        return f"Error: {e}"


# ── Tool definitions for Anthropic API ──────────────────
TOOLS = [
    {
        "name": "read_recent_trades",
        "description": (
            "Read recent trades from intelligence.db. Returns count + trades list."
            " Each trade has: ts, symbol, side, score, tier, pnl, pnl_pct, reason, strategy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days back (default 7)"},
                "bot_id": {"type": "string",
                           "description": "Filter, e.g. 'bybit_d' or 'kis_kr_clenow'. Omit for all."},
                "limit": {"type": "integer", "description": "Max rows (default 200)"},
            },
        },
    },
    {
        "name": "read_config",
        "description": "Read full config.py file content for bybit or kis bot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bot": {"type": "string", "enum": ["bybit", "kis"]},
            },
            "required": ["bot"],
        },
    },
    {
        "name": "read_recent_regimes",
        "description": "Read regime classifier outputs (rule-based, trending/ranging/mixed).",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days back (default 3)"},
            },
        },
    },
    {
        "name": "trade_stats_summary",
        "description": "Aggregated stats: tier breakdown, symbol breakdown, win rate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days back (default 30)"},
                "bot_id": {"type": "string", "description": "Optional filter"},
            },
        },
    },
    {
        "name": "create_github_pr",
        "description": (
            "Create a GitHub PR with config/strategy change. "
            "Human reviews + merges. Use sparingly — only when sample ≥ 20 trades supports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name (e.g. 'claude/auto-tune-YYYYMMDD-HH')"},
                "title": {"type": "string", "description": "PR title (concise)"},
                "body": {"type": "string", "description": "PR description with data justification"},
                "file_path": {"type": "string", "description": "Repo-relative path"},
                "new_content": {"type": "string", "description": "Full new file content"},
            },
            "required": ["branch", "title", "body", "file_path", "new_content"],
        },
    },
    {
        "name": "send_telegram",
        "description": (
            "Send notification to user. Use for: PR alert, significant insight,"
            " no-action confirmation. Keep message <500 chars."
        ),
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
    "read_config": read_config,
    "read_recent_regimes": read_recent_regimes,
    "trade_stats_summary": trade_stats_summary,
    "create_github_pr": create_github_pr,
    "send_telegram": send_telegram,
}


# ── 메인 분석 루프 ───────────────────────────────────────
SYSTEM_PROMPT = """You are a quantitative trading strategy analyst for an automated Bybit + KIS bot.

Your role:
- Periodically analyze recent trades + market state
- Find patterns that suggest config/strategy improvements
- Propose changes via GitHub PR (human reviews)
- Notify user via Telegram with concise findings

REQUIRED: ALWAYS end with at least one send_telegram call summarizing your findings.
Even if no PR is needed, report what you analyzed and your conclusion.

Guidelines:
1. **Data-driven only** — every recommendation needs sample size ≥ 20 trades.
2. **One change per session** — avoid over-tuning.
3. **Conservative** — when in doubt, propose nothing but DO report what you saw.
4. **Always notify** — final send_telegram with: sample size, key findings, action taken (or "no action — reason").
5. **PR body must include**:
   - Data: sample size, win rate, PnL impact
   - Hypothesis: what pattern was found
   - Change: exact param diff
   - Risk: worst case scenario

Available bots:
- bybit_d (D + D_INV + MR strategy on Bybit perpetuals)
- kis_kr_clenow (KR Clenow momentum)
- kis_us_swing (US swing)

Common patterns to watch for:
- Tier-specific losses (mid/high tier underperforming)
- Symbol-specific losses (SOL has been bad)
- Time-of-day patterns (06-12 KST bad for Bybit)
- server_stop high % (SL too tight)
- Score correlation with win rate (D_INV experiment)

Cost optimization:
- Use tools efficiently, max ~6-8 tool calls per cycle.
"""


def run_analysis(user_prompt: str | None = None) -> bool:
    """단일 분석 사이클 실행. 성공시 True."""
    print("[claude_agent] run_analysis start", flush=True)
    client = _get_client()
    if not client:
        print("[claude_agent] no client", flush=True)
        return False
    print("[claude_agent] client OK, calling Anthropic API...", flush=True)
    if user_prompt is None:
        user_prompt = (
            f"현재 시각 {datetime.now().strftime('%Y-%m-%d %H:%M')} KST. "
            f"지난 24시간 거래 분석. 명확한 개선 신호 있으면 PR 제안. "
            f"표본 부족/신호 약함이면 'no action — 이유' 로 Telegram. "
            f"중요: 분석 결과를 반드시 send_telegram 으로 보고하고 끝낼 것."
        )

    messages: list = [{"role": "user", "content": user_prompt}]
    model = os.environ.get("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")
    max_iters = 10
    total_input = 0
    total_output = 0
    telegram_sent = False
    tools_used = []
    last_text = ""

    for iteration in range(max_iters):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"[claude_agent] API err: {err_msg}", flush=True)
            tg.send_force(f"⚠️ Claude Agent API 오류:\n{err_msg}")
            return False

        total_input += getattr(response.usage, "input_tokens", 0)
        total_output += getattr(response.usage, "output_tokens", 0)

        # assistant turn 저장
        messages.append({"role": "assistant", "content": response.content})

        # 마지막 텍스트 응답 기억 (fallback 용)
        for block in response.content:
            if block.type == "text":
                last_text = block.text

        if response.stop_reason == "end_turn":
            break

        # tool_use 처리
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
        f"[claude_agent] cycle done. iters={iteration + 1} "
        f"tokens in={total_input} out={total_output} "
        f"tools={tools_used} telegram_sent={telegram_sent}",
        flush=True,
    )

    # v6.44: fallback — telegram 안 보냈으면 강제 요약 전송
    if not telegram_sent:
        fallback = last_text[:500] if last_text else "분석 완료 (구체 응답 없음)"
        tg.send_force(
            f"🤖 Claude Agent (요약)\n"
            f"도구 호출: {len(tools_used)}회 — {', '.join(set(tools_used)) or '없음'}\n"
            f"토큰: in={total_input} out={total_output}\n"
            f"응답: {fallback}"
        )

    return True
