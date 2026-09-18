"""Calibrate and run the two frozen development equity/cash controls."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brindco_momentum.data.settlement_calendar import CUTOFF, START
from brindco_momentum.execution.development_accounts import INPUTS, ROOT, _hash, inputs, run_account


OUT = ROOT / "results/controls_development"
FROZEN_ACCOUNTS = ROOT / "results/accounts_development/frozen_corporate_action_scenario"
MODELLING_SHADOW = ROOT / "data/processed/primary_modelling_shadow_daily_returns.parquet"


def calibrate(overlay: pd.DataFrame, shadow: pd.DataFrame,
              sessions: list) -> tuple[dict, pd.DataFrame]:
    """Use the plan's zero-return-cash gross reference, before all account frictions."""
    targets = overlay.copy()
    targets["holding_month"] = targets["holding_month"].astype(str)
    if (targets.empty or targets.holding_month.duplicated().any()
            or not targets.is_scored.eq(True).all()
            or targets.formation_date.max() > CUTOFF
            or not np.isfinite(targets.exposure).all()
            or targets.exposure.lt(0).any() or targets.exposure.gt(1).any()):
        raise ValueError("Invalid frozen VM target exposure schedule")
    months = [day.strftime("%Y-%m") for day in sessions]
    if set(months) != set(targets.holding_month):
        raise ValueError("VM targets do not cover every development holding month")
    valid = (targets.risk_estimate_available.eq(True)
             & targets.risk_status.eq("VALID")
             & targets.exposure.gt(0))
    if not valid.any():
        raise ValueError("No valid development VM targets for FIX calibration")
    fixed = float(targets.loc[valid, "exposure"].mean())

    expected_dates = pd.DatetimeIndex(sessions)
    if (len(shadow) != len(sessions) or shadow.date.duplicated().any()
            or not pd.DatetimeIndex(shadow.date).equals(expected_dates)
            or shadow.date.max() > CUTOFF or shadow.date.min() < START
            or not shadow.valid_return.eq(True).all()
            or not np.isfinite(shadow.shadow_daily_return).all()):
        raise ValueError("Incomplete or noncanonical development MOM shadow returns")

    exposure_by_month = targets.set_index("holding_month")["exposure"]
    reference = pd.DataFrame({
        "date": shadow.date.to_numpy(),
        "holding_month": months,
        "mom_shadow_daily_return": shadow.shadow_daily_return.to_numpy(),
    })
    reference["vm_target_exposure"] = reference.holding_month.map(exposure_by_month)
    if reference.vm_target_exposure.isna().any():
        raise ValueError("Missing VM exposure on a canonical session")
    # This is the plan's simplified common-return reference with zero-return cash.
    reference["vm_gross_reference_daily_return"] = (
        reference.vm_target_exposure * reference.mom_shadow_daily_return
    )
    numerator = float(reference.vm_gross_reference_daily_return.std(ddof=1))
    denominator = float(reference.mom_shadow_daily_return.std(ddof=1))
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator <= 0:
        raise ValueError("Undefined development gross-reference volatility ratio")
    ratio = numerator / denominator
    definitions = {
        "FIX": {"allocation": fixed, "valid_vm_monthly_targets": int(valid.sum())},
        "FIXVOL": {"allocation": min(1.0, ratio),
                   "numerator_daily_sd": numerator, "denominator_daily_sd": denominator,
                   "uncapped_ratio": ratio},
    }
    return definitions, reference


def run_controls(output_root: Path = OUT) -> None:
    frozen_before = {path.relative_to(FROZEN_ACCOUNTS).as_posix(): _hash(path)
                     for path in sorted(FROZEN_ACCOUNTS.rglob("*")) if path.is_file()}
    selections, sessions, vm_exposures, panel, common = inputs()
    shadow_hash = _hash(MODELLING_SHADOW)
    overlay = pd.read_parquet(
        INPUTS["overlay"],
        columns=["formation_date", "holding_month", "is_scored", "risk_estimate_available",
                 "risk_status", "exposure"],
        filters=[("formation_date", "<=", CUTOFF), ("is_scored", "=", True)],
    )
    shadow = pd.read_parquet(
        MODELLING_SHADOW, columns=["date", "shadow_daily_return", "valid_return"],
        filters=[("date", ">=", START), ("date", "<=", CUTOFF)],
    )
    definitions, reference = calibrate(overlay, shadow, sessions)
    if (set(selections) != set(vm_exposures)
            or any(vm_exposures[month] != value for month, value in
                   overlay.set_index(overlay.holding_month.astype(str)).exposure.items())):
        raise ValueError("Control calibration differs from frozen VM account targets")

    output_root.mkdir(parents=True, exist_ok=True)
    reference.to_parquet(output_root / "vm_gross_reference_daily_returns.parquet", index=False)
    pd.DataFrame([{"path": name, "sha256": digest} for name, digest in frozen_before.items()]).to_csv(
        output_root / "frozen_mom_vm_before.csv", index=False
    )
    source_hashes = {**common["hashes"], "modelling_shadow": shadow_hash}
    input_paths = {**INPUTS, "modelling_shadow": MODELLING_SHADOW}
    for name in ("FIX", "FIXVOL"):
        account_dir = output_root / name
        account_dir.mkdir(parents=True, exist_ok=True)
        manifest = pd.DataFrame([
            {"input": key, "path": path.relative_to(ROOT).as_posix(), "sha256": source_hashes[key]}
            for key, path in input_paths.items()
        ])
        manifest.to_csv(account_dir / "input_manifest.csv", index=False)
        schedule = overlay[["formation_date", "holding_month"]].sort_values("formation_date").copy()
        schedule["target_exposure"] = definitions[name]["allocation"]
        schedule.to_csv(account_dir / "target_exposure_schedule.csv", index=False)
        definition = {
            "account": name, **definitions[name], "development_start": START.date().isoformat(),
            "development_end": CUTOFF.date().isoformat(),
            "vm_targets": "data/processed/volatility_overlay_development.parquet:exposure",
            "mom_shadow": "data/processed/primary_modelling_shadow_daily_returns.parquet:shadow_daily_return",
            "vm_gross_reference": "../vm_gross_reference_daily_returns.parquet:vm_gross_reference_daily_return",
            "reference_convention": "monthly VM target times daily MOM modelling-shadow return; zero-return cash",
            "rebalance_day_convention": "holding-month target applies to the whole daily shadow return",
            "standard_deviation_ddof": 1,
        }
        (account_dir / "control_definition.json").write_text(json.dumps(definition, indent=2))
        control_exposures = {month: definitions[name]["allocation"] for month in selections}
        account_common = {**common, "manifest_hash": _hash(account_dir / "input_manifest.csv")}
        result = run_account(name, selections, sessions, control_exposures, panel, account_common,
                             account_dir, "FROZEN_CORPORATE_ACTION_FRAMEWORK",
                             enable_alkylamine_cil=True, enable_unominda_2018=True)
        pd.DataFrame([{**result, "blocker": json.dumps(result["blocker"], default=str)}]).to_csv(
            account_dir / "account_run_summary.csv", index=False
        )
        print(f"{name}: {result['valid_daily_nav_rows']} NAV rows through {result['last_valid_date']}; "
              f"blocker={result['blocker']}")

    if {_key: _hash(path) for _key, path in input_paths.items()} != source_hashes:
        raise ValueError("Frozen control input changed during run")
    frozen_after = {path.relative_to(FROZEN_ACCOUNTS).as_posix(): _hash(path)
                    for path in sorted(FROZEN_ACCOUNTS.rglob("*")) if path.is_file()}
    if frozen_after != frozen_before:
        raise ValueError("Frozen MOM/VM artifact changed during control run")


if __name__ == "__main__":
    run_controls()
