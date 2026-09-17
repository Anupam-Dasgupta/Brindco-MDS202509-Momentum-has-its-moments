import numpy as np
import pandas as pd
import pytest

import brindco_momentum.signals.momentum_materiality as triage
from brindco_momentum.signals.momentum_signal import OLD_PANEL


@pytest.fixture(scope="module")
def outputs():
    return (
        pd.read_csv(triage.OUTPUT / "affected_signal_materiality.csv"),
        pd.read_csv(triage.OUTPUT / "unresolved_event_priority.csv"),
        pd.read_csv(triage.OUTPUT / "materiality_summary.csv").set_index("measure")["value"],
    )


def test_candidate_changes_decile_boundary_at_a_multiple_of_ten():
    known = pd.DataFrame({
        "security_id": [f"S{i:02d}" for i in range(20)],
        "momentum_score": np.arange(20, 0, -1, dtype=float),
    })
    result = triage.winner_boundary(known, "X", concurrent=1)
    assert result["eligible_count"] == 20
    assert result["winner_count"] == 2
    assert result["current_weakest_winner_score"] == 19
    assert result["current_strongest_nonwinner_score"] == 18
    assert result["winner_count_with_one_candidate"] == 3
    assert result["individual_boundary_score"] == 18
    assert result["possible_count_change"]


def test_concurrent_candidates_have_distinct_best_and_worst_boundaries():
    known = pd.DataFrame({
        "security_id": [f"S{i:02d}" for i in range(20)],
        "momentum_score": np.arange(20, 0, -1, dtype=float),
    })
    result = triage.winner_boundary(known, "S02A", concurrent=3)
    assert result["winner_count_with_all_concurrent"] == 3
    assert result["best_case_boundary_score"] == 18
    assert result["worst_case_boundary_score"] == 20
    assert result["individual_equality_selects_candidate"] is False
    assert result["best_case_equality_selects_candidate"] is False
    assert result["worst_case_equality_selects_candidate"] is False


def test_threshold_uses_ten_known_months_without_guessing_missing_month():
    assert triage.required_month_return(0.50, 1.25) == pytest.approx(0.20)
    with pytest.raises(ValueError, match="cannot support"):
        triage.required_month_return(0.50, np.nan)


def test_strict_immateriality_requires_accepted_upper_bound_and_no_seat_change():
    assert triage.classify_materiality(True, None, None, 0.10, 0.20, False) == "CANNOT_BOUND"
    assert triage.classify_materiality(True, None, 0.05, 0.10, 0.20, False) == "IMMATERIAL_TO_WINNER_SET"
    assert triage.classify_materiality(True, None, 0.05, 0.10, 0.20, True) == "CANNOT_BOUND"
    assert triage.classify_materiality(True, 0.05, 0.15, 0.10, 0.20, False) == "POSSIBLY_MATERIAL"


def test_warmup_class_is_separate_from_scored_unbounded_case():
    assert triage.classify_materiality(False, None, None, 0.10, 0.20, False) == "MATERIAL_WARMUP_ONLY"
    assert triage.classify_materiality(True, None, None, 0.10, 0.20, False) == "CANNOT_BOUND"


def test_price_only_diagnostic_leaves_missing_strict_return_missing():
    event_date = pd.Timestamp("2020-01-03")
    rows = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
        "all_event_ids": ["", "E", ""],
        "total_return_available": [True, False, True],
        "daily_total_return": [0.10, np.nan, 0.20],
        "price_return": [0.10, -0.50, 0.20],
        "previous_close": [100.0, 110.0, 55.0],
    })
    result = triage.equity_price_only_month(rows, event_date, "E", 3)
    assert result == pytest.approx(1.10 * 0.50 * 1.20 - 1)
    assert pd.isna(rows.loc[1, "daily_total_return"])
    rows.loc[2, "daily_total_return"] = np.nan
    with pytest.raises(ValueError, match="exactly one unresolved"):
        triage.equity_price_only_month(rows, event_date, "E", 3)


def test_unbounded_structural_event_is_not_declared_immaterial(outputs):
    affected, priority, _ = outputs
    tata = affected.loc[affected["symbol"].eq("TATACHEM")]
    assert not tata.empty and tata["event_type"].eq("STRUCTURAL").all()
    assert tata["materiality_class"].eq("CANNOT_BOUND").all()
    assert tata["accepted_additional_return_upper_bound"].isna().all()
    assert priority.loc[priority["symbol"].eq("TATACHEM"), "needs_further_research"].all()


def test_unresolved_event_is_grouped_across_multiple_formations(outputs):
    affected, priority, _ = outputs
    key = "CA_bc661c41f226f8cadf0f"
    rows = affected.loc[affected["event_id"].eq(key)]
    event = priority.loc[priority["event_id"].eq(key)].iloc[0]
    assert len(rows) == 8
    assert rows["formation_date"].nunique() == 8
    assert event["affected_formations"] == 8
    assert event["affected_scored_formations"] == 8
    assert event["first_affected_formation"] == rows["formation_date"].min()
    assert event["last_affected_formation"] == rows["formation_date"].max()


def test_accepted_bonus_exception_is_reconciled_but_not_reopened(outputs):
    affected, priority, summary = outputs
    assert len(affected) == 207 and len(priority) == 38
    assert summary["source_blocking_events"] == "39"
    assert summary["source_blocking_observations"] == "216"
    assert summary["accepted_britannia_exception_observations_out_of_scope"] == "9"
    assert "CA_52dafdfb28d9f35d7326" not in set(affected["event_id"])
    assert not affected["event_id"].str.contains("CA_faa277a19bfa2ac115cc|CA_df82d8fc43ad7e21c2a8").any()


def test_current_and_prospective_thresholds_reconcile_with_frozen_outputs(outputs):
    affected, _, _ = outputs
    assert affected["month_return_below_this_is_definitely_out"].le(
        affected["month_return_to_single_candidate_cutoff"] + 1e-12
    ).all()
    assert affected["month_return_to_single_candidate_cutoff"].le(
        affected["month_return_above_this_is_definitely_in"] + 1e-12
    ).all()
    assert np.allclose(
        affected["month_return_to_current_cutoff"],
        (1 + affected["current_weakest_winner_score"]) / affected["other_ten_months_gross"] - 1,
    )
    assert affected["winner_count"].eq(np.ceil(affected["eligible_count"] / 10)).all()
    assert affected["winner_count_with_one_candidate"].eq(
        np.ceil((affected["eligible_count"] + 1) / 10)
    ).all()


def test_no_hypothetical_momentum_or_rank_is_assigned(outputs):
    affected, _, _ = outputs
    assert affected["hypothetical_momentum"].isna().all()
    assert affected["hypothetical_rank"].isna().all()
    assert affected["accepted_additional_return_lower_bound"].isna().all()
    assert affected["accepted_additional_return_upper_bound"].isna().all()


def test_panel_v1_is_rejected_as_an_input():
    with pytest.raises(ValueError, match="Only authoritative"):
        triage.read_development(OLD_PANEL, ["date"], "date")


def test_read_guard_filters_synthetic_post_cutoff_data(monkeypatch, tmp_path):
    path = tmp_path / "synthetic.parquet"
    pd.DataFrame({
        "date": pd.to_datetime(["2023-03-31", "2023-04-03"]),
        "security_id": ["A", "A"], "value": [1, 999],
    }).to_parquet(path)
    monkeypatch.setattr(triage, "SOURCES", (path,))
    result = triage.read_development(path, ["date", "security_id", "value"], "date")
    assert result["date"].max() == triage.CUTOFF
    assert result["value"].tolist() == [1]


def test_final_audit_date_and_class_count_reconcile(outputs):
    affected, priority, summary = outputs
    assert affected["materiality_class"].value_counts().to_dict() == {
        "CANNOT_BOUND": 152, "MATERIAL_WARMUP_ONLY": 55
    }
    assert affected["is_scored"].sum() == 152
    assert summary["maximum_value_date_read"] == "2023-03-31"
    assert summary["unique_events_requiring_scored_research"] == "31"
    assert summary["unique_events_requiring_eventual_research_including_warmup"] == "38"
    assert priority["needs_further_research"].all()
