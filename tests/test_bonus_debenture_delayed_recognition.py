import pandas as pd

from bonus_debenture_delayed_recognition import (
    ACCEPTED_TREATMENT_SHA256,
    TREATMENTS,
    build_timing_audit,
    build_trade_candidates,
    file_sha256,
    run,
)


def test_candidate_selection_uses_earliest_date_then_highest_traded_value():
    candidates = build_trade_candidates()
    selected = candidates[candidates["selected"]].set_index("isin")

    assert selected.loc["INE233B08087", "venue"] == "BSE"
    assert selected.loc["INE233B08087", "date"] == pd.Timestamp("2014-11-28")
    assert selected.loc["INE733E07JP6", "venue"] == "NSE"
    assert selected.loc["INE216A07052", "venue"] == "NSE"
    assert selected.loc["INE216A08027", "venue"] == "NSE"


def test_multi_leg_gate_rejects_every_partial_window():
    delayed = pd.DataFrame(
        [
            {
                "event_id": "EVENT",
                "symbol": "TEST",
                "event_ex_date": "2020-01-15",
                "event_holding_month": "2020-01",
                "tranche_id": "A",
                "valuation_holding_month": "2020-01",
                "information_available_timestamp": "2020-02-01T00:00:00+05:30",
            },
            {
                "event_id": "EVENT",
                "symbol": "TEST",
                "event_ex_date": "2020-01-15",
                "event_holding_month": "2020-01",
                "tranche_id": "B",
                "valuation_holding_month": "2020-02",
                "information_available_timestamp": "2020-03-01T00:00:00+05:30",
            },
        ]
    )
    formations = pd.DataFrame(
        [
            {
                "decision_month": pd.Period("2020-03", freq="M"),
                "formation_date": pd.Timestamp("2020-02-28"),
                "formation_timestamp": pd.Timestamp(
                    "2020-02-29T00:00:00", tz="Asia/Kolkata"
                ),
                "window_start_month": pd.Period("2019-03", freq="M"),
                "window_end_month": pd.Period("2020-01", freq="M"),
            },
            {
                "decision_month": pd.Period("2020-04", freq="M"),
                "formation_date": pd.Timestamp("2020-03-31"),
                "formation_timestamp": pd.Timestamp(
                    "2020-04-01T00:00:00", tz="Asia/Kolkata"
                ),
                "window_start_month": pd.Period("2019-04", freq="M"),
                "window_end_month": pd.Period("2020-02", freq="M"),
            },
        ]
    )

    _, timing, gate = build_timing_audit(delayed, formations)

    assert not gate
    assert not timing.iloc[0]["formation_safe"]
    assert timing.iloc[0]["unsafe_reason"] == "PARTIAL_ECONOMIC_EVENT_IN_WINDOW"
    assert timing.iloc[1]["formation_safe"]


def test_end_to_end_outputs_and_preserves_accepted_artifact():
    before = file_sha256(TREATMENTS)
    delayed, timing, gate = run()
    after = file_sha256(TREATMENTS)

    event_status = delayed.groupby("event_id")["signal_safe"].first().to_dict()
    assert not gate
    assert event_status["CA_faa277a19bfa2ac115cc"]
    assert event_status["CA_df82d8fc43ad7e21c2a8"]
    assert not event_status["CA_52dafdfb28d9f35d7326"]
    assert not event_status["CA_9d29c825ee80b650567a"]
    assert timing["unsafe_reason"].eq("PARTIAL_ECONOMIC_EVENT_IN_WINDOW").any()
    assert before == after == ACCEPTED_TREATMENT_SHA256
