"""Regressions for the executable-account evidence gate."""

from pathlib import Path

import pandas as pd

from account_preflight import CUTOFF, INPUTS, OUT, sha256


def test_candidate_audit_exposes_dhani_right_without_invented_sale():
    events = pd.read_csv(OUT / "candidate_corporate_actions.csv", parse_dates=["ex_date"])
    assert events["ex_date"].max() <= CUTOFF
    dhani = events.loc[events["event_id"].eq("CA_2dcc6f730654721a5203")]
    assert len(dhani) == 1
    row = dhani.iloc[0]
    assert bool(row["in_normal_window"])
    assert not bool(row["rights_entitlement_observed"])
    assert row["account_mechanics_status"] == "UNRESOLVED_ACCOUNT_RIGHTS_REALISATION"
    assert "Theoretical" in row["account_evidence_issue"]


def test_calendar_passes_and_candidate_right_does_not_block_ledger_preemptively():
    summary = pd.read_csv(OUT / "preflight_summary.csv").set_index("check")["value"]
    assert summary["settlement_calendar_verified"] == "True"
    assert summary["account_run_authorized_by_evidence"] == "True"
    assert summary["held_event_materiality_requires_chronological_run"] == "True"
    assert summary["normal_window_unresolved_account_rights"] == "1"
    assert summary["maximum_event_date_read"] == "2023-03-31"


def test_accepted_upstream_inputs_match_preflight_hashes():
    manifest = pd.read_csv(OUT / "input_manifest.csv")
    assert set(manifest["input"]) == set(INPUTS)
    for row in manifest.itertuples(index=False):
        assert Path(row.path).as_posix() == INPUTS[row.input].relative_to(INPUTS["winners"].parents[2]).as_posix()
        assert sha256(INPUTS[row.input]) == row.sha256
