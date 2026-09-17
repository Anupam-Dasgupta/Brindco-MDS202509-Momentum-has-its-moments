from datetime import date

import pytest

from tax_model import Lot, compute_year_tax, consume_fifo, fiscal_year, holding_term


def test_fiscal_year_and_calendar_anniversary():
    assert fiscal_year(date(2022, 3, 31)) == 2021
    assert fiscal_year(date(2022, 4, 1)) == 2022
    assert holding_term(date(2020, 2, 29), date(2021, 2, 28)) == "ST"
    assert holding_term(date(2020, 2, 29), date(2021, 3, 1)) == "LT"
    assert holding_term(date(2021, 6, 1), date(2022, 6, 1)) == "ST"
    assert holding_term(date(2021, 6, 1), date(2022, 6, 2)) == "LT"


def test_fifo_partial_lot_uses_settled_shares_and_prorated_basis():
    lots = [
        Lot("L2", "S", date(2020, 2, 1), 10, 200.0, "BUY", 10),
        Lot("L1", "S", date(2020, 1, 1), 10, 100.0, "BUY", 10),
    ]
    realised = consume_fifo(lots, "S", 12, date(2021, 2, 2), 240.0, "F1")
    assert [r["lot_id"] for r in realised] == ["L1", "L2"]
    assert [r["quantity"] for r in realised] == [10, 2]
    assert [r["term"] for r in realised] == ["LT", "LT"]
    assert sum(r["gain"] for r in realised) == pytest.approx(100.0)
    assert lots[0].quantity == 8 and lots[0].basis == pytest.approx(160.0)
    assert lots[1].quantity == 0 and lots[1].basis == pytest.approx(0.0)
    with pytest.raises(ValueError, match="settled"):
        consume_fifo(lots, "S", 9, date(2021, 2, 2), 180.0, "F2")


def test_annual_lt_exemption_applies_once_to_year_to_date_gains():
    gains = [{"term": "LT", "gain": 100_000.0}, {"term": "LT", "gain": 100_000.0}]
    tax = compute_year_tax(gains, [], 2022)
    assert tax["exemption_used"] == 125_000.0
    assert tax["taxable_lt"] == 75_000.0
    assert tax["liability"] == pytest.approx(9_375.0)


def test_lt_loss_never_offsets_st_gain():
    tax = compute_year_tax([{"term": "ST", "gain": 100_000.0}],
                           [{"origin_fy": 2020, "term": "LT", "amount": 50_000.0}], 2022)
    assert tax["liability"] == pytest.approx(20_000.0)
    assert tax["closing_losses"] == [{"origin_fy": 2020, "term": "LT", "amount": 50_000.0}]


def test_recomputed_provision_does_not_consume_carried_loss_twice():
    pools = [{"origin_fy": 2020, "term": "ST", "amount": 30_000.0}]
    gains = [{"term": "ST", "gain": 20_000.0}]
    first = compute_year_tax(gains, pools, 2022)
    second = compute_year_tax(gains, pools, 2022)
    assert first == second
    assert pools == [{"origin_fy": 2020, "term": "ST", "amount": 30_000.0}]
    assert first["closing_losses"] == [{"origin_fy": 2020, "term": "ST", "amount": 10_000.0}]
    assert first["liability"] == 0


def test_loss_expires_after_eight_succeeding_financial_years():
    old = [{"origin_fy": 2015, "term": "ST", "amount": 100_000.0}]
    in_year_eight = compute_year_tax([{"term": "ST", "gain": 100_000.0}], old, 2023)
    in_year_nine = compute_year_tax([{"term": "ST", "gain": 100_000.0}], old, 2024)
    assert in_year_eight["liability"] == 0
    assert in_year_nine["liability"] == pytest.approx(20_000.0)
