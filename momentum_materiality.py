"""Triage unresolved momentum winner boundaries without valuing corporate actions."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
RETURNS = PROCESSED / "stock_total_returns.parquet"
PANEL = PROCESSED / "research_panel_v2.parquet"
MONTHLY = PROCESSED / "momentum_monthly_features.parquet"
FORMATIONS = PROCESSED / "momentum_formations.parquet"
WINNERS = PROCESSED / "momentum_winners.parquet"
EVENTS = ROOT / "results" / "stock_total_return_audit" / "unresolved_events.csv"
IMPACT = ROOT / "results" / "momentum_signal_audit" / "unresolved_event_materiality.csv"
OUTPUT = ROOT / "results" / "momentum_materiality"
CUTOFF = pd.Timestamp("2023-03-31")
SOURCES = (RETURNS, PANEL, MONTHLY, FORMATIONS, WINNERS)


def read_development(path: Path, columns: list[str], date_column: str,
                     security_ids: list[str] | None = None) -> pd.DataFrame:
    if path not in SOURCES:
        raise ValueError("Only authoritative corrected development artifacts are allowed")
    predicate = ds.field(date_column) <= CUTOFF.to_datetime64()
    if security_ids is not None:
        predicate = predicate & ds.field("security_id").isin(security_ids)
    frame = ds.dataset(path, format="parquet").to_table(columns=columns, filter=predicate).to_pandas()
    frame[date_column] = pd.to_datetime(frame[date_column])
    if not frame.empty and frame[date_column].max() > CUTOFF:
        raise ValueError("Post-development value encountered")
    return frame


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def winner_boundary(known: pd.DataFrame, candidate_id: str, concurrent: int) -> dict:
    """Same decile rule, with one or all unresolved candidates becoming eligible."""
    known = known.sort_values(["momentum_score", "security_id"], ascending=[False, True])
    n = len(known)
    if n < 20 or concurrent < 1:
        raise ValueError("Invalid known eligible count or concurrent candidate count")
    k = math.ceil(n / 10)
    k_one = math.ceil((n + 1) / 10)
    k_all = math.ceil((n + concurrent) / 10)
    if k_all > n:
        raise ValueError("Cannot locate boundary among known eligible names")
    # Best case: all other unresolved candidates are behind this candidate.
    # Worst case: any subset is eligible and each is ahead of this candidate.
    worst_known_rank = min(
        math.ceil((n + 1 + others) / 10) - others
        for others in range(concurrent)
    )
    if worst_known_rank < 1:
        raise ValueError("No finite worst-case known-name threshold")

    def boundary(rank: int) -> tuple[float, str, bool]:
        row = known.iloc[rank - 1]
        return float(row.momentum_score), str(row.security_id), candidate_id < row.security_id

    current, current_id, _ = boundary(k)
    one, one_id, one_tie_wins = boundary(k_one)
    best, best_id, best_tie_wins = boundary(k_all)
    worst, worst_id, worst_tie_wins = boundary(worst_known_rank)
    runner = known.iloc[k] if k < n else None
    return {
        "eligible_count": n, "winner_count": k,
        "current_weakest_winner_score": current,
        "current_weakest_winner_id": current_id,
        "current_strongest_nonwinner_score": float(runner.momentum_score) if runner is not None else np.nan,
        "current_strongest_nonwinner_id": str(runner.security_id) if runner is not None else "",
        "winner_count_with_one_candidate": k_one,
        "winner_count_with_all_concurrent": k_all,
        "concurrent_uncertain_candidates": concurrent,
        "possible_count_change": any(
            math.ceil((n + others + 1) / 10) > math.ceil((n + others) / 10)
            for others in range(concurrent)
        ),
        "individual_boundary_score": one, "individual_boundary_id": one_id,
        "individual_equality_selects_candidate": one_tie_wins,
        "best_case_boundary_score": best, "best_case_boundary_id": best_id,
        "best_case_equality_selects_candidate": best_tie_wins,
        "worst_case_boundary_score": worst, "worst_case_boundary_id": worst_id,
        "worst_case_equality_selects_candidate": worst_tie_wins,
    }


def required_month_return(cutoff_score: float, other_ten_gross: float) -> float:
    if not np.isfinite(other_ten_gross) or other_ten_gross <= 0:
        raise ValueError("Ten other months cannot support a return threshold")
    return (1 + cutoff_score) / other_ten_gross - 1


def classify_materiality(scored: bool, accepted_lower: float | None,
                         accepted_upper: float | None, best_adjustment: float,
                         worst_adjustment: float, count_sensitive: bool) -> str:
    """An unknown bound never proves that an excluded candidate is harmless."""
    bounded_above = accepted_upper is not None and np.isfinite(accepted_upper)
    bounded_below = accepted_lower is not None and np.isfinite(accepted_lower)
    if bounded_above and accepted_upper < best_adjustment and not count_sensitive:
        return "IMMATERIAL_TO_WINNER_SET"
    if not scored:
        return "MATERIAL_WARMUP_ONLY"
    if not bounded_above or not bounded_below:
        return "CANNOT_BOUND"
    if accepted_lower > worst_adjustment or count_sensitive:
        return "REQUIRES_EVENT_RESEARCH"
    return "POSSIBLY_MATERIAL"


def equity_price_only_month(rows: pd.DataFrame, event_date: pd.Timestamp,
                            event_id: str, expected_sessions: int) -> float:
    """Diagnostic baseline; never writes or substitutes a missing daily return."""
    ex = rows.loc[rows["date"].eq(event_date)]
    other = rows.loc[rows["date"].ne(event_date)]
    if len(rows) != expected_sessions or len(ex) != 1 or len(other) != expected_sessions - 1:
        raise ValueError(f"Incomplete event month: {event_id}")
    ex = ex.iloc[0]
    if (event_id not in str(ex["all_event_ids"]).split(";")
            or ex["total_return_available"] or pd.notna(ex["daily_total_return"])
            or not np.isfinite(ex["price_return"]) or not np.isfinite(ex["previous_close"])
            or ex["previous_close"] <= 0
            or not other["total_return_available"].all()
            or not np.isfinite(other["daily_total_return"]).all()):
        raise ValueError(f"Event month does not have exactly one unresolved daily return: {event_id}")
    return float(np.prod(1 + other["daily_total_return"]) * (1 + ex["price_return"]) - 1)


def build_triage() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    existing = pd.read_csv(IMPACT, parse_dates=["event_date", "formation_date"])
    actions = pd.read_csv(EVENTS, parse_dates=["ex_date"])
    blockers = existing.loc[existing["final_signal_availability_changed"].eq(True)].copy()
    if len(blockers) != 216 or blockers["event_id"].nunique() != 39:
        raise ValueError("Accepted 216-observation/39-event blocker audit changed")
    accepted_bonus = blockers["event_reason"].eq("ACCEPTED_STRICT_RETURN_EXCEPTION")
    if (accepted_bonus.sum() != 9
            or set(blockers.loc[accepted_bonus, "event_id"]) != {"CA_52dafdfb28d9f35d7326"}):
        raise ValueError("Accepted Britannia exception scope changed")
    targets = blockers.loc[~accepted_bonus].copy()
    targets = targets.merge(actions[[
        "event_id", "security_id", "symbol", "ex_date", "primary_class",
        "purpose_normalized", "application_reason",
    ]], on=["event_id", "security_id"], how="left", validate="many_to_one")
    if (targets["primary_class"].isna().any()
            or not targets["event_date"].eq(targets["ex_date"]).all()):
        raise ValueError("Unresolved event identity/date audit mismatch")
    targets["formation_month"] = targets["formation_date"].dt.to_period("M")
    targets["event_month"] = targets["event_date"].dt.to_period("M")

    formations = read_development(FORMATIONS, [
        "formation_date", "security_id", "symbol", "holding_month", "scored",
        "eligible", "momentum_score", "rank", "winner", "eligible_count",
        "target_winner_count", "quote_usable", "adv_eligible", "volume_eligible",
        "timing_eligible", "history_eligible",
    ], "formation_date")
    winners = read_development(WINNERS, [
        "formation_date", "security_id", "momentum_score", "rank",
    ], "formation_date")
    monthly = read_development(MONTHLY, [
        "security_id", "month", "month_end", "gross", "complete",
        "expected_sessions", "unavailable_event_ids",
    ], "month_end")
    event_ids = targets["security_id"].unique().tolist()
    returns = read_development(RETURNS, [
        "security_id", "date", "previous_close", "price_return", "daily_total_return",
        "total_return_available", "all_event_ids",
    ], "date", event_ids)
    panel = read_development(PANEL, [
        "security_id", "date", "daily_total_return",
    ], "date", event_ids)
    event_dates = targets[["security_id", "event_date"]].drop_duplicates()
    source_check = event_dates.merge(
        returns[["security_id", "date", "daily_total_return"]],
        left_on=["security_id", "event_date"], right_on=["security_id", "date"],
        how="left", validate="one_to_one",
    ).merge(
        panel[["security_id", "date", "daily_total_return"]],
        on=["security_id", "date"], how="left", validate="one_to_one",
        suffixes=("_corrected", "_panel_v2"),
    )
    if (len(source_check) != len(event_dates)
            or source_check["date"].isna().any()
            or not np.allclose(source_check["daily_total_return_corrected"],
                               source_check["daily_total_return_panel_v2"], equal_nan=True)):
        raise ValueError("Corrected ex-date return and panel-v2 are not aligned")

    lookup = formations.set_index(["formation_date", "security_id"])
    monthly_lookup = monthly.set_index(["security_id", "month"])
    eligible = {date: group.loc[group["eligible"]].copy()
                for date, group in formations.groupby("formation_date")}
    concurrent = blockers.groupby("formation_date")["security_id"].nunique()
    if targets.duplicated(["event_id", "security_id", "formation_date"]).any():
        raise ValueError("Duplicate event/security/formation materiality observation")
    if winners.duplicated(["formation_date", "security_id"]).any():
        raise ValueError("Duplicate winner at formation")

    event_month_price = {}
    records = []
    for event in targets.itertuples(index=False):
        candidate = lookup.loc[(event.formation_date, event.security_id)]
        if (candidate.eligible or candidate.history_eligible or not candidate.quote_usable
                or not candidate.adv_eligible or not candidate.volume_eligible
                or not candidate.timing_eligible):
            raise ValueError("Target has an independent eligibility failure or an existing score")
        current = eligible[event.formation_date]
        boundary = winner_boundary(current, event.security_id, int(concurrent.loc[event.formation_date]))
        if (boundary["eligible_count"] != candidate.eligible_count
                or boundary["winner_count"] != candidate.target_winner_count):
            raise ValueError("Frozen decile count differs from accepted formation")
        actual_winners = winners.loc[winners["formation_date"].eq(event.formation_date)]
        expected_winners = current.sort_values(
            ["momentum_score", "security_id"], ascending=[False, True]
        ).head(boundary["winner_count"])
        if (len(actual_winners) != boundary["winner_count"]
                or set(actual_winners["security_id"]) != set(expected_winners["security_id"])):
            raise ValueError("Frozen winner set does not match accepted formation")
        months = pd.period_range(event.formation_month - 11, event.formation_month - 1, freq="M")
        if event.event_month not in months:
            raise ValueError("Event is outside the declared 12-to-2 lookback")
        others = monthly_lookup.loc[[(event.security_id, month) for month in months if month != event.event_month]]
        missing = monthly_lookup.loc[(event.security_id, event.event_month)]
        if (len(others) != 10 or not others["complete"].all()
                or missing["complete"] or missing["unavailable_event_ids"] != event.event_id):
            raise ValueError("Missing event is not the only incomplete lookback month")
        ten_gross = float(others["gross"].prod())
        current_threshold = required_month_return(boundary["current_weakest_winner_score"], ten_gross)
        if not np.isclose(current_threshold, event.required_event_month_return_to_win, rtol=0, atol=1e-10):
            raise ValueError("Existing current-cutoff diagnostic does not reconcile")
        key = (event.security_id, event.event_month, event.event_id)
        if key not in event_month_price:
            month_rows = returns.loc[
                returns["security_id"].eq(event.security_id)
                & returns["date"].dt.to_period("M").eq(event.event_month)
            ]
            event_month_price[key] = equity_price_only_month(
                month_rows, event.event_date, event.event_id, int(missing.expected_sessions)
            )
        price_only = event_month_price[key]
        thresholds = {
            "current_cutoff": current_threshold,
            "single_candidate": required_month_return(boundary["individual_boundary_score"], ten_gross),
            "best_case": required_month_return(boundary["best_case_boundary_score"], ten_gross),
            "worst_case": required_month_return(boundary["worst_case_boundary_score"], ten_gross),
        }
        classification = classify_materiality(
            bool(candidate.scored), None, None,
            thresholds["best_case"] - price_only,
            thresholds["worst_case"] - price_only,
            boundary["possible_count_change"],
        )
        records.append({
            "event_id": event.event_id, "security_id": event.security_id,
            "symbol": event.symbol, "event_date": event.event_date,
            "event_type": event.primary_class, "event_description": event.purpose_normalized,
            "formation_date": event.formation_date, "holding_month": candidate.holding_month,
            "is_scored": bool(candidate.scored),
            **boundary,
            "other_ten_months_gross": ten_gross,
            "price_only_month_return_diagnostic": price_only,
            "month_return_to_current_cutoff": thresholds["current_cutoff"],
            "month_return_to_single_candidate_cutoff": thresholds["single_candidate"],
            "month_return_below_this_is_definitely_out": thresholds["best_case"],
            "month_return_above_this_is_definitely_in": thresholds["worst_case"],
            "additional_month_return_to_single_candidate_cutoff": thresholds["single_candidate"] - price_only,
            "additional_month_return_below_this_is_definitely_out": thresholds["best_case"] - price_only,
            "additional_month_return_above_this_is_definitely_in": thresholds["worst_case"] - price_only,
            "accepted_additional_return_lower_bound": np.nan,
            "accepted_additional_return_upper_bound": np.nan,
            "materiality_class": classification,
            "needs_further_research": classification != "IMMATERIAL_TO_WINNER_SET",
            "hypothetical_momentum": np.nan, "hypothetical_rank": pd.NA,
        })
    affected = pd.DataFrame(records).sort_values(["event_date", "event_id", "formation_date"])
    if len(affected) != 207 or affected["event_id"].nunique() != 38:
        raise ValueError("Targeted triage scope changed unexpectedly")

    grouped = affected.groupby(["event_id", "security_id", "symbol", "event_date", "event_type"])
    priority = grouped.agg(
        affected_formations=("formation_date", "size"),
        affected_scored_formations=("is_scored", "sum"),
        first_affected_formation=("formation_date", "min"),
        last_affected_formation=("formation_date", "max"),
        possibly_material_scored_formations=(
            "materiality_class", lambda s: int(s.isin(["CANNOT_BOUND", "POSSIBLY_MATERIAL", "REQUIRES_EVENT_RESEARCH"]).sum())
        ),
        warmup_only_formations=("is_scored", lambda s: int((~s).sum())),
        cannot_bound_formations=("materiality_class", lambda s: int(s.eq("CANNOT_BOUND").sum())),
        best_case_additional_return_required=("additional_month_return_below_this_is_definitely_out", "min"),
    ).reset_index()
    priority["event_materiality_class"] = np.where(
        priority["affected_scored_formations"].gt(0), "CANNOT_BOUND", "MATERIAL_WARMUP_ONLY"
    )
    priority["needs_further_research"] = True
    priority["priority_group"] = np.where(priority["affected_scored_formations"].gt(0),
                                          "SCORED_WINNER_UNCERTAINTY", "WARMUP_ONLY_SHADOW_DEPENDENCY")
    priority = priority.sort_values(
        ["affected_scored_formations", "possibly_material_scored_formations",
         "warmup_only_formations", "event_id"], ascending=[False, False, False, True]
    ).reset_index(drop=True)
    priority.insert(0, "priority_order", np.arange(1, len(priority) + 1))

    class_counts = affected["materiality_class"].value_counts()
    summary = pd.DataFrame([
        ("source_unresolved_events", len(actions)),
        ("source_blocking_events", blockers["event_id"].nunique()),
        ("source_blocking_observations", len(blockers)),
        ("accepted_britannia_exception_events_out_of_scope", blockers.loc[accepted_bonus, "event_id"].nunique()),
        ("accepted_britannia_exception_observations_out_of_scope", int(accepted_bonus.sum())),
        ("unresolved_events_examined_in_scope", len(priority)),
        ("affected_observations", len(affected)),
        ("scored_affected_observations", int(affected["is_scored"].sum())),
        ("warmup_affected_observations", int((~affected["is_scored"]).sum())),
        *[(f"class_{category}", int(class_counts.get(category, 0))) for category in [
            "IMMATERIAL_TO_WINNER_SET", "POSSIBLY_MATERIAL", "MATERIAL_WARMUP_ONLY",
            "REQUIRES_EVENT_RESEARCH", "CANNOT_BOUND",
        ]],
        ("unique_events_requiring_scored_research", int(priority["affected_scored_formations"].gt(0).sum())),
        ("unique_events_requiring_eventual_research_including_warmup", int(priority["needs_further_research"].sum())),
        ("unknown_identity_events_outside_formation_audit", int(actions["security_id"].isna().sum())),
        ("maximum_value_date_read", max(
            returns["date"].max(), panel["date"].max(), monthly["month_end"].max(),
            formations["formation_date"].max(), winners["formation_date"].max(),
        ).date()),
    ], columns=["measure", "value"])
    return affected, priority, summary


def main() -> None:
    before = {path: sha256(path) for path in SOURCES}
    affected, priority, summary = build_triage()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    affected.to_csv(OUTPUT / "affected_signal_materiality.csv", index=False)
    priority.to_csv(OUTPUT / "unresolved_event_priority.csv", index=False)
    summary.to_csv(OUTPUT / "materiality_summary.csv", index=False)
    if {path: sha256(path) for path in SOURCES} != before:
        raise ValueError("An accepted source artifact changed during materiality triage")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
