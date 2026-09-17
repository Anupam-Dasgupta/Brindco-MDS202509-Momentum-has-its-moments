# Primary shadow portfolio and signal-sensitivity audit

The primary selection rule is frozen as `STRICT_AUDITABLE_SIGNAL_PRIMARY`. For each official formation-date NIFTY 500 member, a missing required t−12 through t−2 economic return makes that security ineligible **for that formation only**. The existing momentum pipeline already applied this rule and recomputed the eligible count `N`, `K = ceil(0.10 × N)`, ranks, and deterministic winners. This stage confirmed its output hashes against the accepted event-resolution build; it did not overwrite those primary artifacts. The dated rationale is in [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md). A data-availability exclusion is not a claim that the security's missing entitlement was worthless or that a complete historical-universe result has been proved.

## Separate zero-entitlement signal sensitivity

[`zero_entitlement_sensitivity.py`](zero_entitlement_sensitivity.py) constructed a separate scenario for the **30** still-unresolved economic event days. It sets only their unresolved increment to zero, retains any separately accepted same-day share/cash/entitlement effects, and requires a real positive close, valid previous canonical close, valid price return, and no unrelated unresolved action on that day. Missing sessions, identities, anchors, quotes, and the four accepted strict bonus-debenture daily exceptions remain invalid. No primary return, panel, monthly feature, formation, or winner artifact changed.

| Signal comparison | Count |
| --- | ---: |
| Formations with changed eligible `N` | 71 |
| Formations with changed top-decile `K` | 18 |
| Sensitivity winner entries | 19 |
| Sensitivity winner exits | 1 |

Only one newly eligible unresolved-event security directly enters the sensitivity winner set: **TATACOMM at the 2020-08-31 formation**. Other entries arise from seat-count or ranking changes; the single exit is GARFIBRES at that same formation. This scenario demonstrates selection dependence, not an audited alternative economic history. Its three outputs are under [`data/processed/sensitivity/`](data/processed/sensitivity/), and the per-formation comparison is [`results/shadow_audit/primary_vs_zero_signal_changes.csv`](results/shadow_audit/primary_vs_zero_signal_changes.csv). No sensitivity portfolio return was calculated.

## Primary shadow construction

[`shadow_portfolio.py`](shadow_portfolio.py) follows the accepted primary winners chronologically. The first evidenced formation is **2014-08-28**, with the first rebalance at the next canonical NSE session's raw opening reference on **2014-09-01**. The gross reference book uses equal opening value per selected winner and fractional synthetic units. Between rebalances, units and weights drift with the corrected strict daily total returns; cash distributions and evidenced entitlements are reflected through that audited return series. A rebalance gives the old book the prior-close-to-open move, then gives the new book only the open-to-close move. The new basket is never applied backward.

The shadow completed **44** monthly rebalances and **886** valid daily returns from 2014-09-01 through 2018-04-04. Its file contains a 887th dated row on 2018-04-05 with an unavailable return and NAV. No prior close was substituted for a missing opening quote. A same-day entitlement lacking an evidenced opening value would also block an affected rebalance rather than being assigned its closing value at the open. The holdings and daily series are [`primary_shadow_holdings.parquet`](data/processed/primary_shadow_holdings.parquet) and [`primary_shadow_daily_returns.parquet`](data/processed/primary_shadow_daily_returns.parquet).

The March 2015 scored formation has **142 genuinely observed canonical-session shadow daily returns**, exceeding the required 126. Thus `WARMUP_GATE = PASS`. Membership was not inferred before 2014-08-28; the first holding month is September 2014. The 142-session count is based on actual exchange sessions, including the first open-to-close trading day and no invented prior-stock exposure.

## Held daily-return blocker

On **2018-04-05**, the shadow held **ADANIENT** (permanent security `NSE_42CD50DCCBD6`) at **1.8914%** of prior close wealth. Its `SCHEME OF ARRANGEMENT` action `CA_09d4133ad6ad9024fa83` has no accepted daily economic treatment. This event was not one of the 30 remaining signal-priority cases: it falls in an actual holding month and reveals a distinct **daily shadow-risk** dependency. The strict return is unavailable, so the 2018-04-05 shadow return and wealth are left null and the path stops. No price return, zero-entitlement scenario, or monthly delayed-recognition value was inserted into the primary shadow.

A 126-session trailing window containing this date can first end on 2018-04-05 and last end on **2018-10-05**. The directly affected monthly formation dates are 2018-04-30, 2018-05-31, 2018-06-29, 2018-07-31, 2018-08-31, and 2018-09-28. Because the shadow path itself stops at the event, later risk histories also cannot be certified by this build. The exact event, weight, reason, and window dates are in [`results/shadow_audit/unavailable_daily_return_materiality.csv`](results/shadow_audit/unavailable_daily_return_materiality.csv).

For the four preserved bonus-debenture strict daily exceptions, BLUEDART (2014-11-17) and NTPC (2015-03-20) were not held on their ex-dates. The two later BRITANNIA dates are marked **not assessable after the earlier ADANIENT blocker**; they are not falsely labelled unheld. The accepted narrow monthly delayed-recognition signal treatment was unchanged and was never used to fill a daily shadow return.

## Reconciliation and limits

The [rebalance summary](results/shadow_audit/rebalance_summary.csv), [daily completeness file](results/shadow_audit/shadow_daily_return_completeness.csv), [materiality file](results/shadow_audit/unavailable_daily_return_materiality.csv), and [warm-up summary](results/shadow_audit/warmup_summary.csv) provide the arithmetic and gate records. The maximum value-bearing market date read was **2023-03-31**; no later market value or holdout strategy result was accessed. The shadow output itself stops at the 2018 blocker.

Focused tests: **6 passed**. Full repository suite: **117 passed**. No 126-session volatility estimate, exposure rule, implementable account, costs, taxes, performance statistic, benchmark comparison, or holdout evaluation was produced.

**Gate:** The early 126-session warm-up passes, but a complete development primary shadow and subsequent volatility overlay are **blocked** by the held ADANIENT daily return. The remaining signal exclusions and the zero-entitlement scenario must remain explicit limitations of any later strategy claim. Work stops at this gate pending a separate treatment decision or new evidence for that specific held event.

## Later modelling-shadow continuation (2026-09-17)

The strict shadow and the original audit findings above remain unchanged as historical audit references. A separate development modelling shadow now uses an explicitly flagged zero-incremental-entitlement assumption for held ADANIENT. The official HGS filing separately establishes its 2022-02-22 1:1 bonus and ₹28 dividend payable on **pre-bonus** holdings, so the modelling shadow combines those verified ordinary legs rather than using the raw price return. The continuation is documented in [`VOLATILITY_OVERLAY_AUDIT.md`](VOLATILITY_OVERLAY_AUDIT.md) and the frozen decision in [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md). The strict source return and strict shadow artifacts have not been rewritten.

The modelling shadow subsequently encountered EASEMYTRIP's 2022-11-21 split-plus-bonus event. A separately verified eightfold share transformation, with no cash, now carries that modelling shadow through **2023-03-31**. This later result does not alter the original strict shadow stop or its historical audit findings.
