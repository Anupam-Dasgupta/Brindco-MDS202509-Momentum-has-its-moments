from pathlib import Path
import pandas as pd
import pyarrow.dataset as ds


PRICE_PARQUET = Path(
    "data/processed/nse_cm_2013_2026.parquet"
)

TRI_PARQUET = Path(
    "data/processed/nifty500_tri_2013_2026.parquet"
)

OUTPUT = Path(
    "data/processed/nse_trading_calendar_2013_2026.parquet"
)

AUDIT = Path(
    "data/processed/trading_calendar_audit.csv"
)


def main():

    # --------------------------------------------------------
    # 1. Extract actual trading dates from NSE bhavcopies
    # --------------------------------------------------------

    dataset = ds.dataset(
        PRICE_PARQUET,
        format="parquet",
    )

    table = dataset.to_table(
        columns=["date"]
    )

    price_dates = (
        table
        .to_pandas()["date"]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )

    price_dates = pd.to_datetime(
        price_dates
    )

    # --------------------------------------------------------
    # 2. Build canonical calendar
    # --------------------------------------------------------

    calendar = pd.DataFrame({
        "date": price_dates
    })

    calendar["trading_day_number"] = (
        range(len(calendar))
    )

    calendar["previous_trading_day"] = (
        calendar["date"].shift(1)
    )

    calendar["next_trading_day"] = (
        calendar["date"].shift(-1)
    )

    calendar["next_2_trading_days"] = (
        calendar["date"].shift(-2)
    )

    calendar["calendar_gap_from_previous"] = (
        calendar["date"]
        .diff()
        .dt.days
    )

    calendar["year"] = (
        calendar["date"].dt.year
    )

    calendar["month"] = (
        calendar["date"].dt.month
    )

    calendar["weekday"] = (
        calendar["date"].dt.day_name()
    )

    # --------------------------------------------------------
    # 3. Month-end trading dates
    # --------------------------------------------------------

    month_end = (
        calendar
        .groupby(
            [
                calendar["date"].dt.year,
                calendar["date"].dt.month,
            ]
        )["date"]
        .transform("max")
    )

    calendar["is_last_trading_day_of_month"] = (
        calendar["date"].eq(month_end)
    )

    # --------------------------------------------------------
    # 4. TRI cross-check
    # --------------------------------------------------------

    tri = pd.read_parquet(
        TRI_PARQUET,
        columns=["date"],
    )

    tri_dates = set(
        pd.to_datetime(
            tri["date"]
        )
    )

    price_date_set = set(
        calendar["date"]
    )

    only_prices = sorted(
        price_date_set - tri_dates
    )

    only_tri = sorted(
        tri_dates - price_date_set
    )

    audit_rows = []

    for d in only_prices:
        audit_rows.append({
            "date": d,
            "issue":
                "BHAVCOPY_DATE_MISSING_FROM_TRI",
        })

    for d in only_tri:
        audit_rows.append({
            "date": d,
            "issue":
                "TRI_DATE_MISSING_FROM_BHAVCOPY",
        })

    audit = pd.DataFrame(
        audit_rows,
        columns=["date", "issue"],
    )

    audit.to_csv(
        AUDIT,
        index=False,
    )

    # --------------------------------------------------------
    # 5. Save
    # --------------------------------------------------------

    calendar.to_parquet(
        OUTPUT,
        compression="zstd",
        index=False,
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "TRADING CALENDAR BUILD COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"Trading sessions      : "
        f"{len(calendar):,}"
    )

    print(
        f"First session         : "
        f"{calendar['date'].min().date()}"
    )

    print(
        f"Last session          : "
        f"{calendar['date'].max().date()}"
    )

    print(
        f"Month-end sessions    : "
        f"{calendar['is_last_trading_day_of_month'].sum():,}"
    )

    print(
        f"Bhavcopy not in TRI   : "
        f"{len(only_prices):,}"
    )

    print(
        f"TRI not in bhavcopy   : "
        f"{len(only_tri):,}"
    )

    print(
        "\nLargest observed calendar gaps:"
    )

    print(
        calendar[
            [
                "date",
                "previous_trading_day",
                "calendar_gap_from_previous",
            ]
        ]
        .nlargest(
            10,
            "calendar_gap_from_previous",
        )
        .to_string(
            index=False
        )
    )

    print(
        f"\nWritten:\n{OUTPUT.resolve()}"
    )


if __name__ == "__main__":
    main()