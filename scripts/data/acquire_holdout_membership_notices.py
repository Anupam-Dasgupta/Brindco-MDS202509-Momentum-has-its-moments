"""Cache official NSE Indices notices that may change holdout membership."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from brindco_momentum.data import membership_rebuild
from brindco_momentum.paths import ROOT


DESTINATION = ROOT / "data" / "evidence" / "membership_holdout"
NOTICES = DESTINATION / "notices_pdf"
START = pd.Timestamp("2023-04-01")
END = pd.Timestamp("2026-03-30")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.niftyindices.com/press-release",
}


def candidate_notices() -> pd.DataFrame:
    archive = membership_rebuild.archive_entries()
    archive = archive[archive["publication_date"].between(START, END)].copy()
    title = archive["title"].str.lower()
    possible_change = title.str.contains(
        "replac|exclu|inclu|corporate action|corporate adjustment|revision in criteria|methodology|meeting of the index maintenance"
    )
    unrelated_index = title.str.contains(
        "fixed income|sme emerge|government bond|g-sec|esg|shariah|multi asset|aif|launch"
    ) | title.str.match(r"^(?:inclusions?|replacements?) in nifty ipo")
    return archive[possible_change & ~unrelated_index].sort_values(
        ["publication_date", "filename"]
    )


def retrieve(row: dict[str, object]) -> dict[str, object]:
    source_url = str(row["source_url"])
    destination = NOTICES / str(row["filename"])
    if not destination.exists():
        response = requests.get(source_url, headers=HEADERS, timeout=40)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"Official source did not return a PDF: {source_url}")
        destination.write_bytes(response.content)
    content = destination.read_bytes()
    return {
        "publication_date": row["publication_date"],
        "title": row["title"],
        "source_url": source_url,
        "local_path": destination.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "status": "VERIFIED",
    }


def main() -> None:
    NOTICES.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(retrieve, row): row for row in candidate_notices().to_dict("records")
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                rows.append(future.result())
            except (requests.RequestException, ValueError) as exc:
                rows.append({
                    "publication_date": row["publication_date"],
                    "title": row["title"],
                    "source_url": row["source_url"],
                    "local_path": "",
                    "sha256": "",
                    "bytes": 0,
                    "status": f"ERROR: {exc}",
                })
    manifest = pd.DataFrame(rows).sort_values(["publication_date", "source_url"])
    manifest.to_csv(DESTINATION / "notice_pdf_manifest.csv", index=False)
    print(f"Retrieved/cached {(~manifest['status'].str.startswith('ERROR')).sum()} of {len(manifest)} official PDFs")
    print(f"Errors: {manifest['status'].str.startswith('ERROR').sum()}")
    if manifest["status"].str.startswith("ERROR").any():
        return

    membership_rebuild.CUTOFF = END
    archive = membership_rebuild.archive_entries()
    statuses = []
    events = []
    for path in sorted(NOTICES.glob("*.pdf")):
        parsed = membership_rebuild.parse_notice(path, archive)
        dates = ";".join(value.date().isoformat() for value in parsed.effective_dates)
        statuses.append({
            "source_file": path.name,
            "publication_date": parsed.publication_date,
            "effective_date_candidates": dates,
            "contains_nifty500_text": parsed.text_contains_base_index,
            "parsed_event_rows": len(parsed.rows),
            "parse_error": parsed.error,
        })
        for event in parsed.rows:
            events.append({
                **event,
                "publication_date": parsed.publication_date,
                "effective_date_candidates": dates,
                "source_url": archive.loc[
                    archive["filename"].eq(path.name), "source_url"
                ].iloc[0],
            })
    pd.DataFrame(statuses).to_csv(DESTINATION / "notice_parse_status.csv", index=False)
    pd.DataFrame(events).to_csv(DESTINATION / "notice_parsed_events.csv", index=False)
    print(f"Parsed {len(events)} tabular NIFTY 500 event rows from {len(statuses)} notices")


if __name__ == "__main__":
    main()
