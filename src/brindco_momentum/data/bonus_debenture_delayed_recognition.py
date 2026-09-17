"""Build the delayed-recognition overlay for four bonus-debenture events.

The accepted corporate-action treatments remain unchanged.  This stage uses
only official exchange trades to determine when each entitlement first became
observable, then tests every monthly 12-to-2 window for partial-event timing.
It does not construct an equity return or rebuild the research panel.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds


from brindco_momentum.paths import ROOT
TREATMENTS = (
    ROOT
    / "data"
    / "processed"
    / "corporate_action_treatment"
    / "in_universe_event_treatments.parquet"
)
MARKET_DATA = ROOT / "data" / "processed" / "nse_cm_2013_2026.parquet"
TRADING_CALENDAR = (
    ROOT / "data" / "processed" / "nse_trading_calendar_2013_2026.parquet"
)
DELAYED_RECOGNITION_OUTPUT = (
    ROOT
    / "data"
    / "processed"
    / "corporate_action_treatment"
    / "bonus_debenture_delayed_recognition.csv"
)
TIMING_AUDIT_OUTPUT = (
    ROOT
    / "results"
    / "corporate_action_treatment"
    / "bonus_debenture_signal_timing_audit.csv"
)

DATA_CUTOFF = pd.Timestamp("2023-03-31")
FIRST_DECISION_MONTH = pd.Period("2014-08", freq="M")
LAST_DECISION_MONTH = pd.Period("2023-03", freq="M")
TIMEZONE = "Asia/Kolkata"

# Exact accepted file at the start of this task.  The script refuses to run if
# the input differs and verifies the same byte hash again after writing outputs.
ACCEPTED_TREATMENT_SHA256 = (
    "5ddea240585838652401277a3b8b3e417d21b2919c9e6a8906cb3ea328c858cf"
)

NSE_DIRTY_PRICE_CONVENTION_SOURCE = (
    "https://nsearchives.nseindia.com/content/yield_example.pdf"
)
BSE_DIRTY_PRICE_CONVENTION_SOURCE = (
    "https://www.bseindia.com/downloads1/Clean_Price_Booklet.pdf"
)


EVENTS = {
    "CA_faa277a19bfa2ac115cc": {
        "symbol": "BLUEDART",
        "security_id": "NSE_1789CF98709C",
        "event_ex_date": "2014-11-17",
        "terms_known_by_date": "2014-11-26",
        "identity_known_by_date": "2014-11-26",
        "terms_evidence_source": (
            "https://nsearchives.nseindia.com/content/press/26112014.htm"
        ),
        "tranches": [
            {
                "tranche_id": "SERIES_I",
                "isin": "INE233B08087",
                "quantity": 7.0,
                "face_value": 10.0,
                "nse_series": "N1",
            },
            {
                "tranche_id": "SERIES_II",
                "isin": "INE233B08095",
                "quantity": 4.0,
                "face_value": 10.0,
                "nse_series": "N2",
            },
            {
                "tranche_id": "SERIES_III",
                "isin": "INE233B08103",
                "quantity": 3.0,
                "face_value": 10.0,
                "nse_series": "N3",
            },
        ],
    },
    "CA_df82d8fc43ad7e21c2a8": {
        "symbol": "NTPC",
        "security_id": "NSE_4FB8019524D0",
        "event_ex_date": "2015-03-20",
        "terms_known_by_date": "2015-03-26",
        "identity_known_by_date": "2015-03-27",
        "terms_evidence_source": (
            "https://dea.gov.in/files/press_release_documents/"
            "NTPC_issue_Bonus_Debentures26032015.pdf;"
            "https://nsearchives.nseindia.com/content/press/27032015.htm"
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "isin": "INE733E07JP6",
                "quantity": 1.0,
                "face_value": 12.5,
                "nse_series": "N7",
            }
        ],
    },
    "CA_52dafdfb28d9f35d7326": {
        "symbol": "BRITANNIA",
        "security_id": "NSE_444C594AB9B7",
        "event_ex_date": "2019-08-22",
        "terms_known_by_date": "2019-08-28",
        "identity_known_by_date": "2019-10-07",
        "terms_evidence_source": (
            "https://nsearchives.nseindia.com/corporate/"
            "BRITANNIA_28082019165059_OUTCOMEBONUSDEBENTURECOMMITTEEALLOTMENT_260.pdf;"
            "https://archives.nseindia.com/corporate/"
            "BRITANNIA_08102019164515_IntimationofTradingApprovalsforBonusDebentures_018.pdf"
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "isin": "INE216A07052",
                "quantity": 1.0,
                "face_value": 30.0,
                "nse_series": "N2",
            }
        ],
    },
    "CA_9d29c825ee80b650567a": {
        "symbol": "BRITANNIA",
        "security_id": "NSE_444C594AB9B7",
        "event_ex_date": "2021-05-25",
        "terms_known_by_date": "2021-06-03",
        "identity_known_by_date": "2021-07-19",
        "terms_evidence_source": (
            "https://archives.nseindia.com/corporate/"
            "BRITANNIA_03062021131616_OUTCOMEOFBDC03062021.pdf;"
            "https://archives.nseindia.com/corporate/"
            "BRITANNIA_19072021194130_IntimationtoSEforBonusDebentures.pdf"
        ),
        "tranches": [
            {
                "tranche_id": "BONUS_DEBENTURE",
                "isin": "INE216A08027",
                "quantity": 1.0,
                "face_value": 29.0,
                "nse_series": "N3",
            }
        ],
    },
}


# Target rows transcribed from the named official BSE daily bhavcopies.  The
# source file hashes make the evidence independently reproducible.  NSE rows
# are read from the accepted processed NSE bhavcopy dataset at run time.
BSE_FIRST_TRADE_CANDIDATES = [
    {
        "isin": "INE233B08087",
        "date": "2014-11-28",
        "symbol": "BLUENCDSR1",
        "series": "F/D",
        "open": 11.00,
        "high": 11.00,
        "low": 11.00,
        "close": 11.00,
        "last": 11.00,
        "volume": 633,
        "traded_value": 6963.00,
        "num_trades": 4,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ281114_CSV.ZIP"
        ),
        "source_sha256": (
            "bbd0d2e08d5723fa678307189041923f2dc4239be141f8dfabf4492390703b59"
        ),
    },
    {
        "isin": "INE233B08095",
        "date": "2014-11-28",
        "symbol": "BLUENCDSR2",
        "series": "F/D",
        "open": 11.00,
        "high": 11.00,
        "low": 11.00,
        "close": 11.00,
        "last": 11.00,
        "volume": 576,
        "traded_value": 6336.00,
        "num_trades": 4,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ281114_CSV.ZIP"
        ),
        "source_sha256": (
            "bbd0d2e08d5723fa678307189041923f2dc4239be141f8dfabf4492390703b59"
        ),
    },
    {
        "isin": "INE233B08103",
        "date": "2014-11-28",
        "symbol": "BLUENCDSR3",
        "series": "F/D",
        "open": 11.00,
        "high": 11.00,
        "low": 11.00,
        "close": 11.00,
        "last": 11.00,
        "volume": 500,
        "traded_value": 5500.00,
        "num_trades": 4,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ281114_CSV.ZIP"
        ),
        "source_sha256": (
            "bbd0d2e08d5723fa678307189041923f2dc4239be141f8dfabf4492390703b59"
        ),
    },
    {
        "isin": "INE733E07JP6",
        "date": "2015-03-30",
        "symbol": "849NTPC25",
        "series": "F/D",
        "open": 12.52,
        "high": 12.75,
        "low": 12.52,
        "close": 12.71,
        "last": 12.72,
        "volume": 61_368_722,
        "traded_value": 777_867_864.00,
        "num_trades": 544,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ300315_CSV.ZIP"
        ),
        "source_sha256": (
            "7029bf1dcc8de80fca582209b7aad29f15144841505bd23f8220b3605aff5d46"
        ),
    },
    {
        "isin": "INE216A07052",
        "date": "2019-10-09",
        "symbol": "BILNCD",
        "series": "F/D",
        "open": 31.00,
        "high": 31.00,
        "low": 30.60,
        "close": 30.83,
        "last": 30.82,
        "volume": 2_754_172,
        "traded_value": 84_828_335.00,
        "num_trades": 54,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ091019_CSV.ZIP"
        ),
        "source_sha256": (
            "f49b371c1a093870bf87c1992308f08bfa79f520bdee6aa4955c4fd68b73c641"
        ),
    },
    {
        "isin": "INE216A08027",
        "date": "2021-07-20",
        "symbol": "BILNCD2021",
        "series": "F/D",
        "open": 29.22,
        "high": 29.50,
        "low": 28.60,
        "close": 29.37,
        "last": 29.37,
        "volume": 54_043,
        "traded_value": 1_578_502.00,
        "num_trades": 252,
        "source_url": (
            "https://www.bseindia.com/download/BhavCopy/Equity/"
            "EQ200721_CSV.ZIP"
        ),
        "source_sha256": (
            "2d218d028ccee31aed93e04d200bb72cfeb160049a275bc56fe6dd231dbc19d1"
        ),
    },
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def after_close_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    """Conservatively make an undated official close usable next calendar day."""

    date = pd.Timestamp(value).normalize()
    return (date + pd.Timedelta(days=1)).tz_localize(TIMEZONE)


def _actual_trade_mask(frame: pd.DataFrame) -> pd.Series:
    numeric = ["open", "high", "low", "close", "volume", "traded_value", "num_trades"]
    finite = np.isfinite(frame[numeric]).all(axis=1)
    within_range = frame["close"].between(frame["low"], frame["high"])
    average_price = frame["traded_value"] / frame["volume"]
    average_within_range = average_price.between(frame["low"] - 0.01, frame["high"] + 0.01)
    return (
        finite
        & frame["volume"].gt(0)
        & frame["traded_value"].gt(0)
        & frame["num_trades"].gt(0)
        & within_range
        & average_within_range
    )


def load_nse_first_trade_candidates() -> pd.DataFrame:
    isins = [
        tranche["isin"]
        for event in EVENTS.values()
        for tranche in event["tranches"]
    ]
    columns = [
        "date",
        "isin",
        "symbol",
        "series",
        "open",
        "high",
        "low",
        "close",
        "last",
        "volume",
        "traded_value",
        "num_trades",
        "source_file",
    ]
    market = ds.dataset(MARKET_DATA, format="parquet")
    cutoff = pa.scalar(DATA_CUTOFF.to_pydatetime())
    table = market.to_table(
        columns=columns,
        filter=ds.field("isin").isin(isins) & (ds.field("date") <= cutoff),
    )
    frame = table.to_pandas()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame[_actual_trade_mask(frame)].copy()
    frame = frame.sort_values(["isin", "date"], kind="stable")
    frame = frame.groupby("isin", as_index=False, sort=False).first()
    if set(frame["isin"]) != set(isins):
        missing = sorted(set(isins) - set(frame["isin"]))
        raise ValueError(f"No qualifying NSE trade for ISINs: {missing}")

    frame["venue"] = "NSE"
    frame["source_url"] = frame.apply(
        lambda row: (
            "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
            f"{row['date'].year}/{row['date'].strftime('%b').upper()}/"
            f"{row['source_file']}"
        ),
        axis=1,
    )
    frame["source_sha256"] = ""
    return frame


def build_trade_candidates() -> pd.DataFrame:
    nse = load_nse_first_trade_candidates()
    bse = pd.DataFrame(BSE_FIRST_TRADE_CANDIDATES)
    bse["date"] = pd.to_datetime(bse["date"])
    bse["source_file"] = bse["source_url"].str.rsplit("/", n=1).str[-1]
    bse["venue"] = "BSE"
    if not _actual_trade_mask(bse).all():
        raise ValueError("At least one preserved BSE candidate is not an actual trade")

    candidates = pd.concat([nse, bse], ignore_index=True, sort=False)
    candidates["average_trade_price"] = (
        candidates["traded_value"] / candidates["volume"]
    )
    candidates = candidates.sort_values(
        ["isin", "date", "traded_value", "venue"],
        ascending=[True, True, False, True],
        kind="stable",
    )
    candidates["selected"] = False
    selected_index = candidates.groupby("isin", sort=False).head(1).index
    candidates.loc[selected_index, "selected"] = True
    return candidates.reset_index(drop=True)


def _candidate_json(group: pd.DataFrame) -> str:
    records = []
    for row in group.sort_values(
        ["date", "traded_value", "venue"],
        ascending=[True, False, True],
        kind="stable",
    ).itertuples():
        records.append(
            {
                "venue": row.venue,
                "trade_date": row.date.strftime("%Y-%m-%d"),
                "close": float(row.close),
                "volume": int(row.volume),
                "traded_value": float(row.traded_value),
                "num_trades": int(row.num_trades),
                "source_url": row.source_url,
                "source_sha256": row.source_sha256,
                "selected": bool(row.selected),
            }
        )
    return json.dumps(records, separators=(",", ":"))


def build_delayed_recognition(
    treatments: pd.DataFrame, candidates: pd.DataFrame
) -> pd.DataFrame:
    if len(treatments) != 149 or not treatments["event_id"].is_unique:
        raise ValueError("Accepted treatment artifact must contain 149 unique event IDs")
    indexed_treatments = treatments.set_index("event_id")
    selected = candidates[candidates["selected"]].set_index("isin")
    candidate_groups = {isin: group for isin, group in candidates.groupby("isin")}

    rows = []
    for event_id, event in EVENTS.items():
        if event_id not in indexed_treatments.index:
            raise ValueError(f"Accepted treatment event is missing: {event_id}")
        parent = indexed_treatments.loc[event_id]
        if parent["security_id"] != event["security_id"]:
            raise ValueError(f"Security ID mismatch for {event_id}")
        if pd.Timestamp(parent["effective_date"]) != pd.Timestamp(event["event_ex_date"]):
            raise ValueError(f"Ex-date mismatch for {event_id}")

        for tranche in event["tranches"]:
            price = selected.loc[tranche["isin"]]
            price_trade_date = pd.Timestamp(price["date"])
            if price_trade_date <= pd.Timestamp(event["event_ex_date"]):
                raise ValueError(f"Observable value must follow the ex-date: {event_id}")

            information_available_timestamp = max(
                after_close_timestamp(event["terms_known_by_date"]),
                after_close_timestamp(event["identity_known_by_date"]),
                after_close_timestamp(price_trade_date),
            )
            value_per_share = tranche["quantity"] * float(price["close"])
            rows.append(
                {
                    "event_id": event_id,
                    "security_id": event["security_id"],
                    "symbol": event["symbol"],
                    "event_ex_date": event["event_ex_date"],
                    "event_holding_month": pd.Timestamp(event["event_ex_date"]).strftime("%Y-%m"),
                    "tranche_id": tranche["tranche_id"],
                    "entitlement_security": tranche["isin"],
                    "quantity_per_pre_event_share": tranche["quantity"],
                    "face_value_per_entitlement": tranche["face_value"],
                    "terms_known_by_date": event["terms_known_by_date"],
                    "identity_known_by_date": event["identity_known_by_date"],
                    "price_trade_date": price_trade_date.strftime("%Y-%m-%d"),
                    "entitlement_valuation_date": price_trade_date.strftime("%Y-%m-%d"),
                    "valuation_holding_month": price_trade_date.strftime("%Y-%m"),
                    "selected_venue": price["venue"],
                    "selected_symbol": price["symbol"],
                    "selected_series": price["series"],
                    "observable_value_per_entitlement": float(price["close"]),
                    "quantity_traded": int(price["volume"]),
                    "traded_value": float(price["traded_value"]),
                    "number_of_trades": int(price["num_trades"]),
                    "actual_official_trade": True,
                    "quote_face_value_basis": tranche["face_value"],
                    "quote_unit_basis": "INR_DIRTY_PRICE_PER_DEBENTURE",
                    "clean_or_dirty_price": "DIRTY",
                    "accrued_interest_treatment": (
                        "INCLUDED_IN_NSE_OR_BSE_CAPITAL_MARKET_TRADE_PRICE;"
                        "NO_SEPARATE_ADDITION"
                    ),
                    "price_normalization_method": (
                        "DIRECT_EXCHANGE_CLOSE_PER_DEBENTURE_NO_SCALING"
                    ),
                    "entitlement_value_per_pre_event_share": value_per_share,
                    "information_available_date": information_available_timestamp.strftime("%Y-%m-%d"),
                    "information_available_timestamp": information_available_timestamp.isoformat(),
                    "price_availability_method": (
                        "CONSERVATIVE_NEXT_CALENDAR_DAY_00_00_IST_AFTER_OFFICIAL_CLOSE"
                    ),
                    "price_candidate_count": len(candidate_groups[tranche["isin"]]),
                    "price_candidates_json": _candidate_json(
                        candidate_groups[tranche["isin"]]
                    ),
                    "selection_reason": (
                        "Earliest qualifying official trade date; highest traded value "
                        "on that date; venue name as final deterministic tie-break."
                    ),
                    "price_evidence_source": price["source_url"],
                    "price_evidence_sha256": price["source_sha256"],
                    "terms_evidence_source": event["terms_evidence_source"],
                    "quote_convention_evidence_source": (
                        BSE_DIRTY_PRICE_CONVENTION_SOURCE
                        if price["venue"] == "BSE"
                        else NSE_DIRTY_PRICE_CONVENTION_SOURCE
                    ),
                    "strict_ex_date_value_observable": False,
                    "treatment_notes": (
                        "Mandatory entitlement recognized only at its first selected "
                        "official traded close. No value is assigned to the equity ex-date."
                    ),
                }
            )

    delayed = pd.DataFrame(rows)
    totals = (
        delayed.groupby("event_id")["entitlement_value_per_pre_event_share"]
        .sum()
        .rename("event_entitlement_value_per_pre_event_share")
    )
    delayed = delayed.merge(totals, on="event_id", validate="many_to_one")
    return delayed.sort_values(["event_ex_date", "tranche_id"], kind="stable")


def build_formation_schedule(calendar: pd.DataFrame) -> pd.DataFrame:
    calendar = calendar[pd.to_datetime(calendar["date"]).le(DATA_CUTOFF)].copy()
    calendar["date"] = pd.to_datetime(calendar["date"])
    month_ends = calendar[calendar["is_last_trading_day_of_month"]].copy()
    month_ends["holding_month"] = month_ends["date"].dt.to_period("M")
    formation_dates = month_ends.set_index("holding_month")["date"]

    rows = []
    for decision_month in pd.period_range(
        FIRST_DECISION_MONTH, LAST_DECISION_MONTH, freq="M"
    ):
        preceding_month = decision_month - 1
        if preceding_month not in formation_dates.index:
            raise ValueError(f"No canonical month-end session for {preceding_month}")
        formation_date = formation_dates.loc[preceding_month]
        rows.append(
            {
                "decision_month": decision_month,
                "formation_date": formation_date,
                "formation_timestamp": after_close_timestamp(formation_date),
                "window_start_month": decision_month - 12,
                "window_end_month": decision_month - 2,
            }
        )
    return pd.DataFrame(rows)


def build_timing_audit(
    delayed: pd.DataFrame, formations: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    rows = []
    first_affected = {}
    event_safe = {}

    for event_id, tranches in delayed.groupby("event_id", sort=False):
        event_month = pd.Period(tranches["event_holding_month"].iloc[0], freq="M")
        tranche_months = {
            row.tranche_id: pd.Period(row.valuation_holding_month, freq="M")
            for row in tranches.itertuples()
        }
        information_timestamps = pd.to_datetime(
            tranches["information_available_timestamp"], utc=True
        ).dt.tz_convert(TIMEZONE)
        max_information_timestamp = information_timestamps.max()

        event_rows = []
        for formation in formations.itertuples():
            window_start = formation.window_start_month
            window_end = formation.window_end_month
            ex_date_in_window = window_start <= event_month <= window_end
            tranche_membership = {
                tranche_id: window_start <= month <= window_end
                for tranche_id, month in tranche_months.items()
            }
            flags = [ex_date_in_window, *tranche_membership.values()]
            if not any(flags):
                continue

            all_or_none = all(flag == flags[0] for flag in flags)
            all_legs_in_window = all(flags)
            information_available = (
                max_information_timestamp <= formation.formation_timestamp
            )
            formation_safe = all_or_none and (
                not all_legs_in_window or information_available
            )
            reasons = []
            if not all_or_none:
                reasons.append("PARTIAL_ECONOMIC_EVENT_IN_WINDOW")
            if all_legs_in_window and not information_available:
                reasons.append("INFORMATION_UNAVAILABLE_AT_FORMATION")

            missing_legs = []
            if not ex_date_in_window:
                missing_legs.append("EQUITY_EX_DATE")
            missing_legs.extend(
                tranche_id
                for tranche_id, in_window in tranche_membership.items()
                if not in_window
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "symbol": tranches["symbol"].iloc[0],
                    "event_ex_date": tranches["event_ex_date"].iloc[0],
                    "decision_month": str(formation.decision_month),
                    "formation_date": formation.formation_date.strftime("%Y-%m-%d"),
                    "formation_timestamp": formation.formation_timestamp.isoformat(),
                    "window_start_month": str(window_start),
                    "window_end_month": str(window_end),
                    "required_entitlement_leg_count": len(tranche_membership),
                    "required_economic_leg_count": 1 + len(tranche_membership),
                    "economic_legs_in_window": sum(flags),
                    "equity_ex_date_in_window": ex_date_in_window,
                    "entitlement_legs_in_window": "|".join(
                        f"{key}={str(value).lower()}"
                        for key, value in tranche_membership.items()
                    ),
                    "missing_required_legs": "|".join(missing_legs),
                    "all_legs_or_none_in_window": all_or_none,
                    "latest_information_available_timestamp": (
                        max_information_timestamp.isoformat()
                    ),
                    "information_available_by_formation": information_available,
                    "formation_safe": formation_safe,
                    "unsafe_reason": "|".join(reasons),
                }
            )

        if not event_rows:
            raise ValueError(f"No affected formations found for {event_id}")
        event_frame = pd.DataFrame(event_rows)
        affected = event_frame[event_frame["equity_ex_date_in_window"]]
        first_affected[event_id] = affected.iloc[0]["formation_date"]
        event_safe[event_id] = bool(event_frame["formation_safe"].all())
        rows.extend(event_rows)

    timing = pd.DataFrame(rows)
    timing["first_affected_formation_date"] = timing["event_id"].map(first_affected)
    timing["event_signal_safe"] = timing["event_id"].map(event_safe)
    research_gate = len(event_safe) == 4 and all(event_safe.values())
    timing["research_feature_gate"] = "PASS" if research_gate else "FAIL"

    delayed = delayed.copy()
    delayed["first_affected_formation_date"] = delayed["event_id"].map(first_affected)
    delayed["signal_safe"] = delayed["event_id"].map(event_safe)
    delayed["research_feature_gate"] = "PASS" if research_gate else "FAIL"
    return delayed, timing, research_gate


def validate_results(
    delayed: pd.DataFrame, timing: pd.DataFrame, artifact_hash_before: str
) -> None:
    expected_isins = {
        tranche["isin"]
        for event in EVENTS.values()
        for tranche in event["tranches"]
    }
    if len(delayed) != 6 or set(delayed["entitlement_security"]) != expected_isins:
        raise ValueError("Delayed-recognition output must contain all six tranches")
    if delayed.duplicated(["event_id", "tranche_id"]).any():
        raise ValueError("Duplicate event/tranche rows")
    if not delayed["actual_official_trade"].all():
        raise ValueError("Every selected value must be an actual official trade")
    if delayed["observable_value_per_entitlement"].isna().any():
        raise ValueError("Every entitlement requires an observable value")
    if timing.duplicated(["event_id", "formation_date"]).any():
        raise ValueError("Duplicate event/formation audit rows")
    if not timing.groupby("event_id")["equity_ex_date_in_window"].any().all():
        raise ValueError("Each event requires at least one affected formation")

    artifact_hash_after = file_sha256(TREATMENTS)
    if artifact_hash_before != artifact_hash_after:
        raise ValueError("Accepted treatment artifact changed during the task")


def run() -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    artifact_hash_before = file_sha256(TREATMENTS)
    if artifact_hash_before != ACCEPTED_TREATMENT_SHA256:
        raise ValueError(
            "Accepted treatment artifact does not match its approved pre-task hash"
        )

    treatments = pd.read_parquet(TREATMENTS)
    candidates = build_trade_candidates()
    delayed = build_delayed_recognition(treatments, candidates)
    calendar = pd.read_parquet(
        TRADING_CALENDAR,
        columns=["date", "is_last_trading_day_of_month"],
        filters=[("date", "<=", DATA_CUTOFF)],
    )
    formations = build_formation_schedule(calendar)
    delayed, timing, research_gate = build_timing_audit(delayed, formations)

    DELAYED_RECOGNITION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TIMING_AUDIT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    delayed.to_csv(DELAYED_RECOGNITION_OUTPUT, index=False)
    timing.to_csv(TIMING_AUDIT_OUTPUT, index=False)
    validate_results(delayed, timing, artifact_hash_before)

    summary = (
        delayed.groupby(
            ["event_id", "symbol", "event_ex_date", "first_affected_formation_date"],
            as_index=False,
        )
        .agg(
            first_observable_valuation_date=("entitlement_valuation_date", "min"),
            entitlement_value_per_pre_event_share=(
                "event_entitlement_value_per_pre_event_share",
                "first",
            ),
            signal_safe=("signal_safe", "first"),
        )
    )
    print(summary.to_string(index=False))
    print(f"RESEARCH_FEATURE_CORPORATE_ACTION_GATE={'PASS' if research_gate else 'FAIL'}")
    print(f"accepted_treatment_sha256={artifact_hash_before}")
    print("accepted_treatment_artifact_unchanged=true")
    return delayed, timing, research_gate


if __name__ == "__main__":
    run()
