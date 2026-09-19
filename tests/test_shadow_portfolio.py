import numpy as np
import pandas as pd

from brindco_momentum.signals.momentum_signal import CUTOFF, FORMATIONS_OUTPUT, MONTHLY_OUTPUT, PANEL, RETURNS, WINNERS_OUTPUT
from brindco_momentum.portfolio.shadow_portfolio import simulate_shadow


def small_shadow_inputs():
    dates = pd.to_datetime(["2014-08-28", "2014-09-01", "2014-09-02", "2014-09-30", "2014-10-01"])
    calendar = pd.DataFrame({"date": dates, "next_trading_day": [*dates[1:], pd.NaT]})
    winners = pd.DataFrame({
        "formation_date": [dates[0], dates[0], dates[3]],
        "security_id": ["A", "B", "C"],
    })
    observations = {
        dates[1]: [("A", 100.0, 110.0, 0.10), ("B", 100.0, 100.0, 0.0), ("C", 150.0, 150.0, 0.0)],
        dates[2]: [("A", 110.0, 121.0, 0.10), ("B", 100.0, 100.0, 0.0), ("C", 150.0, 150.0, 0.0)],
        dates[3]: [("A", 121.0, 121.0, 0.0), ("B", 100.0, 100.0, 0.0), ("C", 150.0, 150.0, 0.0)],
        dates[4]: [("A", 133.1, 133.1, 0.10), ("B", 100.0, 100.0, 0.0), ("C", 200.0, 220.0, 220 / 150 - 1)],
    }
    rows = []
    for date, values in observations.items():
        for security_id, open_price, close, daily_return in values:
            rows.append({
                "date": date, "security_id": security_id, "symbol": security_id,
                "series": "EQ", "open": open_price, "close": close,
                "market_observed": True, "market_data_status": "OK", "identity_status": "RESOLVED",
                "daily_total_return": daily_return, "total_return_available": True,
                "exclusion_reason": "", "all_event_ids": "",
                "cash_effect": 0.0, "share_effect": 1.0, "entitlement_effect": 0.0,
            })
    return calendar, winners, pd.DataFrame(rows)


def test_shadow_rebalance_open_chronology_fractional_units_and_drift():
    calendar, winners, market = small_shadow_inputs()
    holdings, daily, rebalances, _ = simulate_shadow(calendar, winners, market)
    first = holdings.loc[holdings.date.eq(pd.Timestamp("2014-09-01"))].set_index("security_id")
    assert np.isclose(first.loc["A", "units"], 0.005)
    assert np.isclose(first.loc["B", "units"], 0.005)
    assert np.isclose(first.loc["A", "units"] * 100, first.loc["B", "units"] * 100)
    assert first.loc["A", "portfolio_weight"] > 0.5  # Weights drift by that close.
    second = holdings.loc[holdings.date.eq(pd.Timestamp("2014-09-02"))].set_index("security_id")
    assert second.loc["A", "portfolio_weight"] > first.loc["A", "portfolio_weight"]
    assert "C" not in set(holdings.loc[holdings.date.lt(pd.Timestamp("2014-10-01")), "security_id"])

    last = rebalances.iloc[-1]
    expected_open = 0.005 * 133.1 + 0.005 * 100
    assert np.isclose(last.opening_nav, expected_open)
    assert np.isclose(last.closing_nav, expected_open * 220 / 200)
    assert np.isclose(daily.iloc[-1].shadow_daily_return, last.closing_nav / last.prior_close_nav - 1)
    pd.testing.assert_frame_equal(daily, simulate_shadow(calendar, winners, market)[1])


def test_old_holder_gets_split_and_cash_before_rebalance_open():
    calendar, winners, market = small_shadow_inputs()
    mask = market.date.eq(pd.Timestamp("2014-10-01")) & market.security_id.eq("A")
    market.loc[mask, ["open", "close", "share_effect", "cash_effect"]] = [60.0, 65.0, 2.0, 5.0]
    market.loc[mask, "daily_total_return"] = (2 * 65 + 5) / 121 - 1
    _, daily, rebalances, _ = simulate_shadow(calendar, winners, market)
    assert daily.valid_return.all()
    assert np.isclose(rebalances.iloc[-1].opening_nav, 0.005 * (2 * 60 + 5) + 0.005 * 100)


def test_held_unavailable_daily_return_stops_without_zero_fill():
    calendar, winners, market = small_shadow_inputs()
    mask = market.date.eq(pd.Timestamp("2014-09-02")) & market.security_id.eq("A")
    market.loc[mask, "total_return_available"] = False
    market.loc[mask, "daily_total_return"] = np.nan
    market.loc[mask, "all_event_ids"] = "E"
    market.loc[mask, "exclusion_reason"] = "TREATMENT_NOT_ACCEPTED"
    _, daily, rebalances, materiality = simulate_shadow(calendar, winners, market)
    assert len(daily) == 2 and len(rebalances) == 1
    assert not daily.iloc[-1].valid_return and pd.isna(daily.iloc[-1].shadow_daily_return)
    blocked = materiality.loc[materiality.materiality_status.eq("SHADOW_DAILY_RETURN_BLOCKER")]
    assert len(blocked) == 1 and blocked.iloc[0].held_before_event
    assert blocked.iloc[0].pre_event_weight > 0


def test_missing_open_and_unvalued_open_entitlement_block_rebalance():
    calendar, winners, market = small_shadow_inputs()
    mask = market.date.eq(pd.Timestamp("2014-09-01")) & market.security_id.eq("A")
    market.loc[mask, "open"] = np.nan
    _, daily, _, materiality = simulate_shadow(calendar, winners, market)
    assert len(daily) == 1 and not daily.iloc[0].valid_return
    assert daily.iloc[0].blocker_reason == "SELECTED_OPEN_OR_CLOSE_MISSING"
    assert materiality.iloc[0].materiality_status == "SELECTED_OPEN_OR_CLOSE_MISSING"

    calendar, winners, market = small_shadow_inputs()
    mask = market.date.eq(pd.Timestamp("2014-10-01")) & market.security_id.eq("A")
    market.loc[mask, "entitlement_effect"] = 5.0
    market.loc[mask, "daily_total_return"] = (133.1 + 5) / 121 - 1
    _, daily, rebalances, _ = simulate_shadow(calendar, winners, market)
    assert daily.iloc[-1].blocker_reason == "ENTITLEMENT_OPEN_VALUE_UNEVIDENCED"
    assert len(rebalances) == 1


