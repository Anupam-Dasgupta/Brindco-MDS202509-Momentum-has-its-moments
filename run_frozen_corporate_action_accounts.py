"""Replay development MOM and VM with the frozen event engine and exit policy."""

from development_accounts import ROOT, main


if __name__ == "__main__":
    main(
        output_dir=ROOT / "results/accounts_development/frozen_corporate_action_scenario",
        scenario="FROZEN_CORPORATE_ACTION_FRAMEWORK",
        enable_alkylamine_cil=True,
        enable_unominda_2018=True,
    )
