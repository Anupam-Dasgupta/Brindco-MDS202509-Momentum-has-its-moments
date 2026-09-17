"""Separate signal sensitivity for still-unvalued economic entitlements."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from momentum_signal import (
    CUTOFF, FORMATIONS_OUTPUT, MONTHLY_OUTPUT, RETURNS, WINNERS_OUTPUT,
    build_formations, build_monthly, build_roster, load_inputs,
)


ROOT = Path(__file__).resolve().parent
SENSITIVITY = ROOT / "data/processed/sensitivity"
AUDIT = ROOT / "results/shadow_audit"
STATUS = ROOT / "results/event_resolution/event_resolution_status.csv"
EVENTS = ROOT / "results/stock_total_return_audit/event_application_detail.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zero_increment_days(status: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Value only the unresolved increment at zero; retain accepted same-day legs."""
    target_ids = set(status.loc[status["final_status"].eq("UNRESOLVED_ECONOMIC_TREATMENT"), "event_id"])
    target = events.loc[events["event_id"].isin(target_ids)].copy()
    if len(target) != 30 or not target["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all():
        raise ValueError("The frozen 30-event unresolved research inventory changed")
    target["ex_date"] = pd.to_datetime(target["ex_date"])
    blocked = events.loc[events["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT")].copy()
    blocked["ex_date"] = pd.to_datetime(blocked["ex_date"])
    keys = target[["security_id", "ex_date"]].drop_duplicates()
    other = keys.merge(blocked, on=["security_id", "ex_date"], how="left")
    if not set(other["event_id"]).issubset(target_ids):
        raise ValueError("An unrelated event blocks a proposed sensitivity day")
    if target["security_id"].isna().any() or target["ex_date"].max() > CUTOFF:
        raise ValueError("Unresolved sensitivity event has no dated development identity")

    event_dates = target["ex_date"].drop_duplicates().tolist()
    table = ds.dataset(RETURNS, format="parquet").to_table(
        columns=["security_id", "date", "close", "previous_close", "price_return",
                 "daily_total_return", "total_return_available", "quality_status",
                 "exclusion_reason", "all_event_ids", "cash_effect", "share_effect",
                 "entitlement_effect"],
        filter=ds.field("date").isin(event_dates) & (ds.field("date") <= CUTOFF.to_datetime64()),
    ).to_pandas()
    days = keys.merge(table, left_on=["security_id", "ex_date"], right_on=["security_id", "date"],
                      how="left", validate="one_to_one")
    if len(days) != len(keys) or days["date"].isna().any():
        raise ValueError("An unresolved event has no authoritative return row")
    if not (
        days["quality_status"].eq("CORPORATE_ACTION_UNRESOLVED").all()
        and days["total_return_available"].eq(False).all()
        and days["exclusion_reason"].eq("TREATMENT_NOT_ACCEPTED").all()
        and np.isfinite(days["close"]).all() and days["close"].gt(0).all()
        and np.isfinite(days["previous_close"]).all() and days["previous_close"].gt(0).all()
        and np.isfinite(days["price_return"]).all()
    ):
        raise ValueError("Zero-increment scenario would waive an ordinary data-quality failure")
    days["sensitivity_total_return"] = (
        days["share_effect"] * days["close"]
        + days["cash_effect"] + days["entitlement_effect"]
    ) / days["previous_close"] - 1
    if days["sensitivity_total_return"].lt(-1).any():
        raise ValueError("Sensitivity produces impossible negative gross return")
    return days[["security_id", "date", "sensitivity_total_return"]]


def build_sensitivity() -> dict[str, int]:
    protected = [MONTHLY_OUTPUT, FORMATIONS_OUTPUT, WINNERS_OUTPUT, RETURNS,
                 ROOT / "data/processed/research_panel_v2.parquet"]
    protected_hashes = {path: sha256(path) for path in protected}
    accepted_hashes = pd.read_csv(ROOT / "results/event_resolution/artifact_hashes.csv")
    for path, digest in protected_hashes.items():
        relative = path.relative_to(ROOT).as_posix()
        accepted = accepted_hashes.loc[accepted_hashes["artifact"].eq(relative), "after_sha256"]
        if len(accepted) != 1 or accepted.iloc[0] != digest:
            raise ValueError(f"Primary artifact differs from accepted event-resolution build: {relative}")
    panel, calendar, membership, delayed, timing = load_inputs()
    status = pd.read_csv(STATUS)
    events = pd.read_csv(EVENTS)
    repairs = zero_increment_days(status, events)

    # This copy exists only inside the separate scenario. The accepted daily
    # return and research panel files are never written by this script.
    scenario = panel.copy()
    key = pd.MultiIndex.from_frame(scenario[["security_id", "date"]])
    replacement = key.map(repairs.set_index(["security_id", "date"])["sensitivity_total_return"])
    mask = replacement.notna()
    if int(mask.sum()) != len(repairs):
        raise ValueError("Not every targeted economic day appeared in the scenario panel")
    scenario.loc[mask, "daily_total_return"] = replacement[mask].to_numpy()
    scenario.loc[mask, "total_return_available"] = True
    scenario.loc[mask, "quality_status"] = "ZERO_UNRESOLVED_INCREMENT_SENSITIVITY"
    scenario.loc[mask, "exclusion_reason"] = ""

    monthly = build_monthly(scenario, calendar, delayed, timing)
    roster = build_roster(membership, calendar)
    formations = build_formations(roster, scenario, monthly, timing)
    winners = formations.loc[formations["winner"], [
        "formation_date", "holding_month", "scored", "security_id", "symbol",
        "momentum_score", "rank", "eligible_count", "target_winner_count",
    ]].sort_values(["formation_date", "rank"])
    SENSITIVITY.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(SENSITIVITY / "zero_entitlement_monthly_features.parquet", index=False)
    formations.to_parquet(SENSITIVITY / "zero_entitlement_formations.parquet", index=False)
    winners.to_parquet(SENSITIVITY / "zero_entitlement_winners.parquet", index=False)

    primary = pd.read_parquet(FORMATIONS_OUTPUT)
    comparison = primary[["formation_date", "security_id", "symbol", "eligible", "winner",
                          "eligible_count", "target_winner_count"]].merge(
        formations[["formation_date", "security_id", "symbol", "eligible", "winner",
                    "eligible_count", "target_winner_count"]],
        on=["formation_date", "security_id"], how="outer", suffixes=("_primary", "_sensitivity"),
        validate="one_to_one", indicator=True,
    )
    if len(comparison) != len(primary) or not comparison["_merge"].eq("both").all():
        raise ValueError("Sensitivity changed the official formation universe")
    summary = []
    for formation_date, group in comparison.groupby("formation_date", sort=True):
        entered = group.loc[~group["winner_primary"] & group["winner_sensitivity"], "symbol_sensitivity"]
        exited = group.loc[group["winner_primary"] & ~group["winner_sensitivity"], "symbol_primary"]
        restored = group.loc[~group["eligible_primary"] & group["eligible_sensitivity"], "symbol_sensitivity"]
        restored_winners = group.loc[~group["eligible_primary"] & group["winner_sensitivity"], "symbol_sensitivity"]
        summary.append({
            "formation_date": formation_date,
            "primary_n": int(group["eligible_count_primary"].iloc[0]),
            "sensitivity_n": int(group["eligible_count_sensitivity"].iloc[0]),
            "primary_k": int(group["target_winner_count_primary"].iloc[0]),
            "sensitivity_k": int(group["target_winner_count_sensitivity"].iloc[0]),
            "winner_entries": ";".join(entered), "winner_exits": ";".join(exited),
            "restored_signal_symbols": ";".join(restored),
            "restored_event_winners": ";".join(restored_winners),
        })
    summary = pd.DataFrame(summary)
    summary.to_csv(AUDIT / "primary_vs_zero_signal_changes.csv", index=False)
    if any(sha256(path) != digest for path, digest in protected_hashes.items()):
        raise ValueError("A primary artifact changed during sensitivity construction")
    if not (formations["target_winner_count"].eq(formations["eligible_count"].map(lambda n: math.ceil(n / 10))).all()):
        raise ValueError("Sensitivity seat count was not recomputed")
    return {
        "zero_increment_event_days": len(repairs),
        "formations_n_changed": int(summary["primary_n"].ne(summary["sensitivity_n"]).sum()),
        "formations_k_changed": int(summary["primary_k"].ne(summary["sensitivity_k"]).sum()),
        "winner_entries": int(summary["winner_entries"].map(lambda s: len(s.split(";")) if s else 0).sum()),
        "winner_exits": int(summary["winner_exits"].map(lambda s: len(s.split(";")) if s else 0).sum()),
    }


if __name__ == "__main__":
    for name, value in build_sensitivity().items():
        print(f"{name}: {value}")
