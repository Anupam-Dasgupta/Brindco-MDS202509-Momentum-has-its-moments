import hashlib

import numpy as np
import pandas as pd
import pytest

from brindco_momentum.data.corporate_action_treatment import (
    DATA_CUTOFF,
    EVIDENCE_MANIFEST,
    REQUIRED_TREATMENT_COLUMNS,
    ROOT,
    TREATMENTS,
    add_event_ids,
    classify_buyback,
    dividend_treatment,
    direct_terms_treatment,
    event_is_ordinary_equity_bonus,
    parse_compact_cash_amount,
    parse_rights_terms,
    read_dated_parquet,
    research_total_return,
    rights_entitlement_value,
    rights_treatment,
    validate_treatments,
)


def event_row(**overrides):
    row = {
        "event_id": "CA_TEST",
        "symbol": "TEST",
        "series": "EQ",
        "ex_date": pd.Timestamp("2020-01-02"),
        "purpose": "",
        "source_file": "fixture.csv",
        "security_id": "SEC_TEST",
        "primary_class": "BONUS",
        "is_split": False,
        "is_bonus": False,
        "is_dividend": False,
        "is_buyback": False,
        "old_face_value_parsed": np.nan,
        "new_face_value_parsed": np.nan,
        "ratio_a": np.nan,
        "ratio_b": np.nan,
        "face_value": 10.0,
        "dividend_amount": np.nan,
    }
    row.update(overrides)
    return pd.Series(row)


def test_ordinary_dividend_return_is_three_percent():
    treatment = dividend_treatment(
        event_row(
            primary_class="DIVIDEND",
            purpose="Dividend Rs 5 per share",
            is_dividend=True,
            dividend_amount=5.0,
        )
    )
    assert treatment["cash_unit_basis"] == "GROSS_DECLARED_CASH_PER_PRE_EVENT_SHARE"
    result = research_total_return(
        100.0,
        98.0,
        cash_per_pre_event_share=treatment["cash_per_pre_event_share"],
    )
    assert result == pytest.approx(0.03)


def test_two_for_one_split_has_zero_total_return():
    treatment = direct_terms_treatment(
        event_row(
            primary_class="SPLIT",
            purpose="Face value split from Rs 10 to Rs 5",
            is_split=True,
            old_face_value_parsed=10.0,
            new_face_value_parsed=5.0,
        )
    )
    result = research_total_return(
        100.0, 50.0, share_multiplier=treatment["share_multiplier"]
    )
    assert result == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("ratio_a", "ratio_b", "ex_close"),
    [(1.0, 1.0, 50.0), (1.0, 2.0, 100.0 / 1.5)],
)
def test_bonus_examples_have_zero_total_return(ratio_a, ratio_b, ex_close):
    treatment = direct_terms_treatment(
        event_row(
            purpose=f"Bonus equity shares {ratio_a:g}:{ratio_b:g}",
            is_bonus=True,
            ratio_a=ratio_a,
            ratio_b=ratio_b,
        )
    )
    result = research_total_return(
        100.0, ex_close, share_multiplier=treatment["share_multiplier"]
    )
    assert result == pytest.approx(0.0)


def test_dividend_and_bonus_are_composed_on_pre_event_share_basis():
    row = event_row(
        purpose="Bonus 1:1 and dividend Rs 5",
        is_bonus=True,
        is_dividend=True,
        ratio_a=1.0,
        ratio_b=1.0,
        dividend_amount=5.0,
    )
    treatment = direct_terms_treatment(row)
    assert treatment["share_multiplier"] == 2.0
    assert treatment["cash_per_pre_event_share"] == 5.0
    assert research_total_return(100.0, 47.5, 5.0, 2.0) == pytest.approx(0.0)


def test_dividend_and_split_are_composed_on_pre_event_share_basis():
    row = event_row(
        primary_class="SPLIT",
        purpose="Split 10 to 5 and dividend Rs 4",
        is_split=True,
        is_dividend=True,
        old_face_value_parsed=10.0,
        new_face_value_parsed=5.0,
        dividend_amount=4.0,
    )
    treatment = direct_terms_treatment(row)
    assert treatment["share_multiplier"] == 2.0
    assert treatment["cash_per_pre_event_share"] == 4.0


def test_split_and_bonus_multipliers_are_composed():
    row = event_row(
        purpose="Split 10 to 5 and bonus 1:1",
        is_split=True,
        is_bonus=True,
        old_face_value_parsed=10.0,
        new_face_value_parsed=5.0,
        ratio_a=1.0,
        ratio_b=1.0,
    )
    treatment = direct_terms_treatment(row)
    assert treatment["share_multiplier"] == 4.0


def test_preference_share_bonus_is_not_ordinary_equity_bonus():
    assert not event_is_ordinary_equity_bonus("Bonus Preference Shares 1:1")


def test_bonus_debenture_is_not_ordinary_equity_bonus():
    assert not event_is_ordinary_equity_bonus("Bonus Debenture 1:1")


def test_compact_cash_parser_preserves_leading_decimal_zeroes():
    assert parse_compact_cash_amount("Dividend Rs.0125 per share") == 0.125


def test_open_market_buyback_has_no_automatic_passive_holder_cash():
    open_market = classify_buyback("OPEN_MARKET")
    assert open_market["cash_per_pre_event_share"] == 0.0


def test_tender_buyback_records_non_participation_and_no_automatic_cash():
    tender = classify_buyback("TENDER_OFFER")
    assert tender["cash_per_pre_event_share"] == 0.0
    assert tender["assumption_code"] == "PASSIVE_HOLDER_DOES_NOT_TENDER"
    assert tender["treatment_status"] == "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT"


def test_rights_are_valued_as_entitlements_and_not_bonus_shares():
    assert not event_is_ordinary_equity_bonus("Rights issue 1:1")
    value = rights_entitlement_value(100.0, 1.0, 80.0)
    assert value == pytest.approx(10.0)
    assert research_total_return(
        100.0,
        90.0,
        share_multiplier=1.0,
        entitlement_value_per_pre_event_share=value,
    ) == pytest.approx(0.0)


def test_missing_rights_terms_remain_unresolved():
    row = event_row(primary_class="RIGHTS", purpose="Rights issue")
    terms = parse_rights_terms(row)
    assert np.isnan(terms["new_shares_per_old_share"])
    market = pd.Series(
        {
            "prev_close": 100.0,
            "ex_date_close": 100.0,
            "market_symbol": "TEST",
            "market_isin": "ISIN_TEST",
            "market_series": "EQ",
        }
    )
    treatment = rights_treatment(row, market)
    assert treatment["treatment_status"] == "UNRESOLVED_RIGHTS_TREATMENT"
    assert treatment["blocks_total_return"]


def test_structural_blocker_suppresses_total_return():
    result = research_total_return(100.0, 98.0, blocks_total_return=True)
    assert np.isnan(result)


def test_cutoff_is_applied_inside_parquet_read(tmp_path):
    path = tmp_path / "dated.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2023-03-31", "2023-04-03"]),
            "value": [1.0, 2.0],
        }
    ).to_parquet(path, index=False)
    result = read_dated_parquet(path, "date", ["date", "value"])
    assert result["date"].max() == DATA_CUTOFF
    assert result["value"].tolist() == [1.0]


def test_produced_treatment_table_satisfies_parent_integrity_contract():
    treatments = pd.read_parquet(TREATMENTS)
    parents = pd.read_parquet(
        ROOT
        / "data"
        / "processed"
        / "corporate_action_treatment"
        / "in_universe_parent_events.parquet"
    )
    gate = validate_treatments(parents, treatments)
    assert set(REQUIRED_TREATMENT_COLUMNS).issubset(treatments.columns)
    assert len(parents) == 149
    assert len(treatments) == 149
    assert gate["distinct_parent_event_ids_with_exactly_one_treatment"] == 149
    assert gate["duplicated_parent_event_id_count"] == 0
    assert gate["duplicated_treatment_event_id_count"] == 0
    assert gate["missing_event_id_count"] == 0
    assert gate["orphan_treatment_count"] == 0
    assert gate["blocking_event_count"] == 4
    assert not gate["corporate_action_gate_passes"]


def test_evidence_manifest_preserves_source_bytes_and_provenance():
    manifest = pd.read_csv(EVIDENCE_MANIFEST)
    assert manifest["evidence_id"].is_unique
    assert manifest["source_url"].fillna("").ne("").all()
    assert manifest["retrieved_at_utc"].notna().all()
    assert manifest["effective_date"].notna().all()
    assert manifest["publication_date_status"].notna().all()
    for row in manifest.itertuples(index=False):
        path = ROOT / row.local_file
        content = path.read_bytes()
        assert len(content) == row.bytes
        assert hashlib.sha256(content).hexdigest() == row.sha256
