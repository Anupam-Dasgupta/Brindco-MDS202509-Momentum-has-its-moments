"""
Download and normalize NSE Capital Market UDiFF Bhavcopies.

Coverage
--------
2024-07-08 through 2026-03-31 inclusive.

This script does NOT touch or redownload the legacy 2013-2024 data.

Outputs
-------
Raw ZIPs:
    data/raw/bhavcopy_udiff/

Modern processed parquet:
    data/processed/nse_cm_udiff_2024_2026.parquet

Final combined parquet:
    data/processed/nse_cm_2013_2026.parquet

Expected existing legacy parquet:
    data/processed/nse_cm_legacy_2013_2024.parquet
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests


# ============================================================
# CONFIG
# ============================================================

START_DATE = date(2024, 7, 8)
END_DATE = date(2026, 3, 31)

RAW_DIR = Path("data/raw/bhavcopy_udiff")
PROCESSED_DIR = Path("data/processed")

MANIFEST_FILE = RAW_DIR / "manifest.csv"

UDIFF_PARQUET = (
    PROCESSED_DIR / "nse_cm_udiff_2024_2026.parquet"
)

LEGACY_PARQUET = (
    PROCESSED_DIR / "nse_cm_legacy_2013_2024.parquet"
)

FINAL_PARQUET = (
    PROCESSED_DIR / "nse_cm_2013_2026.parquet"
)

BASE_URL = (
    "https://nsearchives.nseindia.com/content/cm"
)

REQUEST_DELAY_SECONDS = 0.20
TIMEOUT_SECONDS = 30
MAX_RETRIES = 4


# These are the fields verified in the UDiFF file you uploaded.
REQUIRED_COLUMNS = {
    "TradDt",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "FinInstrmNm",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "LastPric",
    "PrvsClsgPric",
    "TtlTradgVol",
    "TtlTrfVal",
    "TtlNbOfTxsExctd",
}


# Canonical schema shared with the legacy parquet.
CANONICAL_COLUMNS = [
    "date",
    "isin",
    "symbol",
    "series",
    "open",
    "high",
    "low",
    "close",
    "last",
    "prev_close",
    "volume",
    "traded_value",
    "num_trades",
    "source_file",
    "source_format",
]


# ============================================================
# FILENAME / URL
# ============================================================

def filename_for_date(d: date) -> str:
    return (
        "BhavCopy_NSE_CM_0_0_0_"
        f"{d:%Y%m%d}"
        "_F_0000.csv.zip"
    )


def expected_csv_name(d: date) -> str:
    return filename_for_date(d).removesuffix(".zip")


def url_for_date(d: date) -> str:
    return f"{BASE_URL}/{filename_for_date(d)}"


# ============================================================
# VALIDATION
# ============================================================

def inspect_zip(
    content: bytes,
    d: date,
) -> tuple[bool, str, int]:

    if not content.startswith(b"PK"):
        return False, "response is not ZIP data", 0

    try:
        buffer = io.BytesIO(content)

        if not zipfile.is_zipfile(buffer):
            return False, "invalid ZIP structure", 0

        buffer.seek(0)

        with zipfile.ZipFile(buffer) as zf:

            bad_member = zf.testzip()

            if bad_member is not None:
                return (
                    False,
                    f"corrupt ZIP member: {bad_member}",
                    0,
                )

            expected = expected_csv_name(d)

            matches = [
                member
                for member in zf.namelist()
                if Path(member).name.lower()
                == expected.lower()
            ]

            if not matches:
                return (
                    False,
                    f"expected CSV {expected!r} not found; "
                    f"members={zf.namelist()}",
                    0,
                )

            with zf.open(matches[0]) as f:

                text = io.TextIOWrapper(
                    f,
                    encoding="utf-8-sig",
                    errors="replace",
                    newline="",
                )

                reader = csv.reader(text)

                try:
                    header = next(reader)
                except StopIteration:
                    return False, "CSV is empty", 0

                header = {
                    x.strip()
                    for x in header
                    if x.strip()
                }

                missing = REQUIRED_COLUMNS - header

                if missing:
                    return (
                        False,
                        "missing required columns: "
                        + ", ".join(sorted(missing)),
                        0,
                    )

                rows = sum(
                    1
                    for row in reader
                    if any(row)
                )

                if rows == 0:
                    return False, "CSV has zero rows", 0

        return True, "ok", rows

    except Exception as exc:
        return (
            False,
            f"ZIP validation error: {exc}",
            0,
        )


def validate_existing(
    path: Path,
    d: date,
) -> tuple[bool, str, int]:

    try:
        return inspect_zip(
            path.read_bytes(),
            d,
        )

    except OSError as exc:
        return (
            False,
            f"could not read existing file: {exc}",
            0,
        )


# ============================================================
# MANIFEST
# ============================================================

def append_manifest(row: dict) -> None:

    fields = [
        "date",
        "filename",
        "url",
        "status",
        "http_status",
        "bytes",
        "rows",
        "message",
    ]

    exists = MANIFEST_FILE.exists()

    with MANIFEST_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


# ============================================================
# DOWNLOAD
# ============================================================

def download_one(
    session: requests.Session,
    d: date,
) -> str:

    filename = filename_for_date(d)
    destination = RAW_DIR / filename
    url = url_for_date(d)

    # ----------------------------------------------
    # Already downloaded?
    # ----------------------------------------------

    if destination.exists():

        valid, message, rows = validate_existing(
            destination,
            d,
        )

        if valid:

            print(
                f"[SKIP] {d} "
                f"{destination.stat().st_size / 1024:8.1f} KB "
                f"{rows:5d} rows"
            )

            return "SKIPPED"

        print(
            f"[BAD ] {d} existing file invalid: "
            f"{message}"
        )

        destination.unlink()

    # ----------------------------------------------
    # Download
    # ----------------------------------------------

    last_error = ""

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = session.get(
                url,
                timeout=TIMEOUT_SECONDS,
            )

        except requests.RequestException as exc:

            last_error = str(exc)

            print(
                f"[RETRY] {d} request failure "
                f"({attempt}/{MAX_RETRIES}): {exc}"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        # Missing archive object.
        if response.status_code == 404:

            print(f"[MISS] {d} 404")

            append_manifest({
                "date": d.isoformat(),
                "filename": filename,
                "url": url,
                "status": "missing",
                "http_status": 404,
                "bytes": 0,
                "rows": 0,
                "message": "archive object not found",
            })

            return "MISSING"

        # Retry likely transient errors.
        if response.status_code in {
            403,
            408,
            429,
            500,
            502,
            503,
            504,
        }:

            last_error = (
                f"HTTP {response.status_code}"
            )

            print(
                f"[RETRY] {d} "
                f"HTTP {response.status_code} "
                f"({attempt}/{MAX_RETRIES})"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        if response.status_code != 200:

            last_error = (
                f"unexpected HTTP "
                f"{response.status_code}"
            )

            break

        content = response.content

        valid, message, rows = inspect_zip(
            content,
            d,
        )

        if not valid:

            last_error = message

            print(
                f"[RETRY] {d} invalid response "
                f"({attempt}/{MAX_RETRIES}): "
                f"{message}"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        # Temporary file first so interrupted writes don't
        # masquerade as completed downloads.
        temp = destination.with_suffix(
            destination.suffix + ".part"
        )

        temp.write_bytes(content)
        temp.replace(destination)

        print(
            f"[ OK ] {d} "
            f"{len(content) / 1024:8.1f} KB "
            f"{rows:5d} rows"
        )

        append_manifest({
            "date": d.isoformat(),
            "filename": filename,
            "url": url,
            "status": "downloaded",
            "http_status": 200,
            "bytes": len(content),
            "rows": rows,
            "message": "ok",
        })

        return "DOWNLOADED"

    print(
        f"[ERR ] {d} failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    )

    append_manifest({
        "date": d.isoformat(),
        "filename": filename,
        "url": url,
        "status": "error",
        "http_status": "",
        "bytes": 0,
        "rows": 0,
        "message": last_error,
    })

    return "ERROR"


def download_udiff() -> None:

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept": (
            "application/zip,"
            "application/octet-stream,"
            "*/*"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })

    stats = {
        "DOWNLOADED": 0,
        "SKIPPED": 0,
        "MISSING": 0,
        "ERROR": 0,
    }

    d = START_DATE

    while d <= END_DATE:

        # Skip Saturdays and Sundays.
        if d.weekday() < 5:

            result = download_one(
                session,
                d,
            )

            stats[result] += 1

            time.sleep(
                REQUEST_DELAY_SECONDS
            )

        d += timedelta(days=1)

    print("\n" + "=" * 60)
    print("UDIFF DOWNLOAD COMPLETE")
    print("=" * 60)

    for key, value in stats.items():
        print(f"{key:12s}: {value}")

    print()
    print(f"Raw files : {RAW_DIR.resolve()}")
    print(
        f"Manifest  : "
        f"{MANIFEST_FILE.resolve()}"
    )

    if stats["ERROR"]:

        print(
            "\nWARNING: "
            f"{stats['ERROR']} dates produced actual "
            "errors. Inspect the manifest and rerun."
        )


# ============================================================
# NORMALIZE ONE UDIFF FILE
# ============================================================

def read_and_normalize_udiff(
    zip_path: Path,
) -> pd.DataFrame:

    df = pd.read_csv(
        zip_path,
        compression="zip",
        low_memory=False,
    )

    df.columns = [
        c.strip()
        for c in df.columns
    ]

    missing = REQUIRED_COLUMNS - set(df.columns)

    if missing:

        raise ValueError(
            f"{zip_path.name}: missing columns "
            f"{sorted(missing)}"
        )

    # --------------------------------------------------------
    # Canonical trading date from filename
    #
    # BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip
    #                       ^^^^^^^^
    # --------------------------------------------------------

    pieces = zip_path.name.split("_")

    # Structure:
    # BhavCopy NSE CM 0 0 0 YYYYMMDD F 0000.csv.zip
    filename_date_text = pieces[6]

    filename_date = pd.to_datetime(
        filename_date_text,
        format="%Y%m%d",
        errors="raise",
    )

    # Validate internal TradDt rather than blindly trusting it.
    internal_dates = pd.to_datetime(
        df["TradDt"],
        errors="coerce",
    )

    bad_dates = (
        internal_dates.notna()
        & (
            internal_dates.dt.normalize()
            != filename_date.normalize()
        )
    )

    if bad_dates.any():

        raise ValueError(
            f"{zip_path.name}: TradDt disagrees "
            f"with filename for "
            f"{int(bad_dates.sum())} rows"
        )

    # --------------------------------------------------------
    # Rename to exactly the same schema as legacy data.
    # --------------------------------------------------------

    rename_map = {
        "ISIN": "isin",
        "TckrSymb": "symbol",
        "SctySrs": "series",
        "OpnPric": "open",
        "HghPric": "high",
        "LwPric": "low",
        "ClsPric": "close",
        "LastPric": "last",
        "PrvsClsgPric": "prev_close",
        "TtlTradgVol": "volume",
        "TtlTrfVal": "traded_value",
        "TtlNbOfTxsExctd": "num_trades",
    }

    df = df.rename(
        columns=rename_map,
    )

    # One date per file.
    df["date"] = filename_date

    # --------------------------------------------------------
    # Types
    # --------------------------------------------------------

    for col in [
        "open",
        "high",
        "low",
        "close",
        "last",
        "prev_close",
        "volume",
        "traded_value",
        "num_trades",
    ]:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    for col in [
        "isin",
        "symbol",
        "series",
    ]:

        df[col] = (
            df[col]
            .astype("string")
            .str.strip()
        )

    df["source_file"] = zip_path.name
    df["source_format"] = "udiff_cm_bhavcopy"

    return df[CANONICAL_COLUMNS]


# ============================================================
# BUILD UDIFF PARQUET
# ============================================================

def build_udiff_parquet() -> None:

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = sorted(
        RAW_DIR.glob(
            "BhavCopy_NSE_CM_0_0_0_*_F_0000.csv.zip"
        )
    )

    if not files:
        raise RuntimeError(
            f"No UDiFF ZIP files found in {RAW_DIR}"
        )

    print(
        f"\nBuilding UDiFF Parquet from "
        f"{len(files):,} files..."
    )

    frames = []

    for i, zip_path in enumerate(
        files,
        start=1,
    ):

        try:

            frame = read_and_normalize_udiff(
                zip_path
            )

            frames.append(frame)

        except Exception as exc:

            raise RuntimeError(
                f"Failed processing "
                f"{zip_path.name}: {exc}"
            ) from exc

        if i % 100 == 0:

            print(
                f"Parsed {i:,}/{len(files):,} files"
            )

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    combined = combined.sort_values(
        [
            "date",
            "isin",
            "series",
            "symbol",
        ]
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # Sanity checks
    # --------------------------------------------------------

    duplicate_mask = combined.duplicated(
        subset=[
            "date",
            "isin",
            "series",
        ],
        keep=False,
    )

    duplicate_count = int(
        duplicate_mask.sum()
    )

    if duplicate_count:

        print(
            f"WARNING: {duplicate_count:,} rows "
            "participate in duplicate "
            "date/ISIN/series keys."
        )

    print()
    print(f"Rows    : {len(combined):,}")
    print(
        f"Dates   : "
        f"{combined['date'].min().date()} "
        f"to "
        f"{combined['date'].max().date()}"
    )
    print(
        f"Sessions: "
        f"{combined['date'].nunique():,}"
    )
    print(
        f"ISINs   : "
        f"{combined['isin'].nunique():,}"
    )
    print(
        f"Symbols : "
        f"{combined['symbol'].nunique():,}"
    )

    combined.to_parquet(
        UDIFF_PARQUET,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    print(
        f"\nWritten:\n"
        f"{UDIFF_PARQUET.resolve()}"
    )

    print(
        f"Size: "
        f"{UDIFF_PARQUET.stat().st_size / 1024**2:.1f} MB"
    )


# ============================================================
# MERGE LEGACY + UDIFF WITHOUT LOADING EVERYTHING INTO RAM
# ============================================================

def build_final_parquet() -> None:

    if not LEGACY_PARQUET.exists():

        raise FileNotFoundError(
            "Legacy parquet not found:\n"
            f"{LEGACY_PARQUET.resolve()}"
        )

    if not UDIFF_PARQUET.exists():

        raise FileNotFoundError(
            "UDiFF parquet not found:\n"
            f"{UDIFF_PARQUET.resolve()}"
        )

    print("\nCombining legacy + UDiFF...")
    print(f"Legacy: {LEGACY_PARQUET}")
    print(f"UDiFF : {UDIFF_PARQUET}")

    # Delete an older final output so we never accidentally
    # append duplicate data.
    if FINAL_PARQUET.exists():
        FINAL_PARQUET.unlink()

    writer = None

    try:

        for parquet_path in [
            LEGACY_PARQUET,
            UDIFF_PARQUET,
        ]:

            parquet_file = pq.ParquetFile(
                parquet_path
            )

            for batch in parquet_file.iter_batches(
                batch_size=100_000
            ):

                table = pa.Table.from_batches(
                    [batch]
                )

                # Enforce canonical order.
                table = table.select(
                    CANONICAL_COLUMNS
                )

                if writer is None:

                    writer = pq.ParquetWriter(
                        FINAL_PARQUET,
                        table.schema,
                        compression="zstd",
                    )

                else:

                    # Catch schema differences instead of
                    # silently coercing something incorrectly.
                    if table.schema != writer.schema:

                        raise ValueError(
                            "\nSchema mismatch while merging.\n"
                            f"Expected:\n{writer.schema}\n\n"
                            f"Found:\n{table.schema}"
                        )

                writer.write_table(table)

    finally:

        if writer is not None:
            writer.close()

    print(
        f"\nFinal dataset written:\n"
        f"{FINAL_PARQUET.resolve()}"
    )

    print(
        f"Size: "
        f"{FINAL_PARQUET.stat().st_size / 1024**2:.1f} MB"
    )


# ============================================================
# FINAL VALIDATION
# ============================================================

def validate_final_parquet() -> None:

    print("\nValidating final dataset...")

    pf = pq.ParquetFile(
        FINAL_PARQUET
    )

    print(f"Rows      : {pf.metadata.num_rows:,}")
    print(
        f"Row groups: "
        f"{pf.metadata.num_row_groups:,}"
    )

    # Load only dates and key identifiers for validation,
    # rather than every numerical field.
    keys = pd.read_parquet(
        FINAL_PARQUET,
        columns=[
            "date",
            "isin",
            "symbol",
            "series",
        ],
    )

    print(
        f"First date: {keys['date'].min().date()}"
    )

    print(
        f"Last date : {keys['date'].max().date()}"
    )

    print(
        f"Sessions  : {keys['date'].nunique():,}"
    )

    print(
        f"Unique ISINs: "
        f"{keys['isin'].nunique():,}"
    )

    # Check boundary explicitly.
    legacy_last = pd.Timestamp(
        "2024-07-05"
    )

    udiff_first = pd.Timestamp(
        "2024-07-08"
    )

    print()
    print(
        "2024-07-05 present:",
        legacy_last in set(keys["date"]),
    )

    print(
        "2024-07-08 present:",
        udiff_first in set(keys["date"]),
    )

    print(
        "\nFinal market-data parquet looks "
        "structurally valid."
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # 1. Download modern raw ZIPs.
    download_udiff()

    # 2. Convert them to normalized Parquet.
    build_udiff_parquet()

    # 3. Join with your already-existing legacy Parquet.
    build_final_parquet()

    # 4. Sanity-check the resulting complete dataset.
    validate_final_parquet()