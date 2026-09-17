"""Verified development-period NSE capital-market settlement business days.

Annual capital-market circulars define the weekday closures. Later dated
capital-market amendments override the annual list, never the trading calendar.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from brindco_momentum.data.acquire_settlement_notices import NOTICE_IDS, OUT as EVIDENCE


from brindco_momentum.paths import ROOT
START = pd.Timestamp("2015-04-01")
CUTOFF = pd.Timestamp("2023-03-31")
SOURCE_DATES = {
    2015: "2014-12-26", 2016: "2015-12-23", 2017: "2016-12-16",
    2018: "2017-12-29", 2019: "2018-12-28", 2020: "2019-12-20",
    2021: "2020-12-18", 2022: "2021-12-15", 2023: "2022-12-16",
}
AMENDMENTS = {
    date(2017, 2, 21): ("CMPT34182", "2017-02-15", "Municipal corporation elections; no settlement"),
    date(2018, 4, 2): ("CMPT37310", "2018-03-26", "Annual bank closing; no settlement"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def notice_holidays() -> dict[date, tuple[str, str, str]]:
    holidays = {}
    for year, notice in NOTICE_IDS.items():
        path = EVIDENCE / f"{notice}.pdf"
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        if f"Settlement Holidays for the Calendar Year {year}" not in text:
            raise ValueError(f"Unexpected notice title in {path}")
        # The annual PDF has a separate weekend table. Both tables are parsed;
        # weekend closures are already implied by the business-day convention.
        for match in re.finditer(r"(?m)^\s*\d+\s+(\d{2}-[A-Za-z]{3}-\d{2})\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+([^\n]+)", text):
            day = pd.to_datetime(match.group(1), format="%d-%b-%y").date()
            if day.year != year or day.strftime("%A") != match.group(2):
                raise ValueError(f"Holiday date/day mismatch: {notice} {match.group(0)}")
            if day in holidays:
                raise ValueError(f"Duplicate holiday {day}")
            holidays[day] = (notice, SOURCE_DATES[year], match.group(3).strip())
        if sum(day.year == year and day.weekday() < 5 for day in holidays) < 15:
            raise ValueError(f"Incomplete holiday table: {notice}")
    for day, (notice, source_date, description) in AMENDMENTS.items():
        text = "\n".join(page.extract_text() or "" for page in PdfReader(EVIDENCE / f"{notice}.pdf").pages)
        if "no settlement" not in text.lower() or not re.search(
            day.strftime("%B %d,") + r"\s*" + str(day.year), text
        ):
            raise ValueError(f"Unverified amendment {notice}")
        holidays[day] = (notice, source_date, description)
    return holidays


def build_calendar(end: pd.Timestamp = CUTOFF) -> pd.DataFrame:
    holidays = notice_holidays()
    rows = []
    for day in pd.date_range(START, end):
        annual_notice = NOTICE_IDS[day.year]
        notice, source_date, description = holidays.get(
            day.date(), (annual_notice, SOURCE_DATES[day.year], ""))
        is_business = day.weekday() < 5 and day.date() not in holidays
        rows.append({
            "date": day, "settlement_business_day": is_business,
            "source_notice": notice, "source_date": pd.Timestamp(source_date),
            "notes": description or ("Weekend" if day.weekday() >= 5 else "Business day under annual notice"),
        })
    return pd.DataFrame(rows)


def freeze_calendar() -> dict[str, object]:
    calendar = build_calendar()
    trading = pd.read_parquet(
        ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet",
        columns=["date"], filters=[("date", ">=", START), ("date", "<=", CUTOFF)],
    )
    trading_dates = set(pd.to_datetime(trading.date).dt.date)
    settlement_dates = set(calendar.loc[calendar.settlement_business_day, "date"].dt.date)
    nonsettling_trade_dates = sorted(trading_dates - settlement_dates)
    manifest = []
    for path in sorted(EVIDENCE.glob("*.pdf")):
        notice = path.stem
        source_date = next((SOURCE_DATES[y] for y, ref in NOTICE_IDS.items() if ref == notice),
                           next((row[1] for row in AMENDMENTS.values() if row[0] == notice), None))
        manifest.append({"notice": notice, "source_date": source_date,
                         "url": f"https://archives.nseindia.com/content/circulars/{path.name}",
                         "local_evidence": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)})
    output = ROOT / "data/processed/nse_settlement_calendar_2015_2023.parquet"
    calendar.to_parquet(output, index=False)
    pd.DataFrame(manifest).to_csv(EVIDENCE / "source_manifest.csv", index=False)
    return {"rows": len(calendar), "business_days": len(settlement_dates),
            "weekday_holidays": int(((calendar.date.dt.dayofweek < 5) & ~calendar.settlement_business_day).sum()),
            "trading_but_not_settlement_dates": nonsettling_trade_dates,
            "maximum_market_date_read": max(trading_dates)}


if __name__ == "__main__":
    print(freeze_calendar())
