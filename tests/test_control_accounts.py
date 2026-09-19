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


