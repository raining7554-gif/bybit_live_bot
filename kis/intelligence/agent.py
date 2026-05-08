"""Gemini 기반 분석 에이전트 (bot-agnostic).

기능:
  analyze_trade_async   — 거래 종료시 사후분석 (3줄 + lesson 추출 + DB 저장)
  detect_regime_async   — 시장 레짐 분류 (DB 저장)
  weekly_review_async   — 주간 회고 (지난 7일 거래/레짐/lesson 통합)
  propose_async         — 4주 데이터 기반 파라미터 변경 제안

모든 호출은 best-effort (백그라운드 스레드, 매매 루프 블로킹 없음).
실패시 조용히 스킵 (또는 verbose 모드에서 텔레그램 에러 보고).
"""
from __future__ import annotations
import json
import os
import threading
import time
from typing import Callable, Optional

import requests

from . import journal


_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ── 환경변수 ────────────────────────────────────────────────────

def _enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY")) and \
        os.environ.get("AI_ENABLED", "false").lower() == "true"


def _api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


def _model() -> str:
    return os.environ.get("AI_MODEL", "gemini-2.0-flash")


# ── Gemini REST 호출 ─────────────────────────────────────────────

# v6.14: 일일 quota 추적 (429 후 당일 추가 호출 차단)
import time as _t
_quota_state: dict = {"date": "", "calls": 0, "exhausted": False}


def _today_key() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _quota_check_and_increment() -> tuple[bool, Optional[str]]:
    """호출 전 quota 체크. (allowed, error_msg)."""
    today = _today_key()
    if _quota_state["date"] != today:
        # 새로운 날 — 리셋
        _quota_state["date"] = today
        _quota_state["calls"] = 0
        _quota_state["exhausted"] = False
    if _quota_state["exhausted"]:
        return False, "오늘 Gemini 무료 quota 소진 — 내일 자정 (UTC) 리셋"
    _quota_state["calls"] += 1
    return True, None


def _quota_mark_exhausted():
    """429 받으면 호출 — 당일 추가 호출 차단."""
    _quota_state["exhausted"] = True
    print(f"[AI quota] 오늘 소진됨 (호출 {_quota_state['calls']}회 후 429)", flush=True)


def _call_gemini(prompt: str, *, want_json: bool = False,
                 timeout: int = 30) -> tuple[Optional[str], Optional[str]]:
    """단일 호출. (텍스트, 에러메시지) 튜플. 성공시 에러는 None."""
    if not _enabled():
        return None, "AI disabled"
    # v6.14: quota 체크
    allowed, qerr = _quota_check_and_increment()
    if not allowed:
        return None, qerr
    url = f"{_API_BASE}/{_model()}:generateContent?key={_api_key()}"
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    try:
        r = requests.post(url, json=body, timeout=timeout)
        if r.status_code == 429:
            _quota_mark_exhausted()
            return None, "오늘 Gemini quota 소진 (429) — 내일 자정 UTC 리셋"
        if r.status_code != 200:
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            print(f"[AI {err}]", flush=True)
            return None, err
        data = r.json()
        cands = data.get("candidates", [])
        if not cands:
            err = f"no candidates: {str(data)[:200]}"
            print(f"[AI {err}]", flush=True)
            return None, err
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return None, "empty text"
        return text, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[AI exc] {err}", flush=True)
        return None, err


def _extract_json(text: str) -> Optional[dict]:
    """JSON 파싱 — 코드펜스나 prose 둘러싸여 있어도 추출 시도."""
    text = text.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


# ── 사후분석 (개별 거래) ──────────────────────────────────────────

def _build_postmortem_prompt(trade: dict, snapshot: dict, lessons: list[str]) -> str:
    side_kr = "롱" if trade.get("side") in ("Buy", "long") else (
        "매수" if trade.get("side") == "buy" else (
            "매도" if trade.get("side") == "sell" else "숏"))
    pnl = trade.get("pnl", 0)
    pnl_pct = trade.get("pnl_pct", 0) * 100 if trade.get("pnl_pct") else 0
    outcome = "수익" if pnl >= 0 else "손실"
    reason = trade.get("reason", "?")
    strategy = trade.get("strategy", "?")
    tier = trade.get("tier") or "-"
    score = trade.get("score") or 0
    lev = trade.get("leverage", 1.0)
    symbol = trade.get("symbol", "?")

    lessons_block = ""
    if lessons:
        items = "\n".join(f"- {l}" for l in lessons[:5])
        lessons_block = f"\n\n과거 도출된 교훈 (top 5, 같은 실수 반복 방지용):\n{items}"

    return (
        "당신은 암호화폐/주식 트레이딩 분석가입니다. 방금 종료된 거래를 분석하세요.\n"
        "응답은 한국어로 정확히 3줄, 각 줄 50자 이내:\n"
        "1줄: 결과의 핵심 원인 (시장 상황 + 진입 타이밍 기반)\n"
        "2줄: 다음에 적용할 구체적 교훈 1가지 (40자 이내, 행동 지침 형태)\n"
        "3줄: 현재 전략 유지/수정 제안 (한 단어 + 짧은 이유)\n"
        "─────────\n"
        f"종목: {symbol}\n"
        f"거래: {strategy} {side_kr} {lev:.1f}x (tier={tier}, score={score:.0f})\n"
        f"진입가 {trade.get('entry_price', 0)} → 청산가 {trade.get('exit_price', 0)}\n"
        f"결과: {outcome} {pnl:+.2f} ({pnl_pct:+.2f}%) | 청산사유: {reason}\n"
        f"진입시 시장상태: {json.dumps(snapshot, ensure_ascii=False)[:600]}"
        + lessons_block
    )


def _extract_lesson(postmortem_text: str) -> Optional[str]:
    """3줄 사후분석에서 2번째 줄(교훈)을 추출."""
    lines = [ln.strip() for ln in postmortem_text.splitlines() if ln.strip()]
    if len(lines) >= 2:
        # 일부 응답이 "1줄:", "2줄:" 같은 라벨 붙이는 경우 제거
        line = lines[1]
        for prefix in ("2줄:", "2.", "2)", "2 :", "교훈:", "교훈 :"):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
        return line[:120]
    return None


def _postmortem_worker(bot_id: str, trade: dict, snapshot: dict,
                       trade_id: Optional[int],
                       send_telegram: Optional[Callable[[str], None]]):
    lessons = [l["lesson"] for l in journal.recent_lessons(bot_id=bot_id, limit=5)
               if l.get("lesson")]
    text, err = _call_gemini(_build_postmortem_prompt(trade, snapshot, lessons))
    if not text:
        print(f"[AI postmortem skipped] {err}", flush=True)
        return

    lesson = _extract_lesson(text)
    journal.log_analysis(
        bot_id=bot_id, kind="postmortem", content=text,
        trade_id=trade_id, lesson=lesson,
    )

    if send_telegram:
        pnl = trade.get("pnl", 0)
        icon = "🧠✅" if pnl >= 0 else "🧠❌"
        try:
            send_telegram(f"{icon} AI 분석\n{text}")
        except Exception as e:
            print(f"[AI postmortem TG err] {e}", flush=True)


def analyze_trade_async(*, bot_id: str, trade: dict,
                        snapshot: Optional[dict] = None,
                        trade_id: Optional[int] = None,
                        send_telegram: Optional[Callable[[str], None]] = None):
    """거래 종료 직후 호출. 백그라운드에서 분석 + DB 저장 + (옵션) 텔레그램."""
    if not _enabled():
        return
    threading.Thread(
        target=_postmortem_worker,
        args=(bot_id, trade, snapshot or {}, trade_id, send_telegram),
        daemon=True, name="ai-postmortem",
    ).start()


# ── 시장 레짐 ─────────────────────────────────────────────────────

def _build_regime_prompt(asset: str, snapshot: dict) -> str:
    return (
        f"당신은 시장 분석가입니다. 현재 {asset} 시장 레짐을 판단하세요.\n"
        "JSON으로만 응답 (다른 텍스트 없이):\n"
        '{\n'
        '  "regime": "trending_up" | "trending_down" | "chop" | "high_vol" | "low_vol",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "summary_kr": "한국어 1줄 요약 (50자 이내)",\n'
        '  "suggested": "trend" | "mr" | "stand_aside",\n'
        '  "reason_kr": "한국어 1줄 근거 (50자 이내)"\n'
        '}\n'
        "─────────\n"
        f"시장 데이터: {json.dumps(snapshot, ensure_ascii=False)[:800]}"
    )


def _regime_worker(bot_id: str, asset: str, snapshot: dict,
                   send_telegram: Optional[Callable[[str], None]],
                   verbose_errors: bool):
    text, err = _call_gemini(_build_regime_prompt(asset, snapshot), want_json=True)
    if not text:
        if verbose_errors and send_telegram:
            try:
                send_telegram(f"⚠️ AI 호출 실패\n{err}")
            except Exception:
                pass
        return
    parsed = _extract_json(text)
    if parsed is None:
        if verbose_errors and send_telegram:
            try:
                send_telegram(f"⚠️ AI 응답 파싱 실패\n{text[:300]}")
            except Exception:
                pass
        return

    journal.log_regime(
        bot_id=bot_id, asset=asset,
        regime=parsed.get("regime", "?"),
        confidence=float(parsed.get("confidence", 0)),
        summary=parsed.get("summary_kr", ""),
        suggested=parsed.get("suggested", ""),
    )

    if send_telegram:
        try:
            send_telegram(
                f"🧠 {asset} 레짐: {parsed.get('regime', '?')}"
                f" (확신 {float(parsed.get('confidence', 0))*100:.0f}%)\n"
                f"{parsed.get('summary_kr', '')}\n"
                f"근거: {parsed.get('reason_kr', '')}\n"
                f"제안: {parsed.get('suggested', '?')}"
            )
        except Exception as e:
            print(f"[AI regime TG err] {e}", flush=True)


def detect_regime_async(*, bot_id: str, asset: str, snapshot: dict,
                        send_telegram: Optional[Callable[[str], None]] = None,
                        verbose_errors: bool = False):
    if not _enabled():
        return
    threading.Thread(
        target=_regime_worker,
        args=(bot_id, asset, snapshot, send_telegram, verbose_errors),
        daemon=True, name="ai-regime",
    ).start()


# ── 주간 회고 ─────────────────────────────────────────────────────

def _build_review_prompt(stats: dict, lessons: list[str], regimes: list[dict]) -> str:
    n = stats.get("n", 0)
    wr = stats.get("win_rate", 0) * 100
    pnl = stats.get("total_pnl", 0)

    by_bot_lines = []
    for b, s in stats.get("by_bot", {}).items():
        bn = s["n"]
        bwr = (s["wins"] / bn * 100) if bn else 0
        by_bot_lines.append(f"  - {b}: {bn}건, 승률 {bwr:.0f}%, PnL {s['pnl']:+.2f}")
    by_strategy_lines = []
    for st, s in stats.get("by_strategy", {}).items():
        bn = s["n"]
        bwr = (s["wins"] / bn * 100) if bn else 0
        by_strategy_lines.append(f"  - {st}: {bn}건, 승률 {bwr:.0f}%, PnL {s['pnl']:+.2f}")
    by_symbol_lines = []
    # PnL 내림차순으로 — 가장 잘된 심볼 / 못한 심볼 명확히
    sorted_syms = sorted(stats.get("by_symbol", {}).items(), key=lambda x: -x[1]["pnl"])
    for sy, s in sorted_syms:
        bn = s["n"]
        bwr = (s["wins"] / bn * 100) if bn else 0
        by_symbol_lines.append(f"  - {sy}: {bn}건, 승률 {bwr:.0f}%, PnL {s['pnl']:+.2f}")
    by_tier_lines = []
    for ti, s in stats.get("by_tier", {}).items():
        bn = s["n"]
        bwr = (s["wins"] / bn * 100) if bn else 0
        by_tier_lines.append(f"  - {ti}: {bn}건, 승률 {bwr:.0f}%, PnL {s['pnl']:+.2f}")
    by_reason_str = ", ".join(f"{k}={v}" for k, v in
                              sorted(stats.get("by_reason", {}).items(),
                                     key=lambda x: -x[1])[:6])

    lessons_block = ""
    if lessons:
        items = "\n".join(f"  - {l}" for l in lessons[:8])
        lessons_block = f"\n지난주 도출된 교훈:\n{items}"

    regime_block = ""
    if regimes:
        regime_counts: dict[str, int] = {}
        for r in regimes:
            regime_counts[r["regime"]] = regime_counts.get(r["regime"], 0) + 1
        rs = ", ".join(f"{k}={v}회" for k, v in regime_counts.items())
        regime_block = f"\n지난주 시장 레짐 분포: {rs}"

    return (
        "당신은 트레이딩 코치입니다. 지난 7일 거래 데이터를 분석하세요.\n"
        "응답은 한국어로 정확히 6줄, 각 줄 60자 이내:\n"
        "1줄: 지난주 핵심 패턴 1개 (데이터 기반)\n"
        "2줄: 가장 잘된 심볼/전략 + 이유\n"
        "3줄: 가장 부진한 심볼/전략 + 이유 (제거 고려?)\n"
        "4줄: tier별 효율 — 어느 tier 가 가장 수익적이었나\n"
        "5줄: 다음주 주의점 1가지\n"
        "6줄: 봇별 성과 한 줄 평\n"
        "─────────\n"
        f"전체: {n}건, 승률 {wr:.1f}%, 총 PnL {pnl:+.2f}\n"
        f"심볼별 (PnL 순):\n" + ("\n".join(by_symbol_lines) or "  (없음)") + "\n"
        f"tier별:\n" + ("\n".join(by_tier_lines) or "  (없음)") + "\n"
        f"전략별:\n" + ("\n".join(by_strategy_lines) or "  (없음)") + "\n"
        f"봇별:\n" + ("\n".join(by_bot_lines) or "  (없음)") + "\n"
        f"청산사유 분포: {by_reason_str}"
        + lessons_block
        + regime_block
    )


def _review_worker(bot_id: Optional[str],
                   send_telegram: Optional[Callable[[str], None]],
                   verbose_errors: bool):
    stats = journal.trade_stats(bot_id=bot_id, since_seconds=7 * 86400)
    if stats.get("n", 0) < 5:
        msg = (f"📊 주간 회고 — 데이터 부족 (지난 7일 {stats.get('n', 0)}건)\n"
               f"최소 5건 이상 누적되면 분석 시작합니다.")
        if send_telegram:
            try:
                send_telegram(msg)
            except Exception:
                pass
        return

    lessons = [l["lesson"] for l in journal.recent_lessons(bot_id=bot_id, limit=10)
               if l.get("lesson")]
    regimes = journal.recent_regimes(bot_id=bot_id, since_seconds=7 * 86400)

    text, err = _call_gemini(_build_review_prompt(stats, lessons, regimes))
    if not text:
        if verbose_errors and send_telegram:
            try:
                send_telegram(f"⚠️ AI 회고 실패\n{err}")
            except Exception:
                pass
        return

    journal.log_analysis(
        bot_id=bot_id or "all", kind="review", content=text,
    )

    scope = bot_id if bot_id else "전체 봇"
    n = stats["n"]
    wr = stats["win_rate"] * 100
    pnl = stats["total_pnl"]
    if send_telegram:
        try:
            send_telegram(
                f"📊 <b>주간 회고</b> ({scope})\n"
                f"{n}건, 승률 {wr:.0f}%, PnL {pnl:+.2f}\n"
                f"─────────\n{text}"
            )
        except Exception as e:
            print(f"[AI review TG err] {e}", flush=True)


def weekly_review_async(*, bot_id: Optional[str] = None,
                        send_telegram: Optional[Callable[[str], None]] = None,
                        verbose_errors: bool = False):
    """지난 7일 회고. bot_id None이면 전체 봇 통합."""
    if not _enabled():
        return
    threading.Thread(
        target=_review_worker,
        args=(bot_id, send_telegram, verbose_errors),
        daemon=True, name="ai-review",
    ).start()


# ── 파라미터 제안 ─────────────────────────────────────────────────

def _build_proposal_prompt(stats: dict, current_params: dict, lessons: list[str]) -> str:
    items = "\n".join(f"  {k}: {v}" for k, v in current_params.items())

    by_strategy_lines = []
    for st, s in stats.get("by_strategy", {}).items():
        bn = s["n"]
        bwr = (s["wins"] / bn * 100) if bn else 0
        by_strategy_lines.append(f"  - {st}: {bn}건, 승률 {bwr:.0f}%, PnL {s['pnl']:+.2f}")

    lessons_block = ""
    if lessons:
        items_l = "\n".join(f"  - {l}" for l in lessons[:8])
        lessons_block = f"\n누적 교훈:\n{items_l}"

    return (
        "당신은 시스템 트레이딩 분석가입니다. 지난 4주 거래 데이터를 보고 봇 파라미터\n"
        "변경을 제안하세요. 데이터 기반 + 보수적 (한 번에 큰 변경 X).\n"
        "JSON으로만 응답 (다른 텍스트 없이):\n"
        '{\n'
        '  "should_propose": true | false,\n'
        '  "summary_kr": "1줄 요약 (왜 변경/유지인지)",\n'
        '  "proposals": [\n'
        '    {\n'
        '      "param": "PARAM_NAME",\n'
        '      "current": "현재값",\n'
        '      "suggested": "제안값",\n'
        '      "reason_kr": "근거 1줄 (50자 이내)",\n'
        '      "confidence": 0.0~1.0\n'
        '    }\n'
        '  ]\n'
        '}\n'
        "변경 권장 안되면 should_propose=false, proposals=[].\n"
        "─────────\n"
        f"현재 파라미터:\n{items}\n\n"
        f"지난 4주: {stats.get('n', 0)}건, 승률 {stats.get('win_rate', 0)*100:.1f}%, "
        f"총 PnL {stats.get('total_pnl', 0):+.2f}\n"
        f"전략별:\n" + "\n".join(by_strategy_lines)
        + lessons_block
    )


def _proposal_worker(bot_id: str, current_params: dict,
                     send_telegram: Optional[Callable[[str], None]],
                     verbose_errors: bool):
    stats = journal.trade_stats(bot_id=bot_id, since_seconds=28 * 86400)
    if stats.get("n", 0) < 20:
        msg = (f"⚙️ 파라미터 제안 — 데이터 부족\n"
               f"지난 4주 {stats.get('n', 0)}건 (최소 20건 필요)")
        if send_telegram:
            try:
                send_telegram(msg)
            except Exception:
                pass
        return

    lessons = [l["lesson"] for l in journal.recent_lessons(bot_id=bot_id, limit=15)
               if l.get("lesson")]

    text, err = _call_gemini(_build_proposal_prompt(stats, current_params, lessons),
                             want_json=True)
    if not text:
        if verbose_errors and send_telegram:
            try:
                send_telegram(f"⚠️ AI 제안 실패\n{err}")
            except Exception:
                pass
        return

    parsed = _extract_json(text)
    if parsed is None or not parsed.get("should_propose"):
        msg = "⚙️ AI 파라미터 검토 — 변경 권장 사항 없음"
        if parsed and parsed.get("summary_kr"):
            msg += f"\n사유: {parsed['summary_kr']}"
        journal.log_analysis(bot_id=bot_id, kind="proposal", content=text)
        if send_telegram:
            try:
                send_telegram(msg)
            except Exception:
                pass
        return

    proposals = parsed.get("proposals", [])
    journal.log_analysis(bot_id=bot_id, kind="proposal", content=text)

    msg_lines = [f"⚙️ <b>AI 파라미터 제안</b> ({bot_id})"]
    if parsed.get("summary_kr"):
        msg_lines.append(parsed["summary_kr"])
    msg_lines.append("─────────")
    for p in proposals[:5]:
        param = p.get("param", "?")
        cur = str(p.get("current", "?"))
        sug = str(p.get("suggested", "?"))
        reason = p.get("reason_kr", "")
        conf = float(p.get("confidence", 0))
        # DB에 pending 상태로 저장
        journal.log_proposal(
            bot_id=bot_id, param=param,
            current_value=cur, suggested_value=sug,
            reason=reason, confidence=conf,
        )
        msg_lines.append(f"• {param}: {cur} → {sug} ({conf*100:.0f}%)")
        msg_lines.append(f"  {reason}")
    msg_lines.append("─────────")
    msg_lines.append("⚠️ 자동 적용 ❌. 본인이 검토 후 수동 적용.")

    if send_telegram:
        try:
            send_telegram("\n".join(msg_lines))
        except Exception as e:
            print(f"[AI proposal TG err] {e}", flush=True)


def propose_async(*, bot_id: str, current_params: dict,
                  send_telegram: Optional[Callable[[str], None]] = None,
                  verbose_errors: bool = False):
    """4주 데이터 기반 파라미터 제안. 절대 자동 적용하지 않음 — 사람 승인 필요."""
    if not _enabled():
        return
    threading.Thread(
        target=_proposal_worker,
        args=(bot_id, current_params, send_telegram, verbose_errors),
        daemon=True, name="ai-proposal",
    ).start()


# ── 패턴 매칭 (Tier 1 자동 학습) ──────────────────────────────

def _feature_distance(a: dict, b: dict) -> float:
    """두 시장 스냅샷 간 거리 (작을수록 비슷). 정규화된 차이의 L2."""
    if not a or not b:
        return float("inf")
    # 비교할 핵심 indicator (있는 것만)
    keys = ["adx", "rsi", "bb_width", "vol_ratio"]
    diffs = []
    for tf in ("15m", "1h", "4h"):
        sa = a.get(tf, {}) if isinstance(a.get(tf), dict) else {}
        sb = b.get(tf, {}) if isinstance(b.get(tf), dict) else {}
        for k in keys:
            va = sa.get(k)
            vb = sb.get(k)
            if va is None or vb is None:
                continue
            try:
                # k 별 정규화 (대략 0~1)
                if k == "adx":
                    d = (float(va) - float(vb)) / 50.0
                elif k == "rsi":
                    d = (float(va) - float(vb)) / 100.0
                elif k == "bb_width":
                    d = (float(va) - float(vb)) / 0.05
                elif k == "vol_ratio":
                    d = (float(va) - float(vb)) / 2.0
                else:
                    d = float(va) - float(vb)
                diffs.append(d * d)
            except (TypeError, ValueError):
                continue
    if not diffs:
        return float("inf")
    return sum(diffs) ** 0.5


def find_similar_trades(*, bot_id: str, symbol: str,
                        current_snapshot: dict,
                        k: int = 5,
                        days: int = 90) -> list[dict]:
    """현재 시장 스냅샷과 비슷한 과거 거래 K건 반환 (가장 비슷한 순)."""
    trades = journal.recent_trades(bot_id=bot_id,
                                   since_seconds=days * 86400,
                                   limit=300)
    if not trades:
        return []
    # 같은 심볼 우선
    same_sym = [t for t in trades if t.get("symbol") == symbol]
    pool = same_sym if len(same_sym) >= k else trades

    scored = []
    for t in pool:
        snap_str = t.get("market_snapshot")
        if not snap_str:
            continue
        try:
            snap = json.loads(snap_str)
        except Exception:
            continue
        d = _feature_distance(current_snapshot, snap)
        if d == float("inf"):
            continue
        scored.append((d, t))
    scored.sort(key=lambda x: x[0])
    return [t for _, t in scored[:k]]


def _build_pattern_prompt(symbol: str, direction: str,
                          current_snap: dict,
                          similar_trades: list[dict]) -> str:
    cur = json.dumps(current_snap, ensure_ascii=False)[:500]
    lines = [
        f"당신은 트레이딩 패턴 분석가입니다. 현재 셋업과 비슷한 과거 거래들을 비교해서",
        f"이번 진입 추천 여부를 JSON 으로 답하세요.",
        f"",
        f"현재: {symbol} {direction} 진입 검토 중",
        f"현재 시장: {cur}",
        f"",
        f"과거 비슷한 거래 {len(similar_trades)}건:",
    ]
    for i, t in enumerate(similar_trades, 1):
        outcome = "이김" if t.get("pnl", 0) >= 0 else "짐"
        lines.append(
            f"  {i}. {t.get('symbol')} {t.get('side')} score={t.get('score', 0):.0f} "
            f"→ {outcome} ({t.get('pnl', 0):+.2f}, {t.get('reason', '?')})"
        )
    lines.extend([
        "",
        "JSON 응답 형식 (다른 텍스트 금지):",
        '{"recommend": "go" | "small" | "skip",',
        ' "confidence": 0.0~1.0,',
        ' "reason_kr": "1줄 근거 (40자 이내)"}',
        "",
        "기준:",
        "- 과거 4건 이상 이김 → go",
        "- 비슷한 결과 (3:2 or 2:3) → small",
        "- 4건 이상 짐 → skip",
    ])
    return "\n".join(lines)


def pattern_check(bot_id: str, symbol: str, direction: str,
                  current_snapshot: dict) -> Optional[dict]:
    """v15 Tier 1: 과거 비슷한 거래 비교 + AI 의견.

    Returns:
        {"recommend": "go"|"small"|"skip", "confidence": 0~1, "reason_kr": "..."}
        또는 None (데이터 부족 / AI 비활성)

    매 진입시 호출. 시간 비용 = AI 1회 호출 (~3초). 신호 평가 단계에 적합.
    동기 호출 (진입 결정에 영향) — 백그라운드 X.
    """
    if not _enabled():
        return None
    similar = find_similar_trades(
        bot_id=bot_id, symbol=symbol,
        current_snapshot=current_snapshot, k=5,
    )
    if len(similar) < 3:
        return None  # 데이터 부족 (3건 미만이면 의미 없음)

    text, err = _call_gemini(
        _build_pattern_prompt(symbol, direction, current_snapshot, similar),
        want_json=True, timeout=15,
    )
    if not text:
        return None
    parsed = _extract_json(text)
    if parsed is None:
        return None
    rec = parsed.get("recommend", "small")
    if rec not in ("go", "small", "skip"):
        rec = "small"
    parsed["recommend"] = rec
    parsed["similar_count"] = len(similar)
    parsed["similar_wins"] = sum(1 for t in similar if t.get("pnl", 0) >= 0)
    return parsed


def pattern_to_multiplier(pattern_result: Optional[dict]) -> float:
    """패턴 매칭 결과 → 점수 multiplier.

    go = 1.0 (페널티 없음)
    small = 0.85 (사이즈 약간 줄임)
    skip = 0.55 (강한 페널티 — 점수 < 55 가 되어 진입 차단되도록)
    None (데이터 부족) = 1.0
    """
    if pattern_result is None:
        return 1.0
    rec = pattern_result.get("recommend", "small")
    conf = float(pattern_result.get("confidence", 0.5))
    if rec == "go":
        return 1.0
    elif rec == "skip":
        # 확신 높을수록 강한 페널티
        return 0.55 - (conf - 0.5) * 0.20  # 0.45 ~ 0.55
    else:  # small
        return 0.85 - (conf - 0.5) * 0.10  # 0.80 ~ 0.85
