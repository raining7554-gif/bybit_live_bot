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


def trigger_backtest_sweep(symbol: str = "BTCUSDT", days: int = 180) -> str:
    """v6.49: GitHub Actions weekly_sweep.yml 워크플로우 dispatch.
    백테스트 파라미터 sweep 결과는 며칠 후 PR 자동 생성됨.
    """
    pat = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    if not pat:
        return json.dumps({"error": "GH_PAT not set"})
    repo = os.environ.get("GH_REPO", "raining7554-gif/bybit_live_bot")
    workflow = "weekly_sweep.yml"
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    try:
        r = requests.post(
            url, timeout=15,
            headers={
                "Authorization": f"token {pat}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": "main", "inputs": {}},
        )
        if r.status_code == 204:
            return json.dumps({"success": True,
                               "msg": f"Sweep triggered ({symbol} {days}d). 결과는 GitHub Actions 완료 후 PR 로."})
        return json.dumps({"error": f"{r.status_code} {r.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def read_backtest_results(symbol: str = "BTC") -> str:
    """최근 sweep 결과 JSON 읽기."""
    fname = f"backtest/reports/sweep_mr_v5_{symbol.upper()}.json"
    try:
        with open(fname) as f:
            data = json.load(f)
        # top 5 만 반환 (전체는 너무 큼)
        top = data.get("top10", [])[:5]
        current = data.get("current", {})
        return json.dumps({
            "ts": data.get("ts"),
            "symbol": data.get("symbol"),
            "days": data.get("days"),
            "current_params": current,
            "top5": top,
        }, default=str)[:5000]
    except FileNotFoundError:
        return json.dumps({"error": f"No backtest result yet for {symbol}. Trigger sweep first."})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def write_strategy_variant(branch: str, variant_name: str,
                            base_file: str, modifications: dict,
                            description: str) -> str:
    """v6.49: 전략 변형 파일 생성 + PR.

    base_file: 기존 전략 파일 (예: 'backtest/strategies/strategy_mr_v5.py')
    modifications: 변경할 상수 dict (예: {'SCORE_MIN': 55, 'RSI_OVERSOLD': 32})
    description: PR body 설명

    동작:
    1. base_file 읽기
    2. modifications 적용 (정규식 치환)
    3. 새 파일명 = base_file 의 _vX → _v(X+1) 로 변경 또는 _experimental 추가
    4. PR 생성 → 사용자 머지하면 backtest sweep 가능
    """
    import re
    pat = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    if not pat:
        return json.dumps({"error": "GH_PAT not set"})
    repo = os.environ.get("GH_REPO", "raining7554-gif/bybit_live_bot")
    base = "main"

    # 1) base file 읽기 (로컬)
    try:
        with open(base_file) as f:
            content = f.read()
    except Exception as e:
        return json.dumps({"error": f"read base: {e}"})

    # 2) modifications 적용 — 각 키워드 = 값 치환
    for key, new_val in modifications.items():
        pattern = rf"^{re.escape(key)}\s*=\s*[\d.\[\]\(\),'\"\s\w]+"
        replacement = f"{key} = {repr(new_val)}"
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
        if new_content == content:
            return json.dumps({"error": f"pattern not matched: {key}"})
        content = new_content

    # 3) 새 파일 경로 — _experimental_{timestamp}
    base_dir, base_name = os.path.split(base_file)
    name_root, ext = os.path.splitext(base_name)
    ts_tag = datetime.utcnow().strftime("%Y%m%d_%H%M")
    new_path = f"{base_dir}/{name_root}_exp_{ts_tag}{ext}"

    # 4) GitHub PR
    body = (
        f"## Claude Agent 자율 전략 실험\n\n"
        f"**변형 이름**: {variant_name}\n\n"
        f"**기반**: `{base_file}`\n"
        f"**신규**: `{new_path}`\n\n"
        f"**변경 사항**:\n"
        + "\n".join(f"- `{k}` → `{v}`" for k, v in modifications.items())
        + f"\n\n**설명**: {description}\n\n"
        f"## 검증 방법\n"
        f"1. 머지 후 weekly_sweep workflow 수동 트리거\n"
        f"2. 결과 비교 (현재 vs experimental)\n"
        f"3. 더 좋으면 main 전략에 적용\n\n"
        f"⚠️ 라이브 적용 X — 백테스트 검증만"
    )

    h = {"Authorization": f"token {pat}",
         "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}"
    try:
        # base SHA
        r = requests.get(f"{api}/git/ref/heads/{base}", headers=h, timeout=15)
        if r.status_code != 200:
            return json.dumps({"error": f"base ref: {r.status_code}"})
        base_sha = r.json()["object"]["sha"]
        # branch
        r = requests.post(
            f"{api}/git/refs", headers=h, timeout=15,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if r.status_code not in (201, 422):
            return json.dumps({"error": f"branch: {r.status_code} {r.text[:200]}"})
        # new file commit
        import base64 as _b64
        r = requests.put(
            f"{api}/contents/{new_path}", headers=h, timeout=15,
            json={
                "message": f"exp: {variant_name}",
                "content": _b64.b64encode(content.encode()).decode(),
                "branch": branch,
            },
        )
        if r.status_code not in (200, 201):
            return json.dumps({"error": f"commit: {r.status_code} {r.text[:200]}"})
        # PR
        r = requests.post(
            f"{api}/pulls", headers=h, timeout=15,
            json={"title": f"exp: {variant_name}", "head": branch,
                  "base": base, "body": body},
        )
        if r.status_code != 201:
            return json.dumps({"error": f"PR: {r.status_code} {r.text[:200]}"})
        return json.dumps({"success": True, "url": r.json().get("html_url", "")})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


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
    {
        "name": "trigger_backtest_sweep",
        "description": (
            "Trigger GitHub Actions backtest sweep workflow. Use to test new "
            "parameter combinations. Results available in 5-10 min via PR."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol (BTCUSDT, ETHUSDT)"},
                "days": {"type": "integer", "description": "Historical days (default 180)"},
            },
        },
    },
    {
        "name": "read_backtest_results",
        "description": (
            "Read latest backtest sweep result JSON. Returns top 5 param "
            "combinations + current settings for comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol prefix (BTC, ETH)"},
            },
        },
    },
    {
        "name": "write_strategy_variant",
        "description": (
            "Create a new experimental strategy file with modified constants + PR. "
            "Use when hypothesizing entirely new param set worth testing. "
            "Variant is NOT applied live — only for backtest comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name (e.g. 'claude/exp-YYYYMMDD')"},
                "variant_name": {"type": "string", "description": "Short name (e.g. 'low-vol-strict')"},
                "base_file": {"type": "string", "description": "Path (e.g. 'backtest/strategies/strategy_mr_v5.py')"},
                "modifications": {
                    "type": "object",
                    "description": "Dict of constant_name → new_value (e.g. {'SCORE_MIN': 55, 'RSI_OVERSOLD': 32})",
                },
                "description": {"type": "string", "description": "Why this variant + expected effect"},
            },
            "required": ["branch", "variant_name", "base_file", "modifications", "description"],
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
    "trigger_backtest_sweep": trigger_backtest_sweep,
    "read_backtest_results": read_backtest_results,
    "write_strategy_variant": write_strategy_variant,
}


# ── 메인 분석 루프 ───────────────────────────────────────
SYSTEM_PROMPT = """You are a quantitative trading strategy analyst for an automated Bybit + KIS bot.

Your role:
- Periodically analyze recent trades + market state
- Find patterns that suggest config/strategy improvements
- Propose changes via GitHub PR (human reviews)
- **Run backtest experiments** on new hypotheses (zero live risk)
- Notify user via Telegram with concise findings

REQUIRED: ALWAYS end with at least one send_telegram call summarizing your findings.

## Available capabilities

### Analysis tools
- read_recent_trades: pull trade history
- read_config: read current strategy config
- read_recent_regimes: rule-based regime classifier output
- trade_stats_summary: aggregated stats

### Action tools
- create_github_pr: param changes (live config)
- send_telegram: alert user (REQUIRED at end)

### Experimental tools (NEW)
- trigger_backtest_sweep: run param sweep on historical data
- read_backtest_results: read latest sweep JSON
- write_strategy_variant: create new experimental strategy file + PR
  - Creates `strategy_mr_v5_exp_YYYYMMDD_HHMM.py` with modified constants
  - User merges + runs sweep → compares to current

## Workflow patterns

### Pattern 1: Quick config tune (live)
Use when: clear pattern in trades, low risk param adjustment
1. read_recent_trades + trade_stats_summary
2. Identify clear winner/loser pattern
3. create_github_pr with 1 param diff
4. send_telegram with rationale

### Pattern 2: Strategy experimentation (backtest only)
Use when: structural hypothesis (e.g. "MR with RSI 30/70 might be better than 35/65")
1. read_backtest_results (existing baseline)
2. write_strategy_variant with new constants
3. trigger_backtest_sweep (optional — already runs weekly)
4. send_telegram explaining hypothesis + expected validation timeline

### Pattern 3: No-op
Use when: no significant data, small sample
- Just send_telegram("no actionable signal — sample N, monitoring")

## Guidelines
1. **Data-driven only** — sample size ≥ 20 trades.
2. **One change per session** — avoid over-tuning.
3. **Conservative live changes** — strategy experiments via write_strategy_variant (zero risk).
4. **Cost** — max 6-8 tool calls per cycle.

## Current known issues
- SOL has been worst symbol (-$138 in 30 days)
- D high/mid tier losing despite D_INV inversion
- server_stop 63% — SL too tight
- v6.48 just tightened server trail (effect TBD)

## Bot IDs
- bybit_d (D + D_INV + MR strategies on Bybit perpetuals)
- kis_kr_clenow (KR Clenow momentum)
- kis_us_swing (US swing)
"""


SYSTEM_PROMPT_RESEARCH = """You are a quant strategy RESEARCH specialist.

Focus: find new patterns, propose backtest experiments.
- Read recent trades + market state
- Identify untested hypotheses
- Use write_strategy_variant to create experimental files
- Use trigger_backtest_sweep to validate
- DO NOT propose live config changes (research only)

Always end with send_telegram summarizing what you found + what you tested.
Max 6 tool calls. Sample requirements: ≥ 30 trades for pattern claims.
"""

SYSTEM_PROMPT_RISK = """You are a quant RISK specialist.

Focus: position sizing, exposure, drawdown alerts.
- Read current positions + recent PnL
- Check tier/symbol concentration
- Alert if exposure > safe limit
- Propose MAX_TOTAL_MARGIN adjustment if needed

Always end with send_telegram with risk status:
- 🟢 안전
- 🟡 주의 (drawdown > 5%)
- 🔴 위험 (drawdown > 10% OR concentration > 70%)

If 🔴, propose specific action via create_github_pr or alert user.
Max 4 tool calls. No experimental work — risk only.
"""

SYSTEM_PROMPT_PORTFOLIO = """You are a quant PORTFOLIO specialist.

Focus: capital allocation across strategies/markets.
- Compare D / D_INV / MR strategy performance
- Compare symbol performance (which to boost/cut)
- Suggest rebalancing (e.g., "shift 20% from D to MR")
- Track weekly performance trends

Always end with send_telegram allocation recommendation.
Max 5 tool calls. Focus on macro patterns, not individual trades.
"""


def run_analysis(user_prompt: str | None = None,
                 mode: str = "default") -> bool:
    """단일 분석 사이클 실행. mode = default/research/risk/portfolio."""
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

    # v6.51: 모드별 시스템 프롬프트 선택
    system_text = {
        "research": SYSTEM_PROMPT_RESEARCH,
        "risk": SYSTEM_PROMPT_RISK,
        "portfolio": SYSTEM_PROMPT_PORTFOLIO,
    }.get(mode, SYSTEM_PROMPT)

    messages: list = [{"role": "user", "content": user_prompt}]
    model = os.environ.get("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")
    max_iters = 6  # v6.49: 10 → 6 (timeout 안전)
    max_wallclock = 180.0  # v6.49: 3분 한도
    start_ts = time.time()
    total_input = 0
    total_output = 0
    telegram_sent = False
    tools_used = []
    last_text = ""

    for iteration in range(max_iters):
        # v6.49: wallclock 한도 체크
        if time.time() - start_ts > max_wallclock:
            print(f"[claude_agent] wallclock timeout at iter {iteration}", flush=True)
            tg.send_force(
                f"⏱️ Claude Agent timeout ({max_wallclock:.0f}s)\n"
                f"도구 사용: {tools_used}\n"
                f"중단 — 비용 누수 방지"
            )
            return False
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": system_text,
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
