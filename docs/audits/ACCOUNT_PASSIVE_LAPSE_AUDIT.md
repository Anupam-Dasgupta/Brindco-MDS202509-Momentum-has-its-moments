# Development account: DHANI passive-lapse scenario

This is a **conditional executable-account scenario**, not a completed economic-NAV backtest. It applies the project's no-subscription policy to the actually held DHANI/Indiabulls Ventures right (`CA_2dcc6f730654721a5203`) and assumes the accounts neither subscribe nor renounce it. No entitlement sale, sale price, cash receipt, new share allotment, or tax lot is invented. The original stopped run and its audit remain under `results/accounts_development/` and `ACCOUNT_DEVELOPMENT_AUDIT.md`; this scenario writes only under `results/accounts_development/passive_lapse/`.

The [February 1, 2018 offer document](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2018/1517830321746.pdf) specifies three new shares per sixteen old shares, a ₹240 subscription price, disregard of fractional entitlements, and the March 7, 2018 issue close. The [company's post-issue announcement](https://www.dhani.com/services/wp-content/uploads/2020/08/indiabulls-ventures-bs-eng2_1564749288.pdf) confirms the actual close on March 7. The account records 216 whole-share rights for MOM's 1,154 old shares and 120 for VM's 642 old shares. These are **rights**, not issued portfolio shares. Their fractional remainders (0.375 each) are not credited. The accounts take no action; both claims lapse at issue close with zero realised proceeds.

From the February 9 ex-date through March 6, the right is separately recorded as **open and unpriced**. The daily `nav` excludes its unknown value, and `nav_status=PASSIVE_LAPSE_UNPRICED_RIGHT_EXCLUDED` makes the limitation visible. From March 7 onward, `nav_status=PASSIVE_LAPSE_SCENARIO` identifies the continuing no-action path. The accepted theoretical ex-date research value is not account cash or an executable sale price. At that reference only, the amounts would be about ₹282 for MOM and ₹157 for VM; this is scale information, not an upper bound or a mark used by the ledger. This treatment is consistent with [plan.md](../../plan.md) §5.4's prohibition on invented rights proceeds, but any investment conclusion remains conditional on the passive-lapse assumption and later data-quality blockers.

| Check | MOM | VM |
|---|---:|---:|
| Original stopped run, last NAV date | 2018-02-08 | 2018-02-08 |
| Scenario last NAV date | 2020-08-13 | 2020-08-13 |
| Scenario daily NAV rows | 1,327 | 1,327 |
| Pre-DHANI rows identical to stopped run | Yes, all 709 | Yes, all 709 |
| Unpriced-right NAV rows | 16 | 16 |
| Rights cash credited / new shares issued | ₹0 / 0 | ₹0 / 0 |
| Maximum NAV reconciliation error | 0 | 0 |
| Maximum value-bearing input date read | 2023-03-31 | 2023-03-31 |

Both runs stop before 2020-08-14 NAV at a **different actually held rights issue**, UNOMINDA `CA_277f0c578cd42848896a` (`NSE_48390A9F12CC`). MOM held 418 old shares, marked at ₹121,533.50 or 0.8637% of its preceding NAV; VM held 202, marked at ₹58,731.50 or 0.5280%. The accepted stock-return event is classified as a rights issue, but this task did not establish its executable-account treatment. No 2020-08-14 or later NAV or full-period account performance is claimed. The DHANI convention has deliberately **not** been applied automatically to other rights events.

The ledger verifies frozen input hashes before and after the run. Targeted direct-event tests verify whole-share entitlement, no cash or share credit, unresolved claim value, verified terms, and lapse timing. Artifact tests verify the 16 flagged NAV rows, claim state, original stopped run, and reconciliation. Full repository suite: **152 passed**.
