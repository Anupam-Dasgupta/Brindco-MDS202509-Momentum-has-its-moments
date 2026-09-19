"""Construct daily economic returns from accepted prices and corporate actions."""

from __future__ import annotations

import numpy as np

import pandas as pd

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
