# Development accounts: passive-lapse rights scenario

This is the user-authorized `PASSIVE_LAPSE_RIGHTS_SCENARIO`, not a completed development-period account backtest. The original stopped outputs in `results/accounts_development/` and the earlier DHANI-only scenario in `results/accounts_development/passive_lapse/` remain separate. The new outputs are in `results/accounts_development/passive_lapse_rights_scenario/`. Only development value data through 2023-03-31 were read; no holdout values or performance were inspected.

## Account policy

For an actually held, ordinary rights issue with verified terms and a separately confirmed issue close, the account records the whole-share rights entitlement separately at the equity ex-date, with the legal record date retained. It neither subscribes nor contributes capital, manufactures equity shares, sells an unexecuted entitlement, or credits theoretical rights value. A live right is unpriced and excluded from NAV; the daily NAV row says `PASSIVE_LAPSE_UNPRICED_RIGHT_EXCLUDED`. If the holder took no action, the claim becomes `LAPSED_UNEXERCISED` on the confirmed close date, with no cash, shares, or tax event. This is a conditional account scenario consistent with `../../plan.md` §5.4's prohibition on invented rights proceeds, not a statement that an actual investor would let the right lapse.

The account compares the accepted ratio and any accepted subscription price against the official evidence. It stops on a conflict, on a nonordinary rights structure, or if actual closing evidence is still missing. Final-offer *scheduled* closing dates are recorded in the batch table but are not treated as post-close confirmation. The batch table is included in the new input manifest, so any future amendment changes the manifest hash. Theoretical entitlement values in upstream research remain diagnostics only.

## Batch coverage and evidence

[`rights_candidate_scan.csv`](../../results/accounts_development/rights_candidate_scan.csv) records the ratio, subscription price, record date, issue-close date, fractional treatment, primary URLs, and evidence status for **26** rights events that occurred after their security first entered a frozen MOM/VM winner set and by 2023-03-31. Eight other rights-classified events on eventual winner securities occurred *before* their first possible selection, so they could not be held in these accounts. The scan is complete by this potential-holdings definition. The 26 events include 24 ordinary structures and two complex structures (`SINTEX` combined dividend/rights; `TATASTEEL` two separately priced rights legs) that cannot pass the one-leg rule if actually held.

All 26 have official issue terms and scheduled closing dates in primary documents. Fifteen have independent post-close confirmation; 11 currently have only the final offer's scheduled close and are marked `PRIMARY_TERMS_SCHEDULED_CLOSE_ONLY`. They will block the account if later actually held until the final close is separately confirmed. This distinction caught a real difference: SPARC's [issuer annual report](https://sparc.life/wp-content/uploads/2023/09/Annual-Report-2016-17.pdf) states that its close was extended from 2016-04-11 to **2016-04-13**; the batch table records the latter. The official Capri/CGCL offer says ₹475 while the accepted treatment table says ₹474; the account will also stop rather than silently choose a price. These limitations do not affect the two rights actually held before the current stop, both of which have confirmed closes. The [SEBI 2020 rights circular](https://www.sebi.gov.in/sebi_data/attachdocs/jan-2020/1579691409907.pdf) provides the fractional-entitlement round-down and lapse rules for offers in its scope; earlier offers use their own documented terms.

## Actually held rights

| Event | Verified primary terms | MOM entitlement | VM entitlement | Live, unpriced NAV dates | Lapse |
|---|---|---:|---:|---|---|
| DHANI / Indiabulls Ventures, `CA_2dcc6f730654721a5203` | 3 rights per 16 shares; ₹240 per right; record 2018-02-12; ex 2018-02-09; fractional rights ignored; actual close 2018-03-07 | 1,154 old shares → 216 whole rights | 642 → 120 | 2018-02-09 through 2018-03-06, 16 sessions | 2018-03-07 |
| UNOMINDA / Minda Industries, `CA_277f0c578cd42848896a` | 1 right per 27 shares; ₹250 per right; record 2020-08-17; ex 2020-08-14; fractions rounded down; actual close 2020-09-08 | 418 old shares → 15 whole rights | 202 → 7 | 2020-08-14 through 2020-09-07, 17 sessions | 2020-09-08 |

DHANI terms and fractional treatment are in its [official letter of offer](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2018/1517830321746.pdf); its [issuer post-issue announcement](https://www.dhani.com/services/wp-content/uploads/2020/08/indiabulls-ventures-bs-eng2_1564749288.pdf) confirms closure. UNOMINDA terms are in its [revised NSE filing](https://nsearchives.nseindia.com/corporate/MINDAIND_11082020190205_revised_outcome.pdf); its [post-issue advertisement, page 4](https://nsearchives.nseindia.com/corporate/SEQUENT_19092020165528_Stock_Exchange_intimation_Offer_PostOfferAdvertisement.pdf) confirms the September 8 close. The UNOMINDA fractional rule follows the SEBI circular cited above. Neither account has a rights-related cash event, subscribed share, or recognised entitlement value.

## Run, reconciliation, and stop

| Check | MOM | VM |
|---|---:|---:|
| Last valid daily NAV | 2021-05-10 | 2021-05-10 |
| Valid daily NAV rows | 1,510 | 1,510 |
| Live, unpriced right NAV rows | 33 | 33 |
| Maximum NAV reconciliation difference | 0 | 0 |
| Original strict-run prefix identical (date, NAV, return) | 709 / 709 rows | 709 / 709 rows |
| Earlier DHANI-scenario prefix identical (date, NAV, return) | 1,327 / 1,327 rows | 1,327 / 1,327 rows |
| Latest value-bearing market date read | 2023-03-31 | 2023-03-31 |

**Neither account reaches 2023-03-31.** Both stop before the 2021-05-11 NAV on a separate ALKYLAMINE split (`CA_4f478b35c127d00f600f`, multiplier 2.5). The executable account enforces whole shares per tax lot and has no evidenced treatment for fractional split units. MOM has 46 aggregate pre-split shares, but some individual lots would become fractional; VM has 19 aggregate shares, which would become 47.5. The split check is atomic: failure leaves all lots in their pre-event state. This is a new non-rights methodology blocker, so the account did not extend the rights policy or continue past it.

The full repository suite passes **160 tests**. Rights tests cover both held quantities, no invented value/cash/shares, verified terms, fractional handling, close-date lapse, missing/complex/conflicting evidence stops, scenario NAV flags, batch coverage, and unchanged earlier account prefixes. No 2021-05-11 or later account NAV, full-period performance, or holdout result is claimed.
