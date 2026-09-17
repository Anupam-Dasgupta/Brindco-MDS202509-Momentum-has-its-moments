# Research Panel Build Specification

## 0. Authority and Scope

Read `../../plan.md` first and treat it as the authoritative implementation specification.

This document defines only the **research-panel construction stage**.

If this document and `../../plan.md` appear to conflict, follow `../../plan.md` and report the conflict rather than silently choosing an interpretation.

Do NOT modify `../../plan.md`.

Do NOT implement the momentum strategy, shadow portfolio, volatility overlay, execution engine, taxes, transaction costs, or performance evaluation in this stage.

The objective is to produce a point-in-time, auditable, interview-defensible stock-level research dataset that later strategy code can consume.


# 1. CRITICAL DATA-ACCESS RULES

## 1.1 Do not use raw data

DO NOT inspect, read, scan, validate, modify, hash, or otherwise access anything under:

    data/raw/

Do not access `data/raw/` for any reason.

Do not download any additional data.

External data acquisition is complete.

Do not rerun downloaders.

Use only processed datasets already present in the repository.


## 1.2 Holdout isolation

This is a **BUILD-WINDOW task only**.

Project windows:

    Build:
        2015-04-01 through 2023-03-31

    Holdout:
        2023-04-01 through 2026-03-31

Warm-up observations before 2015 are allowed and required where necessary.

Before the research protocol is frozen:

- Do NOT inspect holdout prices.
- Do NOT inspect holdout volume.
- Do NOT inspect holdout returns.
- Do NOT inspect holdout corporate-action values.
- Do NOT inspect holdout benchmark values.
- Do NOT calculate holdout signals.
- Do NOT calculate holdout rankings.
- Do NOT calculate holdout strategy results.
- Do NOT build a 2023-2026 research panel.
- Do NOT use post-2023-03-31 observations to debug or tune transformations.

Processed files may physically contain data through 2026.

When reading any such file for value-based processing, predicate-filter the read so that:

    date <= 2023-03-31

Reading schema or metadata without inspecting post-2023-03-31 values is permitted if necessary to understand the stored format.

The transformation code should be generic enough that the same frozen implementation can later be used by the holdout pipeline.

Do NOT execute that holdout transformation in this task.


# 2. Allowed Processed Inputs

Use only processed inputs.

Relevant inputs include:

    data/processed/nse_cm_2013_2026.parquet

    data/processed/nse_trading_calendar_2013_2026.parquet

    data/processed/membership_official/
        nifty500_official_membership_intervals.parquet

    data/processed/security_identity_official/
        dated_security_identity.parquet
        historical_series_classification.parquet
        dated_alias_collisions.csv

    data/processed/corporate_action_treatment/
        in_universe_event_treatments.parquet
        nse_corporate_actions_treated_through_2023_03_31.parquet
        bonus_debenture_delayed_recognition.csv

    results/corporate_action_treatment/
        bonus_debenture_signal_timing_audit.csv

The following superseded membership artifact is prohibited and must not be
read or used as a fallback:

    data/processed/membership_audit/
        nifty500_membership_intervals.parquet

Inspect the actual schemas on disk before coding.

Do not assume a column exists merely because it was mentioned in an earlier script or document.

The files on disk are the source of truth for their current schemas.

Do NOT use the NIFTY 500 TRI in this stage.

The benchmark is not required to construct the stock-level research panel.


# 3. Required Workflow Before Coding

Before implementing the panel:

1. Read the relevant sections of `../../plan.md`.
2. Inspect the schemas of all required processed inputs.
3. Inspect basic BUILD-period metadata only:
   - row counts
   - date ranges
   - column types
   - uniqueness
   - missingness relevant to construction
4. Write a short implementation plan.
5. Identify any ambiguity, contradiction, or missing field.
6. Only then implement.

Do not invent economic assumptions silently.

If an assumption is genuinely unspecified:

- choose no assumption if the case can simply remain unresolved;
- otherwise use the most conservative defensible interpretation;
- isolate the choice in configuration/constants;
- document it explicitly in `../audits/DATA_AUDIT.md`.


# 4. Conceptual Data Model

The panel must preserve the distinction between:

    market observation
    security identity
    index membership
    economic return
    corporate-action state
    data quality
    execution-relevant information

Do NOT collapse these concepts into a single generic "eligible" flag.

The research panel is a security-date dataset.

Conceptually:

    date × permanent security identity

with the contemporaneous traded symbol and market observation attached.


# 5. Security Identity

A ticker is not itself a permanent security identity.

Use the existing processed security-identity layer.

For each market observation preserve, where available:

- permanent/internal security identity
- contemporaneous NSE symbol
- ISIN
- series
- date

Do NOT rewrite historical rows to use current or terminal symbols.

Example:

    historical traded symbol = MINDTREE
    later symbol            = LTIM

Do not replace historical MINDTREE rows with LTIM merely for cosmetic consistency.

Instead, connect them through the security-identity layer where the evidence supports continuity.


## 5.1 Rename versus structural event

A supported ticker rename may preserve security identity.

A merger, demerger, scheme of arrangement, acquisition, delisting, or successor-security relationship must NOT automatically be treated as a ticker rename.

Do not splice unrelated predecessor/successor return paths.

If identity cannot be established confidently:

    flag it

Do not guess.

Do not silently drop unresolved NIFTY 500 members.


# 6. Point-in-Time NIFTY 500 Membership

Historical membership must be point-in-time.

Membership interval semantics are:

    valid_from <= date < valid_to

where missing `valid_to` means open-ended.

Membership begins on the effective trading date, not the announcement date.

Ensure that overlapping membership records cannot cause a security to appear twice in the index universe on the same date.


## 6.1 Critical ordering rule

DO NOT restrict a security's historical price/return data to dates on which it was already a NIFTY 500 member.

Construct valid historical market/return history first.

Attach membership afterward as a separate state.

This is necessary because a security may enter NIFTY 500 later while its pre-entry market history is still required for momentum formation.

For example:

    stock enters NIFTY 500 in 2018

Its valid 2017 price history may still be required to determine whether it has enough trailing history for a later signal.

Do not erase that history.


# 7. Trading Calendar

Use:

    data/processed/nse_trading_calendar_2013_2026.parquet

as the canonical NSE trading-session calendar.

Do NOT infer trading days from Monday-Friday logic.

The historical sample includes genuine Saturday/Sunday special trading sessions.

Calendar-based lags must operate over actual NSE sessions.


# 8. Market Observation Rules

Use the processed NSE cash-market data.

For every security/date observation, preserve at minimum:

- date
- permanent security identity
- contemporaneous symbol
- ISIN
- series
- open
- high
- low
- close
- previous close if available
- volume
- traded value


## 8.1 Series handling

Do NOT globally assume that:

    series == "EQ"

is sufficient to define every historically valid observation.

Follow `../../plan.md`:

identify the actual eligible NSE cash-equity series for a security/date.

Do not represent the same economic security twice on the same date merely because it appears under multiple series.

If series selection is ambiguous, flag the observation/security.


## 8.2 Market-data validation

Validate:

- security-date uniqueness
- finite relevant prices
- positive tradable prices where required
- nonnegative volume
- nonnegative traded value
- sensible OHLC ordering
- duplicate identity/date observations
- conflicting series observations

Do not automatically delete exchange exceptions without recording them.


# 9. Missing and Stale Data

Never backfill a historical price using a future observation.

Never fill an unobserved return with zero merely to complete a rolling window.

Never treat a missing stock observation as a missing market session.

Never treat a stale price as an executable quote.

If a stale mark concept is useful for later accounting, it may be represented as a quality field, but do not manufacture a new market observation.

Preserve explicit reason codes for missing or unusable observations.


# 10. Corporate Actions and Research Returns

Use the accepted parent-event treatment table and its reconciled treated-event
artifact under `data/processed/corporate_action_treatment/`.

Do not access raw corporate-action files.

The purpose of this stage is to create an audited **feature return series**, not the final implementable-account corporate-action ledger.


## 10.1 Keep two concepts separate

The project later requires:

    A. total/economic returns for research features

and:

    B. raw-price account accounting with explicit cash/share events

This task implements A only.

Do NOT implement account-level tax lots, dividend receivables, settlement, bonus tax lots, merger consideration ledgers, or execution accounting here.


## 10.2 Return construction

At minimum construct:

    daily_price_return
    daily_total_return

For a simple cash dividend D and share transformation ratio s new shares per old share, follow the convention in `../../plan.md`:

    1 + r = (s * P_t + D) / P_(t-1)

Use a convention-consistent implementation for combined events.

Document units carefully.


## 10.3 Dividends

A valid cash dividend should enter the economic/total return on the appropriate ex-date.

Do not add a dividend twice.

Do not alter raw execution prices.


## 10.4 Splits / subdivisions / consolidations

A share-count transformation must not create a fake economic gain or loss.

For example:

    previous state:
        1 share × ₹100

    2-for-1 split:
        2 shares × ₹50

must imply approximately zero economic return absent any genuine price move.


## 10.5 Bonus issues

A bonus issue must not create a fake price crash.

Use the parsed ratio where confidently available.

This panel only needs the economic total-return treatment.

The later implementable-account code will handle separate tax-lot basis/age rules.


## 10.6 Rights issues

Do not invent subscription value or entitlement proceeds.

Use the accepted rights-entitlement treatments. Do not recalculate or replace
their accepted valuation assumptions in this stage.


## 10.7 Structural events

Examples:

- merger
- demerger
- scheme of arrangement
- amalgamation
- capital restructuring
- unresolved successor event

Do not automatically treat these as simple return-adjustment events or splice
successor price history onto predecessor history. Preserve the four accepted
bonus-debenture events as strict ex-date total-return exceptions and do not
fabricate fair values.

Produce audit outputs identifying material cases intersecting the research universe.


# 11. ADV Construction

Follow `../../plan.md` exactly.

For security i on trading session d:

    ADV20(i,d)
      = mean rupee traded value
        over the 20 NSE trading sessions strictly preceding d

Today's traded value must NOT enter today's ADV.

Use the canonical NSE trading calendar.


## 11.1 Critical ADV rule

Do NOT implement ADV as merely:

    rolling mean of previous 20 observed rows for the stock

because the previous 20 stock rows are not necessarily the previous 20 NSE sessions.

The window is defined over the previous 20 market sessions.


## 11.2 Zero volume versus missing observation

A genuine observed session with zero trading volume:

    contributes zero traded value

and remains in the 20-session denominator.

A missing security observation:

    is NOT automatically a zero-volume session

and must not be silently imputed as zero.


## 11.3 Preserve ADV diagnostics

At minimum create:

- `adv20_lagged`
- `adv20_observation_count`
- `positive_volume_sessions_20`
- `adv20_complete`
- related data-quality/reason flag if incomplete

The later eligibility stage requires at least 15 positive-volume sessions in the preceding 20 NSE sessions, so preserve the information needed for that rule.

Do not implement final momentum eligibility in this stage.


# 12. Required Panel Fields

The exact schema may adapt to actual processed inputs, but the resulting panel should contain at minimum:

    date

    security_id
    symbol
    isin
    series

    in_nifty500

    open
    high
    low
    close
    volume
    traded_value

    daily_price_return
    daily_total_return

    adv20_lagged
    adv20_observation_count
    positive_volume_sessions_20
    adv20_complete

    corporate-action flags
    corporate_action_review_required

    identity_status
    market_data_status
    return_status

    exclusion/review reason codes

Preserve useful source/event identifiers where they improve auditability.

Also preserve:

    strict_total_return_available
    corporate_action_exception
    delayed_recognition_available
    momentum_signal_safe
    momentum_signal_exclusion_reason
    final_signal_available

`momentum_signal_safe` measures only the corporate-action timing dimension. It
is null on ordinary daily rows, true on formation rows unaffected by a partial
economic event, and false on the eight accepted Britannia
event/security/formation cases. A true value does not mean a globally valid
momentum signal.

`final_signal_available` is not evaluated in this stage and remains null. The
later strategy stage may set it only after combining corporate-action timing
safety with sufficient lookback history, valid returns, membership,
liquidity/tradability, and every other signal requirement.

Delayed-recognition values are metadata only. They must not be inserted into a
daily return or used to calculate momentum in this stage. Preserve the eight
Britannia exceptions in a separate audit keyed by `event_id`, `security_id`,
and `formation_date`.


# 13. Reason Codes

Use explicit, machine-readable reason/status codes.

Examples include:

    IDENTITY_UNRESOLVED
    CORPORATE_ACTION_UNRESOLVED
    STRUCTURAL_EVENT
    PRICE_MISSING
    PREVIOUS_PRICE_MISSING
    NON_EQ_OR_UNSUPPORTED_SERIES
    SERIES_AMBIGUOUS
    NOT_IN_NIFTY500
    STALE_PRICE
    ADV_UNAVAILABLE
    ADV_INCOMPLETE
    RETURN_UNAVAILABLE
    MARKET_OBSERVATION_INVALID

Do not force these exact names if the implementation has a cleaner equivalent.

The essential requirement is:

    no silent exclusion

Every problematic case must be traceable to an explicit reason.


# 14. Look-Ahead Protection

The implementation must be temporally causal.

Information attached to date t must not depend on future information in a way that would affect decisions at t.

In particular:

- point-in-time membership dates must be respected;
- no future price may repair a historical price;
- today's traded value cannot enter today's lagged ADV;
- future corporate actions cannot alter earlier signals;
- future ticker states must not improperly change historical membership/tradability;
- post-2023-03-31 values must not be accessed during this build task.


# 15. Warm-Up and Output Date Range

The research panel may begin in 2013 because warm-up history is required.

The output may therefore contain observations before the scored build window.

However:

    MAXIMUM OUTPUT DATE = 2023-03-31

No row later than 2023-03-31 may appear in the build panel.


# 16. Output Files

Produce at minimum:

    data/processed/research_panel_build.parquet

and:

    results/audit/panel_summary.csv

    results/audit/
        unresolved_identity_in_universe.csv

    results/audit/
        unresolved_corporate_actions_in_universe.csv

    results/audit/
        exclusion_reason_counts.csv

    results/audit/
        membership_count_by_rebalance.csv

    results/audit/
        return_sanity_checks.csv

    docs/audits/DATA_AUDIT.md

Additional small audit artifacts are permitted if they materially improve traceability.

Do not create unnecessary framework or dozens of redundant files.


# 17. DATA_AUDIT.md Requirements

Document:

- exact processed files used
- schemas actually encountered
- panel output schema
- row count
- first date
- last date
- unique security identities
- unique symbols
- NIFTY 500 observation counts
- membership-count diagnostics
- identity reconciliation statistics
- unresolved identity cases
- corporate-action reconciliation statistics
- unresolved corporate-action cases
- return-construction methodology
- ADV methodology
- series-selection methodology
- missing/stale-data treatment
- exclusion/review reason counts
- survivorship-bias protections
- look-ahead protections
- assumptions
- known limitations
- manual follow-up still required

Explicitly state:

    data/raw/ was not accessed.

Also explicitly report:

    maximum value date read
    maximum output date

and confirm:

    no post-2023-03-31 value observations were accessed during this task.


# 18. Required Tests

Tests should establish financial and temporal correctness rather than merely mirror the implementation.

Use small synthetic fixtures where the correct answer is known exactly.


## 18.1 Panel uniqueness

Verify that the panel cannot contain duplicate:

    security_id × date

observations after identity/series resolution.


## 18.2 Point-in-time membership

Example:

    valid_from = 2020-03-27

Then:

    2020-03-26 -> not member
    2020-03-27 -> member


## 18.3 Historical pre-membership data

A stock entering the index on date X may retain valid historical market observations before X.

Verify that attaching membership does not erase those prior observations.


## 18.4 Dividend

Example:

    previous close = 100
    ex-date close  = 98
    dividend       = 5

Expected:

    total return = (98 + 5) / 100 - 1
                 = +3%

while:

    raw price return = -2%


## 18.5 Split

A 2-for-1 split must not create a fake -50% economic return.

Example:

    previous close = 100
    ex-date close  = 50
    new shares per old share = 2

Expected economic return approximately zero.


## 18.6 Bonus

A correctly parsed bonus ratio must not create a fake mechanical crash.


## 18.7 Rename continuity

A supported:

    OLD -> NEW

ticker change for the same security must preserve identity/history.


## 18.8 Structural-event protection

A merger/demerger must not automatically splice unrelated histories together.


## 18.9 ADV causality

Construct an example where today's traded value is extremely large.

Verify that:

    ADV20_lagged(t)

does not change when only today's traded value changes.


## 18.10 ADV session semantics

Create a synthetic security that is missing on one market session.

Verify that the implementation distinguishes:

    genuine observed zero volume

from:

    missing observation

and does not simply roll over the last 20 security rows.


## 18.11 Special weekend session

Verify that a genuine Saturday/Sunday NSE special session participates normally in:

- date ordering
- lags
- ADV windows


## 18.12 Missing prices

Verify that a missing price:

- is not backfilled from the future
- does not become a zero return
- receives an explicit quality status


## 18.13 Unresolved identity

Verify that an unresolved membership/security mapping is:

    flagged

rather than guessed or silently removed.


## 18.14 Holdout protection

Add a test proving that build-panel construction cannot emit or consume value observations later than:

    2023-03-31


# 19. Performance and Engineering

The processed market dataset contains millions of rows.

Use efficient Parquet reads and dataframe operations.

Where possible, predicate-filter the Parquet read itself rather than loading 2023-2026 values and filtering afterward.

Avoid unnecessary full cross joins.

Avoid repeated loading of the full market dataset.

Do not add:

- database infrastructure
- Spark
- cloud services
- web apps
- workflow engines
- unnecessary abstractions

Keep the implementation readable and interview-defensible.

Use clear modules/functions with explicit contracts.


# 20. Things NOT to Implement

Do NOT implement any of the following in this task:

- 12-to-2 momentum signal
- momentum ranking
- top-decile selection
- equal-weight portfolio construction
- shadow portfolio
- 126-day volatility estimate
- volatility targeting
- VM
- MOM
- FIX
- FIXVOL
- transaction costs
- impact model
- execution scheduling
- position ledger
- settlement accounting
- dividend receivables
- tax lots
- capital-gains taxes
- portfolio NAV
- performance metrics
- bootstrap inference
- strategy charts
- holdout evaluation

Those are later stages.


# 21. Existing Code

You may inspect existing Python source files and project documentation to understand:

- processed-file provenance
- field meanings
- naming conventions
- prior identity/corporate-action transformations

Do not blindly reuse old code if it violates this specification.

Do not rerun acquisition scripts.

Do not access `data/raw/`.


# 22. Final Validation

Before declaring the panel complete, run:

- the full panel-specific test suite
- structural validation
- BUILD-window temporal validation
- audit-output generation

The implementation should fail loudly on violations of major invariants rather than silently repairing them.


# 23. Final Report to User

After implementation, report:

    tests passed
    tests failed

    panel row count
    first panel date
    last panel date

    number of permanent identities
    number of contemporaneous symbols

    number of NIFTY 500 security-date observations

    membership-count range at formation/month-end dates

    resolved identity count
    unresolved identity count

    corporate-action adjusted count
    unresolved corporate-action count

    ADV incomplete count

    exclusion/review reason counts

    maximum value date read
    maximum panel output date

    any assumptions made
    any unresolved issues
    anything requiring user approval

Explicitly confirm whether:

    data/raw/ was accessed

and whether:

    any post-2023-03-31 value data was accessed

Both should be NO.

Do not automatically begin strategy implementation afterward.

Stop and wait for review.


# 24. Acceptance Standard

The goal is not merely to make a Parquet file.

The panel is accepted only if it is:

- point-in-time
- non-survivorship-biased to the extent supported by available data
- temporally causal
- identity-aware
- corporate-action-aware
- calendar-correct
- explicit about unresolved cases
- auditable
- reproducible
- understandable enough to defend line-by-line in a quantitative-research interview

Again:

    DO NOT ACCESS data/raw/ FOR ANY REASON.

    DO NOT ACCESS POST-2023-03-31 VALUE DATA.

    DO NOT BEGIN THE MOMENTUM STRATEGY AFTER COMPLETING THIS TASK.
