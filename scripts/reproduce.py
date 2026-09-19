"""Reproduce the submitted Brindco development and holdout results."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brindco_momentum.evaluation.development import evaluate as evaluate_development
from brindco_momentum.evaluation.final_figures import main as make_figures
from brindco_momentum.evaluation.holdout import main as evaluate_holdout
from brindco_momentum.execution.control_accounts import run_controls
from brindco_momentum.execution.development_accounts import main as run_development
from brindco_momentum.holdout_run import main as run_holdout
from brindco_momentum.portfolio.shadow_portfolio import build_primary_shadow
from brindco_momentum.portfolio.volatility_overlay import build_overlay
from brindco_momentum.signals.momentum_signal import main as build_momentum


GENERATED_DIRECTORIES = [
    ROOT / "results/momentum_signal_audit",
    ROOT / "results/shadow_audit",
    ROOT / "results/volatility_overlay_audit",
    ROOT / "results/accounts_development",
    ROOT / "results/controls_development",
    ROOT / "results/evaluation_development",
    ROOT / "results/accounts_holdout",
    ROOT / "results/final_figures",
]
GENERATED_DATA = [
    "momentum_monthly_features.parquet",
    "momentum_formations.parquet",
    "momentum_winners.parquet",
    "primary_shadow_holdings.parquet",
    "primary_shadow_daily_returns.parquet",
    "primary_modelling_shadow_holdings.parquet",
    "primary_modelling_shadow_daily_returns.parquet",
    "volatility_overlay_development.parquet",
]


def remove_generated_work() -> None:
    for path in GENERATED_DIRECTORIES:
        if path.exists():
            shutil.rmtree(path)
    blocker = ROOT / "results/holdout_bundle_blocker.json"
    if blocker.exists():
        blocker.unlink()


def validate_submitted_metrics() -> None:
    expected = {
        "MOM": (38.23e6, 0.2471, 0.2105, 1.17, -0.2494),
        "VM": (23.17e6, 0.1605, 0.1508, 1.08, -0.1581),
        "FIX": (27.68e6, 0.1780, 0.1609, 1.12, -0.1922),
        "FIXVOL": (28.77e6, 0.1845, 0.1682, 1.11, -0.2005),
    }
    summary = pd.read_csv(ROOT / "results/holdout_summary.csv").set_index("account")
    for account, values in expected.items():
        actual = summary.loc[account]
        checks = (
            np.isclose(actual.final_nav, values[0], rtol=0, atol=5_000),
            np.isclose(actual.cagr, values[1], rtol=0, atol=0.00005),
            np.isclose(actual.annualised_volatility, values[2], rtol=0, atol=0.00005),
            np.isclose(actual.sharpe_0pct_cash, values[3], rtol=0, atol=0.005),
            np.isclose(actual.max_drawdown, values[4], rtol=0, atol=0.00005),
        )
        if not all(checks):
            raise ValueError(f"Submitted holdout metrics changed for {account}")
    if not np.isclose(summary.nifty500_tri_cagr.iloc[0], 0.1323, rtol=0, atol=0.00005):
        raise ValueError("Submitted NIFTY 500 TRI CAGR changed")


def main() -> None:
    remove_generated_work()
    build_momentum()
    build_primary_shadow()
    build_overlay()

    development_accounts = ROOT / "results/accounts_development/frozen_corporate_action_scenario"
    run_development(
        output_dir=development_accounts,
        scenario="FROZEN_CORPORATE_ACTION_FRAMEWORK",
        enable_alkylamine_cil=True,
        enable_unominda_2018=True,
    )
    run_controls()
    development_evaluation = ROOT / "results/evaluation_development"
    evaluate_development(development_evaluation)
    shutil.copy2(
        development_evaluation / "summary_metrics.csv",
        ROOT / "results/development_summary.csv",
    )

    run_holdout()
    evaluate_holdout()
    make_figures()
    validate_submitted_metrics()

    for path in GENERATED_DIRECTORIES[:-1]:
        if path.exists():
            shutil.rmtree(path)
    for name in GENERATED_DATA:
        path = ROOT / "data/processed" / name
        if path.exists():
            path.unlink()
    print("Reproduction complete: development and holdout summaries and final figures regenerated.")


if __name__ == "__main__":
    main()
