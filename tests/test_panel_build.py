import numpy as np
import pandas as pd
import pytest

from panel_build import (
    DATA_CUTOFF,
    add_reason,
    attach_returns,
    build_membership_spine,
    calculate_lagged_adv,
    combine_market_and_membership,
    coalesce_membership_intervals,
    read_dated_parquet,
    select_market_observations,
    unresolved_security_id,
    validate_panel,
)


def calendar(dates):
    dates = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "trading_day_number": np.arange(len(dates)),
            "weekday": dates.day_name(),
            "is_last_trading_day_of_month": False,
        }
    )


def identity_map(rows):
    return pd.DataFrame(
        rows, columns=["isin", "symbol", "identity_id", "identity_status"]
    )


def market_row(date, symbol="OLD", isin="ISIN1", series="EQ", close=100.0, volume=10):
    return {
        "date": pd.Timestamp(date),
        "isin": isin,
        "symbol": symbol,
        "series": series,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "prev_close": close,
        "volume": volume,
        "traded_value": close * volume,
        "source_file": "fixture",
        "source_format": "fixture",
    }


def action_frame(date, **overrides):
    row = {
        "security_id": "ID1",
        "date": pd.Timestamp(date),
        "is_dividend": False,
        "is_bonus": False,
        "is_split": False,
        "is_consolidation": False,
        "is_rights": False,
        "is_structural": False,
        "is_buyback": False,
        "is_capital_reduction": False,
        "is_redemption": False,
        "needs_manual_review": False,
        "multiple_event_types": False,
        "event_unresolved": False,
        "dividend_amount": 0.0,
        "split_factor": 1.0,
        "bonus_factor": 1.0,
        "share_factor": 1.0,
        "corporate_action_purpose": "",
        "corporate_action_source_file": "",
        "corporate_action_classes": "",
        "corporate_action_review_required": False,
        "corporate_action_adjusted": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def empty_actions():
    return action_frame("1990-01-01").iloc[:0]


def ready_panel(rows):
    frame = pd.DataFrame(rows)
    frame["security_id"] = "ID1"
    frame["identity_status"] = "RESOLVED"
    frame["market_observed"] = True
    frame["market_observation_invalid"] = False
    frame["series_ambiguous"] = False
    return frame


def test_panel_uniqueness_after_series_resolution():
    rows = [
        market_row("2020-01-02", series="BE"),
        market_row("2020-01-02", series="EQ"),
    ]
    selected, _ = select_market_observations(
        pd.DataFrame(rows), identity_map([("ISIN1", "OLD", "ID1", "RESOLVED")])
    )
    assert len(selected) == 1
    assert selected.iloc[0]["series"] == "EQ"
    assert selected.iloc[0]["conflicting_series"]


def test_ambiguous_series_suppresses_prices():
    rows = [
        market_row("2020-01-02", symbol="OLD", series="BE"),
        market_row("2020-01-02", symbol="NEW", series="BZ"),
    ]
    mapping = identity_map(
        [
            ("ISIN1", "OLD", "ID1", "RESOLVED"),
            ("ISIN1", "NEW", "ID1", "RESOLVED"),
        ]
    )
    selected, _ = select_market_observations(pd.DataFrame(rows), mapping)
    assert selected.iloc[0]["market_data_status"] == "SERIES_AMBIGUOUS"
    assert np.isnan(selected.iloc[0]["close"])


def test_point_in_time_membership_is_half_open():
    member = pd.DataFrame(
        {
            "symbol": ["A"],
            "valid_from": [pd.Timestamp("2020-03-27")],
            "valid_to": [pd.Timestamp("2020-03-30")],
            "source": ["fixture"],
        }
    )
    crosswalk = pd.DataFrame(
        {
            "membership_symbol": ["A"],
            "identity_id": ["ID1"],
            "canonical_symbol": ["A"],
            "observed_in_prices": [True],
        }
    )
    intervals = coalesce_membership_intervals(member, crosswalk)
    spine = build_membership_spine(
        calendar(["2020-03-26", "2020-03-27", "2020-03-30"]), intervals
    )
    assert spine["date"].tolist() == [pd.Timestamp("2020-03-27")]


def test_membership_attachment_keeps_pre_entry_market_history():
    member = pd.DataFrame(
        {
            "symbol": ["A"],
            "valid_from": [pd.Timestamp("2020-03-27")],
            "valid_to": [pd.NaT],
            "source": ["fixture"],
        }
    )
    crosswalk = pd.DataFrame(
        {
            "membership_symbol": ["A"],
            "identity_id": ["ID1"],
            "canonical_symbol": ["A"],
            "observed_in_prices": [True],
        }
    )
    intervals = coalesce_membership_intervals(member, crosswalk)
    spine = build_membership_spine(
        calendar(["2020-03-26", "2020-03-27"]), intervals
    )
    market = ready_panel([market_row("2020-03-26"), market_row("2020-03-27")])
    market["candidate_count"] = 1
    market["eq_candidate_count"] = 1
    market["conflicting_series"] = False
    market["unsupported_series"] = False
    market["market_data_status"] = "OK"
    combined = combine_market_and_membership(market, spine)
    before_entry = combined.loc[combined["date"].eq(pd.Timestamp("2020-03-26"))]
    assert len(before_entry) == 1
    assert not before_entry.iloc[0]["in_nifty500"]


def test_dividend_return_is_three_percent():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-02", close=98),
        ]
    )
    actions = action_frame(
        "2020-01-02",
        is_dividend=True,
        dividend_amount=5.0,
        corporate_action_adjusted=True,
    )
    result = attach_returns(rows, actions, calendar(["2020-01-01", "2020-01-02"]))
    assert result.iloc[1]["daily_price_return"] == pytest.approx(-0.02)
    assert result.iloc[1]["daily_total_return"] == pytest.approx(0.03)


def test_two_for_one_split_has_zero_economic_return():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-02", close=50),
        ]
    )
    actions = action_frame(
        "2020-01-02",
        is_split=True,
        share_factor=2.0,
        split_factor=2.0,
        corporate_action_adjusted=True,
    )
    result = attach_returns(rows, actions, calendar(["2020-01-01", "2020-01-02"]))
    assert result.iloc[1]["daily_price_return"] == pytest.approx(-0.5)
    assert result.iloc[1]["daily_total_return"] == pytest.approx(0.0)


def test_one_for_one_bonus_has_zero_economic_return():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-02", close=50),
        ]
    )
    actions = action_frame(
        "2020-01-02",
        is_bonus=True,
        share_factor=2.0,
        bonus_factor=2.0,
        corporate_action_adjusted=True,
    )
    result = attach_returns(rows, actions, calendar(["2020-01-01", "2020-01-02"]))
    assert result.iloc[1]["daily_total_return"] == pytest.approx(0.0)


def test_supported_rename_preserves_return_history():
    rows = ready_panel(
        [
            market_row("2020-01-01", symbol="OLD", close=100),
            market_row("2020-01-02", symbol="NEW", close=110),
        ]
    )
    result = attach_returns(
        rows, empty_actions(), calendar(["2020-01-01", "2020-01-02"])
    )
    assert result.iloc[1]["daily_total_return"] == pytest.approx(0.10)


def test_structural_event_is_not_spliced_into_total_return():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-02", close=180),
        ]
    )
    actions = action_frame(
        "2020-01-02",
        is_structural=True,
        event_unresolved=True,
        corporate_action_review_required=True,
    )
    result = attach_returns(rows, actions, calendar(["2020-01-01", "2020-01-02"]))
    assert np.isnan(result.iloc[1]["daily_total_return"])
    assert result.iloc[1]["return_status"] == "CORPORATE_ACTION_UNRESOLVED"
    assert result.iloc[1]["event_unresolved"]


def test_implausible_corporate_action_adjustment_is_flagged():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-02", close=100),
        ]
    )
    actions = action_frame(
        "2020-01-02",
        is_dividend=True,
        dividend_amount=125.0,
        corporate_action_adjusted=True,
    )
    result = attach_returns(rows, actions, calendar(["2020-01-01", "2020-01-02"]))
    assert result.iloc[1]["return_adjustment_implausible"]
    assert result.iloc[1]["corporate_action_review_required"]
    assert np.isnan(result.iloc[1]["daily_total_return"])


def test_adv_is_causal_and_uses_previous_twenty_sessions():
    dates = pd.date_range("2020-01-01", periods=21, freq="D")
    rows = ready_panel(
        [market_row(date, close=10, volume=10) for date in dates]
    )
    rows["trading_day_number"] = np.arange(21)
    rows.loc[20, "traded_value"] = 1_000_000_000
    result = calculate_lagged_adv(rows)
    assert result.loc[20, "adv20_lagged"] == pytest.approx(100.0)
    changed = rows.copy()
    changed.loc[20, "traded_value"] = 2_000_000_000
    assert calculate_lagged_adv(changed).loc[20, "adv20_lagged"] == pytest.approx(100.0)


def test_adv_distinguishes_zero_volume_from_missing_observation():
    dates = pd.date_range("2020-01-01", periods=21, freq="D")
    rows = ready_panel(
        [market_row(date, close=10, volume=10) for date in dates]
    )
    rows["trading_day_number"] = np.arange(21)
    rows.loc[5, ["volume", "traded_value"]] = 0
    zero_result = calculate_lagged_adv(rows.copy())
    assert zero_result.loc[20, "adv20_observation_count"] == 20
    assert zero_result.loc[20, "positive_volume_sessions_20"] == 19
    assert zero_result.loc[20, "adv20_complete"]

    missing = rows.copy()
    missing.loc[5, "market_observed"] = False
    missing.loc[5, ["volume", "traded_value"]] = np.nan
    missing_result = calculate_lagged_adv(missing)
    assert missing_result.loc[20, "adv20_observation_count"] == 19
    assert not missing_result.loc[20, "adv20_complete"]
    assert np.isnan(missing_result.loc[20, "adv20_lagged"])


def test_weekend_session_participates_in_adv_ordering():
    dates = list(pd.date_range("2020-01-01", periods=19, freq="D"))
    dates += [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-02-03")]
    rows = ready_panel(
        [market_row(date, close=10, volume=10) for date in dates]
    )
    rows["trading_day_number"] = np.arange(21)
    result = calculate_lagged_adv(rows)
    assert result.loc[20, "adv20_observation_count"] == 20
    assert result.loc[20, "adv20_complete"]


def test_missing_price_is_not_future_filled_or_zero_return():
    rows = ready_panel(
        [
            market_row("2020-01-01", close=100),
            market_row("2020-01-03", close=110),
        ]
    )
    result = attach_returns(
        rows,
        empty_actions(),
        calendar(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )
    assert np.isnan(result.iloc[1]["daily_total_return"])
    assert result.iloc[1]["return_status"] == "PREVIOUS_PRICE_MISSING"


def test_unresolved_identity_has_stable_flag_not_a_guess():
    token = unresolved_security_id("UNKNOWN", "ISINX")
    assert token.startswith("UNRESOLVED_")
    codes = add_reason(
        pd.Series([""], dtype="string"),
        pd.Series([True]),
        "IDENTITY_UNRESOLVED",
    )
    assert codes.iloc[0] == "IDENTITY_UNRESOLVED"


def test_holdout_rows_fail_structural_validation():
    panel = pd.DataFrame(
        {
            "security_id": ["ID1"],
            "date": [DATA_CUTOFF + pd.Timedelta(days=1)],
            "in_nifty500": [False],
            "adv20_observation_count": [0],
            "adv20_complete": [False],
            "adv20_lagged": [np.nan],
            "event_unresolved": [False],
            "daily_total_return": [np.nan],
        }
    )
    with pytest.raises(ValueError, match="post-cutoff"):
        validate_panel(panel, calendar([DATA_CUTOFF]))


def test_dated_parquet_reader_does_not_consume_holdout_rows(tmp_path):
    path = tmp_path / "dated.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2023-03-31", "2023-04-03"]),
            "value": [1.0, 999.0],
        }
    ).to_parquet(path, index=False)
    result = read_dated_parquet(path, "date", ["date", "value"])
    assert result.to_dict("records") == [
        {"date": pd.Timestamp("2023-03-31"), "value": 1.0}
    ]
