# Development control construction audit

FIX and FIXVOL reuse the frozen monthly momentum winner sets and the existing
executable account runner. They change only the target equity exposure. Both
controls were calibrated and run within the development period ending
2023-03-31. No holdout observations or performance results were used.

## Calibration

FIX uses the arithmetic mean of the 96 valid, scored monthly VM target
exposures from 2015-04 through 2023-03:

```
FIX allocation = 0.5995134123578113
```

FIXVOL uses the sample standard deviation (`ddof=1`) of two aligned gross
daily reference-return series over the same development period:

```
VM gross reference return[t] = VM target exposure[holding month(t)]
                               * MOM modelling shadow return[t]
FIXVOL allocation = min(1, sd(VM gross reference) / sd(MOM modelling shadow))
                  = min(1, 0.008632095091121457 / 0.013711830079815078)
                  = 0.6295363230783175
```

The inputs are the scored VM exposure schedule in
`data/processed/volatility_overlay_development.parquet`, valid daily returns in
`data/processed/primary_modelling_shadow_daily_returns.parquet`, and the
canonical development trading calendar. The frozen project did not contain a
separate full-period VM gross daily-reference artifact, so the run saves the
explicitly derived, aligned 1,982-row series at
`results/controls_development/vm_gross_reference_daily_returns.parquet`.
This is a zero-return-cash, common-return reference convention as described in
plan.md section 14.4. The monthly target applies to the first session's
close-to-close return of its holding month. It is a simplified gross reference,
not the executable VM account's after-cost, tax, or settlement return. This
timing convention should remain visible when interpreting the control.

Each calibrated allocation is constant in its account run, capped at one,
and recorded with input hashes and a monthly target schedule. Calibration
uses completed development-period VM targets as a fixed control definition;
the executable run does not recalculate that allocation using future account
observations.

## Construction checks

| Check | FIX | FIXVOL |
| --- | ---: | ---: |
| Last valid account date | 2023-03-31 | 2023-03-31 |
| Daily NAV rows | 1,982 | 1,982 |
| Account blocker | None | None |
| Maximum NAV reconciliation residual | 0 | 0 |
| Maximum value-bearing market date read | 2023-03-31 | 2023-03-31 |

The unchanged account runner supplied the same execution, tax, settlement,
corporate-action, and accounting rules used by MOM and VM. The control tests
verified identical winner inputs, unchanged frozen MOM/VM artifact hashes,
and byte-identical replay outputs (with semantic equality for JSON objects).
The full test suite passed: **182 tests**. Outputs and per-account manifests are
under `results/controls_development/FIX/` and
`results/controls_development/FIXVOL/`; the isolated deterministic replay is
under `results/controls_development/rerun/`.

This audit covers construction and account reconciliation only. It does not
evaluate portfolio performance or holdout results.
