# Targeted corporate-action resolution audit

This stage researched the 31 scored-selection events and seven warm-up-only events identified by the accepted materiality audit, plus four source actions with unresolved identity. It did not change the official index universe, accepted identity history, accepted 149-event treatment table, four bonus-debenture strict daily exceptions, or historical equity quotes. The prior return and signal artifacts are preserved by SHA-256 in [`results/event_resolution/artifact_hashes.csv`](../../results/event_resolution/artifact_hashes.csv); the prior formation and winner files are also retained under `results/event_resolution/baseline/`.

The manual economic decisions are in [`data/manual/corporate_action_resolutions_v1.csv`](../../data/manual/corporate_action_resolutions_v1.csv). The separate research register in [`data/manual/corporate_action_research_v1.csv`](../../data/manual/corporate_action_research_v1.csv) records the unresolved evidence gaps and orphan-identity conclusions. The pipeline applies only the eight defensible treatments in `src/brindco_momentum/data/stock_total_returns.py`; `src/brindco_momentum/signals/momentum_signal.py` then regenerates monthly returns, formations, ranks, and winners without overrides.

| Measure | Before | After |
| --- | ---: | ---: |
| Scored-priority economic events unresolved | 31 | 24 |
| Warm-up-only economic events unresolved | 7 | 6 |
| Scored signal observations blocked by these events | 152 | 119 |
| Warm-up signal observations blocked by these events | 55 | 41 |
| Total in-scope signal observations blocked | 207 | 160 |
| Identity-orphan source actions unresolved | 4 | 2 exact bond identities; neither is ordinary equity |

The 160 remaining blocked observations span 71 formation dates: 64 scored dates and all seven warm-up dates. These are independent of the accepted Britannia bonus-debenture timing exclusions. The current momentum audit reports 169 independent event blockers in total because it also includes nine already accepted Britannia-related blockers outside this research queue. The eight specified Britannia partial-window exclusions remain intact.

The corrected treatments changed eligibility on 33 formation dates and changed `K = ceil(0.10 × eligible count)` on nine dates. Winner membership changed in 17 security/formation rows: 13 entries and four exits. Entries were ADANIENT, ADVANTA, AMTEKAUTO, CUB, DMART, LGBBROSLTD, PRISMCEM, SADBHAV, TANLA, and TUBEINVEST; exits were CGCL, JSLHISAR, SRF, and WOCKPHARMA. Repeated names represent distinct formations. The exact affected dates, old/new eligibility, scores, ranks, seats, winner flags, and relevant event IDs are in [`results/event_resolution/downstream_signal_changes.csv`](../../results/event_resolution/downstream_signal_changes.csv). Changes on a date with multiple resolved events are jointly attributable; the audit does not assign a false single-event causal share.

## Defensible treatments added

| Event | Holder economics entered | Evidence basis and limitation |
| --- | --- | --- |
| NIACL, 2018-06-27 | 1:1 ordinary bonus plus ₹5 cash per pre-event share; `2 × ex-close + 5` | NSE source action and company annual report establish both ordinary legs. |
| TATACHEM, 2020-03-04 | 1.14 already-listed TATACONSUM ordinary shares per old share; value ₹398.088 at its actual NSE ex-date EQ close | Tata transaction documents establish the ratio; official bhavcopy records ₹349.20 for the received class. Value becomes observable after that session closes. |
| FDC, 2018-02-26 | No direct holder adjustment under explicit passive-holder `DO_NOT_TENDER` assumption | SEBI-filed voluntary tender terms allow nonparticipation. The tender price is not credited to every holder. |
| SHRENUJ, 2014-07-15 | 1:1 ordinary bonus plus ₹0.60 per pre-event share | Company postal-ballot filing establishes the cash equivalence across the bonus. This also clears seven warm-up observations. |
| ABIRLANUVO, 2016-01-20 | 26 already-listed PFRL ordinary shares per five old Nuvo shares; value ₹1,137.76 per old share at NSE ex-date EQ close | Company scheme establishes the ratio; official bhavcopy records ₹218.80 for the received class. Value becomes observable after that session closes. |
| LGBBROSLTD, 2014-07-04 | 1:1 ordinary bonus plus ₹7 cash per pre-event share | Official exchange action records establish the two ordinary legs. |
| TANLA, 2020-06-09 | No direct holder adjustment under explicit passive-holder `DO_NOT_TENDER` assumption | NSE-filed offer document makes tender participation optional. |
| RAJTV, 2014-03-25 | ₹10-to-₹5 split followed by 1:1 bonus on post-split shares; four resulting shares per old share | Company annual report and NSE action establish both same-date legs. This clears seven warm-up observations. |

For a resolved event, the daily holder-return numerator is `share_multiplier × ordinary ex-date close + cash per old share + evidenced listed-share entitlement value`. Optional non-tendered buybacks retain the ordinary price return. The listed-share cases value shares of an already traded ordinary class at the actual ex-date close; they do not assign synthetic prices to unlisted successors or model temporary settlement constraints. All ratios and assumptions are explicit in the manual artifact. The accepted four bonus-debenture strict daily returns remain unavailable.

## Four source events lacking identity

MONNETISPA (2018-08-29) and SUPPETRO (2022-07-22) have exact EQ issuer/ISIN matches in the accepted identity history. Official NIFTY 500 membership for those permanent securities ended before the respective actions, with no later membership through the development cutoff. Their capital reduction and dividend therefore cannot enter a required member lookback; their economics were not inserted into returns.

The two IDFCFIRSTB events on 2015-10-29 are H3 and H4 **bondholder** buyback-payment records, not EQ actions. The source appears to carry a later ordinary-equity ISIN retroactively, so it is unsafe to map either record to an equity security or to claim its precise historical bond ISIN. Exact debt identities remain unresolved, but the source series, ₹5,000 face value, and bondholder subject exclude these from the ordinary-equity signal. These conclusions are checked against the raw NSE records, accepted dated identities, and official membership intervals by `src/brindco_momentum/data/event_resolution_audit.py`.

## Remaining evidence gaps

The 24 scored-priority cases still lacking a defensible daily value are IIFL (two events), RELCAPITAL, CESC, AARTIIND, COX&KINGS, STAR, BALKRISIND, ABB, CGPOWER, SUNDARMFIN, JUBLPHARMA, FRETAIL, ARVIND, LAKSHVILAS, MFSL, GAYAPROJ, MOTHERSON, BSOFT, BEML, TATACOMM, GRASIM, ADANIENT, and IDFC. Most involve a newly distributed or temporarily unlisted share: official documents identify the successor and usually the ratio, but not a contemporaneous ex-date value. LAKSHVILAS instead lacks an evidenced point-in-time rights-entitlement value and complete coincident cash treatment. No missing entitlement was set to zero or inferred from the predecessor price drop.

The six warm-up-only cases still open are ZEEL (redeemable preference-share value), TATAPOWER (rights value and conflicting filed ratio evidence), IL&FSTRANS and WHEELS (rights-entitlement market value), WELCORP (unlisted demerger share value), and MARICO (unlisted Kaya share value and complete cash treatment). LAKSHVILAS is a scored-priority event that also blocks seven warm-up observations. The exact event ID, primary source, source fact, missing evidence, and before/after affected counts for every case are in [`results/event_resolution/unresolved_after_research.csv`](../../results/event_resolution/unresolved_after_research.csv) and [`results/event_resolution/event_resolution_status.csv`](../../results/event_resolution/event_resolution_status.csv).

The evidence manifest, [`results/event_resolution/event_evidence_manifest.csv`](../../results/event_resolution/event_evidence_manifest.csv), records NSE source-action URLs, retrieved timestamps and verified local SHA-256 values for all 42 events; a supplemental primary source for each; and official ex-date bhavcopy URLs and hashes for the two listed-share valuations. Supplemental documents consulted online were not downloaded locally, so their local-file and hash fields are blank. Later archival issuer documents were used only to establish historical event facts, never later market valuations.

## Rebuild and validation

`src/brindco_momentum/data/stock_total_returns.py` regenerated 1,810,466 development daily-return rows and `research_panel_v2.parquet`; `src/brindco_momentum/signals/momentum_signal.py` regenerated 106,395 monthly features, 51,583 official formation rows, and 5,085 winner rows across 103 dates. The maximum value-bearing market date read was **2023-03-31**; the latest formation was **2023-02-28**. The accepted 149-event treatment artifact still hashes to `5ddea240585838652401277a3b8b3e417d21b2919c9e6a8906cb3ea328c858cf`, and its four strict bonus-debenture event days remain unavailable. The source NSE files used for all 42 targeted events were checked against their download manifest hashes. Existing delayed-recognition logic was not changed.

Focused tests: **6 passed**. Full repository suite: **111 passed**. The prior test that demanded byte identity with the old return file was revised to require the recorded before/after hash pair, since changing those returns is the authorized result of this stage. No shadow portfolio, volatility estimate, holdings, performance, benchmark, or holdout analysis was run.

**Gate:** Scored winner sets are still provisional because 119 scored observations remain economically unavailable; warm-up winner sets are likewise not yet defensible for a later shadow portfolio because 41 warm-up observations remain blocked. Further progress requires contemporaneous valuation evidence or an explicitly approved narrower methodology for those specific events. This stage stops here.
