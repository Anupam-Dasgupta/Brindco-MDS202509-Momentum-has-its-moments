import math

import numpy as np
import pandas as pd

from brindco_momentum.holdout_run import calculate_lagged_adv
from brindco_momentum.signals.momentum_signal import (
    attach_formation_observations,
    build_monthly,
    build_roster,
    rank_winners,
    usable_formation_quote,
)


def test_membership_roster_uses_half_open_intervals():
    dates = pd.to_datetime(["2015-01-30", "2015-02-27", "2015-03-31"])
    calendar = pd.DataFrame({"date": dates, "is_last_trading_day_of_month": True})
    ids = [f"S{i:03d}" for i in range(500)]
    membership = pd.DataFrame({
        "security_id": ids,
        "published_symbol": ids,
        "valid_from": pd.Timestamp("2014-01-01"),
        "valid_to": pd.NaT,
    })
    membership.loc[0, "valid_to"] = pd.Timestamp("2015-03-31")
    membership = pd.concat([membership, pd.DataFrame([{
        "security_id": "REPLACEMENT",
        "published_symbol": "REPLACEMENT",
        "valid_from": pd.Timestamp("2015-03-31"),
        "valid_to": pd.NaT,
    }])], ignore_index=True)
    roster = build_roster(membership, calendar, last_formation=pd.Period("2015-03"))
    assert roster.groupby("formation_date").size().eq(500).all()
    assert set(roster.loc[roster.formation_date.lt("2015-03-31"), "security_id"]) >= {"S000"}
    march = set(roster.loc[roster.formation_date.eq("2015-03-31"), "security_id"])
    assert "S000" not in march and "REPLACEMENT" in march


def test_adv_uses_preceding_twenty_sessions_only():
    panel = pd.DataFrame({
        "security_id": "A",
        "trading_day_number": np.arange(1, 22),
        "traded_value": [100.0] * 20 + [1_000_000.0],
        "volume": [1.0] * 21,
        "market_observed": True,
    })
    result = calculate_lagged_adv(panel)
    assert result.iloc[-1].adv20_observation_count == 20
    assert result.iloc[-1].positive_volume_sessions_20 == 20
    assert result.iloc[-1].adv20_lagged == 100.0


def test_missing_formation_row_remains_visible_and_ineligible():
    date = pd.Timestamp("2015-03-31")
    roster = pd.DataFrame({
        "formation_date": [date, date], "security_id": ["A", "B"],
        "published_symbol": ["AAA", "BBB"],
    })
    panel = pd.DataFrame({
        "date": [date], "security_id": ["A"], "is_formation_date": [True],
        "symbol": ["AAA"], "series": ["BE"], "close": [100.0],
        "market_observed": [True], "identity_status": ["RESOLVED"],
        "market_data_status": ["OK"], "in_nifty500": [True],
        "adv20_lagged": [10000.0], "adv20_complete": [True],
        "adv20_observation_count": [20], "positive_volume_sessions_20": [15],
        "momentum_signal_safe": [True], "momentum_signal_exclusion_reason": [""],
        "corporate_action_timing_event_ids": [""],
    })
    attached = attach_formation_observations(roster, panel)
    assert attached.security_id.tolist() == ["A", "B"]
    assert attached.formation_market_observation_missing.tolist() == [False, True]
    assert usable_formation_quote(attached).tolist() == [True, False]


def test_winner_count_and_tie_break_are_deterministic():
    candidates = pd.DataFrame({
        "formation_date": pd.Timestamp("2015-03-31"),
        "security_id": [f"ID{i:02d}" for i in range(21)],
        "eligible": True,
        "momentum_score": 1.0,
    })
    ranked = rank_winners(candidates)
    assert ranked.target_winner_count.eq(math.ceil(21 / 10)).all()
    assert ranked.loc[ranked.winner, "security_id"].tolist() == ["ID00", "ID01", "ID02"]


def test_delayed_recognition_does_not_repair_an_unrelated_missing_return():
    dates = pd.to_datetime(["2014-11-03", "2014-11-17", "2014-11-27", "2014-11-28"])
    event_id = "CA_faa277a19bfa2ac115cc"
    panel = pd.DataFrame({
        "security_id": ["X"] * 4, "date": dates,
        "market_observed": True, "market_data_status": "OK", "identity_status": "RESOLVED",
        "daily_total_return": [0.05, np.nan, np.nan, 0.10],
        "price_return": [0.05, -0.10, 0.0, 0.10],
        "previous_close": [95.0, 100.0, 90.0, 90.0],
        "total_return_available": [True, False, False, True],
        "exclusion_reason": ["", "ACCEPTED_STRICT_RETURN_EXCEPTION", "MISSING", ""],
        "all_event_ids": ["", event_id, "", ""], "quality_status": "OK",
    })
    calendar = pd.DataFrame({"date": dates, "is_last_trading_day_of_month": [False, False, False, True]})
    delayed = pd.DataFrame({
        "event_id": [event_id], "security_id": ["X"], "event_ex_date": [dates[1]],
        "price_trade_date": [dates[-1]], "actual_official_trade": [True],
        "information_available_timestamp": ["2014-11-29T00:00:00+05:30"],
        "entitlement_value_per_pre_event_share": [10.0], "price_evidence_source": ["official"],
    })
    timing = pd.DataFrame({
        "event_id": [event_id], "formation_date": [pd.Timestamp("2014-12-31")],
        "formation_timestamp": ["2015-01-01T00:00:00+05:30"],
        "equity_ex_date_in_window": [True], "formation_safe": [True],
        "all_legs_or_none_in_window": [True], "information_available_by_formation": [True],
    })
    monthly = build_monthly(panel, calendar, delayed, timing).iloc[0]
    assert not monthly.complete and pd.isna(monthly.monthly_total_return)
