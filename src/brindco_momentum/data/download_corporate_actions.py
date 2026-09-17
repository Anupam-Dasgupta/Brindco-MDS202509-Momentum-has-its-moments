from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from pathlib import Path
from brindco_momentum.paths import ROOT

import pandas as pd
import requests


# ============================================================
# CONFIG
# ============================================================

START_DATE = pd.Timestamp("2013-01-01")
END_DATE = pd.Timestamp("2026-03-31")

RAW_DIR = ROOT / Path("data/raw/corporate_actions")
PROCESSED_DIR = ROOT / Path("data/processed")

OUTPUT_PARQUET = (
    PROCESSED_DIR / "nse_corporate_actions_2013_2026.parquet"
)

OUTPUT_CSV = (
    PROCESSED_DIR / "nse_corporate_actions_2013_2026.csv"
)

MANIFEST_PATH = RAW_DIR / "manifest.csv"

BASE_URL = "https://www.nseindia.com"

LANDING_URL = (
    "https://www.nseindia.com/"
    "companies-listing/corporate-filings-actions"
)

API_URL = (
    "https://www.nseindia.com/api/"
    "corporates-corporateActions"
)

TIMEOUT = 30
MAX_RETRIES = 5
REQUEST_DELAY = 0.5


# ============================================================
# SESSION
# ============================================================

def make_session() -> requests.Session:

    s = requests.Session()

    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/json,text/plain,*/*"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": LANDING_URL,
        "Connection": "keep-alive",
    })

    warm_session(s)

    return s


def warm_session(
    session: requests.Session,
) -> None:

    response = session.get(
        LANDING_URL,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    time.sleep(0.5)


# ============================================================
# MONTH WINDOWS
# ============================================================

def month_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
):

    current = start.to_period("M")

    final = end.to_period("M")

    while current <= final:

        month_start = max(
            current.start_time.normalize(),
            start,
        )

        month_end = min(
            current.end_time.normalize(),
            end,
        )

        yield month_start, month_end

        current += 1


# ============================================================
# HELPERS
# ============================================================

def nse_date(
    ts: pd.Timestamp,
) -> str:

    return ts.strftime("%d-%m-%Y")


def raw_filename(
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:

    return (
        f"corporate_actions_"
        f"{start:%Y%m%d}_"
        f"{end:%Y%m%d}.json"
    )


def sha256_bytes(data: bytes) -> str:

    return hashlib.sha256(
        data
    ).hexdigest()


def append_manifest(row: dict) -> None:

    df = pd.DataFrame([row])

    if MANIFEST_PATH.exists():

        df.to_csv(
            MANIFEST_PATH,
            mode="a",
            header=False,
            index=False,
        )

    else:

        df.to_csv(
            MANIFEST_PATH,
            index=False,
        )


# ============================================================
# VALIDATE API RESPONSE
# ============================================================

def parse_api_response(
    response: requests.Response,
):

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    text = response.text.strip()

    if not text:

        raise ValueError(
            "NSE returned an empty response"
        )

    # Common sign we've received an HTML error/block page.
    if (
        text.startswith("<!DOCTYPE")
        or
        text.startswith("<html")
        or
        "text/html" in content_type
    ):
        raise ValueError(
            "NSE returned HTML instead of JSON"
        )

    try:
        payload = response.json()

    except Exception as exc:

        raise ValueError(
            "Response could not be decoded as JSON"
        ) from exc

    if not isinstance(payload, list):

        raise ValueError(
            f"Expected a JSON list, got "
            f"{type(payload).__name__}"
        )

    return payload


# ============================================================
# DOWNLOAD ONE MONTH
# ============================================================

def download_window(
    session: requests.Session,
    start: pd.Timestamp,
    end: pd.Timestamp,
):

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = raw_filename(
        start,
        end,
    )

    path = RAW_DIR / filename

    # ----------------------------------------------
    # Existing valid raw file
    # ----------------------------------------------

    if path.exists():

        try:

            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(payload, list):

                print(
                    f"[SKIP] "
                    f"{start.date()} → {end.date()} "
                    f"{len(payload):5d} rows"
                )

                return "SKIPPED", payload

        except Exception:

            print(
                f"[BAD ] Existing file invalid: "
                f"{filename}"
            )

            path.unlink()

    params = {
        "index": "equities",
        "from_date": nse_date(start),
        "to_date": nse_date(end),
    }

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = session.get(
                API_URL,
                params=params,
                timeout=TIMEOUT,
            )

            # NSE commonly invalidates/blocks stale sessions.
            if response.status_code in {
                401,
                403,
                429,
            }:

                last_error = (
                    f"HTTP {response.status_code}"
                )

                print(
                    f"[RETRY] "
                    f"{start:%Y-%m} "
                    f"{last_error}; "
                    f"refreshing NSE session"
                )

                time.sleep(
                    2 ** (attempt - 1)
                )

                warm_session(session)

                continue

            if response.status_code >= 500:

                last_error = (
                    f"HTTP {response.status_code}"
                )

                print(
                    f"[RETRY] "
                    f"{start:%Y-%m}: "
                    f"{last_error}"
                )

                time.sleep(
                    2 ** (attempt - 1)
                )

                continue

            response.raise_for_status()

            payload = parse_api_response(
                response
            )

            # --------------------------------------
            # Save exact raw response semantically
            # --------------------------------------

            raw_bytes = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")

            temp = path.with_suffix(
                ".json.part"
            )

            temp.write_bytes(
                raw_bytes
            )

            temp.replace(
                path
            )

            digest = sha256_bytes(
                raw_bytes
            )

            append_manifest({
                "window_start":
                    start.date().isoformat(),
                "window_end":
                    end.date().isoformat(),
                "filename":
                    filename,
                "status":
                    "downloaded",
                "rows":
                    len(payload),
                "sha256":
                    digest,
                "retrieved_at_utc":
                    pd.Timestamp.now(
                        tz="UTC"
                    ).isoformat(),
                "url":
                    response.url,
            })

            print(
                f"[ OK ] "
                f"{start.date()} → {end.date()} "
                f"{len(payload):5d} rows"
            )

            return "DOWNLOADED", payload

        except Exception as exc:

            last_error = repr(exc)

            print(
                f"[RETRY] "
                f"{start:%Y-%m} "
                f"attempt {attempt}/{MAX_RETRIES}: "
                f"{exc}"
            )

            time.sleep(
                2 ** (attempt - 1)
            )

            try:
                warm_session(
                    session
                )
            except Exception:
                pass

    append_manifest({
        "window_start":
            start.date().isoformat(),
        "window_end":
            end.date().isoformat(),
        "filename":
            filename,
        "status":
            "error",
        "rows":
            0,
        "sha256":
            "",
        "retrieved_at_utc":
            pd.Timestamp.now(
                tz="UTC"
            ).isoformat(),
        "url":
            "",
        "error":
            last_error,
    })

    print(
        f"[ERR ] "
        f"{start.date()} → {end.date()} "
        f"{last_error}"
    )

    return "ERROR", None


# ============================================================
# DOWNLOAD EVERYTHING
# ============================================================

def download_all():

    print(
        "\nDownloading NSE corporate actions"
    )

    print(
        f"{START_DATE.date()} "
        f"→ {END_DATE.date()}\n"
    )

    session = make_session()

    stats = {
        "DOWNLOADED": 0,
        "SKIPPED": 0,
        "ERROR": 0,
    }

    for start, end in month_windows(
        START_DATE,
        END_DATE,
    ):

        status, _ = download_window(
            session,
            start,
            end,
        )

        stats[status] += 1

        time.sleep(
            REQUEST_DELAY
        )

    print("\n" + "=" * 60)

    print(
        "CORPORATE-ACTION DOWNLOAD COMPLETE"
    )

    print("=" * 60)

    for key, value in stats.items():

        print(
            f"{key:12s}: {value}"
        )

    if stats["ERROR"]:

        raise RuntimeError(
            f"{stats['ERROR']} monthly windows "
            f"failed. Rerun before building."
        )


# ============================================================
# NORMALIZATION
# ============================================================

def get_value(
    row: dict,
    *keys,
):

    for key in keys:

        if key in row:
            return row[key]

    return None


def normalize_action(
    row: dict,
    source_file: str,
) -> dict:

    return {
        "symbol":
            get_value(
                row,
                "symbol",
            ),

        "company":
            get_value(
                row,
                "comp",
                "company",
            ),

        "series":
            get_value(
                row,
                "series",
            ),

        "face_value":
            get_value(
                row,
                "faceVal",
                "faceValue",
            ),

        "purpose":
            get_value(
                row,
                "subject",
                "purpose",
            ),

        "ex_date":
            get_value(
                row,
                "exDate",
            ),

        # NSE variants have been seen using either key.
        "record_date":
            get_value(
                row,
                "recDate",
                "recordDate",
            ),

        "book_closure_start":
            get_value(
                row,
                "bcStartDate",
            ),

        "book_closure_end":
            get_value(
                row,
                "bcEndDate",
            ),

        "payment_date":
            get_value(
                row,
                "payDate",
                "paymentDate",
            ),

        "remarks":
            get_value(
                row,
                "remarks",
            ),

        "source_file":
            source_file,

        "source":
            "NSE corporate actions API",
    }


def parse_nse_date_series(
    series: pd.Series,
):

    return pd.to_datetime(
        series,
        format="mixed",
        dayfirst=True,
        errors="coerce",
    )


# ============================================================
# BUILD NORMALIZED DATASET
# ============================================================

def build_parquet():

    files = sorted(
        RAW_DIR.glob(
            "corporate_actions_*.json"
        )
    )

    if not files:

        raise RuntimeError(
            "No raw corporate-action files found."
        )

    print(
        f"\nNormalizing {len(files):,} "
        f"monthly raw files..."
    )

    rows = []

    for path in files:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            list,
        ):
            raise ValueError(
                f"{path.name}: "
                f"expected list"
            )

        for record in payload:

            if not isinstance(
                record,
                dict,
            ):
                continue

            rows.append(
                normalize_action(
                    record,
                    path.name,
                )
            )

    df = pd.DataFrame(
        rows
    )

    print(
        f"Raw action rows: "
        f"{len(df):,}"
    )

    # ----------------------------------------------
    # Strings
    # ----------------------------------------------

    string_cols = [
        "symbol",
        "company",
        "series",
        "purpose",
        "remarks",
        "source_file",
        "source",
    ]

    for col in string_cols:

        df[col] = (
            df[col]
            .astype("string")
            .str.strip()
        )

    df["symbol"] = (
        df["symbol"]
        .str.upper()
    )

    df["series"] = (
        df["series"]
        .str.upper()
    )

    # ----------------------------------------------
    # Numeric
    # ----------------------------------------------

    df["face_value"] = (
        pd.to_numeric(
            df["face_value"],
            errors="coerce",
        )
    )

    # ----------------------------------------------
    # Dates
    # ----------------------------------------------

    date_cols = [
        "ex_date",
        "record_date",
        "book_closure_start",
        "book_closure_end",
        "payment_date",
    ]

    for col in date_cols:

        df[col] = (
            parse_nse_date_series(
                df[col]
            )
        )

    # ----------------------------------------------
    # Restrict to requested sample
    # ----------------------------------------------

    # Keep rows whose ex-date is within our requested period.
    # Rows without an ex-date are preserved separately below.
    dated = df[
        df["ex_date"].notna()
    ].copy()

    dated = dated[
        dated["ex_date"].between(
            START_DATE,
            END_DATE,
            inclusive="both",
        )
    ]

    no_ex_date = df[
        df["ex_date"].isna()
    ].copy()

    if not no_ex_date.empty:

        no_ex_date.to_csv(
            PROCESSED_DIR /
            "corporate_actions_missing_ex_date.csv",
            index=False,
        )

    # ----------------------------------------------
    # Dedupe
    # ----------------------------------------------

    identity_cols = [
        "symbol",
        "series",
        "purpose",
        "ex_date",
        "record_date",
        "face_value",
    ]

    duplicate_mask = (
        dated.duplicated(
            subset=identity_cols,
            keep=False,
        )
    )

    duplicate_rows = (
        dated.loc[
            duplicate_mask
        ]
        .sort_values(
            identity_cols
        )
    )

    if not duplicate_rows.empty:

        duplicate_rows.to_csv(
            PROCESSED_DIR /
            "corporate_action_duplicate_candidates.csv",
            index=False,
        )

    before = len(
        dated
    )

    dated = (
        dated
        .sort_values(
            [
                "ex_date",
                "symbol",
                "purpose",
            ]
        )
        .drop_duplicates(
            subset=identity_cols,
            keep="first",
        )
        .reset_index(
            drop=True
        )
    )

    removed = (
        before - len(dated)
    )

    # ----------------------------------------------
    # Write
    # ----------------------------------------------

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    dated.to_parquet(
        OUTPUT_PARQUET,
        engine="pyarrow",
        compression="zstd",
        index=False,
    )

    dated.to_csv(
        OUTPUT_CSV,
        index=False,
    )

    print("\n" + "=" * 60)

    print(
        "CORPORATE-ACTION BUILD COMPLETE"
    )

    print("=" * 60)

    print(
        f"Rows                : "
        f"{len(dated):,}"
    )

    print(
        f"Duplicate rows removed: "
        f"{removed:,}"
    )

    print(
        f"Earliest ex-date    : "
        f"{dated['ex_date'].min()}"
    )

    print(
        f"Latest ex-date      : "
        f"{dated['ex_date'].max()}"
    )

    print(
        f"Unique symbols      : "
        f"{dated['symbol'].nunique():,}"
    )

    print(
        f"Missing record dates: "
        f"{dated['record_date'].isna().sum():,}"
    )

    print(
        f"Missing face values : "
        f"{dated['face_value'].isna().sum():,}"
    )

    print(
        f"\nParquet:\n"
        f"{OUTPUT_PARQUET.resolve()}"
    )


# ============================================================
# BASIC AUDIT
# ============================================================

def audit():

    df = pd.read_parquet(
        OUTPUT_PARQUET
    )

    print(
        "\n=== MOST COMMON PURPOSES ==="
    )

    print(
        df["purpose"]
        .value_counts()
        .head(40)
        .to_string()
    )

    print(
        "\n=== ACTIONS BY YEAR ==="
    )

    yearly = (
        df.assign(
            year=df[
                "ex_date"
            ].dt.year
        )
        .groupby(
            "year"
        )
        .size()
    )

    print(
        yearly.to_string()
    )

    print(
        "\n=== SAMPLE ==="
    )

    print(
        df[
            [
                "symbol",
                "purpose",
                "ex_date",
                "record_date",
                "face_value",
            ]
        ]
        .head(25)
        .to_string(
            index=False
        )
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    download_all()

    build_parquet()

    audit()