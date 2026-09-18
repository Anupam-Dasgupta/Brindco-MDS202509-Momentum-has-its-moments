# Development evaluation notes

All return and performance results use 2015-04-01 through 2023-03-31 only.
Account NAV is the frozen after-cost, after-tax executable path. TRI is a
published index used for context, with no fictional tax or transaction costs.
Its 2015-03-31 close is the anchor for its first development-session return.

Zero-friction reference wealth compounds the frozen MOM modelling-shadow daily
returns at 100%, or the frozen VM monthly target, FIX constant, or FIXVOL
constant times those daily returns. Cash earns zero. This reference does not
model execution or tax. The frozen FIXVOL first-session holding-month exposure
convention is retained.

The matched executable before-tax view adds back accrued capital-gains tax and
tax already paid to the *same executed share path*. FY-end tax payment occurs
after that day's closing NAV, so paid tax is added beginning the next session.
The matched cost/tax-reversed view additionally adds back cumulative recorded
fees and impact as non-invested cash. These are exact cash-flow reversals for
the realised shares and fills, not counterfactual reruns with different trades.
Cost drag is its CAGR minus the matched before-tax CAGR; tax drag is matched
before-tax CAGR minus frozen after-tax CAGR. Both include the initial trades.
Gross edge and hurdle in cost_arithmetic.csv are explicitly relative to 0%
cash using the matched cost/tax-reversed path; this is not an alpha estimate.
The separately saved zero-friction reference also reflects selection and
execution-path differences, so its gap to NAV is not labelled fee drag.
FIX and FIXVOL use constants calibrated on this full development period;
their development comparisons are in-sample controls, not 2015 forecasts.

Executed traded notionals, fees, and participation-dependent impact come from
the fill ledger. Annual recurring gross turnover sums consideration divided by
the latest recorded *previous-close* NAV on each trade day, then multiplies by
252 / 1,982. The first five NSE sessions' funding trades are excluded from
that recurring rate and reported separately. The frozen ledger has no
open-marked contemporaneous pre-trade NAV, so this is a labelled operational
turnover measure, not the exact intraday denominator specified in plan.md.
RT-equivalent turnover is half gross turnover. The weighted effective RT cost
is twice total actual fees-plus-impact divided by total executed consideration;
buy and sell rates are shown separately.

CAGR uses 365.2425-day elapsed calendar years from inception. Annualised
volatility is the sample standard deviation of 1,982 daily returns times
sqrt(252). Sharpe uses daily arithmetic mean / daily sample standard
deviation times sqrt(252) against the declared 0% cash return; zero variance
is undefined. Drawdown starts from initial funded wealth, and recovery is the
first later close at or above the previous peak. Unrecovered episodes have an
empty recovery date. Daily NAV may exclude live unpriced rights or fractional
claims under the frozen account convention; nav_status_counts.csv preserves
the exact counts by strategy. These valuations remain unresolved in the
frozen account scenario and limit interpretation of the results. No parameter
or frozen account artifact is changed here.
