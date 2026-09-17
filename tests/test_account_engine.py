from datetime import date

import pytest

from brindco_momentum.execution.account_engine import (
    AccountState, affordable_buy_quantity, fill_terms, participation_cap_shares,
    recognise_bonus, recognise_dividend, rights_materiality, settle_due,
    settlement_after, target_shares,
)
from brindco_momentum.execution.tax_model import Lot


def test_whole_share_targets_and_capacity_use_lagged_adv():
    assert target_shares(1999.0, 100.0) == 19
    assert participation_cap_shares(1_000_000.0, 100.0) == 100
    assert participation_cap_shares(float("nan"), 100.0) == 0
    with pytest.raises(ValueError, match="cap"):
        fill_terms("BUY", 101, 100.0, 1_000_000.0)


def test_impact_is_in_fill_price_once_and_fixed_costs_are_separate():
    buy = fill_terms("BUY", 100, 100.0, 100_000_000.0)
    sell = fill_terms("SELL", 100, 100.0, 100_000_000.0)
    assert buy["impact_bps"] == 10.0
    assert buy["fill_price"] == pytest.approx(100.1)
    assert sell["fill_price"] == pytest.approx(99.9)
    assert buy["fees"] / buy["consideration"] * 10_000 == pytest.approx(11.927)
    assert sell["fees"] / sell["consideration"] * 10_000 == pytest.approx(10.427)
    assert 10 + 11.927 == pytest.approx(21.927)
    assert 10 + 10.427 == pytest.approx(20.427)
    assert 21.927 + 20.427 == pytest.approx(42.354)
    assert buy["cash_flow"] == pytest.approx(-(buy["consideration"] + buy["fees"]))
    assert buy["deductible_fees"] == pytest.approx(buy["fees"] - buy["stt"])
    assert sell["deductible_fees"] == pytest.approx(sell["fees"] - sell["stt"])
    assert buy["impact_rupees"] == pytest.approx(10.0)


def test_impact_scales_with_actual_participation():
    fill = fill_terms("BUY", 100, 100.0, 1_000_000.0)
    assert fill["participation"] == pytest.approx(0.01)
    assert fill["impact_bps"] == pytest.approx(10 * (0.01 / 0.001) ** 0.5)


def test_purchase_affordability_includes_impacted_price_and_fees():
    one = fill_terms("BUY", 1, 100.0, 1_000_000.0)
    assert affordable_buy_quantity(10, -one["cash_flow"] - 0.01, 100.0, 1_000_000.0) == 0
    assert affordable_buy_quantity(10, -one["cash_flow"], 100.0, 1_000_000.0) == 1
    assert affordable_buy_quantity(1000, 1_000_000.0, 100.0, 1_000_000.0) == 100


def test_t_plus_two_skips_separate_settlement_holiday():
    # Friday bank holiday is excluded even though it is a weekday.
    dates = [date(2022, 3, 30), date(2022, 3, 31), date(2022, 4, 4), date(2022, 4, 5)]
    assert settlement_after(date(2022, 3, 30), dates) == date(2022, 4, 4)
    with pytest.raises(ValueError, match="unavailable"):
        settlement_after(date(2022, 4, 4), dates)


def test_sale_and_dividend_claims_are_nav_assets_but_not_free_cash():
    state = AccountState("MOM", cash=500)
    state.sale_receivables.append({"amount": 1000, "settlement_date": date(2022, 4, 4)})
    state.lots.append(Lot("l1", "A", date(2022, 3, 1), 10, 100, "FILL", 10))
    recognise_dividend(state, "d1", "A", 2, None)
    assert state.nav({"A": 10}) == pytest.approx(1620)
    assert state.free_cash() == pytest.approx(500)
    assert affordable_buy_quantity(100, state.free_cash(), 100, 1_000_000) == 4
    settle_due(state, date(2022, 4, 1))
    assert state.free_cash() == pytest.approx(500)
    settle_due(state, date(2022, 4, 4))
    assert state.free_cash() == pytest.approx(1500)
    assert affordable_buy_quantity(100, state.free_cash(), 100, 1_000_000) == 14
    assert len(state.dividend_receivables) == 1
    assert state.dividend_receivables[0]["status"] == "UNSPENDABLE_PENDING_PAYMENT"


def test_bonus_claim_is_valued_but_not_sellable_without_evidenced_credit():
    state = AccountState("VM", cash=0)
    state.lots.append(Lot("l1", "A", date(2022, 1, 1), 10, 100, "FILL", 10))
    recognise_bonus(state, "b1", "A", 1, None)
    assert state.nav({"A": 5}) == pytest.approx(100)
    assert state.owned("A") == state.settled("A") == 10
    assert state.bonus_entitlements[0]["tax_holding_start"] is None


def test_unexposed_right_does_nothing_but_held_right_blocks():
    state = AccountState("MOM")
    assert rights_materiality(state, "DHANI") == {"status": "ACCOUNT_NOT_EXPOSED", "held_quantity": 0}
    state.lots.append(Lot("l1", "DHANI", date(2017, 4, 1), 7, 700, "FILL", 7))
    assert rights_materiality(state, "DHANI") == {"status": "UNRESOLVED_HELD_RIGHTS_NAV", "held_quantity": 7}
    assert state.cash == 10_000_000
