import hashlib

import numpy as np
import pandas as pd
import pytest

from bonus_debenture_valuation import (
    ACCEPTED_NON_TARGET_SHA256,
    AUDIT_DIR,
    DETAIL_OUTPUT,
    EVIDENCE_MANIFEST,
    IMMUTABILITY_OUTPUT,
    ROOT,
    SENSITIVITY_OUTPUT,
    TARGET_EVENT_IDS,
    TREATMENTS,
    YIELD_CANDIDATES_OUTPUT,
    aggregate_entitlement_value,
    build_fixed_coupon_cash_flows,
    canonical_rows_hash,
    convert_to_annual_effective_yield,
    present_value_cash_flows,
    select_yield_proxy,
    validate_yield_observation_date,
)
from corporate_action_treatment import DATA_CUTOFF, PARENT_EVENTS, validate_treatments


def test_deterministic_bond_present_value():
    cash_flows = [{"date": "2020-01-01", "amount": 110.0}]
    assert present_value_cash_flows(cash_flows, "2019-01-01", 0.10) == pytest.approx(
        100.0
    )


def test_quantity_per_share_aggregation():
    assert aggregate_entitlement_value([(2.0, 9.5), (0.5, 12.0)]) == pytest.approx(
        25.0
    )


def test_multiple_blue_dart_tranches_are_aggregated():
    tranche_values = [(7.0, 9.0), (4.0, 8.0), (3.0, 7.0)]
    assert aggregate_entitlement_value(tranche_values) == pytest.approx(116.0)


def test_coupon_and_principal_cash_flows_are_combined():
    flows = build_fixed_coupon_cash_flows(
        face_value=100.0,
        annual_coupon_rate=0.10,
        coupon_dates=["2021-01-01", "2022-01-01"],
        principal_schedule={"2022-01-01": 100.0},
    )
    assert flows[0]["coupon"] == pytest.approx(10.0)
    assert flows[0]["principal"] == pytest.approx(0.0)
    assert flows[1]["coupon"] == pytest.approx(10.0)
    assert flows[1]["principal"] == pytest.approx(100.0)
    assert flows[1]["amount"] == pytest.approx(110.0)


def test_staggered_principal_reduces_later_coupon_amounts():
    dates = pd.date_range("2016-03-25", periods=10, freq=pd.DateOffset(years=1))
    flows = build_fixed_coupon_cash_flows(
        face_value=12.5,
        annual_coupon_rate=0.0849,
        coupon_dates=dates,
        principal_schedule={dates[7]: 2.5, dates[8]: 5.0, dates[9]: 5.0},
    )
    assert flows[7]["coupon"] == pytest.approx(1.06125)
    assert flows[8]["coupon"] == pytest.approx(0.849)
    assert flows[9]["coupon"] == pytest.approx(0.4245)
    assert sum(flow["principal"] for flow in flows) == pytest.approx(12.5)


def test_future_yield_observation_is_rejected():
    with pytest.raises(ValueError, match="future yield"):
        validate_yield_observation_date("2020-01-03", "2020-01-02")


def test_yield_sensitivity_has_the_correct_direction():
    cash_flows = [
        {"date": "2021-01-01", "amount": 10.0},
        {"date": "2022-01-01", "amount": 110.0},
    ]
    low = present_value_cash_flows(cash_flows, "2020-01-01", 0.07)
    central = present_value_cash_flows(cash_flows, "2020-01-01", 0.08)
    high = present_value_cash_flows(cash_flows, "2020-01-01", 0.09)
    assert low > central > high


def test_nominal_yield_is_converted_before_discounting():
    converted, method = convert_to_annual_effective_yield(
        0.08, "NOMINAL_COMPOUNDED", 2
    )
    assert converted == pytest.approx((1.04**2) - 1)
    assert method == "NOMINAL_M2_TO_ANNUAL_EFFECTIVE"
    with pytest.raises(ValueError, match="not established"):
        convert_to_annual_effective_yield(0.08, "UNKNOWN")


def test_yield_proxy_selection_uses_the_approved_order():
    candidates = pd.DataFrame(
        [
            {
                "candidate_id": "older_same_issuer",
                "evidence_level": 1,
                "issuer": "Issuer A",
                "seniority": "Senior unsecured",
                "credit_rating": "AAA",
                "residual_maturity_years": 3.0,
                "yield_observation_date": "2020-01-01",
                "quoted_yield": 0.08,
            },
            {
                "candidate_id": "latest_same_issuer",
                "evidence_level": 1,
                "issuer": "Issuer A",
                "seniority": "Senior unsecured",
                "credit_rating": "AAA",
                "residual_maturity_years": 3.0,
                "yield_observation_date": "2020-01-02",
                "quoted_yield": 0.081,
            },
            {
                "candidate_id": "future",
                "evidence_level": 1,
                "issuer": "Issuer A",
                "seniority": "Senior unsecured",
                "credit_rating": "AAA",
                "residual_maturity_years": 3.0,
                "yield_observation_date": "2020-01-03",
                "quoted_yield": 0.079,
            },
        ]
    )
    selected, audit = select_yield_proxy(
        candidates,
        equity_ex_date="2020-01-02",
        issuer="Issuer A",
        seniority="Senior unsecured",
        credit_rating="AAA",
        residual_maturity_years=3.0,
    )
    assert selected["candidate_id"] == "latest_same_issuer"
    future_status = audit.loc[audit["candidate_id"].eq("future"), "selection_status"]
    assert future_status.iloc[0] == "INELIGIBLE_FUTURE_OBSERVATION"


def test_four_target_events_remain_integrated_and_blocking():
    treatments = pd.read_parquet(TREATMENTS)
    target = treatments[treatments["event_id"].isin(TARGET_EVENT_IDS)]
    assert len(target) == 4
    assert target["event_id"].is_unique
    assert target["blocks_total_return"].all()
    assert target["entitlement_value_per_pre_event_share"].isna().all()
    assert target["valuation_method"].eq(
        "BLOCKED_POINT_IN_TIME_CONTRACTUAL_TERMS_INCOMPLETE"
    ).all()


def test_parent_treatment_integrity_and_literal_gate():
    treatments = pd.read_parquet(TREATMENTS)
    parents = pd.read_parquet(PARENT_EVENTS)
    gate = validate_treatments(parents, treatments)
    assert len(parents) == 149
    assert len(treatments) == 149
    assert gate["distinct_parent_event_ids_with_exactly_one_treatment"] == 149
    assert gate["duplicated_parent_event_id_count"] == 0
    assert gate["duplicated_treatment_event_id_count"] == 0
    assert gate["missing_event_id_count"] == 0
    assert gate["orphan_treatment_count"] == 0
    assert gate["blocking_event_count"] == 4
    assert not gate["corporate_action_gate_passes"]


def test_all_145_non_target_treatments_match_the_accepted_baseline():
    treatments = pd.read_parquet(TREATMENTS)
    non_target = treatments[~treatments["event_id"].isin(TARGET_EVENT_IDS)]
    assert len(non_target) == 145
    assert canonical_rows_hash(non_target) == ACCEPTED_NON_TARGET_SHA256
    audit = pd.read_csv(IMMUTABILITY_OUTPUT)
    assert len(audit) == 145
    assert audit["rows_equal"].all()


def test_no_price_or_return_observation_was_fabricated():
    detail = pd.read_csv(DETAIL_OUTPUT)
    candidates = pd.read_csv(YIELD_CANDIDATES_OUTPUT)
    sensitivity = pd.read_csv(SENSITIVITY_OUTPUT)
    assert len(detail) == 6
    assert detail["modeled_debenture_value"].isna().all()
    assert detail["entitlement_value_per_pre_event_share"].isna().all()
    assert candidates.empty
    assert sensitivity.empty
    assert not {"previous_close", "ex_date_close", "total_return"}.intersection(
        detail.columns
    )


def test_bonus_debenture_stage_obeys_the_cutoff():
    detail = pd.read_csv(
        DETAIL_OUTPUT,
        parse_dates=["equity_ex_date", "yield_observation_date"],
    )
    assert detail["equity_ex_date"].max() <= DATA_CUTOFF
    observed = detail["yield_observation_date"].notna()
    assert (
        detail.loc[observed, "yield_observation_date"]
        <= detail.loc[observed, "equity_ex_date"]
    ).all()
    source = (ROOT / "bonus_debenture_valuation.py").read_text(encoding="utf-8")
    assert "MARKET_DATA" not in source


def test_new_evidence_manifest_rows_match_preserved_bytes():
    expected = {
        "BLUEDART_AR_2014_15",
        "NSE_BLUEDART_LISTING_2014_11_26",
        "BSE_NTPC_COUPON_ANNOUNCEMENT_2015_03_20",
        "NTPC_PIB_RELEASE_2015_03_26",
        "NSE_NTPC_LISTING_2015_03_27",
        "BRITANNIA_IM_2019",
        "BRITANNIA_ALLOTMENT_2019_08_28",
        "BRITANNIA_TERMS_2021_05_21",
        "BRITANNIA_ALLOTMENT_2021_06_03",
        "FIMMDA_VALUATION_CIRCULAR_2012",
    }
    manifest = pd.read_csv(EVIDENCE_MANIFEST)
    new_rows = manifest[manifest["evidence_id"].isin(expected)]
    assert set(new_rows["evidence_id"]) == expected
    for row in new_rows.itertuples(index=False):
        content = (ROOT / row.local_file).read_bytes()
        assert hashlib.sha256(content).hexdigest() == row.sha256
        assert len(content) == row.bytes


def test_required_regenerated_audit_outputs_exist():
    expected = [
        "corporate_action_treatment_summary.csv",
        "corporate_action_treatment_detail.csv",
        "unresolved_corporate_actions_in_universe.csv",
        "no_direct_adjustment_events.csv",
    ]
    assert all((AUDIT_DIR / name).is_file() for name in expected)
