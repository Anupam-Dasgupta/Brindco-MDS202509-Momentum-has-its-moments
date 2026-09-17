from __future__ import annotations

import argparse
import hashlib
import html
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import pdfplumber


from brindco_momentum.paths import ROOT
RAW = ROOT / "data" / "raw" / "membership_official"
NOTICES = RAW / "notices"
MONTHLY = RAW / "monthly"
LEDGERS = RAW / "ledgers"
SNAPSHOTS = RAW / "snapshots"
OUTPUT = ROOT / "data" / "processed" / "membership_official"
AUDIT = ROOT / "results" / "membership_rebuild_audit"
IDENTITY_RAW = ROOT / "data" / "raw" / "security_identity"
IDENTITY_OUTPUT = ROOT / "data" / "processed" / "security_identity_official"
CORPORATE_ACTION_OUTPUT = ROOT / "data" / "processed" / "corporate_actions_official"
MANUAL = ROOT / "data" / "manual"
MARKET_PATH = ROOT / "data" / "processed" / "nse_cm_2013_2026.parquet"
OLD_MEMBERSHIP_PATH = (
    ROOT / "data" / "processed" / "membership_audit" / "nifty500_membership_intervals.parquet"
)
CORPORATE_ACTION_PATH = (
    ROOT
    / "data"
    / "processed"
    / "corporate_actions"
    / "nse_corporate_actions_classified.parquet"
)
SERIES_REFERENCE = ROOT / "data" / "raw" / "series_reference" / "legend_of_series.html"

PRESS_ARCHIVE_URL = "https://niftyindices.com/press-release"
MONTHLY_URL = (
    "https://niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/"
    "indices_data{month}.zip"
)
LEDGER_URL = "https://archives.nseindia.com/content/indices/IndexInclExcl.xls"
SEED_MONTH = "Aug2014"
START_DATE = pd.Timestamp("2014-08-28")
CUTOFF = pd.Timestamp("2023-03-31")

DATE_TEXT = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|December)[,]?\s+\d{4}"
)


@dataclass
class NoticeParse:
    rows: list[dict[str, object]]
    publication_date: pd.Timestamp | pd.NaT
    effective_dates: list[pd.Timestamp]
    text_contains_base_index: bool
    error: str = ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def normalize_name(value: object) -> str:
    text = clean_cell(value).upper().replace("&", " AND ")
    text = re.sub(r"\b(LIMITED|LTD|COMPANY|CO|THE)\b", " ", text)
    return re.sub(r"[^A-Z0-9]+", "", text)


def normalize_symbol(value: object) -> str:
    return clean_cell(value).upper()


def parse_date(value: object) -> pd.Timestamp | pd.NaT:
    if value is None or clean_cell(value) == "":
        return pd.NaT
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", clean_cell(value), flags=re.I)
    parsed = pd.to_datetime(text, format="mixed", dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    return pd.Timestamp(parsed).normalize()


def archive_entries() -> pd.DataFrame:
    path = RAW / "press_release_archive.html"
    source = path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(
        r'<div class="pressItem" data-date="([^"]+)"[^>]*>.*?'
        r'<a href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        flags=re.I | re.S,
    )
    rows = []
    for date_text, href, title in pattern.findall(source):
        publication_date = parse_date(date_text)
        title = html.unescape(re.sub(r"<.*?>", "", title)).strip()
        rows.append(
            {
                "publication_date": publication_date,
                "source_url": urljoin(PRESS_ARCHIVE_URL, href),
                "title": title,
                "filename": Path(urlparse(href).path).name,
            }
        )
    return pd.DataFrame(rows).drop_duplicates(["filename"], keep="first")


def extract_snapshot_pdfs() -> list[Path]:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    extracted = []
    pattern = re.compile(r"(?:cnx500|nifty_?500)_[A-Za-z]{3}\d{4}\.pdf$", re.I)
    for archive in sorted(MONTHLY.glob("indices_data*.zip")):
        with zipfile.ZipFile(archive) as zipped:
            candidates = [name for name in zipped.namelist() if pattern.search(name)]
            if len(candidates) > 1:
                raise ValueError(f"Multiple NIFTY 500 PDFs in {archive}: {candidates}")
            if not candidates:
                continue
            member = candidates[0]
            destination = SNAPSHOTS / Path(member).name
            content = zipped.read(member)
            if destination.exists() and destination.read_bytes() != content:
                raise ValueError(f"Extracted snapshot changed: {destination}")
            destination.write_bytes(content)
            extracted.append(destination)
    return extracted


def parse_snapshot(path: Path) -> tuple[pd.Timestamp, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    with pdfplumber.open(path) as document:
        first_text = document.pages[0].extract_text() or ""
        dates = [parse_date(value) for value in re.findall(DATE_TEXT, first_text, flags=re.I)]
        dates = [value for value in dates if pd.notna(value)]
        if not dates:
            raise ValueError(f"No as-of date found in {path.name}")
        as_of_date = dates[0]
        for page_number, page in enumerate(document.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                header = [clean_cell(value).lower() for value in table[0]]
                if "symbol" not in header or not any("security name" in value for value in header):
                    continue
                symbol_index = header.index("symbol")
                name_index = next(i for i, value in enumerate(header) if "security name" in value)
                industry_index = next(
                    (i for i, value in enumerate(header) if "industry" in value), None
                )
                for raw in table[1:]:
                    symbol = normalize_symbol(raw[symbol_index])
                    security_name = clean_cell(raw[name_index])
                    if not symbol or not security_name:
                        continue
                    rows.append(
                        {
                            "as_of_date": as_of_date,
                            "symbol": symbol,
                            "security_name": security_name,
                            "industry": (
                                clean_cell(raw[industry_index])
                                if industry_index is not None and industry_index < len(raw)
                                else ""
                            ),
                            "source_file": path.name,
                            "source_page": page_number,
                        }
                    )
    frame = pd.DataFrame(rows).drop_duplicates(["symbol"])
    return as_of_date, frame.sort_values("symbol").reset_index(drop=True)


def update_notice_state(
    text: str, is_base_index: bool, action: str | None
) -> tuple[bool, str | None]:
    for raw_line in text.splitlines():
        line = clean_cell(raw_line)
        if not line:
            continue
        heading = re.match(
            r"^\s*(?:\(?[A-Za-z0-9]+\)?\s*[.)]?\s*)?((?:CNX|NIFTY)\s*[^:]{0,70}?)\s*:?$",
            line,
            flags=re.I,
        )
        if heading and len(line) < 100:
            index_name = re.sub(r"\s+", " ", heading.group(1)).strip()
            base = bool(
                re.fullmatch(r"(?:CNX|NIFTY)\s*500(?:\s+INDEX)?", index_name, re.I)
            )
            if base or re.match(r"^(?:CNX|NIFTY)\b", index_name, re.I):
                is_base_index = base
                action = None
        lower = line.lower()
        if "being excluded" in lower or "will be excluded" in lower:
            action = "EXCLUDE"
        elif "being included" in lower or "will be included" in lower:
            action = "INCLUDE"
    return is_base_index, action


def table_company_rows(table: list[list[object]]) -> list[tuple[str, str]]:
    if not table:
        return []
    header = [clean_cell(value).lower() for value in table[0]]
    symbol_index = next((i for i, value in enumerate(header) if "symbol" in value), None)
    company_index = next(
        (i for i, value in enumerate(header) if "company" in value or "scrip name" in value),
        None,
    )
    if symbol_index is None or company_index is None:
        return []
    rows = []
    for raw in table[1:]:
        if max(symbol_index, company_index) >= len(raw):
            continue
        symbol = normalize_symbol(raw[symbol_index])
        company = clean_cell(raw[company_index])
        if not symbol or not company or symbol.lower() == "symbol":
            continue
        if not re.fullmatch(r"[A-Z0-9&.-]{1,40}", symbol):
            continue
        rows.append((company, symbol))
    return rows


def text_company_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    is_base_index = False
    action: str | None = None
    pending_company = ""
    for raw_line in text.splitlines():
        line = clean_cell(raw_line)
        if not line:
            continue
        previous_base = is_base_index
        is_base_index, updated_action = update_notice_state(line, is_base_index, action)
        if is_base_index != previous_base:
            pending_company = ""
        if updated_action != action:
            pending_company = ""
        action = updated_action
        if not is_base_index or not action:
            continue
        if re.search(r"^(?:sr\.?|scrip name|company name|no\.?)\b", line, re.I):
            continue
        if re.fullmatch(r"\d{1,2}", line):
            continue
        match = re.match(
            r"^\s*\d+\s+(.+?)\s+([A-Z0-9][A-Z0-9&.-]{0,39})\s*$", line
        )
        if match:
            company = clean_cell(match.group(1))
            symbol = normalize_symbol(match.group(2))
            if pending_company and len(company) < 18:
                company = clean_cell(f"{pending_company} {company}")
            if re.fullmatch(r"[A-Z0-9&.-]{1,40}", symbol):
                rows.append(
                    {"action": action, "company_name": company, "symbol": symbol}
                )
            pending_company = ""
            continue
        lower = line.lower()
        if (
            len(line) < 120
            and not line.startswith("(")
            and "following" not in lower
            and "effective" not in lower
            and "index" not in lower
            and "replacement" not in lower
        ):
            pending_company = line
    return rows


def notice_effective_dates(text: str, title: str) -> list[pd.Timestamp]:
    contexts = []
    combined = f"{title}\n{text}"
    for match in re.finditer(r"(?:effective|w\.?e\.?f\.?|wef)", combined, flags=re.I):
        contexts.append(combined[match.end() : match.end() + 180])
    dates = []
    for context in contexts:
        found = re.search(DATE_TEXT, context, flags=re.I)
        if found:
            parsed = parse_date(found.group(0))
            if pd.notna(parsed) and START_DATE < parsed <= CUTOFF:
                dates.append(parsed)
    return sorted(set(dates))


def parse_notice(path: Path, archive: pd.DataFrame) -> NoticeParse:
    metadata = archive[archive["filename"].eq(path.name)]
    publication_date = (
        metadata.iloc[0]["publication_date"] if not metadata.empty else parse_date(path.stem[-8:])
    )
    title = metadata.iloc[0]["title"] if not metadata.empty else ""
    parsed_rows: list[dict[str, object]] = []
    full_text = []
    try:
        with pdfplumber.open(path) as document:
            is_base_index = False
            action: str | None = None
            for page_number, page in enumerate(document.pages, start=1):
                full_text.append(page.extract_text() or "")
                tables = sorted(page.find_tables(), key=lambda item: item.bbox[1])
                cursor = 0.0
                for table_number, found in enumerate(tables, start=1):
                    table_top = max(0.0, found.bbox[1])
                    prefix = ""
                    if table_top > cursor:
                        prefix = (
                            page.crop((0, cursor, page.width, table_top)).extract_text()
                            or ""
                        )
                    is_base_index, action = update_notice_state(prefix, is_base_index, action)
                    if is_base_index and action:
                        for company_name, symbol in table_company_rows(found.extract()):
                            parsed_rows.append(
                                {
                                    "action": action,
                                    "company_name": company_name,
                                    "symbol": symbol,
                                    "source_file": path.name,
                                    "source_page": page_number,
                                    "source_table": table_number,
                                }
                            )
                    cursor = max(cursor, min(page.height, found.bbox[3]))
                suffix = ""
                if cursor < page.height:
                    suffix = (
                        page.crop((0, cursor, page.width, page.height)).extract_text()
                        or ""
                    )
                is_base_index, action = update_notice_state(suffix, is_base_index, action)
    except Exception as exc:
        return NoticeParse([], publication_date, [], False, str(exc))

    text = "\n".join(full_text)
    contains = bool(re.search(r"(?:CNX|NIFTY)\s*500(?:\s+Index)?", text, flags=re.I))
    parsed_rows.extend(
        {
            **row,
            "source_file": path.name,
            "source_page": pd.NA,
            "source_table": pd.NA,
        }
        for row in text_company_rows(text)
    )
    rows = pd.DataFrame(parsed_rows)
    if not rows.empty:
        rows["company_name_length"] = rows["company_name"].str.len()
        rows = rows.sort_values("company_name_length", ascending=False).drop_duplicates(
            ["action", "symbol"]
        )
        rows = rows.drop(columns="company_name_length").to_dict("records")
    return NoticeParse(
        rows=rows,
        publication_date=publication_date,
        effective_dates=notice_effective_dates(text, title),
        text_contains_base_index=contains,
    )


def read_official_ledger() -> pd.DataFrame:
    ledger = pd.read_excel(LEDGERS / "IndexInclExcl.xls", sheet_name="Nifty 500")
    ledger = ledger.rename(
        columns={
            "Event Date": "effective_date",
            "Scrip Name": "company_name",
            "Description": "description",
        }
    )
    ledger["effective_date"] = pd.to_datetime(
        ledger["effective_date"], format="mixed", dayfirst=True, errors="coerce"
    ).dt.normalize()
    ledger["action"] = ledger["description"].map(
        {"Inclusion into Index": "INCLUDE", "Exclusion from Index": "EXCLUDE"}
    )
    ledger = ledger[
        ledger["effective_date"].between(START_DATE + pd.Timedelta(days=1), CUTOFF)
        & ledger["action"].notna()
    ].copy()
    ledger["company_name_normalized"] = ledger["company_name"].map(normalize_name)
    return ledger[
        ["effective_date", "action", "company_name", "company_name_normalized"]
    ].reset_index(drop=True)


def parse_all_notices() -> tuple[pd.DataFrame, pd.DataFrame]:
    archive = archive_entries()
    event_rows = []
    status_rows = []
    for path in sorted(NOTICES.glob("*.pdf")):
        parsed = parse_notice(path, archive)
        effective_date = parsed.effective_dates[0] if len(parsed.effective_dates) == 1 else pd.NaT
        for row in parsed.rows:
            event_rows.append(
                {
                    **row,
                    "publication_date": parsed.publication_date,
                    "effective_date": effective_date,
                    "effective_date_candidates": ";".join(
                        value.date().isoformat() for value in parsed.effective_dates
                    ),
                    "company_name_normalized": normalize_name(row["company_name"]),
                    "source_url": (
                        archive.loc[archive["filename"].eq(path.name), "source_url"].iloc[0]
                        if archive["filename"].eq(path.name).any()
                        else ""
                    ),
                }
            )
        status_rows.append(
            {
                "source_file": path.name,
                "publication_date": parsed.publication_date,
                "effective_date_candidates": ";".join(
                    value.date().isoformat() for value in parsed.effective_dates
                ),
                "contains_nifty500_text": parsed.text_contains_base_index,
                "parsed_event_rows": len(parsed.rows),
                "parse_error": parsed.error,
            }
        )
    events = pd.DataFrame(event_rows)
    statuses = pd.DataFrame(status_rows)
    return events, statuses


def match_notice_events_to_ledger(
    notice_events: pd.DataFrame, ledger: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    matched_rows = []
    unmatched_rows = []
    for row in ledger.itertuples(index=False):
        date_text = row.effective_date.date().isoformat()
        candidates = notice_events[
            notice_events["action"].eq(row.action)
            & notice_events["company_name_normalized"].eq(row.company_name_normalized)
            & notice_events["effective_date_candidates"].fillna("").str.split(";").map(
                lambda values: date_text in values
            )
        ]
        symbols = sorted(candidates["symbol"].dropna().unique())
        if len(symbols) == 1:
            candidate = candidates.sort_values("publication_date").iloc[-1]
            matched_rows.append(
                {
                    "effective_date": row.effective_date,
                    "action": row.action,
                    "company_name": row.company_name,
                    "company_name_normalized": row.company_name_normalized,
                    "symbol": symbols[0],
                    "source_file": candidate["source_file"],
                    "source_url": candidate["source_url"],
                    "publication_date": candidate["publication_date"],
                    "match_method": "OFFICIAL_DATE_NAME",
                }
            )
        else:
            unmatched_rows.append(
                {
                    "effective_date": row.effective_date,
                    "action": row.action,
                    "company_name": row.company_name,
                    "company_name_normalized": row.company_name_normalized,
                    "candidate_symbols": ";".join(symbols),
                }
            )
    return pd.DataFrame(matched_rows), pd.DataFrame(unmatched_rows)


def load_reviewed_overrides() -> pd.DataFrame:
    path = MANUAL / "membership_official_event_overrides.csv"
    overrides = pd.read_csv(path)
    overrides["effective_date"] = pd.to_datetime(overrides["effective_date"]).dt.normalize()
    overrides["publication_date"] = pd.to_datetime(overrides["publication_date"]).dt.normalize()
    overrides["company_name_normalized"] = overrides["company_name"].map(normalize_name)
    overrides["match_method"] = "MANUALLY_VERIFIED_OFFICIAL_NOTICE"
    for source_file in overrides["source_file"]:
        if not (NOTICES / source_file).exists():
            raise FileNotFoundError(f"Missing override evidence: {source_file}")
    return overrides


def build_authoritative_events(
    notice_events: pd.DataFrame,
    ledger: pd.DataFrame,
    matched: pd.DataFrame,
    unmatched: pd.DataFrame,
) -> pd.DataFrame:
    overrides = load_reviewed_overrides()
    ledger_overrides = overrides[overrides["override_scope"].eq("LEDGER_MATCH")]
    dated_notice_overrides = overrides[
        overrides["override_scope"].eq("NOTICE_EFFECTIVE_DATE")
    ]
    unresolved = unmatched.merge(
        ledger_overrides[["effective_date", "action", "company_name_normalized"]],
        on=["effective_date", "action", "company_name_normalized"],
        how="left",
        indicator=True,
    )
    unresolved = unresolved[unresolved["_merge"].eq("left_only")]
    if not unresolved.empty:
        raise ValueError("Official ledger rows remain without a notice-backed symbol")

    ledger_events = pd.concat(
        [
            matched,
            ledger_overrides[
                [
                    "effective_date",
                    "action",
                    "company_name",
                    "company_name_normalized",
                    "symbol",
                    "source_file",
                    "source_url",
                    "publication_date",
                    "match_method",
                ]
            ],
        ],
        ignore_index=True,
    )
    if len(ledger_events) != len(ledger):
        raise ValueError(
            f"Official ledger coverage is {len(ledger_events)} of {len(ledger)} rows"
        )
    ledger_events = ledger_events.sort_values("publication_date").drop_duplicates(
        ["effective_date", "action", "symbol"], keep="last"
    )

    ledger_end = ledger["effective_date"].max()
    later_events = notice_events[
        notice_events["effective_date"].notna()
        & notice_events["effective_date"].gt(ledger_end)
        & notice_events["effective_date"].le(CUTOFF)
    ].copy()
    later_events["match_method"] = "OFFICIAL_NOTICE"
    later_events = later_events[
        [
            "effective_date",
            "action",
            "company_name",
            "company_name_normalized",
            "symbol",
            "source_file",
            "source_url",
            "publication_date",
            "match_method",
        ]
    ]
    dated_notice_overrides = dated_notice_overrides[
        [
            "effective_date",
            "action",
            "company_name",
            "company_name_normalized",
            "symbol",
            "source_file",
            "source_url",
            "publication_date",
            "match_method",
        ]
    ]
    later_events = pd.concat(
        [later_events, dated_notice_overrides], ignore_index=True
    )
    later_events = later_events.sort_values("publication_date").drop_duplicates(
        ["effective_date", "action", "symbol"], keep="last"
    )

    events = pd.concat([ledger_events, later_events], ignore_index=True)
    events["effective_date"] = pd.to_datetime(events["effective_date"]).dt.normalize()
    events["publication_date"] = pd.to_datetime(events["publication_date"]).dt.normalize()
    events["symbol"] = events["symbol"].map(normalize_symbol)
    events["source_sha256"] = events["source_file"].map(
        lambda value: sha256(NOTICES / value)
    )
    events["review_status"] = "OFFICIAL_EVIDENCE"
    events.loc[
        events["match_method"].eq("MANUALLY_VERIFIED_OFFICIAL_NOTICE"),
        "review_status",
    ] = "MANUALLY_VERIFIED"
    if events.duplicated(["effective_date", "action", "symbol"]).any():
        raise ValueError("Duplicate authoritative membership event")
    return events.sort_values(
        ["effective_date", "action", "symbol"], ascending=[True, False, True]
    ).reset_index(drop=True)


def find_root(parent: dict[str, str], node: str) -> str:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def join_identity_nodes(
    parent: dict[str, str], left: str, right: str
) -> bool:
    left_root = find_root(parent, left)
    right_root = find_root(parent, right)
    if left_root == right_root:
        return False
    if left_root < right_root:
        parent[right_root] = left_root
    else:
        parent[left_root] = right_root
    return True


def read_market_identity_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    market = pd.read_parquet(
        MARKET_PATH,
        columns=["date", "isin", "symbol", "series"],
        filters=[("date", "<=", CUTOFF)],
    )
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    for column in ["isin", "symbol", "series"]:
        market[column] = market[column].astype("string").str.strip().str.upper()
    market = market[
        market["isin"].notna()
        & market["symbol"].notna()
        & market["isin"].ne("")
        & market["symbol"].ne("")
    ].copy()
    equity_history = market[market["series"].isin(["EQ", "BE", "BZ"])].copy()
    observed = (
        equity_history.groupby(["isin", "symbol"], observed=True)
        .agg(
            first_seen=("date", "min"),
            last_seen=("date", "max"),
            observations=("date", "size"),
            observed_series=("series", lambda values: ";".join(sorted(values.dropna().unique()))),
        )
        .reset_index()
    )
    return market, observed


def build_dated_identity(observed: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    parent = {value: value for value in observed["isin"].unique()}
    edge_rows: list[dict[str, object]] = []

    for symbol, group in observed.groupby("symbol", sort=True):
        ordered = group.sort_values(["first_seen", "last_seen"]).reset_index(drop=True)
        for index in range(1, len(ordered)):
            previous = ordered.iloc[index - 1]
            current = ordered.iloc[index]
            gap = (current["first_seen"] - previous["last_seen"]).days
            if previous["isin"] != current["isin"] and 0 < gap <= 31:
                joined = join_identity_nodes(parent, previous["isin"], current["isin"])
                edge_rows.append(
                    {
                        "left_isin": previous["isin"],
                        "right_isin": current["isin"],
                        "old_symbol": symbol,
                        "new_symbol": symbol,
                        "effective_date": current["first_seen"],
                        "evidence": "CONTIGUOUS_SAME_SYMBOL_ISIN_TRANSITION",
                        "joined": joined,
                    }
                )

    changes = pd.read_csv(
        IDENTITY_RAW / "symbolchange.csv",
        header=None,
        names=["company_name", "old_symbol", "new_symbol", "effective_date"],
    )
    changes["effective_date"] = pd.to_datetime(
        changes["effective_date"], format="%d-%b-%Y", errors="coerce"
    ).dt.normalize()
    changes["old_symbol"] = changes["old_symbol"].map(normalize_symbol)
    changes["new_symbol"] = changes["new_symbol"].map(normalize_symbol)
    changes = changes[
        changes["effective_date"].notna()
        & changes["effective_date"].le(CUTOFF)
        & changes["old_symbol"].ne("")
        & changes["new_symbol"].ne("")
    ]
    by_symbol = {symbol: frame.copy() for symbol, frame in observed.groupby("symbol")}
    for change in changes.itertuples(index=False):
        old_rows = by_symbol.get(change.old_symbol)
        new_rows = by_symbol.get(change.new_symbol)
        if old_rows is None or new_rows is None:
            continue
        old_candidates = old_rows[
            old_rows["last_seen"].between(
                change.effective_date - pd.Timedelta(days=366),
                change.effective_date + pd.Timedelta(days=7),
            )
        ].sort_values("last_seen", ascending=False)
        new_candidates = new_rows[
            new_rows["first_seen"].between(
                change.effective_date - pd.Timedelta(days=7),
                change.effective_date + pd.Timedelta(days=366),
            )
        ].sort_values("first_seen")
        if old_candidates.empty or new_candidates.empty:
            continue
        old_isin = old_candidates.iloc[0]["isin"]
        new_isin = new_candidates.iloc[0]["isin"]
        joined = join_identity_nodes(parent, old_isin, new_isin)
        edge_rows.append(
            {
                "left_isin": old_isin,
                "right_isin": new_isin,
                "old_symbol": change.old_symbol,
                "new_symbol": change.new_symbol,
                "effective_date": change.effective_date,
                "evidence": "OFFICIAL_SYMBOL_CHANGE",
                "joined": joined,
            }
        )

    groups: dict[str, list[str]] = defaultdict(list)
    for isin in parent:
        groups[find_root(parent, isin)].append(isin)
    security_ids = {}
    for isins in groups.values():
        digest = hashlib.sha1("|".join(sorted(isins)).encode()).hexdigest()[:12].upper()
        security_id = f"NSE_{digest}"
        for isin in isins:
            security_ids[isin] = security_id

    dated = observed.copy()
    dated["security_id"] = dated["isin"].map(security_ids)
    dated = dated.sort_values(["security_id", "first_seen", "symbol", "isin"])
    summary_rows = []
    for security_id, group in dated.groupby("security_id", sort=True):
        most_recent = group.sort_values(
            ["last_seen", "first_seen", "observations"], ascending=[False, False, False]
        ).iloc[0]
        summary_rows.append(
            {
                "security_id": security_id,
                "canonical_symbol": most_recent["symbol"],
                "first_seen": group["first_seen"].min(),
                "last_seen": group["last_seen"].max(),
                "isins": ";".join(sorted(group["isin"].unique())),
                "aliases": ";".join(sorted(group["symbol"].unique())),
                "observations": int(group["observations"].sum()),
            }
        )
    edges = pd.DataFrame(edge_rows)
    return dated.reset_index(drop=True), pd.DataFrame(summary_rows), edges


def resolve_symbol(
    symbol: str, date: pd.Timestamp, dated_identity: pd.DataFrame
) -> tuple[str | None, str, int]:
    rows = dated_identity[dated_identity["symbol"].eq(normalize_symbol(symbol))]
    if rows.empty:
        return None, "NO_OBSERVED_SYMBOL", 0
    active = rows[rows["first_seen"].le(date) & rows["last_seen"].ge(date)]
    active_ids = sorted(active["security_id"].unique())
    if len(active_ids) == 1:
        return active_ids[0], "ACTIVE_DATE_MATCH", 1
    if len(active_ids) > 1:
        return None, "AMBIGUOUS_ACTIVE_DATE", len(active_ids)
    all_ids = sorted(rows["security_id"].unique())
    if len(all_ids) == 1:
        return all_ids[0], "UNIQUE_SYMBOL_HISTORY", 1
    return None, "AMBIGUOUS_REUSED_SYMBOL", len(all_ids)


def map_membership_rows(
    frame: pd.DataFrame, date_column: str, dated_identity: pd.DataFrame
) -> pd.DataFrame:
    mapped = []
    for row in frame.to_dict("records"):
        date = pd.Timestamp(row[date_column]).normalize()
        security_id, method, candidates = resolve_symbol(row["symbol"], date, dated_identity)
        mapped.append(
            {
                **row,
                "security_id": security_id,
                "identity_match_method": method,
                "identity_candidate_count": candidates,
            }
        )
    return pd.DataFrame(mapped)


def reconstruct_membership(
    seed: pd.DataFrame,
    events: pd.DataFrame,
    dated_identity: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    mapped_seed = map_membership_rows(seed, "as_of_date", dated_identity)
    mapped_events = map_membership_rows(events, "effective_date", dated_identity)

    identity_issues = pd.concat(
        [
            mapped_seed[mapped_seed["security_id"].isna()].assign(record_type="SEED"),
            mapped_events[mapped_events["security_id"].isna()].assign(record_type="EVENT"),
        ],
        ignore_index=True,
        sort=False,
    )
    if not identity_issues.empty:
        return (
            pd.DataFrame(),
            mapped_seed,
            mapped_events,
            pd.DataFrame(),
            pd.DataFrame(),
            identity_issues,
        )
    if mapped_seed["security_id"].nunique() != 500:
        raise ValueError("Official seed does not map to 500 distinct securities")

    state = set(mapped_seed["security_id"])
    open_intervals = {}
    for row in mapped_seed.itertuples(index=False):
        open_intervals[row.security_id] = {
            "index_id": 221,
            "index_name": "NIFTY 500",
            "security_id": row.security_id,
            "published_symbol": row.symbol,
            "valid_from": row.as_of_date,
            "announced_at": pd.NaT,
            "evidence_file": row.source_file,
            "source_url": MONTHLY_URL.format(month=SEED_MONTH),
            "source_sha256": sha256(MONTHLY / f"indices_data{SEED_MONTH}.zip"),
            "evidence_status": "OFFICIAL_FULL_SNAPSHOT",
        }

    intervals = []
    application_rows = []
    count_rows = [
        {
            "effective_date": START_DATE,
            "exclusions": 0,
            "inclusions": 500,
            "count_before": 0,
            "count_after": 500,
            "application_issues": 0,
            "source": "OFFICIAL_FULL_SNAPSHOT",
        }
    ]
    for effective_date, day_events in mapped_events.groupby("effective_date", sort=True):
        count_before = len(state)
        issues = 0
        exclusions = day_events[day_events["action"].eq("EXCLUDE")]
        inclusions = day_events[day_events["action"].eq("INCLUDE")]
        for row in exclusions.itertuples(index=False):
            status = "APPLIED"
            if row.security_id not in state:
                status = "NOT_PRESENT_BEFORE_EXCLUSION"
                issues += 1
            else:
                interval = open_intervals.pop(row.security_id)
                interval["valid_to"] = effective_date
                intervals.append(interval)
                state.remove(row.security_id)
            application_rows.append(
                {
                    "effective_date": effective_date,
                    "action": row.action,
                    "symbol": row.symbol,
                    "security_id": row.security_id,
                    "application_status": status,
                    "source_file": row.source_file,
                }
            )
        for row in inclusions.itertuples(index=False):
            status = "APPLIED"
            if row.security_id in state:
                status = "ALREADY_PRESENT_BEFORE_INCLUSION"
                issues += 1
            else:
                state.add(row.security_id)
                open_intervals[row.security_id] = {
                    "index_id": 221,
                    "index_name": "NIFTY 500",
                    "security_id": row.security_id,
                    "published_symbol": row.symbol,
                    "valid_from": effective_date,
                    "announced_at": row.publication_date,
                    "evidence_file": row.source_file,
                    "source_url": row.source_url,
                    "source_sha256": row.source_sha256,
                    "evidence_status": row.review_status,
                }
            application_rows.append(
                {
                    "effective_date": effective_date,
                    "action": row.action,
                    "symbol": row.symbol,
                    "security_id": row.security_id,
                    "application_status": status,
                    "source_file": row.source_file,
                }
            )
        count_rows.append(
            {
                "effective_date": effective_date,
                "exclusions": len(exclusions),
                "inclusions": len(inclusions),
                "count_before": count_before,
                "count_after": len(state),
                "application_issues": issues,
                "source": ";".join(sorted(day_events["source_file"].unique())),
            }
        )

    for interval in open_intervals.values():
        interval["valid_to"] = pd.NaT
        intervals.append(interval)
    membership = pd.DataFrame(intervals).sort_values(
        ["security_id", "valid_from"]
    ).reset_index(drop=True)
    applications = pd.DataFrame(application_rows)
    counts = pd.DataFrame(count_rows)
    return membership, mapped_seed, mapped_events, applications, counts, identity_issues


def active_membership_ids(membership: pd.DataFrame, date: pd.Timestamp) -> set[str]:
    active = membership[
        membership["valid_from"].le(date)
        & (membership["valid_to"].isna() | membership["valid_to"].gt(date))
    ]
    return set(active["security_id"])


def validate_snapshots(
    snapshots: pd.DataFrame,
    membership: pd.DataFrame,
    dated_identity: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    discrepancy_rows = []
    for as_of_date, frame in snapshots.groupby("as_of_date", sort=True):
        mapped = map_membership_rows(frame, "as_of_date", dated_identity)
        unresolved = mapped[mapped["security_id"].isna()]
        expected = set(mapped["security_id"].dropna())
        reconstructed = active_membership_ids(membership, as_of_date)
        for security_id in sorted(expected - reconstructed):
            symbol = mapped.loc[mapped["security_id"].eq(security_id), "symbol"].iloc[0]
            discrepancy_rows.append(
                {
                    "as_of_date": as_of_date,
                    "side": "SNAPSHOT_ONLY",
                    "security_id": security_id,
                    "symbol": symbol,
                }
            )
        for security_id in sorted(reconstructed - expected):
            discrepancy_rows.append(
                {
                    "as_of_date": as_of_date,
                    "side": "RECONSTRUCTION_ONLY",
                    "security_id": security_id,
                    "symbol": "",
                }
            )
        summary_rows.append(
            {
                "as_of_date": as_of_date,
                "snapshot_count": len(frame),
                "mapped_snapshot_count": len(expected),
                "reconstructed_count": len(reconstructed),
                "unresolved_snapshot_symbols": len(unresolved),
                "symmetric_difference_count": len(expected ^ reconstructed),
                "source_file": frame["source_file"].iloc[0],
            }
        )
    return pd.DataFrame(summary_rows), pd.DataFrame(discrepancy_rows)


def build_prelisting_audit(
    membership: pd.DataFrame,
    dated_identity: pd.DataFrame,
) -> pd.DataFrame:
    equity = pd.read_csv(IDENTITY_RAW / "EQUITY_L.csv")
    equity.columns = [clean_cell(column).upper() for column in equity.columns]
    equity["ISIN NUMBER"] = equity["ISIN NUMBER"].astype("string").str.strip().str.upper()
    equity["OFFICIAL_LISTING_DATE"] = pd.to_datetime(
        equity["DATE OF LISTING"], format="%d-%b-%Y", errors="coerce"
    ).dt.normalize()
    official_listing = equity.set_index("ISIN NUMBER")["OFFICIAL_LISTING_DATE"].to_dict()

    observations = dated_identity.groupby("security_id").agg(
        first_observed_date=("first_seen", "min"),
        isins=("isin", lambda values: ";".join(sorted(values.unique()))),
    )
    rows = []
    for interval in membership.itertuples(index=False):
        record = observations.loc[interval.security_id]
        dates = [
            official_listing.get(isin)
            for isin in str(record["isins"]).split(";")
            if pd.notna(official_listing.get(isin))
        ]
        listing_date = min(dates) if dates else pd.NaT
        first_observed = record["first_observed_date"]
        if dates and listing_date <= first_observed:
            evidence = "CURRENT_NSE_EQUITY_MASTER"
            reference_date = listing_date
        else:
            evidence = "FIRST_OBSERVED_PRICE_PROXY"
            reference_date = first_observed
        days_before = (reference_date - interval.valid_from).days
        status = "PASS"
        if interval.valid_from < reference_date:
            status = "FAIL_PRELISTING" if dates else "REVIEW_BEFORE_FIRST_OBSERVATION"
        rows.append(
            {
                "security_id": interval.security_id,
                "published_symbol": interval.published_symbol,
                "membership_from": interval.valid_from,
                "membership_to": interval.valid_to,
                "listing_or_first_observed_date": reference_date,
                "date_evidence": evidence,
                "days_membership_precedes_reference": max(days_before, 0),
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def compare_previous_membership(
    membership: pd.DataFrame,
    dated_identity: pd.DataFrame,
    identity_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    previous = pd.read_parquet(
        OLD_MEMBERSHIP_PATH, filters=[("valid_from", "<=", CUTOFF)]
    )
    previous["valid_from"] = pd.to_datetime(previous["valid_from"]).dt.normalize()
    previous["valid_to"] = pd.to_datetime(previous["valid_to"]).dt.normalize()
    canonical = identity_summary.set_index("security_id")["canonical_symbol"].to_dict()
    mapped_previous = []
    for row in previous.to_dict("records"):
        mapping_date = max(pd.Timestamp(row["valid_from"]), START_DATE)
        security_id, method, _ = resolve_symbol(row["symbol"], mapping_date, dated_identity)
        mapped_previous.append(
            {**row, "security_id": security_id, "identity_match_method": method}
        )
    previous = pd.DataFrame(mapped_previous)

    differences = []
    counts = []
    month_end_dates = pd.date_range(START_DATE, CUTOFF, freq="ME").union(
        pd.DatetimeIndex([START_DATE, CUTOFF])
    )
    for date in month_end_dates:
        official_ids = active_membership_ids(membership, date)
        old_active = previous[
            previous["valid_from"].le(date)
            & (previous["valid_to"].isna() | previous["valid_to"].gt(date))
        ]
        old_ids = set(old_active["security_id"].dropna())
        unresolved_old = sorted(old_active.loc[old_active["security_id"].isna(), "symbol"].unique())
        counts.append(
            {
                "as_of_date": date,
                "official_count": len(official_ids),
                "previous_mapped_count": len(old_ids),
                "previous_unmapped_count": len(unresolved_old),
                "symmetric_difference_count": len(official_ids ^ old_ids),
            }
        )

    boundaries = {START_DATE, CUTOFF + pd.Timedelta(days=1)}
    for column in ["valid_from", "valid_to"]:
        boundaries.update(
            value
            for value in membership[column].dropna()
            if START_DATE <= value <= CUTOFF + pd.Timedelta(days=1)
        )
        boundaries.update(
            value
            for value in previous[column].dropna()
            if START_DATE <= value <= CUTOFF + pd.Timedelta(days=1)
        )
    ordered_boundaries = sorted(boundaries)
    for index in range(len(ordered_boundaries) - 1):
        valid_from = ordered_boundaries[index]
        valid_to = ordered_boundaries[index + 1]
        official_ids = active_membership_ids(membership, valid_from)
        old_active = previous[
            previous["valid_from"].le(valid_from)
            & (previous["valid_to"].isna() | previous["valid_to"].gt(valid_from))
        ]
        old_ids = set(old_active["security_id"].dropna())
        old_symbol_by_id = (
            old_active.dropna(subset=["security_id"])
            .drop_duplicates("security_id")
            .set_index("security_id")["symbol"]
            .to_dict()
        )
        for security_id in sorted(official_ids - old_ids):
            differences.append(
                {
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "side": "OFFICIAL_ONLY",
                    "security_id": security_id,
                    "symbol": canonical.get(security_id, ""),
                }
            )
        for security_id in sorted(old_ids - official_ids):
            differences.append(
                {
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "side": "PREVIOUS_ONLY",
                    "security_id": security_id,
                    "symbol": old_symbol_by_id.get(security_id, ""),
                }
            )
        for row in old_active[old_active["security_id"].isna()].itertuples(index=False):
            differences.append(
                {
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "side": "PREVIOUS_UNMAPPED",
                    "security_id": "",
                    "symbol": row.symbol,
                }
            )
    return pd.DataFrame(differences), pd.DataFrame(counts)


def classify_historical_series(
    market: pd.DataFrame,
    dated_identity: pd.DataFrame,
    membership: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = (
        market.groupby(["series", "symbol", "isin"], observed=True, dropna=False)
        .agg(
            first_seen=("date", "min"),
            last_seen=("date", "max"),
            observations=("date", "size"),
        )
        .reset_index()
    )
    identity_lookup = dated_identity[
        ["isin", "symbol", "security_id"]
    ].drop_duplicates(["isin", "symbol"])
    groups = groups.merge(identity_lookup, on=["isin", "symbol"], how="left")
    equity_isins = set(market.loc[market["series"].eq("EQ"), "isin"].dropna())
    member_ids = set(membership["security_id"])

    current = pd.read_csv(IDENTITY_RAW / "EQUITY_L.csv")
    current.columns = [clean_cell(column).upper() for column in current.columns]
    current_equity_isins = set(
        current["ISIN NUMBER"].astype("string").str.strip().str.upper().dropna()
    )
    groups["is_eligible_common_equity"] = False
    groups["classification"] = "OTHER_SERIES"
    groups["classification_evidence"] = "NSE_SERIES_LEGEND"

    eq = groups["series"].eq("EQ")
    groups.loc[eq, "is_eligible_common_equity"] = True
    groups.loc[eq, "classification"] = "FULLY_PAID_EQUITY"

    trade_for_trade = groups["series"].isin(["BE", "BZ"])
    rights = trade_for_trade & groups["symbol"].str.match(r".*-RE\d*$", na=False)
    groups.loc[rights, "classification"] = "RIGHTS_ENTITLEMENT"
    groups.loc[rights, "classification_evidence"] = "NSE_SERIES_LEGEND_AND_SYMBOL"

    same_isin_eq = trade_for_trade & groups["isin"].isin(equity_isins) & ~rights
    current_anchor = (
        trade_for_trade
        & groups["isin"].isin(current_equity_isins)
        & ~same_isin_eq
        & ~rights
    )
    membership_anchor = (
        trade_for_trade
        & groups["security_id"].isin(member_ids)
        & ~same_isin_eq
        & ~current_anchor
        & ~rights
    )
    for mask, evidence in [
        (same_isin_eq, "SAME_ISIN_OBSERVED_IN_EQ"),
        (current_anchor, "CURRENT_NSE_EQUITY_MASTER"),
        (membership_anchor, "OFFICIAL_NIFTY500_MEMBERSHIP"),
    ]:
        groups.loc[mask, "is_eligible_common_equity"] = True
        groups.loc[mask, "classification"] = "TRADE_FOR_TRADE_EQUITY"
        groups.loc[mask, "classification_evidence"] = evidence

    unresolved = trade_for_trade & ~groups["is_eligible_common_equity"] & ~rights
    groups.loc[unresolved, "classification"] = "UNRESOLVED_BE_BZ"
    groups.loc[unresolved, "classification_evidence"] = "MANUAL_REVIEW_REQUIRED"

    summary = (
        groups.groupby(
            ["series", "classification", "is_eligible_common_equity"],
            dropna=False,
        )
        .agg(security_series_groups=("symbol", "size"), observations=("observations", "sum"))
        .reset_index()
        .sort_values(["series", "classification"])
    )
    return groups, summary


def repair_corporate_actions(
    dated_identity: pd.DataFrame, membership: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actions = pd.read_parquet(
        CORPORATE_ACTION_PATH,
        filters=[("ex_date", "<=", CUTOFF)],
    )
    actions["repair_status"] = "UNCHANGED"
    actions["repair_reason"] = ""

    preference_bonus = actions["purpose"].str.contains(
        r"BONUS\s+PREFERENCE\s+SHARES", case=False, na=False
    )
    actions.loc[preference_bonus, "is_bonus"] = False
    actions.loc[preference_bonus, "is_structural"] = True
    actions.loc[preference_bonus, "primary_class"] = "PREFERENCE_SHARE_BONUS"
    actions.loc[preference_bonus, "needs_manual_review"] = True
    actions.loc[preference_bonus, "repair_status"] = "RECLASSIFIED"
    actions.loc[
        preference_bonus, "repair_reason"
    ] = "Preference-share entitlement is not an ordinary-equity bonus."

    compact_decimal = actions["purpose"].str.extract(
        r"(?i)\b(?:RS|RE)\.(0\d{2,})(?!\.)\b", expand=False
    )
    compact_decimal_value = pd.to_numeric(
        "0." + compact_decimal.str.slice(1), errors="coerce"
    )
    simple_compact = (
        actions["is_dividend"]
        & compact_decimal_value.notna()
        & actions["purpose"].str.count(r"(?i)\b(?:RS|RE)\b").eq(1)
    )
    actions.loc[simple_compact, "dividend_amount"] = compact_decimal_value[simple_compact]
    actions.loc[simple_compact, "repair_status"] = "REPARSED"
    actions.loc[
        simple_compact, "repair_reason"
    ] = "Preserved the decimal point in compact Rs.0xxx notation."

    spaced_decimal = actions["purpose"].str.extract(
        r"(?i)\b(?:RS|RE)\s+0\s+\.\s*(\d+)\b", expand=False
    )
    spaced_decimal_value = pd.to_numeric(
        "0." + spaced_decimal, errors="coerce"
    )
    simple_spaced = (
        actions["is_dividend"]
        & spaced_decimal_value.notna()
        & actions["economic_event_count"].eq(1)
    )
    actions.loc[simple_spaced, "dividend_amount"] = spaced_decimal_value[simple_spaced]
    actions.loc[simple_spaced, "needs_manual_review"] = False
    actions.loc[simple_spaced, "repair_status"] = "REPARSED"
    actions.loc[
        simple_spaced, "repair_reason"
    ] = "Normalized whitespace inside a decimal dividend amount."

    face_values = actions["purpose"].str.extract(
        r"(?i)FACE VALUE SPLIT.*?(?:FROM\s+)?(?:RS|RE)\.?\s*(\d+(?:\.\d+)?)\s*/?-\s*(?:PER SHARE\s*)?TO\s+(?:RS|RE)\.?\s*(\d+(?:\.\d+)?)",
        expand=True,
    )
    reparsed_face_value = face_values[0].notna() & face_values[1].notna()
    missing_face_value = reparsed_face_value & (
        actions["old_face_value_parsed"].isna()
        | actions["new_face_value_parsed"].isna()
    )
    actions.loc[missing_face_value, "old_face_value_parsed"] = pd.to_numeric(
        face_values.loc[missing_face_value, 0]
    )
    actions.loc[missing_face_value, "new_face_value_parsed"] = pd.to_numeric(
        face_values.loc[missing_face_value, 1]
    )
    simple_split = (
        missing_face_value
        & actions["primary_class"].eq("SPLIT")
        & actions["economic_event_count"].eq(1)
    )
    actions.loc[simple_split, "needs_manual_review"] = False
    actions.loc[missing_face_value, "repair_status"] = "REPARSED"
    actions.loc[
        missing_face_value, "repair_reason"
    ] = "Parsed dotted face values when the phrase omits the word 'from'."

    debenture_entitlement = actions["purpose"].str.contains(
        r"BONUS[^\n]*DEBENTURE", case=False, na=False
    )
    actions.loc[debenture_entitlement, "is_bonus"] = False
    actions.loc[debenture_entitlement, "is_structural"] = True
    actions.loc[debenture_entitlement, "primary_class"] = "DEBENTURE_ENTITLEMENT"
    actions.loc[debenture_entitlement, "economic_event_count"] = 1
    actions.loc[debenture_entitlement, "multiple_event_types"] = False
    actions.loc[debenture_entitlement, "needs_manual_review"] = True
    actions.loc[debenture_entitlement, "repair_status"] = "RECLASSIFIED"
    actions.loc[
        debenture_entitlement, "repair_reason"
    ] = "A debenture entitlement is not an ordinary-equity bonus."

    repaired = actions[actions["repair_status"].ne("UNCHANGED")].copy()
    unresolved_mask = (
        actions["needs_manual_review"]
        | actions["is_rights"]
        | actions["is_structural"]
        | actions["is_buyback"]
        | actions["is_capital_reduction"]
        | actions["is_consolidation"]
    )
    unresolved = actions[unresolved_mask].copy()
    unresolved_rows = []
    for row in unresolved.to_dict("records"):
        security_id, method, _ = resolve_symbol(
            row["symbol"], pd.Timestamp(row["ex_date"]), dated_identity
        )
        is_member = (
            security_id in active_membership_ids(membership, pd.Timestamp(row["ex_date"]))
            if security_id is not None
            else False
        )
        unresolved_rows.append(
            {
                **row,
                "security_id": security_id,
                "identity_match_method": method,
                "is_nifty500_member_on_ex_date": is_member,
            }
        )
    unresolved = pd.DataFrame(unresolved_rows)
    return actions, repaired, unresolved


def build_manifest(snapshot_dates: dict[str, pd.Timestamp]) -> pd.DataFrame:
    archive = archive_entries().set_index("filename")
    rows = []
    for path in sorted(RAW.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        source_url = ""
        publication_date = pd.NaT
        applicable_date = pd.NaT
        document_type = ""
        if path.parent == NOTICES:
            document_type = "index_change_notice"
            if path.name in archive.index:
                record = archive.loc[path.name]
                source_url = record["source_url"]
                publication_date = record["publication_date"]
        elif path.parent == MONTHLY:
            document_type = "monthly_constituent_archive"
            month = path.stem.replace("indices_data", "")
            source_url = MONTHLY_URL.format(month=month)
        elif path.parent == SNAPSHOTS:
            document_type = "constituent_snapshot"
            applicable_date = snapshot_dates.get(path.name, pd.NaT)
            month_match = re.search(r"_([A-Za-z]{3}\d{4})\.pdf$", path.name)
            if month_match:
                source_url = MONTHLY_URL.format(month=month_match.group(1))
        elif path.name == "IndexInclExcl.xls":
            document_type = "official_event_ledger"
            source_url = LEDGER_URL
        elif path.name == "press_release_archive.html":
            document_type = "press_release_archive"
            source_url = PRESS_ARCHIVE_URL
        else:
            continue
        retrieved = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        rows.append(
            {
                "source_id": f"NIFTY_{hashlib.sha1(relative.encode()).hexdigest()[:12]}",
                "local_path": relative,
                "source_url": source_url,
                "retrieved_at_utc": retrieved.isoformat(),
                "publication_date": publication_date,
                "applicable_date": applicable_date,
                "document_type": document_type,
                "mime_type": {
                    ".pdf": "application/pdf",
                    ".zip": "application/zip",
                    ".xls": "application/vnd.ms-excel",
                    ".html": "text/html",
                }.get(path.suffix.lower(), "application/octet-stream"),
                "byte_count": path.stat().st_size,
                "sha256": sha256(path),
                "retrieval_status": "OK",
            }
        )
    return pd.DataFrame(rows)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")


def run() -> dict[str, object]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    IDENTITY_OUTPUT.mkdir(parents=True, exist_ok=True)
    CORPORATE_ACTION_OUTPUT.mkdir(parents=True, exist_ok=True)

    snapshot_paths = extract_snapshot_pdfs()
    snapshot_frames = []
    snapshot_dates: dict[str, pd.Timestamp] = {}
    snapshot_summary = []
    for path in snapshot_paths:
        as_of_date, frame = parse_snapshot(path)
        snapshot_dates[path.name] = as_of_date
        snapshot_frames.append(frame)
        snapshot_summary.append(
            {
                "as_of_date": as_of_date,
                "source_file": path.name,
                "constituent_count": len(frame),
                "duplicate_symbol_count": int(frame["symbol"].duplicated().sum()),
            }
        )
    snapshots = pd.concat(snapshot_frames, ignore_index=True)
    seed = snapshots[snapshots["as_of_date"].eq(START_DATE)].copy()
    if len(seed) != 500 or seed["symbol"].nunique() != 500:
        raise ValueError(f"Official seed does not contain 500 unique symbols: {len(seed)}")

    notice_events, notice_status = parse_all_notices()
    ledger = read_official_ledger()
    matched, unmatched = match_notice_events_to_ledger(notice_events, ledger)
    authoritative_events = build_authoritative_events(
        notice_events, ledger, matched, unmatched
    )
    event_coverage = (
        authoritative_events.groupby("effective_date")
        .agg(
            exclusions=("action", lambda values: int(values.eq("EXCLUDE").sum())),
            inclusions=("action", lambda values: int(values.eq("INCLUDE").sum())),
            source_files=("source_file", lambda values: ";".join(sorted(values.unique()))),
            evidence_methods=("match_method", lambda values: ";".join(sorted(values.unique()))),
        )
        .reset_index()
    )
    ledger_duplicates = matched[
        matched.duplicated(["effective_date", "action", "symbol"], keep=False)
    ].sort_values(["effective_date", "action", "symbol"])

    market, observed = read_market_identity_history()
    dated_identity, identity_summary, identity_edges = build_dated_identity(observed)
    (
        membership,
        mapped_seed,
        mapped_events,
        applications,
        event_counts,
        identity_issues,
    ) = reconstruct_membership(seed, authoritative_events, dated_identity)
    if identity_issues.empty:
        identity_issues = pd.DataFrame(
            columns=[
                "record_type",
                "symbol",
                "security_id",
                "identity_match_method",
                "identity_candidate_count",
            ]
        )
    identity_issues.to_csv(AUDIT / "unresolved_membership_identity.csv", index=False)
    if not identity_issues.empty:
        raise ValueError(
            f"{len(identity_issues)} official membership rows have unresolved identity"
        )

    snapshot_validation, snapshot_discrepancies = validate_snapshots(
        snapshots, membership, dated_identity
    )
    prelisting = build_prelisting_audit(membership, dated_identity)
    previous_differences, previous_counts = compare_previous_membership(
        membership, dated_identity, identity_summary
    )
    series_classification, series_summary = classify_historical_series(
        market, dated_identity, membership
    )
    repaired_actions, action_repairs, unresolved_actions = repair_corporate_actions(
        dated_identity, membership
    )

    month_end_rows = []
    month_end_dates = pd.date_range(START_DATE, CUTOFF, freq="ME").union(
        pd.DatetimeIndex([START_DATE, CUTOFF])
    )
    for date in month_end_dates:
        month_end_rows.append(
            {"as_of_date": date, "constituent_count": len(active_membership_ids(membership, date))}
        )
    month_end_counts = pd.DataFrame(month_end_rows)

    collision_counts = (
        dated_identity.groupby("symbol")["security_id"]
        .nunique()
        .rename("security_id_count")
        .reset_index()
    )
    alias_collisions = collision_counts[collision_counts["security_id_count"].gt(1)].merge(
        dated_identity[
            ["symbol", "security_id", "isin", "first_seen", "last_seen", "observations"]
        ],
        on="symbol",
        how="left",
    )

    manifest = build_manifest(snapshot_dates)
    notice_counts = (
        notice_events.pivot_table(
            index="source_file", columns="action", values="symbol", aggfunc="size", fill_value=0
        )
        .rename(columns={"INCLUDE": "parsed_additions", "EXCLUDE": "parsed_deletions"})
        .reset_index()
    )
    manifest["source_file"] = manifest["local_path"].map(lambda value: Path(value).name)
    manifest = manifest.merge(
        notice_status.drop(columns="publication_date"), on="source_file", how="left"
    )
    manifest = manifest.merge(notice_counts, on="source_file", how="left")
    for column in ["parsed_additions", "parsed_deletions", "parsed_event_rows"]:
        manifest[column] = manifest[column].fillna(0).astype(int)
    manifest["parse_status"] = "NOT_APPLICABLE"
    notice_mask = manifest["document_type"].eq("index_change_notice")
    manifest.loc[notice_mask, "parse_status"] = "NO_BASE_INDEX_ROWS"
    manifest.loc[
        notice_mask & manifest["parsed_event_rows"].gt(0), "parse_status"
    ] = "PARSED"
    manifest.loc[
        notice_mask & manifest["parse_error"].fillna("").ne(""), "parse_status"
    ] = "ERROR"
    single_effective_date = (
        notice_mask
        & manifest["effective_date_candidates"].fillna("").ne("")
        & ~manifest["effective_date_candidates"].fillna("").str.contains(";")
    )
    manifest.loc[single_effective_date, "applicable_date"] = pd.to_datetime(
        manifest.loc[single_effective_date, "effective_date_candidates"]
    )
    manifest = manifest.drop(columns="source_file")

    write_parquet(seed, OUTPUT / "nifty500_official_seed.parquet")
    write_parquet(snapshots, OUTPUT / "nifty500_official_snapshots.parquet")
    write_parquet(notice_events, OUTPUT / "nifty500_notice_events.parquet")
    write_parquet(ledger, OUTPUT / "nifty500_official_event_ledger.parquet")
    write_parquet(
        authoritative_events, OUTPUT / "nifty500_authoritative_events.parquet"
    )
    authoritative_events.to_csv(OUTPUT / "nifty500_authoritative_events.csv", index=False)
    write_parquet(
        membership, OUTPUT / "nifty500_official_membership_intervals.parquet"
    )
    manifest.to_csv(OUTPUT / "membership_evidence_manifest.csv", index=False)

    write_parquet(
        dated_identity, IDENTITY_OUTPUT / "dated_security_identity.parquet"
    )
    write_parquet(identity_summary, IDENTITY_OUTPUT / "security_identity_summary.parquet")
    identity_edges.to_csv(IDENTITY_OUTPUT / "identity_evidence_edges.csv", index=False)
    alias_collisions.to_csv(IDENTITY_OUTPUT / "dated_alias_collisions.csv", index=False)

    write_parquet(
        series_classification, IDENTITY_OUTPUT / "historical_series_classification.parquet"
    )
    series_summary.to_csv(AUDIT / "historical_series_classification_summary.csv", index=False)

    write_parquet(
        repaired_actions,
        CORPORATE_ACTION_OUTPUT / "nse_corporate_actions_classified_through_2023_03_31.parquet",
    )
    action_repairs.to_csv(
        AUDIT / "corporate_action_repairs.csv", index=False
    )
    unresolved_actions.to_csv(
        AUDIT / "corporate_action_unresolved_cases.csv", index=False
    )
    (
        repaired_actions.groupby(["primary_class", "needs_manual_review"])
        .size()
        .rename("rows")
        .reset_index()
        .to_csv(AUDIT / "corporate_action_resolution_summary.csv", index=False)
    )

    pd.DataFrame(snapshot_summary).sort_values("as_of_date").to_csv(
        AUDIT / "official_snapshot_counts.csv", index=False
    )
    notice_status.to_csv(AUDIT / "notice_parse_status.csv", index=False)
    unmatched.to_csv(AUDIT / "official_ledger_unmatched_notice_rows.csv", index=False)
    mapped_seed.to_csv(AUDIT / "official_seed_identity_mapping.csv", index=False)
    mapped_events.to_csv(AUDIT / "official_event_identity_mapping.csv", index=False)
    applications.to_csv(AUDIT / "membership_event_application.csv", index=False)
    event_counts.to_csv(AUDIT / "membership_event_counts.csv", index=False)
    month_end_counts.to_csv(AUDIT / "official_membership_month_end_counts.csv", index=False)
    snapshot_validation.to_csv(AUDIT / "official_snapshot_reconciliation.csv", index=False)
    if snapshot_discrepancies.empty:
        snapshot_discrepancies = pd.DataFrame(
            columns=["as_of_date", "side", "security_id", "symbol"]
        )
    snapshot_discrepancies.to_csv(
        AUDIT / "official_snapshot_discrepancies.csv", index=False
    )
    prelisting.to_csv(AUDIT / "official_membership_prelisting_audit.csv", index=False)
    if previous_differences.empty:
        previous_differences = pd.DataFrame(
            columns=["valid_from", "valid_to", "side", "security_id", "symbol"]
        )
    previous_differences.to_csv(
        AUDIT / "membership_discrepancies_vs_previous.csv", index=False
    )
    previous_counts.to_csv(
        AUDIT / "membership_counts_vs_previous.csv", index=False
    )
    event_coverage.to_csv(AUDIT / "official_event_coverage.csv", index=False)
    ledger_duplicates.to_csv(AUDIT / "official_ledger_duplicate_rows.csv", index=False)

    series_manifest = pd.DataFrame(
        [
            {
                "local_path": SERIES_REFERENCE.relative_to(ROOT).as_posix(),
                "source_url": "https://www.nseindia.com/static/market-data/legend-of-series",
                "retrieved_at_utc": datetime.fromtimestamp(
                    SERIES_REFERENCE.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "document_type": "official_series_legend",
                "byte_count": SERIES_REFERENCE.stat().st_size,
                "sha256": sha256(SERIES_REFERENCE),
            }
        ]
    )
    series_manifest.to_csv(AUDIT / "upstream_reference_manifest.csv", index=False)

    event_application_issues = int(
        applications["application_status"].ne("APPLIED").sum()
    )
    snapshot_difference_count = int(
        snapshot_validation["symmetric_difference_count"].sum()
    )
    exact_prelisting_failures = int(prelisting["status"].eq("FAIL_PRELISTING").sum())
    observed_date_reviews = int(
        prelisting["status"].eq("REVIEW_BEFORE_FIRST_OBSERVATION").sum()
    )

    return {
        "seed_rows": len(seed),
        "snapshots": len(snapshot_summary),
        "notices": int(manifest["document_type"].eq("index_change_notice").sum()),
        "parsed_notice_rows": len(notice_events),
        "official_ledger_rows": len(ledger),
        "matched_ledger_rows": len(matched),
        "unmatched_ledger_rows": len(unmatched),
        "reviewed_event_overrides": len(load_reviewed_overrides()),
        "authoritative_event_rows": len(authoritative_events),
        "membership_intervals": len(membership),
        "final_constituent_count": len(active_membership_ids(membership, CUTOFF)),
        "event_application_issues": event_application_issues,
        "snapshot_symmetric_differences": snapshot_difference_count,
        "exact_prelisting_failures": exact_prelisting_failures,
        "first_observation_reviews": observed_date_reviews,
        "dated_identity_rows": len(dated_identity),
        "dated_alias_collision_rows": len(alias_collisions),
        "unresolved_membership_identity_rows": len(identity_issues),
        "unresolved_be_bz_groups": int(
            series_classification["classification"].eq("UNRESOLVED_BE_BZ").sum()
        ),
        "corporate_action_repairs": len(action_repairs),
        "unresolved_corporate_action_rows": len(unresolved_actions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild official NIFTY 500 evidence.")
    parser.parse_args()
    summary = run()
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
