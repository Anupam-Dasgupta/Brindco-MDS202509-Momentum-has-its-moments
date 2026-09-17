import copy
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from account_engine import AccountState
from development_accounts import (
    ALKYLAMINE_SECURITY, ALKYLAMINE_SPLIT, CUTOFF, ROOT,
    _apply_alkylamine_split, _apply_events,
)
from tax_model import Lot, consume_fifo


OLD = ROOT / "results/accounts_development/passive_lapse_rights_scenario"
NEW = ROOT / "results/accounts_development/passive_lapse_rights_alkylamine_cil_scenario"


def old_lots(account):
    snapshot = json.loads((OLD / f"{account}_state.json").read_text())
    return [Lot(row["lot_id"], row["security_id"], date.fromisoformat(row["acquired"]),
                row["quantity"], row["basis"], row["basis_provenance"],
                row["settled_quantity"])
            for row in snapshot["lots"] if row["security_id"] == ALKYLAMINE_SECURITY]


@pytest.mark.parametrize("account,old_quantity,whole_quantity,fraction", [
    ("MOM", 46, 115, 0), ("VM", 19, 47, 0.5),
])
def test_account_level_split_preserves_wealth_and_lot_lineage(
        account, old_quantity, whole_quantity, fraction):
    state = AccountState(account)
    state.lots = old_lots(account)
    original = {lot.lot_id: (lot.acquired, lot.basis) for lot in state.lots}
    original_basis = sum(lot.basis for lot in state.lots)
    assert state.owned(ALKYLAMINE_SECURITY) == old_quantity

    claim = _apply_alkylamine_split(state, date(2021, 5, 11))

    assert state.owned(ALKYLAMINE_SECURITY) == whole_quantity
    assert state.settled(ALKYLAMINE_SECURITY) == whole_quantity
    assert sum(lot.quantity for lot in state.lots) == whole_quantity
    assert sum(lot.basis for lot in state.lots) + (
        claim["allocated_basis"] if claim else 0) == pytest.approx(original_basis)
    assert all(lot.acquired == original[lot.lot_id][0] for lot in state.lots)
    assert all(lot.quantity == lot.settled_quantity for lot in state.lots)
    assert len(state.fractional_split_claims) == int(bool(fraction))
    if fraction:
        assert claim["fractional_quantity"] == fraction
        assert claim["ex_date"] == date(2021, 5, 11)
        assert claim["entitlement_date"] == date(2021, 5, 12)
        assert claim["original_acquisition_date"] == date(2020, 11, 3)
        assert claim["allocated_basis"] == pytest.approx(original[claim["original_lot_id"]][1] / 5)
        assert claim["gross_proceeds"] is None
        assert claim["net_proceeds"] is None
        assert claim["payment_date"] is None
        assert claim["spendable_cash"] == 0
        assert claim["account_value"] is None
    else:
        assert claim is None
    assert state.cash == 10_000_000


def test_fractional_tax_lots_do_not_create_extra_economic_claims():
    state = AccountState("MOM")
    state.lots = [Lot("a", ALKYLAMINE_SECURITY, date(2020, 1, 1), 1, 100, "FILL", 1),
                  Lot("b", ALKYLAMINE_SECURITY, date(2020, 2, 1), 1, 200, "FILL", 1)]
    assert _apply_alkylamine_split(state, date(2021, 5, 11)) is None
    assert [lot.quantity for lot in state.lots] == [2.5, 2.5]
    assert state.owned(ALKYLAMINE_SECURITY) == 5
    assert state.fractional_split_claims == []

    gains = consume_fifo(state.lots, ALKYLAMINE_SECURITY, 3, date(2021, 6, 1), 600, "sale")
    assert sum(row["quantity"] for row in gains) == 3
    assert state.owned(ALKYLAMINE_SECURITY) == 2
    assert sum(lot.basis for lot in state.lots) + sum(row["basis"] for row in gains) == pytest.approx(300)


def test_alkylamine_event_integration_is_account_level_and_does_not_book_cash():
    state = AccountState("VM")
    state.lots = old_lots("VM")
    event = {"event_id": ALKYLAMINE_SPLIT, "security_id": ALKYLAMINE_SECURITY,
             "primary_class": "SPLIT", "share_effect": 2.5, "cash_effect": 0,
             "application_status": "APPLIED_TO_RETURN"}
    audit, cash = [], []
    blocker = _apply_events(state, date(2021, 5, 11), [event], {}, audit, cash,
                            enable_alkylamine_cil=True)
    assert blocker is None
    assert state.owned(ALKYLAMINE_SECURITY) == 47
    assert state.fractional_split_claims[0]["fractional_quantity"] == 0.5
    assert cash == []
    assert audit[0]["status"] == "ACCOUNT_LEVEL_SPLIT_WITH_CIL"


def test_alkylamine_split_failure_is_atomic():
    state = AccountState("VM")
    state.lots = old_lots("VM")
    state.lots[-1].settled_quantity = 0
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="fully settled"):
        _apply_alkylamine_split(state, date(2021, 5, 11))
    assert state == before


def test_continuation_output_keeps_frozen_prefix_and_visible_claim():
    summary_path = NEW / "account_run_summary.csv"
    if not summary_path.exists():
        pytest.skip("Continuation has not yet been run")
    summary = pd.read_csv(summary_path).set_index("account")
    for account in ("MOM", "VM"):
        new = pd.read_parquet(NEW / f"{account}_nav_daily.parquet")
        for old_dir, count in ((ROOT / "results/accounts_development", 709),
                               (ROOT / "results/accounts_development/passive_lapse", 1327),
                               (OLD, 1510)):
            old = pd.read_parquet(old_dir / f"{account}_nav_daily.parquet")
            assert len(old) == count
            columns = old.columns if old_dir == OLD else old.columns.drop("input_manifest_hash")
            pd.testing.assert_frame_equal(new.iloc[:count][columns].reset_index(drop=True),
                                          old[columns].reset_index(drop=True))
        assert summary.loc[account, "maximum_value_bearing_market_date_read"] == str(CUTOFF.date())
        assert new.date.max() <= CUTOFF.date()
        assert (new.settled_cash >= -1e-6).all()
        assert (new.free_cash >= -1e-6).all()
        assert new.reconciliation_error.abs().max() < 1e-6
        event = pd.read_parquet(NEW / f"{account}_held_event_audit.parquet")
        split = event.loc[event.event_id.eq(ALKYLAMINE_SPLIT)]
        assert len(split) == 1
        assert split.ordinary_share_quantity.iloc[0] == (115 if account == "MOM" else 47)
        cash = pd.read_parquet(NEW / f"{account}_cash_events.parquet")
        assert not cash.event_id.eq(ALKYLAMINE_SPLIT).any()
        positions = pd.read_parquet(NEW / f"{account}_positions.parquet")
        assert (positions.owned_shares >= 0).all()
        assert (positions.settled_shares >= 0).all()
        assert positions.owned_shares.mod(1).eq(0).all()
        assert positions.settled_shares.mod(1).eq(0).all()
    assert summary.loc["MOM", "unpriced_fractional_split_claim_count"] == 0
    assert summary.loc["VM", "unpriced_fractional_split_claim_count"] == 1
    claims = pd.read_parquet(NEW / "VM_fractional_split_claims.parquet")
    assert len(claims) == 1 and claims.fractional_quantity.iloc[0] == 0.5
    vm_nav = pd.read_parquet(NEW / "VM_nav_daily.parquet")
    assert vm_nav.loc[vm_nav.date.ge(date(2021, 5, 11)), "nav_status"].eq(
        "UNPRICED_FRACTIONAL_SPLIT_CLAIM_EXCLUDED").all()


def test_earlier_account_output_files_remain_byte_identical():
    baseline = NEW / "frozen_account_hashes_before.csv"
    if not baseline.exists():
        pytest.skip("Baseline account hashes not yet recorded")
    for row in pd.read_csv(baseline).itertuples(index=False):
        path = ROOT / Path(row.path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row.sha256
