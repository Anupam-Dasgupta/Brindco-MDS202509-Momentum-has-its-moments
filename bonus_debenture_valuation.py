"""Audit the four mandatory bonus-debenture entitlement events.

This stage is intentionally separate from equity-return and panel construction.
It values an entitlement only when contractual terms and a convention-consistent
market yield were knowable by the equity ex-date.  Otherwise it records the
missing evidence and leaves the parent event blocking.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from corporate_action_treatment import (
    AUDIT_DIR,
    DATA_CUTOFF,
    EVIDENCE_MANIFEST,
    OUTPUT_DIR,
    PARENT_EVENTS,
    ROOT,
    TREATED_ACTIONS,
    TREATMENTS,
    evidence_manifest,
    validate_treatments,
    write_audits,
)


DETAIL_OUTPUT = AUDIT_DIR / "bonus_debenture_valuation_detail.csv"
SENSITIVITY_OUTPUT = AUDIT_DIR / "bonus_debenture_valuation_sensitivity.csv"
YIELD_CANDIDATES_OUTPUT = AUDIT_DIR / "bonus_debenture_yield_proxy_candidates.csv"
IMMUTABILITY_OUTPUT = AUDIT_DIR / "non_target_treatment_immutability_audit.csv"

TARGET_EVENT_IDS = {
    "CA_faa277a19bfa2ac115cc",
    "CA_df82d8fc43ad7e21c2a8",
    "CA_52dafdfb28d9f35d7326",
    "CA_9d29c825ee80b650567a",
}

ACCEPTED_TREATMENT_COLUMNS = [
    "event_id",
    "treatment_status",
    "cash_per_pre_event_share",
    "share_multiplier",
    "entitlement_value_per_pre_event_share",
    "cash_unit_basis",
    "valuation_date",
    "valuation_method",
    "is_mandatory",
    "blocks_total_return",
    "evidence_source",
    "effective_date",
    "security_id",
    "parent_event_class",
    "treatment_notes",
    "event_mechanism",
    "assumption_code",
    "assumption_requires_approval",
    "no_direct_adjustment_component",
    "rights_new_shares_per_old_share",
    "rights_subscription_price",
    "previous_close",
    "ex_date_close",
    "market_symbol",
    "market_isin",
    "market_series",
    "rights_entitlement_symbol",
    "rights_entitlement_observed",
    "rights_entitlement_first_seen",
    "rights_entitlement_last_seen",
    "treatment_row_id",
]

# Canonical hash of the 145 accepted non-target rows before this task.  It is
# independent of Parquet metadata and protects every accepted treatment column.
ACCEPTED_NON_TARGET_SHA256 = (
    "cf35ac4481c82d3da7dcfca58e01e605d747b1dfd44aaf320d974dfc2602721d"
)


EVENT_REVIEWS = {
    "CA_faa277a19bfa2ac115cc": {
        "symbol": "BLUEDART",
        "term_knowledge_status": (
            "BLOCKED_COUPONS_AND_ALLOTMENT_DATE_NOT_FIXED_IN_PRE_EX_OFFICIAL_EVIDENCE"
        ),
        "missing_evidence": (
            "An issuer or exchange record proving the three coupon rates and the "
            "allotment date were legally fixed no later than 2014-11-17."
        ),
        "evidence_source": (
            "LOCAL_NSE_CA_API:corporate_actions_20141101_20141130.json;"
            "BLUEDART_BONUS_DEBENTURE_TERMS;BLUEDART_AR_2014_15;"
            "NSE_BLUEDART_LISTING_2014_11_26;FIMMDA_VALUATION_CIRCULAR_2012"
        ),
        "treatment_notes": (
            "The pre-ex-date issuer release fixes quantities, face value, annual "
            "frequency and tenor, but says the Board will determine the coupons. "
            "The preserved official sources that state 9.3%, 9.4% and 9.5% are "
            "post-ex-date and do not establish when those rates or the allotment "
            "date became legally fixed. Contractual cash flows therefore cannot be "
            "constructed point in time; no yield or value is selected."
        ),
        "tranches": [
            {
                "tranche_id": "SERIES_I",
                "debenture_isin": "INE233B08087",
                "quantity_per_pre_event_share": 7.0,
                "face_value": 10.0,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 36,
                "subsequently_observed_coupon_rate": 0.093,
                "subsequently_observed_maturity_date": "2017-11-20",
            },
            {
                "tranche_id": "SERIES_II",
                "debenture_isin": "INE233B08095",
                "quantity_per_pre_event_share": 4.0,
                "face_value": 10.0,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 48,
                "subsequently_observed_coupon_rate": 0.094,
                "subsequently_observed_maturity_date": "2018-11-20",
            },
            {
                "tranche_id": "SERIES_III",
                "debenture_isin": "INE233B08103",
                "quantity_per_pre_event_share": 3.0,
                "face_value": 10.0,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 60,
                "subsequently_observed_coupon_rate": 0.095,
                "subsequently_observed_maturity_date": "2019-11-20",
            },
        ],
    },
    "CA_df82d8fc43ad7e21c2a8": {
        "symbol": "NTPC",
        "term_knowledge_status": (
            "BLOCKED_COUPON_DISCLOSED_AFTER_EQUITY_EX_DATE_CLOSE"
        ),
        "missing_evidence": (
            "No evidence can make the coupon point-in-time: the official BSE archive "
            "timestamps public disclosure of the 8.49% coupon at 19:47:23 on "
            "2015-03-20, after the equity market close used for that day's return."
        ),
        "evidence_source": (
            "LOCAL_NSE_CA_API:corporate_actions_20150301_20150331.json;"
            "BSE_NTPC_COUPON_ANNOUNCEMENT_2015_03_20;"
            "NTPC_BONUS_DEBENTURE_TRANSCRIPT;NTPC_PIB_RELEASE_2015_03_26;"
            "NSE_NTPC_LISTING_2015_03_27;FIMMDA_VALUATION_CIRCULAR_2012"
        ),
        "treatment_notes": (
            "The official BSE archive timestamps public disclosure of the 8.49% "
            "coupon at 19:47:23 on 2015-03-20, after the equity market close used "
            "for the ex-date return. The coupon was therefore not a knowable input "
            "to that closing valuation. Contractual cash flows cannot be constructed "
            "point in time; no yield or value is selected."
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "debenture_isin": "INE733E07JP6",
                "quantity_per_pre_event_share": 1.0,
                "face_value": 12.5,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 120,
                "subsequently_observed_coupon_rate": 0.0849,
                "subsequently_observed_maturity_date": "2025-03-25",
            }
        ],
    },
    "CA_52dafdfb28d9f35d7326": {
        "symbol": "BRITANNIA",
        "term_knowledge_status": "BLOCKED_COUPON_FIXED_AFTER_EQUITY_EX_DATE",
        "missing_evidence": (
            "No evidence can make the coupon point-in-time: the official scheme "
            "states that the Board determines it on the 2019-08-23 record date, one "
            "day after the equity ex-date."
        ),
        "evidence_source": (
            "LOCAL_NSE_CA_API:corporate_actions_20190801_20190831.json;"
            "BRITANNIA_IM_2019;BRITANNIA_ALLOTMENT_2019_08_28;"
            "BRITANNIA_AR_2021_22_2019_EVENT;FIMMDA_VALUATION_CIRCULAR_2012"
        ),
        "treatment_notes": (
            "The official scheme says the Board determines the coupon on the "
            "2019-08-23 record date, after the 2019-08-22 equity ex-date. The later "
            "8% coupon and 2019-08-28 allotment date are hindsight inputs for this "
            "valuation date. Contractual cash flows therefore cannot be constructed "
            "point in time; no yield or value is selected."
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "debenture_isin": "INE216A07052",
                "quantity_per_pre_event_share": 1.0,
                "face_value": 30.0,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 36,
                "subsequently_observed_coupon_rate": 0.08,
                "subsequently_observed_maturity_date": "2022-08-28",
            }
        ],
    },
    "CA_9d29c825ee80b650567a": {
        "symbol": "BRITANNIA",
        "term_knowledge_status": "BLOCKED_COUPON_FIXED_AFTER_EQUITY_EX_DATE",
        "missing_evidence": (
            "No evidence can make the coupon point-in-time: the 2021-05-21 official "
            "terms leave it to a later Board decision, and the 5.5% coupon was fixed "
            "with allotment on 2021-06-03."
        ),
        "evidence_source": (
            "LOCAL_NSE_CA_API:corporate_actions_20210501_20210531.json;"
            "BRITANNIA_TERMS_2021_05_21;BRITANNIA_ALLOTMENT_2021_06_03;"
            "BRITANNIA_AR_2021_22_2021_EVENT;FIMMDA_VALUATION_CIRCULAR_2012"
        ),
        "treatment_notes": (
            "The 2021-05-21 official terms state that the Board will determine the "
            "coupon after scheme approval and before allotment. The 5.5% coupon and "
            "2021-06-03 allotment date were fixed after the 2021-05-25 equity "
            "ex-date. Contractual cash flows therefore cannot be constructed point "
            "in time; no yield or value is selected."
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "debenture_isin": "INE216A08027",
                "quantity_per_pre_event_share": 1.0,
                "face_value": 29.0,
                "coupon_frequency": "ANNUAL",
                "tenor_months": 36,
                "subsequently_observed_coupon_rate": 0.055,
                "subsequently_observed_maturity_date": "2024-06-03",
            }
        ],
    },
}


def convert_to_annual_effective_yield(
    quoted_yield: float,
    quoted_yield_convention: str,
    compounding_frequency: int | None = None,
) -> tuple[float, str]:
    """Convert a supported quoted yield to the annual-effective convention."""

    if not np.isfinite(quoted_yield) or quoted_yield <= -1:
        raise ValueError("Quoted yield must be finite and greater than -100%")
    convention = quoted_yield_convention.upper()
    if convention == "ANNUAL_EFFECTIVE":
        return float(quoted_yield), "IDENTITY_ANNUAL_EFFECTIVE"
    if convention in {"NOMINAL_COMPOUNDED", "BOND_EQUIVALENT"}:
        if not compounding_frequency or compounding_frequency < 1:
            raise ValueError("A positive compounding frequency is required")
        converted = (1.0 + quoted_yield / compounding_frequency) ** (
            compounding_frequency
        ) - 1.0
        return float(converted), f"NOMINAL_M{compounding_frequency}_TO_ANNUAL_EFFECTIVE"
    raise ValueError("Yield convention is not established")


def validate_yield_observation_date(
    yield_observation_date: str | pd.Timestamp,
    equity_ex_date: str | pd.Timestamp,
) -> None:
    if pd.Timestamp(yield_observation_date) > pd.Timestamp(equity_ex_date):
        raise ValueError("A future yield observation cannot be used")


def present_value_cash_flows(
    contractual_cash_flows: Iterable[dict[str, object]],
    valuation_date: str | pd.Timestamp,
    annual_effective_yield: float,
) -> float:
    """Discount explicit future cash flows using Actual/365 year fractions."""

    if not np.isfinite(annual_effective_yield) or annual_effective_yield <= -1:
        raise ValueError("Annual-effective yield must exceed -100%")
    valuation_date = pd.Timestamp(valuation_date)
    value = 0.0
    count = 0
    for cash_flow in contractual_cash_flows:
        cash_flow_date = pd.Timestamp(cash_flow["date"])
        amount = float(cash_flow["amount"])
        if cash_flow_date <= valuation_date:
            raise ValueError("Contractual cash flows must follow the valuation date")
        if not np.isfinite(amount):
            raise ValueError("Cash-flow amount must be finite")
        year_fraction = (cash_flow_date - valuation_date).days / 365.0
        value += amount / (1.0 + annual_effective_yield) ** year_fraction
        count += 1
    if count == 0:
        raise ValueError("At least one contractual cash flow is required")
    return float(value)


def build_fixed_coupon_cash_flows(
    face_value: float,
    annual_coupon_rate: float,
    coupon_dates: Iterable[str | pd.Timestamp],
    principal_schedule: dict[str | pd.Timestamp, float],
    coupon_frequency: int = 1,
) -> list[dict[str, object]]:
    """Build regular coupon flows, paying principal after coupon on each date."""

    if face_value <= 0 or coupon_frequency < 1:
        raise ValueError("Face value and coupon frequency must be positive")
    principal = {pd.Timestamp(date): float(amount) for date, amount in principal_schedule.items()}
    if not np.isclose(sum(principal.values()), face_value):
        raise ValueError("Principal schedule must sum to face value")

    outstanding = float(face_value)
    rows = []
    coupon_dates = sorted(pd.Timestamp(date) for date in coupon_dates)
    for date in coupon_dates:
        coupon = outstanding * annual_coupon_rate / coupon_frequency
        redemption = principal.get(date, 0.0)
        rows.append(
            {
                "date": date,
                "coupon": float(coupon),
                "principal": float(redemption),
                "amount": float(coupon + redemption),
            }
        )
        outstanding -= redemption
    missing_redemptions = set(principal) - set(coupon_dates)
    if missing_redemptions:
        raise ValueError("Every principal date must also be a coupon date")
    if not np.isclose(outstanding, 0.0):
        raise ValueError("Principal was not fully redeemed")
    return rows


def aggregate_entitlement_value(
    tranche_values: Iterable[tuple[float, float]],
) -> float:
    """Aggregate (quantity per old share, per-debenture value) pairs."""

    total = 0.0
    for quantity, value in tranche_values:
        if quantity < 0 or not np.isfinite(quantity) or not np.isfinite(value):
            raise ValueError("Quantities and values must be finite and nonnegative")
        total += quantity * value
    return float(total)


def select_yield_proxy(
    candidates: pd.DataFrame,
    *,
    equity_ex_date: str | pd.Timestamp,
    issuer: str,
    seniority: str,
    credit_rating: str,
    residual_maturity_years: float,
    material_yield_difference_bps: float = 25.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Apply the approved proxy hierarchy and return a full candidate audit."""

    required = {
        "candidate_id",
        "evidence_level",
        "issuer",
        "seniority",
        "credit_rating",
        "residual_maturity_years",
        "yield_observation_date",
        "quoted_yield",
    }
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"Missing yield-candidate columns: {missing}")
    if candidates.empty:
        raise ValueError("No yield candidates are available")

    audited = candidates.copy()
    audited["yield_observation_date"] = pd.to_datetime(
        audited["yield_observation_date"]
    )
    ex_date = pd.Timestamp(equity_ex_date)
    audited["eligible_on_date"] = audited["yield_observation_date"].le(ex_date)
    audited["same_issuer"] = audited["issuer"].str.casefold().eq(issuer.casefold())
    audited["same_seniority"] = (
        audited["seniority"].str.casefold().eq(seniority.casefold())
    )
    audited["same_rating"] = (
        audited["credit_rating"].str.casefold().eq(credit_rating.casefold())
    )
    audited["maturity_difference"] = (
        pd.to_numeric(audited["residual_maturity_years"], errors="raise")
        - residual_maturity_years
    ).abs()
    audited["selection_status"] = "INELIGIBLE_FUTURE_OBSERVATION"

    eligible = audited[audited["eligible_on_date"]].copy()
    if eligible.empty:
        raise ValueError("All yield candidates are dated after the equity ex-date")
    best_level = eligible["evidence_level"].min()
    eligible = eligible[eligible["evidence_level"].eq(best_level)].copy()
    eligible = eligible.sort_values(
        [
            "same_issuer",
            "same_seniority",
            "same_rating",
            "maturity_difference",
            "yield_observation_date",
            "candidate_id",
        ],
        ascending=[False, False, False, True, False, True],
        kind="stable",
    )
    selected = eligible.iloc[0]
    equivalent = eligible[
        eligible["same_issuer"].eq(selected["same_issuer"])
        & eligible["same_seniority"].eq(selected["same_seniority"])
        & eligible["same_rating"].eq(selected["same_rating"])
        & eligible["maturity_difference"].eq(selected["maturity_difference"])
        & eligible["yield_observation_date"].eq(selected["yield_observation_date"])
    ]
    dispersion_bps = (
        equivalent["quoted_yield"].max() - equivalent["quoted_yield"].min()
    ) * 10_000
    if len(equivalent) > 1 and dispersion_bps > material_yield_difference_bps:
        raise ValueError("Equally defensible proxies have materially different yields")

    audited.loc[audited["eligible_on_date"], "selection_status"] = (
        "ELIGIBLE_NOT_SELECTED"
    )
    audited.loc[
        audited["candidate_id"].eq(selected["candidate_id"]), "selection_status"
    ] = "SELECTED"
    audited["selection_reason"] = ""
    audited.loc[
        audited["candidate_id"].eq(selected["candidate_id"]), "selection_reason"
    ] = (
        "Lowest evidence level; then same issuer, seniority and rating; closest "
        "residual maturity; latest observation on or before the ex-date."
    )
    return selected, audited


def _normalized_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def canonical_rows_hash(frame: pd.DataFrame) -> str:
    ordered = frame[ACCEPTED_TREATMENT_COLUMNS].sort_values("event_id")
    records = [
        {column: _normalized_scalar(row[column]) for column in ACCEPTED_TREATMENT_COLUMNS}
        for _, row in ordered.iterrows()
    ]
    payload = json.dumps(
        records, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def row_hashes(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.sort_values("event_id").iterrows():
        record = {
            column: _normalized_scalar(row[column])
            for column in ACCEPTED_TREATMENT_COLUMNS
        }
        payload = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        rows.append(
            {
                "event_id": row["event_id"],
                "accepted_columns_sha256": hashlib.sha256(
                    payload.encode("utf-8")
                ).hexdigest(),
            }
        )
    return pd.DataFrame(rows)


def build_valuation_detail(treatments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    indexed = treatments.set_index("event_id")
    for event_id, review in EVENT_REVIEWS.items():
        parent = indexed.loc[event_id]
        for tranche in review["tranches"]:
            rows.append(
                {
                    "event_id": event_id,
                    "security_id": parent["security_id"],
                    "symbol": review["symbol"],
                    "equity_ex_date": parent["effective_date"],
                    **tranche,
                    "coupon_rate": np.nan,
                    "maturity_date": pd.NaT,
                    "contractual_cash_flows": "",
                    "quoted_yield": np.nan,
                    "quoted_yield_convention": "",
                    "compounding_frequency": np.nan,
                    "converted_annual_effective_yield": np.nan,
                    "conversion_method": "",
                    "selected_market_yield": np.nan,
                    "yield_source": "",
                    "yield_observation_date": pd.NaT,
                    "yield_selection_method": (
                        "NOT_ATTEMPTED_CONTRACTUAL_TERMS_GATE_FAILED"
                    ),
                    "credit_rating": "",
                    "valuation_method": (
                        "NOT_PERFORMED_POINT_IN_TIME_CONTRACTUAL_TERMS_INCOMPLETE"
                    ),
                    "modeled_debenture_value": np.nan,
                    "entitlement_value_per_pre_event_share": np.nan,
                    "term_knowledge_status": review["term_knowledge_status"],
                    "missing_evidence": review["missing_evidence"],
                    "blocks_total_return": True,
                    "evidence_source": review["evidence_source"],
                    "treatment_notes": review["treatment_notes"],
                }
            )
    detail = pd.DataFrame(rows)
    detail["equity_ex_date"] = pd.to_datetime(detail["equity_ex_date"])
    detail["maturity_date"] = pd.to_datetime(detail["maturity_date"])
    detail["subsequently_observed_maturity_date"] = pd.to_datetime(
        detail["subsequently_observed_maturity_date"]
    )
    detail["yield_observation_date"] = pd.to_datetime(
        detail["yield_observation_date"]
    )
    return detail.sort_values(["equity_ex_date", "tranche_id"]).reset_index(drop=True)


def apply_blocker_reviews(treatments: pd.DataFrame) -> pd.DataFrame:
    updated = treatments.copy()
    if set(updated.columns) != set(ACCEPTED_TREATMENT_COLUMNS):
        raise ValueError("Accepted treatment schema changed before this task")
    if set(updated.loc[updated["event_id"].isin(TARGET_EVENT_IDS), "event_id"]) != TARGET_EVENT_IDS:
        raise ValueError("The four target event IDs are not present exactly as expected")

    for event_id, review in EVENT_REVIEWS.items():
        mask = updated["event_id"].eq(event_id)
        if mask.sum() != 1:
            raise ValueError(f"Expected one treatment row for {event_id}")
        updated.loc[mask, "valuation_method"] = (
            "BLOCKED_POINT_IN_TIME_CONTRACTUAL_TERMS_INCOMPLETE"
        )
        updated.loc[mask, "evidence_source"] = review["evidence_source"]
        updated.loc[mask, "treatment_notes"] = review["treatment_notes"]
    return updated


def update_treated_actions(
    treated_actions: pd.DataFrame, treatments: pd.DataFrame
) -> pd.DataFrame:
    updated = treated_actions.copy()
    for event_id in TARGET_EVENT_IDS:
        treatment = treatments.loc[treatments["event_id"].eq(event_id)].iloc[0]
        mask = updated["event_id"].eq(event_id)
        if mask.sum() != 1:
            raise ValueError(f"Expected one treated action row for {event_id}")
        for column in ["valuation_method", "evidence_source", "treatment_notes"]:
            updated.loc[mask, column] = treatment[column]
    return updated


def empty_sensitivity_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "tranche_id",
            "equity_ex_date",
            "yield_scenario",
            "annual_effective_yield",
            "modeled_debenture_value",
            "entitlement_value_per_pre_event_share",
        ]
    )


def empty_yield_candidate_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "tranche_id",
            "candidate_id",
            "evidence_level",
            "issuer",
            "seniority",
            "credit_rating",
            "residual_maturity_years",
            "yield_observation_date",
            "quoted_yield",
            "quoted_yield_convention",
            "compounding_frequency",
            "eligible_on_date",
            "selection_status",
            "selection_reason",
        ]
    )


def append_stage_summary(
    gate: dict[str, object], protected_hash: str, detail: pd.DataFrame
) -> None:
    path = AUDIT_DIR / "corporate_action_treatment_summary.csv"
    summary = pd.read_csv(path)
    additions = pd.DataFrame(
        [
            ("protected_non_target_treatment_rows", 145),
            ("protected_non_target_rows_changed", 0),
            ("accepted_non_target_rows_sha256", protected_hash),
            ("bonus_debenture_target_events", len(TARGET_EVENT_IDS)),
            ("bonus_debenture_target_tranches", len(detail)),
            ("bonus_debenture_resolved_events", 0),
            ("bonus_debenture_blocking_events", int(detail["event_id"].nunique())),
            ("bonus_debenture_yield_candidates", 0),
            ("bonus_debenture_price_observations", 0),
            ("post_cutoff_price_or_return_observations_accessed", 0),
            ("corporate_action_gate_passes", gate["corporate_action_gate_passes"]),
        ],
        columns=["metric", "value"],
    )
    summary = summary[~summary["metric"].isin(additions["metric"])]
    pd.concat([summary, additions], ignore_index=True).to_csv(path, index=False)


def write_stage_audit(
    treatments: pd.DataFrame,
    detail: pd.DataFrame,
    manifest: pd.DataFrame,
    gate: dict[str, object],
    protected_hash: str,
) -> None:
    blockers = treatments[treatments["blocks_total_return"]]
    blocker_lines = "\n".join(
        f"- `{row.event_id}` — {EVENT_REVIEWS[row.event_id]['symbol']}, "
        f"{pd.Timestamp(row.effective_date).date()}: {row.treatment_notes}"
        for row in blockers.itertuples()
    )
    evidence_ids = {
        evidence_id
        for review in EVENT_REVIEWS.values()
        for evidence_id in review["evidence_source"].split(";")
        if not evidence_id.startswith("LOCAL_NSE_CA_API")
    }
    evidence_lines = "\n".join(
        f"- `{row.evidence_id}` — {row.authority}; `{row.local_file}`; "
        f"SHA-256 `{row.sha256}`."
        for row in manifest[manifest["evidence_id"].isin(evidence_ids)].itertuples()
    )

    audit = f"""# Corporate-action treatment audit

## Scope and result

This reopening is limited to the four mandatory bonus-debenture events. It does not read equity prices, calculate an equity return, rebuild the research panel, or alter membership, identity, series policy, strategy, performance or holdout artifacts.

- Parent treatment rows: **{len(treatments)}**
- Protected non-target rows: **145 / 145 unchanged across every accepted treatment column**
- Target events reviewed: **4**
- Target tranches reviewed: **{len(detail)}**
- Target events valued: **0**
- Events still blocking total return: **{gate['blocking_event_count']}**
- Corporate-action gate: **{'PASS' if gate['corporate_action_gate_passes'] else 'FAIL'}**

The valuation convention is sound, but it cannot be applied to these events without hindsight. Every event fails the contractual-terms gate before yield selection. The NTPC and two Britannia failures are conclusive because official records place coupon disclosure or determination after the relevant equity close. The preserved official Blue Dart evidence does not prove all contractual cash-flow terms were fixed by the ex-date.

## Literal gate

```sql
corporate_action_gate_passes =
    count(distinct event_id with exactly one parent treatment) == 149
    AND count(event_id where blocks_total_return == true) == 0
```

- Distinct event IDs with exactly one treatment: **{gate['distinct_parent_event_ids_with_exactly_one_treatment']}**
- Duplicated parent event IDs: **{gate['duplicated_parent_event_id_count']}**
- Duplicated treatment event IDs: **{gate['duplicated_treatment_event_id_count']}**
- Missing event IDs: **{gate['missing_event_id_count']}**
- Treatment rows without a valid parent event ID: **{gate['orphan_treatment_count']}**
- Blocking event IDs: **{gate['blocking_event_count']}**

## Point-in-time findings

- **Blue Dart, 2014-11-17:** the 2013 issuer release fixes 7/4/3 debentures, Rs 10 face values, annual coupons and 36/48/60-month tenors, but says the Board will determine the coupon rates. The 9.3%/9.4%/9.5% rates and 2014-11-21 allotment date appear in preserved official post-ex-date sources. No pre/ex-date primary record was found that establishes when those inputs became fixed.
- **NTPC, 2015-03-20:** the official BSE announcement archive timestamps disclosure of the 8.49% fixed coupon at 19:47:23 on the ex-date, after the equity market close used for that day's return. The coupon was therefore unavailable for the closing valuation. Later primary sources confirm one Rs 12.50 debenture and 20%/40%/40% staged principal redemption.
- **Britannia, 2019-08-22:** the official scheme states that the Board determines the coupon on the 2019-08-23 record date. The later 8% coupon and 2019-08-28 allotment date cannot be used for the prior ex-date.
- **Britannia, 2021-05-25:** the 2021-05-21 exchange filing states that the Board will determine the coupon after scheme approval and before allotment. The official allotment filing fixes 5.5% and the 2021-06-03 allotment date after the ex-date.

`bonus_debenture_valuation_detail.csv` preserves the terms that were fixed before the ex-date separately from terms observed later. The point-in-time `coupon_rate`, `maturity_date`, contractual cash flows, selected yield and modeled value remain null. This prevents the later terms from entering an earlier return.

## Yield and discount convention

The implemented valuation functions require an explicit quoted-yield convention and convert supported nominal quotations to annual-effective yield before discounting. A yield with unknown convention is rejected. Candidate selection follows evidence level, same issuer, same seniority, same rating valid on the ex-date, nearest residual maturity, and latest observation on or before the ex-date. Materially different equally ranked proxies cause a blocker.

FIMMDA's official methodology supports rating/tenor matrices for untraded bonds, linear interpolation across intermediate tenors, a maximum 15-day lookback for qualifying issuer traded spreads, and weighted-average maturity for staggered principal. No proxy search was allowed to manufacture value after the contractual-terms gate failed, so the yield-candidate and sensitivity outputs contain headers and zero observations.

## Immutability and data access

- Accepted non-target canonical SHA-256: `{protected_hash}`
- Non-target rows changed: **0**
- Equity price observations read: **0**
- Equity returns calculated: **0**
- Post-2023-03-31 price/return observations read: **0**

The accepted treatment artifact remains the input and output location. Only `valuation_method`, `evidence_source`, and `treatment_notes` changed for the four authorized event IDs. The other 145 rows compare equal over all {len(ACCEPTED_TREATMENT_COLUMNS)} accepted columns.

## Remaining blockers

{blocker_lines}

The gate remains failed. Resolving Blue Dart requires missing primary point-in-time term evidence and then a convention-specified contemporaneous yield. NTPC and the two Britannia events cannot be resolved at the specified equity close under this convention because their coupon disclosure or determination occurred later.

## Preserved official evidence

{evidence_lines}

Each preserved file is represented in `corporate_action_evidence_manifest.csv` with its source URL, authority, retrieval timestamp, byte count, SHA-256, date fields, relevant terms and review status.

## Outputs

- `data/processed/corporate_action_treatment/in_universe_event_treatments.parquet`
- `data/processed/corporate_action_treatment/nse_corporate_actions_treated_through_2023_03_31.parquet`
- `data/processed/corporate_action_treatment/corporate_action_evidence_manifest.csv`
- `results/corporate_action_treatment/bonus_debenture_valuation_detail.csv`
- `results/corporate_action_treatment/bonus_debenture_valuation_sensitivity.csv`
- `results/corporate_action_treatment/bonus_debenture_yield_proxy_candidates.csv`
- `results/corporate_action_treatment/non_target_treatment_immutability_audit.csv`
- regenerated corporate-action summary, detail, unresolved and no-direct-adjustment audits
"""
    (ROOT / "CORPORATE_ACTION_TREATMENT_AUDIT.md").write_text(
        audit, encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("Reading the accepted treatment artifacts...")
    treatments_before = pd.read_parquet(TREATMENTS)
    parents = pd.read_parquet(PARENT_EVENTS)
    treated_actions = pd.read_parquet(TREATED_ACTIONS)
    if treated_actions["ex_date"].max() > DATA_CUTOFF:
        raise ValueError("Treated corporate-action input exceeds the research cutoff")

    non_target_before = treatments_before[
        ~treatments_before["event_id"].isin(TARGET_EVENT_IDS)
    ]
    protected_hash = canonical_rows_hash(non_target_before)
    if protected_hash != ACCEPTED_NON_TARGET_SHA256:
        raise ValueError("The 145 accepted non-target treatments changed before this task")
    before_hashes = row_hashes(non_target_before).rename(
        columns={"accepted_columns_sha256": "before_sha256"}
    )

    detail = build_valuation_detail(treatments_before)
    treatments_after = apply_blocker_reviews(treatments_before)
    non_target_after = treatments_after[
        ~treatments_after["event_id"].isin(TARGET_EVENT_IDS)
    ]
    after_hash = canonical_rows_hash(non_target_after)
    if after_hash != protected_hash:
        raise ValueError("A protected non-target treatment row changed")
    after_hashes = row_hashes(non_target_after).rename(
        columns={"accepted_columns_sha256": "after_sha256"}
    )
    immutability = before_hashes.merge(after_hashes, on="event_id", validate="one_to_one")
    immutability["rows_equal"] = immutability["before_sha256"].eq(
        immutability["after_sha256"]
    )
    if len(immutability) != 145 or not immutability["rows_equal"].all():
        raise ValueError("Non-target treatment immutability audit failed")

    gate = validate_treatments(parents, treatments_after)
    manifest = evidence_manifest()
    treated_after = update_treated_actions(treated_actions, treatments_after)

    print("Writing blocker, provenance and immutability audits...")
    treatments_after.to_parquet(TREATMENTS, index=False)
    treated_after.to_parquet(TREATED_ACTIONS, index=False)
    manifest.to_csv(EVIDENCE_MANIFEST, index=False)
    detail.to_csv(DETAIL_OUTPUT, index=False)
    empty_sensitivity_table().to_csv(SENSITIVITY_OUTPUT, index=False)
    empty_yield_candidate_table().to_csv(YIELD_CANDIDATES_OUTPUT, index=False)
    immutability.to_csv(IMMUTABILITY_OUTPUT, index=False)
    write_audits(parents, treatments_after, manifest, gate)
    append_stage_summary(gate, protected_hash, detail)
    write_stage_audit(treatments_after, detail, manifest, gate, protected_hash)

    print(f"Parent treatments: {len(treatments_after)}")
    print("Protected non-target treatments changed: 0")
    print("Bonus-debenture target events valued: 0")
    print(f"Blocking events: {gate['blocking_event_count']}")
    print("Equity price observations read: 0")
    print(
        "Corporate-action gate: "
        + ("PASS" if gate["corporate_action_gate_passes"] else "FAIL")
    )


if __name__ == "__main__":
    main()
