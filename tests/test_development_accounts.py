import json
from datetime import date
from math import floor

import pandas as pd
import pytest

from brindco_momentum.execution.account_engine import AccountState
from brindco_momentum.execution.development_accounts import (
    CUTOFF, DHANI_RIGHT, OUT, _apply_events, _apply_split, _expire_rights,
)
from brindco_momentum.execution.tax_model import Lot


OLD_OUT = OUT.parent / "passive_lapse"


def rights_evidence(event_id, symbol, ex_date, record_date, close_date, numerator,
                    denominator, price):
    evidence = {"event_id": event_id, "symbol": symbol, "ex_date": ex_date,
                "record_date": record_date, "issue_close_date": close_date,
                "ratio_a": numerator, "ratio_b": denominator,
                "rights_subscription_price": price, "fractional_policy": "FLOOR",
                "ordinary_status": "ORDINARY_VERIFIED", "verification_status": "VERIFIED_PRIMARY",
                "primary_evidence_url": "official-offer", "close_confirmation_url": "official-close"}
    event = {"event_id": event_id, "security_id": symbol, "primary_class": "RIGHTS",
             "rights_new_shares_per_old_share": numerator / denominator,
             "rights_subscription_price": price}
    return event, {event_id: evidence}


@pytest.mark.parametrize("account,quantity", [("MOM", 1154), ("VM", 642)])
def test_dhani_passive_lapse_has_no_fabricated_cash_or_shares(account, quantity):
    state = AccountState(account)
    state.lots.append(Lot("old", "DHANI", date(2017, 4, 1), quantity,
                          quantity * 241.55, "FILL", quantity))
    starting_cash = state.cash
    starting_nav = state.nav({"DHANI": 241.55})
    audit, cash_events = [], []
    event, evidence = rights_evidence(DHANI_RIGHT, "DHANI", "2018-02-09",
                                      "2018-02-12", "2018-03-07", 3, 16, 240.0)

    blocker = _apply_events(state, date(2018, 2, 9), [event],
                            {"DHANI": 241.55}, audit, cash_events, evidence)
    assert blocker is None
    claim = state.rights_entitlements[0]
    assert claim["new_share_entitlement"] == floor(quantity * 3 / 16)
    assert claim["indicative_fractional_entitlement"] == pytest.approx(quantity * 3 / 16 % 1)
    assert claim["status"] == "OPEN_UNPRICED_PASSIVE_LAPSE"
    assert claim["account_claim_value"] is None
    assert claim["realised_sale_proceeds"] == 0
    assert not claim["subscribed"]
    assert state.owned("DHANI") == quantity
    assert state.cash == starting_cash
    assert state.nav({"DHANI": 241.55}) == starting_nav
    assert cash_events == []

    _expire_rights(state, date(2018, 3, 6), audit)
    assert claim["status"] == "OPEN_UNPRICED_PASSIVE_LAPSE"
    _expire_rights(state, date(2018, 3, 7), audit)
    assert claim["status"] == "LAPSED_UNEXERCISED"
    assert claim["lapse_date"] == date(2018, 3, 7)
    assert state.cash == starting_cash
    assert state.owned("DHANI") == quantity
    assert cash_events == []


@pytest.mark.parametrize("ratio,price", [(1 / 16, 240.0), (3 / 16, 241.0)])
def test_dhani_offer_terms_cannot_silently_change(ratio, price):
    state = AccountState("MOM")
    state.lots.append(Lot("old", "DHANI", date(2017, 4, 1), 16, 1000, "FILL", 16))
    event, evidence = rights_evidence(DHANI_RIGHT, "DHANI", "2018-02-09",
                                      "2018-02-12", "2018-03-07", 3, 16, 240.0)
    event["rights_new_shares_per_old_share"] = ratio
    event["rights_subscription_price"] = price
    with pytest.raises(ValueError, match="Rights terms differ"):
        _apply_events(state, date(2018, 2, 9), [event], {}, [], [], evidence)
    assert state.rights_entitlements == []


@pytest.mark.parametrize("account,quantity", [("MOM", 1154), ("VM", 642)])
def test_passive_lapse_run_keeps_unpriced_interval_visible(account, quantity):
    summary = pd.read_csv(OLD_OUT / "account_run_summary.csv").set_index("account").loc[account]
    blocker = json.loads(summary.blocker)
    assert blocker is None or blocker.get("event_id") != DHANI_RIGHT
    assert summary.scenario == "DHANI_PASSIVE_LAPSE_NO_PROCEEDS"
    assert summary.dhani_event_status == "LAPSED_UNEXERCISED"
    assert summary.maximum_value_bearing_market_date_read == str(CUTOFF.date())
    assert summary.max_nav_reconciliation_error < 1e-6

    rights = pd.read_parquet(OLD_OUT / f"{account}_rights_entitlements.parquet")
    claim = rights.iloc[0]
    assert claim.pre_event_shares == quantity
    assert claim.new_share_entitlement == floor(quantity * 3 / 16)
    assert claim.realised_sale_proceeds == 0
    assert pd.isna(claim.account_claim_value)
    assert claim.status == "LAPSED_UNEXERCISED"
    assert claim.lapse_date == date(2018, 3, 7)

    nav = pd.read_parquet(OLD_OUT / f"{account}_nav_daily.parquet")
    assert nav.date.min() == date(2015, 4, 1)
    assert nav.date.max() >= date(2018, 3, 7)
    assert nav.loc[nav.date.eq(date(2018, 2, 9)), "nav_status"].iloc[0] == (
        "PASSIVE_LAPSE_UNPRICED_RIGHT_EXCLUDED")
    assert nav.loc[nav.date.eq(date(2018, 3, 7)), "nav_status"].iloc[0] == (
        "PASSIVE_LAPSE_SCENARIO")
    assert summary.unpriced_rights_nav_rows == nav.unpriced_rights_count.gt(0).sum()
    assert (nav.settled_cash >= -1e-6).all()
    assert (nav.free_cash >= -1e-6).all()
    assert (nav.reconciliation_error.abs() < 1e-6).all()

    cash = pd.read_parquet(OLD_OUT / f"{account}_cash_events.parquet")
    assert not cash.event_id.eq(DHANI_RIGHT).any()


def test_original_stopped_run_is_preserved():
    old = OUT.parent
    for account in ("MOM", "VM"):
        nav = pd.read_parquet(old / f"{account}_nav_daily.parquet")
        assert len(nav) == 709
        assert nav.date.max() == date(2018, 2, 8)


def test_account_claims_remain_unavailable():
    for account in ("MOM", "VM"):
        dividends = pd.read_parquet(OLD_OUT / f"{account}_dividend_receivables.parquet")
        bonuses = pd.read_parquet(OLD_OUT / f"{account}_bonus_entitlements.parquet")
        assert dividends.payment_date.isna().all()
        assert dividends.status.eq("UNSPENDABLE_PENDING_PAYMENT").all()
        assert bonuses.availability_date.isna().all()
        assert bonuses.tax_holding_start.isna().all()
        assert bonuses.status.eq("UNAVAILABLE_FOR_DELIVERY").all()


@pytest.mark.parametrize("account,quantity", [("MOM", 418), ("VM", 202)])
def test_unominda_passive_lapse_tracks_only_the_entitlement(account, quantity):
    state = AccountState(account)
    state.lots.append(Lot("old", "UNOMINDA", date(2020, 8, 1), quantity,
                          quantity * 250, "FILL", quantity))
    event_id = "CA_277f0c578cd42848896a"
    event, evidence = rights_evidence(event_id, "UNOMINDA", "2020-08-14",
                                      "2020-08-17", "2020-09-08", 1, 27, 250.0)
    event["cash_effect"] = 10_000.0  # A theoretical value must never enter the account.
    cash, nav = state.cash, state.nav({"UNOMINDA": 250.0})
    audit, cash_events = [], []
    assert _apply_events(state, date(2020, 8, 14), [event], {}, audit,
                         cash_events, evidence) is None
    claim = state.rights_entitlements[0]
    assert claim["new_share_entitlement"] == quantity // 27
    assert claim["entitlement_date"] == date(2020, 8, 17)
    assert claim["account_claim_value"] is None
    assert state.cash == cash and state.owned("UNOMINDA") == quantity
    assert state.nav({"UNOMINDA": 250.0}) == nav
    assert cash_events == []
    _expire_rights(state, date(2020, 9, 7), audit)
    assert claim["status"] == "OPEN_UNPRICED_PASSIVE_LAPSE"
    _expire_rights(state, date(2020, 9, 8), audit)
    assert claim["status"] == "LAPSED_UNEXERCISED"
    assert claim["lapse_date"] == date(2020, 9, 8)
    assert state.cash == cash and state.owned("UNOMINDA") == quantity


def test_unverified_or_multi_leg_rights_stops_account():
    state = AccountState("MOM")
    state.lots.append(Lot("old", "X", date(2020, 8, 1), 30, 300, "FILL", 30))
    event, evidence = rights_evidence("right", "X", "2020-08-14",
                                      "2020-08-17", "2020-09-08", 1, 27, 250.0)
    evidence["right"]["verification_status"] = "PENDING_PRIMARY_EVIDENCE"
    blocker = _apply_events(state, date(2020, 8, 14), [event], {}, [], [], evidence)
    assert blocker["reason"] == "HELD_RIGHTS_TERMS_UNVERIFIED"
    evidence["right"]["verification_status"] = "PRIMARY_TERMS_SCHEDULED_CLOSE_ONLY"
    blocker = _apply_events(state, date(2020, 8, 14), [event], {}, [], [], evidence)
    assert blocker["reason"] == "HELD_RIGHTS_TERMS_UNVERIFIED"
    evidence["right"]["verification_status"] = "VERIFIED_PRIMARY"
    evidence["right"]["ordinary_status"] = "MULTI_LEG_RIGHTS"
    blocker = _apply_events(state, date(2020, 8, 14), [event], {}, [], [], evidence)
    assert blocker["reason"] == "HELD_NONORDINARY_RIGHTS_ISSUE"
    assert state.rights_entitlements == []


def test_primary_offer_price_conflict_stops_before_claim_creation():
    state = AccountState("MOM")
    state.lots.append(Lot("old", "CGCL", date(2023, 2, 1), 64, 6400, "FILL", 64))
    event, evidence = rights_evidence("capri", "CGCL", "2023-02-17",
                                      "2023-02-17", "2023-03-10", 11, 64, 475.0)
    event["rights_subscription_price"] = 474.0
    with pytest.raises(ValueError, match="Rights terms differ"):
        _apply_events(state, date(2023, 2, 17), [event], {}, [], [], evidence)
    assert state.rights_entitlements == []


@pytest.mark.parametrize("account,dhani,unominda", [("MOM", 216, 15), ("VM", 120, 7)])
def test_new_scenario_outputs_are_reconciled_and_keep_rights_unpriced(account, dhani, unominda):
    summary = pd.read_csv(OUT / "account_run_summary.csv").set_index("account").loc[account]
    assert summary.scenario == "PASSIVE_LAPSE_RIGHTS_SCENARIO"
    assert summary.last_valid_date == "2021-05-10"
    assert summary.valid_daily_nav_rows == 1510
    assert summary.max_nav_reconciliation_error < 1e-6
    assert summary.maximum_value_bearing_market_date_read == str(CUTOFF.date())

    rights = pd.read_parquet(OUT / f"{account}_rights_entitlements.parquet")
    assert rights.new_share_entitlement.tolist() == [dhani, unominda]
    assert rights.status.eq("LAPSED_UNEXERCISED").all()
    assert rights.account_claim_value.isna().all()
    assert rights.realised_sale_proceeds.eq(0).all()
    nav = pd.read_parquet(OUT / f"{account}_nav_daily.parquet")
    assert nav.unpriced_rights_count.gt(0).sum() == 33
    assert nav.loc[nav.unpriced_rights_count.gt(0), "nav_status"].eq(
        "PASSIVE_LAPSE_UNPRICED_RIGHT_EXCLUDED").all()
    assert nav.reconciliation_error.abs().max() < 1e-6
    cash = pd.read_parquet(OUT / f"{account}_cash_events.parquet")
    assert not cash.event_id.isin(rights.event_id).any()


def test_batch_rights_evidence_is_complete_and_flags_complex_or_conflicting_terms():
    evidence = pd.read_csv(OUT.parent / "rights_candidate_scan.csv")
    assert len(evidence) == 26
    assert evidence.event_id.is_unique
    assert evidence.close_evidence_level.value_counts().to_dict() == {
        "FINAL_OFFER_SCHEDULE": 11, "POST_CLOSE_CONFIRMATION": 15,
    }
    assert evidence.loc[evidence.close_evidence_level.eq("POST_CLOSE_CONFIRMATION"),
                        "verification_status"].eq("VERIFIED_PRIMARY").all()
    assert evidence.loc[evidence.close_evidence_level.eq("FINAL_OFFER_SCHEDULE"),
                        "verification_status"].eq("PRIMARY_TERMS_SCHEDULED_CLOSE_ONLY").all()
    assert evidence[["ratio_a", "ratio_b", "record_date", "issue_close_date",
                     "fractional_policy", "primary_evidence_url",
                     "fractional_evidence_url"]].notna().all().all()
    assert evidence.loc[evidence.symbol.eq("CGCL"), "accepted_price_mismatch"].iloc[0] == "YES"
    assert evidence.loc[evidence.symbol.eq("SPARC"), "issue_close_date"].iloc[0] == "2016-04-13"
    assert set(evidence.loc[~evidence.ordinary_status.eq("ORDINARY_VERIFIED"),
                        "symbol"]) == {"SINTEX", "TATASTEEL"}
    assert evidence.loc[evidence.symbol.eq("TATASTEEL"), "issue_structure_detail"].iloc[0]

    winners = pd.read_parquet(
        "data/processed/momentum_winners.parquet",
        columns=["formation_date", "security_id", "scored"],
        filters=[("formation_date", "<=", CUTOFF), ("scored", "=", True)],
    )
    first_selection = winners.groupby("security_id").formation_date.min()
    events = pd.read_csv("results/stock_total_return_audit/event_application_detail.csv",
                         parse_dates=["ex_date"])
    possible = events.loc[
        events.ex_date.between("2015-04-01", CUTOFF)
        & events.primary_class.eq("RIGHTS")
        & events.security_id.isin(first_selection.index)
    ]
    possible = possible.loc[
        possible.apply(lambda row: first_selection[row.security_id] < row.ex_date, axis=1)
    ]
    assert set(evidence.event_id) == set(possible.event_id)


def test_fractional_split_failure_does_not_partially_change_lots():
    state = AccountState("MOM")
    state.lots.append(Lot("even", "X", date(2020, 1, 1), 4, 400, "FILL", 4))
    state.lots.append(Lot("odd", "X", date(2020, 2, 1), 1, 100, "FILL", 1))
    with pytest.raises(ValueError, match="Fractional split"):
        _apply_split(state, "X", 2.5)
    assert [(lot.quantity, lot.settled_quantity) for lot in state.lots] == [(4, 4), (1, 1)]
