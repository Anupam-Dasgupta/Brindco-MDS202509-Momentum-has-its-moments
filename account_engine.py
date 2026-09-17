"""Frozen execution and settlement arithmetic for development accounts."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from math import floor, isfinite, sqrt

from tax_model import Lot


CAP_FRACTION = 0.01
IMPACT_MIN_BPS = 10.0
IMPACT_REFERENCE_PARTICIPATION = 0.001
STT_BPS = 10.0
STAMP_BUY_BPS = 1.5
EXCHANGE_BPS = 0.297
SEBI_GST_BPS = 0.130


@dataclass
class AccountState:
    account: str
    cash: float = 10_000_000.0
    lots: list[Lot] = field(default_factory=list)
    sale_receivables: list[dict] = field(default_factory=list)
    dividend_receivables: list[dict] = field(default_factory=list)
    bonus_entitlements: list[dict] = field(default_factory=list)
    rights_entitlements: list[dict] = field(default_factory=list)
    fractional_split_claims: list[dict] = field(default_factory=list)
    tax_liability: float = 0.0
    tax_paid: float = 0.0

    def owned(self, security_id: str) -> float:
        return sum(lot.quantity for lot in self.lots if lot.security_id == security_id)

    def settled(self, security_id: str) -> float:
        return sum(lot.settled_quantity for lot in self.lots if lot.security_id == security_id)

    def economic_units(self, security_id: str) -> float:
        return self.owned(security_id) + sum(
            row["quantity"] for row in self.bonus_entitlements if row["security_id"] == security_id
        )

    def free_cash(self) -> float:
        return max(0.0, self.cash - self.tax_liability)

    def nav(self, marks: dict[str, float]) -> float:
        units = {sid: self.owned(sid) for sid in {lot.security_id for lot in self.lots}}
        for item in self.bonus_entitlements:
            units[item["security_id"]] = units.get(item["security_id"], 0) + item["quantity"]
        stocks = sum(quantity * marks[sid] for sid, quantity in units.items() if quantity)
        sale_claims = sum(row["amount"] for row in self.sale_receivables)
        dividend_claims = sum(row["amount"] for row in self.dividend_receivables)
        return stocks + self.cash + sale_claims + dividend_claims - self.tax_liability


def recognise_dividend(state: AccountState, event_id: str, security_id: str,
                       amount_per_share: float, payment_date: date | None) -> None:
    amount = state.economic_units(security_id) * amount_per_share
    if amount < 0 or not isfinite(amount):
        raise ValueError("Invalid dividend entitlement")
    if amount:
        state.dividend_receivables.append({
            "event_id": event_id, "security_id": security_id, "amount": amount,
            "payment_date": payment_date, "status": "UNSPENDABLE_PENDING_PAYMENT",
        })


def recognise_bonus(state: AccountState, event_id: str, security_id: str,
                    additional_per_share: float, availability_date: date | None) -> None:
    quantity = state.economic_units(security_id) * additional_per_share
    if quantity < 0 or not isfinite(quantity):
        raise ValueError("Invalid bonus entitlement")
    if quantity:
        state.bonus_entitlements.append({
            "event_id": event_id, "security_id": security_id, "quantity": quantity,
            "availability_date": availability_date, "status": "UNAVAILABLE_FOR_DELIVERY",
            "tax_holding_start": availability_date,
        })


def rights_materiality(state: AccountState, security_id: str) -> dict[str, object]:
    quantity = state.economic_units(security_id)
    return {"status": "UNRESOLVED_HELD_RIGHTS_NAV" if quantity else "ACCOUNT_NOT_EXPOSED",
            "held_quantity": quantity}


def settle_due(state: AccountState, day: date) -> list[dict]:
    """Release evidenced obligations only; unknown dates remain unavailable."""
    released = []
    outstanding = []
    for row in state.sale_receivables:
        if row["settlement_date"] <= day:
            state.cash += row["amount"]
            released.append({"category": "SALE_SETTLEMENT", **row})
        else:
            outstanding.append(row)
    state.sale_receivables = outstanding
    outstanding = []
    for row in state.dividend_receivables:
        if row["payment_date"] is not None and row["payment_date"] <= day:
            state.cash += row["amount"]
            released.append({"category": "DIVIDEND_PAYMENT", **row})
        else:
            outstanding.append(row)
    state.dividend_receivables = outstanding
    return released


def target_shares(target_notional: float, raw_open: float) -> int:
    if not isfinite(target_notional) or target_notional < 0:
        raise ValueError("Invalid target notional")
    if not isfinite(raw_open) or raw_open <= 0:
        raise ValueError("No usable raw opening price")
    return floor(target_notional / raw_open)


def participation_cap_shares(lagged_adv: float, raw_open: float) -> int:
    if not isfinite(lagged_adv) or lagged_adv <= 0:
        return 0
    return target_shares(CAP_FRACTION * lagged_adv, raw_open)


def settlement_after(trade_date: date, settlement_business_dates: list[date]) -> date:
    """Two verified settlement business days strictly after trade date."""
    first = bisect_right(settlement_business_dates, trade_date)
    if first + 1 >= len(settlement_business_dates):
        raise ValueError("Verified T+2 settlement date is unavailable")
    return settlement_business_dates[first + 1]


def fill_terms(side: str, quantity: int, raw_open: float, lagged_adv: float) -> dict[str, float]:
    if side not in {"BUY", "SELL"} or quantity <= 0:
        raise ValueError("Invalid order side or share quantity")
    if not isfinite(raw_open) or raw_open <= 0:
        raise ValueError("No usable raw opening price")
    if not isfinite(lagged_adv) or lagged_adv <= 0:
        raise ValueError("No usable lagged ADV")
    participation = quantity * raw_open / lagged_adv
    if participation > CAP_FRACTION + 1e-12:
        raise ValueError("Fill exceeds the 1% lagged ADV cap")
    impact_bps = IMPACT_MIN_BPS * max(1.0, sqrt(participation / IMPACT_REFERENCE_PARTICIPATION))
    sign = 1 if side == "BUY" else -1
    fill_price = raw_open * (1 + sign * impact_bps / 10_000)
    consideration = quantity * fill_price
    stt = consideration * STT_BPS / 10_000
    stamp = consideration * STAMP_BUY_BPS / 10_000 if side == "BUY" else 0.0
    exchange = consideration * EXCHANGE_BPS / 10_000
    sebi_gst = consideration * SEBI_GST_BPS / 10_000
    fees = stt + stamp + exchange + sebi_gst
    return {
        "quantity": quantity,
        "raw_open": raw_open,
        "lagged_adv": lagged_adv,
        "participation": participation,
        "impact_bps": impact_bps,
        "fill_price": fill_price,
        "consideration": consideration,
        "stt": stt,
        "stamp": stamp,
        "exchange": exchange,
        "sebi_gst": sebi_gst,
        "fees": fees,
        "deductible_fees": stamp + exchange + sebi_gst,
        "impact_rupees": quantity * abs(fill_price - raw_open),
        "cash_flow": -(consideration + fees) if side == "BUY" else consideration - fees,
    }


def affordable_buy_quantity(maximum_shares: int, free_settled_cash: float,
                            raw_open: float, lagged_adv: float) -> int:
    """Largest affordable whole-share fill, including impact and all fees."""
    if maximum_shares < 0 or not isfinite(free_settled_cash) or free_settled_cash < 0:
        raise ValueError("Invalid desired shares or free cash")
    high = min(maximum_shares, participation_cap_shares(lagged_adv, raw_open))
    low = 0
    while low < high:
        middle = (low + high + 1) // 2
        cost = -fill_terms("BUY", middle, raw_open, lagged_adv)["cash_flow"]
        if cost <= free_settled_cash:
            low = middle
        else:
            high = middle - 1
    return low
