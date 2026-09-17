from __future__ import annotations

from pathlib import Path
from brindco_momentum.paths import ROOT
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

MEMBERSHIP_CSV = ROOT / Path("data/raw/membership/index_membership_history.csv"
)

OUTPUT_DIR = ROOT / Path("data/processed/membership_audit"
)

INDEX_NAME = "Nifty 500"

# Project-relevant period.
PROJECT_START = pd.Timestamp("2015-04-01")
PROJECT_END = pd.Timestamp("2026-03-31")

# We care especially about the less reliable early period.
EARLY_AUDIT_END = pd.Timestamp("2017-12-31")

# NIFTY 500 should ordinarily be near 500 names, but temporary
# deviations can exist around corporate actions/rebalances.
# These thresholds are for FLAGGING, not automatically declaring
# the data wrong.
COUNT_WARNING_LOW = 485
COUNT_WARNING_HIGH = 515


# ============================================================
# LOAD + BASIC CLEANING
# ============================================================

def load_membership() -> pd.DataFrame:

    if not MEMBERSHIP_CSV.exists():
        raise FileNotFoundError(
            f"Could not find:\n{MEMBERSHIP_CSV.resolve()}"
        )

    df = pd.read_csv(
        MEMBERSHIP_CSV,
        dtype={
            "index_id": "string",
            "index_name": "string",
            "symbol": "string",
            "source": "string",
            "source_url": "string",
            "notes": "string",
        },
    )

    required = {
        "index_id",
        "index_name",
        "symbol",
        "valid_from",
        "valid_to",
        "source",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Membership CSV is missing required columns: "
            f"{sorted(missing)}"
        )

    # Normalize strings.
    for col in [
        "index_name",
        "symbol",
        "source",
        "source_url",
        "notes",
    ]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype("string")
                .str.strip()
            )

    # Dates.
    df["valid_from"] = pd.to_datetime(
        df["valid_from"],
        errors="raise",
    )

    df["valid_to"] = pd.to_datetime(
        df["valid_to"],
        errors="coerce",
    )

    return df


# ============================================================
# MEMBERSHIP LOOKUP
# ============================================================

def members_on(
    df: pd.DataFrame,
    on_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Half-open membership interval:
        valid_from <= date < valid_to

    Blank valid_to means still active.
    """

    mask = (
        (df["valid_from"] <= on_date)
        &
        (
            df["valid_to"].isna()
            |
            (df["valid_to"] > on_date)
        )
    )

    return df.loc[mask].copy()


# ============================================================
# VALIDATION
# ============================================================

def validate_intervals(df: pd.DataFrame) -> None:

    print("\n=== INTERVAL CHECKS ===")

    # valid_to must be strictly after valid_from.
    invalid = df[
        df["valid_to"].notna()
        &
        (df["valid_to"] <= df["valid_from"])
    ]

    print(
        "Invalid/non-positive intervals:",
        len(invalid)
    )

    if not invalid.empty:
        invalid.to_csv(
            OUTPUT_DIR / "invalid_intervals.csv",
            index=False,
        )

    # Exact duplicate interval rows.
    dupes = df.duplicated(
        subset=[
            "index_name",
            "symbol",
            "valid_from",
            "valid_to",
        ],
        keep=False,
    )

    duplicate_rows = df.loc[dupes]

    print(
        "Duplicate interval rows:",
        len(duplicate_rows),
    )

    if not duplicate_rows.empty:
        duplicate_rows.to_csv(
            OUTPUT_DIR / "duplicate_intervals.csv",
            index=False,
        )

    # Overlapping intervals for same symbol/index.
    overlaps = []

    for (
        index_name,
        symbol,
    ), group in df.groupby(
        ["index_name", "symbol"],
        sort=False,
    ):

        g = group.sort_values("valid_from")

        previous_end = None
        previous_row = None

        for _, row in g.iterrows():

            start = row["valid_from"]
            end = row["valid_to"]

            if previous_end is None:
                # Previous open interval would overlap everything
                # after it.
                if previous_row is not None:
                    overlaps.append({
                        "index_name": index_name,
                        "symbol": symbol,
                        "previous_valid_from":
                            previous_row["valid_from"],
                        "previous_valid_to":
                            previous_row["valid_to"],
                        "current_valid_from": start,
                        "current_valid_to": end,
                    })

            elif previous_row is not None:
                if start < previous_end:
                    overlaps.append({
                        "index_name": index_name,
                        "symbol": symbol,
                        "previous_valid_from":
                            previous_row["valid_from"],
                        "previous_valid_to":
                            previous_row["valid_to"],
                        "current_valid_from": start,
                        "current_valid_to": end,
                    })

            previous_row = row
            previous_end = end

    overlaps_df = pd.DataFrame(overlaps)

    print(
        "Overlapping symbol intervals:",
        len(overlaps_df),
    )

    if not overlaps_df.empty:
        overlaps_df.to_csv(
            OUTPUT_DIR / "overlapping_intervals.csv",
            index=False,
        )


# ============================================================
# MONTH-END MEMBERSHIP COUNTS
# ============================================================

def build_month_end_counts(
    nifty500: pd.DataFrame,
) -> pd.DataFrame:

    # Calendar month-end is fine for membership auditing because
    # membership intervals are effective-date based.
    month_ends = pd.date_range(
        PROJECT_START,
        PROJECT_END,
        freq="ME",
    )

    rows = []

    for d in month_ends:

        members = members_on(
            nifty500,
            d,
        )

        unique_symbols = members["symbol"].nunique()

        rows.append({
            "date": d,
            "member_rows": len(members),
            "unique_symbols": unique_symbols,
            "warning":
                (
                    unique_symbols < COUNT_WARNING_LOW
                    or
                    unique_symbols > COUNT_WARNING_HIGH
                ),
        })

    result = pd.DataFrame(rows)

    result.to_csv(
        OUTPUT_DIR / "nifty500_month_end_counts.csv",
        index=False,
    )

    return result


# ============================================================
# EARLY-PERIOD / LOW-CONFIDENCE AUDIT
# ============================================================

def build_early_audit(
    nifty500: pd.DataFrame,
) -> pd.DataFrame:

    # Any interval touching the 2015-2017 period.
    touches_early_period = (
        (nifty500["valid_from"] <= EARLY_AUDIT_END)
        &
        (
            nifty500["valid_to"].isna()
            |
            (nifty500["valid_to"] >= PROJECT_START)
        )
    )

    early = nifty500.loc[
        touches_early_period
    ].copy()

    source_lower = (
        early["source"]
        .fillna("")
        .str.lower()
    )

    notes_lower = (
        early["notes"]
        .fillna("")
        .str.lower()
        if "notes" in early.columns
        else pd.Series(
            "",
            index=early.index,
        )
    )

    # Heuristic flags:
    #
    # "press_release" is direct event evidence.
    # "snapshot_floor" is reconstructed from a snapshot boundary
    # and therefore deserves extra scrutiny for early history.
    #
    # Also flag anything explicitly described as inferred.
    early["needs_manual_audit"] = (
        ~source_lower.eq("press_release")
        |
        notes_lower.str.contains(
            "infer|snapshot|manual|override|uncertain",
            regex=True,
        )
        |
        early["source_url"].fillna("").eq("")
    )

    early = early.sort_values(
        [
            "needs_manual_audit",
            "valid_from",
            "symbol",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    )

    early.to_csv(
        OUTPUT_DIR / "early_2015_2017_intervals.csv",
        index=False,
    )

    return early


# ============================================================
# OFFICIAL SOURCES TO VERIFY
# ============================================================

def build_source_checklist(
    early: pd.DataFrame,
) -> pd.DataFrame:

    cols = [
        "symbol",
        "valid_from",
        "valid_to",
        "source",
        "source_url",
        "notes",
        "needs_manual_audit",
    ]

    cols = [
        c
        for c in cols
        if c in early.columns
    ]

    checklist = early.loc[
        early["needs_manual_audit"],
        cols,
    ].copy()

    # Pull referenced circular filenames out of notes where a
    # source URL is not directly attached.
    if "notes" in checklist.columns:

        checklist["referenced_document"] = (
            checklist["notes"]
            .fillna("")
            .str.extract(
                r"(ind_prs[^,\s]+\.pdf)",
                expand=False,
            )
        )

    checklist.to_csv(
        OUTPUT_DIR /
        "official_documents_to_verify.csv",
        index=False,
    )

    return checklist


# ============================================================
# SOURCE SUMMARY
# ============================================================

def print_source_summary(
    nifty500: pd.DataFrame,
) -> None:

    print("\n=== SOURCE TYPES ===")

    print(
        nifty500["source"]
        .fillna("<missing>")
        .value_counts(dropna=False)
        .to_string()
    )


# ============================================================
# COVERAGE
# ============================================================

def print_coverage(
    nifty500: pd.DataFrame,
) -> None:

    print("\n=== NIFTY 500 COVERAGE ===")

    print(
        "Earliest valid_from:",
        nifty500["valid_from"].min().date(),
    )

    finite_end = nifty500[
        "valid_to"
    ].dropna()

    if not finite_end.empty:
        print(
            "Latest finite valid_to:",
            finite_end.max().date(),
        )

    print(
        "Open/current intervals:",
        int(nifty500["valid_to"].isna().sum()),
    )

    print(
        "Distinct symbols:",
        nifty500["symbol"].nunique(),
    )

    print(
        "Total intervals:",
        len(nifty500),
    )


# ============================================================
# OPTIONAL PRICE-SYMBOL CROSS-CHECK
# ============================================================

def cross_check_against_prices(
    nifty500: pd.DataFrame,
) -> None:
    """
    Optional diagnostic against your finished price parquet.

    IMPORTANT:
    The repository canonicalizes some historical ticker names,
    so a symbol mismatch is NOT automatically a missing security.

    This report is meant to identify names requiring identity/
    rename reconciliation.
    """

    price_path = ROOT / Path("data/processed/nse_cm_2013_2026.parquet"
    )

    if not price_path.exists():
        print(
            "\nPrice parquet not found; "
            "skipping symbol cross-check."
        )
        return

    print(
        "\n=== PRICE / MEMBERSHIP SYMBOL CROSS-CHECK ==="
    )

    prices = pd.read_parquet(
        price_path,
        columns=[
            "date",
            "symbol",
            "series",
            "isin",
        ],
    )

    prices["date"] = pd.to_datetime(
        prices["date"]
    )

    # Keep ordinary EQ series for this diagnostic.
    prices = prices[
        prices["series"].eq("EQ")
    ].copy()

    # Sample project dates rather than doing every daily join.
    audit_dates = pd.to_datetime([
        "2015-04-30",
        "2016-03-31",
        "2017-03-31",
        "2018-03-28",
        "2020-03-31",
        "2022-03-31",
        "2023-03-31",
        "2024-03-28",
        "2025-03-31",
        "2026-03-31",
    ])

    mismatch_rows = []

    for d in audit_dates:

        membership = members_on(
            nifty500,
            d,
        )

        # Use exact date if it exists, otherwise most recent
        # observed trading date on/before d.
        available = prices.loc[
            prices["date"] <= d,
            "date",
        ]

        if available.empty:
            continue

        px_date = available.max()

        symbols_present = set(
            prices.loc[
                prices["date"].eq(px_date),
                "symbol",
            ].dropna()
        )

        for symbol in sorted(
            set(membership["symbol"]) - symbols_present
        ):
            mismatch_rows.append({
                "membership_date": d,
                "price_date_used": px_date,
                "symbol": symbol,
            })

    mismatches = pd.DataFrame(
        mismatch_rows
    )

    print(
        "Potential symbol/identity mismatches:",
        len(mismatches),
    )

    if not mismatches.empty:
        mismatches.to_csv(
            OUTPUT_DIR /
            "membership_price_symbol_mismatches.csv",
            index=False,
        )

        print(
            "These are NOT automatically errors. "
            "Historical renames/canonicalized symbols "
            "are expected and must be resolved via "
            "ISIN/security identity history."
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    df = load_membership()

    print("Loaded rows:", len(df))
    print("Columns:")
    print(list(df.columns))

    # ----------------------------------------------
    # Global structural validation
    # ----------------------------------------------

    validate_intervals(df)

    # ----------------------------------------------
    # NIFTY 500 only
    # ----------------------------------------------

    nifty500 = df[
        df["index_name"].eq(INDEX_NAME)
    ].copy()

    if nifty500.empty:
        raise RuntimeError(
            f"No rows found for index_name={INDEX_NAME!r}. "
            f"Available names include:\n"
            f"{sorted(df['index_name'].dropna().unique())}"
        )

    print_coverage(nifty500)
    print_source_summary(nifty500)

    # Save clean filtered table.
    nifty500.to_parquet(
        OUTPUT_DIR /
        "nifty500_membership_intervals.parquet",
        index=False,
    )

    # ----------------------------------------------
    # Month-end counts
    # ----------------------------------------------

    counts = build_month_end_counts(
        nifty500
    )

    warnings = counts[
        counts["warning"]
    ]

    print("\n=== MONTH-END COUNT SUMMARY ===")

    print(
        counts[
            "unique_symbols"
        ].describe().to_string()
    )

    print(
        "\nFlagged month-ends outside "
        f"{COUNT_WARNING_LOW}-{COUNT_WARNING_HIGH}:",
        len(warnings),
    )

    if not warnings.empty:
        print(
            warnings[
                [
                    "date",
                    "unique_symbols",
                ]
            ].to_string(
                index=False
            )
        )

    # ----------------------------------------------
    # Early period
    # ----------------------------------------------

    early = build_early_audit(
        nifty500
    )

    checklist = build_source_checklist(
        early
    )

    print("\n=== EARLY 2015-2017 AUDIT ===")

    print(
        "Intervals touching early period:",
        len(early),
    )

    print(
        "Intervals flagged for manual review:",
        int(
            early[
                "needs_manual_audit"
            ].sum()
        ),
    )

    print(
        "Rows in official-source checklist:",
        len(checklist),
    )

    # ----------------------------------------------
    # Optional price cross-check
    # ----------------------------------------------

    cross_check_against_prices(
        nifty500
    )

    print("\n" + "=" * 65)
    print("MEMBERSHIP VALIDATION COMPLETE")
    print("=" * 65)

    print(
        f"Outputs:\n{OUTPUT_DIR.resolve()}"
    )

    print(
        "\nMost important files to inspect:"
    )

    print(
        "1. nifty500_month_end_counts.csv"
    )

    print(
        "2. early_2015_2017_intervals.csv"
    )

    print(
        "3. official_documents_to_verify.csv"
    )

    print(
        "4. membership_price_symbol_mismatches.csv "
        "(if generated)"
    )


if __name__ == "__main__":
    main()