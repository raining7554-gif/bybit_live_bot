"""US 레버리지 체제 스위치 전략 (v1.1 — 분할 포트 지원)

단일 모드:
  - BULL 신호 → 1개 ETF 풀매수 (TQQQ 등)
  - BEAR → 현금

분할 모드 (4-way 등):
  - 여러 ETF에 비중 배분 (각자 독립 체제 스위치)
  - 예: SOXL 25% + TQQQ 25% + TECL 25% + FAS 25%
  - 각 슬리브는 자기 벤치마크(SPY/QQQ) 기준 독립 판정
  - 한 ETF BULL / 다른 ETF BEAR 동시 가능

백테스트 (2015-2026, $700):
  - SOXL/Cash 단일:       CAGR +41%, MDD -71%  → $34,432
  - TQQQ/Cash 단일:       CAGR +37%, MDD -42%  → $23,885
  - SOXL+TQQQ+TECL+FAS:   CAGR +38%, MDD -44%  → $25,029  ⭐
"""
from __future__ import annotations
from datetime import datetime, date
import pytz
import kis_auth as api


# ═══════════════════════════════════════════════════════
# 벤치/레버리지 ETF 일봉 조회 (KIS API 해외)
# ═══════════════════════════════════════════════════════
def get_overseas_daily(ticker: str, exchange: str = "NAS", count: int = 220) -> list:
    """해외 일봉 조회 (KIS API)"""
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/dailyprice",
            "HHDFS76240000",
            {
                "AUTH": "", "EXCD": exchange, "SYMB": ticker,
                "GUBN": "0", "BYMD": "", "MODP": "1",
            },
        )
        if data.get("rt_cd") != "0":
            return []
        outputs = data.get("output2", [])
        # 최신순 정렬된 상태로 반환
        result = []
        for o in outputs[:count]:
            try:
                result.append({
                    "date": o.get("xymd", ""),
                    "close": float(o.get("clos", 0)),
                    "high": float(o.get("high", 0)),
                    "low": float(o.get("low", 0)),
                    "volume": int(float(o.get("tvol", 0))),
                })
            except (ValueError, TypeError):
                continue
        return result
    except Exception as e:
        print(f"[LEV] {ticker} 일봉 조회 오류: {e}")
        return []


def _sma(values: list[float], n: int) -> float:
    if len(values) < n:
        return 0.0
    return sum(values[:n]) / n


# ═══════════════════════════════════════════════════════
# 체제 판정
# ═══════════════════════════════════════════════════════
def get_regime(benchmark: str = "SPY", signal_ma: int = 200, aux_ma: int = 50) -> dict:
    """체제 판정: BULL / BEAR / UNKNOWN
    Returns: {"regime": str, "close": float, "ma_s": float, "ma_a": float}
    """
    candles = get_overseas_daily(benchmark, "NAS" if benchmark == "QQQ" else "AMS", count=220)
    if len(candles) < signal_ma + 5:
        # AMS/NAS 실패 시 다른 거래소 시도
        candles = get_overseas_daily(benchmark, "NAS", count=220)
    if len(candles) < signal_ma + 5:
        print(f"[LEV] {benchmark} 데이터 부족 ({len(candles)}일) → UNKNOWN")
        return {"regime": "UNKNOWN", "close": 0, "ma_s": 0, "ma_a": 0}

    closes = [c["close"] for c in candles]
    close = closes[0]
    ma_s = _sma(closes, signal_ma)
    ma_a = _sma(closes, aux_ma)

    if close > ma_s and ma_a > ma_s:
        regime = "BULL"
    elif close < ma_s and ma_a < ma_s:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"  # 경계 — 현재 포지션 유지

    return {"regime": regime, "close": close, "ma_s": ma_s, "ma_a": ma_a}


# ═══════════════════════════════════════════════════════
# 체제 스위치 주문 로직
# ═══════════════════════════════════════════════════════
def decide_target_ticker(
    regime: str,
    bull_ticker: str,
    bear_ticker: str | None,
    current_ticker: str | None,
) -> str | None:
    """
    BULL → bull_ticker
    BEAR → bear_ticker (None 이면 현금)
    NEUTRAL → 현재 유지
    """
    if regime == "BULL":
        return bull_ticker
    elif regime == "BEAR":
        return bear_ticker  # None 이면 현금
    elif regime == "NEUTRAL":
        return current_ticker
    else:  # UNKNOWN
        return current_ticker


def execute_regime_switch(
    target_ticker: str | None,
    current_position: dict | None,
    account_usd: float,
) -> dict:
    """
    target_ticker 로 전환.
    current_position: {"ticker": str, "qty": int, "buy_price": float} or None
    Returns: {"action": "buy"|"sell"|"switch"|"hold", "new_position": dict|None, "msg": str}
    """
    import trader_overseas
    import telegram

    curr = current_position.get("ticker") if current_position else None

    # 동일 타겟 → hold
    if curr == target_ticker:
        return {"action": "hold", "new_position": current_position, "msg": "체제 유지"}

    # 기존 청산
    sell_done = True
    if current_position:
        ok = trader_overseas.sell_overseas(
            current_position["ticker"],
            current_position.get("name", current_position["ticker"]),
            "NAS",
            current_position["qty"],
            current_position["buy_price"],
            reason="[REGIME] 체제 전환",
        )
        sell_done = ok
        if not ok:
            return {"action": "sell_fail", "new_position": current_position,
                    "msg": f"{current_position['ticker']} 매도 실패"}

    # 현금 도피 타겟 (None) 이면 종료
    if target_ticker is None:
        telegram.send(f"🛡 <b>체제=BEAR</b>\n현금 도피 완료")
        return {"action": "sell", "new_position": None, "msg": "현금 도피"}

    # 새 매수 — 풀 allocation
    res = trader_overseas.buy_overseas(
        target_ticker, target_ticker, "NAS",
        reason=f"[REGIME] 레버리지 진입",
        full_allocation_usd=account_usd,  # trader_overseas 에서 지원 필요
    )
    if res:
        return {"action": "switch", "new_position": res,
                "msg": f"{target_ticker} 풀매수 완료"}
    return {"action": "buy_fail", "new_position": None,
            "msg": f"{target_ticker} 매수 실패"}


# ═══════════════════════════════════════════════════════
# 메인 루프에서 호출하는 엔트리
# ═══════════════════════════════════════════════════════
def check_and_execute(
    config: dict,
    current_position: dict | None,
    account_usd: float,
) -> dict:
    """하루 1회 (또는 월 1회) 호출해서 체제 체크 + 주문 실행

    config:
      benchmark: "SPY" | "QQQ"
      bull_ticker: "TQQQ" | "SOXL" | "UPRO"
      bear_ticker: None | "SQQQ" | "SOXS" | "SPXS"  (None 권장)
      signal_ma: 200
      aux_ma: 50
      rebalance: "daily" | "monthly"
    """
    import telegram
    info = get_regime(
        config.get("benchmark", "SPY"),
        config.get("signal_ma", 200),
        config.get("aux_ma", 50),
    )
    regime = info["regime"]

    target = decide_target_ticker(
        regime,
        config.get("bull_ticker", "TQQQ"),
        config.get("bear_ticker"),
        current_position.get("ticker") if current_position else None,
    )

    telegram.send(
        f"📊 <b>US 레버리지 체제 체크</b>\n"
        f"{config.get('benchmark', 'SPY')} close={info['close']:.2f}\n"
        f"MA{config.get('signal_ma', 200)}={info['ma_s']:.2f} "
        f"MA{config.get('aux_ma', 50)}={info['ma_a']:.2f}\n"
        f"체제: <b>{regime}</b> → 타겟: {target or '현금'}",
        dedup_sec=3600,
    )

    result = execute_regime_switch(target, current_position, account_usd)
    return {
        "regime_info": info,
        "target": target,
        **result,
    }


# ═══════════════════════════════════════════════════════
# 분할 포트폴리오 (4-way 등) — 슬리브별 독립 체제 스위치
# ═══════════════════════════════════════════════════════
def check_and_execute_split(
    allocations: list[dict],
    current_positions: dict,
    total_account_usd: float,
    signal_ma: int = 200,
    aux_ma: int = 50,
) -> dict:
    """여러 ETF 슬리브 독립 체제 체크 + 주문 실행.

    allocations: [{"ticker": "SOXL", "benchmark": "QQQ", "weight": 0.25}, ...]
    current_positions: {ticker: {qty, buy_price, name}} — 현재 보유 ETF들
    total_account_usd: 전체 USD 잔고 평가액 (슬리브 예산 산정 기준)

    Returns: {"switches": [...], "regimes": {ticker: regime}, "actions": [...]}
    """
    import trader_overseas
    import telegram

    results = {"switches": [], "regimes": {}, "actions": [], "held": []}

    n_sleeves = len(allocations)
    if n_sleeves == 0:
        return results

    msg_lines = [f"📊 <b>US 레버리지 분할 체제 체크</b> ({n_sleeves}-way)"]

    for alloc in allocations:
        ticker = alloc["ticker"]
        bench = alloc.get("benchmark", "SPY")
        weight = alloc.get("weight", 1.0 / n_sleeves)
        sleeve_budget = total_account_usd * weight

        # 체제 판정
        info = get_regime(bench, signal_ma, aux_ma)
        regime = info["regime"]
        results["regimes"][ticker] = regime
        msg_lines.append(
            f"• {ticker} (bench={bench}): {regime}  "
            f"close={info['close']:.2f} MA{signal_ma}={info['ma_s']:.2f}"
        )

        currently_held = ticker in current_positions
        curr_pos = current_positions.get(ticker)

        # 의사결정
        if regime == "BULL" and not currently_held:
            # 진입
            try:
                res = trader_overseas.buy_overseas(
                    ticker, ticker, "NAS",
                    reason=f"[SPLIT] {ticker} BULL 진입 ({weight*100:.0f}% 슬리브)",
                    full_allocation_usd=sleeve_budget,
                )
                if res:
                    results["switches"].append({"action": "buy", "ticker": ticker, "budget": sleeve_budget})
                    current_positions[ticker] = res
                    msg_lines.append(f"  → 매수 ${sleeve_budget:.0f}")
            except Exception as e:
                print(f"[SPLIT] {ticker} 매수 오류: {e}")
                msg_lines.append(f"  → ❌ 매수 실패: {e}")

        elif regime == "BEAR" and currently_held:
            # 청산
            try:
                ok = trader_overseas.sell_overseas(
                    ticker, ticker, "NAS",
                    curr_pos["qty"], curr_pos["buy_price"],
                    reason=f"[SPLIT] {ticker} BEAR 전환",
                )
                if ok:
                    results["switches"].append({"action": "sell", "ticker": ticker})
                    current_positions.pop(ticker, None)
                    msg_lines.append(f"  → 매도 (현금 도피)")
            except Exception as e:
                print(f"[SPLIT] {ticker} 매도 오류: {e}")
                msg_lines.append(f"  → ❌ 매도 실패: {e}")

        elif regime == "NEUTRAL":
            if currently_held:
                results["held"].append(ticker)
                msg_lines.append(f"  → 유지 (NEUTRAL)")
            # 애매 — 현 상태 유지
        elif regime == "BULL" and currently_held:
            results["held"].append(ticker)
            # 이미 보유 중 — 유지

    telegram.send("\n".join(msg_lines), dedup_sec=3600)
    return results
