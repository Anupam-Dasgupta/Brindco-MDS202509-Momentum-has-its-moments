import hashlib

import numpy as np
import pandas as pd

from brindco_momentum.signals.momentum_signal import CUTOFF, FORMATIONS_OUTPUT, MONTHLY_OUTPUT, PANEL, RETURNS, WINNERS_OUTPUT
from brindco_momentum.portfolio.shadow_portfolio import simulate_shadow
from brindco_momentum.portfolio.zero_entitlement_sensitivity import AUDIT, SENSITIVITY


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


def test_primary_files_are_unmodified_and_sensitivity_is_separate():
    hashes = pd.read_csv(AUDIT.parent / "event_resolution/artifact_hashes.csv")
    for path in [RETURNS, PANEL, MONTHLY_OUTPUT, FORMATIONS_OUTPUT, WINNERS_OUTPUT]:
        revision = hashes.loc[hashes.artifact.eq(str(path.relative_to(AUDIT.parent.parent)).replace("\\", "/"))]
        assert len(revision) == 1
        assert hashlib.sha256(path.read_bytes()).hexdigest() == revision.iloc[0].after_sha256
    primary = pd.read_parquet(FORMATIONS_OUTPUT)
    scenario = pd.read_parquet(SENSITIVITY / "zero_entitlement_formations.parquet")
    assert len(primary) == len(scenario)
    assert primary.formation_date.max() <= CUTOFF
    assert scenario.formation_date.max() <= CUTOFF
    changes = pd.read_csv(AUDIT / "primary_vs_zero_signal_changes.csv")
    assert changes.primary_n.ne(changes.sensitivity_n).sum() == 71
    assert changes.primary_k.ne(changes.sensitivity_k).sum() == 18
    assert changes.restored_event_winners.dropna().tolist() == ["TATACOMM"]
    assert scenario.loc[scenario.signal_exclusion_reason.eq("BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW")].shape[0] == 8
    seats = scenario.groupby("formation_date").eligible.sum()
    winners = pd.read_parquet(SENSITIVITY / "zero_entitlement_winners.parquet")
    assert winners.groupby("formation_date").size().eq(np.ceil(seats / 10)).all()
    sensitivity_monthly = pd.read_parquet(SENSITIVITY / "zero_entitlement_monthly_features.parquet")
    unrelated = sensitivity_monthly.loc[
        sensitivity_monthly.security_id.eq("NSE_42CD50DCCBD6")
        & sensitivity_monthly.month.eq(pd.Period("2018-04"))
    ].iloc[0]
    assert not unrelated.complete
    assert "CA_09d4133ad6ad9024fa83" in unrelated.unavailable_event_ids


def test_actual_shadow_warmup_and_daily_blocker_are_explicit():
    daily = pd.read_parquet(AUDIT.parent.parent / "data/processed/primary_shadow_daily_returns.parquet")
    holdings = pd.read_parquet(AUDIT.parent.parent / "data/processed/primary_shadow_holdings.parquet")
    materiality = pd.read_csv(AUDIT / "unavailable_daily_return_materiality.csv")
    assert daily.date.min() == pd.Timestamp("2014-09-01")
    assert daily.date.max() == pd.Timestamp("2018-04-05")
    assert daily.loc[daily.date.le(pd.Timestamp("2015-03-31")), "valid_return"].sum() == 142
    assert daily.iloc[-1].blocker_reason == "SHADOW_DAILY_RETURN_BLOCKER"
    assert pd.isna(daily.iloc[-1].shadow_daily_return)
    held = materiality.loc[materiality.materiality_status.eq("SHADOW_DAILY_RETURN_BLOCKER")]
    assert len(held) == 1 and held.iloc[0].symbol == "ADANIENT"
    assert np.isclose(held.iloc[0].pre_event_weight, 0.018914, atol=1e-6)
    assert holdings.date.max() == pd.Timestamp("2018-04-04")
    assert not holdings.duplicated(["date", "security_id"]).any()
    assert holdings.units.gt(0).all()
    weights = holdings.groupby("date").portfolio_weight.sum()
    assert np.allclose(weights, 1.0)
    marked = holdings.groupby("date").market_value.sum()
    valid_nav = daily.loc[daily.valid_return].set_index("date").shadow_nav_index
    assert np.allclose(marked.loc[valid_nav.index], valid_nav)
    strict = materiality.loc[materiality.symbol.isin(["BLUEDART", "NTPC", "BRITANNIA"])]
    assert strict.materiality_status.value_counts().to_dict() == {
        "NOT_HELD": 2, "NOT_ASSESSABLE_AFTER_FIRST_BLOCKER": 2,
    }
