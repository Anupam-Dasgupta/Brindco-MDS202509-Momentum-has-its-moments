import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from brindco_momentum.execution import control_accounts, development_accounts


def example_inputs(exposures=(0.25, 0.75), returns=(0.1, -0.2)):
    dates = pd.to_datetime(["2015-04-01", "2015-05-04"])
    overlay = pd.DataFrame({
        "formation_date": pd.to_datetime(["2015-03-31", "2015-04-30"]),
        "holding_month": ["2015-04", "2015-05"], "is_scored": [True, True],
        "risk_estimate_available": [True, True], "risk_status": ["VALID", "VALID"],
        "exposure": exposures,
    })
    shadow = pd.DataFrame({"date": dates, "shadow_daily_return": returns,
                           "valid_return": [True, True]})
    return overlay, shadow, list(dates.date)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def test_control_calibrations_use_frozen_exposures_and_gross_shadow():
    overlay, shadow, sessions = example_inputs()
    definitions, reference = control_accounts.calibrate(overlay, shadow, sessions)
    expected_vm = np.array([0.025, -0.15])
    numerator = float(np.std(expected_vm, ddof=1))
    denominator = float(np.std([0.1, -0.2], ddof=1))
    assert definitions["FIX"]["allocation"] == 0.5
    assert definitions["FIX"]["valid_vm_monthly_targets"] == 2
    np.testing.assert_allclose(reference.vm_gross_reference_daily_return, expected_vm, rtol=0, atol=1e-15)
    assert definitions["FIXVOL"]["numerator_daily_sd"] == pytest.approx(numerator)
    assert definitions["FIXVOL"]["denominator_daily_sd"] == pytest.approx(denominator)
    assert definitions["FIXVOL"]["uncapped_ratio"] == pytest.approx(numerator / denominator)
    assert definitions["FIXVOL"]["allocation"] == pytest.approx(min(1, numerator / denominator))


def test_only_valid_monthly_vm_targets_enter_fix_mean_and_fixvol_is_capped():
    overlay, shadow, sessions = example_inputs((1.0, 0.0), (0.2, 0.21))
    overlay.loc[1, "risk_estimate_available"] = False
    overlay.loc[1, "risk_status"] = "NONPOSITIVE_VOLATILITY"
    definitions, reference = control_accounts.calibrate(overlay, shadow, sessions)
    assert definitions["FIX"]["valid_vm_monthly_targets"] == 1
    assert definitions["FIX"]["allocation"] == 1.0
    assert definitions["FIXVOL"]["uncapped_ratio"] > 1.0
    assert definitions["FIXVOL"]["allocation"] == 1.0
    assert reference.vm_gross_reference_daily_return.iloc[1] == 0.0


def test_calibration_rejects_missing_or_post_cutoff_shadow():
    overlay, shadow, sessions = example_inputs()
    with pytest.raises(ValueError, match="Incomplete or noncanonical"):
        control_accounts.calibrate(overlay, shadow.iloc[:1], sessions)
    shadow.loc[1, "date"] = pd.Timestamp("2023-04-03")
    sessions[1] = pd.Timestamp("2023-04-03").date()
    overlay.loc[1, "holding_month"] = "2023-04"
    overlay.loc[1, "formation_date"] = pd.Timestamp("2023-03-31")
    with pytest.raises(ValueError, match="Incomplete or noncanonical"):
        control_accounts.calibrate(overlay, shadow, sessions)


def test_controls_call_the_existing_account_engine():
    assert control_accounts.run_account is development_accounts.run_account


@pytest.mark.parametrize("name", ["FIX", "FIXVOL"])
def test_saved_controls_preserve_winners_and_reconcile(name):
    account_dir = control_accounts.OUT / name
    if not (account_dir / "account_run_summary.csv").exists():
        pytest.skip("Development controls have not been run")
    schedule = pd.read_csv(account_dir / "target_exposure_schedule.csv")
    definition = json.loads((account_dir / "control_definition.json").read_text())
    manifest = pd.read_csv(account_dir / "input_manifest.csv").set_index("input")
    frozen = pd.read_csv(control_accounts.FROZEN_ACCOUNTS / "input_manifest.csv").set_index("input")
    assert len(schedule) == 96 and schedule.target_exposure.nunique() == 1
    assert schedule.target_exposure.iloc[0] == pytest.approx(definition["allocation"])
    assert 0 <= definition["allocation"] <= 1
    for source in ("winners", "overlay"):
        assert manifest.loc[source, "sha256"] == frozen.loc[source, "sha256"]
    overlay = pd.read_parquet(
        control_accounts.INPUTS["overlay"],
        columns=["formation_date", "holding_month", "is_scored", "risk_estimate_available",
                 "risk_status", "exposure"],
        filters=[("formation_date", "<=", control_accounts.CUTOFF), ("is_scored", "=", True)],
    )
    assert schedule.holding_month.tolist() == overlay.sort_values("formation_date").holding_month.astype(str).tolist()
    if name == "FIX":
        valid = overlay.risk_estimate_available & overlay.risk_status.eq("VALID") & overlay.exposure.gt(0)
        assert definition["valid_vm_monthly_targets"] == int(valid.sum()) == 96
        assert definition["allocation"] == float(overlay.loc[valid, "exposure"].mean())
    else:
        reference = pd.read_parquet(control_accounts.OUT / "vm_gross_reference_daily_returns.parquet")
        assert len(reference) == 1982 and reference.date.max() == control_accounts.CUTOFF
        expected_vm = reference.vm_target_exposure * reference.mom_shadow_daily_return
        pd.testing.assert_series_equal(reference.vm_gross_reference_daily_return, expected_vm,
                                       check_names=False)
        numerator = float(expected_vm.std(ddof=1))
        denominator = float(reference.mom_shadow_daily_return.std(ddof=1))
        assert definition["numerator_daily_sd"] == numerator
        assert definition["denominator_daily_sd"] == denominator
        assert definition["uncapped_ratio"] == numerator / denominator
        assert definition["allocation"] == min(1.0, numerator / denominator)
    summary = pd.read_csv(account_dir / "account_run_summary.csv").iloc[0]
    nav = pd.read_parquet(account_dir / f"{name}_nav_daily.parquet",
                          columns=["date", "reconciliation_error"])
    assert summary.last_valid_date == "2023-03-31"
    assert summary.valid_daily_nav_rows == len(nav) == 1982
    assert summary.maximum_value_bearing_market_date_read == "2023-03-31"
    assert nav.reconciliation_error.abs().max() < 1e-6
    assert pd.Timestamp(nav.date.max()) == pd.Timestamp("2023-03-31")

    rerun = control_accounts.OUT / "rerun" / name
    if rerun.exists():
        for path in account_dir.iterdir():
            other = rerun / path.name
            assert other.exists()
            if path.suffix == ".json":
                assert json.loads(path.read_text()) == json.loads(other.read_text())
            else:
                assert digest(path) == digest(other)


def test_frozen_mom_vm_artifacts_are_unchanged():
    baseline = control_accounts.OUT / "frozen_mom_vm_before.csv"
    if not baseline.exists():
        pytest.skip("Development controls have not been run")
    for row in pd.read_csv(baseline).itertuples(index=False):
        assert digest(control_accounts.FROZEN_ACCOUNTS / row.path) == row.sha256
