import hashlib

import numpy as np
import pandas as pd
import pytest
import pyarrow.dataset as ds

from brindco_momentum.signals.momentum_signal import (
    AUDIT, CALENDAR, CUTOFF, DELAYED, FORMATIONS_OUTPUT, MEMBERSHIP,
    MONTHLY_OUTPUT, OLD_PANEL, PANEL, RETURNS, WINNERS_OUTPUT,
    attach_formation_observations, build_monthly, rank_winners,
    read_parquet_before_cutoff, require_corrected_sources, usable_formation_quote,
)


@pytest.fixture(scope="module")
def outputs():
    return (
        pd.read_parquet(MONTHLY_OUTPUT),
        pd.read_parquet(FORMATIONS_OUTPUT),
        pd.read_parquet(WINNERS_OUTPUT),
    )


def test_v1_cannot_be_selected_as_return_source():
    require_corrected_sources(PANEL, RETURNS)
    with pytest.raises(ValueError, match="revoked"):
        require_corrected_sources(OLD_PANEL, RETURNS)
    with pytest.raises(ValueError, match="revoked"):
        require_corrected_sources(PANEL, OLD_PANEL)


def test_corrected_return_artifact_and_v2_are_actual_inputs():
    tcs_date = pd.Timestamp("2022-05-25").to_datetime64()
    corrected = ds.dataset(RETURNS).to_table(
        columns=["date", "symbol", "daily_total_return", "price_return"],
        filter=ds.field("date") == tcs_date,
    ).to_pandas()
    old = ds.dataset(OLD_PANEL).to_table(
        columns=["date", "symbol", "daily_total_return"],
        filter=ds.field("date") == tcs_date,
    ).to_pandas()
    tcs = corrected.loc[corrected["symbol"].eq("TCS")].iloc[0]
    v1 = old.loc[old["symbol"].eq("TCS")].iloc[0]
    assert not np.isclose(tcs["daily_total_return"], v1["daily_total_return"])
    assert np.isclose(v1["daily_total_return"], tcs["price_return"])


def test_monthly_delayed_entitlement_is_one_time_endpoint_credit():
    dates = pd.to_datetime(["2014-11-03", "2014-11-17", "2014-11-27", "2014-11-28"])
    event_id = "CA_faa277a19bfa2ac115cc"
    panel = pd.DataFrame({
        "security_id": ["X"] * 4, "date": dates,
        "market_observed": True, "market_data_status": "OK", "identity_status": "RESOLVED",
        "daily_total_return": [0.05, np.nan, 0.0, 0.10],
        "price_return": [0.05, -0.10, 0.0, 0.10],
        "previous_close": [95.0, 100.0, 90.0, 90.0],
        "total_return_available": [True, False, True, True],
        "exclusion_reason": ["", "ACCEPTED_STRICT_RETURN_EXCEPTION", "", ""],
        "all_event_ids": ["", event_id, "", ""], "quality_status": "OK",
    })
    calendar = pd.DataFrame({
        "date": dates, "is_last_trading_day_of_month": [False, False, False, True]
    })
    delayed = pd.DataFrame({
        "event_id": [event_id], "security_id": ["X"],
        "event_ex_date": [dates[1]], "price_trade_date": [dates[-1]],
        "actual_official_trade": [True], "information_available_timestamp": ["2014-11-29T00:00:00+05:30"],
        "entitlement_value_per_pre_event_share": [10.0], "price_evidence_source": ["official trade"],
    })
    timing = pd.DataFrame({
        "event_id": [event_id], "formation_date": [pd.Timestamp("2014-12-31")],
        "formation_timestamp": ["2015-01-01T00:00:00+05:30"],
        "equity_ex_date_in_window": [True], "formation_safe": [True],
        "all_legs_or_none_in_window": [True], "information_available_by_formation": [True],
    })
    monthly = build_monthly(panel, calendar, delayed, timing).iloc[0]
    assert monthly["complete"]
    assert monthly["delayed_event_id"] == event_id
    assert monthly["recognition_date"] == dates[-1]
    assert monthly["information_available_timestamp"] == pd.Timestamp("2014-11-29T00:00:00+05:30")
    assert np.isclose(monthly["monthly_total_return"], 1.05 * 0.90 * 1.10 + 1.05 * 10 / 100 - 1)
    assert not np.isclose(monthly["monthly_total_return"], 1.05 * (0.90 + 0.10) * 1.10 - 1)
    assert pd.isna(panel.loc[1, "daily_total_return"])

    panel.loc[2, "daily_total_return"] = np.nan
    panel.loc[2, "total_return_available"] = False
    blocked = build_monthly(panel, calendar, delayed, timing).iloc[0]
    assert not blocked["complete"]
    assert pd.isna(blocked["monthly_total_return"])
    assert blocked["method"] != "DELAYED_RECOGNITION_MONTHLY_ENDPOINT"
    timing.loc[0, "formation_safe"] = False
    panel.loc[2, "daily_total_return"] = 0.0
    panel.loc[2, "total_return_available"] = True
    unsafe = build_monthly(panel, calendar, delayed, timing).iloc[0]
    assert not unsafe["complete"]


def test_formation_window_is_exactly_april_2014_through_february_2015(outputs):
    monthly, formations, _ = outputs
    formed = formations.loc[
        formations["formation_date"].eq(pd.Timestamp("2015-03-31"))
        & formations["security_id"].eq("NSE_4FB8019524D0")
    ].iloc[0]
    assert formed["holding_month"] == pd.Period("2015-04", freq="M")
    assert formed["lookback_first_month"] == pd.Period("2014-04", freq="M")
    assert formed["lookback_last_month"] == pd.Period("2015-02", freq="M")
    lookback = monthly.loc[
        monthly["security_id"].eq(formed["security_id"])
        & monthly["month"].between(formed["lookback_first_month"], formed["lookback_last_month"])
    ]
    assert len(lookback) == 11 and lookback["complete"].all()
    assert np.isclose(formed["momentum_score"], lookback["gross"].prod() - 1)
    assert pd.Period("2015-03", freq="M") not in set(lookback["month"])


def test_official_spine_and_liquidity_quote_gates(outputs):
    _, formations, _ = outputs
    assert formations["formation_date"].nunique() == 103
    assert formations.groupby("formation_date").size().between(500, 501).all()
    assert not formations.duplicated(["security_id", "formation_date"]).any()
    assert not formations["formation_market_observation_missing"].any() or (
        ~formations.loc[formations["formation_market_observation_missing"], "eligible"]
    ).all()
    assert (formations.loc[formations["eligible"], "adv20_observation_count"] == 20).all()
    assert (formations.loc[formations["eligible"], "positive_volume_sessions_20"] >= 15).all()
    assert formations.loc[formations["eligible"], "quote_usable"].all()
    assert not formations.loc[formations["eligible"], "market_data_status"].ne("OK").any()
    official = pd.read_parquet(MEMBERSHIP, columns=["evidence_status"])
    assert not official["evidence_status"].str.contains("snapshot_floor", case=False, na=False).any()


def test_missing_formation_panel_row_remains_in_official_roster():
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
    assert attached["security_id"].tolist() == ["A", "B"]
    assert attached["formation_market_observation_missing"].tolist() == [False, True]
    # Current-day volume is deliberately absent from the quote predicate.
    assert usable_formation_quote(attached).tolist() == [True, False]
    attached.loc[0, "market_data_status"] = "STALE"
    assert not usable_formation_quote(attached).any()


def test_top_decile_ceiling_and_security_id_tie_break():
    date = pd.Timestamp("2015-03-31")
    ids = [f"ID{i:02d}" for i in range(21)]
    candidates = pd.DataFrame({
        "formation_date": date, "security_id": ids,
        "eligible": True, "momentum_score": [1.0] * 21,
    })
    ranked = rank_winners(candidates)
    assert ranked.loc[ranked["winner"], "security_id"].tolist() == ["ID00", "ID01", "ID02"]
    assert ranked["target_winner_count"].eq(3).all()


def test_eight_britannia_timing_reasons_are_distinct_from_other_failures(outputs):
    _, formations, _ = outputs
    timing = formations.loc[
        formations["signal_exclusion_reason"].eq("BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW")
    ]
    assert len(timing) == 8
    assert timing["security_id"].eq("NSE_444C594AB9B7").all()
    britannia = formations.loc[formations["security_id"].eq("NSE_444C594AB9B7")]
    assert len(britannia.loc[~britannia["eligible"]]) > 8
    assert formations.loc[formations["eligible"], "timing_eligible"].all()


def test_monthly_completeness_provenance_and_strict_daily_exceptions(outputs):
    monthly, formations, _ = outputs
    assert monthly["security_id"].nunique() == 865
    assert monthly["month"].max() == pd.Period("2023-03", freq="M")
    assert monthly.loc[~monthly["complete"], "gross"].isna().all()
    repaired = monthly.loc[monthly["method"].eq("DELAYED_RECOGNITION_MONTHLY_ENDPOINT")]
    assert set(repaired["delayed_event_id"]) == {
        "CA_faa277a19bfa2ac115cc", "CA_df82d8fc43ad7e21c2a8"
    }
    strict = ds.dataset(RETURNS).to_table(
        columns=["date", "security_id", "daily_total_return", "exclusion_reason"],
        filter=ds.field("date") <= CUTOFF.to_datetime64(),
    ).to_pandas()
    unresolved = strict.loc[strict["exclusion_reason"].str.contains("ACCEPTED_STRICT_RETURN_EXCEPTION", na=False)]
    assert len(unresolved) == 4 and unresolved["daily_total_return"].isna().all()
    assert formations.loc[~formations["history_eligible"], "lookback_unavailable_reasons"].str.len().gt(0).all()


def test_winner_sets_are_ranked_deterministically_without_portfolio_weights(outputs):
    _, formations, winners = outputs
    assert formations.loc[formations["scored"], "formation_date"].nunique() == 96
    assert formations.loc[~formations["scored"], "formation_date"].nunique() == 7
    assert winners["scored"].sum() > 0
    counts = formations.groupby("formation_date")["eligible"].sum()
    selected = winners.groupby("formation_date").size()
    assert selected.eq(np.ceil(counts / 10)).all()
    for _, group in winners.groupby("formation_date"):
        ordered = group.sort_values("rank")
        assert ordered["rank"].tolist() == list(range(1, len(ordered) + 1))
        assert ordered[["momentum_score", "security_id"]].reset_index(drop=True).equals(
            ordered.sort_values(["momentum_score", "security_id"], ascending=[False, True])[
                ["momentum_score", "security_id"]
            ].reset_index(drop=True)
        )
    assert "target_weight" not in winners.columns


def test_unresolved_event_materiality_has_no_guessed_winner_rank(outputs):
    _, formations, _ = outputs
    audit = pd.read_csv(AUDIT / "unresolved_event_materiality.csv")
    changed = audit.loc[audit["final_signal_availability_changed"].eq(True)]
    assert not changed.empty
    assert changed["would_otherwise_be_winner"].eq("UNKNOWN_MISSING_ECONOMIC_RETURN").all()
    assert changed["required_event_month_return_to_win"].notna().all()
    assert set(changed["formation_date"]).issubset(set(formations["formation_date"].dt.strftime("%Y-%m-%d")))


def test_development_cutoff_and_return_revision_is_audited(outputs):
    _, formations, _ = outputs
    assert formations["formation_date"].max() == pd.Timestamp("2023-02-28")
    assert formations["holding_month"].max() == pd.Period("2023-03", freq="M")
    hashes = pd.read_csv(AUDIT.parent / "event_resolution/artifact_hashes.csv")
    revision = hashes.loc[hashes["artifact"].eq("data/processed/stock_total_returns.parquet")].iloc[0]
    assert revision.before_sha256 == "ba05c8c4964c9cf3845dac99f49f6864b63f79d87beaa76549126d6b0990bac8"
    assert revision.after_sha256 == hashlib.sha256(RETURNS.read_bytes()).hexdigest()
    assert revision.before_sha256 != revision.after_sha256
    dates = read_parquet_before_cutoff(CALENDAR, ["date"], "date")
    assert dates["date"].max() <= CUTOFF
