"""토스증권 매매 어댑터 — 멀티에셋 리밸런스가 쓰는 최소 인터페이스.

미국 주식만 대상. 토스는 소수점 매매를 지원하므로:
  - 매수: 금액(orderAmount, USD) 시장가 → 정확히 그 달러만큼 매수 (온주 반올림 없음)
  - 매도: 수량(quantity, 소수점 6자리) 시장가
  - 둘 다 미국 '정규장' 시간에만 접수 가능 (그 외 422)

  from toss_trader import get_us_holdings, get_buying_power_usd, buy_usd, sell_qty
"""
from __future__ import annotations

from toss_auth import request, TossError

_acct = {"seq": None}


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def account_seq() -> int:
    """첫 종합매매(BROKERAGE) 계좌의 accountSeq. 모든 계좌 API 헤더에 사용. 캐시."""
    if _acct["seq"] is not None:
        return _acct["seq"]
    accts = request("GET", "/api/v1/accounts").get("result", []) or []
    if not accts:
        raise TossError(0, "no-account", "종합매매 계좌 없음")
    _acct["seq"] = accts[0]["accountSeq"]
    return _acct["seq"]


def get_us_holdings() -> dict:
    """미국 보유종목 → {SYMBOL: {symbol, name, qty, price, buy_price, eval_usd}}.

    quantity=보유수량, lastPrice=현재가, averagePurchasePrice=평단,
    marketValue.amount=평가금액(USD, 거래통화 기준)."""
    res = request("GET", "/api/v1/holdings", account_seq=account_seq()).get("result", {})
    out = {}
    for it in (res.get("items") or []):
        if it.get("marketCountry") != "US":
            continue
        sym = it["symbol"]
        out[sym] = {
            "symbol": sym,
            "name": it.get("name", sym),
            "qty": _f(it.get("quantity")),
            "price": _f(it.get("lastPrice")),
            "buy_price": _f(it.get("averagePurchasePrice")),
            "eval_usd": _f((it.get("marketValue") or {}).get("amount")),
        }
    return out


def get_holdings_overview() -> dict:
    """계좌 요약: USD 평가액·평가손익(USD·%). 알림용."""
    res = request("GET", "/api/v1/holdings", account_seq=account_seq()).get("result", {})
    mv = ((res.get("marketValue") or {}).get("amount") or {})
    pl = (res.get("profitLoss") or {})
    return {
        "market_value_usd": _f(mv.get("usd")),
        "pnl_usd": _f((pl.get("amount") or {}).get("usd")),
        "pnl_rate": _f(pl.get("rate")),
    }


def get_buying_power_usd() -> float:
    """USD 현금 매수가능금액."""
    res = request("GET", "/api/v1/buying-power", account_seq=account_seq(),
                  params={"currency": "USD"}).get("result", {})
    return _f(res.get("cashBuyingPower"))


def get_prices(symbols) -> dict:
    """{symbol: lastPrice(float)}. 최대 200개 다건."""
    if not symbols:
        return {}
    res = request("GET", "/api/v1/prices",
                  params={"symbols": ",".join(symbols)}).get("result", []) or []
    return {r["symbol"]: _f(r.get("lastPrice")) for r in res}


def buy_usd(symbol: str, usd: float, client_order_id: str | None = None) -> dict:
    """금액(USD) 시장가 매수 — orderAmount. 정규장에서만 접수됨.
    성공: {'orderId':...} 반환. 실패: TossError."""
    body = {"symbol": symbol, "side": "BUY", "orderType": "MARKET",
            "orderAmount": f"{usd:.2f}"}
    if client_order_id:
        body["clientOrderId"] = client_order_id[:36]
    return request("POST", "/api/v1/orders", account_seq=account_seq(),
                   body=body).get("result", {})


def sell_qty(symbol: str, qty: float, client_order_id: str | None = None) -> dict:
    """수량(소수점) 시장가 매도 — 정규장에서만. 성공: {'orderId':...}."""
    body = {"symbol": symbol, "side": "SELL", "orderType": "MARKET",
            "quantity": f"{qty:.6f}"}
    if client_order_id:
        body["clientOrderId"] = client_order_id[:36]
    return request("POST", "/api/v1/orders", account_seq=account_seq(),
                   body=body).get("result", {})


def sellable_qty(symbol: str) -> float:
    res = request("GET", "/api/v1/sellable-quantity", account_seq=account_seq(),
                  params={"symbol": symbol}).get("result", {})
    return _f(res.get("sellableQuantity"))
