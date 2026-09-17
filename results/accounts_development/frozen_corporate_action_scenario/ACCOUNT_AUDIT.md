# Development account continuation audit

The `FROZEN_CORPORATE_ACTION_FRAMEWORK` scenario reaches 2023-03-31 for MOM and VM. It preserves the frozen winner sets, research panel, and earlier account outputs. This is a **date-complete but provisional executable-account scenario**: material frozen bonus entitlements remain unavailable for delivery, and many dividend receivables have no verified payment date.

## UNOMINDA 2018 lifecycle repair

The accepted combined event `CA_715af64eb2a5a45d9eb5` is a 2:1 bonus plus a ₹1.60 final dividend per pre-bonus share. The [company's July 13, 2018 board outcome](https://www.unominda.com/uploads/investor/invites-and-announcements/outcome-of-bm_13072018.pdf) establishes allotment to July 12 record-date holders. The [FY2018–19 annual report](https://www.unominda.com/uploads/investor/annual-reports/ar-2018-19.pdf), shareholder transaction tables on PDF pages 82–86, records bonus additions dated July 20 and sales by shareholders dated July 27. Its bonus resolution also excludes the new shares from the FY2017–18 final dividend.

The account recognises the bonus entitlement and pre-bonus dividend on the July 11 ex-date; starts the new zero-basis lot's tax clock on July 13; and makes the bonus shares available to sell from July 23, the first NSE session after the documented July 20 shareholder posting. **July 23 is a conservative modelling convention, not direct proof of this simulated account's demat credit.** No dividend payment date is inferred; the dividend remains an unspendable receivable. The first modelled post-event UNOMINDA sale is August 7 for MOM and August 2 for VM.

| Account | Pre-event shares | Bonus shares | Dividend receivable |
| --- | ---: | ---: | ---: |
| MOM | 209 | 418 | ₹334.40 |
| VM | 101 | 202 | ₹161.60 |

The local evidence files are `evidence/UNOMINDA_2018_07_13_allotment.pdf` (SHA-256 `90ADB2842D5AFC8294AE35682EEA0E8D48D639E19A780DE296FB661C71CAF6A8`) and `evidence/UNOMINDA_FY2018_19_annual_report.pdf` (SHA-256 `1A8B0FC99713DE741F6E6B5C8B839095A509462AA2F6F6D4C4AB3944C4AAF46B`).

## Frozen operational exit rule

For an unsupported event with a verified public notice row in `data/processed/account_operational_event_notices.csv`, the account blocks purchases from the next NSE session after the announcement. It tries to sell any holding on each subsequent session before the effective date under the existing 1%-of-lagged-ADV participation cap, impact, fees, delivery, tax-lot, and T+2 settlement rules. At the effective date, an unsold economic position stops that account and records its residual. This changes orders only; selections and target signal values remain frozen. The purchase block persists after the event to prevent re-entry into an unsupported security.

The notice table has **zero verified rows** in this run. No actual mandatory-exit order was triggered. Synthetic tests cover successful exit and a liquidity-limited residual stop. The processed corporate-action files contain effective dates but no reliable public-announcement dates; the engine does not infer them. Although neither account held an unsupported event on its effective date in this replay, some securities were held earlier and could have had public notices before their ordinary exit. Therefore the announcement-driven rule has not been retrospectively verified for every historical event, and this run must not be described as a fully validated implementation of that policy.

## Results and limitations

| Measure | MOM | VM |
| --- | ---: | ---: |
| Valid daily NAV rows | 1,982 | 1,982 |
| Last NAV date | 2023-03-31 | 2023-03-31 |
| Effective-date unsupported-event holdings | 0 | 0 |
| Maximum NAV reconciliation error | 0 | 0 |
| Remaining unavailable bonus entitlements | 26 | 26 |
| Remaining unavailable bonus units | 16,803.5222 | 9,563.2778 |
| Their March 31 marked value | ₹2,636,211.70 | ₹1,705,307.56 |
| Share of reported NAV | 13.37% | 11.50% |
| Unspendable dividend receivables | ₹977,983.52 | ₹592,193.98 |
| Share of reported NAV | 4.96% | 3.99% |

The remaining bonus claims include fractional economic units and cannot be delivered by the frozen engine. They are marked in NAV but cannot be sold. Dividend receivables without payment dates are also included in NAV but cannot finance purchases. These are material execution limitations under `plan.md` §5.4 and §9, not additional event treatments. The UNOMINDA 2018 bonus entitlement itself is fully converted; none of its units remains in the unavailable-bonus list.

The maximum market-value date read is 2023-03-31 for both accounts. Seventy-nine previously accepted account files matched their saved SHA-256 hashes. The final economic NAV paths match the UNOMINDA diagnostic replay exactly; the new empty notice input changes only the input manifest identifier. No holdout values, performance metrics, or later strategy stages were inspected.

Test command: `.venv/Scripts/python.exe -m pytest -q` — **173 passed**.
