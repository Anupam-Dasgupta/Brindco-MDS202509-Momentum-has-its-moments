from datetime import date

import pandas as pd
import pytest

from brindco_momentum.execution.development_accounts import ROOT, UNOMINDA_2018_BONUS


FINAL = ROOT / "results/accounts_development/frozen_corporate_action_scenario"
DIAGNOSTIC = ROOT / "results/accounts_development/unominda2018_lifecycle_scenario"


@pytest.mark.parametrize("account", ["MOM", "VM"])
def test_completed_account_keeps_frozen_economic_replay(account):
    if not (FINAL / "account_run_summary.csv").exists():
        pytest.skip("Final development account replay has not finished")
    summary = pd.read_csv(FINAL / "account_run_summary.csv").set_index("account")
    assert summary.loc[account, "last_valid_date"] == "2023-03-31"
    assert summary.loc[account, "valid_daily_nav_rows"] == 1982
    assert pd.isna(summary.loc[account, "blocker"])
    assert summary.loc[account, "maximum_value_bearing_market_date_read"] == "2023-03-31"
    final_nav = pd.read_parquet(FINAL / f"{account}_nav_daily.parquet")
    diagnostic_nav = pd.read_parquet(DIAGNOSTIC / f"{account}_nav_daily.parquet")
    pd.testing.assert_frame_equal(final_nav.drop(columns="input_manifest_hash"),
                                  diagnostic_nav.drop(columns="input_manifest_hash"))
    assert final_nav.date.max() == date(2023, 3, 31)
    assert final_nav.reconciliation_error.abs().max() < 1e-6
    event = pd.read_parquet(FINAL / f"{account}_held_event_audit.parquet")
    lifecycle = event.loc[event.event_id.eq(UNOMINDA_2018_BONUS)]
    assert {"BONUS_AND_PRE_BONUS_DIVIDEND_RECOGNISED",
            "BONUS_ALLOTTED_UNDELIVERABLE",
            "BONUS_DELIVERABLE_ZERO_BASIS_LOT"} <= set(lifecycle.status)
