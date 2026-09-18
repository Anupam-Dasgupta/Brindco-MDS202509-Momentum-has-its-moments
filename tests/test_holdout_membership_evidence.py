"""Source-audit checks only; these do not approve holdout membership."""

import hashlib
from pathlib import Path

import pandas as pd

from brindco_momentum.paths import ROOT
from scripts.data.acquire_holdout_membership_notices import candidate_notices


EVIDENCE = ROOT / "data" / "evidence" / "membership_holdout"


def test_notice_discovery_keeps_mixed_index_changes_and_stays_in_window():
    candidates = candidate_notices()
    filenames = set(candidates["filename"])
    assert "ind_prs15072025.pdf" in filenames  # Mixed NIFTY 500 / NIFTY IPO notice.
    assert "ind_prs26122025.pdf" not in filenames  # NIFTY IPO only.
    assert candidates["filename"].is_unique
    assert candidates["publication_date"].between("2023-04-01", "2026-03-30").all()
    assert candidates["source_url"].str.contains("niftyindices.com/Press_Release/").all()


def test_cached_official_pdfs_and_parse_outputs_match_manifest():
    manifest = pd.read_csv(EVIDENCE / "notice_pdf_manifest.csv")
    assert set(manifest["source_url"]) == set(candidate_notices()["source_url"])
    assert manifest["status"].eq("VERIFIED").all()
    for row in manifest.itertuples(index=False):
        path = ROOT / row.local_path
        assert path.is_file()
        content = path.read_bytes()
        assert content.startswith(b"%PDF")
        assert path.stat().st_size == row.bytes
        assert hashlib.sha256(content).hexdigest() == row.sha256

    status = pd.read_csv(EVIDENCE / "notice_parse_status.csv")
    events = pd.read_csv(EVIDENCE / "notice_parsed_events.csv")
    assert set(status["source_file"]) == {
        Path(path).name for path in manifest["local_path"]
    }
    assert status["parse_error"].isna().all()
    assert int(status["parsed_event_rows"].sum()) == len(events)
