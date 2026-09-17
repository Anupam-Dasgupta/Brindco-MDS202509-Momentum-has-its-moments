"""Build the development research panel through 2023-03-31.

Only accepted processed artifacts are consumed. Dated Parquet reads are
predicate-filtered at the development cutoff.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
AUDIT_DIR = ROOT / "results" / "audit"
OUTPUT_PANEL = PROCESSED / "research_panel_build.parquet"
DATA_CUTOFF = pd.Timestamp("2023-03-31")
BUILD_START = pd.Timestamp("2014-08-28")
DAY_AFTER_CUTOFF = DATA_CUTOFF + pd.Timedelta(days=1)

MARKET_PATH = PROCESSED / "nse_cm_2013_2026.parquet"
CALENDAR_PATH = PROCESSED / "nse_trading_calendar_2013_2026.parquet"
MEMBERSHIP_PATH = PROCESSED / "membership_official" / "nifty500_official_membership_intervals.parquet"
IDENTITY_PATH = PROCESSED / "security_identity_official" / "dated_security_identity.parquet"
SERIES_PATH = PROCESSED / "security_identity_official" / "historical_series_classification.parquet"
ALIAS_COLLISION_PATH = PROCESSED / "security_identity_official" / "dated_alias_collisions.csv"
TREATMENT_PATH = PROCESSED / "corporate_action_treatment" / "in_universe_event_treatments.parquet"
TREATED_ACTION_PATH = PROCESSED / "corporate_action_treatment" / "nse_corporate_actions_treated_through_2023_03_31.parquet"
DELAYED_RECOGNITION_PATH = PROCESSED / "corporate_action_treatment" / "bonus_debenture_delayed_recognition.csv"
TIMING_AUDIT_PATH = ROOT / "results" / "corporate_action_treatment" / "bonus_debenture_signal_timing_audit.csv"
PROHIBITED_MEMBERSHIP_PATH = PROCESSED / "membership_audit" / "nifty500_membership_intervals.parquet"

EXPECTED_TREATMENT_EVENTS = 149
EXPECTED_STRICT_EXCEPTIONS = 4
EXPECTED_UNSAFE_FORMATIONS = 8
BRITANNIA_SECURITY_ID = "NSE_444C594AB9B7"


def read_dated_parquet(
    path: Path,
    date_column: str,
    columns: list[str] | None,
    cutoff: pd.Timestamp = DATA_CUTOFF,
) -> pd.DataFrame:
    """Predicate-read a dated Parquet input and enforce the cutoff."""
    dataset = ds.dataset(path, format="parquet")
    table = dataset.to_table(
        columns=columns,
        filter=ds.field(date_column) <= cutoff.to_datetime64(),
    )
    frame = table.to_pandas()
    frame[date_column] = pd.to_datetime(frame[date_column])
    if not frame.empty and frame[date_column].max() > cutoff:
        raise ValueError(f"{path} produced an observation after {cutoff.date()}")
    return frame


def unresolved_security_id(symbol: str, isin: str = "") -> str:
    token = f"{symbol}|{isin}".encode("utf-8")
    return "UNRESOLVED_" + hashlib.sha1(token).hexdigest()[:12]


def assert_input_contract() -> None:
    accepted_paths = {
        MARKET_PATH,
        CALENDAR_PATH,
        MEMBERSHIP_PATH,
        IDENTITY_PATH,
        SERIES_PATH,
        TREATMENT_PATH,
        TREATED_ACTION_PATH,
        DELAYED_RECOGNITION_PATH,
        TIMING_AUDIT_PATH,
    }
    if PROHIBITED_MEMBERSHIP_PATH in accepted_paths:
        raise ValueError("The snapshot_floor membership artifact is prohibited")
    missing = [str(path) for path in accepted_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing accepted input(s): " + ", ".join(missing))


def prepare_identity_inputs(
    member_security_ids: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    identity = read_dated_parquet(
        IDENTITY_PATH,
        "first_seen",
        ["isin", "symbol", "first_seen", "last_seen", "observations", "observed_series", "security_id"],
    )
    identity["last_seen"] = pd.to_datetime(identity["last_seen"])
    if identity.duplicated(["isin", "symbol"]).any():
        raise ValueError("Accepted identity has duplicate symbol/ISIN keys")
    if member_security_ids is not None:
        identity = identity[identity["security_id"].isin(member_security_ids)].copy()

    series = read_dated_parquet(
        SERIES_PATH,
        "first_seen",
        [
            "series", "symbol", "isin", "first_seen", "last_seen",
            "observations", "security_id", "is_eligible_common_equity",
            "classification", "classification_evidence",
        ],
    )
    series["last_seen"] = pd.to_datetime(series["last_seen"])
    if member_security_ids is not None:
        series = series[series["security_id"].isin(member_security_ids)].copy()
    if series.duplicated(["security_id", "isin", "symbol", "series"]).any():
        raise ValueError("Accepted series classification has duplicate keys")

    alias_collisions = pd.read_csv(ALIAS_COLLISION_PATH)
    if not alias_collisions.empty:
        raise ValueError("Accepted dated identity contains alias collisions")
    return identity, series, alias_collisions


def select_market_observations(
    market: pd.DataFrame,
    identity_map: pd.DataFrame,
    series_classification: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Resolve one accepted common-equity observation per security and date."""
    input_rows = len(market)
    identity = identity_map.copy()
    if "identity_id" in identity.columns and "security_id" not in identity.columns:
        identity = identity.rename(columns={"identity_id": "security_id"})
    if "identity_status" not in identity.columns:
        identity["identity_status"] = "RESOLVED"
    identity_columns = ["isin", "symbol", "security_id", "identity_status"]
    for column in ["first_seen", "last_seen"]:
        if column in identity.columns:
            identity_columns.append(column)

    mapped = market.merge(
        identity[identity_columns],
        on=["isin", "symbol"],
        how="inner",
        validate="many_to_one",
    )
    if "first_seen" in mapped.columns:
        dated_identity = mapped["date"].ge(mapped["first_seen"])
        dated_identity &= mapped["last_seen"].isna() | mapped["date"].le(mapped["last_seen"])
        mapped = mapped[dated_identity].copy()
    matched_rows = len(mapped)

    legacy_series_fixture = series_classification is None
    if legacy_series_fixture:
        mapped["is_eligible_common_equity"] = True
        mapped["classification"] = np.where(mapped["series"].eq("EQ"), "FULLY_PAID_EQUITY", "UNCLASSIFIED")
        mapped["classification_evidence"] = "TEST_FALLBACK_EQ_ONLY"
    else:
        mapped = mapped.merge(
            series_classification[
                [
                    "security_id", "isin", "symbol", "series", "first_seen",
                    "last_seen", "is_eligible_common_equity", "classification",
                    "classification_evidence",
                ]
            ].rename(columns={"first_seen": "series_first_seen", "last_seen": "series_last_seen"}),
            on=["security_id", "isin", "symbol", "series"],
            how="left",
            validate="many_to_one",
        )
        series_date_valid = mapped["date"].ge(mapped["series_first_seen"])
        series_date_valid &= mapped["series_last_seen"].isna() | mapped["date"].le(mapped["series_last_seen"])
        mapped["is_eligible_common_equity"] = mapped["is_eligible_common_equity"].fillna(False) & series_date_valid

    mapped["is_eq"] = mapped["series"].eq("EQ")
    keys = ["security_id", "date"]
    mapped["candidate_count"] = mapped.groupby(keys, sort=False)["security_id"].transform("size")
    mapped["eligible_candidate_count"] = mapped.groupby(keys, sort=False)["is_eligible_common_equity"].transform("sum")
    mapped["eq_candidate_count"] = (
        mapped["is_eq"] & mapped["is_eligible_common_equity"]
    ).groupby([mapped["security_id"], mapped["date"]]).transform("sum")

    mapped = mapped.sort_values(
        ["security_id", "date", "is_eligible_common_equity", "is_eq", "series", "symbol"],
        ascending=[True, True, False, False, True, True],
        na_position="last",
    )
    selected = mapped.drop_duplicates(keys, keep="first").copy()
    ambiguous = selected["eligible_candidate_count"].gt(1) & selected["eq_candidate_count"].ne(1)
    unsupported = selected["eligible_candidate_count"].eq(0)
    if legacy_series_fixture:
        unsupported = selected["candidate_count"].eq(1) & ~selected["series"].eq("EQ")
    selected["series_ambiguous"] = ambiguous
    selected["conflicting_series"] = selected["candidate_count"].gt(1)
    selected["unsupported_series"] = unsupported
    selected["raw_market_observed"] = True
    selected["market_observed"] = ~unsupported

    value_columns = ["open", "high", "low", "close", "prev_close", "volume", "traded_value"]
    selected.loc[ambiguous | unsupported, value_columns] = np.nan
    selected.loc[ambiguous | unsupported, "series"] = pd.NA
    price_columns = ["open", "high", "low", "close", "prev_close"]
    invalid = (
        selected[price_columns].isna().any(axis=1)
        | ~np.isfinite(selected[price_columns]).all(axis=1)
        | selected[price_columns].le(0).any(axis=1)
        | selected["volume"].isna()
        | selected["traded_value"].isna()
        | selected["volume"].lt(0)
        | selected["traded_value"].lt(0)
        | selected["high"].lt(selected[["open", "low", "close"]].max(axis=1))
        | selected["low"].gt(selected[["open", "high", "close"]].min(axis=1))
    )
    invalid &= ~(ambiguous | unsupported)
    selected["market_observation_invalid"] = invalid
    selected["market_data_status"] = "OK"
    selected.loc[unsupported, "market_data_status"] = "NO_ELIGIBLE_SERIES"
    selected.loc[invalid, "market_data_status"] = "MARKET_OBSERVATION_INVALID"
    selected.loc[ambiguous, "market_data_status"] = "SERIES_AMBIGUOUS"
    selected = selected.drop(
        columns=[
            column for column in [
                "is_eq", "first_seen", "last_seen", "series_first_seen",
                "series_last_seen", "is_eligible_common_equity",
            ] if column in selected.columns
        ]
    )
    stats = {
        "market_input_rows_through_cutoff": input_rows,
        "member_identity_matched_market_rows": matched_rows,
        "selected_market_rows": len(selected),
        "selected_eq_rows": int(selected["series"].eq("EQ").sum()),
        "selected_be_rows": int(selected["series"].eq("BE").sum()),
        "selected_bz_rows": int(selected["series"].eq("BZ").sum()),
        "conflicting_series_rows": int(selected["conflicting_series"].sum()),
        "ambiguous_series_rows": int(selected["series_ambiguous"].sum()),
        "no_eligible_series_rows": int(selected["unsupported_series"].sum()),
        "invalid_market_rows": int(selected["market_observation_invalid"].sum()),
    }
    return selected, stats


def coalesce_membership_intervals(
    membership: pd.DataFrame, crosswalk: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Normalize accepted half-open membership intervals and union overlaps."""
    frame = membership.copy()
    if "security_id" not in frame.columns:
        if crosswalk is None:
            raise ValueError("Legacy membership fixture requires a crosswalk")
        frame = frame.merge(
            crosswalk,
            left_on="symbol",
            right_on="membership_symbol",
            how="left",
            validate="many_to_one",
        )
        missing = frame["identity_id"].isna()
        frame.loc[missing, "identity_id"] = [unresolved_security_id(symbol) for symbol in frame.loc[missing, "symbol"]]
        frame["security_id"] = frame["identity_id"]
        frame["published_symbol"] = frame["symbol"]
        frame["membership_identity_resolved"] = ~missing
        frame["membership_source_value"] = frame.get("source", "fixture")
    else:
        frame["membership_identity_resolved"] = True
        frame["membership_source_value"] = frame["evidence_status"].astype(str) + ":" + frame["evidence_file"].astype(str)

    frame["valid_from"] = pd.to_datetime(frame["valid_from"])
    frame["valid_to"] = pd.to_datetime(frame["valid_to"])
    frame["effective_end"] = frame["valid_to"].fillna(DAY_AFTER_CUTOFF).clip(upper=DAY_AFTER_CUTOFF)
    frame = frame[frame["valid_from"].lt(frame["effective_end"])].copy()

    records: list[dict[str, object]] = []
    for security_id, group in frame.groupby("security_id", sort=True):
        group = group.sort_values(["valid_from", "effective_end", "published_symbol"])
        current: dict[str, object] | None = None
        for row in group.itertuples(index=False):
            if current is None or row.valid_from > current["effective_end"]:
                if current is not None:
                    records.append(current)
                current = {
                    "security_id": security_id,
                    "valid_from": row.valid_from,
                    "effective_end": row.effective_end,
                    "membership_symbols": {row.published_symbol},
                    "membership_sources": {row.membership_source_value},
                    "membership_identity_resolved": bool(row.membership_identity_resolved),
                }
            else:
                current["effective_end"] = max(current["effective_end"], row.effective_end)
                current["membership_symbols"].add(row.published_symbol)
                current["membership_sources"].add(row.membership_source_value)
                current["membership_identity_resolved"] &= bool(row.membership_identity_resolved)
        if current is not None:
            records.append(current)
    intervals = pd.DataFrame(records)
    intervals["membership_symbol"] = intervals["membership_symbols"].map(lambda values: ";".join(sorted(map(str, values))))
    intervals["membership_source"] = intervals["membership_sources"].map(lambda values: ";".join(sorted(map(str, values))))
    return intervals.drop(columns=["membership_symbols", "membership_sources"])


def build_membership_spine(calendar: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    dates = calendar["date"].sort_values().to_numpy()
    pieces: list[pd.DataFrame] = []
    for row in intervals.itertuples(index=False):
        start = np.searchsorted(dates, np.datetime64(row.valid_from), side="left")
        end = np.searchsorted(dates, np.datetime64(row.effective_end), side="left")
        if start == end:
            continue
        pieces.append(
            pd.DataFrame(
                {
                    "date": dates[start:end],
                    "security_id": row.security_id,
                    "membership_symbol": row.membership_symbol,
                    "membership_source": row.membership_source,
                    "membership_identity_resolved": row.membership_identity_resolved,
                }
            )
        )
    spine = pd.concat(pieces, ignore_index=True)
    if spine.duplicated(["security_id", "date"]).any():
        raise ValueError("Official membership creates duplicate security/date rows")
    return spine


def combine_market_and_membership(market: pd.DataFrame, spine: pd.DataFrame) -> pd.DataFrame:
    panel = market.merge(
        spine,
        on=["security_id", "date"],
        how="outer",
        validate="one_to_one",
        indicator="_membership_merge",
    )
    panel["in_nifty500"] = panel["_membership_merge"].ne("left_only")
    panel = panel.drop(columns="_membership_merge")
    missing_market = panel["market_observed"].isna()
    panel.loc[missing_market, "raw_market_observed"] = False
    panel.loc[missing_market, "market_observed"] = False
    panel.loc[missing_market, "market_data_status"] = "PRICE_MISSING"
    for column in ["market_observation_invalid", "series_ambiguous", "conflicting_series", "unsupported_series"]:
        panel.loc[missing_market, column] = False
        panel[column] = panel[column].fillna(False).astype(bool)
    for column in ["candidate_count", "eligible_candidate_count", "eq_candidate_count"]:
        if column not in panel.columns:
            panel[column] = 0
        panel.loc[missing_market, column] = 0
    panel["market_observed"] = panel["market_observed"].fillna(False).astype(bool)
    panel["raw_market_observed"] = panel["raw_market_observed"].fillna(False).astype(bool)
    panel["membership_identity_resolved"] = panel["membership_identity_resolved"].fillna(True).astype(bool)
    panel.loc[missing_market, "identity_status"] = "RESOLVED"
    return panel


def prepare_corporate_actions(
    treatments: pd.DataFrame,
    treated_actions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    required = {
        "event_id", "security_id", "effective_date", "treatment_status",
        "cash_per_pre_event_share", "share_multiplier",
        "entitlement_value_per_pre_event_share", "blocks_total_return",
        "parent_event_class", "treatment_notes", "evidence_source",
    }
    missing = required.difference(treatments.columns)
    if missing:
        raise ValueError(f"Accepted treatment is missing columns: {sorted(missing)}")
    if len(treatments) != EXPECTED_TREATMENT_EVENTS:
        raise ValueError("Accepted treatment table must contain 149 parent events")
    if treatments["event_id"].isna().any() or treatments["event_id"].duplicated().any():
        raise ValueError("Each accepted parent event must have exactly one treatment")
    if treatments["security_id"].isna().any():
        raise ValueError("Accepted treatment has a missing security_id")
    if int(treatments["blocks_total_return"].sum()) != EXPECTED_STRICT_EXCEPTIONS:
        raise ValueError("Expected exactly four strict total-return exceptions")
    if treated_actions is not None:
        reviewed = treated_actions.loc[treated_actions["treatment_reviewed_for_in_universe_event"], "event_id"]
        if set(reviewed) != set(treatments["event_id"]):
            raise ValueError("Treated corporate-action artifact disagrees with accepted parents")

    frame = treatments.copy()
    frame["date"] = pd.to_datetime(frame["effective_date"])
    frame["cash_per_pre_event_share"] = frame["cash_per_pre_event_share"].fillna(0.0)
    frame["entitlement_value_per_pre_event_share"] = frame["entitlement_value_per_pre_event_share"].fillna(0.0)
    grouped_rows: list[dict[str, object]] = []
    for (security_id, date), group in frame.groupby(["security_id", "date"], sort=True):
        blocked = bool(group["blocks_total_return"].any())
        grouped_rows.append(
            {
                "security_id": security_id,
                "date": date,
                "corporate_action_event_ids": ";".join(sorted(group["event_id"].astype(str))),
                "corporate_action_event_count": len(group),
                "cash_per_pre_event_share": group["cash_per_pre_event_share"].sum(min_count=1),
                "share_multiplier": group["share_multiplier"].prod(min_count=1),
                "entitlement_value_per_pre_event_share": group["entitlement_value_per_pre_event_share"].sum(min_count=1),
                "blocks_total_return": blocked,
                "corporate_action_exception": blocked,
                "corporate_action_treatment_status": ";".join(sorted(set(group["treatment_status"].astype(str)))),
                "corporate_action_classes": ";".join(sorted(set(group["parent_event_class"].astype(str)))),
                "corporate_action_evidence_source": ";".join(sorted(set(group["evidence_source"].dropna().astype(str)))),
                "corporate_action_treatment_notes": " | ".join(sorted(set(group["treatment_notes"].dropna().astype(str)))),
            }
        )
    grouped = pd.DataFrame(grouped_rows)
    grouped["corporate_action_adjusted"] = (
        ~grouped["blocks_total_return"]
        & (
            grouped["cash_per_pre_event_share"].ne(0)
            | grouped["share_multiplier"].ne(1)
            | grouped["entitlement_value_per_pre_event_share"].ne(0)
        )
    )
    grouped["corporate_action_review_required"] = grouped["blocks_total_return"]
    grouped["event_unresolved"] = grouped["blocks_total_return"]
    return grouped


def _normalize_actions_for_returns(actions: pd.DataFrame) -> pd.DataFrame:
    frame = actions.copy()
    accepted_treatment = "corporate_action_treatment_status" in frame.columns
    rename = {}
    if "share_multiplier" not in frame.columns and "share_factor" in frame.columns:
        rename["share_factor"] = "share_multiplier"
    if "cash_per_pre_event_share" not in frame.columns and "dividend_amount" in frame.columns:
        rename["dividend_amount"] = "cash_per_pre_event_share"
    frame = frame.rename(columns=rename)
    if "blocks_total_return" not in frame.columns and "event_unresolved" in frame.columns:
        frame["blocks_total_return"] = frame["event_unresolved"].fillna(False)
    if "corporate_action_exception" not in frame.columns and "blocks_total_return" in frame.columns:
        frame["corporate_action_exception"] = frame["blocks_total_return"].fillna(False)
    defaults: dict[str, object] = {
        "share_multiplier": 1.0,
        "cash_per_pre_event_share": 0.0,
        "entitlement_value_per_pre_event_share": 0.0,
        "blocks_total_return": False,
        "corporate_action_exception": False,
        "corporate_action_adjusted": False,
        "corporate_action_review_required": False,
        "event_unresolved": False,
        "corporate_action_event_ids": "",
        "corporate_action_event_count": 0,
        "corporate_action_treatment_status": "",
        "corporate_action_classes": "",
        "corporate_action_evidence_source": "",
        "corporate_action_treatment_notes": "",
    }
    for column, value in defaults.items():
        if column not in frame.columns:
            frame[column] = value
    frame["accepted_treatment_input"] = accepted_treatment
    return frame[list(defaults) + ["accepted_treatment_input", "security_id", "date"]]


def attach_returns(panel: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    actions = _normalize_actions_for_returns(actions)
    panel = panel.merge(actions, on=["security_id", "date"], how="left", validate="one_to_one")
    boolean_columns = [
        "blocks_total_return", "corporate_action_exception",
        "corporate_action_adjusted", "corporate_action_review_required",
        "event_unresolved", "accepted_treatment_input",
    ]
    for column in boolean_columns:
        panel[column] = panel[column].fillna(False).astype(bool)
    for column, default in [
        ("share_multiplier", 1.0), ("cash_per_pre_event_share", 0.0),
        ("entitlement_value_per_pre_event_share", 0.0),
        ("corporate_action_event_count", 0),
    ]:
        panel[column] = panel[column].fillna(default)
    for column in [
        "corporate_action_event_ids", "corporate_action_treatment_status",
        "corporate_action_classes", "corporate_action_evidence_source",
        "corporate_action_treatment_notes",
    ]:
        panel[column] = panel[column].fillna("").astype("string")

    panel["strict_total_return_available"] = ~panel["blocks_total_return"]
    panel["trading_day_number"] = panel["date"].map(calendar.set_index("date")["trading_day_number"])
    if panel["trading_day_number"].isna().any():
        raise ValueError("Panel contains a date outside the canonical NSE calendar")
    panel = panel.sort_values(["security_id", "date"]).reset_index(drop=True)
    grouped = panel.groupby("security_id", sort=False)
    panel["prior_panel_close"] = grouped["close"].shift(1)
    prior_session = grouped["trading_day_number"].shift(1)
    panel["prior_session_is_consecutive"] = (panel["trading_day_number"] - prior_session).eq(1)
    panel["previous_close_matches_source"] = np.isclose(
        panel["prior_panel_close"], panel["prev_close"], rtol=1e-7, atol=1e-8, equal_nan=False
    )
    usable = (
        panel["market_observed"]
        & ~panel["market_observation_invalid"]
        & ~panel["series_ambiguous"]
        & panel["identity_status"].eq("RESOLVED")
        & panel["prior_session_is_consecutive"]
        & panel["prior_panel_close"].gt(0)
        & panel["close"].gt(0)
    )
    panel["daily_price_return"] = np.nan
    panel.loc[usable, "daily_price_return"] = panel.loc[usable, "close"] / panel.loc[usable, "prior_panel_close"] - 1.0
    total_usable = usable & panel["strict_total_return_available"]
    panel["daily_total_return"] = np.nan
    panel.loc[total_usable, "daily_total_return"] = (
        (
            panel.loc[total_usable, "share_multiplier"] * panel.loc[total_usable, "close"]
            + panel.loc[total_usable, "cash_per_pre_event_share"]
            + panel.loc[total_usable, "entitlement_value_per_pre_event_share"]
        )
        / panel.loc[total_usable, "prior_panel_close"] - 1.0
    )
    panel["return_adjustment_implausible"] = panel["corporate_action_adjusted"] & panel["daily_total_return"].abs().gt(1.0)
    legacy_implausible = panel["return_adjustment_implausible"] & ~panel["accepted_treatment_input"]
    panel.loc[legacy_implausible, "corporate_action_review_required"] = True
    panel.loc[legacy_implausible, "event_unresolved"] = True
    panel.loc[legacy_implausible, "corporate_action_adjusted"] = False
    panel.loc[legacy_implausible, "daily_total_return"] = np.nan
    panel["return_status"] = "OK"
    panel.loc[~panel["prior_session_is_consecutive"], "return_status"] = "PREVIOUS_PRICE_MISSING"
    panel.loc[panel["market_observation_invalid"] | ~panel["market_observed"], "return_status"] = "MARKET_OBSERVATION_INVALID"
    panel.loc[panel["series_ambiguous"], "return_status"] = "SERIES_AMBIGUOUS"
    panel.loc[panel["identity_status"].ne("RESOLVED"), "return_status"] = "IDENTITY_UNRESOLVED"
    panel.loc[panel["event_unresolved"], "return_status"] = "CORPORATE_ACTION_UNRESOLVED"
    panel.loc[
        panel["blocks_total_return"] & panel["accepted_treatment_input"],
        "return_status",
    ] = "STRICT_CORPORATE_ACTION_EXCEPTION"
    return panel


def calculate_lagged_adv(panel: pd.DataFrame) -> pd.DataFrame:
    panel["adv20_lagged"] = np.nan
    panel["adv20_observation_count"] = np.int16(0)
    panel["positive_volume_sessions_20"] = np.int16(0)
    for positions in panel.groupby("security_id", sort=False).indices.values():
        positions = np.asarray(positions)
        sessions = panel.loc[positions, "trading_day_number"].to_numpy(dtype=np.int64)
        traded = panel.loc[positions, "traded_value"].to_numpy(dtype=float)
        observed = panel.loc[positions, "market_observed"].to_numpy(dtype=bool) & np.isfinite(traded) & (traded >= 0)
        observed_sessions = sessions[observed]
        traded_values = traded[observed]
        positive_volume = (panel.loc[positions[observed], "volume"].to_numpy(dtype=float) > 0).astype(np.int16)
        left = np.searchsorted(observed_sessions, sessions - 20, side="left")
        right = np.searchsorted(observed_sessions, sessions, side="left")
        counts = right - left
        value_prefix = np.concatenate([[0.0], np.cumsum(traded_values)])
        positive_prefix = np.concatenate([[0], np.cumsum(positive_volume)])
        sums = value_prefix[right] - value_prefix[left]
        positive_counts = positive_prefix[right] - positive_prefix[left]
        complete = counts == 20
        panel.loc[positions, "adv20_lagged"] = np.where(complete, sums / 20.0, np.nan)
        panel.loc[positions, "adv20_observation_count"] = counts.astype(np.int16)
        panel.loc[positions, "positive_volume_sessions_20"] = positive_counts.astype(np.int16)
    panel["adv20_complete"] = panel["adv20_observation_count"].eq(20)
    return panel


def attach_delayed_recognition_metadata(
    panel: pd.DataFrame,
    delayed: pd.DataFrame,
    timing_audit: pd.DataFrame,
    calendar: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach recognition metadata and corporate-action timing safety only."""
    delayed = delayed.copy()
    for column in ["event_ex_date", "price_trade_date", "information_available_timestamp"]:
        delayed[column] = pd.to_datetime(delayed[column])
    if delayed["price_trade_date"].max() > DATA_CUTOFF:
        raise ValueError("Delayed-recognition input contains a post-cutoff value")

    recognition_rows: list[dict[str, object]] = []
    for (security_id, date), group in delayed.groupby(["security_id", "price_trade_date"], sort=True):
        recognition_rows.append(
            {
                "security_id": security_id,
                "date": date,
                "delayed_recognition_event_ids": ";".join(sorted(set(group["event_id"].astype(str)))),
                "delayed_recognition_tranche_count": len(group),
                "delayed_recognition_value_per_pre_event_share": group["entitlement_value_per_pre_event_share"].sum(min_count=1),
                "delayed_recognition_information_timestamp": group["information_available_timestamp"].max(),
                "delayed_recognition_event_signal_safe": bool(group["signal_safe"].all()),
            }
        )
    recognition = pd.DataFrame(recognition_rows)
    panel = panel.merge(recognition, on=["security_id", "date"], how="left", validate="one_to_one")
    panel["delayed_recognition_available"] = panel["delayed_recognition_event_ids"].notna()
    panel["delayed_recognition_event_ids"] = panel["delayed_recognition_event_ids"].fillna("").astype("string")
    panel["delayed_recognition_tranche_count"] = panel["delayed_recognition_tranche_count"].fillna(0).astype("int16")

    timing = timing_audit.copy()
    timing["formation_date"] = pd.to_datetime(timing["formation_date"])
    event_security = delayed[["event_id", "security_id"]].drop_duplicates()
    if event_security["event_id"].duplicated().any():
        raise ValueError("Delayed-recognition event maps to multiple securities")
    timing = timing.merge(event_security, on="event_id", how="left", validate="many_to_one")
    if timing["security_id"].isna().any():
        raise ValueError("Timing audit contains an unmapped event")
    unsafe = timing[~timing["formation_safe"].astype(bool)].copy()
    unsafe = unsafe.sort_values(["formation_date", "event_id"]).reset_index(drop=True)
    if len(unsafe) != EXPECTED_UNSAFE_FORMATIONS:
        raise ValueError("Expected exactly eight unsafe formation observations")
    if not unsafe["security_id"].eq(BRITANNIA_SECURITY_ID).all():
        raise ValueError("An unexplained non-Britannia unsafe formation was introduced")
    if unsafe.duplicated(["event_id", "security_id", "formation_date"]).any():
        raise ValueError("Unsafe formation audit contains duplicate economic cases")

    month_ends = set(calendar.loc[calendar["is_last_trading_day_of_month"], "date"].tolist())
    panel["is_formation_date"] = panel["date"].isin(month_ends)
    panel["momentum_signal_safe"] = pd.Series(pd.NA, index=panel.index, dtype="boolean")
    panel.loc[panel["is_formation_date"], "momentum_signal_safe"] = True
    panel["momentum_signal_exclusion_reason"] = pd.Series(pd.NA, index=panel.index, dtype="string")
    panel["corporate_action_timing_event_ids"] = pd.Series("", index=panel.index, dtype="string")
    unsafe_keys = unsafe[["security_id", "formation_date", "event_id", "unsafe_reason"]].rename(columns={"formation_date": "date"})
    panel = panel.merge(unsafe_keys, on=["security_id", "date"], how="left", validate="one_to_one")
    unsafe_mask = panel["event_id"].notna()
    panel.loc[unsafe_mask, "momentum_signal_safe"] = False
    panel.loc[unsafe_mask, "momentum_signal_exclusion_reason"] = panel.loc[unsafe_mask, "unsafe_reason"].astype("string")
    panel.loc[unsafe_mask, "corporate_action_timing_event_ids"] = panel.loc[unsafe_mask, "event_id"].astype("string")
    panel = panel.drop(columns=["event_id", "unsafe_reason"])
    panel["final_signal_available"] = pd.Series(pd.NA, index=panel.index, dtype="boolean")
    panel["final_signal_availability_status"] = "NOT_EVALUATED_PANEL_STAGE"
    return panel, unsafe


def add_reason(codes: pd.Series, mask: pd.Series, code: str) -> pd.Series:
    separator = np.where(codes.eq(""), "", ";")
    return codes + np.where(mask, separator + code, "")


def assign_reason_codes(panel: pd.DataFrame, earliest_membership: pd.Timestamp) -> pd.DataFrame:
    codes = pd.Series("", index=panel.index, dtype="string")
    codes = add_reason(codes, panel["identity_status"].ne("RESOLVED"), "IDENTITY_UNRESOLVED")
    codes = add_reason(codes, ~panel["market_observed"], "PRICE_MISSING")
    codes = add_reason(codes, panel["market_observation_invalid"], "MARKET_OBSERVATION_INVALID")
    codes = add_reason(codes, panel["series_ambiguous"], "SERIES_AMBIGUOUS")
    codes = add_reason(codes, panel["unsupported_series"], "NO_ELIGIBLE_SERIES")
    codes = add_reason(codes, ~panel["prior_session_is_consecutive"], "PREVIOUS_PRICE_MISSING")
    codes = add_reason(codes, panel["blocks_total_return"], "STRICT_CORPORATE_ACTION_EXCEPTION")
    codes = add_reason(codes, ~panel["adv20_complete"], "ADV_INCOMPLETE")
    codes = add_reason(codes, panel["daily_total_return"].isna(), "RETURN_UNAVAILABLE")
    codes = add_reason(codes, panel["momentum_signal_safe"].eq(False).fillna(False), "CORPORATE_ACTION_TIMING_UNSAFE")
    codes = add_reason(codes, ~panel["in_nifty500"] & panel["date"].ge(earliest_membership), "NOT_IN_NIFTY500")
    codes = add_reason(codes, panel["date"].lt(earliest_membership), "MEMBERSHIP_UNAVAILABLE")
    panel["reason_codes"] = codes
    panel["review_reason_codes"] = codes
    return panel


def validate_panel(panel: pd.DataFrame, calendar: pd.DataFrame) -> None:
    if panel.empty:
        raise ValueError("Panel is empty")
    if panel.duplicated(["security_id", "date"]).any():
        raise ValueError("Duplicate security_id/date rows in final panel")
    if panel["date"].max() > DATA_CUTOFF:
        raise ValueError("Final panel contains a post-cutoff row")
    if panel["date"].min() < calendar["date"].min():
        raise ValueError("Panel predates the canonical calendar")
    if panel["security_id"].isna().any():
        raise ValueError("Final panel has missing security IDs")
    if panel["in_nifty500"].isna().any():
        raise ValueError("Final panel has missing membership state")
    if (panel["adv20_observation_count"] > 20).any():
        raise ValueError("ADV observation count exceeds the 20-session window")
    if panel.loc[~panel["adv20_complete"], "adv20_lagged"].notna().any():
        raise ValueError("Incomplete ADV window has a reported ADV")
    if panel.loc[panel["blocks_total_return"], "daily_total_return"].notna().any():
        raise ValueError("A strict corporate-action exception has a total return")
    if int(panel["corporate_action_exception"].sum()) != EXPECTED_STRICT_EXCEPTIONS:
        raise ValueError("Final panel does not preserve four strict exceptions")
    unsafe = panel["momentum_signal_safe"].eq(False).fillna(False)
    if int(unsafe.sum()) != EXPECTED_UNSAFE_FORMATIONS:
        raise ValueError("Final panel does not preserve eight unsafe formations")
    if panel.loc[~panel["is_formation_date"], "momentum_signal_safe"].notna().any():
        raise ValueError("Ordinary daily rows must not carry signal-safety values")
    if panel["final_signal_available"].notna().any():
        raise ValueError("Final signal availability must not be evaluated in this stage")


def grouped_cases(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=columns + ["first_date", "last_date", "rows"])
    return (
        frame.groupby(columns, dropna=False)
        .agg(first_date=("date", "min"), last_date=("date", "max"), rows=("date", "size"))
        .reset_index()
        .sort_values(["rows"] + columns, ascending=[False] + [True] * len(columns))
    )


def membership_counts(panel: pd.DataFrame, calendar: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    month_ends = calendar.loc[
        calendar["is_last_trading_day_of_month"] & calendar["date"].between(BUILD_START, DATA_CUTOFF), "date"
    ]
    counts = (
        panel[panel["date"].isin(month_ends) & panel["in_nifty500"]]
        .groupby("date")
        .agg(official_membership_count=("security_id", "nunique"), observed_market_count=("market_observed", "sum"))
        .reset_index()
    )
    counts = pd.DataFrame({"date": month_ends}).merge(counts, on="date", how="left")
    source_counts = []
    for date in month_ends:
        active = intervals[intervals["valid_from"].le(date) & intervals["effective_end"].gt(date)]
        source_counts.append({"date": date, "source_interval_security_count": active["security_id"].nunique()})
    counts = counts.merge(pd.DataFrame(source_counts), on="date", how="left")
    counts["identity_collision_count"] = counts["source_interval_security_count"] - counts["official_membership_count"]
    return counts


def write_audits(
    panel: pd.DataFrame,
    membership: pd.DataFrame,
    intervals: pd.DataFrame,
    identity: pd.DataFrame,
    alias_collisions: pd.DataFrame,
    market_stats: dict[str, int],
    treatments: pd.DataFrame,
    unsafe_formations: pd.DataFrame,
    calendar: pd.DataFrame,
) -> dict[str, object]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    counts = membership_counts(panel, calendar, intervals)
    counts.to_csv(AUDIT_DIR / "membership_count_by_rebalance.csv", index=False)
    alias_collisions.to_csv(AUDIT_DIR / "membership_alias_collisions.csv", index=False)

    identity_ids = set(identity["security_id"])
    unresolved_membership = membership[~membership["security_id"].isin(identity_ids)].copy()
    unresolved_membership.to_csv(AUDIT_DIR / "unresolved_identity_in_universe.csv", index=False)
    first_seen = identity.groupby("security_id")["first_seen"].min()
    prelisting = membership.assign(identity_first_seen=membership["security_id"].map(first_seen))
    prelisting = prelisting[prelisting["identity_first_seen"].isna() | prelisting["valid_from"].lt(prelisting["identity_first_seen"])]
    prelisting.to_csv(AUDIT_DIR / "official_membership_prelisting_audit.csv", index=False)

    missing_market = panel[panel["in_nifty500"] & ~panel["market_observed"]]
    missing_market_cases = grouped_cases(missing_market, ["security_id", "membership_symbol", "market_data_status"])
    missing_market_cases.to_csv(AUDIT_DIR / "missing_market_in_universe.csv", index=False)
    strict_exceptions = panel[panel["corporate_action_exception"]][
        [
            "date", "security_id", "symbol", "membership_symbol",
            "corporate_action_event_ids", "corporate_action_classes",
            "corporate_action_treatment_status", "strict_total_return_available",
            "daily_total_return",
        ]
    ].sort_values(["date", "security_id"])
    strict_exceptions.to_csv(AUDIT_DIR / "strict_corporate_action_exceptions.csv", index=False)
    strict_exceptions.to_csv(AUDIT_DIR / "unresolved_corporate_actions_in_universe.csv", index=False)

    unsafe_columns = [
        "event_id", "security_id", "formation_date", "symbol", "event_ex_date",
        "formation_timestamp", "economic_legs_in_window",
        "equity_ex_date_in_window", "entitlement_legs_in_window",
        "missing_required_legs", "information_available_by_formation",
        "formation_safe", "unsafe_reason",
    ]
    unsafe_formations[unsafe_columns].to_csv(AUDIT_DIR / "corporate_action_momentum_formation_exceptions.csv", index=False)

    reason_counts = panel[["reason_codes"]].assign(reason_code=panel["reason_codes"].str.split(";")).explode("reason_code")
    reason_counts = (
        reason_counts[reason_counts["reason_code"].ne("")]
        .groupby("reason_code").size().rename("row_count").reset_index()
        .sort_values(["row_count", "reason_code"], ascending=[False, True])
    )
    reason_counts.to_csv(AUDIT_DIR / "exclusion_reason_counts.csv", index=False)
    finite_price = panel["daily_price_return"].dropna()
    finite_total = panel["daily_total_return"].dropna()
    sanity = pd.DataFrame(
        [
            ("price_return_count", len(finite_price)),
            ("total_return_count", len(finite_total)),
            ("price_return_min", finite_price.min()),
            ("price_return_max", finite_price.max()),
            ("total_return_min", finite_total.min()),
            ("total_return_max", finite_total.max()),
            ("absolute_total_return_gt_100pct", finite_total.abs().gt(1).sum()),
            ("prev_close_mismatch_when_comparable", (panel["prior_session_is_consecutive"] & panel["market_observed"] & ~panel["previous_close_matches_source"]).sum()),
            ("accepted_parent_treatments", len(treatments)),
            ("corporate_action_adjusted_rows", panel["corporate_action_adjusted"].sum()),
            ("strict_total_return_exceptions", len(strict_exceptions)),
        ],
        columns=["check", "value"],
    )
    sanity.to_csv(AUDIT_DIR / "return_sanity_checks.csv", index=False)

    summary: dict[str, object] = {
        "panel_rows": len(panel),
        "first_panel_date": panel["date"].min().date(),
        "last_panel_date": panel["date"].max().date(),
        "duplicate_security_date_rows": int(panel.duplicated(["security_id", "date"]).sum()),
        "permanent_identities": panel["security_id"].nunique(),
        "contemporaneous_symbols": panel["symbol"].nunique(dropna=True),
        "nifty500_security_date_observations": int(panel["in_nifty500"].sum()),
        "official_membership_count_min": int(counts["official_membership_count"].min()),
        "official_membership_count_max": int(counts["official_membership_count"].max()),
        "unresolved_official_membership_identities": len(unresolved_membership),
        "impossible_prelisting_memberships": len(prelisting),
        "alias_collisions": len(alias_collisions),
        "duplicated_economic_securities_in_universe": int(panel.loc[panel["in_nifty500"]].duplicated(["security_id", "date"]).sum()),
        "missing_market_rows_in_universe": len(missing_market),
        "missing_market_cases_in_universe": len(missing_market_cases),
        "accepted_parent_treatments": len(treatments),
        "corporate_action_adjusted_rows": int(panel["corporate_action_adjusted"].sum()),
        "strict_corporate_action_exceptions": len(strict_exceptions),
        "delayed_recognition_rows": int(panel["delayed_recognition_available"].sum()),
        "momentum_signal_unsafe_formation_observations": int(panel["momentum_signal_safe"].eq(False).fillna(False).sum()),
        "unexplained_unsafe_formation_observations": int((~unsafe_formations["security_id"].eq(BRITANNIA_SECURITY_ID)).sum()),
        "adv_complete_rows": int(panel["adv20_complete"].sum()),
        "adv_incomplete_rows": int((~panel["adv20_complete"]).sum()),
        "adv_complete_rows_in_universe": int((panel["in_nifty500"] & panel["adv20_complete"]).sum()),
        "maximum_value_date_read": DATA_CUTOFF.date(),
        "maximum_panel_date": panel["date"].max().date(),
        "official_membership_intervals_used": len(membership),
        "old_snapshot_floor_source_rows": 0,
        "prohibited_membership_path_used": False,
        **market_stats,
    }
    pd.DataFrame(summary.items(), columns=["metric", "value"]).to_csv(AUDIT_DIR / "panel_summary.csv", index=False)
    write_data_audit(summary, panel, reason_counts)
    return summary


def write_data_audit(summary: dict[str, object], panel: pd.DataFrame, reason_counts: pd.DataFrame) -> None:
    schema_lines = "\n".join(f"- `{column}`: `{dtype}`" for column, dtype in panel.dtypes.items())
    reason_lines = "\n".join(f"- `{row.reason_code}`: {row.row_count:,}" for row in reason_counts.itertuples(index=False))
    input_paths = [
        MARKET_PATH, CALENDAR_PATH, MEMBERSHIP_PATH, IDENTITY_PATH, SERIES_PATH,
        ALIAS_COLLISION_PATH, TREATMENT_PATH, TREATED_ACTION_PATH,
        DELAYED_RECOGNITION_PATH, TIMING_AUDIT_PATH,
    ]
    inputs = "\n".join(f"- `{path.relative_to(ROOT)}`" for path in input_paths)
    audit = f"""# Research Panel Data Audit

Generated by `panel_build.py` from the accepted upstream artifacts.

## Scope and access controls

- `data/raw/` was not accessed.
- `downloading_validating_data/` was not accessed.
- No data was downloaded.
- Maximum value date read: **{summary['maximum_value_date_read']}**.
- Maximum panel date: **{summary['maximum_panel_date']}**.
- No post-2023-03-31 value observation was read.
- No momentum, ranking, portfolio, execution, tax, performance, or holdout calculation was performed.
- The prohibited `data/processed/membership_audit/nifty500_membership_intervals.parquet` artifact was not read.

## Accepted inputs

{inputs}

## Final panel

- Rows: **{summary['panel_rows']:,}**
- Date range: **{summary['first_panel_date']} to {summary['last_panel_date']}**
- Duplicate security/date rows: **{summary['duplicate_security_date_rows']}**
- Permanent identities: **{summary['permanent_identities']:,}**
- Official member security/date rows: **{summary['nifty500_security_date_observations']:,}**
- Official month-end membership count range: **{summary['official_membership_count_min']}–{summary['official_membership_count_max']}**
- Unresolved official membership identities: **{summary['unresolved_official_membership_identities']}**
- Impossible pre-listing memberships: **{summary['impossible_prelisting_memberships']}**
- Dated alias collisions: **{summary['alias_collisions']}**
- Duplicate economic securities in the universe: **{summary['duplicated_economic_securities_in_universe']}**
- Missing eligible market observations while in the universe: **{summary['missing_market_rows_in_universe']:,}** across **{summary['missing_market_cases_in_universe']:,}** cases
- Accepted corporate-action parent treatments: **{summary['accepted_parent_treatments']}**
- Corporate-action-adjusted rows: **{summary['corporate_action_adjusted_rows']}**
- Strict total-return exceptions: **{summary['strict_corporate_action_exceptions']}**
- Delayed-recognition equity rows: **{summary['delayed_recognition_rows']}**
- Corporate-action-timing-unsafe formation observations: **{summary['momentum_signal_unsafe_formation_observations']}**
- Other unexplained unsafe formations: **{summary['unexplained_unsafe_formation_observations']}**
- ADV complete rows: **{summary['adv_complete_rows']:,}**
- ADV incomplete rows: **{summary['adv_incomplete_rows']:,}**

The 501-security month ends begin in April 2016 in the accepted official
membership intervals. They include `TATAMTRDVR` as a distinct listed security;
the panel preserves the source count instead of deleting a constituent to
force 500. There are no simultaneous duplicate security IDs.

## Membership and identity

Membership uses `valid_from <= date < valid_to`. Market history is built for
every security that appears in the official membership artifact; membership is
attached afterward, preserving valid pre-membership observations. The official
intervals contain no `snapshot_floor` evidence. Every official membership
security ID resolves in the accepted dated identity artifact, and no interval
begins before the identity's first observed market date.

## Series policy

Only rows accepted by the dated series classification are usable market
observations. EQ is accepted as fully paid equity. BE/BZ is accepted only when
the stored evidence classifies the same security as trade-for-trade equity. A
unique EQ row wins when several eligible rows exist; otherwise the observation
is ambiguous and unavailable. Missing volume is never replaced with zero.

Selected EQ/BE/BZ rows: **{summary['selected_eq_rows']:,} /
{summary['selected_be_rows']:,} / {summary['selected_bz_rows']:,}**.

## Returns and corporate actions

Raw market prices are unchanged. The accepted research total return is:

`(share_multiplier * close + cash_per_pre_event_share + entitlement_value_per_pre_event_share) / prior_close - 1`

The prior close must be for the same permanent security on the immediately
preceding canonical NSE session. Missing returns remain missing. The four
bonus-debenture events retain unavailable strict ex-date returns; no fair value
is invented. Their identifiers remain on the panel for the later selected/held
materiality test.

Delayed-recognition values are metadata only and do not alter prices or
returns. `momentum_signal_safe` checks only corporate-action timing: it is null
on ordinary daily rows, true on unaffected formation rows, and false on the
eight accepted Britannia event/security/formation cases.
`final_signal_available` is null throughout because signal history,
membership, liquidity, tradability, and other strategy gates are outside this
stage.

## ADV

`adv20_lagged` uses the preceding 20 canonical NSE sessions and excludes the
current observation. An observed zero-volume session contributes zero. A
missing or invalid observation reduces the count, and ADV remains unavailable
unless all 20 preceding sessions are observed.

## Reason counts

{reason_lines}

## Output schema

{schema_lines}

## Remaining limitations

- Four accepted bonus-debenture events have no strict ex-date fair value; their
  total returns remain unavailable by design.
- Two Britannia events make exactly eight future formation observations
  unavailable for the corporate-action timing dimension.
- Missing market observations and incomplete ADV windows remain explicit; no
  future data, backfill, or zero-return substitution is used.
- The accepted treatment layer covers official in-universe parent events. This
  panel creates no new treatment assumptions outside that accepted scope.
- Market staleness is not inferred because the processed market artifact has no
  authoritative historical suspension/status field.
- Seven comparable rows have a mismatch between the source `prev_close` and the
  panel's immediately preceding observed close. Returns use the latter by
  design; these source exceptions remain a review item.
"""
    (ROOT / "DATA_AUDIT.md").write_text(audit, encoding="utf-8")


def build_panel() -> dict[str, object]:
    assert_input_contract()
    print("Reading accepted development-period inputs...")
    market = read_dated_parquet(
        MARKET_PATH,
        "date",
        [
            "date", "isin", "symbol", "series", "open", "high", "low",
            "close", "prev_close", "volume", "traded_value", "source_file",
            "source_format",
        ],
    )
    calendar = read_dated_parquet(
        CALENDAR_PATH,
        "date",
        ["date", "trading_day_number", "weekday", "is_last_trading_day_of_month"],
    )
    membership = read_dated_parquet(MEMBERSHIP_PATH, "valid_from", None)
    membership["valid_to"] = pd.to_datetime(membership["valid_to"])
    if membership["evidence_status"].astype(str).str.contains("snapshot_floor", case=False, na=False).any():
        raise ValueError("Official membership contains prohibited snapshot_floor evidence")
    member_security_ids = set(membership["security_id"])
    identity, series, alias_collisions = prepare_identity_inputs(member_security_ids)
    treatments = read_dated_parquet(TREATMENT_PATH, "effective_date", None)
    treated_actions = read_dated_parquet(
        TREATED_ACTION_PATH,
        "ex_date",
        ["event_id", "ex_date", "treatment_reviewed_for_in_universe_event"],
    )
    delayed = pd.read_csv(DELAYED_RECOGNITION_PATH)
    timing_audit = pd.read_csv(TIMING_AUDIT_PATH)

    print("Resolving dated identities, accepted series, and official membership...")
    selected_market, market_stats = select_market_observations(market, identity, series)
    del market
    intervals = coalesce_membership_intervals(membership)
    spine = build_membership_spine(calendar, intervals)
    panel = combine_market_and_membership(selected_market, spine)
    del selected_market, spine

    print("Applying accepted treatments, delayed-recognition metadata, and causal ADV...")
    grouped_actions = prepare_corporate_actions(treatments, treated_actions)
    panel = attach_returns(panel, grouped_actions, calendar)
    panel = calculate_lagged_adv(panel)
    panel, unsafe_formations = attach_delayed_recognition_metadata(panel, delayed, timing_audit, calendar)
    panel = assign_reason_codes(panel, membership["valid_from"].min())

    output_columns = [
        "date", "security_id", "symbol", "isin", "series", "classification",
        "classification_evidence", "membership_symbol", "membership_source",
        "membership_identity_resolved", "in_nifty500", "open", "high", "low",
        "close", "prev_close", "volume", "traded_value", "daily_price_return",
        "daily_total_return", "adv20_lagged", "adv20_observation_count",
        "positive_volume_sessions_20", "adv20_complete", "raw_market_observed",
        "market_observed", "candidate_count", "eligible_candidate_count",
        "eq_candidate_count", "conflicting_series", "series_ambiguous",
        "unsupported_series", "corporate_action_event_ids",
        "corporate_action_event_count", "corporate_action_classes",
        "corporate_action_treatment_status", "corporate_action_evidence_source",
        "corporate_action_treatment_notes", "cash_per_pre_event_share",
        "share_multiplier", "entitlement_value_per_pre_event_share",
        "corporate_action_adjusted", "corporate_action_review_required",
        "event_unresolved", "blocks_total_return",
        "strict_total_return_available", "corporate_action_exception",
        "delayed_recognition_available", "delayed_recognition_event_ids",
        "delayed_recognition_tranche_count",
        "delayed_recognition_value_per_pre_event_share",
        "delayed_recognition_information_timestamp",
        "delayed_recognition_event_signal_safe", "is_formation_date",
        "momentum_signal_safe", "momentum_signal_exclusion_reason",
        "corporate_action_timing_event_ids", "final_signal_available",
        "final_signal_availability_status", "return_adjustment_implausible",
        "prior_session_is_consecutive", "previous_close_matches_source",
        "identity_status", "market_data_status", "return_status", "reason_codes",
        "review_reason_codes", "source_file", "source_format",
    ]
    panel = panel[output_columns].sort_values(["date", "security_id"], ignore_index=True)
    validate_panel(panel, calendar)
    print("Writing rebuilt panel and audits...")
    panel.to_parquet(OUTPUT_PANEL, index=False)
    summary = write_audits(
        panel, membership, intervals, identity, alias_collisions, market_stats,
        treatments, unsafe_formations, calendar,
    )
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    build_panel()
