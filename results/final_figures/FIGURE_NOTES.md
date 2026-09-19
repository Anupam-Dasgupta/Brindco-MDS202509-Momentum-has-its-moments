# Final figure notes

All plotted account paths are completed executable, post-cost/post-tax holdout results. The benchmark is the published NIFTY 500 total-return index (TRI), which is not an executable after-tax account. No strategy, account, or development artifact was recomputed or changed.

The wealth chart uses **holdout only**. Development and holdout account paths have different opening-state treatment, including the evidence-backed UPL bonus correction, so this report does not splice the two accounting series. The plotted holdout starts at the frozen 2023-03-31 closing state; the first trading return is 2023-04-03.

## Figure 1 — `01_cumulative_wealth`

- Sources: regenerated `results/accounts_holdout/frozen_bundle/{MOM,VM,FIX,FIXVOL}_nav_daily.parquet` (`date`, `nav`); `results/holdout_summary.csv` (`start_nav`); `data/processed/nifty500_tri_2013_2026.parquet` (`date`, `tri`).
- Period: 2023-03-31 opening anchor to 2026-03-30; 742 holdout trading sessions from 2023-04-03.
- Normalization: account NAV / its own frozen opening NAV; TRI / its 2023-03-31 value. All start at ₹1. No summary statistics were used to synthesize a path.
- Interpretation: MOM accumulated the most holdout wealth; VM grew less than both fixed-allocation controls.

## Figure 2 — `02_holdout_drawdowns`

- Sources: same account NAV files and `start_nav` values as Figure 1; no benchmark drawdown is plotted.
- Period: 2023-03-31 opening anchor to 2026-03-30, holdout only.
- Calculation: plotted wealth divided by its running maximum minus one, with the frozen opening NAV included in the initial peak.
- Interpretation: VM's worst drawdown was shallower than those of MOM, FIX, and FIXVOL.

## Figure 3 — `03_volatility_overlay_mechanism`

- Sources: `results/accounts_holdout/frozen_bundle/producer_inputs/risk.parquet` (`formation_date`, `holding_month`, `sigma_hat`, `volatility_target`, `exposure`, `risk_window_start`, `risk_window_end`, `sum_squared_daily_returns`, `shadow_returns_used`, `risk_status`); `results/accounts_holdout/frozen_bundle/producer_inputs/shadow.parquet` (`date`, `shadow_daily_return`, `valid_return`) for validation.
- Period: 36 monthly formation decisions from 2023-03-31 (April 2023 holding month) through 2026-02-27 (March 2026 holding month); holdout only. Horizontal steps indicate the monthly decision held until the next formation, not interpolated daily decisions.
- Formula: the frozen estimate is `sqrt(252/126 × sum(last 126 shadow daily returns squared))`; exposure is `min(1, 0.12 / sigma_hat)` for valid positive volatility. The dashed horizontal reference is the frozen 12% target.
- Interpretation: higher estimated shadow volatility lowered VM's equity allocation, with the remainder assigned to cash.

## Figure 4 — `04b_holdout_cost_tax_drag`

- Source: `results/holdout_summary.csv` (`annualised_implementation_cost_drag`, `annualised_tax_drag`); definitions in `METHODOLOGY.md`.
- Period: 2023-04-03 to 2026-03-30; holdout only.
- Definition: cost and tax drags are CAGR differences on matched executable account paths. They are not additive return contributions or a counterfactual re-run with different trades. Solid bars represent cost drag; hatched bars represent tax drag. Numeric bar labels are percentage points.
- Interpretation: all four accounts incurred material tax drag alongside implementation costs.

## Validation

Account final NAVs and max drawdowns from the plotted paths were checked against `summary_metrics.csv`; every difference was within the stated tolerances (₹0.000001 for NAV, 1e-10 for drawdown). Every plotted VM formation was checked against the actual 126 shadow returns and the frozen 12% exposure rule (tolerance 1e-12). The source hashes below were checked again after rendering and were unchanged.

- `MOM_final_nav_abs_error_inr`: 0
- `MOM_max_drawdown_abs_error`: 0
- `VM_final_nav_abs_error_inr`: 0
- `VM_max_drawdown_abs_error`: 5.55e-17
- `FIX_final_nav_abs_error_inr`: 0
- `FIX_max_drawdown_abs_error`: 0
- `FIXVOL_final_nav_abs_error_inr`: 0
- `FIXVOL_max_drawdown_abs_error`: 2.78e-17
- `vm_sigma_max_abs_error`: 0
- `vm_exposure_max_abs_error`: 0

## Source file hashes

- `results/holdout_summary.csv` — SHA-256 `e3499520b1e1e3ac21535b562ee5a2c9a2a349951d1d2c82645abf87e5de3c11`
- `data/processed/nifty500_tri_2013_2026.parquet` — SHA-256 `c31974156ddf76c2875ae9582c76d1e81f891c882f7ed15551f3353e66000682`
- `results/accounts_holdout/frozen_bundle/producer_inputs/risk.parquet` — SHA-256 `ac66ea689bb110ef4e8b99d63951c8d2192c7419475ee8e2a4d975c6fef3f85e`
- `results/accounts_holdout/frozen_bundle/producer_inputs/shadow.parquet` — SHA-256 `20d450c278194ebd5b13bf41e312da5376323c1a6b6ae676d88ffd074552dcf4`
- `results/accounts_holdout/frozen_bundle/MOM_nav_daily.parquet` — SHA-256 `3c051047a5004d22aa027105a21f437c674c64599e0e6003129e850e27511466`
- `results/accounts_holdout/frozen_bundle/VM_nav_daily.parquet` — SHA-256 `4cd3aa2a3c1ac278f0d6050fb0f3d2cd9b85127edd1fd64434ef6caf76fdac9e`
- `results/accounts_holdout/frozen_bundle/FIX_nav_daily.parquet` — SHA-256 `fef8a0747ba94537e7a035d93abc1bf6881410321315f2e96927938e42d4a1c1`
- `results/accounts_holdout/frozen_bundle/FIXVOL_nav_daily.parquet` — SHA-256 `66e612c8bfe46c7a05b9cae8ab7a7dbf1345ebf133ec2471928e6d945aabddb5`

Rendering code: `brindco_momentum.evaluation.final_figures` (Matplotlib 3.11.1). Each figure is saved as a 300-dpi PNG.
