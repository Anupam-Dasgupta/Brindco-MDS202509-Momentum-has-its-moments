"""Compare a development replay with the frozen pre-refactor artifacts."""

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from brindco_momentum.paths import ROOT


BASELINE = ROOT / "results/project_refactor/baseline_sha256.csv"
FROZEN = ROOT / "results/accounts_development/frozen_corporate_action_scenario"
REPLAY = ROOT / "results/project_refactor/reproduced_accounts"
REPORT = ROOT / "results/project_refactor/regression_report.csv"
CUTOFF = pd.Timestamp("2023-03-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    rows = []
    with BASELINE.open(newline="", encoding="utf-8-sig") as source:
        for item in csv.DictReader(source):
            path = ROOT / item["path"]
            actual = sha256(path) if path.is_file() else "MISSING"
            rows.append({"check": "frozen_original", "path": item["path"],
                         "status": "MATCH" if actual == item["sha256"] else "DIFF",
                         "expected_sha256": item["sha256"], "actual_sha256": actual})

    expected = {p.name: p for p in FROZEN.iterdir()
                if p.is_file() and p.suffix in {".csv", ".json", ".parquet"}}
    actual = {p.name: p for p in REPLAY.iterdir() if p.is_file()}
    for name in sorted(expected.keys() | actual.keys()):
        original = expected.get(name)
        replayed = actual.get(name)
        expected_hash = sha256(original) if original else "MISSING"
        actual_hash = sha256(replayed) if replayed else "MISSING"
        status = "MATCH" if expected_hash == actual_hash else "DIFF"
        if status == "DIFF" and original and replayed and original.suffix == ".json":
            if json.loads(original.read_text()) == json.loads(replayed.read_text()):
                status = "MATCH_SEMANTIC"
        rows.append({"check": "development_replay", "path": name,
                     "status": status,
                     "expected_sha256": expected_hash, "actual_sha256": actual_hash})

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    mismatches = [row for row in rows if row["status"] == "DIFF"]
    print(f"Frozen original files checked: {sum(row['check'] == 'frozen_original' for row in rows)}")
    print(f"Development replay files checked: {sum(row['check'] == 'development_replay' for row in rows)}")
    print(f"Identical JSON states with different key ordering: {sum(row['status'] == 'MATCH_SEMANTIC' for row in rows)}")
    print(f"Hash mismatches: {len(mismatches)}")
    for row in mismatches:
        print(f"{row['check']}: {row['path']}")
    if mismatches:
        raise SystemExit(1)

    summary = pd.read_csv(REPLAY / "account_run_summary.csv").set_index("account")
    for account in ("MOM", "VM"):
        nav = pd.read_parquet(REPLAY / f"{account}_nav_daily.parquet",
                              columns=["date", "reconciliation_error"])
        assert len(nav) == 1982
        assert pd.Timestamp(nav["date"].max()) == CUTOFF
        assert nav["reconciliation_error"].abs().max() < 1e-6
        assert summary.loc[account, "maximum_value_bearing_market_date_read"] == "2023-03-31"
        print(f"{account}: 1982 development NAV rows through 2023-03-31; reconciliation passed")


if __name__ == "__main__":
    main()
