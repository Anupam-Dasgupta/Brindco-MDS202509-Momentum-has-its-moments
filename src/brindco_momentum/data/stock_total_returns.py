"""Correct development stock returns from accepted processed market and action data."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


from brindco_momentum.paths import ROOT
PROCESSED = ROOT / "data" / "processed"
CUTOFF = pd.Timestamp("2023-03-31")
OLD_PANEL = PROCESSED / "research_panel_build.parquet"
NEW_RETURNS = PROCESSED / "stock_total_returns.parquet"
NEW_PANEL = PROCESSED / "research_panel_v2.parquet"
CALENDAR = PROCESSED / "nse_trading_calendar_2013_2026.parquet"
MEMBERSHIP = PROCESSED / "membership_official" / "nifty500_official_membership_intervals.parquet"
IDENTITY = PROCESSED / "security_identity_official" / "dated_security_identity.parquet"
ACTIONS = PROCESSED / "corporate_action_treatment" / "nse_corporate_actions_treated_through_2023_03_31.parquet"
TREATMENTS = PROCESSED / "corporate_action_treatment" / "in_universe_event_treatments.parquet"
MANUAL_RESOLUTIONS = ROOT / "data" / "manual" / "corporate_action_resolutions_v1.csv"
AUDIT_DIR = ROOT / "results" / "stock_total_return_audit"

PANEL_COLUMNS = [
    "date", "security_id", "symbol", "isin", "series", "in_nifty500",
    "membership_symbol", "membership_source",
    "open", "high", "low", "close", "volume", "traded_value",
    "adv20_lagged", "adv20_observation_count", "positive_volume_sessions_20",
    "adv20_complete",
    "market_observed", "market_data_status", "identity_status",
    "is_formation_date", "momentum_signal_safe",
    "momentum_signal_exclusion_reason", "corporate_action_timing_event_ids",
    "corporate_action_exception", "delayed_recognition_available",
    "delayed_recognition_event_ids", "delayed_recognition_value_per_pre_event_share",
    "delayed_recognition_information_timestamp", "source_file",
]
ACTION_COLUMNS = [
    "event_id", "ex_date", "symbol", "series", "primary_class",
    "purpose_normalized", "source_file", "economic_event_count",
    "multiple_event_types", "needs_manual_review", "dividend_amount",
    "ratio_a", "ratio_b", "old_face_value_parsed", "new_face_value_parsed",
    "treatment_reviewed_for_in_universe_event", "repair_status",
]


def read_through_cutoff(path: Path, date_column: str, columns: list[str]) -> pd.DataFrame:
    table = ds.dataset(path, format="parquet").to_table(
        columns=columns, filter=ds.field(date_column) <= CUTOFF.to_datetime64()
    )
    frame = table.to_pandas()
    frame[date_column] = pd.to_datetime(frame[date_column])
    if not frame.empty and frame[date_column].max() > CUTOFF:
        raise ValueError(f"Post-cutoff value read from {path}")
    return frame


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_prices(panel: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    if panel.duplicated(["security_id", "date"]).any():
        raise ValueError("Accepted panel has duplicate security/date observations")
    panel = panel.sort_values(["security_id", "date"]).reset_index(drop=True)
    previous_session = calendar.set_index("date")["previous_trading_day"]
    panel["previous_session_date"] = panel["date"].map(previous_session)
    grouped = panel.groupby("security_id", sort=False)
    preceding_observed_date = grouped["date"].shift(1)
    preceding_observed_close = grouped["close"].shift(1)
    consecutive = preceding_observed_date.eq(panel["previous_session_date"])
    panel["previous_close"] = preceding_observed_close.where(consecutive)
    valid = (
        panel["market_observed"].fillna(False)
        & panel["market_data_status"].eq("OK")
        & panel["identity_status"].eq("RESOLVED")
        & np.isfinite(panel["close"]) & panel["close"].gt(0)
        & np.isfinite(panel["previous_close"]) & panel["previous_close"].gt(0)
    )
    panel["price_return"] = np.nan
    panel.loc[valid, "price_return"] = (
        panel.loc[valid, "close"] / panel.loc[valid, "previous_close"] - 1
    )
    panel["base_return_status"] = "OK"
    panel.loc[~consecutive, "base_return_status"] = "PREVIOUS_CANONICAL_OBSERVATION_MISSING"
    panel.loc[panel["identity_status"].ne("RESOLVED"), "base_return_status"] = "IDENTITY_UNRESOLVED"
    panel.loc[panel["market_data_status"].ne("OK"), "base_return_status"] = "MARKET_OBSERVATION_INVALID"
    panel.loc[~panel["market_observed"].fillna(False), "base_return_status"] = "MARKET_OBSERVATION_MISSING"
    missing_anchor = panel["price_return"].isna() & panel["base_return_status"].eq("OK")
    panel.loc[missing_anchor, "base_return_status"] = "PREVIOUS_CANONICAL_CLOSE_UNAVAILABLE"
    return panel


def map_actions(
    actions: pd.DataFrame,
    identity: pd.DataFrame,
    membership: pd.DataFrame,
    treatments: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    actions = actions.loc[actions["economic_event_count"].gt(0)].copy()
    if actions["event_id"].isna().any() or actions["event_id"].duplicated().any():
        raise ValueError("Processed economic actions require unique stable event IDs")
    if treatments["event_id"].isna().any() or treatments["event_id"].duplicated().any():
        raise ValueError("Accepted treatments require unique event IDs")
    if len(treatments) != 149 or int(treatments["blocks_total_return"].sum()) != 4:
        raise ValueError("Accepted 149-event treatment gate has changed")
    if not set(treatments["event_id"]).issubset(set(actions["event_id"])):
        raise ValueError("Accepted treatment has no processed parent action")

    candidates = actions[["event_id", "symbol", "ex_date"]].merge(
        identity[["symbol", "security_id", "first_seen", "last_seen"]],
        on="symbol", how="left",
    )
    candidates = candidates.loc[
        candidates["first_seen"].le(candidates["ex_date"])
        & candidates["last_seen"].ge(candidates["ex_date"])
    ]
    counts = candidates.groupby("event_id")["security_id"].nunique()
    unique_ids = candidates.drop_duplicates("event_id").set_index("event_id")["security_id"]
    actions["security_id"] = actions["event_id"].map(unique_ids.where(counts.eq(1)))
    actions["identity_candidate_count"] = actions["event_id"].map(counts).fillna(0).astype(int)
    actions["identity_mapping_method"] = "UNRESOLVED"
    actions.loc[actions["security_id"].notna(), "identity_mapping_method"] = "DATED_ALIAS"

    # The accepted panel supplies a dated permanent identity when its observed
    # market row falls outside the identity table's first/last-seen range.
    observed = prices.loc[prices["market_observed"], ["date", "symbol", "security_id"]].drop_duplicates()
    fallback = actions.loc[actions["security_id"].isna(), ["event_id", "ex_date", "symbol"]].merge(
        observed, left_on=["ex_date", "symbol"], right_on=["date", "symbol"], how="left"
    )
    fallback_counts = fallback.groupby("event_id")["security_id"].nunique()
    fallback_ids = fallback.drop_duplicates("event_id").set_index("event_id")["security_id"]
    actions["security_id"] = actions["security_id"].fillna(
        actions["event_id"].map(fallback_ids.where(fallback_counts.eq(1)))
    )
    panel_mapped = actions["identity_mapping_method"].eq("UNRESOLVED") & actions["security_id"].notna()
    actions.loc[panel_mapped, "identity_mapping_method"] = "CONTEMPORANEOUS_PANEL_SYMBOL"

    # Some processed exchange records carry a later ticker on an older ex-date.
    # Use that alias only if the accepted identity maps it to exactly one
    # permanent security AND that same security has a panel row on the ex-date.
    alias_counts = identity.groupby("symbol")["security_id"].nunique()
    alias_ids = identity.drop_duplicates("symbol").set_index("symbol")["security_id"]
    alias_ids = alias_ids.where(alias_counts.eq(1))
    missing = actions["security_id"].isna()
    proposed = actions.loc[missing, ["event_id", "ex_date", "symbol"]].copy()
    proposed["candidate_id"] = proposed["symbol"].map(alias_ids)
    confirmed = proposed.merge(
        prices[["security_id", "date"]].drop_duplicates(),
        left_on=["candidate_id", "ex_date"], right_on=["security_id", "date"],
        how="inner", validate="many_to_one",
    )
    actions.loc[actions["event_id"].isin(confirmed["event_id"]), "security_id"] = (
        actions.loc[actions["event_id"].isin(confirmed["event_id"]), "event_id"]
        .map(confirmed.set_index("event_id")["security_id"])
    )
    actions.loc[
        actions["event_id"].isin(confirmed["event_id"]), "identity_mapping_method"
    ] = "UNIQUE_ACCEPTED_ALIAS_WITH_EX_DATE_PANEL_ID"

    accepted = treatments[[
        "event_id", "security_id", "effective_date", "valuation_date", "treatment_status",
        "cash_per_pre_event_share", "share_multiplier", "entitlement_value_per_pre_event_share",
        "blocks_total_return", "evidence_source",
    ]].rename(columns={
        "security_id": "accepted_security_id", "effective_date": "accepted_date",
        "valuation_date": "accepted_valuation_date", "treatment_status": "accepted_status",
        "cash_per_pre_event_share": "accepted_cash", "share_multiplier": "accepted_multiplier",
        "entitlement_value_per_pre_event_share": "accepted_entitlement",
        "blocks_total_return": "accepted_blocks", "evidence_source": "accepted_evidence",
    })
    actions = actions.merge(accepted, on="event_id", how="left", validate="one_to_one")
    reviewed = actions["accepted_status"].notna()
    if not reviewed.equals(actions["treatment_reviewed_for_in_universe_event"].fillna(False)):
        raise ValueError("Accepted treatment flags disagree with processed actions")
    if actions.loc[reviewed, "accepted_date"].ne(actions.loc[reviewed, "ex_date"]).any():
        raise ValueError("Accepted treatment effective date differs from action ex-date")
    actions.loc[reviewed, "security_id"] = actions.loc[reviewed, "accepted_security_id"]
    actions.loc[reviewed, "identity_mapping_method"] = "ACCEPTED_TREATMENT"

    member_ids = set(membership["security_id"])
    member_symbols = set(identity.loc[identity["security_id"].isin(member_ids), "symbol"])
    actions["signal_relevant"] = actions["security_id"].isin(member_ids)
    actions["possible_member_symbol"] = actions["symbol"].isin(member_symbols)
    actions["membership_status"] = "NOT_SIGNAL_RELEVANT"
    actions.loc[
        actions["security_id"].isna() & actions["possible_member_symbol"],
        "membership_status",
    ] = "POSSIBLE_MEMBER_IDENTITY_UNRESOLVED"
    first_membership = membership.groupby("security_id")["valid_from"].min()
    actions.loc[actions["signal_relevant"], "membership_status"] = "OUTSIDE_MEMBERSHIP"
    pre = actions["signal_relevant"] & actions["ex_date"].lt(actions["security_id"].map(first_membership))
    actions.loc[pre, "membership_status"] = "PRE_MEMBERSHIP"
    active = actions[["event_id", "security_id", "ex_date"]].dropna(subset=["security_id"]).merge(
        membership[["security_id", "valid_from", "valid_to"]], on="security_id", how="inner"
    )
    active = active.loc[
        active["valid_from"].le(active["ex_date"])
        & (active["valid_to"].isna() | active["ex_date"].lt(active["valid_to"]))
    ]
    if active["event_id"].duplicated().any():
        raise ValueError("Overlapping official membership intervals affect an action")
    actions.loc[actions["event_id"].isin(active["event_id"]), "membership_status"] = "IN_MEMBERSHIP"
    action_prices = prices[["security_id", "date", "previous_close", "close", "price_return", "base_return_status"]]
    return actions.merge(
        action_prices, left_on=["security_id", "ex_date"], right_on=["security_id", "date"],
        how="left", validate="many_to_one",
    ).drop(columns="date")


def classify_actions(actions: pd.DataFrame) -> pd.DataFrame:
    actions = actions.copy()
    actions["application_status"] = "RETURN_UNAVAILABLE_EXPLICIT"
    actions["application_reason"] = "TREATMENT_NOT_ACCEPTED"
    actions["cash_effect"] = 0.0
    actions["share_effect"] = 1.0
    actions["entitlement_effect"] = 0.0

    irrelevant = ~actions["signal_relevant"] & ~(
        actions["security_id"].isna() & actions["possible_member_symbol"]
    )
    actions.loc[irrelevant, "application_status"] = "NOT_SIGNAL_RELEVANT"
    actions.loc[irrelevant, "application_reason"] = "NO_RELEVANT_DATED_SECURITY"
    unknown_identity = actions["security_id"].isna() & actions["possible_member_symbol"]
    actions.loc[unknown_identity, "application_reason"] = "POSSIBLE_MEMBER_IDENTITY_UNRESOLVED"

    relevant = actions["signal_relevant"]
    reviewed = relevant & actions["accepted_status"].notna()
    no_direct = reviewed & actions["accepted_status"].eq("RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT")
    actions.loc[no_direct, "application_status"] = "NO_DIRECT_ADJUSTMENT_REQUIRED"
    actions.loc[no_direct, "application_reason"] = "ACCEPTED_NO_DIRECT_ADJUSTMENT"
    blocked = reviewed & actions["accepted_blocks"].eq(True)
    actions.loc[blocked, "application_reason"] = "ACCEPTED_STRICT_RETURN_EXCEPTION"
    accepted_effect = reviewed & ~blocked & ~no_direct
    accepted_valid = (
        accepted_effect
        & np.isfinite(actions["accepted_cash"].fillna(0))
        & np.isfinite(actions["accepted_multiplier"])
        & actions["accepted_multiplier"].gt(0)
        & np.isfinite(actions["accepted_entitlement"].fillna(0))
        & (actions["accepted_valuation_date"].isna()
           | actions["accepted_valuation_date"].le(actions["ex_date"]))
    )
    actions.loc[accepted_effect, "application_reason"] = "ACCEPTED_TREATMENT_INVALID_OR_LATE"
    actions.loc[accepted_valid, "application_status"] = "APPLIED_TO_RETURN"
    actions.loc[accepted_valid, "application_reason"] = "ACCEPTED_TREATMENT"
    actions.loc[accepted_valid, "cash_effect"] = actions.loc[accepted_valid, "accepted_cash"].fillna(0)
    actions.loc[accepted_valid, "share_effect"] = actions.loc[accepted_valid, "accepted_multiplier"]
    actions.loc[accepted_valid, "entitlement_effect"] = actions.loc[accepted_valid, "accepted_entitlement"].fillna(0)

    ordinary = relevant & ~reviewed & actions["primary_class"].isin(["DIVIDEND", "BONUS", "SPLIT"])
    simple = (
        ordinary & actions["series"].eq("EQ")
        & ~actions["needs_manual_review"].fillna(True)
        & actions["economic_event_count"].eq(1)
        & ~actions["multiple_event_types"].fillna(True)
    )
    actions.loc[ordinary, "application_reason"] = "ORDINARY_ACTION_PARSE_UNVERIFIED"
    dividend = (
        simple & actions["primary_class"].eq("DIVIDEND")
        & np.isfinite(actions["dividend_amount"]) & actions["dividend_amount"].gt(0)
    )
    bonus = (
        simple & actions["primary_class"].eq("BONUS")
        & np.isfinite(actions["ratio_a"]) & np.isfinite(actions["ratio_b"])
        & actions["ratio_a"].gt(0) & actions["ratio_b"].gt(0)
    )
    split = (
        simple & actions["primary_class"].eq("SPLIT")
        & np.isfinite(actions["old_face_value_parsed"])
        & np.isfinite(actions["new_face_value_parsed"])
        & actions["old_face_value_parsed"].gt(0)
        & actions["new_face_value_parsed"].gt(0)
    )
    for mask in (dividend, bonus, split):
        actions.loc[mask, "application_status"] = "APPLIED_TO_RETURN"
        actions.loc[mask, "application_reason"] = "UNAMBIGUOUS_PARSED_ORDINARY_ACTION"
    actions.loc[dividend, "cash_effect"] = actions.loc[dividend, "dividend_amount"]
    actions.loc[bonus, "share_effect"] = 1 + actions.loc[bonus, "ratio_a"] / actions.loc[bonus, "ratio_b"]
    actions.loc[split, "share_effect"] = (
        actions.loc[split, "old_face_value_parsed"] / actions.loc[split, "new_face_value_parsed"]
    )

    unavailable_market = (
        relevant & actions["application_status"].eq("APPLIED_TO_RETURN")
        & actions["price_return"].isna()
    )
    actions.loc[unavailable_market, "application_status"] = "RETURN_UNAVAILABLE_EXPLICIT"
    actions.loc[unavailable_market, "application_reason"] = "MARKET_OR_PREVIOUS_SESSION_UNAVAILABLE"

    # A reviewed treatment supersedes the same action copied into a second
    # exchange source. Two unreviewed descriptions with the same economics but
    # different wording are left unresolved rather than double credited.
    keys = actions.loc[relevant & actions["security_id"].notna()].groupby(
        ["security_id", "ex_date"], sort=False
    ).groups
    for indices in keys.values():
        if len(indices) < 2:
            continue
        group = actions.loc[indices]
        ready = group.loc[group["application_status"].eq("APPLIED_TO_RETURN")]
        for _, same in ready.groupby(
            ["primary_class", "cash_effect", "share_effect", "entitlement_effect"], sort=False
        ):
            if len(same) < 2:
                continue
            reviewed_same = same.loc[same["accepted_status"].notna()]
            if len(reviewed_same) == 1:
                keeper = reviewed_same.index[0]
            elif same["purpose_normalized"].nunique(dropna=False) == 1:
                keeper = same.sort_values("event_id").index[0]
            else:
                actions.loc[same.index, "application_status"] = "RETURN_UNAVAILABLE_EXPLICIT"
                actions.loc[same.index, "application_reason"] = "POSSIBLE_DUPLICATE_ECONOMIC_RECORD"
                continue
            duplicate_ids = same.index.difference(pd.Index([keeper]))
            actions.loc[duplicate_ids, "application_status"] = "NOT_SIGNAL_RELEVANT"
            actions.loc[duplicate_ids, "application_reason"] = "DUPLICATE_SOURCE_RECORD"

        current = actions.loc[indices]
        ready = current.loc[current["application_status"].eq("APPLIED_TO_RETURN")]
        unresolved = current["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").any()
        multiple_non_cash = len(ready) > 1 and (
            ready["share_effect"].ne(1).any() or ready["entitlement_effect"].ne(0).any()
        )
        if unresolved or multiple_non_cash:
            reason = "COINCIDENT_UNRESOLVED_ACTION" if unresolved else "MULTIPLE_ACTION_UNITS_UNVERIFIED"
            actions.loc[ready.index, "application_status"] = "RETURN_UNAVAILABLE_EXPLICIT"
            actions.loc[ready.index, "application_reason"] = reason

    actions["parsed_amount_or_ratio"] = np.select(
        [actions["primary_class"].eq("DIVIDEND"), actions["primary_class"].eq("BONUS"), actions["primary_class"].eq("SPLIT")],
        [
            actions["dividend_amount"].astype(str),
            actions["ratio_a"].astype(str) + ":" + actions["ratio_b"].astype(str),
            actions["old_face_value_parsed"].astype(str) + ":" + actions["new_face_value_parsed"].astype(str),
        ],
        default="",
    )
    return actions


def apply_manual_resolutions(
    events: pd.DataFrame, manual: pd.DataFrame, prices: pd.DataFrame,
) -> pd.DataFrame:
    """Apply reviewed holder economics without changing accepted source actions."""
    if manual["event_id"].isna().any() or manual["event_id"].duplicated().any():
        raise ValueError("Manual resolutions require unique event IDs")
    if not set(manual["event_id"]).issubset(set(events["event_id"])):
        raise ValueError("Manual resolution has no processed parent event")

    events = events.copy().set_index("event_id", drop=False)
    quotes = prices.loc[
        prices["market_observed"].fillna(False),
        ["date", "security_id", "symbol", "isin", "series", "close",
         "market_data_status", "identity_status"],
    ]
    for row in manual.itertuples(index=False):
        event = events.loc[row.event_id]
        if event.accepted_status is not None and pd.notna(event.accepted_status):
            raise ValueError(f"Manual treatment would overwrite an accepted event: {row.event_id}")
        if (
            event.security_id != row.security_id
            or event.symbol != row.symbol_at_event
            or event.ex_date != pd.Timestamp(row.event_date)
            or event.primary_class != row.event_type
            or event.source_file != row.source_file
            or event.series != "EQ"
            or not event.signal_relevant
            or event.application_status != "RETURN_UNAVAILABLE_EXPLICIT"
        ):
            raise ValueError(f"Manual treatment disagrees with accepted event: {row.event_id}")
        parent_quote = quotes.loc[
            quotes["security_id"].eq(row.security_id)
            & quotes["date"].eq(pd.Timestamp(row.event_date))
        ]
        if (
            len(parent_quote) != 1
            or parent_quote.iloc[0]["isin"] != row.isin
            or parent_quote.iloc[0]["series"] != "EQ"
            or parent_quote.iloc[0]["market_data_status"] != "OK"
            or parent_quote.iloc[0]["identity_status"] != "RESOLVED"
            or not np.isfinite(parent_quote.iloc[0]["close"])
            or parent_quote.iloc[0]["close"] <= 0
        ):
            raise ValueError(f"Manual treatment identity is not evidenced: {row.event_id}")
        if not row.evidence_url or not row.evidence_fact or not row.reasoning:
            raise ValueError(f"Manual treatment lacks evidence: {row.event_id}")
        if pd.Timestamp(row.event_date) > CUTOFF:
            raise ValueError("Manual treatment crosses development cutoff")

        cash = float(row.cash_per_pre_event_share)
        multiplier = float(row.share_multiplier)
        if not np.isfinite(cash) or cash < 0 or not np.isfinite(multiplier) or multiplier <= 0:
            raise ValueError(f"Invalid manual cash or share units: {row.event_id}")
        entitlement = 0.0
        if row.treatment_type == "COMBINED_BONUS_DIVIDEND":
            if row.event_type != "BONUS" or row.resolution_status != "RESOLVED_SIMPLE_ACTION" or multiplier <= 1:
                raise ValueError(f"Invalid combined bonus/dividend: {row.event_id}")
        elif row.treatment_type == "COMBINED_SPLIT_BONUS":
            if row.event_type != "SPLIT" or row.resolution_status != "RESOLVED_SIMPLE_ACTION" or cash != 0 or multiplier <= 1:
                raise ValueError(f"Invalid combined split/bonus: {row.event_id}")
        elif row.treatment_type == "LISTED_SHARE_DISTRIBUTION":
            if row.resolution_status != "RESOLVED_EXISTING_TREATMENT" or row.event_type != "STRUCTURAL" or cash != 0 or multiplier != 1:
                raise ValueError(f"Invalid listed-share distribution: {row.event_id}")
            price_date = pd.Timestamp(row.entitlement_price_date)
            if price_date != pd.Timestamp(row.event_date):
                raise ValueError(f"Distribution quote must be from the ex-date: {row.event_id}")
            received = quotes.loc[
                quotes["date"].eq(price_date)
                & quotes["symbol"].eq(row.entitlement_symbol)
                & quotes["isin"].eq(row.entitlement_isin)
                & quotes["series"].eq("EQ")
                & quotes["market_data_status"].eq("OK")
                & quotes["identity_status"].eq("RESOLVED")
            ]
            if len(received) != 1 or not np.isfinite(received.iloc[0]["close"]) or received.iloc[0]["close"] <= 0:
                raise ValueError(f"Received listed share has no usable ex-date quote: {row.event_id}")
            if not np.isclose(received.iloc[0]["close"], float(row.entitlement_price_close)):
                raise ValueError(f"Received share quote disagrees with evidence: {row.event_id}")
            units = float(row.entitlement_units_per_pre_event_share)
            if not np.isfinite(units) or units <= 0:
                raise ValueError(f"Invalid received share ratio: {row.event_id}")
            entitlement = units * float(received.iloc[0]["close"])
        elif row.treatment_type == "OPTIONAL_TENDER_NO_PARTICIPATION":
            if (
                row.event_type != "BUYBACK"
                or row.resolution_status != "RESOLVED_NO_DIRECT_ADJUSTMENT"
                or row.passive_holder_assumption != "DO_NOT_TENDER"
                or cash != 0 or multiplier != 1
            ):
                raise ValueError(f"Invalid no-tender treatment: {row.event_id}")
            events.at[row.event_id, "application_status"] = "NO_DIRECT_ADJUSTMENT_REQUIRED"
            events.at[row.event_id, "application_reason"] = "MANUAL_OPTIONAL_TENDER_NO_PARTICIPATION"
            continue
        else:
            raise ValueError(f"Unsupported manual treatment: {row.treatment_type}")

        events.at[row.event_id, "application_status"] = "APPLIED_TO_RETURN"
        events.at[row.event_id, "application_reason"] = "MANUAL_" + row.treatment_type
        events.at[row.event_id, "cash_effect"] = cash
        events.at[row.event_id, "share_effect"] = multiplier
        events.at[row.event_id, "entitlement_effect"] = entitlement

    return events.reset_index(drop=True)


def build_returns(prices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    relevant = events.loc[events["signal_relevant"] & events["security_id"].notna()]
    groups: list[dict[str, object]] = []
    for (security_id, date), group in relevant.groupby(["security_id", "ex_date"], sort=False):
        applied = group.loc[group["application_status"].eq("APPLIED_TO_RETURN")]
        blocked = group.loc[group["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT")]
        groups.append({
            "security_id": security_id,
            "date": date,
            "cash_effect": applied["cash_effect"].sum(),
            "share_effect": applied["share_effect"].prod(),
            "entitlement_effect": applied["entitlement_effect"].sum(),
            "applied_event_ids": ";".join(sorted(applied["event_id"])),
            "all_event_ids": ";".join(sorted(group["event_id"])),
            "adjustment_type": ";".join(sorted(set(applied["primary_class"]))) if not applied.empty else "NONE",
            "event_blocked": not blocked.empty,
            "event_block_reason": ";".join(sorted(set(blocked["application_reason"]))) if not blocked.empty else "",
        })
    daily = pd.DataFrame(groups, columns=[
        "security_id", "date", "cash_effect", "share_effect", "entitlement_effect",
        "applied_event_ids", "all_event_ids", "adjustment_type", "event_blocked", "event_block_reason",
    ])
    returns = prices[[
        "security_id", "date", "symbol", "isin", "previous_session_date",
        "previous_close", "close", "price_return", "base_return_status", "in_nifty500",
    ]].merge(daily, on=["security_id", "date"], how="left", validate="one_to_one")
    returns["cash_effect"] = pd.to_numeric(returns["cash_effect"], errors="coerce").fillna(0.0)
    returns["share_effect"] = pd.to_numeric(returns["share_effect"], errors="coerce").fillna(1.0)
    returns["entitlement_effect"] = pd.to_numeric(returns["entitlement_effect"], errors="coerce").fillna(0.0)
    returns["applied_event_ids"] = returns["applied_event_ids"].fillna("")
    returns["all_event_ids"] = returns["all_event_ids"].fillna("")
    returns["adjustment_type"] = returns["adjustment_type"].fillna("NONE")
    returns["event_blocked"] = returns["event_blocked"].fillna(False).astype(bool)
    returns["event_block_reason"] = returns["event_block_reason"].fillna("")
    returns["adjustment_applied"] = returns["applied_event_ids"].ne("")
    returns["total_return_available"] = returns["price_return"].notna() & ~returns["event_blocked"]
    returns["daily_total_return"] = np.nan
    valid = returns["total_return_available"]
    returns.loc[valid, "daily_total_return"] = (
        (returns.loc[valid, "share_effect"] * returns.loc[valid, "close"]
         + returns.loc[valid, "cash_effect"] + returns.loc[valid, "entitlement_effect"])
        / returns.loc[valid, "previous_close"] - 1
    )
    returns["quality_status"] = returns["base_return_status"]
    returns.loc[returns["event_blocked"], "quality_status"] = "CORPORATE_ACTION_UNRESOLVED"
    returns["exclusion_reason"] = ""
    unavailable = ~returns["total_return_available"]
    returns.loc[unavailable, "exclusion_reason"] = returns.loc[unavailable, "quality_status"]
    blocked = returns["event_blocked"]
    returns.loc[blocked, "exclusion_reason"] = returns.loc[blocked, "event_block_reason"]
    return returns.drop(columns=["base_return_status", "event_blocked", "event_block_reason"])


def validate(prices: pd.DataFrame, events: pd.DataFrame, returns: pd.DataFrame) -> None:
    if returns.duplicated(["security_id", "date"]).any():
        raise ValueError("Duplicate corrected security/date returns")
    if len(returns) != len(prices):
        raise ValueError("Corrected return layer lost a panel observation")
    if returns["date"].max() > CUTOFF or events["ex_date"].max() > CUTOFF:
        raise ValueError("Post-cutoff value entered return layer")
    statuses = {
        "APPLIED_TO_RETURN", "NO_DIRECT_ADJUSTMENT_REQUIRED",
        "RETURN_UNAVAILABLE_EXPLICIT", "NOT_SIGNAL_RELEVANT",
    }
    if events["application_status"].isna().any() or not set(events["application_status"]).issubset(statuses):
        raise ValueError("An economic event has no explicit disposition")
    unavailable = ~returns["total_return_available"]
    if returns.loc[unavailable, "daily_total_return"].notna().any():
        raise ValueError("Unavailable return was filled")
    if returns.loc[unavailable, "quality_status"].eq("OK").any():
        raise ValueError("Unavailable return has an OK quality status")
    if returns.loc[returns["previous_close"].isna(), "daily_total_return"].notna().any():
        raise ValueError("Missing previous canonical close was filled")
    plain = returns["total_return_available"] & ~returns["adjustment_applied"]
    if not np.allclose(returns.loc[plain, "daily_total_return"], returns.loc[plain, "price_return"]):
        raise ValueError("No-action total return differs from price return")
    dividends = events.loc[
        events["application_status"].eq("APPLIED_TO_RETURN")
        & events["primary_class"].eq("DIVIDEND") & events["share_effect"].eq(1)
    ]
    simple = dividends.merge(
        returns[["security_id", "date", "daily_total_return"]],
        left_on=["security_id", "ex_date"], right_on=["security_id", "date"], how="inner",
    )
    # On a day with two distinct dividends, the total difference contains
    # both cash payments rather than either one alone.
    one = simple.groupby(["security_id", "ex_date"])["event_id"].transform("size").eq(1)
    if not np.allclose(
        (simple.loc[one, "daily_total_return"] - simple.loc[one, "price_return"]).to_numpy(),
        (simple.loc[one, "cash_effect"] / simple.loc[one, "previous_close"]).to_numpy(),
    ):
        raise ValueError("Simple dividend return identity failed")
    strict_ids = {
        "CA_faa277a19bfa2ac115cc", "CA_df82d8fc43ad7e21c2a8",
        "CA_52dafdfb28d9f35d7326", "CA_9d29c825ee80b650567a",
    }
    strict = events[events["event_id"].isin(strict_ids)]
    if len(strict) != 4 or not strict["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all():
        raise ValueError("Four accepted bonus-debenture exceptions changed")
    corresponding = returns.merge(
        strict[["security_id", "ex_date"]], left_on=["security_id", "date"],
        right_on=["security_id", "ex_date"], how="inner",
    )
    if len(corresponding) != 4 or corresponding["daily_total_return"].notna().any():
        raise ValueError("A strict bonus-debenture daily return was fabricated")


def write_outputs(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    returns: pd.DataFrame,
    input_hashes: dict[str, str],
) -> dict[str, object]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return_columns = [
        "security_id", "date", "symbol", "isin", "previous_session_date",
        "previous_close", "close", "price_return", "daily_total_return",
        "total_return_available", "adjustment_applied", "adjustment_type",
        "applied_event_ids", "all_event_ids", "quality_status", "exclusion_reason",
        "in_nifty500", "cash_effect", "share_effect", "entitlement_effect",
    ]
    returns[return_columns].to_parquet(NEW_RETURNS, index=False)
    v2 = prices[PANEL_COLUMNS].merge(
        returns[[
            "security_id", "date", "previous_session_date", "previous_close",
            "price_return", "daily_total_return", "total_return_available",
            "adjustment_applied", "adjustment_type", "applied_event_ids",
            "all_event_ids", "quality_status", "exclusion_reason",
        ]],
        on=["security_id", "date"], how="left", validate="one_to_one",
    ).rename(columns={
        "price_return": "daily_price_return",
        "quality_status": "return_quality_status",
        "exclusion_reason": "return_exclusion_reason",
    })
    if len(v2) != len(prices) or v2["total_return_available"].isna().any():
        raise ValueError("Panel-v2 join failed")
    v2.to_parquet(NEW_PANEL, index=False)

    audit_columns = [
        "event_id", "security_id", "symbol", "series", "ex_date", "primary_class",
        "purpose_normalized", "source_file", "repair_status", "parsed_amount_or_ratio",
        "membership_status", "identity_candidate_count", "identity_mapping_method",
        "treatment_reviewed_for_in_universe_event",
        "accepted_status", "accepted_evidence", "previous_close", "close", "price_return",
        "application_status", "application_reason", "cash_effect", "share_effect",
        "entitlement_effect",
    ]
    detail = events[audit_columns].rename(columns={
        "close": "ex_date_close", "price_return": "calculated_price_return",
    })
    detail = detail.merge(
        returns[["security_id", "date", "daily_total_return"]],
        left_on=["security_id", "ex_date"], right_on=["security_id", "date"],
        how="left", validate="many_to_one",
    ).drop(columns="date").rename(columns={"daily_total_return": "calculated_total_return"})
    detail.to_csv(AUDIT_DIR / "event_application_detail.csv", index=False)
    detail.groupby(
        ["primary_class", "application_status", "membership_status"], dropna=False
    ).size().reset_index(name="events").to_csv(AUDIT_DIR / "event_coverage.csv", index=False)
    detail.loc[detail["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT")].to_csv(
        AUDIT_DIR / "unresolved_events.csv", index=False
    )
    detail.groupby(["primary_class", "application_status"]).size().reset_index(
        name="events"
    ).to_csv(AUDIT_DIR / "application_counts.csv", index=False)
    detail.groupby(["application_reason", "membership_status"], dropna=False).size().reset_index(
        name="events"
    ).to_csv(AUDIT_DIR / "event_reason_counts.csv", index=False)
    returns.groupby(["quality_status", "in_nifty500"], dropna=False).size().reset_index(
        name="security_dates"
    ).to_csv(AUDIT_DIR / "return_quality_counts.csv", index=False)

    examples = []
    for label, mask in [
        ("TCS_DIVIDEND", detail["symbol"].eq("TCS") & detail["ex_date"].eq(pd.Timestamp("2022-05-25"))),
        ("ORDINARY_BONUS", detail["primary_class"].eq("BONUS") & detail["application_status"].eq("APPLIED_TO_RETURN")),
        ("ORDINARY_SPLIT", detail["primary_class"].eq("SPLIT") & detail["application_status"].eq("APPLIED_TO_RETURN")),
        ("COMBINED", detail["accepted_status"].eq("RESOLVED_COMBINED") & detail["application_status"].eq("APPLIED_TO_RETURN")),
        ("NO_DIRECT", detail["application_status"].eq("NO_DIRECT_ADJUSTMENT_REQUIRED")),
        ("STRICT_EXCEPTION", detail["application_reason"].eq("ACCEPTED_STRICT_RETURN_EXCEPTION")),
    ]:
        chosen = detail.loc[mask].head(1).copy()
        if not chosen.empty:
            chosen.insert(0, "example", label)
            examples.append(chosen)
    pd.concat(examples, ignore_index=True).to_csv(AUDIT_DIR / "spot_checks.csv", index=False)

    comparison = prices[[
        "security_id", "date", "in_nifty500", "legacy_daily_total_return",
        "legacy_corporate_action_adjusted",
    ]].merge(
        returns[["security_id", "date", "daily_total_return"]],
        on=["security_id", "date"], how="left", validate="one_to_one",
    )
    different = ~np.isclose(
        comparison["legacy_daily_total_return"], comparison["daily_total_return"],
        rtol=1e-12, atol=1e-12, equal_nan=True,
    )

    summary = {
        "economic_action_rows": len(detail),
        "applied_events": int(detail["application_status"].eq("APPLIED_TO_RETURN").sum()),
        "no_direct_events": int(detail["application_status"].eq("NO_DIRECT_ADJUSTMENT_REQUIRED").sum()),
        "unavailable_events": int(detail["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").sum()),
        "not_signal_relevant_events": int(detail["application_status"].eq("NOT_SIGNAL_RELEVANT").sum()),
        "pre_membership_applied": int((detail["membership_status"].eq("PRE_MEMBERSHIP") & detail["application_status"].eq("APPLIED_TO_RETURN")).sum()),
        "in_membership_applied": int((detail["membership_status"].eq("IN_MEMBERSHIP") & detail["application_status"].eq("APPLIED_TO_RETURN")).sum()),
        "corrected_return_rows": len(returns),
        "old_adjusted_return_rows": int(prices["legacy_corporate_action_adjusted"].sum()),
        "adjusted_return_rows": int(returns["adjustment_applied"].sum()),
        "old_unavailable_return_rows": int(prices["legacy_daily_total_return"].isna().sum()),
        "unavailable_return_rows": int((~returns["total_return_available"]).sum()),
        "old_vs_corrected_return_difference_rows": int(different.sum()),
        "old_vs_corrected_difference_in_membership": int((different & comparison["in_nifty500"]).sum()),
        "maximum_value_date_read": max(prices["date"].max(), events["ex_date"].max()).date().isoformat(),
        "old_panel_sha256": input_hashes[str(OLD_PANEL)],
        "stock_total_returns_sha256": sha256(NEW_RETURNS),
        "research_panel_v2_sha256": sha256(NEW_PANEL),
    }
    pd.DataFrame(list(summary.items()), columns=["metric", "value"]).to_csv(
        AUDIT_DIR / "summary.csv", index=False
    )
    pd.DataFrame(
        [{"accepted_input": path, "sha256": digest} for path, digest in input_hashes.items()]
    ).to_csv(AUDIT_DIR / "accepted_input_hashes.csv", index=False)
    return summary


def main() -> None:
    inputs = [OLD_PANEL, CALENDAR, MEMBERSHIP, IDENTITY, ACTIONS, TREATMENTS, MANUAL_RESOLUTIONS]
    input_hashes = {str(path): sha256(path) for path in inputs}
    print("Reading cutoff-safe accepted inputs...")
    panel = read_through_cutoff(
        OLD_PANEL, "date", PANEL_COLUMNS + ["daily_total_return", "corporate_action_adjusted"]
    ).rename(columns={
        "daily_total_return": "legacy_daily_total_return",
        "corporate_action_adjusted": "legacy_corporate_action_adjusted",
    })
    calendar = read_through_cutoff(CALENDAR, "date", ["date", "previous_trading_day"])
    membership = read_through_cutoff(MEMBERSHIP, "valid_from", ["security_id", "valid_from", "valid_to"])
    identity = read_through_cutoff(IDENTITY, "first_seen", ["symbol", "security_id", "first_seen", "last_seen"])
    actions = read_through_cutoff(ACTIONS, "ex_date", ACTION_COLUMNS)
    treatments = read_through_cutoff(TREATMENTS, "effective_date", [
        "event_id", "security_id", "effective_date", "valuation_date", "treatment_status",
        "cash_per_pre_event_share", "share_multiplier", "entitlement_value_per_pre_event_share",
        "blocks_total_return", "evidence_source",
    ])
    manual = pd.read_csv(MANUAL_RESOLUTIONS)
    print("Mapping dated identities and classifying corporate-action treatments...")
    prices = prepare_prices(panel, calendar)
    events = classify_actions(map_actions(actions, identity, membership, treatments, prices))
    events = apply_manual_resolutions(events, manual, prices)
    returns = build_returns(prices, events)
    validate(prices, events, returns)
    if any(sha256(path) != input_hashes[str(path)] for path in inputs):
        raise ValueError("An accepted upstream artifact changed during this run")
    print("Writing corrected returns and panel-v2...")
    summary = write_outputs(prices, events, returns, input_hashes)
    print(f"Corrected return rows: {summary['corrected_return_rows']:,}")
    print(f"Adjusted return rows: {summary['adjusted_return_rows']:,}")
    print(f"Explicitly unavailable economic events: {summary['unavailable_events']:,}")
    print(f"Maximum value date read: {summary['maximum_value_date_read']}")


if __name__ == "__main__":
    main()
