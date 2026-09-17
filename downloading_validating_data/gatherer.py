"""
Download legacy NSE Capital Market (CM) daily Bhavcopies.

Coverage
--------
2013-01-01 through 2024-07-05 inclusive.

Why 2024-07-05?
----------------
The legacy CM bhavcopy format was replaced by the UDiFF format from
8 July 2024. The next downloader should handle the UDiFF period
2024-07-08 through 2026-03-31 separately.

Official legacy filename pattern
--------------------------------
cmDDMMMYYYYbhav.csv.zip

Example:
cm02JAN2019bhav.csv.zip

Official archive pattern
------------------------
https://nsearchives.nseindia.com/content/historical/EQUITIES/
    YYYY/MMM/cmDDMMMYYYYbhav.csv.zip
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests


# ============================================================
# CONFIGURATION
# ============================================================

START_DATE = date(2013, 1, 1)
END_DATE = date(2024, 7, 5)

OUTPUT_DIR = Path("data/raw/bhavcopy_legacy")
MANIFEST_FILE = OUTPUT_DIR / "manifest.csv"

BASE_URL = (
    "https://nsearchives.nseindia.com/"
    "content/historical/EQUITIES"
)

# Be polite to NSE's archive server.
REQUEST_DELAY_SECONDS = 0.20

TIMEOUT_SECONDS = 30
MAX_RETRIES = 4

# Columns we expect in the legacy bhavcopy.
#
# These match the files you uploaded and verified earlier.
REQUIRED_COLUMNS = {
    "SYMBOL",
    "SERIES",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "LAST",
    "PREVCLOSE",
    "TOTTRDQTY",
    "TOTTRDVAL",
    "TIMESTAMP",
    "TOTALTRADES",
    "ISIN",
}


# ============================================================
# HELPERS
# ============================================================

def filename_for_date(d: date) -> str:
    """
    Example:
        2019-01-02 -> cm02JAN2019bhav.csv.zip
    """
    month = d.strftime("%b").upper()
    return f"cm{d:%d}{month}{d:%Y}bhav.csv.zip"


def url_for_date(d: date) -> str:
    """
    Build the official NSE archive URL.
    """
    month = d.strftime("%b").upper()
    filename = filename_for_date(d)

    return (
        f"{BASE_URL}/"
        f"{d:%Y}/"
        f"{month}/"
        f"{filename}"
    )


def expected_csv_name(d: date) -> str:
    """
    ZIP:
        cm02JAN2019bhav.csv.zip

    Expected CSV:
        cm02JAN2019bhav.csv
    """
    return filename_for_date(d).removesuffix(".zip")


def inspect_zip(content: bytes, d: date) -> tuple[bool, str, int]:
    """
    Validate the downloaded object.

    Checks:
      1. It is a genuine ZIP.
      2. Expected CSV is present.
      3. CSV header contains required legacy bhavcopy fields.

    Returns
    -------
    valid : bool
    message : str
    row_count : int
        Number of data rows if validation succeeded.
    """

    if not content.startswith(b"PK"):
        return False, "response is not ZIP data", 0

    try:
        buffer = io.BytesIO(content)

        if not zipfile.is_zipfile(buffer):
            return False, "invalid ZIP structure", 0

        buffer.seek(0)

        with zipfile.ZipFile(buffer) as zf:

            # Test CRC/integrity of all members.
            bad_member = zf.testzip()
            if bad_member is not None:
                return False, f"corrupt ZIP member: {bad_member}", 0

            members = zf.namelist()

            expected = expected_csv_name(d)

            # Usually exact, but match case-insensitively just in case.
            matches = [
                m for m in members
                if Path(m).name.lower() == expected.lower()
            ]

            if not matches:
                return (
                    False,
                    f"expected CSV {expected!r} not found; "
                    f"members={members}",
                    0,
                )

            csv_member = matches[0]

            with zf.open(csv_member) as f:
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

                # Legacy files sometimes contain whitespace.
                normalized_header = {
                    col.strip()
                    for col in header
                    if col.strip()
                }

                missing = REQUIRED_COLUMNS - normalized_header

                if missing:
                    return (
                        False,
                        "missing required columns: "
                        + ", ".join(sorted(missing)),
                        0,
                    )

                row_count = sum(1 for row in reader if any(row))

                if row_count == 0:
                    return False, "CSV contains no data rows", 0

        return True, "ok", row_count

    except Exception as exc:
        return False, f"ZIP validation error: {exc}", 0


def validate_existing_file(path: Path, d: date) -> tuple[bool, str, int]:
    """
    Revalidate an already-downloaded file before skipping it.
    """
    try:
        content = path.read_bytes()
    except OSError as exc:
        return False, f"cannot read existing file: {exc}", 0

    return inspect_zip(content, d)


def append_manifest(row: dict) -> None:
    """
    Append one download attempt/result to manifest.csv.
    """

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

        writer = csv.DictWriter(f, fieldnames=fields)

        if not exists:
            writer.writeheader()

        writer.writerow(row)


def download_one(
    session: requests.Session,
    d: date,
) -> str:
    """
    Download and validate one trading-date candidate.

    Returns one of:
        DOWNLOADED
        SKIPPED
        MISSING
        ERROR
    """

    filename = filename_for_date(d)
    url = url_for_date(d)
    destination = OUTPUT_DIR / filename

    # --------------------------------------------------------
    # Existing file
    # --------------------------------------------------------

    if destination.exists():

        valid, message, rows = validate_existing_file(
            destination,
            d,
        )

        if valid:
            print(
                f"[SKIP] {d}  "
                f"{destination.stat().st_size / 1024:8.1f} KB  "
                f"{rows:5d} rows"
            )
            return "SKIPPED"

        print(
            f"[BAD ] {d} existing file invalid: {message}"
        )

        # Do not trust it. Remove and reacquire.
        destination.unlink()

    # --------------------------------------------------------
    # Download with retries
    # --------------------------------------------------------

    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                url,
                timeout=TIMEOUT_SECONDS,
            )

        except requests.RequestException as exc:

            last_error = str(exc)

            print(
                f"[RETRY] {d} request error "
                f"({attempt}/{MAX_RETRIES}): {exc}"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        # ----------------------------------------------------
        # 404 = typically holiday/weekend/nonexistent file
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Retry server/rate-limit errors
        # ----------------------------------------------------

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
                f"[RETRY] {d} HTTP {response.status_code} "
                f"({attempt}/{MAX_RETRIES})"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        # ----------------------------------------------------
        # Unexpected HTTP result
        # ----------------------------------------------------

        if response.status_code != 200:

            last_error = (
                f"unexpected HTTP {response.status_code}"
            )

            break

        # ----------------------------------------------------
        # Validate before writing
        # ----------------------------------------------------

        content = response.content

        valid, message, rows = inspect_zip(
            content,
            d,
        )

        if not valid:

            last_error = message

            print(
                f"[RETRY] {d} invalid response "
                f"({attempt}/{MAX_RETRIES}): {message}"
            )

            time.sleep(2 ** (attempt - 1))
            continue

        # ----------------------------------------------------
        # Atomic-ish write:
        # write temporary file, then rename.
        # ----------------------------------------------------

        temp_path = destination.with_suffix(
            destination.suffix + ".part"
        )

        temp_path.write_bytes(content)
        temp_path.replace(destination)

        size = len(content)

        print(
            f"[ OK ] {d}  "
            f"{size / 1024:8.1f} KB  "
            f"{rows:5d} rows"
        )

        append_manifest({
            "date": d.isoformat(),
            "filename": filename,
            "url": url,
            "status": "downloaded",
            "http_status": 200,
            "bytes": size,
            "rows": rows,
            "message": "ok",
        })

        return "DOWNLOADED"

    # --------------------------------------------------------
    # Permanent failure after retries
    # --------------------------------------------------------

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


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = requests.Session()

    session.headers.update({
        # NSE archive endpoints tend to behave better with
        # an ordinary browser-like User-Agent.
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

        # NSE equity market is closed Saturdays/Sundays.
        #
        # We don't need to waste requests on them.
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
    print("DOWNLOAD COMPLETE")
    print("=" * 60)

    for key, value in stats.items():
        print(f"{key:12s}: {value}")

    print()
    print(f"Output   : {OUTPUT_DIR.resolve()}")
    print(f"Manifest : {MANIFEST_FILE.resolve()}")

    if stats["ERROR"]:

        print(
            "\nWARNING:"
            f" {stats['ERROR']} dates encountered real download "
            "errors. Inspect manifest.csv and retry them."
        )

import pandas as pd


def build_legacy_parquet() -> None:
    """
    Read every validated legacy NSE bhavcopy ZIP and combine them
    into one normalized Parquet dataset.

    Raw ZIP files remain untouched.
    """

    processed_dir = Path("data/processed")
    processed_dir.mkdir(parents=True, exist_ok=True)

    output_file = processed_dir / "nse_cm_legacy_2013_2024.parquet"

    frames = []

    zip_files = sorted(
        OUTPUT_DIR.glob("cm*bhav.csv.zip")
    )

    print(f"\nBuilding Parquet from {len(zip_files)} ZIP files...")

    for i, zip_path in enumerate(zip_files, start=1):

        try:
            # pandas can read the single CSV contained inside
            # these ZIP archives directly.
            df = pd.read_csv(
                zip_path,
                compression="zip",
            )

            # Remove legacy trailing blank column if present.
            df = df.loc[
                :,
                ~df.columns.str.startswith("Unnamed")
            ]

            # Strip accidental whitespace from headers.
            df.columns = [
                col.strip()
                for col in df.columns
            ]

            # ------------------------------------------------
            # Normalize legacy NSE column names
            # ------------------------------------------------

            rename_map = {
                "SYMBOL": "symbol",
                "SERIES": "series",
                "OPEN": "open",
                "HIGH": "high",
                "LOW": "low",
                "CLOSE": "close",
                "LAST": "last",
                "PREVCLOSE": "prev_close",
                "TOTTRDQTY": "volume",
                "TOTTRDVAL": "traded_value",
                "TIMESTAMP": "date",
                "TOTALTRADES": "num_trades",
                "ISIN": "isin",
            }

            df = df.rename(columns=rename_map)

            expected = set(rename_map.values())

            missing = expected - set(df.columns)

            if missing:
                raise ValueError(
                    f"{zip_path.name}: missing columns {sorted(missing)}"
                )

            # Keep only the fields actually needed downstream.
            df = df[
                [
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
                ]
            ]

            # ------------------------------------------------
            # Types
            # ------------------------------------------------

            # ------------------------------------------------
            # Trading date
            # ------------------------------------------------
            #
            # NSE changed TIMESTAMP formatting across historical
            # bhavcopy vintages (e.g. 13-JUL-2020 vs 13-Jul-20).
            #
            # Each bhavcopy contains one trading day and its date
            # is encoded unambiguously in the official filename:
            #
            #     cm13JUL2020bhav.csv.zip
            #
            # Therefore use the source filename as the canonical
            # trading date instead of relying on TIMESTAMP formatting.
            #
            filename_date = pd.to_datetime(
                zip_path.name[2:11],   # e.g. "13JUL2020"
                format="%d%b%Y",
                errors="raise",
            )

            # Optional validation of the CSV TIMESTAMP below.
            raw_timestamp = pd.to_datetime(
                df["date"],
                format="mixed",
                dayfirst=True,
                errors="coerce",
            )

            # Every valid row should refer to the same day as the filename.
            mismatch = (
                raw_timestamp.notna()
                & (raw_timestamp.dt.normalize() != filename_date.normalize())
            )

            if mismatch.any():
                raise ValueError(
                    f"{zip_path.name}: TIMESTAMP disagrees with filename "
                    f"for {int(mismatch.sum())} rows"
                )

            df["date"] = filename_date

            numeric_columns = [
                "open",
                "high",
                "low",
                "close",
                "last",
                "prev_close",
                "volume",
                "traded_value",
                "num_trades",
            ]

            for col in numeric_columns:
                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce",
                )

            df["symbol"] = (
                df["symbol"]
                .astype("string")
                .str.strip()
            )

            df["series"] = (
                df["series"]
                .astype("string")
                .str.strip()
            )

            df["isin"] = (
                df["isin"]
                .astype("string")
                .str.strip()
            )

            # Preserve provenance.
            df["source_file"] = zip_path.name
            df["source_format"] = "legacy_cm_bhavcopy"

            frames.append(df)

            if i % 100 == 0:
                print(
                    f"Parsed {i:,}/{len(zip_files):,} files"
                )

        except Exception as exc:
            raise RuntimeError(
                f"Failed while processing {zip_path}: {exc}"
            ) from exc

    if not frames:
        raise RuntimeError("No bhavcopy files found.")

    print("\nConcatenating...")

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    # --------------------------------------------------------
    # Basic integrity checks
    # --------------------------------------------------------

    combined = combined.sort_values(
        ["date", "isin", "series", "symbol"]
    ).reset_index(drop=True)

    # There should not normally be duplicate security rows
    # for the same date/series/ISIN.
    duplicate_mask = combined.duplicated(
        subset=[
            "date",
            "isin",
            "series",
        ],
        keep=False,
    )

    duplicates = int(duplicate_mask.sum())

    if duplicates:
        print(
            f"WARNING: {duplicates:,} rows participate "
            "in duplicate date/ISIN/series keys."
        )

    print(f"Rows       : {len(combined):,}")
    print(
        f"Dates      : "
        f"{combined['date'].min().date()} "
        f"to "
        f"{combined['date'].max().date()}"
    )
    print(f"ISINs      : {combined['isin'].nunique():,}")
    print(f"Symbols    : {combined['symbol'].nunique():,}")

    # --------------------------------------------------------
    # Write compressed Parquet
    # --------------------------------------------------------

    combined.to_parquet(
        output_file,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    print(
        f"\nParquet written:\n{output_file.resolve()}"
    )

    print(
        f"Size: "
        f"{output_file.stat().st_size / 1024**2:.1f} MB"
    )

if __name__ == "__main__":
    main()
    build_legacy_parquet()