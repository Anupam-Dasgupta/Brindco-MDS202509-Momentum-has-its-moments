"""Audit targeted corporate-action research and its mechanical signal effects."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


from brindco_momentum.paths import ROOT
OUT = ROOT / "results" / "event_resolution"
CUTOFF = pd.Timestamp("2023-03-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    priority = pd.read_csv(ROOT / "results/momentum_materiality/unresolved_event_priority.csv")
    before_affected = pd.read_csv(ROOT / "results/momentum_materiality/affected_signal_materiality.csv")
    manual = pd.read_csv(ROOT / "data/manual/corporate_action_resolutions_v1.csv").set_index("event_id")
    research = pd.read_csv(ROOT / "data/manual/corporate_action_research_v1.csv").set_index("event_id")
    events = pd.read_csv(ROOT / "results/stock_total_return_audit/event_application_detail.csv").set_index("event_id")
    after_affected = pd.read_csv(ROOT / "results/momentum_signal_audit/unresolved_event_materiality.csv")
    raw_manifest = pd.read_csv(ROOT / "data/raw/corporate_actions/manifest.csv").set_index("filename")
    bhav_manifest = pd.read_csv(ROOT / "data/raw/bhavcopy_legacy/manifest.csv").set_index("filename")
    accepted_identity = pd.read_parquet(ROOT / "data/processed/security_identity_official/dated_security_identity.parquet")
    membership = pd.read_parquet(ROOT / "data/processed/membership_official/nifty500_official_membership_intervals.parquet")
    retrieved_at = pd.Timestamp.now(tz="UTC").isoformat()

    prior = pd.read_parquet(OUT / "baseline/momentum_formations.parquet")
    current = pd.read_parquet(ROOT / "data/processed/momentum_formations.parquet",
                              filters=[("formation_date", "<=", CUTOFF)])
    for frame in (prior, current):
        frame["formation_date"] = pd.to_datetime(frame["formation_date"])
    if len(prior) != len(current) or prior.duplicated(["formation_date", "security_id"]).any() or current.duplicated(["formation_date", "security_id"]).any():
        raise ValueError("Formation roster changed unexpectedly")
    comparison = prior.merge(current, on=["formation_date", "security_id"], how="outer", suffixes=("_before", "_after"), validate="one_to_one", indicator=True)
    if not comparison["_merge"].eq("both").all():
        raise ValueError("Official formation roster changed")
    score_changed = ~np.isclose(comparison["momentum_score_before"], comparison["momentum_score_after"], equal_nan=True)
    changed = comparison.loc[
        comparison["eligible_before"].ne(comparison["eligible_after"])
        | score_changed
        | comparison["rank_before"].fillna(-1).ne(comparison["rank_after"].fillna(-1))
        | comparison["winner_before"].ne(comparison["winner_after"])
        | comparison["target_winner_count_before"].ne(comparison["target_winner_count_after"])
    ].copy()
    resolved_ids = set(manual.index)
    event_dates = before_affected.loc[before_affected["event_id"].isin(resolved_ids), ["event_id", "formation_date"]].drop_duplicates()
    event_dates["formation_date"] = pd.to_datetime(event_dates["formation_date"])
    causes = event_dates.groupby("formation_date")["event_id"].agg(lambda s: ";".join(sorted(s)))
    changed["resolved_event_ids_at_formation"] = changed["formation_date"].map(causes).fillna("")
    columns = ["formation_date", "security_id", "published_symbol_before", "scored_before",
               "eligible_before", "eligible_after", "momentum_score_before", "momentum_score_after",
               "rank_before", "rank_after", "target_winner_count_before", "target_winner_count_after",
               "winner_before", "winner_after", "resolved_event_ids_at_formation"]
    changed[columns].sort_values(["formation_date", "security_id"]).to_csv(OUT / "downstream_signal_changes.csv", index=False)

    all_ids = list(priority["event_id"]) + [event_id for event_id in research.index if event_id not in set(priority["event_id"])]
    if len(all_ids) != 42 or len(set(all_ids)) != 42 or len(manual) != 8:
        raise ValueError("Targeted research inventory must contain 38 economic and four identity events")
    priority_by_id = priority.set_index("event_id")
    status_rows = []
    evidence_rows = []
    for event_id in all_ids:
        event = events.loc[event_id]
        source_file = event.source_file
        source = raw_manifest.loc[source_file]
        raw_path = ROOT / "data/raw/corporate_actions" / source_file
        if sha256(raw_path) != source.sha256:
            raise ValueError(f"Source evidence changed: {source_file}")
        if event_id in {"CA_25d92bfd331e98d5bc85", "CA_eb8ec60bd0c8f1584789"}:
            if event.series not in {"H3", "H4"} or "BONDHOLDERS" not in event.purpose_normalized:
                raise ValueError("IDFC orphan is not the evidenced debt-series action")
        if event_id in {"CA_a4d21420673221a0b482", "CA_8bd79e7b22c050462139"}:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            records = raw if isinstance(raw, list) else raw["data"]
            match = [record for record in records if record["symbol"] == event.symbol
                     and record["series"] == "EQ"
                     and pd.Timestamp(record["exDate"]) == pd.Timestamp(event.ex_date)]
            if len(match) != 1:
                raise ValueError(f"Orphan source identity ambiguous: {event_id}")
            accepted_id = ("NSE_244EC4566860" if event.symbol == "MONNETISPA"
                           else "NSE_AA00EC8A4A3D")
            linked = accepted_identity.loc[accepted_identity["isin"].eq(match[0]["isin"])
                                           & accepted_identity["symbol"].eq(event.symbol), "security_id"].unique()
            if len(linked) != 1 or linked[0] != accepted_id:
                raise ValueError(f"Orphan ISIN does not match accepted security: {event_id}")
            future_membership = membership.loc[
                membership["security_id"].eq(accepted_id)
                & pd.to_datetime(membership["valid_to"]).gt(pd.Timestamp(event.ex_date))
                & pd.to_datetime(membership["valid_from"]).le(CUTOFF)
            ]
            if not future_membership.empty:
                raise ValueError(f"Orphan could affect a future member lookback: {event_id}")
        if event_id in manual.index:
            note = manual.loc[event_id]
            final_status = note.resolution_status
            treatment = note.treatment_type
            missing = ""
            supplement = (note.evidence_url, note.evidence_title, note.evidence_organization,
                          note.evidence_date, note.evidence_fact)
        else:
            note = research.loc[event_id]
            identity = note.identity_conclusion
            final_status = ("RESOLVED_IDENTITY_ONLY" if identity == "EQUITY_IDENTITY_CONFIRMED_NO_LOOKBACK_OVERLAP"
                            else "UNRESOLVED_IDENTITY" if identity == "NON_EQUITY_BOND_SERIES_NO_SIGNAL_OVERLAP"
                            else "UNRESOLVED_ECONOMIC_TREATMENT")
            treatment = "NO_SIGNAL_OVERLAP" if final_status == "RESOLVED_IDENTITY_ONLY" else "UNRESOLVED"
            missing = note.missing_evidence
            supplement = (note.evidence_url, note.evidence_title, note.evidence_organization,
                          note.evidence_date, note.evidence_fact)
        is_priority = event_id in priority_by_id.index
        if is_priority:
            item = priority_by_id.loc[event_id]
            before_scored = int(item.affected_scored_formations)
            before_warmup = int(item.affected_formations) - before_scored
            security_id = item.security_id
            priority_group = item.priority_group
        else:
            before_scored = before_warmup = 0
            security_id = ("NSE_244EC4566860" if event.symbol == "MONNETISPA" else
                           "NSE_AA00EC8A4A3D" if event.symbol == "SUPPETRO" else "")
            priority_group = "IDENTITY_ORPHAN"
        remaining = after_affected.loc[
            after_affected["event_id"].eq(event_id)
            & after_affected["final_signal_availability_changed"].eq(True)
        ]
        affected = before_affected.loc[before_affected["event_id"].eq(event_id), "formation_date"]
        relevant_changes = changed.loc[
            changed["formation_date"].isin(pd.to_datetime(affected))
            & changed["security_id"].eq(security_id)
        ]
        status_rows.append({
            "priority_group": priority_group, "event_id": event_id, "security_id": security_id,
            "symbol": event.symbol, "event_date": event.ex_date, "event_type": event.primary_class,
            "previous_status": "UNRESOLVED_IDENTITY" if not is_priority else "UNRESOLVED_ECONOMIC_TREATMENT",
            "final_status": final_status, "treatment": treatment,
            "evidence_sources_checked": str(source.url) + ";" + str(supplement[0]),
            "affected_scored_formations_before": before_scored,
            "affected_warmup_formations_before": before_warmup,
            "affected_formations_after": len(remaining),
            "changed_eligibility": bool(relevant_changes["eligible_before"].ne(relevant_changes["eligible_after"]).any()),
            "changed_k": bool(relevant_changes["target_winner_count_before"].ne(relevant_changes["target_winner_count_after"]).any()),
            "changed_own_winner_membership": bool(relevant_changes["winner_before"].ne(relevant_changes["winner_after"]).any()),
            "missing_evidence": missing,
        })
        evidence_rows.append({"event_id": event_id, "evidence_role": "NSE_SOURCE_ACTION", "source_url": source.url,
                              "title": "NSE corporate-action source record", "organization": "NSE",
                              "publication_or_event_date": event.ex_date, "retrieved_at_utc": source.retrieved_at_utc,
                              "extracted_fact": event.purpose_normalized, "local_evidence_file": str(raw_path.relative_to(ROOT)),
                              "sha256": source.sha256})
        evidence_rows.append({"event_id": event_id, "evidence_role": "SUPPLEMENTAL_PRIMARY_RESEARCH",
                              "source_url": supplement[0], "title": supplement[1], "organization": supplement[2],
                              "publication_or_event_date": supplement[3], "retrieved_at_utc": retrieved_at,
                              "extracted_fact": supplement[4], "local_evidence_file": "", "sha256": ""})
        if event_id in manual.index and treatment == "LISTED_SHARE_DISTRIBUTION":
            date = pd.Timestamp(note.entitlement_price_date)
            filename = f"cm{date.strftime('%d%b%Y').upper()}bhav.csv.zip"
            if filename not in bhav_manifest.index:
                raise ValueError(f"Recipient quote source missing from manifest: {filename}")
            quote_source = bhav_manifest.loc[filename]
            quote_path = ROOT / "data/raw/bhavcopy_legacy" / filename
            evidence_rows.append({"event_id": event_id, "evidence_role": "RECIPIENT_EX_DATE_TRADE",
                                  "source_url": quote_source.url, "title": "Official NSE cash-equity bhavcopy",
                                  "organization": "NSE", "publication_or_event_date": date.date().isoformat(),
                                  "retrieved_at_utc": retrieved_at,
                                  "extracted_fact": f"{note.entitlement_symbol} EQ {note.entitlement_isin} close INR {note.entitlement_price_close}",
                                  "local_evidence_file": str(quote_path.relative_to(ROOT)), "sha256": sha256(quote_path)})

    statuses = pd.DataFrame(status_rows)
    statuses.to_csv(OUT / "event_resolution_status.csv", index=False)
    pd.DataFrame(evidence_rows).to_csv(OUT / "event_evidence_manifest.csv", index=False)
    statuses.loc[statuses["final_status"].str.startswith("UNRESOLVED")].to_csv(OUT / "unresolved_after_research.csv", index=False)

    hashes = pd.read_csv(OUT / "artifact_hashes.csv")
    hashes["after_sha256"] = hashes["artifact"].map(lambda name: sha256(ROOT / name))
    hashes.to_csv(OUT / "artifact_hashes.csv", index=False)

    before_scored = int(statuses.affected_scored_formations_before.sum())
    before_warmup = int(statuses.affected_warmup_formations_before.sum())
    remaining_priority = after_affected.loc[
        after_affected["event_id"].isin(priority["event_id"])
        & after_affected["final_signal_availability_changed"].eq(True)
    ].copy()
    remaining_priority["formation_date"] = pd.to_datetime(remaining_priority["formation_date"])
    remaining_priority = remaining_priority.merge(
        current[["formation_date", "security_id", "scored"]],
        on=["formation_date", "security_id"], how="left", validate="many_to_one",
    )
    if remaining_priority["scored"].isna().any():
        raise ValueError("Unresolved event missing from current formation roster")
    after_scored = int(remaining_priority["scored"].sum())
    after_warmup = len(remaining_priority) - after_scored
    changed_dates = comparison.loc[comparison.eligible_before.ne(comparison.eligible_after), "formation_date"].nunique()
    k_dates = comparison.loc[comparison.target_winner_count_before.ne(comparison.target_winner_count_after), "formation_date"].nunique()
    entered = changed.loc[~changed.winner_before & changed.winner_after]
    left = changed.loc[changed.winner_before & ~changed.winner_after]
    print(f"targeted_events={len(statuses)} scored_priority=31 warmup_only=7 identity_orphans=4")
    print(f"resolved_economic={len(manual)} scored_resolved={statuses.loc[statuses.priority_group.eq('SCORED_WINNER_UNCERTAINTY'), 'final_status'].str.startswith('RESOLVED').sum()} warmup_only_resolved={statuses.loc[statuses.priority_group.eq('WARMUP_ONLY_SHADOW_DEPENDENCY'), 'final_status'].str.startswith('RESOLVED').sum()}")
    print(f"blocked_signals_before={before_scored + before_warmup} scored_before={before_scored} warmup_before={before_warmup}")
    print(f"blocked_signals_after={after_scored + after_warmup} scored_after={after_scored} warmup_after={after_warmup}")
    print(f"formation_dates_eligibility_changed={changed_dates} formation_dates_k_changed={k_dates}")
    print(f"winner_entries={len(entered)} winner_exits={len(left)} changed_formations={len(changed)}")
    print(f"entering_symbols={';'.join(sorted(set(entered.symbol_after.dropna())))}")
    print(f"leaving_symbols={';'.join(sorted(set(left.symbol_before.dropna())))}")
    return_summary = pd.read_csv(ROOT / "results/stock_total_return_audit/summary.csv").set_index("metric")
    print(f"max_value_date_read={return_summary.loc['maximum_value_date_read', 'value']}")


if __name__ == "__main__":
    main()
