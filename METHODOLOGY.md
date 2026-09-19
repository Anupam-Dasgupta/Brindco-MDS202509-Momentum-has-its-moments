# Final methodology

## Research question and paper translation

Barroso and Santa-Clara's *Momentum Has Its Moments* motivates reducing momentum exposure when past momentum volatility is high. The original paper studies a winners-minus-losers portfolio and permits leverage. This project tests a different, assignment-constrained question: whether **unlevered long-only NIFTY 500 winners plus cash**, scaled by their own prior risk, improve implementable Indian-account outcomes. It uses the paper's volatility-management mechanism, not the paper's portfolio or its estimated performance. The author's Equation 10 erratum multiplies weights by leverage in turnover; here actual executed trades determine costs.

The development period is 2015-04-01 through 2023-03-31. The holdout is 2023-04-03 through 2026-03-30. Securities, signals, and scheduled risk targets are formed using information available at the relevant formation close. The four holdout accounts continue from their frozen 2023-03-31 closing states; no holdout result calibrated a strategy parameter.

## Universe, returns, and momentum

The candidate roster starts with official NIFTY 500 membership intervals under `valid_from <= formation_date < valid_to`. A member with a missing formation observation stays in the roster and fails eligibility visibly. Dated ISIN/symbol lineage identifies the same economic security through name or symbol changes. The accepted historical cash-equity series policy admits EQ and corroborated BE/BZ observations; rights entitlements are separate assets. Original prices are not retrospectively altered.

Monthly security returns use the accepted corporate-action treatment layer. At the close of the last NSE session before holding month *t*, momentum is the compounded total return for months *t−12* through *t−2*, inclusive: **11 monthly returns**, omitting the most recent month. April 2015's signal, for example, uses April 2014–February 2015 and excludes March 2015. A required missing month or starting anchor makes the signal unavailable. No missing return or volume is replaced with zero.

Eligibility requires contemporaneous membership, valid dated identity and series, complete signal history, an actual usable formation-session quote, positive finite lagged 20-session ADV, and at least 15 positive-volume sessions in the preceding 20 NSE sessions. ADV excludes today's observation. The usable quote must be a finite positive close on an accepted cash-equity observation; a carried stale quote is not a formation quote. Eligible securities are ranked by momentum descending, with permanent `security_id` breaking exact ties. The selected count is `ceil(0.10 × eligible_count)`; names are equally weighted. If fewer than 20 usable names remain, the engine does not invent a target book.

Four bonus-debenture ex-date strict daily returns remain explicit exceptions because contemporaneous entitlement values were unavailable. The accepted monthly delayed-recognition feature is narrower than a repaired daily return. Two Britannia events make eight specified formation signals unavailable. These exceptions are recorded rather than silently dropped.

## Shadow portfolio and risk overlay

An unscaled, gross long-only shadow portfolio holds the contemporaneous historical winner sets with fractional units and no execution costs or tax. It is constructed forward through time; it does not apply today's winners to the preceding 126 sessions. The shadow supplies the risk estimate, independently of VM's past exposure. The historical shadow begins before the scored April 2015 account so the first risk window contains 126 actual NSE-session returns.

At each monthly formation date *d*, the frozen second-moment estimator and capped allocation are:

```text
sigma_hat(d) = sqrt((252 / 126) × sum of the last 126 shadow daily returns squared)
VM target equity exposure = min(1, 0.12 / sigma_hat(d))
```

This is **RMS**, not a demeaned rolling standard deviation. Missing, nonfinite, zero, or negative risk estimates target cash with a visible error status. The scheduled exposure is held until the next formation; actual invested exposure can differ because of drift, capacity, settlement, costs, and whole shares. Cash earns 0% in the primary model.

## Four executable accounts

All four accounts use the same monthly winner sleeve and account engine:

| Account | Equity target |
|---|---|
| MOM | 100% |
| VM | Monthly `min(1, 0.12 / sigma_hat)` |
| FIX | Constant mean of valid monthly VM targets in April 2015–March 2023 |
| FIXVOL | Constant `min(1, sd(development VM gross-reference daily returns) / sd(development MOM shadow daily returns))` |

The fixed controls were calibrated on development data only. Their development-period comparisons are in-sample; their holdout allocations were fixed before the holdout run. Neither substitutes executable after-cost returns for the gross-reference series in FIXVOL's calibration.

Formation takes place after the month's last session; trading begins at the next eligible session's raw open. The account targets equal weights within the selected sleeve at its scheduled equity fraction. Orders are whole-share, cash-funded, and deterministic. Sales are processed before purchases, but unsettled sale proceeds cannot finance immediate buys. Outstanding rebalance orders have at most five NSE sessions. One-sided executed notional per security/day is capped at 1% of the **preceding** 20-session rupee ADV. Missing or insufficient ADV does not create fictitious capacity.

Execution applies the accepted fees and a declared impact curve: `I(p) = 10 bps × max(1, sqrt(p / 0.001))` per side, where *p* is order notional divided by lagged ADV. The opening price is a daily-bar approximation, not proof of an available auction fill. Settlement cash availability uses a validated T+2 settlement-business-day calendar, including holidays. Positions, fills, orders, cash, receivables, gains, tax lots, tax liabilities, and daily NAV reconcile in the account ledger.

The tax scenario matches sales to lots FIFO, distinguishes short- and long-term gains at the acquisition anniversary, applies 20% STCG and 12.5% LTCG, and models the ₹125,000 annual LTCG exemption and eligible carried losses within the declared per-account convention. Tax is accrued in NAV and cash is reserved before annual payment. This is a research-account convention, not individualized tax advice.

Corporate actions follow documented holder economics. Cash dividends credit gross declared cash per pre-event share before account-level taxation. Splits and ordinary bonus issues transform share quantity and lot basis. Optional tender/open-market buybacks assume passive nonparticipation. Ordinary rights issues use the accepted passive-holder policy: no subscription capital, a separately tracked entitlement, sale only when actual tradable-rights quotes and normal execution capacity support it, otherwise lapse. Mandatory received securities are tracked separately and remain unpriced until the first accepted observable quote. Unsupported events would stop a held account rather than receive an invented value.

## Metrics and interpretation

Final NAV includes marked shares, settled cash and receivables, less accrued tax liability. CAGR uses elapsed calendar years; performance volatility is the **sample standard deviation** of daily returns times `sqrt(252)`, distinct from the risk signal's RMS. Sharpe uses the declared 0%-cash convention. Maximum drawdown includes starting funded wealth. NIFTY 500 TRI is published index context, not an after-tax implementable portfolio.

Turnover is executed consideration divided by previous recorded close NAV, annualized by session count. Cost and tax drags are **differences in CAGR on matched executed-share account paths** after reversing recorded cash flows; they are not additive contributions or independent counterfactual account reruns. The concise outputs are `results/development_summary.csv` and `results/holdout_summary.csv`.

## Reproducibility boundary and provenance

The compact submission starts from accepted processed research panels rather than shipping the much larger one-off acquisition and reconstruction archive. `research_panel_v2.parquet` ends on 2023-03-31 and contains the accepted development identity, membership, quote, liquidity, and return state. `holdout_execution_panel.parquet` covers 2023-04-03 through 2026-03-30. Official membership intervals, dated holdout identity, accepted corporate-action tables, settlement calendars, holdout opening states, and the NIFTY 500 TRI remain as separate runtime inputs so their timing and economics stay explicit.

The one-command replay recomputes every decision-bearing and economic stage after that boundary: monthly returns and eligibility, deterministic winners, shadow returns, 126-session RMS risk, development accounts and fixed-control calibration, holdout producers and accounts, evaluation, and figures. Compact runtime CSVs preserve the exact evidence terms used for rights issues and VAKRANGEE's received security. The UPL opening-state correction is documented in `data/evidence/UPL_OPENING_STATE.md`; raw public-source URLs and hashes are in `data/raw/OMITTED_SOURCE_MANIFEST.csv`.
