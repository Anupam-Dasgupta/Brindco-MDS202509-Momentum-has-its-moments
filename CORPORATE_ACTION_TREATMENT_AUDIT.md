# Corporate-action treatment audit

## Final status

This final cleanup is limited to the four mandatory bonus-debenture events. It
uses official NSE and BSE closing trades to build a separate delayed-recognition
overlay and tests every shadow/build-period monthly 12-to-2 window that overlaps
an economic leg. It does not value an entitlement on the equity ex-date, modify
an equity price, calculate an equity return, rebuild the panel, rank momentum,
construct a portfolio, or inspect performance or holdout values.

Two different gates remain intentionally separate:

| Gate | Result | Reason |
|---|---:|---|
| Strict ex-date total-return treatment | **FAIL** | The four entitlements still lack contemporaneously observable ex-date fair values. |
| Delayed-recognition research feature | **FAIL** | The two Britannia recognition dates fall in later holding months and create partial-event 12-to-2 windows. |

The accepted treatment artifact remains byte-for-byte unchanged. Its four
target rows remain blocking under the strict total-return convention.

## Accepted-artifact immutability

```text
Artifact:
data/processed/corporate_action_treatment/
    in_universe_event_treatments.parquet

Rows                                  : 149
Distinct event_id values              : 149
Pre-task SHA-256                      : 5ddea240585838652401277a3b8b3e417d21b2919c9e6a8906cb3ea328c858cf
Post-task SHA-256                     : 5ddea240585838652401277a3b8b3e417d21b2919c9e6a8906cb3ea328c858cf
Accepted treatment rows changed      : 0
Protected non-target rows changed     : 0 / 145
Target treatment rows changed         : 0 / 4
```

The artifact was not rewritten. Full-file equality is stronger than a comparison
over selected treatment columns.

## Strict ex-date gate

```sql
corporate_action_gate_passes =
    count(distinct event_id with exactly one parent treatment) == 149
    AND count(event_id where blocks_total_return == true) == 0
```

```text
Parent events with exactly one treatment       : 149 / 149
Duplicated event_id values                      : 0
Missing event_id values                         : 0
Treatments without a valid parent event_id      : 0
Events with blocks_total_return = true          : 4
Strict corporate-action gate                    : FAIL
```

The four rows retain `UNRESOLVED_STRUCTURAL_EVENT`, null ex-date entitlement
values and `blocks_total_return = true`. An official price observed later does
not make that price knowable on the equity ex-date.

## Official delayed-recognition values

The first qualifying observation must have a finite close inside its daily
range, positive quantity, positive traded value and a positive number of
trades. A zero-volume quote, carried close, listing reference price or
theoretical value is rejected.

When NSE and BSE both provide candidates, selection is deterministic:

1. earliest actual official trade date;
2. highest traded value on that date;
3. venue name as the final tie-break.

All candidates, including those not selected, are preserved in
`price_candidates_json` in the delayed-recognition output.

| Event | Entitlement leg | First selected trade | Venue | Close (₹ per debenture) | Quantity per old share | Value per old share (₹) |
|---|---|---:|---:|---:|---:|---:|
| BLUEDART, 2014-11-17 | INE233B08087 | 2014-11-28 | BSE | 11.00 | 7 | 77.00 |
| BLUEDART, 2014-11-17 | INE233B08095 | 2014-11-28 | BSE | 11.00 | 4 | 44.00 |
| BLUEDART, 2014-11-17 | INE233B08103 | 2014-11-28 | BSE | 11.00 | 3 | 33.00 |
| NTPC, 2015-03-20 | INE733E07JP6 | 2015-03-30 | NSE | 12.71 | 1 | 12.71 |
| BRITANNIA, 2019-08-22 | INE216A07052 | 2019-10-09 | NSE | 30.80 | 1 | 30.80 |
| BRITANNIA, 2021-05-25 | INE216A08027 | 2021-07-20 | NSE | 29.25 | 1 | 29.25 |

Blue Dart's event-level observable entitlement is therefore ₹154.00 per old
equity share. The three BSE trades on 28 November are essential: the first NSE
trades occurred on 1 December, which by themselves would have put the
recognition legs in a later holding month.

The NTPC and Britannia NSE observations were compared with same-day official
BSE candidates. NSE won the fixed traded-value tie-break in all three cases.

## Quotation and accrued interest

The selected observations are capital-market trade prices in rupees per actual
debenture. No face-value scaling is applied. The official exchange convention
for these capital-market bond trades is dirty price, so accrued interest is
already included and is not added again.

The delayed-recognition output preserves:

```text
face_value_per_entitlement
quote_face_value_basis
quote_unit_basis
clean_or_dirty_price
accrued_interest_treatment
price_normalization_method
quote_convention_evidence_source
```

The relevant official convention sources are:

- NSE capital-market bond example: `https://nsearchives.nseindia.com/content/yield_example.pdf`
- BSE clean/dirty price booklet: `https://www.bseindia.com/downloads1/Clean_Price_Booklet.pdf`

## Information timestamps

The exact historical bhavcopy publication times are unavailable. The audit
therefore treats an official closing price as available at `00:00 Asia/Kolkata`
on the following calendar day. The same conservative rule applies when an
official terms or identity source supplies a date without a timestamp.

```text
information_available_timestamp = max(
    terms availability,
    entitlement identity availability,
    official closing-price availability
)
```

Formation is represented at `00:00 Asia/Kolkata` on the day after the canonical
last NSE trading session of the preceding month. Orders may execute only later,
under the strategy's execution rules. None of the four conclusions depends on
same-session timestamp equality.

## Multi-leg 12-to-2 timing gate

For each formation window, the required economic legs are the equity ex-date
and every mandatory entitlement-tranche recognition date. A formation is safe
only when the window contains none of those legs or contains all of them, and
all required information is available by formation.

```text
event_in_window == tranche_1_in_window == ... == tranche_n_in_window
```

The audit evaluates every formation from the August 2014 shadow schedule
through the March 2023 build schedule whose window contains at least one leg.

| Event | Ex-date holding month | Recognition holding month(s) | First affected formation | Audited formations | Unsafe formations | Event result |
|---|---:|---:|---:|---:|---:|---:|
| BLUEDART, 2014-11-17 | 2014-11 | 2014-11 / 2014-11 / 2014-11 | 2014-12-31 | 11 | 0 | **SAFE** |
| NTPC, 2015-03-20 | 2015-03 | 2015-03 | 2015-04-30 | 11 | 0 | **SAFE** |
| BRITANNIA, 2019-08-22 | 2019-08 | 2019-10 | 2019-09-30 | 13 | 4 | **UNSAFE** |
| BRITANNIA, 2021-05-25 | 2021-05 | 2021-07 | 2021-06-30 | 13 | 4 | **UNSAFE** |

The 2019 Britannia partial windows are formations dated 2019-09-30,
2019-10-31, 2020-08-31 and 2020-09-30. The 2021 Britannia partial windows are
formations dated 2021-06-30, 2021-07-30, 2022-05-31 and 2022-06-30.

The first formation for each Britannia event also predates the first traded
price. Later formations do not cure the problem: at the rolling-window exit
boundary, the entitlement recognition remains in the window after the equity
ex-date has left it.

## Research-feature gate

```text
RESEARCH_FEATURE_CORPORATE_ACTION_GATE = PASS only if:

1. the accepted 149-row treatment artifact is unchanged;
2. every required entitlement identity and quantity is known;
3. every selected value is an actual official trade;
4. quotation basis and accrued-interest treatment are established;
5. required information is available by each relevant formation; and
6. no formation contains a partial economic event.
```

All evidence and immutability requirements pass. Requirement 6 fails for the
two Britannia events. Therefore:

```text
RESEARCH_FEATURE_CORPORATE_ACTION_GATE = FAIL
```

No delayed-recognition value may enter the research panel unless a later,
explicitly approved methodology resolves the partial-window problem. This task
does not propose or implement such a change.

## Strict ex-date evidence limitation

- **Blue Dart:** the pre-ex-date release fixed quantities, face value,
  frequency and tenor but left coupon rates to the Board. Complete terms appear
  only after the equity ex-date.
- **NTPC:** BSE timestamps the 8.49% coupon disclosure at 19:47:23 on the
  ex-date, after the equity close.
- **Britannia 2019:** the official scheme says the Board determines the coupon
  on the 2019-08-23 record date, after the equity ex-date.
- **Britannia 2021:** the pre-ex terms defer coupon setting; the 5.5% coupon was
  fixed with the 2021-06-03 allotment.

Consequently, the statement "exact ex-date fair value was contemporaneously
observable" remains false for all four events.

## Outputs and tests

Created:

- `data/processed/corporate_action_treatment/bonus_debenture_delayed_recognition.csv`
- `results/corporate_action_treatment/bonus_debenture_signal_timing_audit.csv`

Implementation and tests:

- `bonus_debenture_delayed_recognition.py`
- `tests/test_bonus_debenture_delayed_recognition.py`

Complete repository test result:

```text
61 passed in 4.00s
```
