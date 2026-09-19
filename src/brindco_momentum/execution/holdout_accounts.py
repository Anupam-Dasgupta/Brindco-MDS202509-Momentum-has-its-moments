"""Sealed holdout account entry point using the frozen development engine."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from brindco_momentum.execution.development_accounts import run_account
from brindco_momentum.paths import ROOT


PROCESSED = ROOT / "data/processed"
RUNTIME_INPUTS = PROCESSED / "runtime_inputs"
OPENING_STATES = {
    name: ROOT / f"data/processed/holdout_opening_states/{name}_state.json"
    for name in ("MOM", "VM", "FIX", "FIXVOL")
}


def load_account_common(manifest_hash: str) -> dict:
    """Translate accepted direct terms into the frozen account event schema."""
    accepted = pd.read_parquet(
        PROCESSED / "corporate_action_treatment_holdout/accepted_event_treatments.parquet"
    )
    if accepted["event_id"].duplicated().any() or accepted["security_id"].isna().any():
        raise ValueError("Accepted holdout action linkage is invalid")
    if not accepted["parent_event_class"].isin({"DIVIDEND", "BONUS", "SPLIT", "RIGHTS", "BUYBACK", "STRUCTURAL"}).all():
        raise ValueError("Holdout action requires an unsupported account mechanism")
    received_evidence = pd.read_csv(
        RUNTIME_INPUTS / "vakrangee_demerger_verified_evidence.csv"
    )
    structural_ids = set(accepted.loc[accepted.parent_event_class.eq("STRUCTURAL"), "event_id"])
    if (received_evidence.event_id.duplicated().any()
            or structural_ids != set(received_evidence.event_id)
            or not accepted.loc[accepted.parent_event_class.eq("STRUCTURAL"),
                                "treatment_status"].eq("RESOLVED_UNLISTED_RECEIVED_SECURITY_CLAIM").all()):
        raise ValueError("Accepted structural action lacks verified received-security evidence")
    buyback = accepted.loc[accepted.parent_event_class.eq("BUYBACK")]
    if not buyback.treatment_status.eq("RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT").all():
        raise ValueError("Holdout buyback has no frozen passive-holder treatment")
    rights_evidence = pd.concat([
        pd.read_csv(RUNTIME_INPUTS / "pnbhousing_rights_verified_evidence.csv"),
        pd.read_csv(RUNTIME_INPUTS / "sobha_rights_verified_evidence.csv"),
        pd.read_csv(RUNTIME_INPUTS / "upl_rights_verified_evidence.csv"),
        pd.read_csv(RUNTIME_INPUTS / "inoxwind_rights_verified_evidence.csv"),
    ], ignore_index=True)
    rights_ids = set(accepted.loc[accepted.parent_event_class.eq("RIGHTS"), "event_id"])
    if (rights_evidence.event_id.duplicated().any()
            or rights_ids != set(rights_evidence.event_id)):
        raise ValueError("Accepted holdout rights lack verified frozen-method evidence")
    events: dict = {}
    for row in accepted.itertuples(index=False):
        day = pd.Timestamp(row.effective_date).date()
        events.setdefault(day, []).append({
            "event_id": row.event_id,
            "security_id": row.security_id,
            "primary_class": row.parent_event_class,
            "application_status": (
                "NO_DIRECT_ADJUSTMENT_REQUIRED"
                if row.treatment_status == "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT"
                else "RECEIVED_SECURITY_CLAIM"
                if row.treatment_status == "RESOLVED_UNLISTED_RECEIVED_SECURITY_CLAIM"
                else "APPLIED_TO_RETURN"
            ),
            "cash_effect": float(row.cash_per_pre_event_share),
            "share_effect": float(row.share_multiplier),
            "payment_date": pd.NaT,
            "rights_new_shares_per_old_share": row.rights_new_shares_per_old_share,
            "rights_subscription_price": row.rights_subscription_price,
        })
    hard_stops = pd.read_csv(
        RUNTIME_INPUTS / "holdout_corporate_action_runtime_hard_stops.csv"
    )
    off_session_guards = pd.read_csv(
        RUNTIME_INPUTS / "off_session_accepted_action_runtime_guards.csv"
    )
    hard_stops = pd.concat([hard_stops, off_session_guards], ignore_index=True, sort=False)
    identity = pd.read_parquet(PROCESSED / "security_identity_holdout/dated_security_identity.parquet")
    settlement = pd.read_parquet(PROCESSED / "nse_settlement_calendar_holdout.parquet")
    settling = sorted(pd.to_datetime(settlement.loc[settlement["settlement_business_day"], "date"]).dt.date)
    return {
        "events": events,
        "rights": rights_evidence.set_index("event_id").to_dict("index"),
        "received_security_evidence": received_evidence.set_index("event_id").to_dict("index"),
        "settling": settling,
        "hard_stops": hard_stops,
        "dated_identity": identity,
        "operational_notices": [],
        "manifest_hash": manifest_hash,
    }


def run_sealed_bundle(selections: dict, sessions: list, exposures_by_account: dict,
                      panel: pd.DataFrame, manifest_hash: str, output_dir: Path) -> dict:
    """Publish account artifacts only after all four accounts finish.

    The caller must construct frozen-strategy holdout selections and exposures
    during the real sealed run. This function does not calculate either.
    """
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite a holdout bundle: {output_dir}")
    if set(exposures_by_account) != set(OPENING_STATES):
        raise ValueError("A complete four-account exposure bundle is required")
    if not sessions or sessions[0].isoformat() != "2023-04-03" or sessions[-1].isoformat() != "2026-03-30":
        raise ValueError("Unexpected holdout session range")
    common = load_account_common(manifest_hash)
    with tempfile.TemporaryDirectory(prefix="brindco_holdout_") as temporary:
        staged = Path(temporary)
        results = {}
        for name in OPENING_STATES:
            opening = json.loads(OPENING_STATES[name].read_text(encoding="utf-8"))
            try:
                result = run_account(
                    name, selections, sessions, exposures_by_account[name], panel, common,
                    output_dir=staged, scenario="FROZEN_HOLDOUT_CONTINUATION",
                    opening_snapshot=opening,
                )
            except Exception as exc:
                blocked = {"status": "BLOCKED", "account": name,
                           "reason": "ACCOUNT_RUN_EXCEPTION", "error_type": type(exc).__name__,
                           "detail": str(exc)[:500]}
                path = ROOT / "results/holdout_bundle_blocker.json"
                path.write_text(json.dumps(blocked, indent=2) + "\n", encoding="utf-8")
                return blocked
            if result["blocker"] is not None:
                blocker = result["blocker"]
                # Never publish partial NAV or exposure diagnostics on failure.
                blocked = {"status": "BLOCKED", "account": name,
                           "date": str(blocker.get("date")),
                           "event_id": blocker.get("event_id"),
                           "security_id": blocker.get("security_id"),
                           "symbol": blocker.get("symbol"),
                           "reason": blocker.get("reason"),
                           "detail": blocker.get("detail"),
                           "source_reason": blocker.get("source_reason")}
                path = ROOT / "results/holdout_bundle_blocker.json"
                path.write_text(json.dumps(blocked, indent=2) + "\n", encoding="utf-8")
                return blocked
            results[name] = result
        shutil.move(str(staged), str(output_dir))
        return {"status": "COMPLETE", "accounts": sorted(results)}
