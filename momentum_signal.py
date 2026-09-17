"""Development 12-to-2 momentum features and official-index winner rosters."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
PANEL = PROCESSED / "research_panel_v2.parquet"
RETURNS = PROCESSED / "stock_total_returns.parquet"
OLD_PANEL = PROCESSED / "research_panel_build.parquet"
MEMBERSHIP = PROCESSED / "membership_official" / "nifty500_official_membership_intervals.parquet"
CALENDAR = PROCESSED / "nse_trading_calendar_2013_2026.parquet"
DELAYED = PROCESSED / "corporate_action_treatment" / "bonus_debenture_delayed_recognition.csv"
TIMING = ROOT / "results" / "corporate_action_treatment" / "bonus_debenture_signal_timing_audit.csv"
UNRESOLVED = ROOT / "results" / "stock_total_return_audit" / "unresolved_events.csv"
MONTHLY_OUTPUT = PROCESSED / "momentum_monthly_features.parquet"
FORMATIONS_OUTPUT = PROCESSED / "momentum_formations.parquet"
WINNERS_OUTPUT = PROCESSED / "momentum_winners.parquet"
AUDIT = ROOT / "results" / "momentum_signal_audit"
CUTOFF = pd.Timestamp("2023-03-31")
FIRST_FORMATION = pd.Period("2014-08", freq="M")
LAST_FORMATION = pd.Period("2023-02", freq="M")
FIRST_SCORED = pd.Period("2015-03", freq="M")
DELAYED_IDS = {"CA_faa277a19bfa2ac115cc", "CA_df82d8fc43ad7e21c2a8"}


def require_corrected_sources(panel_path: Path = PANEL, returns_path: Path = RETURNS) -> None:
    if panel_path.resolve() != PANEL.resolve() or returns_path.resolve() != RETURNS.resolve():
        raise ValueError("Momentum requires research_panel_v2 and stock_total_returns; panel v1 is revoked")
    if panel_path == OLD_PANEL or returns_path == OLD_PANEL:
        raise ValueError("Old panel total returns are revoked")


def read_parquet_before_cutoff(path: Path, columns: list[str], date_column: str) -> pd.DataFrame:
    frame = ds.dataset(path, format="parquet").to_table(
        columns=columns, filter=ds.field(date_column) <= CUTOFF.to_datetime64()
    ).to_pandas()
    frame[date_column] = pd.to_datetime(frame[date_column])
    if not frame.empty and frame[date_column].max() > CUTOFF:
        raise ValueError(f"Value after development cutoff: {path}")
    return frame


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    require_corrected_sources()
    panel_columns = [
        "date", "security_id", "symbol", "series", "close", "market_observed",
        "market_data_status", "identity_status", "adv20_lagged", "adv20_complete",
        "adv20_observation_count", "positive_volume_sessions_20", "in_nifty500",
        "momentum_signal_safe", "momentum_signal_exclusion_reason",
        "corporate_action_timing_event_ids", "is_formation_date", "daily_total_return",
    ]
    return_columns = [
        "date", "security_id", "daily_total_return", "price_return", "previous_close",
        "total_return_available", "exclusion_reason", "all_event_ids", "quality_status",
    ]
    panel = read_parquet_before_cutoff(PANEL, panel_columns, "date")
    returns = read_parquet_before_cutoff(RETURNS, return_columns, "date")
    if panel.duplicated(["security_id", "date"]).any() or returns.duplicated(["security_id", "date"]).any():
        raise ValueError("Duplicate security/date in authoritative inputs")
    panel = panel.sort_values(["security_id", "date"]).reset_index(drop=True)
    returns = returns.sort_values(["security_id", "date"]).reset_index(drop=True)
    if not panel[["security_id", "date"]].equals(returns[["security_id", "date"]]):
        raise ValueError("Panel-v2 and corrected-return keys disagree")
    if not np.allclose(panel["daily_total_return"], returns["daily_total_return"], equal_nan=True):
        raise ValueError("Panel-v2 returns disagree with authoritative corrected returns")
    panel = panel.drop(columns="daily_total_return")
    for column in return_columns[2:]:
        panel[column] = returns[column]
    calendar = read_parquet_before_cutoff(
        CALENDAR, ["date", "is_last_trading_day_of_month"], "date"
    )
    membership = pd.read_parquet(MEMBERSHIP, columns=[
        "security_id", "published_symbol", "valid_from", "valid_to", "evidence_status"
    ])
    if membership["evidence_status"].str.contains("snapshot_floor", case=False, na=False).any():
        raise ValueError("Official membership contains old snapshot_floor evidence")
    delayed = pd.read_csv(DELAYED, parse_dates=["event_ex_date", "price_trade_date"])
    timing = pd.read_csv(TIMING, parse_dates=["formation_date"])
    return panel, calendar, membership, delayed, timing


def build_monthly(panel: pd.DataFrame, calendar: pd.DataFrame,
                  delayed: pd.DataFrame, timing: pd.DataFrame) -> pd.DataFrame:
    daily = panel[[
        "security_id", "date", "market_observed", "market_data_status", "identity_status",
        "daily_total_return", "price_return", "previous_close", "total_return_available",
        "exclusion_reason", "all_event_ids", "quality_status",
    ]].copy()
    daily["month"] = daily["date"].dt.to_period("M")
    sessions = calendar.assign(month=calendar["date"].dt.to_period("M"))
    expected = sessions.groupby("month")["date"].size()
    daily["valid"] = (
        daily["market_observed"].fillna(False)
        & daily["market_data_status"].eq("OK")
        & daily["identity_status"].eq("RESOLVED")
        & daily["total_return_available"].fillna(False)
        & np.isfinite(daily["daily_total_return"])
        & daily["daily_total_return"].ge(-1)
    )
    daily["gross"] = (1 + daily["daily_total_return"]).where(daily["valid"])
    grouped = daily.groupby(["security_id", "month"], sort=False)
    monthly = grouped.agg(
        observed_sessions=("date", "size"), valid_returns=("valid", "sum"),
        gross=("gross", "prod"),
    ).reset_index()
    monthly["expected_sessions"] = monthly["month"].map(expected)
    bad = daily.loc[~daily["valid"]].copy()
    bad["reason"] = bad["exclusion_reason"].fillna("")
    blank = bad["reason"].eq("")
    bad.loc[blank, "reason"] = bad.loc[blank, "quality_status"].fillna("RETURN_UNAVAILABLE")
    causes = bad.groupby(["security_id", "month"], sort=False).agg(
        unavailable_reasons=("reason", lambda s: ";".join(sorted(set(s)))),
        unavailable_event_ids=("all_event_ids", lambda s: ";".join(sorted({
            event for cell in s.dropna() for event in str(cell).split(";") if event
        }))),
    ).reset_index()
    monthly = monthly.merge(causes, on=["security_id", "month"], how="left", validate="one_to_one")
    short_month = monthly["observed_sessions"].lt(monthly["expected_sessions"])
    monthly.loc[short_month, "unavailable_reasons"] = (
        monthly.loc[short_month, "unavailable_reasons"].fillna("").str.strip(";")
        + ";CANONICAL_SESSIONS_MISSING"
    ).str.strip(";")
    monthly["method"] = "STRICT_DAILY_COMPOUNDING"
    monthly["delayed_event_id"] = pd.Series(pd.NA, index=monthly.index, dtype="string")
    monthly["recognition_date"] = pd.NaT
    monthly["information_available_timestamp"] = pd.Series(
        pd.NaT, index=monthly.index, dtype="datetime64[ns, UTC]"
    )
    monthly["entitlement_value_per_pre_event_share"] = np.nan
    monthly["entitlement_evidence_source"] = pd.Series(pd.NA, index=monthly.index, dtype="string")

    # Credit each accepted entitlement at the *monthly endpoint*, not on its
    # equity ex-date. The equity leg uses the ex-date price move, while the
    # separate entitlement leg is never compounded through later equity days.
    for event_id, tranches in delayed.loc[delayed["event_id"].isin(DELAYED_IDS)].groupby("event_id"):
        event_timing = timing.loc[timing["event_id"].eq(event_id)]
        affected_timing = event_timing.loc[event_timing["equity_ex_date_in_window"]]
        if (affected_timing.empty or not event_timing["formation_safe"].all()
                or not event_timing["all_legs_or_none_in_window"].all()
                or not affected_timing["information_available_by_formation"].all()):
            continue
        if not tranches["actual_official_trade"].all():
            continue
        if tranches["event_ex_date"].nunique() != 1 or tranches["price_trade_date"].dt.to_period("M").nunique() != 1:
            continue
        event_date = tranches["event_ex_date"].iloc[0]
        event_month = event_date.to_period("M")
        if tranches["price_trade_date"].dt.to_period("M").iloc[0] != event_month:
            continue
        last_session = sessions.loc[sessions["month"].eq(event_month), "date"].max()
        first_formation = affected_timing.sort_values("formation_date").iloc[0]
        information_time = pd.to_datetime(tranches["information_available_timestamp"], utc=True).max()
        formation_time = pd.to_datetime(first_formation["formation_timestamp"], utc=True)
        if (tranches["price_trade_date"].max() > last_session
                or information_time > formation_time):
            continue
        security_id = tranches["security_id"].iloc[0]
        if tranches["security_id"].nunique() != 1 or not tranches["entitlement_value_per_pre_event_share"].map(np.isfinite).all():
            continue
        subset = daily.loc[daily["security_id"].eq(security_id) & daily["month"].eq(event_month)].sort_values("date")
        exception = subset.loc[subset["date"].eq(event_date)]
        if len(exception) != 1 or event_id not in str(exception["all_event_ids"].iloc[0]).split(";"):
            continue
        if exception["exclusion_reason"].iloc[0] != "ACCEPTED_STRICT_RETURN_EXCEPTION":
            continue
        other = subset.loc[subset["date"].ne(event_date)]
        if len(subset) != expected[event_month] or not other["valid"].all():
            continue
        ex = exception.iloc[0]
        if not np.isfinite(ex["price_return"]) or not np.isfinite(ex["previous_close"]) or ex["previous_close"] <= 0:
            continue
        pre_gross = float(np.prod(1 + other.loc[other["date"].lt(event_date), "daily_total_return"]))
        equity_gross = float(np.prod(1 + other["daily_total_return"]) * (1 + ex["price_return"]))
        entitlement = float(tranches["entitlement_value_per_pre_event_share"].sum())
        total_gross = equity_gross + pre_gross * entitlement / ex["previous_close"]
        row = monthly["security_id"].eq(security_id) & monthly["month"].eq(event_month)
        if row.sum() != 1 or monthly.loc[row, "valid_returns"].iloc[0] != expected[event_month] - 1:
            continue
        monthly.loc[row, "gross"] = total_gross
        monthly.loc[row, "method"] = "DELAYED_RECOGNITION_MONTHLY_ENDPOINT"
        monthly.loc[row, "delayed_event_id"] = event_id
        monthly.loc[row, "recognition_date"] = tranches["price_trade_date"].max()
        monthly.loc[row, "information_available_timestamp"] = information_time
        monthly.loc[row, "entitlement_value_per_pre_event_share"] = entitlement
        monthly.loc[row, "entitlement_evidence_source"] = ";".join(sorted(set(tranches["price_evidence_source"])))

    monthly["complete"] = (
        monthly["observed_sessions"].eq(monthly["expected_sessions"])
        & (monthly["valid_returns"].eq(monthly["expected_sessions"])
           | (monthly["method"].eq("DELAYED_RECOGNITION_MONTHLY_ENDPOINT")
              & monthly["valid_returns"].eq(monthly["expected_sessions"] - 1)))
        & monthly["gross"].map(np.isfinite)
    )
    monthly.loc[~monthly["complete"], "gross"] = np.nan
    monthly["monthly_total_return"] = monthly["gross"] - 1
    monthly.loc[monthly["complete"], ["unavailable_reasons", "unavailable_event_ids"]] = ""

    # Explicitly materialise missing security-months so a gap cannot shrink
    # an eleven-month window by accident.
    all_months = pd.period_range(calendar["date"].min().to_period("M"),
                                 calendar["date"].max().to_period("M"), freq="M")
    all_ids = pd.Index(panel["security_id"].unique(), name="security_id")
    spine = pd.MultiIndex.from_product([all_ids, all_months], names=["security_id", "month"])
    monthly = monthly.set_index(["security_id", "month"]).reindex(spine).reset_index()
    monthly["expected_sessions"] = monthly["month"].map(expected)
    monthly["complete"] = monthly["complete"].fillna(False).astype(bool)
    monthly["method"] = monthly["method"].fillna("MISSING_MONTH")
    monthly["unavailable_reasons"] = monthly["unavailable_reasons"].fillna("MONTHLY_MARKET_OBSERVATIONS_MISSING")
    monthly["unavailable_event_ids"] = monthly["unavailable_event_ids"].fillna("")
    month_end = sessions.loc[sessions["is_last_trading_day_of_month"], ["month", "date"]]
    monthly["month_end"] = monthly["month"].map(month_end.set_index("month")["date"])
    return monthly


def build_roster(membership: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    formation_dates = calendar.loc[calendar["is_last_trading_day_of_month"], "date"]
    formation_dates = formation_dates.loc[
        formation_dates.dt.to_period("M").between(FIRST_FORMATION, LAST_FORMATION)
    ]
    rosters = []
    for date in formation_dates:
        current = membership.loc[
            membership["valid_from"].le(date)
            & (membership["valid_to"].isna() | membership["valid_to"].gt(date)),
            ["security_id", "published_symbol"],
        ].copy()
        current["formation_date"] = date
        rosters.append(current)
    roster = pd.concat(rosters, ignore_index=True)
    if roster.duplicated(["formation_date", "security_id"]).any() or roster.groupby("formation_date").size().lt(500).any():
        raise ValueError("Official formation roster has missing or duplicate identities")
    roster["formation_month"] = roster["formation_date"].dt.to_period("M")
    roster["holding_month"] = roster["formation_month"] + 1
    roster["scored"] = roster["formation_month"].ge(FIRST_SCORED)
    return roster


def attach_formation_observations(roster: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    formation_rows = panel.loc[panel["is_formation_date"], [
        "date", "security_id", "symbol", "series", "close", "market_observed",
        "market_data_status", "identity_status", "adv20_lagged", "adv20_complete",
        "adv20_observation_count", "positive_volume_sessions_20", "in_nifty500",
        "momentum_signal_safe", "momentum_signal_exclusion_reason",
        "corporate_action_timing_event_ids",
    ]].rename(columns={"date": "formation_date"})
    formations = roster.merge(formation_rows, on=["formation_date", "security_id"],
                              how="left", validate="one_to_one", indicator=True)
    formations["formation_market_observation_missing"] = formations["_merge"].eq("left_only")
    formations = formations.drop(columns="_merge")
    mismatched = formations["in_nifty500"].eq(False) & ~formations["formation_market_observation_missing"]
    if mismatched.any():
        raise ValueError("Panel-v2 membership conflicts with official interval roster")
    return formations


def usable_formation_quote(formations: pd.DataFrame) -> pd.Series:
    return (
        ~formations["formation_market_observation_missing"]
        & formations["market_observed"].fillna(False)
        & formations["identity_status"].eq("RESOLVED")
        & formations["market_data_status"].eq("OK")
        & formations["series"].isin(["EQ", "BE", "BZ"])
        & np.isfinite(formations["close"]) & formations["close"].gt(0)
    )


def rank_winners(formations: pd.DataFrame) -> pd.DataFrame:
    formations["rank"] = pd.Series(pd.NA, index=formations.index, dtype="Int64")
    formations["eligible_count"] = formations.groupby("formation_date")["eligible"].transform("sum")
    formations["target_winner_count"] = formations["eligible_count"].map(lambda n: math.ceil(n / 10))
    if formations.groupby("formation_date")["eligible_count"].first().lt(20).any():
        raise ValueError("At least one formation has fewer than 20 eligible names")
    eligible = formations.loc[formations["eligible"]].sort_values(
        ["formation_date", "momentum_score", "security_id"], ascending=[True, False, True]
    )
    formations.loc[eligible.index, "rank"] = eligible.groupby("formation_date").cumcount().to_numpy() + 1
    formations["winner"] = formations["eligible"] & formations["rank"].le(formations["target_winner_count"]).fillna(False)
    return formations


def build_formations(roster: pd.DataFrame, panel: pd.DataFrame,
                     monthly: pd.DataFrame, timing: pd.DataFrame) -> pd.DataFrame:
    formations = attach_formation_observations(roster, panel)

    monthly = monthly.sort_values(["security_id", "month"]).copy()
    monthly["valid_gross"] = monthly["gross"].where(monthly["complete"])
    grouped = monthly.groupby("security_id", sort=False)["valid_gross"]
    monthly["momentum_score"] = grouped.transform(
        lambda s: s.rolling(11, min_periods=11).apply(np.prod, raw=True).shift(1) - 1
    )
    monthly["complete_lookback_months"] = monthly.groupby("security_id", sort=False)["complete"].transform(
        lambda s: s.astype(int).rolling(11, min_periods=11).sum().shift(1)
    )
    scores = monthly[["security_id", "month", "momentum_score", "complete_lookback_months"]]
    formations = formations.merge(scores, left_on=["security_id", "formation_month"],
                                  right_on=["security_id", "month"], how="left", validate="one_to_one")
    formations = formations.drop(columns="month")
    timing = timing.loc[
        timing["symbol"].eq("BRITANNIA") & timing["formation_date"].isin(formations["formation_date"])
        & timing["formation_safe"].eq(False), ["event_id", "formation_date", "unsafe_reason"]
    ]
    if len(timing) != 8:
        raise ValueError(f"Expected eight Britannia partial windows, got {len(timing)}")
    britannia = "NSE_444C594AB9B7"
    affected = formations["security_id"].eq(britannia) & formations["formation_date"].isin(timing["formation_date"])
    if affected.sum() != 8 or not formations.loc[affected, "momentum_signal_safe"].eq(False).all():
        raise ValueError("Panel-v2 Britannia timing flags disagree with the accepted audit")
    if formations.loc[~affected, "momentum_signal_safe"].eq(False).any():
        raise ValueError("Unexplained unsafe formation outside accepted Britannia timing cases")

    formations["quote_usable"] = usable_formation_quote(formations)
    formations["adv_eligible"] = (
        formations["adv20_complete"].fillna(False)
        & formations["adv20_observation_count"].eq(20)
        & np.isfinite(formations["adv20_lagged"])
        & formations["adv20_lagged"].gt(0)
    )
    formations["volume_eligible"] = formations["positive_volume_sessions_20"].ge(15)
    formations["history_eligible"] = formations["complete_lookback_months"].eq(11) & np.isfinite(formations["momentum_score"])
    formations["timing_eligible"] = ~affected
    formations["eligible"] = (
        formations["quote_usable"] & formations["adv_eligible"]
        & formations["volume_eligible"] & formations["history_eligible"]
        & formations["timing_eligible"]
    )
    formations["signal_exclusion_reason"] = ""
    formations.loc[~formations["quote_usable"], "signal_exclusion_reason"] = "FORMATION_QUOTE_INVALID"
    formations.loc[~formations["volume_eligible"], "signal_exclusion_reason"] = "INSUFFICIENT_POSITIVE_VOLUME_SESSIONS"
    formations.loc[~formations["adv_eligible"], "signal_exclusion_reason"] = "ADV_UNAVAILABLE"
    formations.loc[~formations["history_eligible"], "signal_exclusion_reason"] = "MONTHLY_RETURN_HISTORY_INCOMPLETE"
    formations.loc[formations["formation_market_observation_missing"], "signal_exclusion_reason"] = "FORMATION_MARKET_OBSERVATION_MISSING"
    formations.loc[affected, "signal_exclusion_reason"] = "BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW"

    # Every gate remains visible even when another one determines the primary reason.
    formations["additional_exclusion_reasons"] = [
        ";".join(reason for failed, reason in [
            (not q, "FORMATION_QUOTE_INVALID"), (not a, "ADV_UNAVAILABLE"),
            (not v, "INSUFFICIENT_POSITIVE_VOLUME_SESSIONS"),
            (not h, "MONTHLY_RETURN_HISTORY_INCOMPLETE"),
            (not t, "BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW"),
            (m, "FORMATION_MARKET_OBSERVATION_MISSING"),
        ] if failed)
        for q, a, v, h, t, m in zip(
            formations["quote_usable"], formations["adv_eligible"],
            formations["volume_eligible"], formations["history_eligible"],
            formations["timing_eligible"], formations["formation_market_observation_missing"]
        )
    ]
    formations = rank_winners(formations)
    formations["lookback_first_month"] = formations["formation_month"] - 11
    formations["lookback_last_month"] = formations["formation_month"] - 1
    monthly_index = monthly.set_index(["security_id", "month"])
    formations["lookback_unavailable_months"] = ""
    formations["lookback_unavailable_reasons"] = ""
    formations["lookback_unavailable_event_ids"] = ""
    for index, row in formations.loc[~formations["history_eligible"]].iterrows():
        missing = []
        causes = []
        events = set()
        for month in pd.period_range(row.lookback_first_month, row.lookback_last_month, freq="M"):
            feature = monthly_index.loc[(row.security_id, month)]
            if feature["complete"]:
                continue
            missing.append(str(month))
            causes.append(f"{month}:{feature['unavailable_reasons']}")
            events.update(e for e in feature["unavailable_event_ids"].split(";") if e)
        formations.at[index, "lookback_unavailable_months"] = ";".join(missing)
        formations.at[index, "lookback_unavailable_reasons"] = ";".join(causes)
        formations.at[index, "lookback_unavailable_event_ids"] = ";".join(sorted(events))
    return formations


def audit_unresolved(formations: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    unresolved = pd.read_csv(UNRESOLVED, parse_dates=["ex_date"])
    unresolved["event_month"] = unresolved["ex_date"].dt.to_period("M")
    by_candidate = formations.set_index(["formation_date", "security_id"])
    by_month = monthly.set_index(["security_id", "month"])
    formation_dates = formations["formation_date"].drop_duplicates().sort_values()
    winner_threshold = (
        formations.loc[formations["winner"]]
        .groupby("formation_date")["momentum_score"].min()
    )
    rows = []
    for event in unresolved.itertuples(index=False):
        relevant_dates = formation_dates.loc[
            formation_dates.dt.to_period("M").ge(event.event_month + 1)
            & formation_dates.dt.to_period("M").le(event.event_month + 11)
        ]
        if pd.isna(event.security_id):
            rows.append({
                "event_id": event.event_id, "security_id": "", "event_date": event.ex_date,
                "affected_monthly_feature": str(event.event_month), "formation_date": pd.NaT,
                "membership_at_formation": pd.NA, "final_signal_availability_changed": pd.NA,
                "otherwise_eligible_except_event": pd.NA, "would_otherwise_be_winner": "UNKNOWN_IDENTITY",
                "required_event_month_return_to_win": np.nan, "event_reason": event.application_reason,
            })
            continue
        feature = by_month.loc[(event.security_id, event.event_month)] if (
            event.security_id, event.event_month
        ) in by_month.index else None
        feature_used_delayed = (
            feature is not None and pd.notna(feature["delayed_event_id"])
            and feature["delayed_event_id"] == event.event_id
        )
        for formation_date in relevant_dates:
            if (formation_date, event.security_id) not in by_candidate.index:
                rows.append({
                    "event_id": event.event_id, "security_id": event.security_id,
                    "event_date": event.ex_date, "affected_monthly_feature": str(event.event_month),
                    "formation_date": formation_date, "membership_at_formation": False,
                    "final_signal_availability_changed": False,
                    "otherwise_eligible_except_event": False,
                    "would_otherwise_be_winner": "NOT_OFFICIAL_MEMBER",
                    "required_event_month_return_to_win": np.nan, "event_reason": event.application_reason,
                })
                continue
            candidate = by_candidate.loc[(formation_date, event.security_id)]
            other_months = by_month.loc[[
                (event.security_id, month) for month in pd.period_range(
                    candidate.lookback_first_month, candidate.lookback_last_month, freq="M"
                ) if month != event.event_month
            ]]
            only_event_blocks = (
                len(other_months) == 10 and other_months["complete"].all()
                and feature is not None and event.event_id in feature["unavailable_event_ids"].split(";")
                and len(feature["unavailable_event_ids"].split(";")) == 1
                and int(feature["valid_returns"]) == int(feature["expected_sessions"]) - 1
            )
            otherwise = bool(candidate.quote_usable and candidate.adv_eligible and
                             candidate.volume_eligible and candidate.timing_eligible and only_event_blocks)
            changed = bool(otherwise and not feature_used_delayed and not candidate.eligible)
            threshold = np.nan
            if changed:
                other_gross = float(other_months["gross"].prod())
                if other_gross > 0:
                    # A diagnostic threshold, not a guessed return or a rank.
                    threshold = (1 + winner_threshold.loc[formation_date]) / other_gross - 1
            rows.append({
                "event_id": event.event_id, "security_id": event.security_id,
                "event_date": event.ex_date, "affected_monthly_feature": str(event.event_month),
                "formation_date": formation_date, "membership_at_formation": True,
                "final_signal_availability_changed": changed,
                "otherwise_eligible_except_event": otherwise,
                "would_otherwise_be_winner": "UNKNOWN_MISSING_ECONOMIC_RETURN" if changed else "NO_INDEPENDENT_ELIGIBILITY",
                "required_event_month_return_to_win": threshold,
                "event_reason": event.application_reason,
            })
        if relevant_dates.empty:
            rows.append({
                "event_id": event.event_id, "security_id": event.security_id,
                "event_date": event.ex_date, "affected_monthly_feature": str(event.event_month),
                "formation_date": pd.NaT, "membership_at_formation": False,
                "final_signal_availability_changed": False, "otherwise_eligible_except_event": False,
                "would_otherwise_be_winner": "NO_APPLICABLE_FORMATION",
                "required_event_month_return_to_win": np.nan, "event_reason": event.application_reason,
            })
    return pd.DataFrame(rows)


def main() -> None:
    panel, calendar, membership, delayed, timing = load_inputs()
    monthly = build_monthly(panel, calendar, delayed, timing)
    roster = build_roster(membership, calendar)
    formations = build_formations(roster, panel, monthly, timing)
    unresolved = audit_unresolved(formations, monthly)
    winners = formations.loc[formations["winner"], [
        "formation_date", "holding_month", "scored", "security_id", "symbol",
        "momentum_score", "rank", "eligible_count", "target_winner_count",
    ]].sort_values(["formation_date", "rank"])
    if formations["signal_exclusion_reason"].eq("BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW").sum() != 8:
        raise ValueError("Britannia timing exclusion invariant failed")
    if formations.duplicated(["formation_date", "security_id"]).any():
        raise ValueError("Duplicate official economic security at formation")
    if formations["formation_date"].max() > CUTOFF or panel["date"].max() > CUTOFF:
        raise ValueError("Development cutoff breached")
    AUDIT.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(MONTHLY_OUTPUT, index=False)
    formations.to_parquet(FORMATIONS_OUTPUT, index=False)
    winners.to_parquet(WINNERS_OUTPUT, index=False)
    unresolved.to_csv(AUDIT / "unresolved_event_materiality.csv", index=False)
    material = unresolved.loc[unresolved["final_signal_availability_changed"].eq(True)]
    priority = material.groupby(["event_id", "security_id", "event_date", "event_reason"]).agg(
        affected_formations=("formation_date", "size"),
        lowest_required_month_return_to_win=("required_event_month_return_to_win", "min"),
        formations_with_required_return_at_most_10pct=(
            "required_event_month_return_to_win", lambda s: int(s.le(0.10).sum())
        ),
    ).reset_index().sort_values(["formations_with_required_return_at_most_10pct", "affected_formations"],
                                 ascending=False)
    priority.to_csv(AUDIT / "unresolved_event_priority.csv", index=False)
    formations.loc[~formations["eligible"], [
        "formation_date", "security_id", "published_symbol", "signal_exclusion_reason",
        "additional_exclusion_reasons", "complete_lookback_months",
    ]].to_csv(AUDIT / "formation_exclusions.csv", index=False)
    monthly.loc[monthly["method"].eq("DELAYED_RECOGNITION_MONTHLY_ENDPOINT")].to_csv(
        AUDIT / "delayed_monthly_features.csv", index=False
    )
    formations.groupby(["formation_date", "holding_month", "scored"], as_index=False).agg(
        official_members=("security_id", "size"), eligible=("eligible", "sum"),
        winners=("winner", "sum"), missing_formation_observations=("formation_market_observation_missing", "sum"),
    ).to_csv(AUDIT / "formation_summary.csv", index=False)
    summary = pd.DataFrame([
        ("monthly_feature_rows", len(monthly)),
        ("official_formation_rows", len(formations)),
        ("formation_dates", formations["formation_date"].nunique()),
        ("scored_formations", formations.loc[formations["scored"], "formation_date"].nunique()),
        ("warmup_formations", formations.loc[~formations["scored"], "formation_date"].nunique()),
        ("eligible_rows", int(formations["eligible"].sum())),
        ("winner_rows", len(winners)),
        ("scored_winner_rows", int(winners["scored"].sum())),
        ("delayed_monthly_features", int(monthly["method"].eq("DELAYED_RECOGNITION_MONTHLY_ENDPOINT").sum())),
        ("britannia_timing_exclusions", int(formations["signal_exclusion_reason"].eq("BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW").sum())),
        ("unresolved_event_audit_rows", len(unresolved)),
        ("unresolved_independent_signal_blockers", int(unresolved["final_signal_availability_changed"].eq(True).sum())),
        ("material_unresolved_events", len(priority)),
        ("max_value_date_read", panel["date"].max().date()),
        ("max_formation_date", formations["formation_date"].max().date()),
    ], columns=["measure", "value"])
    summary.to_csv(AUDIT / "summary.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
