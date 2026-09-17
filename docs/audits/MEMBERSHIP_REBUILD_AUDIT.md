# Official NIFTY 500 Membership Rebuild Audit

## Scope and conclusion

This work reopened only the upstream historical-universe evidence stage. It did not rebuild the research panel, rank momentum, construct portfolios, calculate performance, or evaluate the holdout.

The historical-universe gate now **passes** for 28 August 2014 through 31 March 2023. The result is supported by an official full CNX 500 seed, the official index inclusion/exclusion ledger, individual official NIFTY/CNX notices, and nine independent full-constituent checkpoints. There are no unresolved membership identities, failed event applications, snapshot differences, or prelisting failures in the new reconstruction.

This pass does not mean the total-return panel is ready to rebuild automatically. There are still explicit corporate-action cases requiring economic treatment. Those cases are preserved in a separate audit described below.

## Authoritative evidence

The evidence hierarchy was:

1. Official full CNX 500 / NIFTY 500 constituent snapshots.
2. The official Nifty Indices `IndexInclExcl.xls` event ledger.
3. Official scheduled review and off-cycle replacement notices.
4. Official merger, delisting, category, and concentration-norm notices that changed NIFTY 500 membership.
5. The previous third-party reconstruction only for discovery and discrepancy comparison.

The seed is `cnx500_Aug2014.pdf` inside the official `indices_dataAug2014.zip` monthly archive. The table is dated **28 August 2014** and contains exactly **500 unique constituents**. The ZIP SHA-256 is `6602912e34d6b6fc66f1cda520094669029c006ae89a2ac0e5aa0a3fe82af360`.

The evidence manifest contains:

| Document type | Files |
|---|---:|
| Official index-change notices | 107 |
| Official monthly constituent archives | 9 |
| Extracted official full snapshots | 9 |
| Official event ledger | 1 |
| Official press-release archive | 1 |

All 107 notices have a source URL, retrieval timestamp, publication date, original byte count, SHA-256, parsed additions/deletions, and parsing status. Seventy-two contain parsed CNX/NIFTY 500 rows; 35 were preserved but contain no base-index event rows. No document has a parser error. Ninety-four notices have one effective-date candidate and the remainder preserve all candidates. Every notice with parsed NIFTY 500 rows has at least one effective-date candidate.

The official event ledger contains 769 source rows through 14 September 2020. Two economic event keys are repeated exactly in the source: RELCAPITAL exclusion and MFSL inclusion on 5 September 2017. The source rows remain in the raw ledger audit, while each event is applied once.

Three ledger rows needed reviewed notice-backed symbol resolution:

- TECHNO exclusion on 8 August 2018 because the ledger abbreviates the company name differently from the notice.
- YESBANK exclusion on 19 March 2020.
- SWSOLAR inclusion on 19 March 2020 after an official timing revision.

One official notice dated 7 September 2020 contains both a 14 September change and changes effective 25 September. Eight NIFTY 500 rows were assigned to 25 September using that notice's section-specific effective-date statement. These eleven manual rows are recorded in `data/manual/membership_official_event_overrides.csv`; none relies on a third-party membership value or a guessed replacement.

## Reconstructed membership

The authoritative event table contains **1,079 rows** on **63 effective dates**: 540 inclusions and 539 exclusions. The net increase of one is official. On 1 April 2016, the notice has 75 exclusions and 76 inclusions because Tata Motors DVR was added as an additional security.

The interval table contains **1,040 half-open intervals** across **865 security identities**:

```text
valid_from <= date < valid_to
```

The coverage begins on 28 August 2014. Active memberships at the cutoff have a blank `valid_to`. There are 501 active securities on 31 March 2023.

At every event date, the audit verifies:

```text
count_before - exclusions + inclusions = count_after
```

All 1,079 event rows apply successfully. Event-date and month-end counts range from **500 to 501**. No count is forced to 500.

## Independent snapshot validation

All full official snapshots map to dated security identities and agree exactly with the reconstructed state:

| Snapshot date | Official count | Reconstructed count | Symmetric difference |
|---|---:|---:|---:|
| 2014-08-28 | 500 | 500 | 0 |
| 2014-09-30 | 500 | 500 | 0 |
| 2015-09-30 | 500 | 500 | 0 |
| 2015-10-30 | 500 | 500 | 0 |
| 2020-09-30 | 501 | 501 | 0 |
| 2020-10-30 | 501 | 501 | 0 |
| 2021-03-31 | 501 | 501 | 0 |
| 2021-09-30 | 501 | 501 | 0 |
| 2022-03-31 | 501 | 501 | 0 |

The freely available monthly archives inspected for September 2022 and March 2023 did not contain a NIFTY 500 full-constituent PDF. Changes after the March 2022 checkpoint are therefore validated through the official press-release sequence and event arithmetic rather than a later independent full snapshot. This reduces redundant validation after March 2022 but does not create an unexplained membership gap.

## Dated identity and prelisting validation

The new dated identity artifact contains **3,195 observed symbol/ISIN histories** mapped to **2,605 security IDs**. It uses only EQ, BE, and BZ observations for the common-equity identity spine. Other instruments that reuse an issuer ticker cannot create an ambiguous membership identity.

The mapping records 565 reviewed evidence edges:

- 243 official symbol-change edges.
- 322 contiguous same-symbol ISIN transitions.

There are zero dated alias collisions in the final mapping, zero unresolved seed/event identities, and no case where one economic security occupies two NIFTY 500 slots on the same date.

The current NSE equity master is used as identity/listing corroboration only. If its current listing date is later than observed historical trading, the audit uses first observed trading as a proxy and does not treat the later current-master date as an original listing date.

The prelisting audit has **zero failures** and **zero proxy reviews**. The known impossible cases now begin membership only after observed listing/trading:

| Security | First observed trade | First official membership |
|---|---|---|
| ALKEM | 2015-12-23 | 2016-09-30 |
| ANGELONE / ANGELBRKG | 2020-10-05 | 2021-03-31 |
| INDIGO | 2015-11-10 | 2016-09-30 |
| LALPATHLAB | 2015-12-23 | 2016-09-30 |
| SYNGENE | 2015-08-11 | 2016-04-01 |

## Comparison with the previous reconstruction

The previous `snapshot_floor` intervals were never used to fill the new state. They were mapped where possible and compared at every boundary where either source changes.

The interval-level discrepancy audit contains **5,915 rows across 76 state intervals**:

| Discrepancy side | Rows | Unique mapped securities/symbols |
|---|---:|---:|
| Official only | 2,885 | 151 securities |
| Previous source only | 1,522 | 106 securities |
| Previous source symbol not mappable | 1,508 | 23 symbols |

At the 105 month-end/start/cutoff checkpoints, the sources differ on every date. The mapped symmetric difference ranges from 19 to 193 securities and averages 59.64. This is evidence that the prior source is materially different, especially early in the sample; it is not an instruction to alter the official path.

## Historical NSE series policy

The series policy is backed by the saved official NSE series legend:

- EQ is treated as fully paid equity.
- BE/BZ is treated as trade-for-trade common equity only when the same ISIN is observed in EQ, the current equity master corroborates it, or an official NIFTY 500 identity corroborates it.
- Rights entitlements using BE remain excluded.
- Other series remain outside the common-equity identity spine.

The processed classification contains 3,086 fully paid EQ groups, 1,826 corroborated BE/BZ trade-for-trade equity groups, and 74 excluded rights-entitlement groups. Twelve BE/BZ groups remain unresolved across eleven symbols: AICHAMP, DCHL, ELECTROSL, JAINSTUDIO, JEYPORE, JUPITER, OCLINDIA, RAMGOPOLY, TCPLTD, VISESHINFO, and VKSPL. None maps to an official NIFTY 500 membership identity in this reconstruction.

## Corporate-action repairs and remaining work

The new cutoff-safe corporate-action artifact contains **21,352 rows**, from 3 January 2013 through 31 March 2023. It does not contain post-cutoff records.

Ten source rows were repaired without inventing economic treatment:

- GENESYS `Rs.0125` now parses as 0.125.
- JKTYRE `Rs 0 .70` now parses as 0.70.
- SBI's dotted face-value split now parses as 10 to 1.
- Two multi-event split records now retain their explicit old/new face values while remaining reviewable as multi-event actions.
- ZEEL preference-share bonus is no longer an ordinary-equity bonus.
- Four bonus-debenture records are now structural debenture entitlements rather than ordinary-equity bonuses.

The resolved ordinary-action counts include 11,626 dividends, 292 bonuses, and 246 splits. Records with multiple simultaneous event types or missing economic amounts remain explicit rather than being simplified.

There are **494 unresolved or treatment-dependent corporate-action rows** overall. Of these, **149 occurred while the mapped security was an official NIFTY 500 member**:

| Class | In-universe unresolved rows |
|---|---:|
| Buyback | 86 |
| Rights | 39 |
| Bonus or multi-event bonus | 8 |
| Dividend with missing/combined treatment | 7 |
| Split or multi-event split | 5 |
| Debenture entitlement | 4 |

Thirty-three unresolved corporate-action rows do not map to a dated identity, but none is in the official NIFTY 500 universe on its ex-date. These cases do not invalidate the membership reconstruction. They must remain visible when the future total-return panel is rebuilt.

## Output inventory

Primary implementation and tests:

- `src/brindco_momentum/data/membership_rebuild.py`
- `tests/test_membership_rebuild.py`
- `data/manual/membership_official_event_overrides.csv`

Raw evidence:

- `data/raw/membership_official/press_release_archive.html`
- `data/raw/membership_official/ledgers/IndexInclExcl.xls`
- `data/raw/membership_official/monthly/` — nine official ZIP archives.
- `data/raw/membership_official/snapshots/` — nine extracted official snapshots.
- `data/raw/membership_official/notices/` — 107 original official PDFs.
- `data/raw/series_reference/legend_of_series.html`

Processed membership:

- `data/processed/membership_official/nifty500_official_membership_intervals.parquet`
- `data/processed/membership_official/nifty500_authoritative_events.parquet`
- `data/processed/membership_official/nifty500_authoritative_events.csv`
- `data/processed/membership_official/nifty500_official_seed.parquet`
- `data/processed/membership_official/nifty500_official_snapshots.parquet`
- `data/processed/membership_official/nifty500_official_event_ledger.parquet`
- `data/processed/membership_official/nifty500_notice_events.parquet`
- `data/processed/membership_official/membership_evidence_manifest.csv`

Processed identity, series, and corporate actions:

- `data/processed/security_identity_official/dated_security_identity.parquet`
- `data/processed/security_identity_official/security_identity_summary.parquet`
- `data/processed/security_identity_official/identity_evidence_edges.csv`
- `data/processed/security_identity_official/dated_alias_collisions.csv`
- `data/processed/security_identity_official/historical_series_classification.parquet`
- `data/processed/corporate_actions_official/nse_corporate_actions_classified_through_2023_03_31.parquet`

All detailed CSV audits are under `results/membership_rebuild_audit/`. They include source parsing, effective-date coverage, event application, event/month-end counts, checkpoint reconciliation, interval-level differences against the previous source, prelisting checks, identity mappings, series counts, corporate-action repairs, and every remaining corporate-action case.

## Test results

Focused upstream suite:

```text
.......                                                                  [100%]
7 passed in 4.25s
```

The plain repository-wide command initially encountered a pre-existing pytest collection collision because both `project/test_panel_build.py` and `tests/test_panel_build.py` use the module name `test_panel_build`. No test ran in that attempt. Running the full suite with pytest's `importlib` collection mode avoids the name collision without changing either file:

```text
.........................................                                [100%]
41 passed in 7.96s
```

The existing failed-panel artifact was not rebuilt or modified. Its retained SHA-256 is `5a122e29bcc5b9a1b16a727c933e11165dbfad846cd93950301e12336aed339e`.

## Assumptions and limits

- Effective membership begins on the effective trading date stated by the official notice. Announcement dates are never used as membership dates.
- Membership intervals are half-open. An exclusion effective on date `t` closes the prior interval at `valid_to = t`; an inclusion begins at `valid_from = t`.
- The official August 2014 snapshot is the seed. The prior third-party history does not contribute members to it.
- Same-symbol ISIN transitions are joined only when the observed histories are non-overlapping and no more than 31 calendar days apart. Every such edge is preserved in the identity-edge audit.
- Official symbol changes join dated aliases when observed old/new histories occur around the official effective date. A future ticker does not rewrite a historical membership symbol.
- The current NSE equity master is corroboration, not historical index-membership evidence.
- The 501-security state is retained because it follows the official event arithmetic and is independently confirmed by five full snapshots from September 2020 through March 2022.
- The last independent full snapshot is 31 March 2022. Official notices and arithmetic provide the evidence from April 2022 through the cutoff.
- The 12 unresolved BE/BZ groups are excluded unless later official identity evidence establishes common-equity status. None affects the reconstructed NIFTY 500 state.
- Complex corporate actions are not assigned fabricated wealth transformations. The 149 in-universe treatment-dependent rows are the material prerequisite for a future total-return panel rebuild.

No issue in this stage requires user approval. The next stage must be separately authorized because this task explicitly stops before rebuilding the research panel.
