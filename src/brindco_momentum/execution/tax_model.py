"""Declared assignment capital-gains tax for one executable account.

The rates and loss-use order are frozen project conventions, not a historical
reconstruction of changing Indian tax law. Calculations are pure so a daily
provision can be recomputed from immutable gains and opening loss pools.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


ST_RATE = 0.20
LT_RATE = 0.125
LT_EXEMPTION = 125_000.0


@dataclass
class Lot:
    lot_id: str
    security_id: str
    acquired: date
    quantity: float
    basis: float
    basis_provenance: str
    settled_quantity: float = 0


def fiscal_year(day: date) -> int:
    """Return the start calendar year of India's April–March FY."""
    return day.year if day.month >= 4 else day.year - 1


def holding_term(acquired: date, sold: date) -> str:
    if sold < acquired:
        raise ValueError("Sale precedes acquisition")
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:
        # A 29 February acquisition reaches its first calendar anniversary on
        # 28 February in the following non-leap year under the declared model.
        anniversary = acquired.replace(year=acquired.year + 1, day=28)
    return "ST" if sold <= anniversary else "LT"


def consume_fifo(
    lots: list[Lot], security_id: str, quantity: int, sold: date,
    taxable_sale_proceeds: float, sale_id: str,
) -> list[dict[str, object]]:
    """Consume settled shares and allocate proceeds/basis pro rata by share."""
    if quantity <= 0 or taxable_sale_proceeds < 0:
        raise ValueError("Invalid sale quantity or taxable proceeds")
    available = sum(lot.settled_quantity for lot in lots if lot.security_id == security_id)
    if quantity > available:
        raise ValueError("Cannot sell more settled shares than available")
    realised = []
    remaining = quantity
    for lot in sorted(lots, key=lambda item: (item.acquired, item.lot_id)):
        if lot.security_id != security_id or lot.settled_quantity == 0:
            continue
        take = min(remaining, lot.settled_quantity)
        if not take:
            continue
        basis_used = lot.basis * take / lot.quantity
        proceeds = taxable_sale_proceeds * take / quantity
        realised.append({
            "sale_id": sale_id,
            "lot_id": lot.lot_id,
            "security_id": security_id,
            "sale_date": sold,
            "acquired": lot.acquired,
            "quantity": take,
            "term": holding_term(lot.acquired, sold),
            "taxable_proceeds": proceeds,
            "basis": basis_used,
            "gain": proceeds - basis_used,
        })
        lot.quantity -= take
        lot.settled_quantity -= take
        lot.basis -= basis_used
        remaining -= take
        if not remaining:
            break
    if remaining:
        raise AssertionError("FIFO sale did not consume requested quantity")
    return realised


def compute_year_tax(
    gains: list[dict[str, object]], opening_losses: list[dict[str, object]],
    year: int,
) -> dict[str, object]:
    """Recompute one FY without mutating its opening carried-loss pools."""
    st = sum(float(row["gain"]) for row in gains if row["term"] == "ST")
    lt = sum(float(row["gain"]) for row in gains if row["term"] == "LT")
    gross_st = st
    gross_lt = lt

    # Current ST losses may reduce positive LT gains; current LT losses never
    # reduce ST gains. Same-category gains/losses were already netted above.
    current_st_to_lt = min(max(-st, 0.0), max(lt, 0.0))
    st += current_st_to_lt
    lt -= current_st_to_lt

    carried = []
    offsets = []
    for pool in sorted(opening_losses, key=lambda row: (int(row["origin_fy"]), str(row["term"]))):
        origin = int(pool["origin_fy"])
        amount = float(pool["amount"])
        term = str(pool["term"])
        if term not in {"ST", "LT"} or amount < 0 or origin >= year:
            raise ValueError("Invalid opening loss pool")
        if year > origin + 8:
            continue
        if term == "LT":
            used = min(amount, max(lt, 0.0))
            lt -= used
            amount -= used
            offsets.append({"origin_fy": origin, "term": term, "against": "LT", "amount": used})
        if amount:
            carried.append({"origin_fy": origin, "term": term, "amount": amount})

    # Brought-forward ST losses are used only after brought-forward LT losses.
    retained = []
    for pool in carried:
        if pool["term"] != "ST":
            retained.append(pool)
            continue
        amount = pool["amount"]
        against_st = min(amount, max(st, 0.0))
        st -= against_st
        amount -= against_st
        against_lt = min(amount, max(lt, 0.0))
        lt -= against_lt
        amount -= against_lt
        offsets.extend([
            {"origin_fy": pool["origin_fy"], "term": "ST", "against": "ST", "amount": against_st},
            {"origin_fy": pool["origin_fy"], "term": "ST", "against": "LT", "amount": against_lt},
        ])
        if amount:
            retained.append({**pool, "amount": amount})

    if st < 0:
        retained.append({"origin_fy": year, "term": "ST", "amount": -st})
    if lt < 0:
        retained.append({"origin_fy": year, "term": "LT", "amount": -lt})
    taxable_st = max(st, 0.0)
    exemption_used = min(max(lt, 0.0), LT_EXEMPTION)
    taxable_lt = max(lt - exemption_used, 0.0)
    liability = ST_RATE * taxable_st + LT_RATE * taxable_lt
    return {
        "fy": year,
        "gross_st": gross_st,
        "gross_lt": gross_lt,
        "current_st_loss_to_lt": current_st_to_lt,
        "opening_loss_offsets": offsets,
        "exemption_used": exemption_used,
        "taxable_st": taxable_st,
        "taxable_lt": taxable_lt,
        "liability": liability,
        "closing_losses": retained,
    }
