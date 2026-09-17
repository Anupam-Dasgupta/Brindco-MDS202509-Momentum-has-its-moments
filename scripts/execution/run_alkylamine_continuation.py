"""Run the development accounts with the verified ALKYLAMINE split treatment."""

import hashlib

from brindco_momentum.execution.development_accounts import ROOT, main


if __name__ == "__main__":
    evidence = ROOT / "results/accounts_development/passive_lapse_rights_alkylamine_cil_scenario/evidence"
    expected = {
        "ALKYLAMINE_FY2021_22_annual_report.pdf":
            "e659a0f55d3ffe29ae58b48fc6700d4cf30da3ed67dcd11a3ba01640f737da93",
        "ALKYLAMINE_2021_05_27_results.pdf":
            "6df1a5cd002da8246b9dfb7ab280317e4ff58b44adf13c32d4a67a1212f4af06",
    }
    for filename, digest in expected.items():
        if hashlib.sha256((evidence / filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Official ALKYLAMINE evidence changed: {filename}")
    main(
        output_dir=ROOT / "results/accounts_development/passive_lapse_rights_alkylamine_cil_scenario",
        scenario="PASSIVE_LAPSE_RIGHTS_ALKYLAMINE_CIL_SCENARIO",
        enable_alkylamine_cil=True,
    )
