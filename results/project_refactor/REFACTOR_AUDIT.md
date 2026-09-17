# Structural refactor regression audit

This change moved reusable code into `src/brindco_momentum/` and added thin
stage scripts. No signal, portfolio, execution, tax, settlement, or
corporate-action calculations were changed.

- Baseline before the move: 173 tests passed. Final suite: 175 tests passed.
- `pip install -e .` succeeded in the project environment; `pip check`
  reported no broken requirements. The new tests import the package from
  outside the repository working directory.
- The 177 frozen original files recorded in `baseline_sha256.csv` still match
  their pre-refactor SHA-256 hashes.
- The independent MOM/VM development replay reached 2023-03-31 for both
  accounts, with 1,982 daily NAV rows per account, no blocker, and zero NAV
  reconciliation error.
- The replay input manifest is byte-identical to the frozen manifest. This
  includes the saved winner-set and VM-exposure input hashes.
- Of 27 replayed output files, 25 are byte-identical to the frozen files.
  `MOM_state.json` and `VM_state.json` parse to exactly the same objects as
  their frozen counterparts; their raw bytes differ only because the
  `last_marks` dictionary keys were serialized in a different order. The
  account engine and frozen output files were not modified to force a new
  serialization order.
- Maximum value-bearing market date read by either account: 2023-03-31.
  No holdout performance was examined.

The file-level comparison, including expected and replay hashes, is in
`regression_report.csv`. The independent replay is under
`results/project_refactor/reproduced_accounts/`; the accepted account files
remain under `results/accounts_development/frozen_corporate_action_scenario/`.
