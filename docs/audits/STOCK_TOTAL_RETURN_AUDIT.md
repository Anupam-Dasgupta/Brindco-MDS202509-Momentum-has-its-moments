# Development stock total-return correction

The old research panel remains on disk as an audit record, but its
`daily_total_return` column is revoked as a total-return source. The panel
builder attached only the 149 specially reviewed in-universe treatments. It
did not attach the much larger set of parsed ordinary dividends, bonuses, and
splits. The old acceptance tests checked those 149 events and the four strict
exceptions; they did not check an ordinary dividend against an actual equity
return.

`src/brindco_momentum/data/stock_total_returns.py` now writes:

- `data/processed/stock_total_returns.parquet`: one corrected daily return per
  accepted panel security/date, with the previous canonical session, raw
  prices, adjustment provenance, and explicit availability status.
- `data/processed/research_panel_v2.parquet`: a compact join of the accepted
  membership/identity/market/ADV/timing fields and the corrected return layer.
  It contains no stale v1 `daily_total_return` or v1 action flags.
- `results/stock_total_return_audit/`: event-level dispositions, grouped
  coverage, unresolved events, hand-checkable examples, summary, and accepted
  input hashes.

All value-bearing reads were predicate-filtered through **2023-03-31**. The
old panel, official membership, dated identity, corporate-action parser, and
149-row treatment artifacts were not modified. No raw files, new downloads,
momentum, portfolios, or holdout values were used.

## Event method

Every processed economic action has one of four dispositions:
`APPLIED_TO_RETURN`, `NO_DIRECT_ADJUSTMENT_REQUIRED`,
`RETURN_UNAVAILABLE_EXPLICIT`, or `NOT_SIGNAL_RELEVANT`. The processed
`event_id` is the stable source key. A dated symbol/identity match supplies the
permanent `security_id`. For 379 older records whose processed action uses a
later ticker, a unique accepted alias was used only when the same permanent
security has a panel row on the ex-date. Four possible-member records remain
unmapped and visible in the audit.

An unreviewed ordinary action is applied only when the accepted parser marks
it as a single, unambiguous EQ dividend, bonus, or split with valid numeric
terms. Dividends add gross declared cash per old share; ordinary bonuses use
`1 + ratio_a / ratio_b`; splits use `old_face_value / new_face_value`.
Accepted special treatments retain their existing cash, share, and
entitlement values. Accepted no-direct events add no wealth. Distinct cash
dividends on one date can be added; duplicate source descriptions are not
credited twice. Mixed actions whose units are not established leave the
strict return unavailable. No unavailable daily return is zero-filled or
repaired with delayed recognition.

## Reconciled coverage

| Measure | Old panel | Corrected layer |
|---|---:|---:|
| Security/date rows | 1,810,466 | 1,810,466 |
| Action-adjusted return rows | 58 | 7,306 |
| Unavailable daily returns | 2,223 | 2,356 |

The corrected daily return differs from v1 on **7,381** security/dates,
including **4,756** dates while the security was an official member. The
source economic-action file contains **12,658** records through the cutoff:

| Disposition | Events |
|---|---:|
| Applied to return | 7,311 |
| Accepted no-direct adjustment | 87 |
| Explicitly unavailable | 173 |
| Not signal-relevant, including duplicate source records | 5,087 |

Applied events comprise **6,993 dividends**, **175 ordinary bonuses**, **104
splits**, and **39 accepted rights entitlements**. Multiple distinct cash
payments explain why 7,311 applied events affect 7,306 security/dates. Of the
applied events, **4,813** occurred during official membership and **1,758**
before first membership; the remaining **740** occurred outside an active
membership interval. The earlier approximate count of 4,346 was restricted
to unreviewed events that matched a contemporaneous in-universe panel symbol
and date; it omitted pre-membership history and later-ticker aliases.

The **173** explicit unavailable events comprise **15** in membership,
**61** before first membership, **93** outside active membership, and **4**
with a possibly relevant but unconfirmed identity. These are not silently
treated as zero-return events. Their exact reasons and source records are in
`unresolved_events.csv`. The four bonus-debenture ex-date returns remain
unavailable, and the accepted global strict corporate-action gate remains
**FAIL**.

## Hand-checkable regression

For TCS on **2022-05-25**, the accepted action data declares a ₹22 dividend,
the preceding canonical close is ₹3,288.00, and the ex-date close is
₹3,167.65. V1 reported both price and “total” return as **−3.6603%**. The
corrected return is `(3167.65 + 22) / 3288 - 1 = −2.9912%`. The ordinary
bonus, split, accepted combined action, no-direct buyback, and unresolved
strict-action examples are recorded in `spot_checks.csv` with their source
fields and calculated returns.

## Tests and use boundary

Focused tests: **10 passed**. Full repository suite: **79 passed**. Tests cover
ordinary formulas, canonical-session anchors, missing returns, duplicate
credits, mixed-action blocking, accepted no-direct treatment, TCS, v2 joins,
pre-membership coverage, cutoff, and the four strict exceptions. The build
also checks that the six accepted input hashes are unchanged before/after.

The corrected layer is suitable as an input to a later momentum stage **only
when that stage requires complete, available returns for every required
session/month and excludes explicit unresolved cases**. It is not a claim that
every security-month has an economic return. Four possible-member actions
could not be linked to an observed ex-date security; parser-marked uncertain
ordinary actions and unaccepted complex actions remain in the unresolved
audit. No daily shadow-risk issue has been solved here.
The processed ordinary-action file does not preserve a reliable publication
timestamp for every record, so this correction establishes ex-post economic
returns, not proof of exact ex-date information availability for every action.
No later market price was used to value an earlier event.

SHA-256: old panel `c35dfbfa2a500143e4ed617dfac35d9c974fd08afe4bc502d8f008a03ea76473`;
corrected returns `ba05c8c4964c9cf3845dac99f49f6864b63f79d87beaa76549126d6b0990bac8`;
panel-v2 `367e2d0805481620124c75d7a70da31844ee86684b7263b3a0bea2fa95d68e18`.
