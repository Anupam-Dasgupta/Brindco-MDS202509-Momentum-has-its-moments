from datetime import date

import pytest

from brindco_momentum.execution.account_engine import AccountState
from brindco_momentum.execution.development_accounts import (
    UNOMINDA_2018_BONUS, UNOMINDA_SECURITY, _advance_unominda_2018,
    _apply_events,
)
from brindco_momentum.execution.tax_model import Lot, consume_fifo


def test_bonus_and_dividend_are_distinct_and_bonus_becomes_sellable():
    state = AccountState("MOM")
    state.lots.append(Lot("old", UNOMINDA_SECURITY, date(2018, 5, 1), 10,
                          1000.0, "FILL", 10))
    event = {"event_id": UNOMINDA_2018_BONUS,
             "security_id": UNOMINDA_SECURITY, "primary_class": "BONUS",
             "application_status": "APPLIED_TO_RETURN", "share_effect": 3.0,
             "cash_effect": 1.6}
    audit, cash = [], []

    assert _apply_events(state, date(2018, 7, 11), [event], {}, audit, cash,
                         enable_unominda_2018=True) is None
    assert state.economic_units(UNOMINDA_SECURITY) == 30
    assert state.settled(UNOMINDA_SECURITY) == 10
    assert state.dividend_receivables[0]["amount"] == pytest.approx(16)
    assert state.dividend_receivables[0]["payment_date"] is None
    assert state.bonus_entitlements[0]["tax_holding_start"] is None
    assert cash[0]["amount"] == pytest.approx(16)

    _advance_unominda_2018(state, date(2018, 7, 13), audit)
    assert state.bonus_entitlements[0]["tax_holding_start"] == date(2018, 7, 13)
    assert state.settled(UNOMINDA_SECURITY) == 10
    _advance_unominda_2018(state, date(2018, 7, 20), audit)
    assert state.settled(UNOMINDA_SECURITY) == 10
    _advance_unominda_2018(state, date(2018, 7, 23), audit)
    assert state.economic_units(UNOMINDA_SECURITY) == 30
    assert state.settled(UNOMINDA_SECURITY) == 30
    assert not state.bonus_entitlements
    bonus = next(lot for lot in state.lots if lot.lot_id.endswith("-BONUS"))
    assert (bonus.acquired, bonus.quantity, bonus.basis) == (date(2018, 7, 13), 20, 0)
    assert sum(lot.basis for lot in state.lots) == 1000

    realised = consume_fifo(state.lots, UNOMINDA_SECURITY, 30,
                            date(2018, 8, 1), 1500.0, "sale")
    assert state.economic_units(UNOMINDA_SECURITY) == 0
    assert sum(row["basis"] for row in realised) == pytest.approx(1000)
    assert sum(row["quantity"] for row in realised) == 30


def test_unominda_terms_mismatch_fails_before_mutation():
    state = AccountState("VM")
    state.lots.append(Lot("old", UNOMINDA_SECURITY, date(2018, 5, 1), 2,
                          100.0, "FILL", 2))
    event = {"event_id": UNOMINDA_2018_BONUS,
             "security_id": UNOMINDA_SECURITY, "primary_class": "BONUS",
             "application_status": "APPLIED_TO_RETURN", "share_effect": 2.0,
             "cash_effect": 1.6}
    with pytest.raises(ValueError, match="accepted combined action"):
        _apply_events(state, date(2018, 7, 11), [event], {}, [], [],
                      enable_unominda_2018=True)
    assert state.economic_units(UNOMINDA_SECURITY) == 2
    assert state.dividend_receivables == []
