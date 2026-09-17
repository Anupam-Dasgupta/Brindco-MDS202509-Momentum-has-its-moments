from pathlib import Path

import pandas as pd

from membership_rebuild import CUTOFF, ROOT, START_DATE, sha256


MEMBERSHIP_DIR = ROOT / "data" / "processed" / "membership_official"
IDENTITY_DIR = ROOT / "data" / "processed" / "security_identity_official"
ACTION_DIR = ROOT / "data" / "processed" / "corporate_actions_official"
AUDIT_DIR = ROOT / "results" / "membership_rebuild_audit"


def read_membership() -> pd.DataFrame:
    return pd.read_parquet(
        MEMBERSHIP_DIR / "nifty500_official_membership_intervals.parquet"
    )


def test_official_seed_and_evidence_manifest_are_complete():
    seed = pd.read_parquet(MEMBERSHIP_DIR / "nifty500_official_seed.parquet")
    assert seed["as_of_date"].nunique() == 1
    assert seed["as_of_date"].iloc[0] == START_DATE
    assert len(seed) == 500
    assert seed["symbol"].nunique() == 500

    manifest = pd.read_csv(MEMBERSHIP_DIR / "membership_evidence_manifest.csv")
    assert manifest["source_url"].fillna("").ne("").all()
    assert manifest["retrieval_status"].eq("OK").all()
    notices = manifest[manifest["document_type"].eq("index_change_notice")]
    assert notices["publication_date"].notna().all()
    assert notices["parse_status"].ne("ERROR").all()
    assert notices.loc[
        notices["parsed_event_rows"].gt(0), "effective_date_candidates"
    ].notna().all()
    for row in manifest.itertuples(index=False):
        path = ROOT / row.local_path
        assert path.exists()
        assert path.stat().st_size == row.byte_count
        assert sha256(path) == row.sha256


def test_authoritative_events_have_valid_effective_dates_and_sources():
    events = pd.read_parquet(MEMBERSHIP_DIR / "nifty500_authoritative_events.parquet")
    assert not events.duplicated(["effective_date", "action", "symbol"]).any()
    assert events["effective_date"].gt(START_DATE).all()
    assert events["effective_date"].le(CUTOFF).all()
    assert events["publication_date"].le(events["effective_date"]).all()
    assert events["action"].isin(["INCLUDE", "EXCLUDE"]).all()
    for source_file in events["source_file"].unique():
        assert (ROOT / "data" / "raw" / "membership_official" / "notices" / source_file).exists()


def test_membership_intervals_are_half_open_and_non_overlapping():
    membership = read_membership().sort_values(["security_id", "valid_from"])
    assert membership["valid_from"].ge(START_DATE).all()
    assert membership["valid_from"].le(CUTOFF).all()
    for _, group in membership.groupby("security_id"):
        ordered = group.sort_values("valid_from")
        previous_to = ordered["valid_to"].shift()
        assert (previous_to.dropna() <= ordered.loc[previous_to.notna(), "valid_from"]).all()


def test_event_arithmetic_and_official_snapshot_reconciliation():
    applications = pd.read_csv(AUDIT_DIR / "membership_event_application.csv")
    counts = pd.read_csv(AUDIT_DIR / "membership_event_counts.csv")
    snapshots = pd.read_csv(AUDIT_DIR / "official_snapshot_reconciliation.csv")
    assert applications["application_status"].eq("APPLIED").all()
    assert (
        counts["count_before"] - counts["exclusions"] + counts["inclusions"]
        == counts["count_after"]
    ).all()
    assert counts["count_after"].between(500, 501).all()
    assert counts["application_issues"].eq(0).all()
    assert snapshots["unresolved_snapshot_symbols"].eq(0).all()
    assert snapshots["symmetric_difference_count"].eq(0).all()


def test_no_impossible_prelisting_membership_and_known_ipos_pass():
    audit = pd.read_csv(AUDIT_DIR / "official_membership_prelisting_audit.csv")
    assert not audit["status"].eq("FAIL_PRELISTING").any()
    assert not audit["status"].eq("REVIEW_BEFORE_FIRST_OBSERVATION").any()

    dated = pd.read_parquet(IDENTITY_DIR / "dated_security_identity.parquet")
    membership = read_membership()
    known_aliases = {
        "ALKEM": ["ALKEM"],
        "ANGELONE": ["ANGELONE", "ANGELBRKG"],
        "INDIGO": ["INDIGO"],
        "LALPATHLAB": ["LALPATHLAB"],
        "SYNGENE": ["SYNGENE"],
    }
    for aliases in known_aliases.values():
        identity_rows = dated[dated["symbol"].isin(aliases)]
        assert not identity_rows.empty
        security_ids = set(identity_rows["security_id"])
        member_rows = membership[membership["security_id"].isin(security_ids)]
        assert not member_rows.empty
        assert member_rows["valid_from"].min() >= identity_rows["first_seen"].min()


def test_identity_and_series_rules_are_dated_and_unambiguous_for_membership():
    identity = pd.read_parquet(IDENTITY_DIR / "dated_security_identity.parquet")
    collisions = pd.read_csv(IDENTITY_DIR / "dated_alias_collisions.csv")
    series = pd.read_parquet(IDENTITY_DIR / "historical_series_classification.parquet")
    event_mapping = pd.read_csv(AUDIT_DIR / "official_event_identity_mapping.csv")
    seed_mapping = pd.read_csv(AUDIT_DIR / "official_seed_identity_mapping.csv")

    assert identity["last_seen"].le(CUTOFF).all()
    assert collisions.empty
    assert event_mapping["security_id"].notna().all()
    assert seed_mapping["security_id"].notna().all()
    assert series.loc[series["series"].eq("EQ"), "is_eligible_common_equity"].all()
    rights = series[
        series["series"].isin(["BE", "BZ"])
        & series["symbol"].str.match(r".*-RE\d*$", na=False)
    ]
    assert not rights["is_eligible_common_equity"].any()


def test_corporate_action_repairs_and_cutoff():
    actions = pd.read_parquet(
        ACTION_DIR / "nse_corporate_actions_classified_through_2023_03_31.parquet"
    )
    assert actions["ex_date"].max() <= CUTOFF

    zeel = actions[
        actions["symbol"].eq("ZEEL")
        & actions["purpose"].str.contains("Bonus Preference Shares", na=False)
    ]
    assert len(zeel) == 1
    assert not bool(zeel.iloc[0]["is_bonus"])
    assert bool(zeel.iloc[0]["is_structural"])
    assert bool(zeel.iloc[0]["needs_manual_review"])
    assert zeel.iloc[0]["primary_class"] == "PREFERENCE_SHARE_BONUS"

    genesys = actions[
        actions["symbol"].eq("GENESYS")
        & actions["purpose"].str.contains("Rs.0125", regex=False, na=False)
    ]
    assert len(genesys) == 1
    assert genesys.iloc[0]["dividend_amount"] == 0.125

    sbin = actions[
        actions["symbol"].eq("SBIN")
        & actions["purpose"].str.startswith("Face Value Split Rs.10", na=False)
    ]
    assert len(sbin) == 1
    assert sbin.iloc[0]["old_face_value_parsed"] == 10.0
    assert sbin.iloc[0]["new_face_value_parsed"] == 1.0
    assert not bool(sbin.iloc[0]["needs_manual_review"])

    jktyre = actions[
        actions["symbol"].eq("JKTYRE")
        & actions["purpose"].str.contains("Rs 0 .70", regex=False, na=False)
    ]
    assert len(jktyre) == 1
    assert jktyre.iloc[0]["dividend_amount"] == 0.70
    assert not bool(jktyre.iloc[0]["needs_manual_review"])

    debenture_entitlements = actions[
        actions["purpose"].str.contains("Bonus", case=False, na=False)
        & actions["purpose"].str.contains("Debenture", case=False, na=False)
    ]
    assert not debenture_entitlements["is_bonus"].any()
    assert debenture_entitlements["is_structural"].all()
