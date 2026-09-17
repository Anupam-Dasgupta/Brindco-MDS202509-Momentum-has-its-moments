# Paper C project plan: Does risk-managed momentum survive the mandate?

Status: implementation specification, written 14 September 2026. No strategy results have been calculated and no complete historical dataset has been verified. This document specifies what to build; it is not evidence that the strategy works.

Chosen paper: Pedro Barroso and Pedro Santa-Clara, *Momentum Has Its Moments*, Journal of Financial Economics 116 (2015), 111–120.

Research question: **Does a capped volatility overlay improve a long-only Indian equity momentum portfolio after transaction costs and the assignment's capital-gains taxes, beyond what a fixed allocation to the same portfolio and cash achieves?**

The intended output is one reproducible research project and a memo of no more than five pages. The intended preparation schedule is seven focused working days, conditional on passing the data feasibility gate. The assignment itself permits fourteen calendar days from receipt; record the actual receipt date and deadline in the README. Do not confuse the seven-day target with a verified deadline or a promise that historical reconstruction can be completed in that time.

Read resources.md alongside this document. It supplies the focused learning and interview-preparation programme. This plan is the authority for implementation choices; if a learning resource uses a different construction, do not silently replace this plan with it.

## 1. Authority, scope, and definition of completion

### 1.1 Order of authority

1. The user's instructions and the actual assignment PDF.
2. Explicit clarifications subsequently received from the desk, recorded with dates.
3. The primary paper and its author-posted errata, for the original construction.
4. The declared adaptations and implementation conventions in this plan.

Source files already in this project root:

- Brindco_Case-Assignment_One-Paper-One-Strategy.pdf
- JD.pdf
- 1786574202344_9cmVTRd4ON_Placement_Resume_Brindco.pdf

The assignment controls the research requirements. The resume affects the learning priorities in resources.md, not the strategy design or evaluation.

### 1.2 Hard requirements

| Requirement | Implementation |
|---|---|
| One paper | Paper C only. Other studies may inform criticism and interpretation, not supply additional trading signals. |
| Historical universe | NIFTY 500 membership as of each rebalance date; also search the older name CNX 500 in archives. |
| Instruments | Fully paid NSE cash equities and cash. No derivatives, short positions, margin funding, or leverage. |
| Build window | 1 April 2015–31 March 2023. |
| Holdout | 1 April 2023–31 March 2026. Evaluate only after freezing the complete protocol. |
| Cadence | Monthly signal and exposure decisions. A short execution window completes those orders; it does not introduce daily signal changes. |
| Costs | The assignment's stack, with an explicit resolution of its spread/impact ambiguity and participation-dependent impact. |
| Taxes | Assignment-standard 20% STCG and 12.5% LTCG with a declared annual exemption and lot accounting. |
| Data | Free public inputs only; sources, vintages, checks, and limitations recorded. |
| Reproducibility | A clean checkout plus documented data acquisition or permitted cached data produces identical results. |
| Submission | Code, README, source manifest, five-page-or-shorter memo, and supporting outputs in an archive or private repository. |
| AI use | Disclose assistance in the README. The candidate must explain every submitted component. |

The deliverable is an individual submission. Independently implement the research code. Public data may be used with attribution and appropriate permissions; the existence of a public replication package does not justify copying strategy code into an individual submission.

### 1.3 Completion means

- Historical data coverage and unresolved issues are measured, not assumed.
- One primary strategy and its predeclared controls run through the required windows.
- Every order reconciles to shares, cash, receivables, fees, and tax lots.
- The cost/turnover hurdle table appears before performance ratios.
- The complete frozen holdout evaluation has been run once, with no result-driven retuning.
- Conclusions distinguish statistical evidence, economic value, and implementation feasibility.
- The memo is at most five pages, including charts; important qualifications appear inside those pages.
- A clean-room reproduction succeeds without private paths or untracked inputs.
- The candidate can derive the exposure rule, hand-work a rebalance and a tax example, and explain the main failure cases.

An honest negative or inconclusive finding can satisfy the assignment. An incomplete historical universe cannot support a claim of a clean full-mandate backtest.

## 2. Hypothesis and translation from the paper

### 2.1 Mechanism in plain language

Momentum strategy risk changes through time. If past realised risk helps forecast subsequent risk, reducing exposure when estimated risk is high can change the portfolio's distribution of returns. Whether that improves net investment outcomes is an empirical question; forecastable volatility alone does not prove forecastable returns or improved utility.

The original study examines a winners-minus-losers construction. This project studies the long leg with a cash allocation and an exposure ceiling. Its results therefore test a constrained adaptation, not a literal replication or a confirmation of the original crash-protection claim.

Primary references: [paper landing page](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429), [author research page](https://sites.google.com/site/pedromsbarroso/).

### 2.2 Author errata: mandatory

The [author-posted errata](https://drive.google.com/file/d/1G9zsx25zs7ijIdjf8VDmmgz7vPIcQSTW/view) corrects Equation 10: leverage multiplies the portfolio weights in the turnover calculation; the printed division is wrong. The errata states that the related reported results already used the correct expression.

The corrected leg-level expression is:

\[
x_t=\frac12\sum_i |w_{i,t}L_t-\widetilde w_{i,t-1}L_{t-1}|.
\]

For this project, compute costs from the actual executed share ledger. Do not estimate overlay turnover by multiplying unscaled turnover by average exposure. Previous holdings must drift with returns, and changes in exposure cause trades even when the selected stocks do not change.

### 2.3 Declare these adaptations in the memo

| Original element | Project choice | Reason and consequence |
|---|---|---|
| Long–short momentum | Long winners plus cash | Required mandate; removes the short leg and changes beta, crash mechanisms, and expected returns. |
| Exposure may exceed one | Exposure capped at one | No leverage; the target becomes an exposure rule, not a guarantee of attaining target volatility. |
| Risk of WML | Risk of an unscaled, historically constructed long-only reference portfolio | Measures the risk of the adapted opportunity; does not assume WML risk equals long-book risk. |
| Original stock universe | Historical NIFTY 500 | Assignment requirement. |
| Value-weighted source portfolios | Equal-weighted selected names | Transparent concentration, no dependence on uncertain historical free-float weights; changes size/liquidity exposure. |
| Original execution and costs | Delayed, capacity-limited cash execution and prescribed Indian costs | Tests implementation rather than merely multiplying a return series. |
| Original tax treatment | Explicit assignment-standard tax lots | Required; reduced turnover and tax deferral must be distinguished from signal quality. |

Keep conventional momentum inside C. Do not add A's intermediate-horizon signal, B's trend gate, low-volatility stock selection, stop-losses, GARCH, ML, or discretionary regime switches to the core strategy.

### 2.4 Questions the experiment must answer

1. Is subsequent realised variance associated with the proposed risk forecast?
2. Does the overlay improve outcomes relative to unscaled long-only momentum?
3. Does it improve outcomes relative to fixed equity–cash controls?
4. How much of the difference is equity exposure, timing, turnover, tax, or execution shortfall?
5. Does the conclusion survive the holdout and predeclared cost/capacity sensitivities?
6. What prevents an investment recommendation even if the equity curve looks attractive?

## 3. Frozen default specification

These values are deliberate design choices, not optimised results. Changes before the holdout require a dated rationale and an experiment-log entry. Change nothing in response to holdout performance.

| Item | Default |
|---|---|
| Currency and base account | INR; initial book value ₹1,00,00,000 (one crore) |
| Price acquisition target | 1 January 2013–31 March 2026; extend earlier only if needed for verified warm-up |
| Shadow portfolio inception | First executable August 2014 rebalance, subject to adequate signal history |
| First scored live-like account | First NSE trading session on/after 1 April 2015 |
| Momentum signal | Cumulative total return from holding-month t−12 through t−2, inclusive |
| Formation time | After the last NSE trading session of the preceding month |
| Eligible set | Historical NIFTY 500 with sufficient trailing history and the contemporaneous trading checks below |
| Selection | Highest-scoring 10% of eligible names; count = ceiling(0.10 × eligible count) |
| Weights within selected set | Equal weight at the target rebalance |
| Minimum usable selection | At least 20 names; otherwise no new target book, retain cash after orderly exits |
| Risk input | Gross, unscaled long-only shadow portfolio's historical daily returns |
| Risk estimator | Annualised root mean square of the last 126 valid daily returns |
| Volatility target | 12% annualised |
| Exposure | min(1, 0.12 / estimated annualised volatility) |
| Cash return | 0% in the primary model, including settlement receivables |
| Execution reference | Next eligible session's raw opening price, plus separately modelled impact |
| Order completion | At most five NSE trading sessions following each monthly formation |
| Capacity cap | One-side traded notional per security per day ≤ 1% of lagged 20-session ADV |
| ADV | Mean rupee traded value over the preceding 20 NSE sessions |
| Impact reference | p0 = 0.001 of ADV (0.1%); primary minimum I0 = 10 bps per side |
| Impact function | I(p) = I0 × max(1, sqrt(p / p0)) bps per side |
| Settlement convention | Conservative T+2 settlement-business-day availability throughout the sample |
| Cash use | Buys use only settled, unencumbered cash, including fees; no reuse of unsettled sale proceeds |
| Share quantities | Whole shares; no fractional shares in implementable accounts |
| Lot matching | FIFO |
| Tax year | 1 April–31 March |
| Tax rates | 20% short term; 12.5% long term |
| LTCG exemption | ₹1,25,000 per account per financial year, assumed unused elsewhere |
| Exactly 12 calendar months | Short term; long term only after the anniversary |
| Resampling seed | 20260914 |
| Primary inference block | Circular moving-block bootstrap, six monthly observations per block |
| Bootstrap draws | 5,000 paired draws |
| Confidence interval | Percentile 95%, with limitations explicitly stated |

The impact curve is an intentionally transparent planning assumption. Its parameters are not estimates validated by exchange data. Applying the curve to all stocks avoids needing historical market-cap tiers solely to assign costs. Low ADV naturally raises participation for a given order. The five-day execution window is an operational implementation of monthly targets, not five daily re-optimisations.

Uniform T+2 availability is deliberately conservative after the transition to T+1. Use a separately verified settlement calendar, including settlement holidays. If actual security-specific historical settlement schedules are available, add them only as a declared sensitivity or future improvement; do not claim the primary simplification reproduces historical settlement rules exactly.

## 4. Data feasibility gate: do this before substantial strategy coding

### 4.1 What has and has not been established

Source pages, several early official membership-change PDFs, and a public reconstruction have been located. A complete downloadable and validated dataset has **not** been established. Attempts to sample ZIPs from the planning environment were blocked by local network restrictions; that is not evidence that the exchange files are unavailable.

The correct next step is a small acquisition and verification exercise, not a promise of full coverage.

### 4.2 Day-one evidence checklist

Produce a data_feasibility.md report containing:

1. Successfully downloaded and parsed exchange samples from the warm-up, 2015, and 2022/early 2023.
2. A demonstrated route to the July 2024 schema transition using document/schema inspection, with holdout return values kept sealed.
3. An independently evidenced membership snapshot near the first shadow formation and the April 2015 first scored formation.
4. A forward application of official changes through several early rebalance dates, reconciled to independent later snapshots.
5. A concrete symbol/identity mapping example, one split or bonus, one dividend, and one merger or vanished security.
6. A benchmark TRI acquisition route and a verified trading/settlement calendar route.
7. A list of missing source periods and expected manual effort.

Pass condition: there is a credible, sampled route to every required input and the early membership history can be evidenced. This is permission to proceed with construction, not a claim that the full data audit has passed.

Fail condition: no defensible early membership seed, pervasive unidentified securities, no usable price archive for early years, or an estimated reconstruction effort that consumes the available project time.

On failure, record the issue and prepare a precise request for desk clarification, including the proposed deviation. Do not send messages externally without the user's authorisation. Work on synthetic ledger tests and paper understanding can continue. Do not silently use today's constituents, start in 2017, replace the universe with an ETF, or discard delisted names.

### 4.3 Concrete source routes

| Input | Source route | Status and use |
|---|---|---|
| Index changes | [Nifty media archive](https://www.niftyindices.com/media) and [press releases](https://www.niftyindices.com/press-release) | Primary evidence; search CNX 500 and NIFTY 500. |
| Early review | [20 February 2015](https://www.niftyindices.com/Press_Release/ind_prs20022015.pdf) | Verified document includes CNX 500 changes. |
| Early special changes | [18 March 2015](https://www.niftyindices.com/Press_Release/ind_prs18032015_2.pdf), [23 January 2015](https://www.niftyindices.com/Press_Release/ind_prs23012015.pdf) | Effective dates must be read separately from announcement dates. |
| Later example | [7 December 2015](https://www.niftyindices.com/docs/default-source/press-release-upload/ind_prs07122015.pdf) | Example of event-specific replacements. |
| Candidate membership dataset | [NSE historical membership reconstruction](https://github.com/aditya-jha/nse-historical-membership) | Audit aid; pin a commit and inspect provenance, inferred intervals, early drift, and identity changes. |
| Prices/volume | [NSE All Reports](https://www.nseindia.com/all-reports) | Separate legacy and UDiFF parsers; inspect actual downloaded headers. |
| Corporate actions | [NSE corporate-action filings](https://www.nseindia.com/companies-listing/corporate-filings-actions) | Resolve dividends, ratios, effective dates, and complex-event documents. |
| Symbol/name changes | [NSE securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading) | Mapping aid; a rename is not the same event as a merger. |
| Benchmark | [Nifty historical data](https://www.niftyindices.com/reports/historical-data) | NIFTY 500 Total Returns Index, not the price index. |

Candidate archive URL patterns, which the builder must test rather than assume complete:

~~~text
Legacy:
https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip

UDiFF:
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

Alternative full-delivery report:
https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
~~~

The exchange reports page documents the old bhavcopy discontinuation from 8 July 2024. Patterns are also visible in [jugaad-data's archive source](https://github.com/jugaad-py/jugaad-data/blob/master/jugaad_data/nse/archives.py); inspect it as endpoint documentation, not as proof that every historical object exists.

The candidate membership repository reports pre-2018 inconsistencies and normalises some historical symbols to terminal names. Its EOD component describes coverage from 2020 and does not ship a complete ready-made early price dataset. Never join its canonical ticker directly to all historical exchange prices without an audited identity map.

### 4.4 Acquisition and provenance rules

- Download each raw object once; preserve bytes unchanged.
- Manifest fields: source_id, URL, retrieval UTC timestamp, publication timestamp if known, applicable dates, MIME type, byte count, SHA-256, parser version, licence/redistribution notes, and retrieval status.
- Detect HTML error pages masquerading as CSV/ZIP/PDF. Validate signature, archive integrity, headers, and row counts.
- Distinguish exchange holiday, unavailable file, blocked request, corrupt archive, and parser failure.
- Use bounded retries with backoff and normal source access. Cache successfully acquired objects.
- Store any manual repair as a versioned override with evidence and before/after values; never edit raw files.
- Prefer official evidence for contradictions. An aggregator is a cross-check or documented fallback, not unquestioned authority.
- Respect redistribution conditions. If raw data cannot be shipped, include scripts, checksums, and precise acquisition instructions; state that future upstream revisions can prevent byte-identical fresh downloads.
- Do not claim results are reproducible until a second clean run has succeeded using the declared inputs.

## 5. Data model and cleaning contract

Use permanent internal security IDs. Preserve original exchange symbol, series, and ISIN as dated attributes. A name change, a share-class change, a merger, and an economic successor are different events.

### 5.1 Required normalised tables

| Table | Essential columns / invariant |
|---|---|
| security_master | security_id, legal issuer/share class, ISIN intervals, listing/delisting dates, source; no identity inferred from ticker alone |
| symbol_history | security_id, symbol, series, valid_from, valid_to, evidence |
| membership_intervals | security_id, index_id, effective_from, effective_to, announced_at, evidence/confidence; half-open intervals |
| trading_calendar | date, session_type, previous_session, next_session, source |
| settlement_calendar | date, settlement_business_day, source |
| prices_daily | security_id, date, series, raw_open/high/low/close, volume_shares, traded_value_INR, status, source |
| corporate_actions | event_id, security_id, announced_at, ex_date, record_date, payment_date, event_type, amounts/ratios, successor_id, tax treatment, evidence |
| stock_total_returns | security_id, date, return, return_index, adjustment provenance, quality_status |
| benchmark_daily | date, NIFTY_500_TRI, source |
| quality_events | issue_id, security_id/date range, problem, resolution, evidence, affected strategy dates/weights |

Feature tables add asof timestamp, lookback boundaries, source-data maximum timestamp, and eligibility reason. Order and accounting schemas appear in Section 10.

### 5.2 Membership

- Begin from an evidenced historical seed; apply scheduled reviews and off-cycle events.
- Membership begins on the effective trading date, not the announcement date.
- A source phrase “effective date X, close of Y” must be translated into the corresponding first session of membership.
- Reconcile multiple snapshots throughout history. Matching today's snapshot does not validate the path.
- Do not assume every count different from 500 is wrong: investigate corporate-action and temporary membership exceptions against official evidence.
- Do not discard inferred/uncertain rows and call the remainder the required universe.
- Historical members that later disappear remain in the data.

### 5.3 Prices, volume, and return adjustments

- Parse quantities as shares and traded value as rupees. Explicitly convert any lakh-denominated fields by 100,000.
- Choose the actual eligible equity series for each security/date. Do not duplicate a company across EQ/BE or other series.
- Check uniqueness, positive tradable prices, nonnegative volume, and normal OHLC ordering; retain documented exchange exceptions separately.
- Reconcile random samples and all large discontinuities to corporate actions or a second source.
- A trading-day price missing for one stock is not a missing market session.
- Never backfill from a future price. Forward marking of an existing position is a labelled stale valuation, not permission to trade at the stale price.
- Never fill an unobserved return with zero merely to make a rolling window complete.

For a simple cash dividend D and split ratio s new shares per old share:

\[
1+r_{i,d}=(sP_{i,d}+D_{i,d})/P_{i,d-1}.
\]

Use a convention-consistent formula for combined events and document units per old/new share. This is a building block, not a formula for every merger, demerger, rights issue, or cancellation.

Features use the audited total-return series. The implementable account uses raw prices plus explicit share/cash events. Do not use adjusted prices for execution or credit a dividend again on top of an already dividend-adjusted portfolio return.

### 5.4 Corporate events in the implementable account

- Split/consolidation: change quantity and per-share basis; preserve aggregate basis, acquisition dates, and economic wealth apart from actual cash-in-lieu.
- Bonus shares: separate original and bonus lots; under the declared modern tax convention, bonus basis is zero and the bonus holding clock begins on allotment. The original lots keep their basis and acquisition dates. This differs from splitting basis across all shares.
- Cash dividend: create entitlement for eligible held shares, recognise a receivable on ex-date, and make it spendable on the evidenced payment date.
- If payment date is unverified, retain an unspendable receivable until resolved. Do not invent a payment date to improve reinvestment.
- Merger: apply the actual cash/share consideration and successor share identity. Carry basis/age only where the declared tax treatment is supported; do not replace the old ticker's history with the survivor's.
- Demerger: allocate quantities and basis using documented consideration and allocation. Temporary unlisted entitlements remain separately valued claims.
- Rights: primary policy does not subscribe with additional capital. Value and sell a separately tradable entitlement only with evidenced cash-market prices and execution; otherwise flag the unresolved entitlement. Do not invent proceeds or free money.
- Buyback/delisting/tender: require eligibility, consideration, acceptance assumptions, and dates; do not assume a holder could always exit at the last quote.
- Securities received through corporate actions outside the selection set are exited at the first feasible scheduled/mandatory event execution under the declared rules, without shorting or invented liquidity.

Unknown complex events are a data-quality exception. If they materially affect performance and cannot be resolved, the investment conclusion must remain provisional.

### 5.5 Missing securities and terminal outcomes

For known held positions with unresolved terminal values, report exposure and run explicit recovery scenarios, including zero recovery and a stated alternative grounded in available evidence. Label these scenario sensitivities.

They are not universal bounds on survivorship bias. Unknown missing historical members may include large winners; there is no model-free finite upper bound on their omitted returns. If membership identity itself is unresolved, report insufficient data for a clean full-universe claim.

Never remove problem names retrospectively based on their later failure. Do not let a suspended name vanish from holdings because its current price row is absent.

## 6. Signal and eligibility

Let t denote the calendar holding month. At the close of the last NSE session in t−1, calculate:

\[
M_{i,t}=\prod_{k=2}^{12}(1+r^{month}_{i,t-k})-1.
\]

There are eleven included monthly returns. For April 2015 holdings, include April 2014 through February 2015; exclude March 2015. Using month-end total-return indices, this is the February 2015 level divided by the March 2014 level, minus one.

Unit-test this date example explicitly. A “12-month momentum” label alone is insufficient to define the implementation.

Eligibility at formation requires:

1. Membership in NIFTY 500 on the formation date under the common-spine convention.
2. An identified NSE cash equity security and an auditable current trading status.
3. Every required signal month and its starting price/return anchor available at that time.
4. Positive finite lagged 20-session ADV.
5. At least 15 positive-volume sessions in the preceding 20 NSE sessions, and an executable recent quote.
6. No known suspension or unresolved price/identity error that prevents forming a valid signal.

All filters use contemporaneously available information. An unresolved historical input found during today's audit is not a tradable signal: report its data limitation separately.

Rank descending on M, breaking exact ties by permanent security_id. Select ceiling(10% of eligible names), equally weighted. Record every exclusion, selected count, and sector/size concentration where historically valid tags exist. No requirement that momentum itself be positive; adding that rule would introduce another strategy mechanism.

Recompute monthly only. Selection changes, drift corrections, index exits, and exposure changes all contribute to requested trades. There is no discretionary override after seeing market news.

## 7. Shadow portfolio, volatility estimate, and exposure

### 7.1 Why a separate shadow portfolio is needed

The risk signal should not shrink mechanically because the overlay already cut exposure. Maintain one gross, unscaled reference strategy that is independent of the overlay's holdings, transaction costs, taxes, and account size.

Construct its selected stocks historically using Section 6, with fractional units, no financing, no trading costs, and no capacity constraint. Rebalance at the same next-session opening reference as the main accounts. Between rebalances, weights drift with returns. Its total-return convention assumes reinvested distributions and must be consistent through the entire series.

At a rebalance open, old holdings earn the prior-close-to-open move; new holdings earn the open-to-close move. Do not apply the new month-end-selected weights to the prior day's close-to-close return. Split a day's return into the appropriate pre/post-trade valuation segments when needed.

The shadow is a reference return series, not a claim that fractional, costless trading was executable. Its differences from the cash ledger are reported explicitly.

Never compute shadow history by taking this month's chosen stocks and applying their weights to the preceding six months. That estimates a different, current-basket risk object rather than the historical strategy's realised risk.

### 7.2 Warm-up

Acquire prices from January 2013 as an initial margin. Begin historical shadow formation by August 2014, with the necessary eleven signal months and anchors. Before the March 2015 formation, require at least 126 genuinely observed shadow daily returns.

Count exchange sessions; six calendar months is not guaranteed to contain 126 sessions. Extend the shadow start and its input history earlier if necessary. Warm-up has no reported strategy performance and no real-account tax lots.

Do not start the reported April 2015 portfolio with an arbitrary volatility estimate. An incomplete warm-up fails the full-window data gate.

### 7.3 Estimator and cap

At each formation close d:

\[
\widehat{\sigma}_{d}^{2}=\frac{252}{126}\sum_{j=0}^{125}(r^{shadow}_{d-j})^2,\qquad
a_d=\min(1,0.12/\widehat{\sigma}_d).
\]

Use decimal returns, not percentages. This is a second-moment/realised-variance estimator, not the demeaned sample variance produced by a default rolling standard deviation. Keep the annualisation units of the target and estimate consistent.

- Missing, nonfinite, or nonpositive estimate: target cash and emit a visible data/error status. Do not divide by zero or silently substitute a future estimate.
- At low estimated volatility, a=1; the mandate prevents increasing exposure further.
- Hold the target exposure decision fixed until the next formation. Actual exposure drifts and can differ because of prices, capacity, settlement, and fees.
- The overlay cannot guarantee a maximum drawdown or realised volatility of 12%.

## 8. Accounts and controls

Run the same selected-stock list, execution engine, tax rules, and initial capital for every implementable account.

| ID | Account | Purpose |
|---|---|---|
| MOM | Unscaled momentum, target equity exposure 100% | Baseline investable opportunity. |
| VM | Momentum with the 12% / 126-session capped overlay | Primary proposed strategy. |
| FIX | Same momentum book with fixed equity allocation equal to mean monthly VM target exposure in the build window | Tests whether holding cash alone explains the result. |
| FIXVOL | Same book with a fixed allocation chosen on build data to match VM's gross reference volatility | Additional control for risk level rather than just exposure. |
| TRI | Published NIFTY 500 TRI | Market context only, not a tax-paid investable account. |

For FIX, freeze a_bar = arithmetic mean of valid scheduled monthly VM target exposures from April 2015–March 2023.

For FIXVOL, use c = min(1, sd(build VM gross reference daily returns) / sd(build MOM shadow daily returns)). With zero-return cash, this defines the scale of a fixed gross reference; execution, costs, and taxes mean realised account volatility will not match exactly. Report that mismatch.

FIX and FIXVOL use build information for calibration; their build-window comparisons are explicitly in-sample. Their allocations are then fixed for the entire holdout. Never match exposure or volatility using the holdout itself.

Re-run the build accounts for the frozen fixed controls to create their state snapshots. This is allowed build calibration, not an ex-ante claim that the controls were chosen in 2015.

Maintain three accounting views for MOM, VM, FIX, and FIXVOL:

1. Zero-friction reference wealth.
2. Executable account after costs, before capital-gains tax.
3. Executable account after costs and the assignment's capital-gains tax.

For exact financial drag decomposition, also maintain matched shadow valuations of the primary executed share path with fee/tax cash flows reversed. Separately re-running a costless account can alter quantities and future trades; its CAGR difference is not an exact additive fee total.

The TRI does not receive a fictional tax haircut. Compare gross strategy exposure with TRI for context, and use the actual accounts for implementable after-tax comparisons.

## 9. Execution and funding

### 9.1 Monthly sequence

1. After formation close: freeze selected names, a, targets, and the source-data timestamps.
2. Before the first execution session: create target notionals using current marked net NAV and selected equal weights.
3. At that session's opening reference, determine whole-share targets and order deltas. Opening quotes may only be used for execution sizing/affordability, not for changing signal ranks or the overlay.
4. Sell required reductions up to the participation cap and available settled share quantity.
5. Treat net sale proceeds as receivables until settlement. Do not finance same-day replacement purchases from them.
6. Buy toward the frozen targets with free settled cash after fees and reserved taxes.
7. Continue outstanding monthly orders for at most five sessions, retaining the original signal and adjusting mechanically for corporate actions.
8. Cancel remaining unfilled orders at the end of that window and report shortfall; unfilled sales remain held.

The next-open reference is a daily-bar execution approximation, not evidence of guaranteed opening-auction fills. State that limitation and apply the predeclared delayed-execution sensitivity.

### 9.2 Capacity

\[
ADV_{i,d-1}=\frac1{20}\sum_{j=1}^{20}V^{INR}_{i,d-j},\quad
p_{i,d}=\frac{q_{i,d}P^{reference}_{i,d}}{ADV_{i,d-1}}.
\]

Cap total one-side notional in that security/day, summed across all orders in that account, at 1% of ADV. No use of the day's final volume to justify the order before execution.

Include genuine zero-volume sessions in the ADV denominator. A missing file is not zero volume.

Orders are deterministic:

- Sales: mandatory exits first, then larger target excesses, then security_id.
- Purchases: allocate scarce available cash proportionately to remaining positive target deficits, floor to whole shares, then use any affordable residual in security_id order without exceeding the target or participation cap.
- Recalculate actual impact for the filled notional, not the requested order.
- At fill time, reduce quantity or reject an unaffordable purchase; never let a price gap create a negative cash balance.
- Never sell more shares than owned and available for delivery.

Volume-zero, missing-open, suspended, or evidenced locked-limit sessions do not fill. Where daily data cannot establish fillability at a price limit, use a conservative no-fill flag and report the limitation. A stale close cannot serve as an executable opening price.

### 9.3 Settlement and NAV

Buys debit full cash and fees at execution; their shares become available for sale only after the modelled settlement lag. Owned unsettled purchases remain market-risk assets. Sales remove economic stock exposure at execution and create net cash receivables. Receivables enter settled cash on their settlement dates.

Primary T+2 means two **settlement business days**, not two calendar days or necessarily two trading sessions.

\[
NAV = \text{stock market value}+\text{settled cash}+\text{receivables}
       -\text{unpaid accrued tax liability}.
\]

Tax-reserved cash is part of cash assets but unavailable for purchases. Avoid subtracting the reserve twice: subtract the tax liability from NAV once, and restrict free cash separately.

Maintain nonnegative free cash, nonnegative holdings, and equity exposure no greater than net NAV after all obligations and reservations. Fees must be included when solving purchase affordability.

## 10. Ledger contract and event order

### 10.1 Output tables

- signals: formation date, security_id, score, eligibility, rank, target weight, inputs_asof.
- exposure: date, shadow variance, target a, actual equity weight, cash/receivables, cap-binding flag.
- orders: order_id, account, decision timestamp, security_id, side, requested shares, target, expiration, reason.
- fills: order_id, fill date, quantity, raw reference, impacted fill price, lagged ADV, participation, each fee, settlement date.
- positions: date, account, security_id, settled/unsettled quantity, cost basis, raw/stale mark, market value.
- cash_events: account, timestamp, category, debit/credit, cash/receivable/reserve balance, source event.
- tax_lots: lot_id, security_id, acquisition date, quantity remaining, basis remaining, basis provenance.
- realised_gains: sale/lot IDs, holding duration, ST/LT class, taxable proceeds, allocated basis, gain/loss.
- tax_years: account, FY, gross ST/LT gains/losses, offsets, carry-forward by origin year, exemption used, tax accrued/paid.
- nav_daily: gross/net views, stocks, cash, receivables, tax liability, NAV, daily return, quality status.
- data_coverage: formation universe, price coverage, exclusions, unresolved events, affected selected weights.

All account-level tables include configuration hash and input-manifest hash.

### 10.2 Event order per date

1. Carry previous closing balances.
2. Apply effective share transformations and evidenced entitlements before the ex-date price move.
3. Settle due cash and share obligations; release only genuinely available amounts.
4. Process planned executions at the declared reference time.
5. Record fees and FIFO realised gains for fills.
6. Recompute year-to-date tax liability from immutable gains and opening loss pools.
7. Ring-fence tax resources and verify affordability/holdings invariants.
8. Mark stocks and receivables at the close, flag stale/unresolved values, and reconcile NAV.
9. Update the historical shadow return and features from data available by that close.
10. If month-end, generate the next monthly decisions.
11. If FY-end, finalise the tax year, commit loss pools, and settle the modelled tax payment when reserved cash is available.

On an unexpected corporate action or suspension, use the recorded event rules. Do not change the trading strategy because the outcome is inconvenient.

## 11. Transaction costs and the required hurdle arithmetic

### 11.1 Resolve the assignment's ambiguity openly

The fixed delivery charges sum to:

| Component, bps | Buy | Sell |
|---|---:|---:|
| STT | 10 | 10 |
| Stamp | 1.5 | 0 |
| Exchange | 0.297 | 0.297 |
| SEBI/GST aggregate | 0.13 | 0.13 |
| Fixed subtotal | 11.927 | 10.427 |

Interpreting the stated 10 bps spread/impact as **per side**, consistent with the table heading, gives 42.354 bps round trip at the minimum impact floor. Interpreting it as **round trip**, consistent with the printed approximate total, gives 32.354 bps.

Primary: use the conservative per-side interpretation and participation curve in Section 3. Sensitivity: use I0=5 bps with the same curve. If the desk clarifies, record the response and revise the choice before freezing. Do not silently choose the cheaper interpretation.

Brokerage is zero/excluded to follow the supplied stack. Do not add current broker rates or describe this prescribed stack as an exhaustive live brokerage quote.

Represent impact in the execution price:

- Buy fill = raw reference × (1 + I(p)/10,000).
- Sell fill = raw reference × (1 − I(p)/10,000).

Charge the fixed fees once on executed consideration. Do not subtract the same impact again as a fee. Maintain a separate diagnostic impact amount relative to the reference price.

The displayed 21.927/20.427 per-side and 42.354 round-trip sums are additive basis-point planning approximations. Fees charged on impacted consideration create small impact-times-fee cross terms relative to the raw reference. Preserve these in the ledger; do not force exact simulated cash differences to equal the rounded hurdle arithmetic.

### 11.2 Turnover and hurdle

For each trade, normalise bought and sold notionals by the account's contemporaneous pre-trade NAV. Sum over the reporting year:

\[
T^{gross}=\sum_d(B_d+S_d)/NAV_{d,pre},\qquad
T^{RT}=T^{gross}/2.
\]

State both conventions. A complete sale-and-repurchase of a one-unit book is roughly two units of gross turnover or one round-trip-equivalent unit.

Compute exact realised cost drag by summing actual fees and modelled impact normalised by pre-trade NAV. For the simplified planning approximation:

\[
\text{annual cost drag}\approx T^{RT}\times c^{RT}.
\]

Use a traded-notional-weighted effective round-trip cost for variable impact, with the buy/sell asymmetry disclosed. Do not multiply gross turnover by a round-trip rate.

Report this table for the main accounts, build first then holdout:

| Cadence | Actual gross turnover | RT-equivalent turnover | Effective RT cost | Annual cost drag | Incremental tax drag | Gross edge needed vs declared control | Observed gross edge | Clears hurdle? |
|---|---|---|---|---|---|---|---|---|

“Edge” must identify the comparator. For overlay VM versus FIX, the incremental net advantage equals gross advantage less the differences in costs/taxes, including path effects. The exact difference between after-tax account returns is authoritative; a turnover approximation is explanatory.

Show cash carry separately at its declared zero rate. Initial funding and final liquidation costs are reported separately from recurring turnover when annualising, and also included in actual wealth where executed.

## 12. Tax model

### 12.1 This is a declared research scenario

Apply the assignment's 20%/12.5% rates uniformly through the entire study. This intentionally does not reproduce changing historical Indian tax legislation. The [Income Tax Department's capital-gains summary](https://www.incometaxindia.gov.in/w/capital-gain) documents current rates and the historical rate-change context.

Assume one account, no external gains/losses, ₹1,25,000 annual LTCG exemption available to that account, and timely returns for loss carry-forward. Cess, surcharge, dividend-income tax, investor-specific tax status, and historical grandfathering are excluded. Label outputs “net of assignment capital-gains tax,” not universally applicable personal after-tax returns.

### 12.2 Lots and taxable gains

- Match sales FIFO, including partial lots.
- Acquire a distinct lot on each fill.
- Tax basis uses impacted acquisition consideration plus the modelled deductible purchase charges; STT is excluded from tax deductions. Use impacted sale consideration less deductible selling charges, again excluding STT.
- Keep the cash cost ledger separate from deductible tax costs.
- Classify by calendar anniversary, not a blanket 365-day threshold. A sale on the first anniversary is short-term in this declared convention; a later sale is long-term.
- Splits preserve original acquisition age and aggregate basis; bonuses and mergers use the explicit event conventions in Section 5.

No tax is levied merely because daily or monthly NAV increased. Taxes arise from realised lot gains.

### 12.3 Losses and annual computation

Maintain ST and LT losses separately by origin FY and expiry. Recompute the current FY provision from the gains ledger and opening loss pools, without repeatedly consuming the same loss when the provision is refreshed.

Deterministic offset convention:

1. Net current FY losses within their own ST/LT category.
2. Apply any remaining current ST loss to positive LT gains.
3. Apply brought-forward LT losses to remaining LT gains, oldest eligible origin first.
4. Apply brought-forward ST losses to remaining ST gains, then remaining LT gains, oldest eligible origin first.
5. Apply the annual LTCG exemption once to the resulting nonnegative LT amount.
6. Tax positive ST at 20% and LT above exemption at 12.5%.
7. At year-end, commit unused losses with their permitted future lifespan; expire after the eight succeeding financial years in the model.

LT losses never reduce ST gains. No loss is refunded as cash. Explain that the stated loss-use ordering is a model convention; do not pretend to solve every taxpayer-specific optimisation question.

Source for the categories and carry-forward principles: [Income Tax Department ITR-2 FAQ](https://www.incometax.gov.in/iec/foportal/help/FileITR-2Online-FAQ?mobile-app=1).

### 12.4 Provision, reserve, and payment

- Recompute liability after every taxable fill and at each month/FY end.
- Reserve the liability from settled cash or encumber corresponding sale receivables until settlement.
- Decreasing the current-year provision releases reserved resources; it is not a refund of a previously paid tax year.
- An annual payment decreases cash and the equal liability, leaving NAV unchanged at payment because the expense was already accrued.
- If resources cannot cover the obligation, stop new purchases and flag the funding problem; never invent outside capital.
- Record exact FY boundaries. Preserve lots, provisions, cash, and loss pools across March 2023.

### 12.5 Terminal wealth

Primary result: marked closing NAV with all realised-gain tax provisions, no artificial last-day liquidation.

Also compute liquidation-equivalent wealth at 31 March 2026: value remaining positions at the closing reference, apply declared hypothetical sale costs, realise remaining lot gains, and recompute the incremental tax without deducting existing provisions twice.

Label this a valuation sensitivity, not proof that all positions could be sold simultaneously at that price. Report estimated days required under the participation cap. If required liquidity extends beyond the sample, do not invent subsequent prices or call the hypothetical liquidation executable.

## 13. Build-window research and holdout isolation

### 13.1 Build workflow

Use the full build window for implementation and diagnosis, with chronological subperiods:

- April 2015–March 2019: initial implementation and mechanism diagnostics.
- April 2019–March 2023: temporal validation and stress investigation.

These are development partitions, not additional untouched holdouts. Record every viewed result and any design change in the experiment log. The default signal, target, and horizon come from the declared design; avoid a grid search for the highest Sharpe.

Study rolling risk and calendar subperiods. Any regime used to change trades must be defined using information available then; the primary strategy has no regime classifier. Ex-post event labels are descriptive only.

### 13.2 Holdout access contract

Before freeze, data acquisition may cache holdout files and perform mechanical schema/coverage validation without printing prices, returns, charts, rankings, strategy results, or performance-driven diagnostics. Keep the value files separate from development loaders.

Use synthetic examples and pre-April-2023 data for strategy debugging. Changes in the 2024 file format can be addressed from published schemas and non-performance validation.

A holdout loader refuses access unless a signed/finalised research freeze manifest exists. The manifest contains:

- Code revision or complete source hash.
- Dependency lock hash.
- Configuration and all comparison/sensitivity definitions.
- Input manifest and known-data-issues register.
- Fixed-control allocations.
- State snapshots at 31 March 2023 for every account.
- Metrics, bootstrap settings, comparison order, decision criteria, and chart templates.

“Touched once” means no adaptive learning from holdout performance. During the single frozen evaluation, the fixed algorithm may update its rolling signal and volatility estimates using data available at each successive holdout date. That is ordinary deployment, not retuning.

Run the complete predeclared account/sensitivity bundle in one holdout evaluation event. No selecting the best variant afterward.

### 13.3 Boundary continuity

Do not sell everything, reset cost bases, forgive tax, reset carry-forward losses, or set volatility to an arbitrary starting value on 1 April 2023.

Each account continues from its own build closing state. Report holdout returns normalised to that account's opening holdout NAV; document the inherited positions and tax state.

A same-start-cash holdout comparison is optional future work, not a silent replacement for the continuous account experiment.

### 13.4 Bugs after unsealing

If a material bug is discovered, stop. Preserve the original run, write the failure and repair, and label the subsequent result as evaluated after holdout exposure. A necessary correction is preferable to knowingly wrong results, but the holdout cannot be made untouched again.

Do not conceal reruns or change economic choices under the label “bug fix.” Deterministic reproduction of an already frozen result is different from retuning.

## 14. Metrics, attribution, and statistical inference

### 14.1 Required output order

1. Data coverage and caveats.
2. Turnover/cost/tax hurdle table.
3. Gross, cost-net, and assignment-tax-net outcomes.
4. Mechanism and control comparisons.
5. Uncertainty, failure analysis, and decision.

### 14.2 Account metrics

- Terminal NAV and CAGR using actual elapsed calendar years.
- Annualised daily volatility using 252 sessions; also monthly-return volatility for comparison.
- Cash-relative Sharpe with the explicitly assumed 0% cash return; do not describe this as a current Treasury-bill-excess Sharpe.
- Maximum drawdown from a daily wealth series and its start/trough/recovery dates; unrecovered drawdowns remain unrecovered.
- Worst day and month, historical 95% daily expected shortfall, and negative skewness as descriptive estimates.
- Average/maximum equity exposure, cash, receivables, and frequency of exposure-cap binding.
- Selected-name count, effective number of holdings = 1/sum(weights²) within equity, and largest position.
- Turnover, cost components, realised ST/LT gains, tax provision/payment, and liquidation-equivalent wealth.
- Fill rate, unfilled buys/sells, participation distribution, stale/unpriced holdings, and estimated exit time.
- Market beta and active returns relative to TRI as descriptive exposure diagnostics.

Sharpe of an all-cash zero-return account is undefined, not zero or infinity. Use sample standard deviation for performance volatility; do not confuse that convention with the risk estimator's root mean square.

### 14.3 Mechanism diagnostics

At each formation, predict the next month's shadow variance:

\[
\widehat V_{t+1}=n_{t+1}\frac1{126}\sum_{j=0}^{125}(r^{shadow}_{d-j})^2.
\]

The exact future session count is used only when evaluating the monthly forecast, not as unknown price information in trading. Realised monthly variance is the sum of squared shadow daily returns over that month.

Report:

- Forecast-versus-realised variance plot and rank correlation.
- Calibration slope/intercept with uncertainty, interpreted cautiously.
- QLIKE loss, using a tiny positive numerical floor such as 1e−12 for variance.
- Comparison against a simple expanding historical mean variance forecast constructed only from prior observations.
- Whether high forecast-risk months also have different subsequent returns; do not equate correlation with causal evidence.
- Frequency and duration of a=1 and the distribution of a<1.
- Market declines/rebounds where the overlay reduced losses or missed recovery.

The forecaster's performance is a diagnostic of C's premise, not a separate traded strategy.

For implementation, use QLIKE = log(max(forecast_variance, 1e−12)) + realised_variance / max(forecast_variance, 1e−12), consistently for both forecasts. Compare mean losses on exactly the same months; lower is better. This form remains defined when realised variance is zero. The expanding comparator is the mean of all observed shadow daily squared returns from shadow inception through formation, multiplied by the evaluated month's session count. Use Spearman rank correlation and OLS realised_variance = intercept + slope × forecast_variance, with six-lag HAC errors for the monthly calibration diagnostic. These are supporting diagnostics, not extra criteria for selecting a different trading rule.

### 14.4 Separate exposure from timing

For the same gross reference return stream r_t and constant c:

\[
r^{VM}_t-r^{fixed}_t=(a_{t-1}-c)r_t
\]

under the explicitly simplified zero-cash, common-return convention. Use the daily applicable target/exposure timing consistently. Real implementable paths additionally differ through drift, fills, costs, and tax.

Report VM−MOM, VM−FIX, and VM−FIXVOL separately. A lower drawdown relative to MOM with no advantage over fixed controls supports a “cash reduction explains much of the benefit” interpretation.

A simple monthly regression of VM excess returns on MOM excess returns may be reported with HAC errors as a diagnostic of return beyond fixed scaling. It is not a complete asset-pricing proof or evidence of causality.

### 14.5 Uncertainty

- Bootstrap monthly return vectors jointly across accounts, preserving comparison pairing and six-month blocks.
- Use 5,000 draws, seed 20260914, percentile 95% intervals for mean active return and difference in monthly-based Sharpe.
- For each bootstrap sample, use all paired months and the same cost/tax-net return series; do not independently resample each strategy.
- This resamples realised account-return outcomes. It does not re-run tax laws on synthetic calendar histories. State that limitation.
- For monthly mean/regression diagnostics, use HAC/Newey–West with six lags and clearly state the convention.
- Three-year holdout means about 36 monthly observations; block intervals will be uncertain. Do not treat hundreds of stocks as hundreds of independent portfolio histories.
- Maximum drawdown and historical expected shortfall are path/tail statistics with few extreme observations. Report them descriptively; do not claim a small sample proves crash protection.
- If giving multiple exploratory p-values, disclose multiplicity. Primary inference is VM versus FIX; other comparisons support interpretation.

Implementation details: for n aligned months, draw ceiling(n/6) starting indices uniformly with replacement from 0 through n−1. Each start contributes six consecutive indices modulo n; concatenate and truncate to n. Apply that index vector to every account column. Compute monthly mean active return and annualised descriptive Sharpe = sqrt(12) × monthly mean / sample monthly standard deviation, using the declared zero-return cash convention. The Sharpe interval is for the difference of these descriptive statistics, not a claim that square-root annualisation removes serial dependence. Report mean-active-return intervals in monthly percentage points; any ×12 display is an annualised arithmetic mean, not CAGR. Use Bartlett weights and the finite-sample correction for HAC, and record those options. If a sample has zero return variance, mark its Sharpe undefined, report the number of invalid draws, and omit the Sharpe interval if it cannot be computed reliably rather than replacing undefined values with zero.

## 15. Predeclared sensitivities and scope control

Core accounts are MOM, VM, FIX, and FIXVOL. Predeclare a small one-at-a-time sensitivity bundle:

| Sensitivity | Change | Question |
|---|---|---|
| Cost ambiguity | I0 10 → 5 bps, same impact curve | Does interpretation of the supplied table change the decision? |
| Higher impact | Double impact component only | Is the conclusion fragile to the uncalibrated impact curve? |
| Smaller participation | 1% → 0.5% ADV daily cap | Does less executable liquidity remove the benefit? |
| Larger account | ₹1 crore → ₹5 crore, same rules and allowance | How do capacity and the fixed rupee tax exemption affect outcomes? |
| Later execution | Delay the first reference execution by one NSE session | Does an optimistic timing convention drive the result? |
| Risk-horizon diagnostic, build only | 126 → 63 and 252 sessions | Is the chosen risk horizon operating in a broad sensible region? |

For paired sensitivities, run the relevant comparator under the same changed execution/tax assumptions. Freeze fixed-control allocations from the primary build; do not recalibrate them to each holdout outcome.

The 63/252 comparisons remain build diagnostics, not a menu from which to pick a winning holdout strategy. No full cross-product of settings. Report every predeclared sensitivity, including unfavourable ones.

The 252-session diagnostic needs more warm-up than the primary account. Either extend the evidenced historical shadow sufficiently far back, or compare all three horizons on the common build-only subperiod beginning when all have valid history. Label the latter dates explicitly and rerun the primary comparison on the identical subperiod. Do not fill the early 252-session estimates with shorter windows or compare unequal scored periods.

If time is short, finish correct core accounting and controls before optional additional figures or model variants. Never drop the mandate, data integrity, taxes, or holdout discipline to make the schedule.

## 16. Decision rule and failure analysis

Before unsealing, write the chosen interpretation of “worth running.” Use the following default classification; these are research decision conventions, not desk-approved investment policy.

### 16.1 Classification

**Not evaluable under the full mandate**

- Historical membership/identity or material terminal outcomes remain unresolved enough to invalidate the claimed universe or wealth path.
- Funding, fees, settlement, or tax cannot be reconciled.

**Reject the overlay / no demonstrated added value**

- After prescribed costs and taxes, VM is dominated by a fixed control in return and risk on the relevant evidence, or its apparent benefit disappears under modest predeclared frictions.
- The incremental gross advantage fails to cover the measured incremental implementation burden.
- Any improvement rests on a data error, unexecutable trade, or unstated short/leverage assumption.

**Inconclusive / do not allocate yet**

- Point estimates are favourable but uncertainty is wide, benefits are concentrated in very few episodes, or conclusions reverse across reasonable sensitivities.
- VM improves drawdown but materially sacrifices return, and no investor risk preference was supplied to establish that trade-off as superior.

**Promising enough for forward paper trading**

- The core data/accounting gates pass.
- VM has favourable after-tax risk-adjusted evidence against fixed controls, with clearly reported return trade-offs.
- Incremental economic benefits survive the principal implementation sensitivities.
- Findings are not adequately explained by one outlier, cash allocation alone, or an unresolved data problem.

Even the last outcome is not approval to deploy real capital. A three-year holdout cannot establish permanent reliability.

### 16.2 Failure modes to investigate explicitly

- The removed short leg was central to the original result.
- Equity beta dominates the long-only portfolio.
- The cap prevents exposure increases in calm periods, making the overlay mostly de-risking.
- Volatility forecasts react after a fall and keep exposure low during a fast rebound.
- Lower raw risk produces lower returns without better risk-adjusted or utility outcomes.
- High turnover, exposure changes, or taxes overwhelm the signal.
- The strategy concentrates in a sector or illiquid names.
- Stale prices make both signal and estimated volatility look better than reality.
- Circuit limits, suspensions, or settlement delays prevent desired exits.
- Results depend on a single stress episode or on incomplete early history.

### 16.3 Forward monitoring proposal

Propose, but do not implement as backtested discretionary exits:

- Data-integrity failure or negative free cash: pause new trading immediately.
- Participation/order-size breach: block the offending order.
- Missing trustworthy risk estimate: target cash through feasible execution and disclose any unfilled exits.
- Monthly review of realised versus forecast risk, exposure-cap binding, fill shortfall, modelled versus observed costs, and active performance against FIX.
- Any numerical performance stop-loss or deterioration threshold requires prospective desk agreement. Do not invent one after inspecting drawdowns.

## 17. Software architecture and reproducibility

Keep a small Python package with explicit data contracts and one ledger engine. A dashboard is unnecessary.

~~~text
brindco/
  plan.md
  resources.md
  README.md
  pyproject.toml
  requirements.lock.txt
  config/
    primary.yaml
    sensitivities.yaml
  data/
    raw/                   # immutable, manifest-controlled
    interim/               # parsed exchange objects
    processed/             # normalised tables
    sealed_holdout/        # separately controlled access
    manual_overrides/      # evidence-backed corrections
    manifest.json
  src/brindco_momentum/
    __init__.py
    __main__.py            # delegates module execution to cli.main()
    cli.py
    config.py
    provenance.py
    calendar.py
    identifiers.py
    membership.py
    prices.py
    corporate_actions.py
    quality.py
    features.py
    shadow.py
    execution.py
    ledger.py
    costs.py
    taxes.py
    backtest.py
    controls.py
    metrics.py
    inference.py
    reporting.py
    freeze.py
  tests/
    fixtures/
    test_dates_and_membership.py
    test_actions_and_identity.py
    test_execution_and_cash.py
    test_costs_and_turnover.py
    test_tax_lots.py
    test_shadow_and_risk.py
    test_holdout_boundary.py
    test_reproduction.py
  research/
    hypothesis.md
    data_feasibility.md
    data_issues.csv
    experiment_log.csv
    deviations.md
    freeze_manifest.json
  output/
    build/
    holdout/
    tables/
    figures/
    memo.pdf
    submission_manifest.json
~~~

Use Python 3.12, NumPy/pandas, SciPy/statsmodels for inference where needed, Matplotlib for static figures, pytest, and YAML or JSON configuration. CSV plus explicit schemas is an acceptable portable storage baseline; Parquet is optional and requires a pinned engine. Do not add a database, workflow service, web UI, or cloud platform.

At implementation setup, install a mutually compatible environment, run the synthetic tests, then freeze **exact** tested direct and transitive versions into requirements.lock.txt. Do not put untested guessed pins in the plan and claim they work. After freeze, no unrecorded package upgrades.

The configuration file must hold every parameter in Section 3 and every sensitivity in Section 15. Economic constants must not be hidden in notebook cells. Validate ranges and incompatible settings on startup.

### 17.1 Command-line contract to implement

The following Windows PowerShell commands are the target interface, not commands that already exist. They assume the implemented package, configuration, and tested lock file are present:

~~~text
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest

.\.venv\Scripts\python.exe -m brindco_momentum data sample --config config/primary.yaml
.\.venv\Scripts\python.exe -m brindco_momentum data fetch --config config/primary.yaml
.\.venv\Scripts\python.exe -m brindco_momentum data validate --config config/primary.yaml
.\.venv\Scripts\python.exe -m brindco_momentum build --config config/primary.yaml
.\.venv\Scripts\python.exe -m brindco_momentum freeze --config config/primary.yaml
.\.venv\Scripts\python.exe -m brindco_momentum holdout --freeze research/freeze_manifest.json
.\.venv\Scripts\python.exe -m brindco_momentum report --freeze research/freeze_manifest.json
.\.venv\Scripts\python.exe -m brindco_momentum verify --freeze research/freeze_manifest.json
.\.venv\Scripts\python.exe -m brindco_momentum package --freeze research/freeze_manifest.json
~~~

Declare the src package layout and build backend in pyproject.toml; include the tested build-backend dependencies in the lock file so the no-build-isolation installation succeeds. The local editable package is installed separately; remove machine-specific editable paths from the third-party dependency lock. For macOS/Linux, use .venv/bin/python in place of the Windows environment interpreter. In the final README, demonstrate the exact successful sequence on the tested platform. Make paths relative to the repository root using pathlib. Never depend on the planner's local runtime path.

“build” cannot read sealed holdout values. “holdout” checks code/config/input hashes, writes an immutable evaluation ID, and rejects silent overwrites. A deliberate reproduction command may rerun the same frozen inputs while checking identical outputs.

Use source control if available; otherwise hash all source files. The submission should still explain every command without requiring knowledge of this conversation.

## 18. Verification: minimum meaningful tests

Tests must establish financial and temporal correctness, not just mirror the implementation.

1. **Momentum calendar:** April 2015 uses April 2014–February 2015 and excludes March 2015.
2. **Availability:** changing any price after a decision date cannot change that earlier signal/order.
3. **Index timing:** announced-but-not-effective member is excluded; effective member is included.
4. **Identity:** a rename preserves identity; a merger does not splice an unrelated predecessor return path.
5. **Split:** 100 shares at ₹100 become 200 at ₹50 with unchanged wealth and aggregate basis.
6. **Dividend:** raw ex-dividend price plus receivable preserves the appropriate wealth; no double counting in adjusted-return mode.
7. **Bonus:** original lots retain basis/age; new bonus lots have separately modelled basis/age.
8. **Terminal event:** merger/delisting consideration enters cash/shares on the correct dates; missing history does not erase the holding.
9. **Drift:** a stock that appreciates changes pre-trade weights before the next rebalance.
10. **Errata:** changing exposure with unchanged selections causes turnover; scaling is multiplication, not division.
11. **Cost stack:** verify the additive 21.927/20.427 and 42.354 bps hurdle arithmetic separately from exact cash fills; test fees on impacted consideration and their small cross terms.
12. **Turnover factor two:** a full book sale and replacement produces gross turnover two, RT-equivalent one.
13. **Liquidity:** a ₹10 lakh ADV and 1% cap permits at most ₹10,000 reference notional that day, subject to whole shares.
14. **No same-day funding:** unsettled sale proceeds cannot fund a replacement purchase.
15. **Settlement calendar:** holidays extend settlement; trading and settlement calendars are not assumed identical.
16. **Gap/cash constraint:** adverse opening gap reduces/rejects a purchase without negative free cash.
17. **Blocked exit:** a suspended holding remains marked and exposed; it does not become cash.
18. **FIFO partial sale:** sale uses the oldest available lots and leaves exact remaining basis.
19. **Tax anniversary:** sale on/beyond the calendar anniversary gets the declared class, including leap-year cases.
20. **Loss offsets:** LT loss cannot offset ST gain; ST loss can offset the declared eligible categories; carry-forward is not consumed twice during provision updates.
21. **Annual exemption:** ₹1,25,000 is applied once per account/FY, never per stock or sale.
22. **Tax NAV:** paying an already-accrued liability changes cash and liability equally, without charging the tax twice.
23. **Terminal sensitivity:** unrealised gains incur only incremental hypothetical tax; existing provisions are not subtracted again.
24. **Risk estimator:** constant daily returns produce the RMS estimator, illustrating the difference from demeaned standard deviation; cap, zero variance, and missing history behave as specified.
25. **Shadow chronology:** historical holdings change only on their actual past rebalance dates; new weights do not earn prior close-to-open moves.
26. **Holdout boundary:** continuation from saved March 2023 state equals a continuous run with the same frozen rules.
27. **Reproducibility:** identical inputs/config/seeds produce identical tables and numeric results.

Also hand-audit at least three actual build-window rebalances: an ordinary month, a stress month, and a month involving a corporate event or major exposure change. Reconcile shares, cash, fees, taxes, and NAV to an independent small worksheet or hand calculation.

Do not use holdout strategy returns to debug these tests.

## 19. Memo and submission design

Use exactly five pages at most. A recommended page allocation:

1. **Question and verdict:** mechanism, constrained adaptation, main conclusion, data caveat, compact hurdle arithmetic.
2. **Construction:** universe, timing diagram, signal, exposure equation, execution/cost/tax assumptions, deviation table.
3. **Results:** build then holdout table, gross/cost-net/tax-net, accounts and fixed controls, one cumulative-wealth/drawdown figure.
4. **Does the mechanism survive?:** risk forecast evidence, cash-control comparison, exposure/cost/tax attribution, core sensitivities and uncertainty.
5. **Failure and decision:** reasons to reject or remain inconclusive, data limitations, implementation constraints, monitoring, and four-week improvement priorities.

Keep tables readable; do not compress six pages into illegible type. The appendix may contain detailed outputs, but anything essential to the verdict belongs in the scored five pages.

Generate static figures with reproducible code. Render the PDF and visually check every page, labels, table widths, page count, and source notes before final submission.

README must include:

- Paper/version and errata link.
- Research question and one-paragraph mechanism.
- Exact environment and run commands.
- Source list, input hashes, coverage, and redistribution/acquisition instructions.
- Default configuration and deviations, especially costs, taxes, long-only adaptation, and settlement.
- Holdout freeze/evaluation history and any bug corrections.
- AI-assistance disclosure and independent-code statement.
- Result reproduction instructions and the five-page memo path.
- Known limitations and what remains unverified.

Package only necessary code, approved data/cache assets, lock file, manifest, memo, and supporting outputs. Exclude credentials, personal filesystem paths, virtual environments, and unexplained scratch outputs. Do not automatically publish or send the submission.

## 20. Seven-day execution and learning schedule

This is a target workload, not a guarantee. Data reconstruction is the dominant uncertainty. Reserve meaningful time for explanation and review instead of spending the final day adding features.

| Day | Build deliverable | Learning/defence deliverable | Exit criterion |
|---|---|---|---|
| 1 | Data feasibility report; source samples; hypothesis and deviations draft | Read C twice in focused passes and its errata; explain mechanism and mandate changes | Credible early membership/price route and adequate warm-up; otherwise surface the blocker |
| 2 | Normalised build data, identities, actions, calendar, eligibility and basic shadow | Hand-work momentum dates, total returns, corporate actions | Auditable input tables and no unexplained material events in the sampled checks |
| 3 | Shared execution/ledger, costs, FIFO tax, invariants and synthetic tests | Work one full rebalance and tax year by hand | Self-financing accounts reconcile; core correctness tests pass |
| 4 | VM/MOM and fixed controls; build diagnostics, forecast evaluation | Explain RMS risk, cap, drift, cash controls, settlement and turnover | Complete build results from the correct ledger, not only vectorised return multiplication |
| 5 | Predeclared sensitivities, data audit completion, freeze manifest | Review uncertainty and alternative explanations; practise adversarial questions | No unresolved critical data/accounting issue hidden by the freeze |
| 6 | Single frozen holdout bundle; memo, figures, reproducibility run | Explain unfavourable results without changing the strategy | Results and limitations written, memo ≤5 pages |
| 7 | Final verification, package, no feature expansion | Two mock interviews; derive equations and explain any sampled function | Candidate can defend all submitted parts; any unexplainable optional component is removed before finalisation |

If day-one data feasibility fails, revise the calendar openly. If construction takes longer, use the remaining official assignment allowance if available; do not claim a rushed unverified result is “bulletproof.”

## 21. Future improvements, explicitly outside the core submission

Future work must use a fresh forward sample for confirmatory claims. After the holdout is opened, it becomes historical development data for subsequent versions.

### 21.1 First additional week: strengthen evidence and implementation

- Complete independent historical-membership reconciliation and unresolved corporate-event research.
- Replace uniform settlement lag with verified historical security-specific schedules.
- Improve treatment of limits, auction fills, trading status, entitlement payments, and actual execution availability.
- Obtain a second public price/action source and reconcile material differences.
- Expand reproducibility checks on another machine and persist source snapshots where redistribution is permitted.

### 21.2 Weeks two to four: test the main economic uncertainties

- Calibrate impact using an appropriate independently obtained dataset or actual paper-trading fills; do not claim a planning curve is empirical.
- Test a limited turnover buffer or partial rebalance, with clear deviation and a new validation protocol.
- Compare alternative risk estimators, such as EWMA, against the fixed 126-session estimate using chronological evaluation.
- Examine whether a risk signal based on the actual implementable book improves forecasts, while preventing feedback from the overlay itself.
- Study sector/size exposures with trustworthy point-in-time classifications.
- Add investor-specific dividend tax, surcharge/cess, actual historical tax scenarios, and more complete corporate-action tax rules if required.
- Use an actually investable cash instrument only after checking mandate eligibility, dates, execution, and taxes.

### 21.3 Longer-term developments

- Prospective paper trading with an immutable monthly decision log and observed fills.
- A proper capacity curve over book sizes, realistic liquidation time, and stressed market depth.
- Better separation of beta timing, momentum-specific risk, and common market volatility.
- Hierarchical uncertainty or richer portfolio risk models only after the simpler mechanism is established.
- Independent implementation review and a fresh untouched evaluation window.

Adding ML, foundation models, text signals, or another paper's strategy is a separate project, not a necessary improvement to this submission.

## 22. Handoff checklist for the next human or AI

Before writing strategy code:

- Read the assignment and resources.md.
- Verify the original paper and errata.
- Write the two-to-three-sentence mechanism in your own words.
- Run the data feasibility gate and record what is actually downloadable.
- Accept or deliberately amend the fixed specification, with rationale, before viewing results.

Before opening holdout:

- All data and ledger gates passed or limitations explicitly prevent a full claim.
- Baselines, sensitivities, metrics, and decision rules frozen.
- Costs, tax lots, settlement, corporate events, and timing independently checked.
- State snapshots and input/code/dependency hashes preserved.

Before submission:

- Every claim traces to a table, calculation, or named assumption.
- All required windows, constraints, arithmetic, and disclosures are present.
- No fabricated result, unverified completeness claim, hidden rerun, or future information.
- Exactly one paper's core strategy; memo at most five pages.
- Clean reproduction passes, and the candidate can explain the work without this plan.
