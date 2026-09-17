# Data Acquisition and Validation Description

## Purpose

This document records the data acquisition, normalization, validation, and audit work completed for the Brindco Paper C project.

It is intended to give a future human or coding agent enough context to understand:

- what data was collected;
- where it came from;
- how it was normalized;
- what validation was performed;
- what each important file contains;
- what known caveats remain;
- which artifacts are safe to use for research-panel construction.

This document is descriptive. `../plan.md` remains authoritative for the economic and research specification.

The acquisition scripts evolved iteratively. For exact column names and current artifact filenames, the processed files on disk and the current code are authoritative; this document provides context and recorded validation results rather than replacing schema inspection.

---

# 1. High-Level Status

External data acquisition is complete.

The project currently has the required source data for:

- NSE Capital Market bhavcopy observations, including historical equity-series prices, volume, and traded value;
- historical point-in-time NIFTY 500 membership;
- symbol/security identity mapping;
- NSE corporate actions;
- NIFTY 500 Total Return Index;
- an NSE trading-session calendar derived from the market files.

No additional external dataset should be downloaded merely to build the research panel.

## Final derived-layer status

Following recovery of the 14 special NSE trading sessions, the trading-calendar
and security-identity layers were regenerated from the final combined market parquet.

Final trading calendar:

```text
Trading sessions      : 3,280
First session         : 2013-01-01
Last session          : 2026-03-30
Month-end sessions    : 159
Bhavcopy not in TRI   : 0
TRI not in bhavcopy   : 0
```

Final security-identity rebuild:

```text
EQ observations                    : 5,288,146
Unique symbols                     : 3,579
Unique ISINs                       : 3,663
Observed ISIN-symbol pairs         : 4,096
Usable symbol-change records       : 1,051
Unparseable symbol-change dates    : 0
Same-ISIN sequential ticker edges  : 433
Suspicious same-ISIN overlaps      : 0
Ticker identity components         : 3,736
NIFTY 500 membership symbols       : 951
Components with price evidence     : 949
```

Previous membership/price mismatch resolution remained:

```text
RESOLVED   : 244
UNRESOLVED : 74
AMBIGUOUS  : 0
```

The processed acquisition and normalization layer is now considered frozen as the current input snapshot; documented unresolved membership, identity, and corporate-action cases remain explicit limitations.

---

# 2. Source Hierarchy and Philosophy

The project deliberately preserves raw data separately from normalized research data.

The important principles used during acquisition were:

1. Prefer free public/official exchange data.
2. Preserve downloaded source files unchanged.
3. Normalize into explicit processed schemas.
4. Record missing or ambiguous observations rather than silently repairing them.
5. Treat ticker symbols as labels, not permanent security identities.
6. Use point-in-time index membership rather than today's constituent list.
7. Reconcile independent datasets where possible.
8. Do not infer NSE sessions from weekdays because special weekend sessions exist.
9. Do not silently interpret every unavailable archive object as an exchange holiday.
10. Complex corporate events remain auditable rather than being forced into simple adjustment formulas.

Primary source families used:

- NSE historical Capital Market bhavcopies;
- NSE UDiFF Capital Market bhavcopies;
- NSE Corporate Actions;
- NSE Changes in Symbols / Changes in Company Names / current equity-security list;
- Nifty Indices historical Total Return Index data;
- a public historical NIFTY membership reconstruction used as a working point-in-time membership source and audit aid.

---

# 3. Directory-Level Data Layout

The relevant data tree is conceptually:

```text
data/
├── raw/
│   ├── bhavcopy_legacy/
│   ├── bhavcopy_udiff/
│   ├── membership/
│   ├── security_identity/
│   ├── corporate_actions/
│   └── benchmark/
│
└── processed/
    ├── nse_cm_legacy_2013_2024.parquet
    ├── nse_cm_udiff_2024_2026.parquet
    ├── nse_cm_2013_2026.parquet
    ├── nifty500_tri_2013_2026.parquet
    ├── nse_trading_calendar_2013_2026.parquet
    ├── nse_corporate_actions_2013_2026.parquet
    ├── membership_audit/
    ├── security_identity/
    └── corporate_actions/
```

`data/raw/` is the immutable acquisition layer.

Downstream research-panel code should use the normalized files under `data/processed/` and should not need to inspect `data/raw/`.

---

# 4. NSE Daily Capital Market Data

## 4.1 Source

Official NSE archive.

Two file generations are required because NSE changed the Capital Market bhavcopy format in July 2024.

### Legacy bhavcopy

Coverage:

```text
2013-01-01 through 2024-07-05
```

Archive pattern:

```text
https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip
```

The month code is uppercase, for example:

```text
.../2019/OCT/cm27OCT2019bhav.csv.zip
```

Typical legacy CSV fields:

```text
SYMBOL
SERIES
OPEN
HIGH
LOW
CLOSE
LAST
PREVCLOSE
TOTTRDQTY
TOTTRDVAL
TIMESTAMP
TOTALTRADES
ISIN
```

The legacy files were normalized using the date encoded in the filename as the canonical trading date.

This was necessary because NSE historical files do not use one consistent textual timestamp format; for example, some rows use two-digit years such as `13-Jul-20`.

The internal `TIMESTAMP` field was used as a consistency check where parseable, rather than as the authoritative date.

### UDiFF bhavcopy

Coverage:

```text
2024-07-08 through 2026-03-30
```

Archive pattern:

```text
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

The correct modern report is:

```text
CM-UDiFF Common Bhavcopy Final (zip)
```

Important source fields include:

```text
TradDt
FinInstrmId
ISIN
TckrSymb
SctySrs
FinInstrmNm
OpnPric
HghPric
LwPric
ClsPric
LastPric
PrvsClsgPric
TtlTradgVol
TtlTrfVal
TtlNbOfTxsExctd
```

---

# 5. Market-Data Acquisition Results

## 5.1 Original legacy download

The first bulk legacy download produced:

```text
DOWNLOADED : 2,838
MISSING    : 166
ERROR      : 0
```

Weekends were intentionally skipped by the original downloader.

The `MISSING` count was not treated as proof that every missing weekday was a holiday; availability and calendar reconciliation were checked later.

## 5.2 Special-session reconciliation

The NIFTY 500 TRI contained 14 observations on dates absent from the first market-data calendar.

Those dates were:

```text
2013-05-11
2013-11-03
2014-03-22
2015-02-28
2016-10-30
2019-10-27
2020-02-01
2020-11-14
2023-11-12
2024-01-20
2024-03-02
2024-05-18
2025-02-01
2026-02-01
```

All are Saturday/Sunday special NSE trading sessions.

The first downloader had skipped them because it used weekday filtering.

A dedicated patch downloader retrieved:

```text
12 legacy bhavcopies
2 UDiFF bhavcopies
0 missing
0 errors
```

This is a useful data-quality lesson: **weekday logic is not a valid substitute for an exchange trading calendar.**

---

# 6. Processed Market Data

## 6.1 Canonical schema

Legacy and UDiFF data were normalized into a common schema:

```text
date
isin
symbol
series
open
high
low
close
last
prev_close
volume
traded_value
num_trades
source_file
source_format
```

The processed data deliberately retains the contemporaneous ticker/series rather than rewriting all history to terminal symbols.

**Important:** the combined bhavcopy parquet is a normalized NSE Capital Market dataset, not a pre-filtered investable-equity universe. It can contain multiple security series/instrument types present in the CM reports. Downstream panel construction must identify the valid cash-equity observation for each security/date instead of assuming every row is an eligible common-equity observation.

## 6.2 Legacy processed parquet

File:

```text
data/processed/nse_cm_legacy_2013_2024.parquet
```

Final rebuild after the special-session patch:

```text
ZIP files     : 2,850
Rows          : 5,450,907
Date range    : 2013-01-01 to 2024-07-05
Unique ISINs  : 5,632
Unique symbols: 5,085
Size          : ~139.7 MB
```

## 6.3 UDiFF processed parquet

File:

```text
data/processed/nse_cm_udiff_2024_2026.parquet
```

Final rebuild:

```text
Files/sessions: 430
Rows           : 1,307,646
Date range     : 2024-07-08 to 2026-03-30
Unique ISINs   : 5,048
Unique symbols : 5,126
Size           : ~38.4 MB
```

## 6.4 Final combined market parquet

File:

```text
data/processed/nse_cm_2013_2026.parquet
```

Final validation:

```text
Rows          : 6,758,553
Parquet groups: 69
First date    : 2013-01-01
Last date     : 2026-03-30
Trading dates : 3,280
Unique ISINs  : 7,270
Size          : ~215.7 MB
```

Boundary validation confirmed that both:

```text
2024-07-05
2024-07-08
```

are present, so the legacy-to-UDiFF transition is covered.

This is the principal processed stock-market input for downstream work.

---

# 7. Historical NIFTY 500 Membership

## 7.1 Source

Working membership source:

```text
index_membership_history.csv
```

from the public `aditya-jha/nse-historical-membership` reconstruction.

The file is based on historical NSE/Nifty public information and is used as a point-in-time reconstruction/audit aid rather than being assumed perfect.

Historical early-period membership also requires awareness of the older index name:

```text
CNX 500
```

before the NIFTY renaming.

## 7.2 Raw membership schema

Observed fields:

```text
index_id
index_name
symbol
valid_from
valid_to
weightage
source
source_url
notes
```

Membership intervals are treated as half-open:

```text
valid_from <= date < valid_to
```

A blank `valid_to` means open-ended.

## 7.3 Validation results

Full membership file:

```text
Rows: 6,525
```

Structural validation:

```text
Invalid/non-positive intervals: 0
Exact duplicate rows          : 0
Overlapping symbol intervals  : 4
```

All four overlap detections involved `GSPL` in different indices.

The relevant NIFTY 500 overlap was:

```text
old interval: 2014-01-01 to 2026-05-12
new interval: 2026-03-31 to open-ended
```

The raw membership file was **not edited**.

The pattern is consistent with a snapshot/reconstruction overlap near the terminal boundary. Downstream lookup logic must ensure that a security cannot enter the same index twice on one date.

## 7.4 NIFTY 500 subset

Validated NIFTY 500 subset:

```text
Earliest valid_from      : 2014-01-01
Latest finite valid_to   : 2026-05-12
Open/current intervals   : 499
Distinct symbols         : 951
Total intervals          : 1,123
```

Source composition:

```text
press_release : 603
snapshot_floor: 516
merger        : 2
snapshot      : 2
```

Month-end membership-count diagnostics over the project period:

```text
Count of month-ends: 132
Mean members       : 501.48
Std. dev.          : 1.67
Minimum            : 499
Median             : 501
Maximum            : 505
```

No month-end count fell outside the deliberately broad sanity range of 485-515.

## 7.5 Early-period caveat

For intervals touching 2015-2017:

```text
Intervals examined                : 588
Intervals flagged for manual audit: 484
```

This is primarily due to reconstructed `snapshot_floor` provenance rather than direct press-release evidence.

The early membership history is therefore **usable but not independently proven row-by-row**.

This uncertainty should remain disclosed.

## 7.6 Processed membership files

Confirmed principal processed file:

```text
data/processed/membership_audit/nifty500_membership_intervals.parquet
```

The membership validator also produced audit CSVs covering items such as:

- month-end membership counts;
- early-period intervals requiring manual review;
- overlap/duplicate diagnostics;
- membership symbols not directly found in the price history;
- official-document follow-up candidates.

Because the validator evolved during the acquisition work, downstream code should inspect `data/processed/membership_audit/` for the exact current audit filenames rather than depending on a filename that appears only in this descriptive document.

---

# 8. Security Identity and Symbol History

## 8.1 Why this layer exists

The membership source may use canonical/terminal ticker symbols, while historical NSE bhavcopies contain the ticker that actually traded on the historical date.

A ticker is therefore not a permanent security identifier.

The identity layer attempts to connect:

```text
membership symbol
        ↓
security identity / alias chain
        ↓
ticker actually traded on date t
        ↓
historical bhavcopy observation
```

Renames and supported same-ISIN transitions may preserve identity.

Mergers/demergers must not be treated as ordinary ticker renames.

## 8.2 Official reference inputs

Three NSE reference files were collected:

```text
data/raw/security_identity/symbolchange.csv
data/raw/security_identity/namechange.csv
data/raw/security_identity/EQUITY_L.csv
```

Their roles are:

```text
symbolchange.csv
    official old-symbol -> new-symbol evidence

namechange.csv
    supporting company-name-change evidence

EQUITY_L.csv
    current NSE equity symbol/ISIN anchor
```

`symbolchange.csv` is headerless in the downloaded NSE format.

It was interpreted as:

```text
company_name
old_symbol
new_symbol
effective_date
```

## 8.3 Identity logic

The processed identity layer combines:

- symbol-change records;
- same-ISIN ticker transitions observed directly in historical bhavcopies;
- current NSE symbol/ISIN information;
- NIFTY 500 membership symbols.

Alias relationships are represented as components rather than destructively renaming historical rows.

## 8.4 Initial identity-build results

The identity build run before the special-session patch observed:

```text
EQ observations          : 5,265,345
Unique symbols           : 3,579
Unique ISINs             : 3,663
Observed ISIN-symbol pairs: 4,096
```

The original sampled membership/price mismatch set contained:

```text
318 rows
```

Resolution result:

```text
RESOLVED  : 244
UNRESOLVED: 74
AMBIGUOUS : 0
```

Automatic resolution rate:

```text
76.73%
```

The 74 unresolved rows corresponded to:

```text
43 unique membership symbols
```

There were:

```text
0 suspicious same-ISIN overlap flags
```

Examples among unresolved symbols included:

```text
ANGELONE
EPIGRAL
SGPC
SHTV
360ONE
COHANCE
DALBHARAT
CHOLAHLDNG
CROMPTON
EQUITAS
INFIBEAM
SCHNEIDER
...
```

These names were deliberately **not guessed or manually rewritten**.

## 8.5 Final identity status

The security-identity layer was regenerated after the final 14 special-session
market files were added.

Final rebuild statistics:

```text
EQ observations                  : 5,288,146
Unique symbols                   : 3,579
Unique ISINs                     : 3,663
Observed ISIN-symbol pairs       : 4,096
Usable symbol-change records     : 1,051
Unparseable effective dates      : 0
Same-ISIN sequential ticker edges: 433
Suspicious same-ISIN overlaps    : 0
Identity components              : 3,736
NIFTY 500 membership symbols     : 951
Components with price evidence   : 949
```

The prior membership-symbol mismatch result remained stable:

```text
RESOLVED   : 244
UNRESOLVED : 74
AMBIGUOUS  : 0
```

The identity artifacts under `data/processed/security_identity/` are therefore
the current downstream inputs. Unresolved mappings must remain explicit rather
than being manually guessed.


## 8.6 Important processed identity files

The identity builder was designed to produce the following principal artifacts:

```text
data/processed/security_identity/observed_symbol_isin_history.parquet
data/processed/security_identity/observed_symbol_isin_history.csv
data/processed/security_identity/normalized_symbol_changes.csv
data/processed/security_identity/normalized_current_equities.csv
data/processed/security_identity/normalized_name_changes.csv
data/processed/security_identity/symbol_alias_edges.csv
data/processed/security_identity/symbol_alias_components.parquet
data/processed/security_identity/symbol_alias_components.csv
data/processed/security_identity/nifty500_symbol_crosswalk.parquet
data/processed/security_identity/nifty500_symbol_crosswalk.csv
data/processed/security_identity/membership_mismatch_resolution.csv
data/processed/security_identity/unresolved_membership_mismatches.csv
data/processed/security_identity/ambiguous_membership_mismatches.csv
```

Possible diagnostic:

```text
same_isin_overlap_flags.csv
```

No such suspicious-overlap file was generated in the prior run.

Following the final `../src/brindco_momentum/data/build_security_identity.py` rerun, treat the actual files and schemas present under `data/processed/security_identity/` as authoritative. This document records the intended/current artifact set but should not override the files on disk.

---

# 9. NSE Corporate Actions

## 9.1 Source and acquisition

Corporate actions were downloaded from the official NSE corporate-actions endpoint in monthly windows.

Coverage target:

```text
2013-01-01 through 2026-03-31
```

Acquisition result:

```text
Monthly windows downloaded: 159
Skipped                   : 0
Errors                    : 0
```

Raw JSON files are stored under:

```text
data/raw/corporate_actions/
```

## 9.2 Normalized corporate-action dataset

File:

```text
data/processed/nse_corporate_actions_2013_2026.parquet
```

Also written as CSV.

Normalization result:

```text
Raw rows              : 28,572
Rows after dedupe     : 28,559
Duplicate rows removed: 13
Earliest ex-date      : 2013-01-03
Latest ex-date        : 2026-03-30
Unique symbols        : 2,741
Missing record dates  : 17,486
Missing face values   : 12
```

A missing record date is not automatically a fatal issue for return construction because ex-date is the primary event timing field for many adjustments.

## 9.3 Normalized base fields

The corporate-action normalizer preserves fields equivalent to:

```text
symbol
company
series
face_value
purpose
ex_date
record_date
book_closure_start
book_closure_end
payment_date
remarks
source_file
source
```

## 9.4 Classification layer

File:

```text
data/processed/corporate_actions/nse_corporate_actions_classified.parquet
```

The classifier uses multiple event flags because one NSE purpose string may contain multiple event concepts.

Primary event counts:

```text
DIVIDEND             16,281
MEETING_ONLY          9,145
INTEREST              1,072
OTHER                   528
BONUS                   475
SPLIT                   439
RIGHTS                  294
STRUCTURAL              171
BUYBACK                 146
CAPITAL_REDUCTION         5
REDEMPTION                2
CONSOLIDATION             1
```

Flag counts differ slightly from primary-class counts because one row can carry multiple flags:

```text
is_dividend          : 16,304
is_bonus             : 498
is_split             : 439
is_consolidation     : 2
is_rights            : 294
is_structural        : 171
is_buyback           : 147
is_capital_reduction : 5
```

## 9.5 Parser coverage

Dividend parsing:

```text
Dividend rows         : 16,304
Dividend amount parsed: 16,277
Coverage              : ~99.83%
```

Bonus parsing:

```text
Bonus rows        : 498
Bonus ratio parsed: 495
Coverage          : ~99.40%
```

Split/consolidation parsing:

```text
Rows               : 441
FV transition parsed: 433
Coverage            : ~98.19%
```

Manual-review rows:

```text
252
```

`OTHER` rows:

```text
528
```

These rows are retained for audit.

No attempt was made to force every complex event into an automatic price-adjustment rule.

## 9.6 Important corporate-action audit files

Confirmed principal processed files:

```text
data/processed/nse_corporate_actions_2013_2026.parquet
data/processed/corporate_actions/nse_corporate_actions_classified.parquet
```

The classification/normalization stage also produced audit outputs for manual-review cases, `OTHER` purposes, parser misses, and duplicate candidates.

Downstream code should inspect `data/processed/corporate_actions/` for the exact current audit filenames rather than assuming every historical helper CSV still has the same name.

---

# 10. NIFTY 500 Total Return Index

## 10.1 Source

Official Nifty Indices historical Total Returns data.

The website restricts downloads to at most roughly one year per request, so the series was downloaded in 14 files:

```text
2013
2014
...
2025
2026 Q1
```

Typical source filename:

```text
NIFTY 500_Historical_TR_01012018to31122018.csv
```

Raw files are stored under:

```text
data/raw/benchmark/
```

## 10.2 Processed TRI file

Files:

```text
data/processed/nifty500_tri_2013_2026.parquet
data/processed/nifty500_tri_2013_2026.csv
```

The core information is:

```text
trading date
NIFTY 500 Total Return Index level
```

The TRI build/validation code also performed date-ordering and calendar-gap diagnostics during validation.

As with the other processed artifacts, inspect the actual parquet schema before coding rather than relying on descriptive column names in this document.

## 10.3 Validation results

```text
Input files          : 14
Trading-day rows     : 3,280
First date           : 2013-01-01
Last date            : 2026-03-30
Duplicate rows       : 0
Calendar gaps >5 days: 1
Missing TRI values   : 0
```

The one >5-day gap was:

```text
2014-10-01 -> 2014-10-07
```

a six-calendar-day gap consistent with a cluster of exchange holidays/weekend dates.

The series ends on 2026-03-30. The following date, 2026-03-31, is an NSE trading holiday (Mahavir Jayanti), so no 31 March cash-market observation is expected.

---

# 11. Trading Calendar

## 11.1 Construction

The trading calendar is derived from the **actual observed dates in the NSE market parquet**, not from weekday rules.

The calendar builder derives information equivalent to:

```text
date
trading_day_number
previous_trading_day
next_trading_day
next_2_trading_days
calendar_gap_from_previous
year
month
weekday
is_last_trading_day_of_month
```

File:

```text
data/processed/nse_trading_calendar_2013_2026.parquet
```

Audit file:

```text
data/processed/trading_calendar_audit.csv
```

## 11.2 Pre-patch validation result

Before the special-session files were recovered:

```text
Trading sessions    : 3,266
Bhavcopy not in TRI : 0
TRI not in bhavcopy : 14
```

That comparison discovered the 14 special weekend sessions described earlier.

## 11.3 Final calendar validation

After recovering the 14 special NSE sessions, the calendar was rebuilt from the
final combined market parquet.

Final result:

```text
Trading sessions      : 3,280
First session         : 2013-01-01
Last session          : 2026-03-30
Month-end sessions    : 159
Bhavcopy not in TRI   : 0
TRI not in bhavcopy   : 0
```

The market-data and TRI date sets now reconcile exactly.

This 3,280-session calendar is the canonical trading calendar for downstream work.

---

# 12. Settlement Convention

No full historical settlement-calendar dataset was reconstructed.

The project specification intentionally uses a simplified conservative primary convention:

```text
T+2 settlement-business-day availability throughout the sample
```

This is a modelling assumption from `../plan.md`, not a claim that historical NSE settlement mechanics were uniformly T+2.

Trading sessions and settlement-business days should not be assumed identical in later ledger code.

A richer historical settlement model is explicitly outside the current acquisition scope unless added as a later sensitivity.

---

# 13. Important Known Data Limitations

## 13.1 Early membership uncertainty

The 2015-2017 NIFTY 500 reconstruction contains many `snapshot_floor` intervals.

It is structurally coherent but not independently verified row-by-row against official circulars.

This must remain disclosed.

## 13.2 Security-identity uncertainty

The previous identity build resolved most sampled ticker mismatches but left:

```text
43 unique membership symbols unresolved
```

No ambiguous mappings were produced.

These cases must not be silently discarded.

The identity build has been rerun after the final market-data patch and is current for downstream panel construction.

## 13.3 Complex corporate actions

Most ordinary dividends, bonus issues, and splits parse automatically.

Complex events such as:

```text
mergers
demergers
schemes of arrangement
rights entitlements
capital restructurings
buybacks/delistings
```

must not be blindly converted into simple adjusted-return events.

Unresolved material events should remain explicit.

## 13.4 Missing security observation is not a market holiday

A stock can be absent on a valid NSE trading session because of suspension, series issues, no trading, data problems, or other reasons.

Do not equate a missing security row with a missing exchange session.

## 13.5 Ticker is not permanent identity

Historical data must preserve the symbol actually trading on the date.

Terminal/current ticker labels should not overwrite historical market observations.

---

# 14. Acquisition / Processing Scripts Used

Current module paths from the repository root for the final rebuild workflow include:

```text
src/brindco_momentum/data/gatherer.py
    legacy bhavcopy acquisition and legacy parquet build

src/brindco_momentum/data/gatherer_udiff.py
    UDiFF acquisition, normalization, and final market merge

src/brindco_momentum/data/build_security_identity.py
    constructs the symbol/ISIN alias identity layer and mismatch resolution

src/brindco_momentum/data/build_trading_calendar.py
    builds the observed NSE-session calendar and reconciles it with TRI
```

Additional scripts were used for:

- membership validation;
- corporate-action acquisition;
- corporate-action classification;
- NIFTY 500 TRI assembly;
- recovery of the 14 special weekend sessions.

Those helper scripts may have been renamed during iterative development. Inspect the repository itself for their exact current filenames rather than treating this descriptive document as a source-code manifest.

These scripts and their processed outputs form part of the provenance trail.

The research-panel stage should consume the processed outputs rather than rerunning external acquisition.

---

# 15. Recommended Processed Inputs for Research-Panel Construction

The panel builder should primarily consume:

```text
data/processed/nse_cm_2013_2026.parquet

data/processed/nse_trading_calendar_2013_2026.parquet

data/processed/membership_audit/
    nifty500_membership_intervals.parquet

data/processed/security_identity/
    observed_symbol_isin_history.parquet
    symbol_alias_components.parquet
    nifty500_symbol_crosswalk.parquet
    symbol_alias_edges.csv
    unresolved_membership_mismatches.csv

data/processed/corporate_actions/
    nse_corporate_actions_classified.parquet
```

The NIFTY 500 TRI is not required to construct the stock-level panel itself.

It remains an important later benchmark/context series:

```text
data/processed/nifty500_tri_2013_2026.parquet
```

---

# 16. Do Not Access Raw Data During Panel Construction

The acquisition stage is closed.

For the research-panel build:

```text
DO NOT inspect data/raw/
DO NOT download more data
DO NOT rerun acquisition scripts
```

Use the processed artifacts as the input contract.

If a required processed artifact appears missing, stale, or inconsistent during panel construction, stop and report the issue rather than accessing `data/raw/`, downloading data, or rerunning acquisition-layer scripts.

The trading-calendar and security-identity layers have already been regenerated
from the final 3,280-session market dataset. No further acquisition-layer rebuild
is currently required.

---

# 17. Holdout Isolation Reminder

The processed market and corporate-action datasets physically contain observations beyond March 2023.

That does **not** mean the development code is free to inspect their values.

Project windows are:

```text
Build   : 2015-04-01 through 2023-03-31
Holdout : 2023-04-01 through 2026-03-31
```

Warm-up data beginning in 2013 is required for historical features.

Before the protocol is frozen, downstream development should predicate-filter value reads to:

```text
date <= 2023-03-31
```

Post-March-2023 values should remain untouched for strategy development.

The acquisition stage did perform full-sample **mechanical** checks such as file/date coverage, row counts, format reconciliation, and duplicate/missing-date checks through March 2026. Those checks are provenance/data-integrity work, not permission to inspect holdout prices, returns, rankings, charts, or strategy performance before freeze.

---

# 18. Summary

At the end of acquisition, the project has:

```text
Final NSE stock-market observations : 6,758,553 rows
Final observed NSE sessions         : 3,280
Market-data range                    : 2013-01-01 to 2026-03-30

NIFTY 500 membership intervals       : 1,123
Historical membership symbols        : 951

Corporate-action rows                : 28,559
Corporate-action manual-review rows  : 252

NIFTY 500 TRI observations           : 3,280
TRI missing values                   : 0
TRI duplicate dates                  : 0
```

The major remaining work is no longer external data acquisition.

It is transformation of these audited inputs into a point-in-time research panel, followed later by:

```text
audited total returns
    ↓
12-to-2 momentum
    ↓
long-only winner portfolio
    ↓
historical shadow portfolio
    ↓
126-session risk estimate
    ↓
capped volatility exposure
    ↓
implementable MOM / VM / fixed controls
```

All unresolved data issues should remain explicit rather than being repaired invisibly.
