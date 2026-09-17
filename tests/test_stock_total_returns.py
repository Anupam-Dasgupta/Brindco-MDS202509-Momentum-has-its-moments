import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from stock_total_returns import (
    ACTIONS,
    AUDIT_DIR,
    CUTOFF,
    NEW_PANEL,
    NEW_RETURNS,
    OLD_PANEL,
    build_returns,
    classify_actions,
    prepare_prices,
    sha256,
)


def sample_prices():
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"])
    calendar = pd.DataFrame({
        "date": dates,
        "previous_trading_day": [pd.NaT, dates[0], dates[1], dates[2]],
    })
    panel = pd.DataFrame({
        "security_id": ["X"] * 4,
        "date": dates,
        "symbol": ["X"] * 4,
        "isin": ["ISINX"] * 4,
        "close": [100.0, 95.0, 50.0, 12.0],
        "market_observed": [True] * 4,
        "market_data_status": ["OK"] * 4,
        "identity_status": ["RESOLVED"] * 4,
        "in_nifty500": [True] * 4,
    })
    return prepare_prices(panel, calendar)


def sample_event(event_id, date, kind, **fields):
    row = {
        "event_id": event_id,
        "security_id": "X",
        "ex_date": pd.Timestamp(date),
        "primary_class": kind,
        "purpose_normalized": kind,
        "signal_relevant": True,
        "possible_member_symbol": True,
        "series": "EQ",
        "economic_event_count": 1,
        "needs_manual_review": False,
        "multiple_event_types": False,
        "dividend_amount": np.nan,
        "ratio_a": np.nan,
        "ratio_b": np.nan,
        "old_face_value_parsed": np.nan,
        "new_face_value_parsed": np.nan,
        "accepted_status": None,
        "accepted_blocks": None,
        "accepted_cash": np.nan,
        "accepted_multiplier": np.nan,
        "accepted_entitlement": np.nan,
        "accepted_valuation_date": pd.NaT,
        "price_return": 0.0,
    }
    row.update(fields)
    return row


def test_ordinary_dividend_bonus_split_use_economic_formula():
    prices = sample_prices()
    events = pd.DataFrame([
        sample_event("D", "2020-01-02", "DIVIDEND", dividend_amount=10.0),
        sample_event("B", "2020-01-03", "BONUS", ratio_a=1.0, ratio_b=1.0),
        sample_event("S", "2020-01-06", "SPLIT", old_face_value_parsed=4.0, new_face_value_parsed=1.0),
    ])
    classified = classify_actions(events)
    assert classified["application_status"].eq("APPLIED_TO_RETURN").all()
    returns = build_returns(prices, classified).set_index("date")
    assert np.isclose(returns.loc["2020-01-02", "daily_total_return"], 105 / 100 - 1)
    assert np.isclose(returns.loc["2020-01-03", "daily_total_return"], 100 / 95 - 1)
    assert np.isclose(returns.loc["2020-01-06", "daily_total_return"], 48 / 50 - 1)
    assert np.isclose(
        returns.loc["2020-01-02", "daily_total_return"] - returns.loc["2020-01-02", "price_return"],
        10 / 100,
    )


def test_missing_canonical_observation_and_anchor_are_not_zero_filled():
    prices = sample_prices().drop(index=1).reset_index(drop=True)
    calendar = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]),
        "previous_trading_day": pd.to_datetime([None, "2020-01-01", "2020-01-02", "2020-01-03"]),
    })
    prices = prepare_prices(prices.drop(columns=[
        "previous_session_date", "previous_close", "price_return", "base_return_status"
    ]), calendar)
    empty = pd.DataFrame(columns=["signal_relevant", "security_id", "ex_date"])
    returns = build_returns(prices, empty).set_index("date")
    assert pd.isna(returns.loc["2020-01-01", "daily_total_return"])
    assert pd.isna(returns.loc["2020-01-03", "daily_total_return"])
    assert returns.loc["2020-01-03", "quality_status"] == "PREVIOUS_CANONICAL_OBSERVATION_MISSING"


def test_missing_close_on_prior_canonical_row_blocks_next_return():
    prices = sample_prices()
    prices.loc[prices["date"].eq(pd.Timestamp("2020-01-02")), "close"] = np.nan
    prices = prepare_prices(prices.drop(columns=[
        "previous_session_date", "previous_close", "price_return", "base_return_status"
    ]), pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]),
        "previous_trading_day": pd.to_datetime([None, "2020-01-01", "2020-01-02", "2020-01-03"]),
    }))
    empty = pd.DataFrame(columns=["signal_relevant", "security_id", "ex_date"])
    returns = build_returns(prices, empty).set_index("date")
    assert pd.isna(returns.loc["2020-01-03", "daily_total_return"])
    assert returns.loc["2020-01-03", "quality_status"] == "PREVIOUS_CANONICAL_CLOSE_UNAVAILABLE"


def test_duplicate_dividend_cannot_double_credit_wealth():
    prices = sample_prices()
    events = pd.DataFrame([
        sample_event("A", "2020-01-02", "DIVIDEND", dividend_amount=10.0),
        sample_event("B", "2020-01-02", "DIVIDEND", dividend_amount=10.0),
    ])
    classified = classify_actions(events)
    assert set(classified["application_status"]) == {"APPLIED_TO_RETURN", "NOT_SIGNAL_RELEVANT"}
    returns = build_returns(prices, classified).set_index("date")
    assert np.isclose(returns.loc["2020-01-02", "daily_total_return"], 105 / 100 - 1)
    assert len(returns.loc["2020-01-02", "applied_event_ids"].split(";")) == 1


def test_distinct_cash_dividends_combine_but_mixed_bonus_is_blocked():
    prices = sample_prices()
    cash = pd.DataFrame([
        sample_event("A", "2020-01-02", "DIVIDEND", dividend_amount=10.0),
        sample_event("B", "2020-01-02", "DIVIDEND", dividend_amount=2.0),
    ])
    cash_returns = build_returns(prices, classify_actions(cash)).set_index("date")
    assert np.isclose(cash_returns.loc["2020-01-02", "daily_total_return"], 107 / 100 - 1)
    mixed = pd.concat([
        cash.iloc[[0]],
        pd.DataFrame([sample_event("C", "2020-01-02", "BONUS", ratio_a=1.0, ratio_b=1.0)]),
    ], ignore_index=True)
    classified = classify_actions(mixed)
    assert classified["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all()
    mixed_returns = build_returns(prices, classified).set_index("date")
    assert pd.isna(mixed_returns.loc["2020-01-02", "daily_total_return"])


def test_accepted_no_direct_and_strict_exception_stay_distinct():
    events = pd.DataFrame([
        sample_event("N", "2020-01-02", "BUYBACK", accepted_status="RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT", accepted_blocks=False),
        sample_event("U", "2020-01-03", "DEBENTURE_ENTITLEMENT", accepted_status="UNRESOLVED_STRUCTURAL_EVENT", accepted_blocks=True),
    ])
    classified = classify_actions(events)
    assert classified.loc[0, "application_status"] == "NO_DIRECT_ADJUSTMENT_REQUIRED"
    assert classified.loc[1, "application_status"] == "RETURN_UNAVAILABLE_EXPLICIT"
    returns = build_returns(sample_prices(), classified).set_index("date")
    assert np.isclose(returns.loc["2020-01-02", "daily_total_return"], returns.loc["2020-01-02", "price_return"])
    assert pd.isna(returns.loc["2020-01-03", "daily_total_return"])


def test_tcs_real_dividend_regression():
    date = pd.Timestamp("2022-05-25")
    table = ds.dataset(NEW_RETURNS).to_table(
        columns=["date", "symbol", "previous_close", "close", "price_return", "daily_total_return", "applied_event_ids"],
        filter=ds.field("date") == date.to_datetime64(),
    ).to_pandas()
    tcs = table.loc[table["symbol"].eq("TCS")].iloc[0]
    source = ds.dataset(ACTIONS).to_table(
        columns=["symbol", "ex_date", "dividend_amount", "primary_class"],
        filter=ds.field("ex_date") == date.to_datetime64(),
    ).to_pandas()
    dividend = source.loc[source["symbol"].eq("TCS") & source["primary_class"].eq("DIVIDEND")].iloc[0]
    assert dividend["dividend_amount"] == 22
    assert np.isclose(tcs["daily_total_return"], (tcs["close"] + dividend["dividend_amount"]) / tcs["previous_close"] - 1)
    assert not np.isclose(tcs["daily_total_return"], tcs["price_return"])
    assert tcs["applied_event_ids"]


def test_return_artifact_and_panel_v2_acceptance():
    returns = pd.read_parquet(NEW_RETURNS, columns=[
        "security_id", "date", "daily_total_return", "total_return_available",
        "adjustment_applied", "in_nifty500",
    ])
    v2 = pd.read_parquet(NEW_PANEL, columns=[
        "security_id", "date", "daily_total_return", "total_return_available",
        "momentum_signal_safe", "corporate_action_timing_event_ids",
    ])
    assert len(returns) == len(v2) == 1_810_466
    assert not returns.duplicated(["security_id", "date"]).any()
    assert returns["date"].max() == v2["date"].max() == CUTOFF
    assert returns.loc[~returns["total_return_available"], "daily_total_return"].isna().all()
    assert returns["adjustment_applied"].sum() > 58
    joined = returns.merge(v2, on=["security_id", "date"], validate="one_to_one")
    assert joined["daily_total_return_x"].equals(joined["daily_total_return_y"])
    assert joined["total_return_available_x"].equals(joined["total_return_available_y"])
    unsafe = v2[v2["momentum_signal_safe"].eq(False).fillna(False)]
    assert len(unsafe) == 8
    assert unsafe["corporate_action_timing_event_ids"].ne("").all()


def test_event_audit_complete_and_accepted_panel_preserved():
    detail = pd.read_csv(AUDIT_DIR / "event_application_detail.csv")
    summary = pd.read_csv(AUDIT_DIR / "summary.csv").set_index("metric")["value"]
    assert detail["event_id"].notna().all()
    assert not detail["event_id"].duplicated().any()
    assert len(detail) == int(summary["economic_action_rows"])
    assert set(detail["application_status"]) == {
        "APPLIED_TO_RETURN", "NO_DIRECT_ADJUSTMENT_REQUIRED",
        "RETURN_UNAVAILABLE_EXPLICIT", "NOT_SIGNAL_RELEVANT",
    }
    assert int((detail["membership_status"].eq("PRE_MEMBERSHIP") & detail["application_status"].eq("APPLIED_TO_RETURN")).sum()) > 0
    assert summary["old_panel_sha256"] == sha256(OLD_PANEL)


def test_four_strict_bonus_debenture_returns_remain_unavailable():
    detail = pd.read_csv(AUDIT_DIR / "event_application_detail.csv")
    strict = detail[detail["application_reason"].eq("ACCEPTED_STRICT_RETURN_EXCEPTION")]
    assert len(strict) == 4
    assert set(strict["symbol"]) == {"BLUEDART", "NTPC", "BRITANNIA"}
    assert strict["calculated_total_return"].isna().all()
