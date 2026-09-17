# Targeted unresolved-event winner materiality

This is a diagnostic of the frozen development momentum outputs, not a new
return treatment or a backtest. `src/brindco_momentum/signals/momentum_materiality.py` reads the corrected
daily returns, panel v2, monthly features, complete formation roster, winner
sets, and existing unresolved-event audits. Every value-bearing Parquet read
is filtered to **2023-03-31 or earlier**. The old panel's revoked total return
is not an input. The five authoritative Parquet input hashes are checked
before and after writing the three files in
`results/momentum_materiality/`; none is modified.

## Scope and result

The prior audit has **173** explicit unresolved economic events, of which
**39** independently block **216** otherwise eligible security/formation
signals. Those 216 include **161 scored** and **55 unscored warm-up** cases.
Nine scored cases come from the already accepted 2019 Britannia strict
bonus-debenture exception. That event is reconciled here but excluded from
new-treatment triage, as requested. The targeted scope is therefore **38
events, 207 observations: 152 scored and 55 warm-up**. The accepted Blue Dart
and NTPC monthly features, four strict daily exceptions, and eight Britannia
partial-window flags remain unchanged. Four source actions with unresolved
security identity cannot be linked to a formation and remain a separate
upstream limitation.

| Formation-level class | Count |
|---|---:|
| `IMMATERIAL_TO_WINNER_SET` | 0 |
| `POSSIBLY_MATERIAL` | 0 |
| `MATERIAL_WARMUP_ONLY` | 55 |
| `REQUIRES_EVENT_RESEARCH` | 0 |
| `CANNOT_BOUND` | 152 |

`REQUIRES_EVENT_RESEARCH` is zero as a *classification label* because every
scored targeted event lacks an accepted finite adjustment bound and is more
precisely labelled `CANNOT_BOUND`. The separate `needs_further_research` flag
is true for all 38 events: **31** have scored winner-set uncertainty and **7**
affect only the mandatory shadow warm-up. No event can be safely discarded
from eventual research based on the accepted data alone. A high threshold is
not a mathematical upper bound on a structural entitlement, mixed bonus,
rights issue, or unaccepted buyback treatment.

## Exact boundary calculation

For each case, the other ten complete monthly gross returns have product
`G10`. If the unknown event month's economic return were `r`, the signal
would be `G10 × (1+r) − 1`. Against any known-name boundary score `M*`, the
exact event-month threshold is `(1+M*) / G10 − 1`. The output also shows the
additional monthly return relative to an **equity price-only diagnostic**;
that diagnostic compounds the other accepted daily total returns and the
unadjusted equity move on the one missing ex-date. It never fills the strict
daily return and is never used for ranking.

Restoring a candidate changes the eligible count from `N` to `N+1`. The
single-candidate boundary therefore uses `ceil(0.10 × (N+1))`, not always the
current `ceil(0.10 × N)`. For example, at `N=490`, the existing set has 49
winners but the candidate would create a 50th seat; the relevant known-name
boundary is the current strongest non-winner. Up to nine unresolved candidates
coincide at a formation. The CSV preserves a best-case boundary with all such
candidates eligible and behind the subject, and a worst-case boundary across
subsets with other unresolved candidates ahead. At exact score equality, the
stored `security_id` tie-break flag determines inclusion. **105 of 207**
targeted observations are at formations where adding unresolved candidates
could change the seat count. These are scenarios for testing selection
possibility, not guessed event values, ranks, or winner lists.

## Hand-checkable cases

- **Clearly immaterial:** none of the 207 targeted otherwise-eligible cases
  qualifies. Every one lacks an accepted upper bound on its additional
  economic return, and in some cases eligible-count changes also affect the
  set. Giving an in-scope “clearly immaterial” example would violate the
  requested proof standard. Events outside the required 12-to-2 window have
  no applicable formation and were excluded by the prior audit, but they are
  not part of these 207 observations.
- **Scored winner uncertainty — TANLA buyback, 2020-06-09; formation
  2021-03-31.** `N=490`, current `K=49`, candidate-adjusted `K=50`.
  Weakest current winner momentum is **224.8431%**; strongest non-winner,
  the candidate boundary, is **224.7059%**. The other ten months have
  `G10=17.786479`, so the missing month would need more than **−81.7442%**
  return to enter (subject to the ID tie rule). The price-only diagnostic is
  **+4.4428%**, well above that threshold, but passive buyback treatment was
  never accepted for this event. Winner membership remains unknown; no
  hypothetical rank is assigned.
- **Warm-up-only — ZEEL preference-share bonus, 2014-03-03; formation
  2014-08-28.** `N=490`, current `K=49`, candidate-adjusted `K=50`.
  The current cutoff is **208.9005%** momentum and the strongest non-winner
  is **207.5618%**. With `G10=1.252137`, the missing month would need at least
  **145.6294%** to enter alone (its security ID wins an exact tie), or
  **144.6432 percentage points** above
  the price-only diagnostic. It affects unscored warm-up selection, not a
  scored holding month; no accepted preference-share valuation bounds it.
- **Unbounded structural case — TATACHEM demerger, 2020-03-04; formation
  2020-09-30.** Current `N=489`, `K=49`, with two concurrent unresolved
  candidates. The current winner cutoff is **68.7150%** momentum; the
  strongest non-winner is **67.4838%**. The single-candidate missing-month
  threshold is **−3.8496%**, versus an equity price-only diagnostic of
  **−68.6905%**: an additional **64.8409 percentage points** would be
  needed. Under both candidates becoming eligible, the best-case threshold
  falls to **−4.5513%**. No accepted demerger-entitlement bound exists, so
  this cannot be classified immaterial despite the sizable adjustment.

The price-only figures in these examples are counterfactual diagnostics, not
valid total returns. None is inserted into the daily-return series, monthly
features, frozen scores, or winner sets.

## Event research queue

The priority CSV supplies each stable event ID, permanent security ID,
first/last affected formation, scored/warm-up counts, exact thresholds, and
deterministic priority order. Scored uncertainty is ordered first by number
of affected scored formations. The seven warm-up-only events follow.

| Scored-priority event (date; type) | Scored formations |
|---|---:|
| IIFL (2019-05-30; structural) | 8 |
| NIACL (2018-06-27; bonus) | 7 |
| RELCAPITAL (2017-09-05; structural) | 7 |
| CESC (2018-10-30; structural) | 7 |
| AARTIIND (2019-07-03; structural) | 7 |
| COX&KINGS (2018-10-25; structural) | 7 |
| STAR (2018-04-06; structural) | 7 |
| BALKRISIND (2015-03-24; structural) | 6 |
| ABB (2019-12-20; structural) | 6 |
| TATACHEM (2020-03-04; structural) | 6 |
| IIFL (2017-10-17; structural) | 6 |
| CGPOWER (2016-03-15; structural) | 6 |
| SUNDARMFIN (2018-02-01; structural) | 5 |
| FDC (2018-02-26; buyback) | 5 |
| JUBLPHARMA (2021-02-04; structural) | 5 |
| FRETAIL (2017-11-29; structural) | 5 |
| ARVIND (2015-05-28; structural) | 5 |
| LAKSHVILAS (2014-07-25; rights) | 4 |
| SHRENUJ (2014-07-15; bonus) | 4 |
| MFSL (2016-01-27; structural) | 4 |
| GAYAPROJ (2018-01-30; structural) | 4 |
| MOTHERSON (2022-01-14; structural) | 4 |
| ABIRLANUVO (2016-01-20; structural) | 4 |
| BSOFT (2019-01-24; structural) | 4 |
| LGBBROSLTD (2014-07-04; bonus) | 4 |
| BEML (2022-09-08; structural) | 3 |
| TATACOMM (2019-09-17; structural) | 3 |
| GRASIM (2017-07-19; structural) | 3 |
| TANLA (2020-06-09; buyback) | 3 |
| ADANIENT (2015-06-03; structural) | 2 |
| IDFC (2015-10-01; structural) | 1 |

| Warm-up-only event (date; type) | Warm-up formations |
|---|---:|
| ZEEL (2014-03-03; preference-share bonus) | 7 |
| TATAPOWER (2014-03-19; rights) | 7 |
| IL&FSTRANS (2014-03-13; rights) | 7 |
| RAJTV (2014-03-25; mixed bonus/split) | 7 |
| WHEELS (2014-02-13; rights) | 5 |
| WELCORP (2014-02-18; structural) | 5 |
| MARICO (2013-11-01; structural/dividend) | 3 |

The two scored-priority July 2014 events, LAKSHVILAS and SHRENUJ, also each
affect seven warm-up formations. A changed warm-up winner could change later
daily shadow returns and the 126-session volatility estimate; a changed scored
winner could additionally change later selected holdings and exposure. These
dependencies are flagged, not simulated. No new source research, action
treatment, portfolio, shadow series, or performance calculation was done.

Validation: **14 focused tests passed; 105 repository tests passed**. The
maximum value date read was **2023-03-31**. Source hashes confirmed that the
corrected daily returns, panel v2, monthly features, formation roster, and
frozen winner sets were unchanged.
