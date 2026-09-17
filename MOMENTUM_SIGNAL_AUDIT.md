# Development monthly momentum and winner-set audit

`momentum_signal.py` builds the 12-to-2 signal solely from the corrected
`data/processed/stock_total_returns.parquet` and membership/market metadata in
`data/processed/research_panel_v2.parquet`. The historical v1 return column is
revoked; the pipeline checks the exact authoritative paths and matches every
v2 daily return against the corrected artifact. The v1 panel is read only by a
regression test that demonstrates the corrected TCS dividend differs.

All value-bearing Parquet reads are predicate-filtered through **2023-03-31**.
There are no downloads, raw-file reads, post-cutoff values, shadow returns,
portfolios, weights, execution, costs, taxes, NAV, or performance results.

## Convention and outputs

The official membership intervals are the only universe source, with an open
`valid_to` interpreted as continuing membership. For each canonical month-end,
the builder first enumerates all members under `valid_from <= formation_date <
valid_to`, then left-joins that day's accepted panel observation. A missing
observation stays in the official roster and fails eligibility explicitly.
Earlier, pre-membership price history remains available for the lookback.

An ordinary security-month is complete only when **every** canonical session
has a selected observation and a valid corrected close-to-close daily return,
including the preceding-session anchor for its first day. Eleven complete
monthly returns enter each formation's score. March 31, 2015 formation for
April 2015 holdings uses **April 2014–February 2015** and excludes March
2015. Formations run August 28, 2014–February 28, 2023; the first seven
winner sets are unscored warm-up and the remaining 96 hold April 2015–March
2023. No stale/forward-filled quote, return, or volume is substituted.

An eligible formation requires official membership, complete 11-month return
history, accepted cash-equity observation on that exact formation session,
finite positive current close, resolved identity, valid market status,
positive finite preceding-20-session ADV with all 20 observations, at least
15 positive-volume sessions in that window, and safe corporate-action timing.
Formation-day positive volume is **not** an extra filter. Scores sort
descending, then by permanent `security_id` ascending; the winner count is
`ceil(eligible_count / 10)`. There is no positive-momentum screen. Each
eligibility gate and all unavailable lookback months/reasons/event IDs are
preserved on the formation record.

- `data/processed/momentum_monthly_features.parquet`: complete and incomplete
  security-months, returns, strict/delayed method, and provenance.
- `data/processed/momentum_formations.parquet`: entire official roster at each
  formation, eligibility, reason, score, rank, and winner flag.
- `data/processed/momentum_winners.parquet`: scored and unscored warm-up
  winners, without portfolio weights.
- `results/momentum_signal_audit/`: per-formation counts, excluded candidates,
  delayed monthly features, unresolved-event materiality, event-priority
  summary, and stage summary.

## Narrow bonus-debenture monthly method

The four strict **daily** ex-date returns remain unavailable and the corrected
daily-return artifact is byte-for-byte unchanged. Blue Dart November 2014 and
NTPC March 2015 have accepted official first-trade entitlement prices in the
same calendar month, accepted quantities, and a timing audit showing complete
12-to-2 economic windows and availability by affected formation. Only these
two months receive the following separate research-feature calculation:

1. Require every canonical monthly session and every other day's corrected
   daily total return; require the ex-date to be the sole unavailable day and
   its event ID/reason to match the accepted strict exception.
2. Compound the corrected daily returns for the equity leg, using **only the
   raw equity price return** on the ex-date. Do not insert an ex-date fair
   value or alter any daily return.
3. At the monthly endpoint, add one entitlement leg:
   `pre_ex_date_gross * sum(quantity * accepted first-trade price) /
   preceding_ex_date_equity_close`. The entitlement leg is not multiplied by
   subsequent equity returns. The resulting month is credited **once** in
   the eleven-month product. Event ID, trade/recognition date, value, and
   official price evidence are stored with the feature.

The accepted values are ₹154 per pre-event Blue Dart share (three tranches,
traded November 28) and ₹12.71 per NTPC share (traded March 30). NTPC's first
trade mark is carried to the March 31 monthly endpoint without a new bond
repricing; this is an explicit one-session feature-accounting assumption, not
an asserted March 31 market quote or an ex-date fair value. The synthetic
monthly feature follows a reinvested total-return-index convention across
subsequent months. It must not be used to create daily shadow returns.

No other unavailable day, missing observation, identity/series defect, or
unresolved event is excused by this method. The two Britannia months receive
no delayed monthly repair. Exactly **eight** Britannia security/formation
observations have primary reason
`BRITANNIA_BONUS_DEBENTURE_PARTIAL_WINDOW`; their other simultaneous failure
reasons, if any, remain visible separately. Other Britannia formations may
fail ordinary return completeness. The 2021 ex-date also has a coincident
unresolved corporate action in the corrected daily-return artifact.

## Final development audit

| Check | Result |
|---|---:|
| Monthly security-feature rows | 106,395 |
| Complete / incomplete security-months | 86,513 / 19,882 |
| Official security/formation rows | 51,583 |
| Formation dates / scored / unscored warm-up | 103 / 96 / 7 |
| Official roster count per formation | 500–501 |
| Eligible formations / excluded observations | 50,350 / 1,233 |
| Eligible count per formation | 475–500 |
| Winners / scored winners / warm-up winners | 5,076 / 4,732 / 344 |
| Winner count per formation | 48–50 |
| Missing formation panel observations | 0 (left-join protection still active) |
| Formation quote / ADV / activity failures | 0 / 3 / 0 |
| Incomplete 11-month histories | 1,226 (overlaps other failures) |
| Delayed monthly features | 2 |
| Britannia timing-specific failures | 8 |
| Duplicate security/formation rows | 0 |
| Maximum value date read / last formation | 2023-03-31 / 2023-02-28 |

Primary exclusion reasons: 1,222 incomplete return histories, eight
Britannia timing failures, and three ADV failures. The source of each
incomplete history is retained on the formation and monthly feature tables.
Focused signal tests: **12 passed** within the complete repository suite of
**91 passed** after final regeneration.

## Unresolved event materiality and stop point

The unresolved-event audit has **1,474** rows with event ID, security ID/date,
affected month and formation, official formation membership, gate effect,
and a deliberately unknown hypothetical winner status. Thirty-nine distinct
unresolved economic events block **216** otherwise eligible formation signals
for 38 securities on 77 formation dates; **161** of these signals are in the
96 scored formations. Of the 216, 178 are unaccepted treatment cases, 29
unverified ordinary-action parses, and nine are the 2019 Britannia strict
exception. Blue Dart and NTPC have their two narrow monthly features and
therefore do not appear among these independent blockers. Four events with
unresolved possible-member identity remain separately visible.

For a single missing-event month, the audit records the return that month
would need to cross the *observed* winner cutoff, using the other ten known
months. This threshold is a triage diagnostic, **not** a guessed economic
return or a determination that the stock would win. Without the missing
economic return, the hypothetical rank and winner status are unknowable.
Twenty-seven of the 216 thresholds are at most 10%, including 12 at or below
zero; that makes targeted action resolution material before claiming a clean
portfolio/backtest comparison. No treatment was newly researched or assumed
in this stage.

The separate daily shadow-risk materiality question remains open: if a future
shadow portfolio actually holds one of the four strict-exception securities
across its ex-date, its 126-session daily risk estimate is blocked until an
explicit daily methodology is accepted. This stage does not construct or
inspect such a portfolio.
