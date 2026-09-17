from __future__ import annotations

import io
import time
import zipfile
from datetime import date
from pathlib import Path
from brindco_momentum.paths import ROOT

import requests


# ============================================================
# SPECIAL WEEKEND / HOLIDAY TRADING SESSIONS
#
# These dates exist in the NIFTY 500 TRI series but were missed
# by the original downloader because it skipped Saturdays and
# Sundays.
# ============================================================

SPECIAL_DATES = [
    date(2013, 5, 11),
    date(2013, 11, 3),
    date(2014, 3, 22),
    date(2015, 2, 28),
    date(2016, 10, 30),
    date(2019, 10, 27),
    date(2020, 2, 1),
    date(2020, 11, 14),
    date(2023, 11, 12),
    date(2024, 1, 20),
    date(2024, 3, 2),
    date(2024, 5, 18),
    date(2025, 2, 1),
    date(2026, 2, 1),
]


# NSE switched to UDiFF bhavcopy format from 8 July 2024.
UDIFF_START = date(2024, 7, 8)


# ============================================================
# PATHS
# ============================================================

LEGACY_DIR = ROOT / Path("data/raw/bhavcopy_legacy"
)

UDIFF_DIR = ROOT / Path("data/raw/bhavcopy_udiff"
)


LEGACY_BASE = (
    "https://nsearchives.nseindia.com/"
    "content/historical/EQUITIES"
)

UDIFF_BASE = (
    "https://nsearchives.nseindia.com/content/cm"
)


# ============================================================
# LEGACY URL / FILENAME
# ============================================================

def legacy_filename(d: date) -> str:
    """
    Example:
        2019-10-27
            ->
        cm27OCT2019bhav.csv.zip

    NSE legacy archive requires uppercase month codes.
    """

    mon = d.strftime("%b").upper()

    return (
        f"cm"
        f"{d.day:02d}"
        f"{mon}"
        f"{d.year}"
        f"bhav.csv.zip"
    )


def legacy_url(d: date) -> str:
    """
    Example:

    https://nsearchives.nseindia.com/
    content/historical/EQUITIES/
    2019/OCT/cm27OCT2019bhav.csv.zip
    """

    mon = d.strftime("%b").upper()

    return (
        f"{LEGACY_BASE}/"
        f"{d.year}/"
        f"{mon}/"
        f"{legacy_filename(d)}"
    )


# ============================================================
# UDIFF URL / FILENAME
# ============================================================

def udiff_filename(d: date) -> str:

    return (
        "BhavCopy_NSE_CM_0_0_0_"
        f"{d:%Y%m%d}"
        "_F_0000.csv.zip"
    )


def udiff_url(d: date) -> str:

    return (
        f"{UDIFF_BASE}/"
        f"{udiff_filename(d)}"
    )


# ============================================================
# ZIP VALIDATION
# ============================================================

def validate_zip(
    content: bytes,
) -> tuple[int, list[str]]:
    """
    Basic integrity validation.

    Returns
    -------
    number of CSV files,
    list of archive members
    """

    if not content.startswith(b"PK"):
        raise ValueError(
            "Response does not begin with ZIP signature"
        )

    buffer = io.BytesIO(content)

    if not zipfile.is_zipfile(buffer):
        raise ValueError(
            "Downloaded content is not a valid ZIP"
        )

    buffer.seek(0)

    with zipfile.ZipFile(buffer) as zf:

        bad_member = zf.testzip()

        if bad_member is not None:
            raise ValueError(
                f"Corrupt ZIP member: {bad_member}"
            )

        members = zf.namelist()

        csv_members = [
            name
            for name in members
            if name.lower().endswith(".csv")
        ]

        if not csv_members:
            raise ValueError(
                "ZIP contains no CSV file"
            )

    return len(csv_members), members


# ============================================================
# VALIDATE EXISTING FILE
# ============================================================

def existing_file_is_valid(
    path: Path,
) -> bool:

    try:

        content = path.read_bytes()

        validate_zip(
            content
        )

        return True

    except Exception:
        return False


# ============================================================
# SESSION
# ============================================================

def make_session() -> requests.Session:

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152.0.0.0 "
            "Safari/537.36"
        ),
        "Accept": (
            "application/zip,"
            "application/octet-stream,"
            "*/*"
        ),
        "Accept-Language": (
            "en-US,en;q=0.9"
        ),
        "Connection": "keep-alive",
    })

    return session


# ============================================================
# DOWNLOAD ONE DATE
# ============================================================

def download_date(
    session: requests.Session,
    d: date,
) -> str:

    # --------------------------------------------------------
    # Choose correct NSE format.
    # --------------------------------------------------------

    if d < UDIFF_START:

        filename = legacy_filename(d)

        url = legacy_url(d)

        destination = (
            LEGACY_DIR / filename
        )

        source_format = "LEGACY"

    else:

        filename = udiff_filename(d)

        url = udiff_url(d)

        destination = (
            UDIFF_DIR / filename
        )

        source_format = "UDIFF"

    # --------------------------------------------------------
    # Existing file?
    # --------------------------------------------------------

    if destination.exists():

        if existing_file_is_valid(
            destination
        ):

            print(
                f"[SKIP] "
                f"{d} "
                f"{source_format:6s} "
                f"{destination.name}"
            )

            return "SKIPPED"

        else:

            print(
                f"[BAD ] "
                f"{d} existing file invalid; "
                f"redownloading"
            )

            destination.unlink()

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    try:

        response = session.get(
            url,
            timeout=30,
        )

        if response.status_code == 404:

            print(
                f"[404 ] "
                f"{d} "
                f"{source_format:6s}\n"
                f"       {url}"
            )

            return "MISSING"

        response.raise_for_status()

        content = response.content

        csv_count, members = (
            validate_zip(
                content
            )
        )

        # ----------------------------------------------------
        # Atomic write
        # ----------------------------------------------------

        temp_path = (
            destination.with_suffix(
                destination.suffix
                + ".part"
            )
        )

        temp_path.write_bytes(
            content
        )

        temp_path.replace(
            destination
        )

        print(
            f"[ OK ] "
            f"{d} "
            f"{source_format:6s} "
            f"{len(content) / 1024:8.1f} KB "
            f"{destination.name}"
        )

        return "DOWNLOADED"

    except Exception as exc:

        print(
            f"[ERR ] "
            f"{d} "
            f"{source_format:6s}: "
            f"{exc}"
        )

        return "ERROR"


# ============================================================
# MAIN
# ============================================================

def main():

    LEGACY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    UDIFF_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = make_session()

    stats = {
        "DOWNLOADED": 0,
        "SKIPPED": 0,
        "MISSING": 0,
        "ERROR": 0,
    }

    print(
        "\nDownloading special NSE trading sessions...\n"
    )

    for d in SPECIAL_DATES:

        result = download_date(
            session,
            d,
        )

        stats[result] += 1

        time.sleep(
            0.25
        )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "SPECIAL SESSION PATCH COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"Downloaded : "
        f"{stats['DOWNLOADED']}"
    )

    print(
        f"Skipped    : "
        f"{stats['SKIPPED']}"
    )

    print(
        f"Missing    : "
        f"{stats['MISSING']}"
    )

    print(
        f"Errors     : "
        f"{stats['ERROR']}"
    )

    print(
        "\nLegacy directory:"
    )

    print(
        LEGACY_DIR.resolve()
    )

    print(
        "\nUDiFF directory:"
    )

    print(
        UDIFF_DIR.resolve()
    )

    if (
        stats["MISSING"] > 0
        or
        stats["ERROR"] > 0
    ):

        print(
            "\nWARNING: Some special sessions "
            "still need investigation."
        )

    else:

        print(
            "\nAll special trading-session "
            "bhavcopies are present."
        )


if __name__ == "__main__":
    main()