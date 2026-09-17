from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


# ============================================================
# PATHS
# ============================================================

RAW_DIR = Path("data/raw/benchmark")

OUTPUT_DIR = Path("data/processed")

OUTPUT_PARQUET = (
    OUTPUT_DIR / "nifty500_tri_2013_2026.parquet"
)

OUTPUT_CSV = (
    OUTPUT_DIR / "nifty500_tri_2013_2026.csv"
)


# ============================================================
# HELPERS
# ============================================================

def normalize_col(name: str) -> str:
    """
    Example:
        'Total Returns Index' -> 'TOTAL_RETURNS_INDEX'
    """

    name = str(name).strip().upper()
    name = re.sub(r"[^A-Z0-9]+", "_", name)
    return name.strip("_")


def find_column(columns, candidates):
    """
    Return first matching normalized column.
    """

    columns = set(columns)

    for candidate in candidates:
        if candidate in columns:
            return candidate

    raise ValueError(
        f"Could not identify column.\n"
        f"Tried: {candidates}\n"
        f"Available: {sorted(columns)}"
    )


# ============================================================
# LOAD ONE FILE
# ============================================================

def load_one(path: Path) -> pd.DataFrame:

    df = pd.read_csv(
        path,
        low_memory=False,
    )

    # Normalize headers.
    df.columns = [
        normalize_col(c)
        for c in df.columns
    ]

    print(
        f"{path.name}: columns = {list(df.columns)}"
    )

    # ----------------------------------------------
    # Detect date
    # ----------------------------------------------

    date_col = find_column(
        df.columns,
        [
            "DATE",
            "INDEX_DATE",
        ],
    )

    # ----------------------------------------------
    # Detect TRI value
    # ----------------------------------------------

    tri_col = find_column(
        df.columns,
        [
            "TOTAL_RETURNS_INDEX",
            "TOTAL_RETURN_INDEX",
            "TRI",
            "TOTAL_RETURNS_INDEX_VALUE",
            "TOTAL_RETURN_INDEX_VALUE",
        ],
    )

    # ----------------------------------------------
    # Optional index name
    # ----------------------------------------------

    index_col = None

    for candidate in [
        "INDEX_NAME",
        "INDEX",
    ]:
        if candidate in df.columns:
            index_col = candidate
            break

    # ----------------------------------------------
    # Build canonical table
    # ----------------------------------------------

    out = pd.DataFrame()

    out["date"] = pd.to_datetime(
        df[date_col],
        dayfirst=True,
        format="mixed",
        errors="coerce",
    )

    out["tri"] = pd.to_numeric(
        df[tri_col],
        errors="coerce",
    )

    if index_col is not None:
        out["index_name"] = (
            df[index_col]
            .astype("string")
            .str.strip()
        )
    else:
        out["index_name"] = "NIFTY 500"

    out["source_file"] = path.name

    # Drop completely invalid rows.
    out = out[
        out["date"].notna()
        &
        out["tri"].notna()
    ].copy()

    return out


# ============================================================
# MAIN BUILD
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = sorted(
        RAW_DIR.glob(
            "NIFTY 500_Historical_TR_*.csv"
        )
    )

    if not files:
        raise FileNotFoundError(
            f"No NIFTY 500 TRI CSV files found in:\n"
            f"{RAW_DIR.resolve()}"
        )

    print(
        f"\nFound {len(files)} TRI files.\n"
    )

    frames = []

    for path in files:

        frame = load_one(path)

        print(
            f"  {len(frame):4d} usable rows"
        )

        frames.append(frame)

    df = pd.concat(
        frames,
        ignore_index=True,
    )

    # ----------------------------------------------
    # Sort
    # ----------------------------------------------

    df = (
        df
        .sort_values("date")
        .reset_index(drop=True)
    )

    # ----------------------------------------------
    # Exact duplicate dates
    # ----------------------------------------------

    duplicate_dates = df[
        df.duplicated(
            subset=["date"],
            keep=False,
        )
    ].copy()

    if not duplicate_dates.empty:

        print(
            f"\nDuplicate date rows found: "
            f"{len(duplicate_dates):,}"
        )

        duplicate_dates.to_csv(
            OUTPUT_DIR /
            "nifty500_tri_duplicate_dates.csv",
            index=False,
        )

        # If duplicate dates carry different TRI values,
        # that is a genuine problem.
        conflicting = (
            duplicate_dates
            .groupby("date")["tri"]
            .nunique()
        )

        conflicting = conflicting[
            conflicting > 1
        ]

        if not conflicting.empty:

            raise ValueError(
                "Conflicting TRI values found for "
                f"{len(conflicting)} duplicate dates."
            )

        # Identical duplicate observations can safely collapse.
        df = df.drop_duplicates(
            subset=["date"],
            keep="first",
        )

    # ----------------------------------------------
    # Date range
    # ----------------------------------------------

    expected_start = pd.Timestamp(
        "2013-01-01"
    )

    expected_end = pd.Timestamp(
        "2026-03-31"
    )

    first_date = df["date"].min()
    last_date = df["date"].max()

    # ----------------------------------------------
    # Basic value checks
    # ----------------------------------------------

    nonpositive = df[
        df["tri"] <= 0
    ]

    if not nonpositive.empty:

        raise ValueError(
            f"Found {len(nonpositive)} "
            f"non-positive TRI values."
        )

    # ----------------------------------------------
    # Daily TRI returns
    # ----------------------------------------------

    df["tri_return"] = (
        df["tri"]
        .pct_change(
            fill_method=None
        )
    )

    # Very wide diagnostic threshold.
    # This is not automatically an error.
    extreme = df[
        df["tri_return"].abs() > 0.20
    ].copy()

    if not extreme.empty:

        extreme.to_csv(
            OUTPUT_DIR /
            "nifty500_tri_extreme_returns.csv",
            index=False,
        )

    # ----------------------------------------------
    # Calendar gaps diagnostic
    # ----------------------------------------------

    df["calendar_gap_days"] = (
        df["date"]
        .diff()
        .dt.days
    )

    # >5 calendar days deserves inspection.
    long_gaps = df[
        df["calendar_gap_days"] > 5
    ].copy()

    if not long_gaps.empty:

        long_gaps.to_csv(
            OUTPUT_DIR /
            "nifty500_tri_long_gaps.csv",
            index=False,
        )

    # ----------------------------------------------
    # Save
    # ----------------------------------------------

    df.to_parquet(
        OUTPUT_PARQUET,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    df.to_csv(
        OUTPUT_CSV,
        index=False,
    )

    # ----------------------------------------------
    # REPORT
    # ----------------------------------------------

    print(
        "\n"
        + "=" * 60
    )

    print(
        "NIFTY 500 TRI BUILD COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"Input files        : {len(files)}"
    )

    print(
        f"Trading-day rows   : {len(df):,}"
    )

    print(
        f"First date         : "
        f"{first_date.date()}"
    )

    print(
        f"Last date          : "
        f"{last_date.date()}"
    )

    print(
        f"Duplicate rows     : "
        f"{len(duplicate_dates):,}"
    )

    print(
        f"Extreme daily moves: "
        f"{len(extreme):,}"
    )

    print(
        f"Calendar gaps >5d  : "
        f"{len(long_gaps):,}"
    )

    print(
        f"Missing TRI values : "
        f"{df['tri'].isna().sum():,}"
    )

    print(
        f"\nTRI min/max:"
    )

    print(
        df["tri"]
        .describe()
        .to_string()
    )

    print(
        f"\nOutput:\n"
        f"{OUTPUT_PARQUET.resolve()}"
    )

    # ----------------------------------------------
    # Coverage warnings
    # ----------------------------------------------

    if first_date > expected_start:

        print(
            "\nNOTE: First observation is after "
            "2013-01-01. That is fine if "
            "2013-01-01 was not a trading day."
        )

    if last_date < expected_end:

        print(
            "\nWARNING: Dataset ends before "
            "2026-03-31."
        )


if __name__ == "__main__":
    main()