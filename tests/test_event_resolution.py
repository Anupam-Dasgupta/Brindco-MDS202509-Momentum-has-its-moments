import hashlib

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pytest

from event_resolution_audit import ROOT
from stock_total_returns import (
    CUTOFF, MANUAL_RESOLUTIONS, NEW_RETURNS,
    apply_manual_resolutions, build_returns, prepare_prices,
)


def sample_data(kind="BONUS", date="2020-01-02"):
    days = pd.to_datetime(["2020-01-01", "2020-01-02"])
    calendar = pd.DataFrame({"date": days, "previous_trading_day": [pd.NaT, days[0]]})
    panel = pd.DataFrame({
        "security_id": ["X", "X"], "date": days, "symbol": ["X", "X"],
        "isin": ["ISINX", "ISINX"], "close": [100.0, 52.0],
        "market_observed": [True, True], "market_data_status": ["OK", "OK"],
        "identity_status": ["RESOLVED", "RESOLVED"], "in_nifty500": [True, True],
        "series": ["EQ", "EQ"],
    })
    prices = prepare_prices(panel, calendar)
    events = pd.DataFrame([{
        "event_id": "E", "security_id": "X", "symbol": "X", "ex_date": days[1],
        "primary_class": kind, "source_file": "source.json", "series": "EQ",
        "signal_relevant": True, "application_status": "RETURN_UNAVAILABLE_EXPLICIT",
        "application_reason": "TREATMENT_NOT_ACCEPTED", "accepted_status": None,
        "cash_effect": 0.0, "share_effect": 1.0, "entitlement_effect": 0.0,
    }])
    manual = pd.DataFrame([{
        "event_id": "E", "security_id": "X", "symbol_at_event": "X", "isin": "ISINX",
        "event_date": date, "event_type": kind, "source_file": "source.json",
        "resolution_status": "RESOLVED_SIMPLE_ACTION", "treatment_type": "COMBINED_BONUS_DIVIDEND",
        "cash_per_pre_event_share": 3.0, "share_multiplier": 2.0,
        "evidence_url": "https://example.org/filing", "evidence_fact": "one share plus cash",
        "reasoning": "holder receives both legs", "passive_holder_assumption": "",
        "entitlement_price_date": "", "entitlement_symbol": "", "entitlement_isin": "",
        "entitlement_price_close": np.nan, "entitlement_units_per_pre_event_share": np.nan,
    }])
    return prices, events, manual


def test_combined_bonus_and_cash_flow_into_total_return():
    prices, events, manual = sample_data()
    resolved = apply_manual_resolutions(events, manual, prices)
    day = build_returns(prices, resolved).iloc[-1]
    assert resolved.loc[0, "application_status"] == "APPLIED_TO_RETURN"
    assert np.isclose(day.daily_total_return, (2 * 52 + 3) / 100 - 1)


def test_split_bonus_and_no_tender_are_distinct():
    prices, events, manual = sample_data(kind="SPLIT")
    manual.loc[0, "treatment_type"] = "COMBINED_SPLIT_BONUS"
    manual.loc[0, "cash_per_pre_event_share"] = 0.0
    manual.loc[0, "share_multiplier"] = 4.0
    split = build_returns(prices, apply_manual_resolutions(events, manual, prices)).iloc[-1]
    assert np.isclose(split.daily_total_return, 4 * 52 / 100 - 1)

    events.loc[0, "primary_class"] = "BUYBACK"
    manual.loc[0, "event_type"] = "BUYBACK"
    manual.loc[0, "resolution_status"] = "RESOLVED_NO_DIRECT_ADJUSTMENT"
    manual.loc[0, "treatment_type"] = "OPTIONAL_TENDER_NO_PARTICIPATION"
    manual.loc[0, "share_multiplier"] = 1.0
    manual.loc[0, "passive_holder_assumption"] = "DO_NOT_TENDER"
    tender = build_returns(prices, apply_manual_resolutions(events, manual, prices)).iloc[-1]
    assert np.isclose(tender.daily_total_return, tender.price_return)


def test_listed_share_distribution_requires_actual_matching_ex_date_quote():
    prices, events, manual = sample_data(kind="STRUCTURAL")
    recipient = prices.iloc[[-1]].copy()
    recipient["security_id"] = "Y"
    recipient["symbol"] = "Y"
    recipient["isin"] = "ISINY"
    recipient["close"] = 10.0
    prices = pd.concat([prices, recipient], ignore_index=True)
    manual.loc[0, "event_type"] = "STRUCTURAL"
    manual.loc[0, "resolution_status"] = "RESOLVED_EXISTING_TREATMENT"
    manual.loc[0, "treatment_type"] = "LISTED_SHARE_DISTRIBUTION"
    manual.loc[0, "cash_per_pre_event_share"] = 0.0
    manual.loc[0, "share_multiplier"] = 1.0
    manual.loc[0, "entitlement_symbol"] = "Y"
    manual.loc[0, "entitlement_isin"] = "ISINY"
    manual.loc[0, "entitlement_price_date"] = "2020-01-02"
    manual.loc[0, "entitlement_price_close"] = 10.0
    manual.loc[0, "entitlement_units_per_pre_event_share"] = 2.0
    resolved = apply_manual_resolutions(events, manual, prices)
    assert resolved.loc[0, "entitlement_effect"] == 20.0
    manual.loc[0, "entitlement_price_close"] = 11.0
    with pytest.raises(ValueError, match="quote disagrees"):
        apply_manual_resolutions(events, manual, prices)


def test_unresolved_and_unmatched_identity_cannot_be_forced():
    prices, events, manual = sample_data()
    unresolved = build_returns(prices, events).iloc[-1]
    assert pd.isna(unresolved.daily_total_return)
    manual.loc[0, "isin"] = "OTHER"
    with pytest.raises(ValueError, match="identity is not evidenced"):
        apply_manual_resolutions(events, manual, prices)
    manual.loc[0, "isin"] = "ISINX"
    events.loc[0, "accepted_status"] = "ACCEPTED"
    with pytest.raises(ValueError, match="overwrite an accepted event"):
        apply_manual_resolutions(events, manual, prices)


def test_real_resolution_propagates_to_monthly_features_and_winners():
    manual = pd.read_csv(MANUAL_RESOLUTIONS)
    day = ds.dataset(NEW_RETURNS).to_table(
        columns=["security_id", "date", "close", "previous_close", "daily_total_return", "applied_event_ids", "total_return_available"],
        filter=ds.field("date") == pd.Timestamp("2020-03-04").to_datetime64(),
    ).to_pandas()
    event = manual.loc[manual.symbol_at_event.eq("TATACHEM")].iloc[0]
    row = day.loc[day.security_id.eq(event.security_id)].iloc[0]
    expected = (row.close + event.entitlement_units_per_pre_event_share * event.entitlement_price_close) / row.previous_close - 1
    assert row.total_return_available and event.event_id in row.applied_event_ids
    assert np.isclose(row.daily_total_return, expected)

    monthly = pd.read_parquet(ROOT / "data/processed/momentum_monthly_features.parquet")
    match = monthly.loc[monthly.security_id.eq(event.security_id) & monthly.month.eq(pd.Period("2020-03"))].iloc[0]
    assert match.complete and np.isfinite(match.monthly_total_return)

    formations = pd.read_parquet(ROOT / "data/processed/momentum_formations.parquet")
    winners = pd.read_parquet(ROOT / "data/processed/momentum_winners.parquet")
    expected_winners = formations.loc[formations.winner, ["formation_date", "security_id"]]
    pd.testing.assert_frame_equal(
        winners[["formation_date", "security_id"]].sort_values(["formation_date", "security_id"]).reset_index(drop=True),
        expected_winners.sort_values(["formation_date", "security_id"]).reset_index(drop=True),
    )
    counts = formations.groupby("formation_date").eligible.sum()
    seats = winners.groupby("formation_date").size()
    assert seats.eq(np.ceil(counts / 10)).all()
    assert formations.formation_date.max() <= CUTOFF


def test_accepted_treatments_and_raw_sources_are_unchanged():
    accepted = ROOT / "data/processed/corporate_action_treatment/in_universe_event_treatments.parquet"
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest(accepted) == "5ddea240585838652401277a3b8b3e417d21b2919c9e6a8906cb3ea328c858cf"
    manual = pd.read_csv(MANUAL_RESOLUTIONS)
    manifest = pd.read_csv(ROOT / "data/raw/corporate_actions/manifest.csv").set_index("filename")
    for filename in manual.source_file.unique():
        path = ROOT / "data/raw/corporate_actions" / filename
        assert digest(path) == manifest.loc[filename, "sha256"]
    for symbol, date in [("BLUEDART", "2014-11-17"), ("NTPC", "2015-03-20"),
                         ("BRITANNIA", "2019-08-22"), ("BRITANNIA", "2021-05-25")]:
        day = ds.dataset(NEW_RETURNS).to_table(
            columns=["symbol", "date", "total_return_available", "daily_total_return"],
            filter=ds.field("date") == pd.Timestamp(date).to_datetime64(),
        ).to_pandas()
        row = day.loc[day.symbol.eq(symbol)].iloc[0]
        assert not row.total_return_available and pd.isna(row.daily_total_return)
