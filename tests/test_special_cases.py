import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from brindco_momentum.execution.account_engine import AccountState
from brindco_momentum.execution.development_accounts import _apply_events, _recognise_received_listing
from brindco_momentum.execution.holdout_accounts import OPENING_STATES, load_account_common
from brindco_momentum.execution.tax_model import Lot


UPL_BONUS = "CA_0590fadd12feff0aaf91"
UPL = "NSE_A707E895DC5D"
UPL_RIGHTS = "HCA_33631a085484241f22c3"
VAKRANGEE = "NSE_7F648FED7CF8"
VLEGOV = "NSE_82510223B25A"
VAKRANGEE_DEMERGER = "HCA_583d085a207d7e2c01c7"


def test_upl_fractional_claim_is_not_a_share_and_confers_no_rights():
    opening = json.loads(OPENING_STATES["VM"].read_text(encoding="utf-8"))
    bonus_lot = next(row for row in opening["lots"] if row["lot_id"] == "VM-CA_0590fadd12feff0aaf91-ALLOTTED_BONUS")
    claim = opening["fractional_bonus_claims"]
    assert bonus_lot["quantity"] == 111 and bonus_lot["basis"] == 0
    assert bonus_lot["acquired"] == "2019-07-04"
    assert len(claim) == 1 and claim[0]["fractional_quantity"] == 0.5

    common = load_account_common("test")
    event = next(row for row in common["events"][date(2024, 11, 26)]
                 if row["event_id"] == UPL_RIGHTS)
    state = AccountState(
        "VM",
        lots=[Lot(**{**bonus_lot, "acquired": date(2019, 7, 4)})],
        fractional_bonus_claims=claim,
    )
    assert _apply_events(state, date(2024, 11, 26), [event], {UPL: 500.0}, [], [],
                         common["rights"]) is None
    assert state.rights_entitlements[0]["pre_event_shares"] == 111
    assert state.rights_entitlements[0]["new_share_entitlement"] == 13
    assert state.fractional_bonus_claims == claim


def test_vakrangee_received_security_is_unpriced_until_first_quote():
    common = load_account_common("test")
    event = next(row for row in common["events"][date(2023, 6, 15)]
                 if row["event_id"] == VAKRANGEE_DEMERGER)
    state = AccountState("TEST", lots=[
        Lot("parent", VAKRANGEE, date(2022, 1, 3), 15, 1500.0, "TEST", 15)
    ])
    marks = {VAKRANGEE: 20.0}
    assert _apply_events(
        state, date(2023, 6, 15), [event], marks, [], [], common["rights"],
        received_evidence=common["received_security_evidence"],
    ) is None
    assert state.owned(VLEGOV) == 1 and state.settled(VLEGOV) == 0
    assert marks[VLEGOV] == 0
    assert state.fractional_received_claims[0]["fractional_quantity"] == pytest.approx(0.5)
    _recognise_received_listing(state, date(2023, 8, 11), {}, [])
    assert state.settled(VLEGOV) == 0
    quote = SimpleNamespace(market_observed=True, market_data_status="OK", series="BE", close=29.5)
    _recognise_received_listing(state, date(2023, 8, 14), {VLEGOV: quote}, [])
    assert state.settled(VLEGOV) == 1
    assert state.received_security_claims[0]["first_observable_price_date"] == date(2023, 8, 14)


def test_final_outputs_match_submitted_metrics_and_figures():
    from brindco_momentum.paths import ROOT

    summary = pd.read_csv(ROOT / "results/holdout_summary.csv").set_index("account")
    expected = {
        "MOM": (38.23e6, 0.2471, 0.2105, 1.17, -0.2494),
        "VM": (23.17e6, 0.1605, 0.1508, 1.08, -0.1581),
        "FIX": (27.68e6, 0.1780, 0.1609, 1.12, -0.1922),
        "FIXVOL": (28.77e6, 0.1845, 0.1682, 1.11, -0.2005),
    }
    for name, values in expected.items():
        row = summary.loc[name]
        assert row.final_nav == pytest.approx(values[0], abs=5_000)
        assert row.cagr == pytest.approx(values[1], abs=0.00005)
        assert row.annualised_volatility == pytest.approx(values[2], abs=0.00005)
        assert row.sharpe_0pct_cash == pytest.approx(values[3], abs=0.005)
        assert row.max_drawdown == pytest.approx(values[4], abs=0.00005)
    assert summary.nifty500_tri_cagr.iloc[0] == pytest.approx(0.1323, abs=0.00005)
    figures = ROOT / "results/final_figures"
    assert {path.name for path in figures.glob("*.png")} == {
        "01_cumulative_wealth.png",
        "02_holdout_drawdowns.png",
        "03_volatility_overlay_mechanism.png",
        "04b_holdout_cost_tax_drag.png",
    }
