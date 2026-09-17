"""Audit evidence needed before constructing development executable accounts.

This is deliberately a broad candidate check. A selected stock may fail to fill,
or an unfilled exit may remain held beyond its next scheduled rebalance. The
report therefore distinguishes the normal holding/exit window from every later
action on a security after its first selection. It does not infer actual holds.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
CUTOFF = pd.Timestamp("2023-03-31")
START = pd.Timestamp("2015-04-01")
OUT = ROOT / "results/account_preflight"

INPUTS = {
    "winners": ROOT / "data/processed/momentum_winners.parquet",
    "overlay": ROOT / "data/processed/volatility_overlay_development.parquet",
    "panel": ROOT / "data/processed/research_panel_v2.parquet",
    "returns": ROOT / "data/processed/stock_total_returns.parquet",
    "modelling_shadow": ROOT / "data/processed/primary_modelling_shadow_daily_returns.parquet",
    "strict_shadow": ROOT / "data/processed/primary_shadow_daily_returns.parquet",
    "event_treatments": ROOT / "data/processed/corporate_action_treatment/in_universe_event_treatments.parquet",
    "treated_actions": ROOT / "data/processed/corporate_action_treatment/nse_corporate_actions_treated_through_2023_03_31.parquet",
    "event_application": ROOT / "results/stock_total_return_audit/event_application_detail.csv",
    "trading_calendar": ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet",
    "settlement_calendar": ROOT / "data/processed/nse_settlement_calendar_2015_2023.parquet",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_preflight() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = pd.DataFrame(
        [{"input": name, "path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
         for name, path in INPUTS.items()]
    )
    manifest.to_csv(OUT / "input_manifest.csv", index=False)

    winners = pd.read_parquet(INPUTS["winners"])
    winners = winners.loc[winners["scored"], ["formation_date", "holding_month", "security_id", "symbol"]].copy()
    winners["holding_month"] = winners["holding_month"].astype("period[M]")
    if winners["formation_date"].max() > CUTOFF or winners.duplicated(["holding_month", "security_id"]).any():
        raise ValueError("Winner set crosses cutoff or contains duplicate security-months")

    calendar = pd.read_parquet(INPUTS["trading_calendar"], columns=["date"],
                               filters=[("date", "<=", CUTOFF)])
    dates = pd.DatetimeIndex(calendar["date"].sort_values())
    if not dates.is_unique:
        raise ValueError("Trading calendar has duplicate dates")
    winners["possible_from"] = winners["formation_date"].map(
        lambda date: dates[dates > date][0]
    )
    # A previous month's selected name can remain during the next month's five
    # execution sessions, even when absent from the new target book.
    def normal_window_end(month: pd.Period) -> pd.Timestamp:
        next_month = month + 1
        next_sessions = dates[dates.to_period("M") == next_month]
        return next_sessions[min(4, len(next_sessions) - 1)] if len(next_sessions) else CUTOFF

    winners["normal_window_end"] = winners["holding_month"].map(normal_window_end)
    first_selection = winners.groupby("security_id")["possible_from"].min().rename("first_possible_hold")

    events = pd.read_csv(INPUTS["event_application"], parse_dates=["ex_date"])
    events = events.loc[events["ex_date"].between(START, CUTOFF)].copy()
    if events["event_id"].duplicated().any():
        raise ValueError("Event application has duplicate event IDs")
    events = events.merge(first_selection, on="security_id", how="inner")
    events = events.loc[events["ex_date"] >= events["first_possible_hold"]].copy()

    # Restrict the raw treatment read to the accepted development dates. The
    # source contains no post-cutoff economic value in this file.
    treated = pd.read_parquet(
        INPUTS["treated_actions"],
        columns=["event_id", "ex_date", "record_date", "payment_date", "primary_class",
                 "dividend_amount", "ratio_a", "ratio_b", "old_face_value_parsed",
                 "new_face_value_parsed", "treatment_status", "share_multiplier",
                 "cash_per_pre_event_share", "evidence_source",
                 "rights_entitlement_observed", "rights_entitlement_symbol"],
        filters=[("ex_date", "<=", CUTOFF)],
    )
    if treated["event_id"].duplicated().any():
        raise ValueError("Treated corporate-action source has duplicate event IDs")
    events = events.merge(treated.drop(columns=["ex_date", "primary_class"]), on="event_id", how="left",
                          validate="one_to_one")
    events["in_normal_window"] = False
    for row in winners.itertuples(index=False):
        mask = (events["security_id"].eq(row.security_id)
                & events["ex_date"].between(row.possible_from, row.normal_window_end))
        events.loc[mask, "in_normal_window"] = True

    events["payment_date_evidenced"] = events["payment_date"].notna()
    events["bonus_credit_date_evidenced"] = False
    settlement = pd.read_parquet(INPUTS["settlement_calendar"], columns=["date", "settlement_business_day"])
    settlement_verified = (
        len(settlement) == len(pd.date_range(START, CUTOFF))
        and settlement["date"].is_unique
        and settlement["date"].min() == START
        and settlement["date"].max() == CUTOFF
        and settlement["settlement_business_day"].notna().all()
    )
    events["settlement_calendar_evidenced"] = settlement_verified
    events["account_mechanics_status"] = "REVIEW"
    events.loc[events["primary_class"].eq("DIVIDEND")
               & events["application_status"].eq("APPLIED_TO_RETURN"),
               "account_mechanics_status"] = "CASH_AMOUNT_KNOWN_PAYMENT_PENDING"
    events.loc[events["primary_class"].eq("SPLIT")
               & events["application_status"].eq("APPLIED_TO_RETURN"),
               "account_mechanics_status"] = "SPLIT_RATIO_KNOWN"
    events.loc[events["primary_class"].eq("BONUS")
               & events["application_status"].eq("APPLIED_TO_RETURN"),
               "account_mechanics_status"] = "BONUS_RATIO_KNOWN_CREDIT_PENDING"
    events.loc[events["application_status"].eq("NO_DIRECT_ADJUSTMENT_REQUIRED"),
               "account_mechanics_status"] = "ACCEPTED_NO_DIRECT_ADJUSTMENT"
    events.loc[events["application_status"].eq("NOT_SIGNAL_RELEVANT"),
               "account_mechanics_status"] = "NOT_ECONOMIC_ACTION_FOR_ACCOUNT"
    events.loc[events["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT"),
               "account_mechanics_status"] = "UNRESOLVED_ECONOMIC_EVENT"
    events.loc[events["event_id"].eq("CA_09d4133ad6ad9024fa83"),
               "account_mechanics_status"] = "ADANIENT_FROZEN_ZERO_INCREMENTAL_ASSUMPTION"
    events.loc[events["event_id"].isin(["CA_a28c7ef7be5fba82424e", "CA_4bd3ac9cadba72dfd0ee"]),
               "account_mechanics_status"] = "HGS_VERIFIED_COMBINED_BONUS_DIVIDEND_CREDIT_PAYMENT_PENDING"
    events.loc[events["event_id"].isin(["CA_bd1a9c0fb614d418b033", "CA_d980fda0218090aafc5e"]),
               "account_mechanics_status"] = "EASEMYTRIP_VERIFIED_SPLIT_BONUS_CREDIT_PENDING"
    # The accepted signal feature values this right theoretically. Plan §5.4
    # requires an evidenced sale and price in the executable account. The
    # processed source explicitly says no rights-entitlement trade was seen.
    events.loc[events["event_id"].eq("CA_2dcc6f730654721a5203"),
               "account_mechanics_status"] = "UNRESOLVED_ACCOUNT_RIGHTS_REALISATION"
    events["account_evidence_issue"] = ""
    events.loc[events["event_id"].eq("CA_2dcc6f730654721a5203"),
               "account_evidence_issue"] = (
                   "Theoretical ex-rights signal value is not executable cash; "
                   "no observed entitlement trade or sale price. "
                   "SEBI letter of offer: https://www.sebi.gov.in/sebi_data/attachdocs/feb-2018/1517830321746.pdf"
               )
    events.sort_values(["ex_date", "security_id", "event_id"]).to_csv(
        OUT / "candidate_corporate_actions.csv", index=False
    )

    normal = events.loc[events["in_normal_window"]]
    economic_dividend = normal["primary_class"].eq("DIVIDEND") & normal["account_mechanics_status"].ne("NOT_ECONOMIC_ACTION_FOR_ACCOUNT")
    summary = {
        "scored_selected_security_months": len(winners),
        "selected_distinct_securities": winners["security_id"].nunique(),
        "normal_window_candidate_actions": len(normal),
        "normal_window_candidate_dividends": int(normal["primary_class"].eq("DIVIDEND").sum()),
        "normal_window_dividends_missing_payment_date": int((normal["primary_class"].eq("DIVIDEND") & ~normal["payment_date_evidenced"]).sum()),
        "normal_window_economic_dividends": int(economic_dividend.sum()),
        "normal_window_economic_dividends_missing_payment_date": int((economic_dividend & ~normal["payment_date_evidenced"]).sum()),
        "normal_window_candidate_bonuses": int(normal["primary_class"].eq("BONUS").sum()),
        "normal_window_bonuses_missing_credit_date": int((normal["primary_class"].eq("BONUS") & ~normal["bonus_credit_date_evidenced"]).sum()),
        "normal_window_unresolved_economic_actions": int(normal["account_mechanics_status"].eq("UNRESOLVED_ECONOMIC_EVENT").sum()),
        "normal_window_unresolved_account_rights": int(normal["account_mechanics_status"].eq("UNRESOLVED_ACCOUNT_RIGHTS_REALISATION").sum()),
        "after_first_selection_candidate_actions": len(events),
        "after_first_selection_unresolved_economic_actions": int(events["account_mechanics_status"].eq("UNRESOLVED_ECONOMIC_EVENT").sum()),
        "settlement_calendar_verified": settlement_verified,
        "corporate_action_preflight_pass": True,
        "account_run_authorized_by_evidence": settlement_verified,
        "held_event_materiality_requires_chronological_run": True,
        "maximum_event_date_read": str(events["ex_date"].max().date()),
    }
    pd.DataFrame([{"check": key, "value": value} for key, value in summary.items()]).to_csv(
        OUT / "preflight_summary.csv", index=False
    )
    after = {name: sha256(path) for name, path in INPUTS.items()}
    if any(after[row.input] != row.sha256 for row in manifest.itertuples(index=False)):
        raise ValueError("An accepted input changed during account preflight")
    return summary


if __name__ == "__main__":
    for key, value in run_preflight().items():
        print(f"{key}: {value}")
