# Development modelling-shadow and volatility-overlay audit

Status: **complete through 2023-03-31 under the explicitly frozen modelling conventions**. The strict audited daily return series still identifies unavailable economic returns; this modelling series does not turn those values into audited total returns. No executable account, strategy performance, or holdout evaluation was run.

## Treatments and unchanged strict inputs

The accepted strict stock-return series, strict shadow, corporate-action treatment tables, primary winner sets, and earlier strict audit results were not rewritten. Six frozen input hashes, including the strict returns and shadow files, match before and after the rebuild in [`results/volatility_overlay_audit/strict_shadow_hashes.csv`](../../results/volatility_overlay_audit/strict_shadow_hashes.csv). The methodology decisions were entered in [`EXPERIMENT_LOG.md`](../EXPERIMENT_LOG.md) before account results were inspected.

| Held security/day | Separate modelling-shadow treatment | Pre-event weight | Modelled stock return |
|---|---|---:|---:|
| ADANIENT, 2018-04-05 | Actual raw price return; **zero unresolved incremental scheme entitlement assumed** | 1.8913516% | −2.3770221% |
| HGS, 2022-02-22 | Verified ordinary 1:1 bonus and ₹28 per pre-bonus share | 2.3241393% | −3.1311727% |
| EASEMYTRIP, 2022-11-21 | Verified ordinary 2:1 subdivision, then 3:1 bonus on subdivided shares; **eight post-event shares per old share, no cash** | 2.0610185% | +20.0157089% |

For HGS, the [company's 12 February 2022 exchange filing](https://www.bseindia.com/xml-data/corpfiling/AttachHis/f5386769-50d2-43c5-aa62-a7bee9caed11.pdf) establishes the pre-bonus dividend basis and 1:1 bonus. The ordinary combined return is `(2 × 1310.1 + 28) / 2733.8 − 1 = −0.0313117273`; its raw price return of −52.0776941% is not an economic return. The observed shadow-unit ratio is **2.0213724143**, equal to `2 + 28/1310.1` under the synthetic reinvested-dividend convention.

For EASEMYTRIP, the [company's 10 November 2022 record-date filing](https://www.easemytrip.com/investor-pdf/2022/Intimation-of-Record-Date-22-11-2022.pdf) specifies the order: each ₹2 share splits into two ₹1 shares, then each resulting ₹1 share receives three bonus ₹1 shares. The NSE action records identify 2022-11-21 as the ex-date and 2022-11-22 as the record date. Using the immediately preceding canonical NSE close of **₹381.95** from 2022-11-18 and ex-date close of **₹57.30**, the combined return is `(8 × 57.3) / 381.95 − 1 = 0.2001570886`. The raw price return of **−84.9980364%** is not substituted. The actual modelling-shadow units after the action equal **8 ×** the prior session's units, with no cash credited. The later executable ledger must implement the quantity transformation rather than alter an execution price.

The reusable raw-price fallback remains restricted to a held unavailable return caused solely by a complex incremental entitlement. It requires actual valid current and previous quotes, resolved identity, eligible equity series, complete event-ID matching, and no known ordinary share or cash leg or terminal action. Only ADANIENT has used it while held. Its zero-incremental assumption is not an audited economic return or a conservative bound on volatility. The per-security-day status, original reason, raw and modelled returns, event IDs, weights, multiplier, cash, and provenance are in [`modelled_corporate_action_days.csv`](../../results/volatility_overlay_audit/modelled_corporate_action_days.csv).

The shadow credits ex-date economic entitlements under the synthetic reinvested-distribution convention. It does not assert that bonus shares or dividend cash could be traded or spent on that date; an executable ledger must respect actual allotment and payment timing.

## Shadow and formation-risk results

| Measure | Result |
|---|---:|
| First modelling shadow return | 2014-09-01 |
| Last valid modelling shadow return | **2023-03-31** |
| Valid daily shadow returns | **2,124** |
| Modelled corporate-action security-days | **3** |
| New uncovered held-return blocker | **None through cutoff** |
| Maximum value-bearing market date read | **2023-03-31** |

At each formation close, use exactly the last 126 canonical NSE shadow returns, including that close: `sigma_hat² = (252/126) × Σ r_daily²`, then `sigma_hat = sqrt(sigma_hat²)`. This is a non-demeaned second moment. A positive finite sigma gives `exposure = min(1, 0.12/sigma_hat)` and `cash_fraction = 1 − exposure`. Missing, nonfinite, zero, or negative estimates target cash with a visible error status, as required by [`../../plan.md` §7.3](../../plan.md).

There are **103** development formation rows: **96 valid scored volatility estimates** and seven earlier warm-up formations with insufficient shadow history. No scored formation has an unavailable risk estimate. Among the 96 scored formations, **95** target exposure below one. Minimum, median, and mean target exposures are **0.3360178732**, **0.5809165789**, and **0.5995134124**; maximum estimated sigma is **0.3571238603**. Every valid formation uses 126 finite observed shadow returns and a source-data date no later than formation close.

The first scored formation, **2015-03-31**, has **142** valid shadow returns available. Its exact 126-session window starts **2014-09-23**; the squared-return sum **0.021030273106643658** × `252/126` = **0.042060546213287316**, giving sigma **0.2050866797558713** and exposure **0.5851184491496191**. The 2019-06-28 positive low-volatility estimate (**0.1181014204**) is capped at exposure **1**. The 2020-08-31 high-volatility estimate (**0.3571238603**) gives exposure **0.3360178732**.

Exactly **16** valid formation windows contain a modelled day: six contain ADANIENT (2018-04-30 through 2018-09-28), six contain HGS (2022-02-28 through 2022-07-29), and four contain EASEMYTRIP (2022-11-30, 2022-12-30, 2023-01-31, 2023-02-28). The `modelling_days_in_window` count and `modelling_assumption_in_window` flag are in [`volatility_overlay_development.parquet`](../../data/processed/volatility_overlay_development.parquet) and [`formation_risk_summary.csv`](../../results/volatility_overlay_audit/formation_risk_summary.csv). The earlier small ADANIENT-only ±5-percentage-point return diagnostic remains separate in [`adanient_modelled_window_impact.csv`](../../results/volatility_overlay_audit/adanient_modelled_window_impact.csv); it is not an entitlement valuation or a strategy result.

Focused overlay tests: **8 passed**. Full repository suite: **125 passed**. The EASEMYTRIP regressions check the multiplier eight, zero cash, the canonical-prior-close formula, exact eightfold actual shadow units, rejection of the raw price return, and unchanged strict hashes. Other tests cover the guarded complex fallback, HGS economics, exact 126-session RMS calculation, cash fallback for invalid sigma, modelled-window flags, and development cutoff. If unresolved entitlements materially affect later account results, [`../../plan.md` §5.4](../../plan.md) requires a provisional investment conclusion.
