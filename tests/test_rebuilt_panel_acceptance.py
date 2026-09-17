import pandas as pd
import pytest

from brindco_momentum.data.panel_build import (
    BRITANNIA_SECURITY_ID,
    DATA_CUTOFF,
    IDENTITY_PATH,
    MEMBERSHIP_PATH,
    OUTPUT_PANEL,
    PROHIBITED_MEMBERSHIP_PATH,
    TREATMENT_PATH,
    select_market_observations,
)


@pytest.fixture(scope="module")
def panel():
    return pd.read_parquet(
        OUTPUT_PANEL,
        columns=[
            "date",
            "security_id",
            "series",
            "in_nifty500",
            "corporate_action_event_count",
            "corporate_action_exception",
            "strict_total_return_available",
            "daily_total_return",
            "delayed_recognition_available",
            "delayed_recognition_event_ids",
            "delayed_recognition_event_signal_safe",
            "is_formation_date",
            "momentum_signal_safe",
            "momentum_signal_exclusion_reason",
            "corporate_action_timing_event_ids",
            "final_signal_available",
        ],
    )


def test_official_membership_is_the_only_configured_source():
    assert MEMBERSHIP_PATH.exists()
    assert MEMBERSHIP_PATH != PROHIBITED_MEMBERSHIP_PATH
    assert MEMBERSHIP_PATH.parts[-2:] == (
        "membership_official",
        "nifty500_official_membership_intervals.parquet",
    )
    membership = pd.read_parquet(MEMBERSHIP_PATH)
    assert not membership["evidence_status"].str.contains(
        "snapshot_floor", case=False, na=False
    ).any()


def test_official_membership_has_no_prelisting_or_unresolved_identity():
    membership = pd.read_parquet(
        MEMBERSHIP_PATH, columns=["security_id", "valid_from"]
    )
    identity = pd.read_parquet(
        IDENTITY_PATH, columns=["security_id", "first_seen"]
    )
    first_seen = identity.groupby("security_id")["first_seen"].min()
    assert membership["security_id"].isin(first_seen.index).all()
    assert not membership["valid_from"].lt(
        membership["security_id"].map(first_seen)
    ).any()


def test_accepted_dated_identity_has_no_alias_collisions():
    collision_path = IDENTITY_PATH.parent / "dated_alias_collisions.csv"
    assert pd.read_csv(collision_path).empty


def test_corroborated_be_series_is_accepted():
    date = pd.Timestamp("2020-01-02")
    market = pd.DataFrame(
        [
            {
                "date": date,
                "isin": "ISIN1",
                "symbol": "ABC",
                "series": "BE",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "prev_close": 100.0,
                "volume": 10,
                "traded_value": 1000.0,
            }
        ]
    )
    identity = pd.DataFrame(
        [
            {
                "isin": "ISIN1",
                "symbol": "ABC",
                "security_id": "ID1",
                "identity_status": "RESOLVED",
                "first_seen": date,
                "last_seen": date,
            }
        ]
    )
    classification = pd.DataFrame(
        [
            {
                "security_id": "ID1",
                "isin": "ISIN1",
                "symbol": "ABC",
                "series": "BE",
                "first_seen": date,
                "last_seen": date,
                "is_eligible_common_equity": True,
                "classification": "TRADE_FOR_TRADE_EQUITY",
                "classification_evidence": "SAME_ISIN_OBSERVED_IN_EQ",
            }
        ]
    )
    selected, _ = select_market_observations(market, identity, classification)
    assert len(selected) == 1
    assert selected.iloc[0]["series"] == "BE"
    assert selected.iloc[0]["market_data_status"] == "OK"


def test_accepted_corporate_actions_are_integrated_once(panel):
    treatments = pd.read_parquet(TREATMENT_PATH)
    assert len(treatments) == 149
    assert treatments["event_id"].notna().all()
    assert not treatments["event_id"].duplicated().any()
    assert int(treatments["blocks_total_return"].sum()) == 4
    assert int(panel["corporate_action_event_count"].sum()) == 149

    strict = panel[panel["corporate_action_exception"]]
    assert len(strict) == 4
    assert not strict["strict_total_return_available"].any()
    assert strict["daily_total_return"].isna().all()


def test_delayed_recognition_metadata_does_not_create_a_signal(panel):
    recognition = panel[panel["delayed_recognition_available"]]
    assert len(recognition) == 4
    assert recognition["delayed_recognition_event_ids"].ne("").all()
    assert set(recognition["delayed_recognition_event_signal_safe"].dropna()) == {
        True,
        False,
    }
    assert panel["final_signal_available"].isna().all()


def test_exactly_eight_britannia_formation_observations_are_unsafe(panel):
    unsafe = panel[panel["momentum_signal_safe"].eq(False).fillna(False)]
    assert len(unsafe) == 8
    assert unsafe["security_id"].eq(BRITANNIA_SECURITY_ID).all()
    assert unsafe["is_formation_date"].all()
    assert unsafe["corporate_action_timing_event_ids"].ne("").all()
    assert unsafe["momentum_signal_exclusion_reason"].eq(
        "PARTIAL_ECONOMIC_EVENT_IN_WINDOW"
    ).all()
    assert panel.loc[~panel["is_formation_date"], "momentum_signal_safe"].isna().all()


def test_rebuilt_panel_respects_development_cutoff(panel):
    assert panel["date"].max() == DATA_CUTOFF
    assert not panel["date"].gt(DATA_CUTOFF).any()
