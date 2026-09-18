# Holdout input readiness — FAIL

Frozen development checkpoint: commit `2380275`, tag `development-evaluation-frozen`.
Required holdout trading sessions: **742**, from **2023-04-03** through
**2026-03-30**. Market, canonical calendar, and NIFTY 500 TRI date sets agree.
The raw corporate-action source has 7,207 holdout rows; these are raw records,
not accepted economic-event treatments. `coverage_summary.csv` records the
metadata-only date and row-count checks.

## Membership evidence gathered

The local NSE Indices press archive was screened for relevant equity-index
notices published from 2023-04-01 through 2026-03-30. **93 original official
PDFs** were cached under `data/evidence/membership_holdout/notices_pdf/` with
source URLs and SHA-256 hashes in `notice_pdf_manifest.csv`. The existing
membership notice parser extracted **336 tabular NIFTY 500 addition/deletion
rows**; `notice_parse_status.csv` and `notice_parsed_events.csv` preserve its
output. Running the acquisition/parser twice produced identical three CSV
hashes. These are candidate evidence rows, not an accepted event ledger.

The frozen builder cannot yet turn the notices into a correct roster:

1. Official demerger notices insert zero-price, unlisted index constituents
   such as `DUMMYSANOF` on 2024-06-13 and `DUMMYITC` on 2025-01-06. The frozen
   ISIN-based resolver returns `NO_OBSERVED_SYMBOL` for these dummies, and the
   tabular parser emits no row for their prose/index-list inclusions. The
   notices also describe later listing and removal. Treating the dummy as an
   ordinary listed share would invent an investable observation; omitting it
   would change the official point-in-time roster. A zero-price JIOFIN
   spin-off inclusion in 2023 is likewise non-tabular. The identified cases
   are listed in `unresolved_events.csv`. Examples:
   [Sanofi inclusion](https://niftyindices.com/Press_Release/ind_prs07062024_2.pdf),
   [ITC Hotels inclusion](https://niftyindices.com/Press_Release/ind_prs30122024.pdf).
2. Official notices revoke previously announced, not-yet-effective changes:
   IREDA/VGUARD on 2024-03-28 and IDEA/PRSMJOHNSN on 2024-09-30. The frozen
   override mechanism adds verified rows but has no cancellation operation.
   Applying both announcements would create a false roster.
   [IREDA revocation](https://niftyindices.com/Press_Release/ind_prs19032024.pdf),
   [IDEA revocation](https://niftyindices.com/Press_Release/ind_prs25092024.pdf).
3. Rebuilding the dated identity with the existing hash-of-entire-ISIN-group
   formula through 2026-03-30 would change the permanent IDs on **208**
   development `ISIN × symbol` rows spanning **167** existing security IDs.
   There are **zero** extended groups that merge two distinct development IDs,
   so a stable-ID carry-forward is feasible, but the unchanged builder cannot
   be run into the frozen development paths.

No holdout membership intervals or identity extension were accepted. The
candidate notice filter is a discovery aid; complete notice-chain validation
and source/event reconciliation remain necessary after these representation
issues are resolved. The existing accepted development intervals and identity
were not rewritten.

## Input gate

| Input | Holdout status |
| --- | --- |
| Market, trading calendar, TRI | Date coverage passes on the same 742 sessions; no price, index-level, or return values were opened. |
| Official membership | **FAIL:** 93 source PDFs cached and 336 candidate table rows parsed, but no accepted holdout intervals because of the cases above. |
| Dated identity / eligible series | **FAIL:** no accepted holdout artifact. The stable-ID issue is quantified above. |
| Corporate-action treatments / event resolution | **FAIL:** 7,207 raw rows, zero accepted holdout treatments. Universe-dependent exception triage was not attempted before membership acceptance. |
| Settlement calendar | **FAIL:** zero accepted holdout rows; not extended after the upstream stop. |
| Research panel / lagged ADV | **FAIL:** zero accepted holdout rows; not built from an unresolved universe. |
| Final freeze manifest | **NOT CREATED:** the prerequisites do not pass. |

The first blocking stage is official membership. The later missing inputs in
the table are downstream work, not independent evidence that the current
holdout is ready. The number of sessions common to **all accepted required
inputs is zero**; the 742-session match applies only to the three covered
source date sets. A narrow, explicit representation for official nontradable
dummy constituents and pre-effective notice revocations is needed before the
same membership reconstruction can be accepted. The identity extension must
preserve frozen development security IDs. None of these rules was silently
introduced in this audit.

## Regression and isolation

- Full test suite: **193 passed**.
- SHA-256 comparison: **286** frozen development files checked, **0 changed**,
  covering membership/identity/treatments, panel, winners, VM exposures,
  account outputs, and evaluation outputs. The checked baseline paths and
  hashes are in `development_hashes_before.csv`.
- Git-tracked frozen code and development results were not modified.
- No holdout signal, winner set, portfolio, account, NAV, return, or
  performance output was produced or examined.

**Decision: FAIL.** The holdout performance gate remains closed. No final
`research/freeze_manifest.json` or holdout freeze manifest was created.
