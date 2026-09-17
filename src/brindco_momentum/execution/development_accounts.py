"""Chronological executable MOM and VM development accounts through March 2023."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from math import floor, isfinite
from pathlib import Path

import pandas as pd

from brindco_momentum.execution.account_engine import (
    AccountState, affordable_buy_quantity, fill_terms, participation_cap_shares,
    recognise_bonus, recognise_dividend, rights_materiality, settle_due,
    settlement_after, target_shares,
)
from brindco_momentum.data.settlement_calendar import CUTOFF, ROOT, START, build_calendar
from brindco_momentum.execution.tax_model import Lot, compute_year_tax, consume_fifo, fiscal_year


OUT = ROOT / "results/accounts_development/passive_lapse_rights_scenario"
RIGHTS_EVIDENCE = ROOT / "results/accounts_development/rights_candidate_scan.csv"
DHANI_RIGHT = "CA_2dcc6f730654721a5203"
ADANIENT_ASSUMPTION = "CA_09d4133ad6ad9024fa83"
HGS_BONUS = "CA_a28c7ef7be5fba82424e"
HGS_DIVIDEND = "CA_4bd3ac9cadba72dfd0ee"
EASE_BONUS = "CA_bd1a9c0fb614d418b033"
EASE_SPLIT = "CA_d980fda0218090aafc5e"
ALKYLAMINE_SPLIT = "CA_4f478b35c127d00f600f"
ALKYLAMINE_SECURITY = "NSE_91CA1F1DFE78"
UNOMINDA_2018_BONUS = "CA_715af64eb2a5a45d9eb5"
UNOMINDA_SECURITY = "NSE_48390A9F12CC"
ALKYLAMINE_SPLIT_SOURCE = (
    "https://www.alkylamines.com/wp-content/uploads/2022/07/Annual-Report-FY-2021-22.pdf"
)

INPUTS = {
    "rights_evidence": RIGHTS_EVIDENCE,
    "winners": ROOT / "data/processed/momentum_winners.parquet",
    "overlay": ROOT / "data/processed/volatility_overlay_development.parquet",
    "panel": ROOT / "data/processed/research_panel_v2.parquet",
    "event_application": ROOT / "results/stock_total_return_audit/event_application_detail.csv",
    "accepted_actions": ROOT / "data/processed/corporate_action_treatment/in_universe_event_treatments.parquet",
    "treated_actions": ROOT / "data/processed/corporate_action_treatment/nse_corporate_actions_treated_through_2023_03_31.parquet",
    "settlement": ROOT / "data/processed/nse_settlement_calendar_2015_2023.parquet",
    "trading": ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet",
    "operational_notices": ROOT / "data/processed/account_operational_event_notices.csv",
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inputs() -> tuple[dict, list[date], dict, pd.DataFrame, dict]:
    hashes = {key: _hash(path) for key, path in INPUTS.items()}
    winners = pd.read_parquet(INPUTS["winners"], filters=[("formation_date", "<=", CUTOFF),
                                                           ("scored", "=", True)])
    winners["holding_month"] = winners.holding_month.astype(str)
    selections = {month: group.security_id.tolist() for month, group in winners.groupby("holding_month")}
    overlay = pd.read_parquet(INPUTS["overlay"], filters=[("formation_date", "<=", CUTOFF),
                                                          ("is_scored", "=", True)])
    exposures = dict(zip(overlay.holding_month.astype(str), overlay.exposure))
    assert set(selections) == set(exposures) and len(selections) == 96
    if any(len(names) < 20 or len(names) != len(set(names)) for names in selections.values()):
        raise ValueError("Unusable frozen winner set")

    trading = pd.read_parquet(
        INPUTS["trading"], columns=["date"],
        filters=[("date", ">=", START), ("date", "<=", CUTOFF)],
    )
    sessions = sorted(pd.to_datetime(trading.date).dt.date)
    if len(sessions) != len(set(sessions)) or sessions[0] != START.date() or sessions[-1] != CUTOFF.date():
        raise ValueError("Invalid development trading calendar")
    # April 2023 holiday *metadata* resolves T+2 obligations from late March;
    # there are no April 2023 market prices or values in this read.
    calendar = build_calendar(pd.Timestamp("2023-04-10"))
    settling = list(calendar.loc[calendar.settlement_business_day, "date"].dt.date)
    frozen = pd.read_parquet(INPUTS["settlement"])
    if not frozen.equals(calendar.loc[calendar.date.le(CUTOFF)].reset_index(drop=True)):
        raise ValueError("Settlement evidence differs from frozen development calendar")

    panel = pd.read_parquet(
        INPUTS["panel"],
        columns=["date", "security_id", "symbol", "series", "open", "high", "low",
                 "close", "volume", "adv20_lagged", "market_observed", "market_data_status"],
        filters=[("date", ">=", START), ("date", "<=", CUTOFF),
                 ("security_id", "in", sorted(set(winners.security_id)))],
    )
    if panel.date.max() > CUTOFF or panel.duplicated(["date", "security_id"]).any():
        raise ValueError("Panel cutoff or duplicate security-date failure")

    events = pd.read_csv(INPUTS["event_application"], parse_dates=["ex_date"])
    events = events.loc[events.ex_date.between(START, CUTOFF)
                        & events.security_id.isin(set(winners.security_id))].copy()
    treated = pd.read_parquet(
        INPUTS["treated_actions"],
        columns=["event_id", "ex_date", "payment_date"],
        filters=[("ex_date", "<=", CUTOFF)],
    )
    events = events.merge(treated.drop(columns="ex_date"), on="event_id", how="left", validate="one_to_one")
    accepted = pd.read_parquet(
        INPUTS["accepted_actions"],
        columns=["event_id", "rights_new_shares_per_old_share", "rights_subscription_price"],
    )
    events = events.merge(accepted, on="event_id", how="left", validate="one_to_one")
    if events.event_id.duplicated().any():
        raise ValueError("Duplicated corporate-action event")
    event_days = {day.date(): group.to_dict("records") for day, group in events.groupby("ex_date")}
    rights = pd.read_csv(RIGHTS_EVIDENCE, dtype={"event_id": str}).set_index("event_id")
    if rights.index.has_duplicates:
        raise ValueError("Duplicated rights evidence ID")
    notices = pd.read_csv(INPUTS["operational_notices"]).to_dict("records")
    event_lookup = events.set_index("event_id")
    if len(notices) != len({row["event_id"] for row in notices}):
        raise ValueError("Duplicated operational event notice")
    for notice in notices:
        event_id = notice["event_id"]
        if event_id not in event_lookup.index:
            raise ValueError(f"Operational notice has no accepted event: {event_id}")
        event = event_lookup.loc[event_id]
        if pd.isna(notice["announcement_date"]) or pd.isna(notice["effective_date"]):
            raise ValueError(f"Operational notice has a missing date: {event_id}")
        announced = pd.Timestamp(notice["announcement_date"]).date()
        effective = pd.Timestamp(notice["effective_date"]).date()
        if (not isinstance(notice["evidence_source"], str) or
                not notice["evidence_source"].startswith("https://") or
                not announced < effective or effective != event["ex_date"].date() or
                notice["security_id"] != event["security_id"] or
                event["application_status"] == "APPLIED_TO_RETURN"):
            raise ValueError(f"Invalid or unsupported operational event notice: {event_id}")
        notice["announcement_date"] = announced
        notice["effective_date"] = effective
    return selections, sessions, exposures, panel, {"events": event_days, "settling": settling,
                                                    "hashes": hashes, "rights": rights.to_dict("index"),
                                                    "operational_notices": notices}


def _apply_split(state: AccountState, security_id: str, multiplier: float) -> None:
    if not isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Invalid split multiplier")
    updated = []
    for lot in state.lots:
        if lot.security_id != security_id:
            continue
        units = lot.quantity * multiplier
        settled = lot.settled_quantity * multiplier
        if not units.is_integer() or not settled.is_integer():
            raise ValueError("Fractional split requires evidenced cash-in-lieu treatment")
        updated.append((lot, int(units), int(settled)))
    for lot, units, settled in updated:
        lot.quantity = units
        lot.settled_quantity = settled
    for entitlement in state.bonus_entitlements:
        if entitlement["security_id"] == security_id:
            entitlement["quantity"] *= multiplier


def _apply_alkylamine_split(state: AccountState, day: date) -> dict | None:
    """Round the shareholder entitlement once; retain fractional tax-lot lineage."""
    if day != date(2021, 5, 11):
        raise ValueError("Unexpected ALKYLAMINE ex-date")
    security_id = ALKYLAMINE_SECURITY
    lots = [lot for lot in state.lots if lot.security_id == security_id and lot.quantity]
    if not lots or any(lot.quantity <= 0 or lot.basis < 0 or
                       lot.settled_quantity != lot.quantity for lot in lots):
        raise ValueError("ALKYLAMINE split needs positive, fully settled lots")
    if any(row["security_id"] == security_id for row in state.bonus_entitlements):
        raise ValueError("ALKYLAMINE has an unsupported pending bonus entitlement")

    old_quantity = sum(lot.quantity for lot in lots)
    if not float(old_quantity).is_integer():
        raise ValueError("ALKYLAMINE pre-split account quantity is not whole")
    economic_quantity = old_quantity * 2.5
    whole_quantity = floor(economic_quantity)
    fraction = economic_quantity - whole_quantity
    old_basis = sum(lot.basis for lot in lots)
    updated = {lot.lot_id: {"quantity": lot.quantity * 2.5, "basis": lot.basis}
               for lot in lots}
    if len(updated) != len(lots):
        raise ValueError("Duplicated ALKYLAMINE tax-lot ID")

    claim = None
    if fraction:
        eligible = sorted((lot for lot in lots if (lot.quantity * 2.5) % 1 == 0.5),
                          key=lambda lot: (lot.acquired, lot.lot_id))
        if not eligible or fraction != 0.5:
            raise ValueError("Unsupported ALKYLAMINE account fraction")
        source = eligible[0]
        transformed = updated[source.lot_id]
        claim_basis = source.basis * fraction / transformed["quantity"]
        transformed["quantity"] -= fraction
        transformed["basis"] -= claim_basis
        claim = {
            "type": "FRACTIONAL_SPLIT_CASH_IN_LIEU",
            "account": state.account,
            "event_id": ALKYLAMINE_SPLIT,
            "security_id": security_id,
            "ex_date": day,
            "entitlement_date": date(2021, 5, 12),
            "pre_split_account_quantity": old_quantity,
            "split_multiplier": 2.5,
            "ordinary_share_quantity": whole_quantity,
            "fractional_quantity": fraction,
            "allocated_basis": claim_basis,
            "original_lot_id": source.lot_id,
            "original_acquisition_date": source.acquired,
            "original_lot_quantity": source.quantity,
            "sale_date": None,
            "gross_proceeds": None,
            "net_proceeds": None,
            "payment_date": None,
            "spendable_cash": 0.0,
            "account_value": None,
            "status": "UNPRICED_FRACTIONAL_SPLIT_CASH_IN_LIEU",
            "evidence_source": ALKYLAMINE_SPLIT_SOURCE,
            "lot_allocation_method": "EARLIEST_FRACTIONAL_LOT_THEN_LOT_ID",
        }

    if (sum(row["quantity"] for row in updated.values()) != whole_quantity or
            any(row["quantity"] < 0 or row["basis"] < -1e-8 for row in updated.values()) or
            abs(sum(row["basis"] for row in updated.values()) +
                (claim["allocated_basis"] if claim else 0.0) - old_basis) > 1e-6):
        raise ValueError("ALKYLAMINE split quantity/basis reconciliation failed")

    # No state changes occur until all account- and lot-level checks pass.
    for lot in lots:
        lot.quantity = updated[lot.lot_id]["quantity"]
        lot.settled_quantity = lot.quantity
        lot.basis = updated[lot.lot_id]["basis"]
    if claim:
        state.fractional_split_claims.append(claim)
    return claim


def _advance_unominda_2018(state: AccountState, day: date,
                            event_audit: list[dict]) -> None:
    """Allotment starts the bonus tax clock; delivery follows the evidenced posting."""
    if day not in {date(2018, 7, 13), date(2018, 7, 23)}:
        return
    for entitlement in list(state.bonus_entitlements):
        if entitlement["event_id"] != UNOMINDA_2018_BONUS:
            continue
        if day == date(2018, 7, 13):
            entitlement["tax_holding_start"] = day
            entitlement["status"] = "ALLOTTED_PENDING_DELIVERY"
            event_audit.append({"date": day, "event_id": UNOMINDA_2018_BONUS,
                                "security_id": UNOMINDA_SECURITY,
                                "status": "BONUS_ALLOTTED_UNDELIVERABLE",
                                "held_quantity": entitlement["quantity"]})
        else:
            if entitlement["tax_holding_start"] != date(2018, 7, 13):
                raise ValueError("UNOMINDA bonus has no verified allotment")
            quantity = entitlement["quantity"]
            if quantity <= 0 or not float(quantity).is_integer():
                raise ValueError("UNOMINDA bonus delivery quantity is invalid")
            state.lots.append(Lot(f"{state.account}-{UNOMINDA_2018_BONUS}-BONUS",
                                  UNOMINDA_SECURITY, date(2018, 7, 13), int(quantity),
                                  0.0, "BONUS_ZERO_BASIS", int(quantity)))
            state.bonus_entitlements.remove(entitlement)
            event_audit.append({"date": day, "event_id": UNOMINDA_2018_BONUS,
                                "security_id": UNOMINDA_SECURITY,
                                "status": "BONUS_DELIVERABLE_ZERO_BASIS_LOT",
                                "held_quantity": quantity})


def _apply_events(state: AccountState, day: date, rows: list[dict], marks: dict,
                  event_audit: list[dict], cash_events: list[dict],
                  rights_evidence: dict | None = None,
                  enable_alkylamine_cil: bool = False,
                  enable_unominda_2018: bool = False) -> dict | None:
    by_security = defaultdict(list)
    for row in rows:
        by_security[row["security_id"]].append(row)
    for security_id, group in by_security.items():
        held = state.economic_units(security_id)
        if not held:
            continue
        ids = {row["event_id"] for row in group}
        for source in [row for row in group if row["primary_class"] == "RIGHTS"]:
            event_id = source["event_id"]
            evidence = (rights_evidence or {}).get(event_id)
            if evidence is None or evidence["verification_status"] != "VERIFIED_PRIMARY":
                return {"date": day, "event_id": event_id, "security_id": security_id,
                        "reason": "HELD_RIGHTS_TERMS_UNVERIFIED", "held_quantity": held}
            if evidence["ordinary_status"] != "ORDINARY_VERIFIED":
                return {"date": day, "event_id": event_id, "security_id": security_id,
                        "reason": "HELD_NONORDINARY_RIGHTS_ISSUE", "held_quantity": held}
            detail = rights_materiality(state, security_id)
            ratio = float(source["rights_new_shares_per_old_share"])
            verified_ratio = float(evidence["ratio_a"]) / float(evidence["ratio_b"])
            verified_price = float(evidence["rights_subscription_price"])
            accepted_price = source["rights_subscription_price"]
            fractional_policy = evidence["fractional_policy"]
            if (not isfinite(ratio) or abs(ratio - verified_ratio) > 1e-12
                    or (pd.notna(accepted_price)
                        and abs(float(accepted_price) - verified_price) > 1e-8)
                    or fractional_policy not in {"FLOOR", "EXACT_INTEGER"}
                    or (fractional_policy == "EXACT_INTEGER"
                        and not (held * ratio).is_integer())
                    or pd.Timestamp(evidence["ex_date"]).date() != day):
                raise ValueError(f"Rights terms differ from verified offer: {event_id}")
            record_date = pd.Timestamp(evidence["record_date"]).date()
            close_date = pd.Timestamp(evidence["issue_close_date"]).date()
            if not day <= record_date <= close_date:
                raise ValueError(f"Invalid rights dates: {event_id}")
            # Rights accrue at ex-date; record date establishes the legal holder.
            whole_entitlement = floor(held * ratio)
            claim = {"date": day, "event_id": event_id, "security_id": security_id,
                     "entitlement_date": record_date,
                     "pre_event_shares": held, "new_share_entitlement": whole_entitlement,
                     "indicative_fractional_entitlement": held * ratio - whole_entitlement,
                     "fractional_policy": fractional_policy,
                     "subscription_price": verified_price, "subscribed": False,
                     "realised_sale_proceeds": 0.0, "account_claim_value": None,
                     "expiry_date": close_date,
                     "offer_terms_evidence": evidence["primary_evidence_url"],
                     "expiry_evidence": evidence["close_confirmation_url"],
                     "status": "OPEN_UNPRICED_PASSIVE_LAPSE",
                     "materiality_status": detail["status"]}
            state.rights_entitlements.append(claim)
            event_audit.append({**claim, "held_quantity": held})
            ids.remove(event_id)
        group = [row for row in group if row["event_id"] in ids]
        if {HGS_BONUS, HGS_DIVIDEND} <= ids:
            recognise_dividend(state, HGS_DIVIDEND, security_id, 28.0, None)
            recognise_bonus(state, HGS_BONUS, security_id, 1.0, None)
            applied = {HGS_BONUS, HGS_DIVIDEND}
        elif {EASE_BONUS, EASE_SPLIT} <= ids:
            _apply_split(state, security_id, 2.0)
            recognise_bonus(state, EASE_BONUS, security_id, 3.0, None)
            applied = {EASE_BONUS, EASE_SPLIT}
        else:
            applied = set()
        for row in group:
            event_id = row["event_id"]
            if event_id in applied:
                event_audit.append({"date": day, "event_id": event_id, "security_id": security_id,
                                    "status": "VERIFIED_COMBINED", "held_quantity": held})
                continue
            status = row["application_status"]
            if event_id == ADANIENT_ASSUMPTION:
                event_audit.append({"date": day, "event_id": event_id, "security_id": security_id,
                                    "status": "FROZEN_ZERO_INCREMENTAL_MODELLING", "held_quantity": held})
                continue
            if event_id == ALKYLAMINE_SPLIT and enable_alkylamine_cil:
                if (day != date(2021, 5, 11) or security_id != ALKYLAMINE_SECURITY or
                        row["primary_class"] != "SPLIT" or
                        row["application_status"] != "APPLIED_TO_RETURN" or
                        float(row["share_effect"]) != 2.5 or float(row["cash_effect"]) != 0):
                    raise ValueError("ALKYLAMINE split differs from verified terms")
                claim = _apply_alkylamine_split(state, day)
                event_audit.append({"date": day, "event_id": event_id,
                                    "security_id": security_id,
                                    "status": "ACCOUNT_LEVEL_SPLIT_WITH_CIL" if claim else
                                              "ACCOUNT_LEVEL_SPLIT_NO_FRACTION",
                                    "held_quantity": held,
                                    "ordinary_share_quantity": state.owned(security_id),
                                    "fractional_quantity": claim["fractional_quantity"] if claim else 0,
                                    "fractional_basis": claim["allocated_basis"] if claim else 0})
                continue
            if event_id == UNOMINDA_2018_BONUS and enable_unominda_2018:
                if (day != date(2018, 7, 11) or security_id != UNOMINDA_SECURITY or
                        row["primary_class"] != "BONUS" or
                        row["application_status"] != "APPLIED_TO_RETURN" or
                        float(row["share_effect"]) != 3 or
                        float(row["cash_effect"]) != 1.6):
                    raise ValueError("UNOMINDA 2018 event differs from accepted combined action")
                # The FY2017-18 final dividend belongs to the pre-bonus shares.
                recognise_dividend(state, event_id, security_id, 1.6, None)
                cash_events.append({"date": day, "category": "DIVIDEND_RECEIVABLE",
                                    "event_id": event_id, "amount": held * 1.6})
                recognise_bonus(state, event_id, security_id, 2.0, None)
                event_audit.append({"date": day, "event_id": event_id,
                                    "security_id": security_id,
                                    "status": "BONUS_AND_PRE_BONUS_DIVIDEND_RECOGNISED",
                                    "held_quantity": held, "bonus_quantity": 2 * held,
                                    "dividend_receivable": 1.6 * held})
                continue
            if status in {"NOT_SIGNAL_RELEVANT", "NO_DIRECT_ADJUSTMENT_REQUIRED"}:
                continue
            if status != "APPLIED_TO_RETURN":
                return {"date": day, "event_id": event_id, "security_id": security_id,
                        "reason": "UNRESOLVED_HELD_CORPORATE_ACTION", "held_quantity": held,
                        "last_mark": marks.get(security_id), "source_status": status}
            cash_per_share = float(row["cash_effect"])
            multiplier = float(row["share_effect"])
            if not isfinite(cash_per_share) or not isfinite(multiplier):
                return {"date": day, "event_id": event_id, "security_id": security_id,
                        "reason": "INVALID_HELD_ACTION_TERMS", "held_quantity": held}
            if row["primary_class"] == "DIVIDEND" and cash_per_share:
                payment = row["payment_date"]
                payment_date = payment.date() if pd.notna(payment) else None
                recognise_dividend(state, event_id, security_id, cash_per_share, payment_date)
                cash_events.append({"date": day, "category": "DIVIDEND_RECEIVABLE",
                                    "event_id": event_id, "amount": held * cash_per_share})
            elif row["primary_class"] in {"SPLIT", "CONSOLIDATION"} and multiplier != 1:
                _apply_split(state, security_id, multiplier)
            elif row["primary_class"] == "BONUS" and multiplier > 1:
                recognise_bonus(state, event_id, security_id, multiplier - 1, None)
            elif row["primary_class"] not in {"DIVIDEND", "SPLIT", "CONSOLIDATION", "BONUS"}:
                return {"date": day, "event_id": event_id, "security_id": security_id,
                        "reason": "UNDEFINED_HELD_ACCOUNT_MECHANICS", "held_quantity": held}
            event_audit.append({"date": day, "event_id": event_id, "security_id": security_id,
                                "status": "APPLIED_ACCOUNT_EVENT", "held_quantity": held})
    return None


def _expire_rights(state: AccountState, day: date, event_audit: list[dict]) -> None:
    for claim in state.rights_entitlements:
        if claim["status"] == "OPEN_UNPRICED_PASSIVE_LAPSE" and day >= claim["expiry_date"]:
            claim["status"] = "LAPSED_UNEXERCISED"
            claim["lapse_date"] = claim["expiry_date"]
            event_audit.append({"date": day, "event_id": claim["event_id"],
                                "security_id": claim["security_id"],
                                "status": "LAPSED_UNEXERCISED", "held_quantity": claim["pre_event_shares"],
                                "realised_sale_proceeds": 0.0})


def run_account(name: str, selections: dict, sessions: list[date], exposures: dict,
                panel: pd.DataFrame, common: dict, output_dir: Path = OUT,
                scenario: str = "PASSIVE_LAPSE_RIGHTS_SCENARIO",
                enable_alkylamine_cil: bool = False,
                enable_unominda_2018: bool = False) -> dict:
    state = AccountState(name)
    by_date = iter(panel.groupby("date", sort=True))
    next_group = next(by_date, None)
    marks = {}
    orders, fills, positions, cash_events, nav_daily = [], [], [], [], []
    gains, tax_years, event_audit = [], [], []
    opening_losses = []
    current_fy = fiscal_year(sessions[0])
    current_gains = []
    pending_buy_lots = []
    active_month, month_sessions, target_notional = None, 0, {}
    last_nav = state.cash
    blocker = None
    maximum_market_date = panel.date.max().date()
    cash_events.append({"date": sessions[0], "category": "INITIAL_FUNDING", "amount": state.cash})

    for day_index, day in enumerate(sessions):
        day_stamp = pd.Timestamp(day)
        prices = {}
        if next_group is not None and next_group[0] == day_stamp:
            prices = {row.security_id: row for row in next_group[1].itertuples(index=False)}
            next_group = next(by_date, None)
        month = day.strftime("%Y-%m")
        if month != active_month:
            active_month = month
            month_sessions = 0
            allocation = 1.0 if name == "MOM" else float(exposures[month])
            names = selections[month]
            target_notional = {sid: last_nav * allocation / len(names) for sid in names}
        month_sessions += 1

        try:
            notices = common.get("operational_notices", [])
            active_exit_ids = {row["security_id"] for row in notices
                               if day > row["announcement_date"]}
            due_exit_ids = {row["security_id"] for row in notices
                            if row["announcement_date"] < day < row["effective_date"]}
            for notice in notices:
                if day == notice["effective_date"] and state.economic_units(notice["security_id"]):
                    blocker = {"date": day, "event_id": notice["event_id"],
                               "security_id": notice["security_id"],
                               "reason": "ANNOUNCED_EVENT_RESIDUAL_POSITION",
                               "announcement_date": notice["announcement_date"],
                               "evidence_source": notice["evidence_source"],
                               "held_quantity": state.economic_units(notice["security_id"])}
                    break
            if blocker:
                break
            blocker = _apply_events(state, day, common["events"].get(day, []), marks,
                                    event_audit, cash_events, common["rights"],
                                    enable_alkylamine_cil, enable_unominda_2018)
            if blocker:
                break
            if enable_unominda_2018:
                _advance_unominda_2018(state, day, event_audit)
            _expire_rights(state, day, event_audit)
            for record in settle_due(state, day):
                cash_events.append({"date": day, "category": record["category"],
                                    "amount": record["amount"],
                                    "event_id": record.get("event_id", record.get("fill_id"))})
            outstanding = []
            for pending in pending_buy_lots:
                if pending["settlement_date"] <= day:
                    lot = next(lot for lot in state.lots if lot.lot_id == pending["lot_id"])
                    lot.settled_quantity = lot.quantity
                else:
                    outstanding.append(pending)
            pending_buy_lots = outstanding

            if month_sessions <= 5 or due_exit_ids:
                candidates = set(due_exit_ids)
                if month_sessions <= 5:
                    candidates |= set(target_notional) | {lot.security_id for lot in state.lots}
                    candidates |= {row["security_id"] for row in state.bonus_entitlements}
                sell_orders, buy_orders = [], []
                for sid in candidates:
                    quote = prices.get(sid)
                    if quote is None or not isfinite(float(quote.open)) or quote.open <= 0:
                        if sid in due_exit_ids and state.economic_units(sid):
                            orders.append({"date": day, "order_id": f"{name}-{day}-{sid}-SELL",
                                           "security_id": sid, "side": "SELL",
                                           "requested_shares": floor(state.economic_units(sid)),
                                           "filled_shares": 0,
                                           "status": "MANDATORY_EXIT_NO_EXECUTABLE_QUOTE"})
                        continue
                    if sid in due_exit_ids:
                        quantity = floor(state.economic_units(sid))
                        if quantity:
                            sell_orders.append((-1, quantity * quote.open, sid, quantity))
                        continue
                    if month_sessions > 5:
                        continue
                    desired = target_shares(target_notional.get(sid, 0.0), float(quote.open))
                    difference = desired - state.economic_units(sid)
                    if difference < 0:
                        sell_orders.append((int(target_notional.get(sid, 0.0) > 0),
                                            -difference * quote.open, sid, floor(-difference)))
                    elif difference > 0:
                        if sid in active_exit_ids:
                            orders.append({"date": day, "order_id": f"{name}-{day}-{sid}-BUY",
                                           "security_id": sid, "side": "BUY",
                                           "requested_shares": floor(difference),
                                           "filled_shares": 0,
                                           "status": "ANNOUNCED_EVENT_BUY_BLOCKED"})
                        else:
                            buy_orders.append((sid, floor(difference), float(quote.open)))
                sell_orders.sort(key=lambda item: (item[0], -item[1], item[2]))
                for priority, _, sid, desired_qty in sell_orders:
                    quote = prices[sid]
                    cap = participation_cap_shares(float(quote.adv20_lagged), float(quote.open))
                    qty = min(desired_qty, state.settled(sid), cap)
                    if priority == -1:
                        reason = ("MANDATORY_EXIT_FILLED" if qty == desired_qty else
                                  "MANDATORY_EXIT_PARTIAL" if qty else
                                  "MANDATORY_EXIT_UNSETTLED_OR_CAP")
                    else:
                        reason = "ELIGIBLE" if qty else "UNSETTLED_OR_CAP"
                    if (not bool(quote.market_observed) or quote.market_data_status != "OK"
                            or quote.series not in {"EQ", "BE", "BZ"}
                            or not isfinite(float(quote.volume)) or quote.volume <= 0):
                        qty, reason = 0, "NO_EXECUTABLE_MARKET_OBSERVATION"
                    order_id = f"{name}-{day}-{sid}-SELL"
                    orders.append({"date": day, "order_id": order_id, "security_id": sid,
                                   "side": "SELL", "requested_shares": desired_qty,
                                   "filled_shares": qty, "status": reason})
                    if not qty:
                        continue
                    terms = fill_terms("SELL", qty, float(quote.open), float(quote.adv20_lagged))
                    fill_id = f"{order_id}-FILL"
                    taxable = terms["consideration"] - terms["deductible_fees"]
                    rows = consume_fifo(state.lots, sid, qty, day, taxable, fill_id)
                    gains.extend(rows)
                    current_gains.extend(rows)
                    due = settlement_after(day, common["settling"])
                    state.sale_receivables.append({"fill_id": fill_id, "security_id": sid,
                                                   "amount": terms["cash_flow"], "settlement_date": due})
                    fills.append({"date": day, "fill_id": fill_id, "order_id": order_id,
                                  "security_id": sid, "side": "SELL", "settlement_date": due, **terms})
                    cash_events.append({"date": day, "category": "SALE_RECEIVABLE",
                                        "event_id": fill_id, "amount": terms["cash_flow"]})

                provision = compute_year_tax(current_gains, opening_losses, current_fy)
                state.tax_liability = sum(row["liability"] - row["paid"] for row in tax_years) + provision["liability"]
                valid_buys = []
                for sid, desired_qty, raw_open in buy_orders:
                    quote = prices[sid]
                    reason = "ELIGIBLE"
                    if (not bool(quote.market_observed) or quote.market_data_status != "OK"
                            or quote.series not in {"EQ", "BE", "BZ"}
                            or not isfinite(float(quote.volume)) or quote.volume <= 0):
                        reason = "NO_EXECUTABLE_MARKET_OBSERVATION"
                    elif not isfinite(float(quote.adv20_lagged)) or quote.adv20_lagged <= 0:
                        reason = "NO_LAGGED_ADV"
                    if reason == "ELIGIBLE":
                        valid_buys.append((sid, min(desired_qty, participation_cap_shares(float(quote.adv20_lagged), raw_open)), raw_open))
                    else:
                        orders.append({"date": day, "order_id": f"{name}-{day}-{sid}-BUY",
                                       "security_id": sid, "side": "BUY", "requested_shares": desired_qty,
                                       "filled_shares": 0, "status": reason})
                # A frozen target deficit determines each name's proportional claim
                # on scarce settled cash. Whole-share residual goes by security ID.
                demand = sum(qty * raw_open for _, qty, raw_open in valid_buys)
                free = state.free_cash()
                budgets = {sid: free * qty * raw_open / demand if demand else 0.0
                           for sid, qty, raw_open in valid_buys}
                quantities = {}
                for sid, qty, raw_open in sorted(valid_buys):
                    quote = prices[sid]
                    quantities[sid] = affordable_buy_quantity(qty, budgets[sid], raw_open,
                                                                float(quote.adv20_lagged))
                    if quantities[sid]:
                        free -= -fill_terms("BUY", quantities[sid], raw_open,
                                            float(quote.adv20_lagged))["cash_flow"]
                for sid, qty, raw_open in sorted(valid_buys):
                    adv = float(prices[sid].adv20_lagged)
                    allocated = quantities[sid]
                    previous_cost = (-fill_terms("BUY", allocated, raw_open, adv)["cash_flow"]
                                     if allocated else 0.0)
                    low, high = allocated, qty
                    while low < high:
                        candidate = (low + high + 1) // 2
                        increment = -fill_terms("BUY", candidate, raw_open, adv)["cash_flow"] - previous_cost
                        if increment <= free + 1e-8:
                            low = candidate
                        else:
                            high = candidate - 1
                    quantities[sid] = low
                    if low > allocated:
                        free -= -fill_terms("BUY", low, raw_open, adv)["cash_flow"] - previous_cost
                for sid, desired_qty, raw_open in sorted(valid_buys):
                    qty = quantities[sid]
                    order_id = f"{name}-{day}-{sid}-BUY"
                    orders.append({"date": day, "order_id": order_id, "security_id": sid,
                                   "side": "BUY", "requested_shares": desired_qty,
                                   "filled_shares": qty, "status": "FILLED" if qty else "CASH_OR_CAP"})
                    if not qty:
                        continue
                    terms = fill_terms("BUY", qty, raw_open, float(prices[sid].adv20_lagged))
                    if -terms["cash_flow"] > state.free_cash() + 1e-6:
                        raise ValueError("Buy would use unsettled or tax-reserved cash")
                    state.cash += terms["cash_flow"]
                    fill_id = f"{order_id}-FILL"
                    due = settlement_after(day, common["settling"])
                    state.lots.append(Lot(fill_id, sid, day, qty,
                                          terms["consideration"] + terms["deductible_fees"],
                                          "IMPACTED_FILL_EXCLUDING_STT", 0))
                    pending_buy_lots.append({"lot_id": fill_id, "settlement_date": due})
                    fills.append({"date": day, "fill_id": fill_id, "order_id": order_id,
                                  "security_id": sid, "side": "BUY", "settlement_date": due, **terms})
                    cash_events.append({"date": day, "category": "PURCHASE",
                                        "event_id": fill_id, "amount": terms["cash_flow"]})

            stale = []
            held_ids = {lot.security_id for lot in state.lots if lot.quantity}
            held_ids |= {row["security_id"] for row in state.bonus_entitlements}
            for sid in held_ids:
                quote = prices.get(sid)
                if quote is not None and isfinite(float(quote.close)) and quote.close > 0 and bool(quote.market_observed):
                    marks[sid] = float(quote.close)
                elif sid in marks:
                    stale.append(sid)
                else:
                    blocker = {"date": day, "security_id": sid,
                               "reason": "HELD_SECURITY_NO_VALID_MARK", "held_quantity": state.economic_units(sid)}
                    break
            if blocker:
                break
            state.tax_liability = sum(row["liability"] - row["paid"] for row in tax_years) + compute_year_tax(
                current_gains, opening_losses, current_fy)["liability"]
            if state.cash < -1e-6 or state.tax_liability < -1e-6:
                raise ValueError("Negative cash or tax provision")
            stock_value = sum(state.economic_units(sid) * marks[sid] for sid in held_ids)
            sale_claims = sum(row["amount"] for row in state.sale_receivables)
            dividend_claims = sum(row["amount"] for row in state.dividend_receivables)
            nav = state.nav(marks)
            check = stock_value + state.cash + sale_claims + dividend_claims - state.tax_liability
            if abs(nav - check) > 1e-6 or nav <= 0 or stock_value > nav + 1e-6:
                raise ValueError("NAV reconciliation failure")
            unpriced_rights = sum(row["status"] == "OPEN_UNPRICED_PASSIVE_LAPSE"
                                  for row in state.rights_entitlements)
            unpriced_split = bool(state.fractional_split_claims)
            if unpriced_split:
                nav_status = "UNPRICED_FRACTIONAL_SPLIT_CLAIM_EXCLUDED"
            elif unpriced_rights:
                nav_status = "PASSIVE_LAPSE_UNPRICED_RIGHT_EXCLUDED"
            elif state.rights_entitlements:
                nav_status = "PASSIVE_LAPSE_SCENARIO"
            else:
                nav_status = "PRE_RIGHT_AUDITED"
            nav_daily.append({"date": day, "account": name, "nav": nav,
                              "daily_return": nav / last_nav - 1,
                              "nav_status": nav_status,
                              "unpriced_rights_count": unpriced_rights,
                              "stocks": stock_value, "settled_cash": state.cash,
                              "sale_receivables": sale_claims,
                              "dividend_receivables": dividend_claims,
                              "tax_liability": state.tax_liability,
                              "free_cash": state.free_cash(), "stale_marks": ",".join(sorted(stale)),
                              "reconciliation_error": nav - check})
            last_nav = nav
            for sid in sorted(held_ids):
                positions.append({"date": day, "account": name, "security_id": sid,
                                  "owned_shares": state.owned(sid), "settled_shares": state.settled(sid),
                                  "unavailable_bonus_units": state.economic_units(sid) - state.owned(sid),
                                  "close_mark": marks[sid], "mark_stale": sid in stale,
                                  "market_value": state.economic_units(sid) * marks[sid]})
            next_fy = fiscal_year(sessions[day_index + 1]) if day_index + 1 < len(sessions) else current_fy
            if next_fy != current_fy:
                result = compute_year_tax(current_gains, opening_losses, current_fy)
                outstanding = result["liability"]
                paid = min(state.cash, outstanding)
                if paid:
                    state.cash -= paid
                    state.tax_liability -= paid
                    cash_events.append({"date": day, "category": "ANNUAL_TAX_PAYMENT",
                                        "event_id": str(current_fy), "amount": -paid})
                tax_years.append({**result, "paid": paid})
                opening_losses = result["closing_losses"]
                current_gains = []
                current_fy = next_fy
        except (ValueError, KeyError, AssertionError) as exc:
            blocker = {"date": day, "reason": "ACCOUNT_RECONCILIATION_OR_METHOD_ERROR",
                       "detail": str(exc)}
            break

    if blocker and blocker.get("held_quantity") and blocker.get("security_id") in marks and nav_daily:
        blocker["prior_close_exposure_value"] = blocker["held_quantity"] * marks[blocker["security_id"]]
        blocker["prior_close_weight"] = blocker["prior_close_exposure_value"] / nav_daily[-1]["nav"]
    output = {"account": name, "last_valid_date": nav_daily[-1]["date"] if nav_daily else None,
              "valid_daily_nav_rows": len(nav_daily), "blocker": blocker,
              "scenario": scenario,
              "unpriced_rights_nav_rows": sum(row["unpriced_rights_count"] > 0 for row in nav_daily),
              "unpriced_fractional_split_claim_count": len(state.fractional_split_claims),
              "unpriced_fractional_split_quantity": sum(
                  row["fractional_quantity"] for row in state.fractional_split_claims),
              "maximum_value_bearing_market_date_read": maximum_market_date,
              "last_market_date_processed": day,
              "unspendable_dividend_count": len(state.dividend_receivables),
              "unspendable_dividend_amount": sum(row["amount"] for row in state.dividend_receivables),
              "unavailable_bonus_count": len(state.bonus_entitlements),
              "unavailable_bonus_units": sum(row["quantity"] for row in state.bonus_entitlements),
              "unavailable_bonus_value": sum(row["quantity"] * marks.get(row["security_id"], 0)
                                             for row in state.bonus_entitlements),
              "max_nav_reconciliation_error": max((abs(row["reconciliation_error"]) for row in nav_daily), default=0),
              "dhani_event_status": next((row["status"] for row in state.rights_entitlements
                                          if row["event_id"] == DHANI_RIGHT), "NOT_REACHED")}
    output_dir.mkdir(parents=True, exist_ok=True)
    for table_name, records in [("orders", orders), ("fills", fills), ("positions", positions),
                                ("cash_events", cash_events), ("nav_daily", nav_daily),
                                ("realised_gains", gains), ("tax_years", tax_years),
                                ("held_event_audit", event_audit),
                                ("dividend_receivables", state.dividend_receivables),
                                ("bonus_entitlements", state.bonus_entitlements)]:
        if records:
            frame = pd.DataFrame(records)
            frame["account"] = name
            frame["input_manifest_hash"] = common["manifest_hash"]
            frame.to_parquet(output_dir / f"{name}_{table_name}.parquet", index=False)
    if state.rights_entitlements:
        rights = pd.DataFrame(state.rights_entitlements)
        rights["account"] = name
        rights["input_manifest_hash"] = common["manifest_hash"]
        rights.to_parquet(output_dir / f"{name}_rights_entitlements.parquet", index=False)
    if state.fractional_split_claims:
        claims = pd.DataFrame(state.fractional_split_claims)
        claims["input_manifest_hash"] = common["manifest_hash"]
        claims.to_parquet(output_dir / f"{name}_fractional_split_claims.parquet", index=False)
    snapshot = {"cash": state.cash, "tax_liability": state.tax_liability,
                "lots": [lot.__dict__ for lot in state.lots if lot.quantity],
                "sale_receivables": state.sale_receivables,
                "dividend_receivables": state.dividend_receivables,
                "bonus_entitlements": state.bonus_entitlements,
                "rights_entitlements": state.rights_entitlements,
                "fractional_split_claims": state.fractional_split_claims,
                "pending_buy_lots": pending_buy_lots, "opening_losses": opening_losses,
                "current_gains": current_gains, "tax_years": tax_years,
                "last_marks": marks, "blocker": blocker}
    (output_dir / f"{name}_state.json").write_text(json.dumps(snapshot, default=str, indent=2))
    return output


def main(output_dir: Path = OUT, scenario: str = "PASSIVE_LAPSE_RIGHTS_SCENARIO",
         enable_alkylamine_cil: bool = False,
         enable_unominda_2018: bool = False) -> None:
    selections, sessions, exposures, panel, common = inputs()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.DataFrame([{"input": key, "path": str(path.relative_to(ROOT)), "sha256": common["hashes"][key]}
                             for key, path in INPUTS.items()])
    manifest.to_csv(output_dir / "input_manifest.csv", index=False)
    common["manifest_hash"] = _hash(output_dir / "input_manifest.csv")
    summary = []
    for name in ("MOM", "VM"):
        result = run_account(name, selections, sessions, exposures, panel, common,
                             output_dir, scenario, enable_alkylamine_cil,
                             enable_unominda_2018)
        summary.append({**result, "blocker": json.dumps(result["blocker"], default=str)})
        print(result)
    pd.DataFrame(summary).to_csv(output_dir / "account_run_summary.csv", index=False)
    after = {key: _hash(path) for key, path in INPUTS.items()}
    if after != common["hashes"]:
        raise ValueError("Frozen input changed during account run")


if __name__ == "__main__":
    main()
